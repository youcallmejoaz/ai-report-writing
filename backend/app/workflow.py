"""Report review workflow: maker-checker approval, blocking findings, approval invalidation on edit.

    draft -> in_review -> (changes_requested -> draft) | approved -> final
    approved --any edit--> draft
"""

from __future__ import annotations

from app.domain.schemas import (
    Report,
    ReportStatus,
    ReviewDecision,
    Role,
    Statement,
    User,
    utcnow,
)


class WorkflowError(PermissionError):
    pass


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise WorkflowError(message)


def can_prepare(user: User) -> bool:
    return user.has(Role.PREPARER) or user.has(Role.ADVISER)


def edit_statement(report: Report, statement_id: str, text: str, fact_ids: list[str], user: User) -> Statement:
    _require(can_prepare(user), "only preparers or advisers can edit report content")
    _require(report.status in (ReportStatus.DRAFT, ReportStatus.CHANGES_REQUESTED, ReportStatus.APPROVED),
             f"report is {report.status}; it cannot be edited")
    s = report.statement(statement_id)
    _require(s is not None, "unknown statement")
    s.text, s.fact_ids, s.edited_by, s.insufficient_evidence = text, fact_ids, user.id, False
    report.editors.add(user.id)
    report.revision += 1
    report.needs_verification = True
    report.reviewed_slots.discard(s.slot_id)
    if report.status is ReportStatus.APPROVED:
        report.status = ReportStatus.DRAFT  # approval was for a different revision
    elif report.status is ReportStatus.CHANGES_REQUESTED:
        report.status = ReportStatus.DRAFT
    return s


def submit_for_review(report: Report, user: User) -> None:
    _require(can_prepare(user), "only preparers or advisers can submit")
    _require(report.status is ReportStatus.DRAFT, f"report is {report.status}")
    _require(not report.needs_verification, "re-run verification after editing before submitting")
    report.status = ReportStatus.IN_REVIEW


def _is_maker(report: Report, user: User) -> bool:
    return user.id == report.prepared_by or user.id in report.editors


def mark_slot_reviewed(report: Report, slot_id: str, reviewer: User) -> None:
    _require(reviewer.has(Role.REVIEWER), "only reviewers can review")
    _require(report.status is ReportStatus.IN_REVIEW, "report is not in review")
    _require(slot_id in report.ai_slots, f"unknown slot {slot_id}")
    report.reviewed_slots.add(slot_id)


def dismiss_warning(report: Report, finding_id: str, reviewer: User, reason: str) -> None:
    _require(reviewer.has(Role.REVIEWER), "only reviewers can dismiss findings")
    _require(bool(reason.strip()), "a reason is required")
    finding = next((f for f in report.findings if f.id == finding_id), None)
    _require(finding is not None, "unknown finding")
    _require(finding.severity == "warning", "blocking findings must be fixed, not dismissed")
    finding.dismissed_by, finding.dismissal_reason = reviewer.id, reason


def request_changes(report: Report, reviewer: User, comment: str) -> None:
    _require(reviewer.has(Role.REVIEWER), "only reviewers can request changes")
    _require(report.status is ReportStatus.IN_REVIEW, "report is not in review")
    report.status = ReportStatus.CHANGES_REQUESTED
    report.decisions.append(ReviewDecision(reviewer=reviewer.id, decision="changes_requested",
                                           report_revision=report.revision, comment=comment))


def approval_blockers(report: Report, reviewer: User) -> list[str]:
    blockers: list[str] = []
    if not reviewer.has(Role.REVIEWER):
        blockers.append("approver does not hold the Reviewer role")
    if _is_maker(report, reviewer):
        blockers.append("maker-checker: the preparer or an editor of this report cannot approve it")
    if report.status is not ReportStatus.IN_REVIEW:
        blockers.append(f"report is {report.status}, not in review")
    if report.needs_verification:
        blockers.append("verification has not been re-run since the last edit")
    if report.open_blocking_findings:
        blockers.append(f"{len(report.open_blocking_findings)} blocking finding(s) remain open")
    unreviewed = report.ai_slots - report.reviewed_slots
    if unreviewed:
        blockers.append(f"AI-drafted sections not yet marked reviewed: {sorted(unreviewed)}")
    return blockers


def approve(report: Report, reviewer: User, comment: str | None = None) -> None:
    blockers = approval_blockers(report, reviewer)
    _require(not blockers, "; ".join(blockers))
    report.status = ReportStatus.APPROVED
    report.decisions.append(ReviewDecision(reviewer=reviewer.id, decision="approved",
                                           report_revision=report.revision, comment=comment))


def finalise(report: Report, user: User, final_sha256: str) -> None:
    _require(report.status is ReportStatus.APPROVED, "only approved reports can be finalised")
    last = report.decisions[-1] if report.decisions else None
    _require(last is not None and last.decision == "approved" and last.report_revision == report.revision,
             "approval does not match the current revision")
    _require(can_prepare(user) or user.has(Role.REVIEWER), "not permitted to finalise")
    report.status = ReportStatus.FINAL
    report.final_sha256, report.finalised_by, report.finalised_at = final_sha256, user.id, utcnow()
