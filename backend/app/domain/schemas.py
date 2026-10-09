"""Typed contracts passed between pipeline stages and persisted as the case record.

Each stage consumes and produces these models only; nothing downstream of extraction ever sees raw
document text except through a ``SourceSpan`` reference.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.domain.values import ValueType, format_value


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


FactValue = str | Decimal | date | int | bool


# --------------------------------------------------------------------------- users


class Role(StrEnum):
    PREPARER = "Preparer"
    ADVISER = "Adviser"
    REVIEWER = "Reviewer"
    COMPLIANCE = "Compliance"
    TEMPLATE_ADMIN = "TemplateAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"
    AUDITOR = "Auditor"


class User(BaseModel):
    id: str
    name: str
    roles: set[Role]
    teams: set[str] = Field(default_factory=set)

    def has(self, role: Role) -> bool:
        return role in self.roles


# --------------------------------------------------------------------------- cases & documents


class Case(BaseModel):
    id: str = Field(default_factory=lambda: new_id("case"))
    client_ref: str  # reference into the firm's CRM/back office; client identity is not duplicated here
    team: str
    template_pack_id: str
    created_by: str
    assigned_to: set[str] = Field(default_factory=set)
    restricted: bool = False
    legal_hold: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    case_id: str
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    doc_type: str | None = None
    doc_type_confirmed_by: str | None = None


class BBox(BaseModel):
    """Bounding box in page units (inches for Document Intelligence; line index for plain text)."""

    x0: float
    y0: float
    x1: float
    y1: float


class SourceSpan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("span"))
    document_id: str
    page: int
    bbox: BBox
    text: str
    ocr_confidence: float = 1.0


# --------------------------------------------------------------------------- extraction


class ExtractedField(BaseModel):
    """One field produced by the extraction stage, already validated against its cited span."""

    key: str
    raw_value: str
    value: FactValue
    value_type: ValueType
    span_id: str
    document_id: str
    confidence: float


class ExtractionIssue(BaseModel):
    key: str
    document_id: str
    reason: str
    raw_value: str | None = None
    span_id: str | None = None


class ExtractionResult(BaseModel):
    document_id: str
    doc_type: str
    fields: list[ExtractedField]
    issues: list[ExtractionIssue]
    not_found: list[str]


# --------------------------------------------------------------------------- case record


class FactStatus(StrEnum):
    EXTRACTED = "extracted"  # machine-extracted, not yet confirmed
    VERIFIED = "verified"  # confirmed by a person against the source
    CORRECTED = "corrected"  # value changed by a person (reason recorded)
    REJECTED = "rejected"  # excluded from use


USABLE_STATUSES = {FactStatus.VERIFIED, FactStatus.CORRECTED}


class SourceRef(BaseModel):
    kind: Literal["span", "adviser_input"]
    span_id: str | None = None
    recorded_by: str | None = None
    note: str | None = None


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fact"))
    case_id: str
    key: str
    value: FactValue
    value_type: ValueType
    sources: list[SourceRef]
    status: FactStatus = FactStatus.EXTRACTED
    confidence: float = 1.0
    material: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None
    correction_reason: str | None = None

    @computed_field  # included in API responses so every client shows the same house formatting
    @property
    def display(self) -> str:
        return format_value(self.value, self.value_type)

    @property
    def usable(self) -> bool:
        return self.status in USABLE_STATUSES


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"  # one candidate chosen
    UNRESOLVED = "unresolved"  # deliberately left unresolved; dependent content gets INSUFFICIENT_EVIDENCE


class Conflict(BaseModel):
    id: str = Field(default_factory=lambda: new_id("conf"))
    case_id: str
    key: str
    candidate_fact_ids: list[str]
    status: ConflictStatus = ConflictStatus.OPEN
    chosen_fact_id: str | None = None
    resolved_by: str | None = None
    reason: str | None = None


class GapStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"  # adviser input recorded
    NOT_APPLICABLE = "not_applicable"


class Gap(BaseModel):
    key: str
    required_by: list[str]
    status: GapStatus = GapStatus.OPEN
    resolved_by: str | None = None
    reason: str | None = None


class CaseRecord(BaseModel):
    case_id: str
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    revision: int = 0

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)

    def facts_for_key(self, key: str) -> list[Fact]:
        return [f for f in self.facts if f.key == key]

    def open_conflict_keys(self) -> set[str]:
        return {c.key for c in self.conflicts if c.status is not ConflictStatus.RESOLVED}

    def usable_fact(self, key: str) -> Fact | None:
        """The single usable fact for a key, or None if absent, unverified or in conflict."""
        if key in self.open_conflict_keys():
            return None
        usable = [f for f in self.facts_for_key(key) if f.usable]
        return usable[0] if len(usable) == 1 else None


# --------------------------------------------------------------------------- drafting & verification


INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Statement(BaseModel):
    id: str = Field(default_factory=lambda: new_id("stmt"))
    slot_id: str
    text: str
    fact_ids: list[str]
    insufficient_evidence: bool = False
    edited_by: str | None = None


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("find"))
    code: str
    severity: Severity
    message: str
    slot_id: str | None = None
    statement_id: str | None = None
    dismissed_by: str | None = None
    dismissal_reason: str | None = None

    @property
    def open_blocking(self) -> bool:
        return self.severity is Severity.BLOCKING and self.dismissed_by is None


class GenerationRecord(BaseModel):
    """What was sent to and returned by a model, recorded for audit (payloads stored per retention)."""

    stage: Literal["extract", "draft", "verify"]
    model: str
    prompt_version: str
    input_sha256: str
    output_sha256: str
    created_at: datetime = Field(default_factory=utcnow)
    usage: dict[str, Any] = Field(default_factory=dict)


class ReportStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    FINAL = "final"


class ReviewDecision(BaseModel):
    reviewer: str
    decision: Literal["approved", "changes_requested"]
    report_revision: int
    comment: str | None = None
    at: datetime = Field(default_factory=utcnow)


class Report(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rpt"))
    case_id: str
    template_pack_id: str
    template_version: str
    template_hash: str
    drafting_model: str
    prompt_version: str
    case_record_revision: int
    statements: list[Statement] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    status: ReportStatus = ReportStatus.DRAFT
    prepared_by: str
    editors: set[str] = Field(default_factory=set)
    revision: int = 1
    needs_verification: bool = False
    reviewed_slots: set[str] = Field(default_factory=set)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    generations: list[GenerationRecord] = Field(default_factory=list)
    final_sha256: str | None = None
    finalised_by: str | None = None
    finalised_at: datetime | None = None

    def statement(self, statement_id: str) -> Statement | None:
        return next((s for s in self.statements if s.id == statement_id), None)

    @property
    def ai_slots(self) -> set[str]:
        return {s.slot_id for s in self.statements}

    @property
    def open_blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.open_blocking]
