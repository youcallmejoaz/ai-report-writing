import pytest

from app.domain.schemas import Statement
from app.llm.client import ScriptedLLMClient
from app.pipeline.draft import DraftingBlocked, LLMDraftingModel, draft_report
from app.pipeline.verify import LLMEntailmentChecker, verify_statements
from tests.conftest import GOOD_DRAFTS, make_service, prepare_ready_case, upload_samples


def codes(findings):
    return {f.code for f in findings}


def test_drafting_blocked_while_conflict_open(service, users, pack):
    case = service.create_case(users["alice"], client_ref="CRM-1", team="north", template_pack_id=pack.id)
    upload_samples(service, users["alice"], case.id)
    with pytest.raises(DraftingBlocked, match="pension.fund_value"):
        service.generate_report(users["alice"], case.id)


def test_missing_required_facts_produce_blocking_insufficient_evidence(service, users, pack, catalogue):
    case = prepare_ready_case(service, users, pack.id)
    record = service.store.records[case.id]
    reasons = record.usable_fact("adviser.reasons")
    reasons.status = "rejected"
    statements, _ = draft_report(pack, record, service.drafter, catalogue)
    rec = [s for s in statements if s.slot_id == "recommendation_explanation"]
    assert len(rec) == 1 and rec[0].insufficient_evidence and "Reasons for recommendation" in rec[0].text
    findings, _ = verify_statements(statements, record, pack, catalogue)
    assert "INSUFFICIENT_EVIDENCE" in codes(findings)


def test_good_draft_has_no_blocking_findings(service, users, pack):
    case = prepare_ready_case(service, users, pack.id)
    report = service.generate_report(users["alice"], case.id)
    assert report.open_blocking_findings == []
    assert report.template_hash == pack.content_hash


@pytest.mark.parametrize(
    "text,keys,expected",
    [
        ("You want to retire early.", [], "UNCITED_STATEMENT"),
        ("You intend to retire at 60.", ["client.retirement_age_target"], "UNSUPPORTED_FIGURE"),
        ("Valued at £125,400.00 on 1 April 2026.", ["pension.fund_value", "pension.valuation_date"],
         "UNSUPPORTED_DATE"),
        ("Your pension growth is guaranteed.", ["client.objectives"], "PROHIBITED_PHRASE"),
        ("You want lower charges.", ["client.no_such_key"], "UNKNOWN_FACT"),
    ],
)
def test_verifier_catches_unsupported_content(catalogue, registry, users, pack, text, keys, expected):
    drafts = dict(GOOD_DRAFTS, objectives_summary=[(text, keys)])
    svc = make_service(catalogue, registry, drafts)
    case = prepare_ready_case(svc, users, pack.id)
    report = svc.generate_report(users["alice"], case.id)
    assert expected in codes(report.open_blocking_findings)


def test_fact_outside_slot_allow_list_is_blocked(service, users, pack, catalogue):
    """E.g. a preparer edit citing income in the objectives section, where the template forbids it."""
    case = prepare_ready_case(service, users, pack.id)
    record = service.store.records[case.id]
    income = record.usable_fact("client.annual_income")
    s = Statement(slot_id="objectives_summary", text="Your income is £68,500.00.", fact_ids=[income.id])
    findings, _ = verify_statements([s], record, pack, catalogue)
    assert codes(findings) == {"FACT_NOT_ALLOWED"}


def test_unverified_fact_cannot_be_cited(service, users, pack, catalogue):
    case = prepare_ready_case(service, users, pack.id)
    record = service.store.records[case.id]
    fact = record.usable_fact("client.objectives")
    fact.status = "extracted"
    s = Statement(slot_id="objectives_summary", text="You want lower charges.", fact_ids=[fact.id])
    findings, _ = verify_statements([s], record, pack, catalogue)
    assert "FACT_NOT_VERIFIED" in codes(findings)


def test_entailment_check_flags_embellishment(service, users, pack, catalogue):
    case = prepare_ready_case(service, users, pack.id)
    record = service.store.records[case.id]
    fact = record.usable_fact("client.capacity_for_loss")
    s = Statement(slot_id="risk_summary", fact_ids=[fact.id],
                  text="Your capacity for loss is high because your other income covers your needs.")
    llm = ScriptedLLMClient([{"supported": False, "explanation": "'other income' is not in the facts"}])
    findings, generations = verify_statements([s], record, pack, catalogue, LLMEntailmentChecker(llm))
    assert [f.code for f in findings] == ["POSSIBLY_UNSUPPORTED"]
    assert generations[0].stage == "verify"


def test_drafting_prompt_never_contains_document_text(service, users, pack, catalogue):
    """Closed world: the drafting model sees facts and instructions, not the uploaded documents
    (so the injected instruction in the sample fact-find cannot reach it)."""
    case = prepare_ready_case(service, users, pack.id)
    record = service.store.records[case.id]
    responses = [{"statements": [{"text": "ok", "fact_ids": [], "insufficient_evidence": False}]}] * 10
    llm = ScriptedLLMClient(responses)
    draft_report(pack, record, LLMDraftingModel(llm), catalogue)
    assert llm.calls, "model was called"
    for call in llm.calls:
        assert "ignore all previous instructions" not in (call["system"] + call["user"]).lower()
        assert "Northbridge Life - ANNUAL PENSION STATEMENT".lower() not in call["user"].lower()
