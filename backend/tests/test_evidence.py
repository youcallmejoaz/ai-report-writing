import pytest

from app.domain.schemas import ConflictStatus, FactStatus
from app.pipeline.evidence import EvidenceError
from tests.conftest import ROOT, upload_samples


@pytest.fixture
def case(service, users, pack):
    case = service.create_case(users["alice"], client_ref="CRM-1", team="north", template_pack_id=pack.id)
    upload_samples(service, users["alice"], case.id)
    return case


def test_duplicate_values_merge_with_all_citations(service, case):
    record = service.store.records[case.id]
    dob = record.facts_for_key("client.date_of_birth")
    assert len(dob) == 1 and len(dob[0].sources) == 2  # "14/07/1968" and "14 July 1968" agree


def test_conflicting_values_create_conflict(service, case, users):
    record = service.store.records[case.id]
    assert [c.key for c in record.conflicts] == ["pension.fund_value"]
    assert record.usable_fact("pension.fund_value") is None
    with pytest.raises(EvidenceError):
        service.verify_fact(users["alice"], case.id, record.conflicts[0].candidate_fact_ids[0])


def test_gaps_from_template_requirements(service, case):
    gaps = {g.key for g in service.store.records[case.id].gaps}
    assert {"client.capacity_for_loss", "adviser.recommendation", "adviser.reasons"} <= gaps


def test_resolution_requires_reason_and_rejects_other_candidates(service, case, users):
    record = service.store.records[case.id]
    conflict = record.conflicts[0]
    with pytest.raises(EvidenceError):
        service.resolve_conflict(users["alice"], case.id, conflict.id, conflict.candidate_fact_ids[0], " ")
    service.resolve_conflict(users["alice"], case.id, conflict.id, conflict.candidate_fact_ids[1], "newer")
    assert record.fact(conflict.candidate_fact_ids[0]).status is FactStatus.REJECTED
    assert record.usable_fact("pension.fund_value").id == conflict.candidate_fact_ids[1]


def test_rebuild_keeps_human_decisions(service, case, users):
    record = service.store.records[case.id]
    conflict = record.conflicts[0]
    name = record.facts_for_key("client.name")[0]
    service.verify_fact(users["alice"], case.id, name.id)
    service.resolve_conflict(users["alice"], case.id, conflict.id, conflict.candidate_fact_ids[1], "newer")
    service.adviser_input(users["aaron"], case.id, "adviser.reasons", "Lower charges")

    # another document arrives; the record is rebuilt from all extractions
    service.upload_document(users["alice"], case.id, "statement_copy.txt",
                            (ROOT / "samples" / "pension_statement.txt").read_bytes())
    rebuilt = service.store.records[case.id]
    assert rebuilt.revision > record.revision
    assert rebuilt.fact(name.id).status is FactStatus.VERIFIED
    assert rebuilt.conflicts[0].status is ConflictStatus.RESOLVED
    assert rebuilt.usable_fact("adviser.reasons") is not None


def test_adviser_input_cannot_override_documentary_evidence(service, case, users):
    with pytest.raises(EvidenceError):
        service.adviser_input(users["alice"], case.id, "client.attitude_to_risk", "Adventurous")


def test_recommendation_only_from_adviser(service, case, users):
    with pytest.raises(PermissionError):
        service.adviser_input(users["alice"], case.id, "adviser.recommendation", "Transfer")
