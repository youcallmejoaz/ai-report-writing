"""Application service: the one path through which the API, workers and demo act on cases.

Every operation checks the caller's role and case scope, and records an audit event. Persistence here
is in-memory for the reference implementation; production uses PostgreSQL (``db/schema.sql``) for the
records and Blob Storage for document bytes and outputs, with the same method boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app import workflow
from app.audit import AuditLog, sha256_hex
from app.auth import can_access_case
from app.domain.catalogue import Catalogue
from app.domain.schemas import (
    Case,
    CaseRecord,
    Document,
    ExtractedField,
    ExtractionResult,
    Report,
    Role,
    SourceSpan,
    User,
)
from app.pipeline import evidence
from app.pipeline.assemble import render_evidence_appendix, render_report
from app.pipeline.draft import DraftingModel, draft_report
from app.pipeline.extract import ExtractionModel, classify, extract_document, layout_for
from app.pipeline.ingest import MalwareScanner, ingest
from app.pipeline.verify import EntailmentChecker, verify_statements
from app.templates_mgmt.registry import TemplateRegistry


class AccessDenied(PermissionError):
    pass


class NotFound(KeyError):
    pass


Variant = Literal["review", "client", "evidence"]


@dataclass
class Store:
    cases: dict[str, Case] = field(default_factory=dict)
    documents: dict[str, Document] = field(default_factory=dict)
    blobs: dict[str, bytes] = field(default_factory=dict)  # document id -> original bytes
    spans: dict[str, SourceSpan] = field(default_factory=dict)
    extractions: dict[str, ExtractionResult] = field(default_factory=dict)  # document id -> result
    records: dict[str, CaseRecord] = field(default_factory=dict)
    reports: dict[str, Report] = field(default_factory=dict)
    finals: dict[str, dict[str, bytes]] = field(default_factory=dict)  # report id -> variant -> bytes


class ReportService:
    def __init__(
        self,
        *,
        catalogue: Catalogue,
        registry: TemplateRegistry,
        extractor: ExtractionModel,
        drafter: DraftingModel,
        scanner: MalwareScanner,
        entailment: EntailmentChecker | None = None,
        allow_text_uploads: bool = False,
    ) -> None:
        self.catalogue = catalogue
        self.registry = registry
        self.extractor = extractor
        self.drafter = drafter
        self.scanner = scanner
        self.entailment = entailment
        self.allow_text_uploads = allow_text_uploads
        self.store = Store()
        self.audit = AuditLog()

    # ------------------------------------------------------------------ helpers

    def _case(self, user: User, case_id: str) -> Case:
        case = self.store.cases.get(case_id)
        if case is None:
            raise NotFound(case_id)
        if not can_access_case(user, case):
            self.audit.record(user.id, "case.access_denied", "case", case_id, case_id=case_id)
            raise AccessDenied("you do not have access to this case")
        return case

    def _report(self, user: User, report_id: str) -> Report:
        report = self.store.reports.get(report_id)
        if report is None:
            raise NotFound(report_id)
        self._case(user, report.case_id)
        return report

    def _require_preparer(self, user: User) -> None:
        if not workflow.can_prepare(user):
            raise AccessDenied("requires Preparer or Adviser role")

    # ------------------------------------------------------------------ cases & documents

    def create_case(self, user: User, *, client_ref: str, team: str, template_pack_id: str,
                    restricted: bool = False) -> Case:
        self._require_preparer(user)
        if team not in user.teams:
            raise AccessDenied("you can only create cases for your own team")
        self.registry.published(template_pack_id)  # must exist and be published
        case = Case(client_ref=client_ref, team=team, template_pack_id=template_pack_id,
                    created_by=user.id, assigned_to={user.id}, restricted=restricted)
        self.store.cases[case.id] = case
        self.store.records[case.id] = CaseRecord(case_id=case.id)
        self.audit.record(user.id, "case.create", "case", case.id, case_id=case.id,
                          template_pack_id=template_pack_id, restricted=restricted)
        return case

    def list_cases(self, user: User) -> list[Case]:
        return [c for c in self.store.cases.values() if can_access_case(user, c)]

    def upload_document(self, user: User, case_id: str, filename: str, data: bytes,
                        doc_type: str | None = None) -> ExtractionResult:
        self._require_preparer(user)
        case = self._case(user, case_id)
        ingested = ingest(case_id=case.id, filename=filename, data=data, uploaded_by=user.id,
                          scanner=self.scanner, allow_text=self.allow_text_uploads)
        doc = ingested.document
        self.store.documents[doc.id] = doc
        self.store.blobs[doc.id] = ingested.data
        # filenames can contain client names, so the audit log records the hash, not the name
        self.audit.record(user.id, "document.upload", "document", doc.id, case_id=case.id,
                          sha256=doc.sha256, media_type=doc.media_type, size=doc.size_bytes)

        spans = layout_for(doc.media_type).analyze(doc, ingested.data)
        for s in spans:
            self.store.spans[s.id] = s
        doc.doc_type = doc_type or classify(spans, self.catalogue)
        if doc.doc_type is None:
            raise ValueError("document type could not be determined; choose it and re-run extraction")
        if doc_type:
            doc.doc_type_confirmed_by = user.id

        result, generation = extract_document(doc, spans, doc.doc_type, self.extractor, self.catalogue)
        self.store.extractions[doc.id] = result
        self.audit.record(
            "system", "document.extract", "document", doc.id, case_id=case.id,
            doc_type=doc.doc_type, spans=len(spans), fields=len(result.fields), issues=len(result.issues),
            model=generation.model if generation else "deterministic",
            prompt_version=generation.prompt_version if generation else None,
            input_sha256=generation.input_sha256 if generation else None,
            output_sha256=generation.output_sha256 if generation else None,
        )
        self._rebuild_record(case)
        return result

    def _rebuild_record(self, case: Case) -> CaseRecord:
        fields: list[ExtractedField] = [
            f for doc_id, r in self.store.extractions.items()
            if self.store.documents[doc_id].case_id == case.id for f in r.fields
        ]
        pack = self.registry.published(case.template_pack_id).pack
        record = evidence.build_case_record(case.id, fields, self.catalogue, pack.required_keys(),
                                            existing=self.store.records.get(case.id))
        self.store.records[case.id] = record
        self.audit.record("system", "case_record.build", "case", case.id, case_id=case.id,
                          revision=record.revision, facts=len(record.facts),
                          conflicts=len(record.conflicts), gaps=len(record.gaps))
        return record

    # ------------------------------------------------------------------ case record (human actions)

    def case_record(self, user: User, case_id: str) -> CaseRecord:
        self._case(user, case_id)
        self.audit.record(user.id, "case_record.view", "case", case_id, case_id=case_id)
        return self.store.records[case_id]

    def source_span(self, user: User, span_id: str) -> tuple[SourceSpan, Document]:
        span = self.store.spans.get(span_id)
        if span is None:
            raise NotFound(span_id)
        doc = self.store.documents[span.document_id]
        self._case(user, doc.case_id)
        return span, doc

    def verify_fact(self, user: User, case_id: str, fact_id: str):
        self._require_preparer(user)
        self._case(user, case_id)
        fact = evidence.verify_fact(self.store.records[case_id], fact_id, user.id)
        self.audit.record(user.id, "fact.verify", "fact", fact_id, case_id=case_id, key=fact.key)
        return fact

    def correct_fact(self, user: User, case_id: str, fact_id: str, raw_value: str, reason: str):
        self._require_preparer(user)
        self._case(user, case_id)
        record = self.store.records[case_id]
        before = record.fact(fact_id)
        before_hash = sha256_hex(str(before.value)) if before else None
        fact = evidence.correct_fact(record, fact_id, raw_value, user.id, reason, self.catalogue)
        self.audit.record(user.id, "fact.correct", "fact", fact_id, case_id=case_id, key=fact.key,
                          before_sha256=before_hash, after_sha256=sha256_hex(str(fact.value)))
        return fact

    def resolve_conflict(self, user: User, case_id: str, conflict_id: str, chosen_fact_id: str | None,
                         reason: str):
        self._require_preparer(user)
        self._case(user, case_id)
        conflict = evidence.resolve_conflict(self.store.records[case_id], conflict_id, chosen_fact_id,
                                             user.id, reason)
        self.audit.record(user.id, "conflict.resolve", "conflict", conflict_id, case_id=case_id,
                          key=conflict.key, outcome=conflict.status, chosen=chosen_fact_id)
        return conflict

    def adviser_input(self, user: User, case_id: str, key: str, raw_value: str, note: str | None = None):
        self._require_preparer(user)
        self._case(user, case_id)
        if self.catalogue.definition(key).adviser_input and not user.has(Role.ADVISER):
            # the recommendation and its reasons are the adviser's judgement, never the tool's
            raise AccessDenied("only an Adviser can record recommendation inputs")
        fact = evidence.record_adviser_input(self.store.records[case_id], key, raw_value, user.id, note,
                                             self.catalogue)
        self.audit.record(user.id, "fact.adviser_input", "fact", fact.id, case_id=case_id, key=key)
        return fact

    # ------------------------------------------------------------------ reports

    def generate_report(self, user: User, case_id: str) -> Report:
        self._require_preparer(user)
        case = self._case(user, case_id)
        tv = self.registry.published(case.template_pack_id)
        record = self.store.records[case_id]
        statements, generations = draft_report(tv.pack, record, self.drafter, self.catalogue)
        report = Report(
            case_id=case_id,
            template_pack_id=tv.pack.id,
            template_version=tv.pack.version,
            template_hash=tv.content_hash,
            drafting_model=self.drafter.name,
            prompt_version=self.drafter.prompt_version,
            case_record_revision=record.revision,
            statements=statements,
            prepared_by=user.id,
            generations=generations,
        )
        self.store.reports[report.id] = report
        for g in generations:
            self.audit.record("system", "llm.generate", "report", report.id, case_id=case_id, stage=g.stage,
                              model=g.model, prompt_version=g.prompt_version,
                              input_sha256=g.input_sha256, output_sha256=g.output_sha256)
        self.audit.record(user.id, "report.generate", "report", report.id, case_id=case_id,
                          template=f"{tv.pack.id}@{tv.pack.version}", template_sha256=tv.content_hash,
                          model=report.drafting_model, prompt_version=report.prompt_version,
                          statements=len(statements))
        self._verify(report)
        return report

    def _verify(self, report: Report) -> None:
        pack = self.registry.get(report.template_pack_id, report.template_version).pack
        findings, generations = verify_statements(report.statements, self.store.records[report.case_id],
                                                  pack, self.catalogue, self.entailment)
        report.findings = findings
        report.generations.extend(generations)
        report.needs_verification = False
        self.audit.record("system", "report.verify", "report", report.id, case_id=report.case_id,
                          revision=report.revision, blocking=len(report.open_blocking_findings),
                          warnings=len(findings) - len(report.open_blocking_findings))

    def list_reports(self, user: User, case_id: str) -> list[Report]:
        self._case(user, case_id)
        return [r for r in self.store.reports.values() if r.case_id == case_id]

    def get_report(self, user: User, report_id: str) -> Report:
        report = self._report(user, report_id)
        self.audit.record(user.id, "report.view", "report", report_id, case_id=report.case_id)
        return report

    def edit_statement(self, user: User, report_id: str, statement_id: str, text: str,
                       fact_ids: list[str]) -> Report:
        report = self._report(user, report_id)
        was = report.status
        workflow.edit_statement(report, statement_id, text, fact_ids, user)
        self.audit.record(user.id, "statement.edit", "report", report_id, case_id=report.case_id,
                          statement_id=statement_id, revision=report.revision,
                          text_sha256=sha256_hex(text), approval_invalidated=was == "approved")
        self._verify(report)
        return report

    def submit(self, user: User, report_id: str) -> Report:
        report = self._report(user, report_id)
        workflow.submit_for_review(report, user)
        self.audit.record(user.id, "report.submit", "report", report_id, case_id=report.case_id,
                          revision=report.revision)
        return report

    def mark_reviewed(self, user: User, report_id: str, slot_id: str) -> Report:
        report = self._report(user, report_id)
        workflow.mark_slot_reviewed(report, slot_id, user)
        self.audit.record(user.id, "report.slot_reviewed", "report", report_id, case_id=report.case_id,
                          slot=slot_id, revision=report.revision)
        return report

    def dismiss_warning(self, user: User, report_id: str, finding_id: str, reason: str) -> Report:
        report = self._report(user, report_id)
        workflow.dismiss_warning(report, finding_id, user, reason)
        self.audit.record(user.id, "finding.dismiss", "report", report_id, case_id=report.case_id,
                          finding_id=finding_id)
        return report

    def request_changes(self, user: User, report_id: str, comment: str) -> Report:
        report = self._report(user, report_id)
        workflow.request_changes(report, user, comment)
        self.audit.record(user.id, "report.request_changes", "report", report_id, case_id=report.case_id,
                          revision=report.revision)
        return report

    def approve(self, user: User, report_id: str, comment: str | None = None) -> Report:
        report = self._report(user, report_id)
        try:
            workflow.approve(report, user, comment)
        except workflow.WorkflowError as exc:
            self.audit.record(user.id, "report.approve_refused", "report", report_id,
                              case_id=report.case_id, reason=str(exc))
            raise
        self.audit.record(user.id, "report.approve", "report", report_id, case_id=report.case_id,
                          revision=report.revision)
        return report

    def render(self, user: User, report_id: str, variant: Variant) -> bytes:
        report = self._report(user, report_id)
        if report.id in self.store.finals:
            data = self.store.finals[report.id][variant]
        else:
            data = self._render(report, variant)
        self.audit.record(user.id, "report.download", "report", report_id, case_id=report.case_id,
                          variant=variant, sha256=sha256_hex(data))
        return data

    def _render(self, report: Report, variant: Variant) -> bytes:
        pack = self.registry.get(report.template_pack_id, report.template_version).pack
        record = self.store.records[report.case_id]
        if variant == "evidence":
            return render_evidence_appendix(report, record, self.catalogue, self.store.spans,
                                            self.store.documents)
        return render_report(pack, record, report, self.catalogue, mode=variant)

    def finalise(self, user: User, report_id: str) -> Report:
        report = self._report(user, report_id)
        outputs = {v: self._render(report, v) for v in ("client", "review", "evidence")}
        workflow.finalise(report, user, sha256_hex(outputs["client"]))
        self.store.finals[report.id] = outputs  # production: write-once to the WORM container
        self.audit.record(user.id, "report.finalise", "report", report_id, case_id=report.case_id,
                          revision=report.revision,
                          **{f"{k}_sha256": sha256_hex(v) for k, v in outputs.items()})
        return report
