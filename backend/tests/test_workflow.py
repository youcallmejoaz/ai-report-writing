import pytest

from app.domain.schemas import ReportStatus
from app.workflow import WorkflowError
from tests.conftest import prepare_ready_case


@pytest.fixture
def report(service, users, pack):
    case = prepare_ready_case(service, users, pack.id)
    return service.generate_report(users["alice"], case.id)


def _review_all(service, users, report):
    for slot in report.ai_slots:
        service.mark_reviewed(users["bob"], report.id, slot)


def test_maker_cannot_approve(service, users, report):
    service.submit(users["alice"], report.id)
    _review_all(service, users, report)
    with pytest.raises(WorkflowError, match="maker-checker"):
        service.approve(users["alice"], report.id)


def test_editor_cannot_approve(service, users, report):
    s = report.statements[0]
    service.edit_statement(users["bob"], report.id, s.id, s.text, s.fact_ids)  # bob edits -> becomes a maker
    service.submit(users["alice"], report.id)
    _review_all(service, users, report)
    with pytest.raises(WorkflowError, match="maker-checker"):
        service.approve(users["bob"], report.id)


def test_all_ai_slots_must_be_reviewed(service, users, report):
    service.submit(users["alice"], report.id)
    with pytest.raises(WorkflowError, match="not yet marked reviewed"):
        service.approve(users["bob"], report.id)


def test_blocking_findings_prevent_approval(service, users, report):
    s = report.statements[0]
    service.edit_statement(users["alice"], report.id, s.id, "Your pension is risk-free.", s.fact_ids)
    service.submit(users["alice"], report.id)
    _review_all(service, users, report)
    with pytest.raises(WorkflowError, match="blocking"):
        service.approve(users["bob"], report.id)
    with pytest.raises(WorkflowError, match="must be fixed"):
        service.dismiss_warning(users["bob"], report.id, report.open_blocking_findings[0].id, "fine")


def test_edit_after_approval_invalidates_it(service, users, report):
    service.submit(users["alice"], report.id)
    _review_all(service, users, report)
    service.approve(users["bob"], report.id)
    s = report.statements[0]
    service.edit_statement(users["alice"], report.id, s.id, s.text + " ", s.fact_ids)
    assert report.status is ReportStatus.DRAFT
    with pytest.raises(WorkflowError):
        service.finalise(users["alice"], report.id)


def test_happy_path_finalises_with_hash(service, users, report):
    service.submit(users["alice"], report.id)
    _review_all(service, users, report)
    service.approve(users["bob"], report.id)
    service.finalise(users["bob"], report.id)
    assert report.status is ReportStatus.FINAL and len(report.final_sha256) == 64
    actions = [e.action for e in service.audit.for_case(report.case_id)]
    assert actions.index("report.approve") < actions.index("report.finalise")


def test_other_team_cannot_see_case(service, users, report):
    with pytest.raises(PermissionError):
        service.get_report(users["sam"], report.id)
    with pytest.raises(PermissionError):
        service.get_report(users["pat"], report.id)  # platform admin: no default content access
    assert service.get_report(users["carol"], report.id).id == report.id  # compliance oversight
