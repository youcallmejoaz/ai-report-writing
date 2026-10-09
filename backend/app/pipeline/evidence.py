"""Stage 3: evidence. Organise extracted fields from all case documents into the case record.

- identical values from several sources merge into one fact with several citations;
- different values for the same key become separate candidate facts plus a ``Conflict``;
- keys the chosen template requires but no document evidences become ``Gap`` items.

No model is involved: the case record is built deterministically and every change to it afterwards is
a recorded human action (verify, correct, resolve, adviser input).
"""

from __future__ import annotations

from collections import defaultdict

from app.domain.catalogue import Catalogue
from app.domain.schemas import (
    CaseRecord,
    Conflict,
    ConflictStatus,
    ExtractedField,
    Fact,
    FactStatus,
    FactValue,
    Gap,
    GapStatus,
    SourceRef,
    utcnow,
)
from app.domain.values import parse_value


class EvidenceError(ValueError):
    pass


def _norm(value: FactValue) -> object:
    return value.strip().lower() if isinstance(value, str) else value


def build_case_record(
    case_id: str,
    fields: list[ExtractedField],
    catalogue: Catalogue,
    required_keys: dict[str, list[str]],
    existing: CaseRecord | None = None,
) -> CaseRecord:
    """Rebuild machine-derived facts, keeping any human-entered adviser inputs from ``existing``.

    ``required_keys`` maps fact key -> template slots/sections that need it (used for gap detection).
    """
    record = CaseRecord(case_id=case_id, revision=(existing.revision + 1) if existing else 1)
    if existing:
        record.facts.extend(
            f for f in existing.facts if any(s.kind == "adviser_input" for s in f.sources)
        )

    grouped: dict[str, dict[object, list[ExtractedField]]] = defaultdict(lambda: defaultdict(list))
    for field in fields:
        grouped[field.key][_norm(field.value)].append(field)

    for key, by_value in grouped.items():
        definition = catalogue.definition(key)
        candidates: list[Fact] = []
        for group in by_value.values():
            candidates.append(
                Fact(
                    case_id=case_id,
                    key=key,
                    value=group[0].value,
                    value_type=group[0].value_type,
                    sources=[SourceRef(kind="span", span_id=f.span_id) for f in group],
                    confidence=min(f.confidence for f in group),
                    material=definition.material,
                )
            )
        record.facts.extend(candidates)
        if len(candidates) > 1:
            record.conflicts.append(
                Conflict(case_id=case_id, key=key, candidate_fact_ids=[f.id for f in candidates])
            )

    if existing:
        _carry_over_human_decisions(record, existing)

    present = {f.key for f in record.facts}
    previous_gaps = {g.key: g for g in existing.gaps} if existing else {}
    for key, needed_by in sorted(required_keys.items()):
        if key not in present:
            prior = previous_gaps.get(key)
            if prior and prior.status is GapStatus.NOT_APPLICABLE:
                record.gaps.append(prior.model_copy(update={"required_by": needed_by}))
            else:
                record.gaps.append(Gap(key=key, required_by=needed_by))
    return record


def _carry_over_human_decisions(record: CaseRecord, existing: CaseRecord) -> None:
    """Keep verifications, corrections and conflict resolutions when the record is rebuilt (e.g. after
    another upload). A rebuilt fact continues an earlier one if it still cites all the earlier spans; it
    keeps the earlier id, so report citations stay valid. A new conflicting value opens a new conflict."""
    old_facts = [f for f in existing.facts if any(s.kind == "span" for s in f.sources)]
    renamed: dict[str, str] = {}
    for fact in record.facts:
        new_spans = {s.span_id for s in fact.sources}
        for old in old_facts:
            old_spans = {s.span_id for s in old.sources}
            if old.key == fact.key and old_spans <= new_spans:
                renamed[fact.id], fact.id = old.id, old.id
                fact.status, fact.verified_by, fact.verified_at = old.status, old.verified_by, old.verified_at
                fact.correction_reason = old.correction_reason
                if old.status is FactStatus.CORRECTED:
                    fact.value = old.value
                break
    for conflict in record.conflicts:
        conflict.candidate_fact_ids = [renamed.get(i, i) for i in conflict.candidate_fact_ids]
        for old in existing.conflicts:
            if old.key == conflict.key and set(old.candidate_fact_ids) == set(conflict.candidate_fact_ids):
                conflict.id, conflict.status, conflict.chosen_fact_id = old.id, old.status, old.chosen_fact_id
                conflict.resolved_by, conflict.reason = old.resolved_by, old.reason
                break


# --------------------------------------------------------------------------- human actions


def _get_fact(record: CaseRecord, fact_id: str) -> Fact:
    fact = record.fact(fact_id)
    if fact is None:
        raise EvidenceError(f"unknown fact {fact_id}")
    return fact


def verify_fact(record: CaseRecord, fact_id: str, user_id: str) -> Fact:
    fact = _get_fact(record, fact_id)
    if fact.key in record.open_conflict_keys():
        raise EvidenceError("resolve the conflict for this fact before verifying it")
    fact.status = FactStatus.VERIFIED
    fact.verified_by, fact.verified_at = user_id, utcnow()
    record.revision += 1
    return fact


def correct_fact(record: CaseRecord, fact_id: str, raw_value: str, user_id: str, reason: str,
                 catalogue: Catalogue) -> Fact:
    if not reason.strip():
        raise EvidenceError("a reason is required to correct a fact")
    fact = _get_fact(record, fact_id)
    fact.value = parse_value(raw_value, catalogue.definition(fact.key).type)
    fact.status = FactStatus.CORRECTED
    fact.verified_by, fact.verified_at, fact.correction_reason = user_id, utcnow(), reason
    record.revision += 1
    return fact


def reject_fact(record: CaseRecord, fact_id: str, user_id: str, reason: str) -> Fact:
    fact = _get_fact(record, fact_id)
    fact.status = FactStatus.REJECTED
    fact.verified_by, fact.verified_at, fact.correction_reason = user_id, utcnow(), reason
    record.revision += 1
    return fact


def resolve_conflict(record: CaseRecord, conflict_id: str, chosen_fact_id: str | None, user_id: str,
                     reason: str) -> Conflict:
    """Choose one candidate (others rejected), or pass None to mark the conflict deliberately unresolved."""
    if not reason.strip():
        raise EvidenceError("a reason is required to resolve a conflict")
    conflict = next((c for c in record.conflicts if c.id == conflict_id), None)
    if conflict is None:
        raise EvidenceError(f"unknown conflict {conflict_id}")
    if chosen_fact_id is not None and chosen_fact_id not in conflict.candidate_fact_ids:
        raise EvidenceError("chosen fact is not a candidate in this conflict")
    for fid in conflict.candidate_fact_ids:
        fact = _get_fact(record, fid)
        if fid == chosen_fact_id:
            fact.status, fact.verified_by, fact.verified_at = FactStatus.VERIFIED, user_id, utcnow()
        else:
            fact.status, fact.correction_reason = FactStatus.REJECTED, f"conflict {conflict.id}: {reason}"
    conflict.status = ConflictStatus.RESOLVED if chosen_fact_id else ConflictStatus.UNRESOLVED
    conflict.chosen_fact_id, conflict.resolved_by, conflict.reason = chosen_fact_id, user_id, reason
    record.revision += 1
    return conflict


def record_adviser_input(record: CaseRecord, key: str, raw_value: str, user_id: str, note: str | None,
                         catalogue: Catalogue) -> Fact:
    """Adviser-provided facts (e.g. the recommendation) are first-class, attributed evidence."""
    definition = catalogue.definition(key)
    for existing in record.facts_for_key(key):
        if existing.status is FactStatus.REJECTED:
            continue
        if any(s.kind == "span" for s in existing.sources):
            raise EvidenceError(f"documentary evidence exists for {key}; verify or correct that fact instead")
        existing.status, existing.correction_reason = FactStatus.REJECTED, "superseded by adviser input"
    fact = Fact(
        case_id=record.case_id,
        key=key,
        value=parse_value(raw_value, definition.type),
        value_type=definition.type,
        sources=[SourceRef(kind="adviser_input", recorded_by=user_id, note=note)],
        status=FactStatus.VERIFIED,
        material=definition.material,
        verified_by=user_id,
        verified_at=utcnow(),
    )
    record.facts.append(fact)
    for gap in record.gaps:
        if gap.key == key and gap.status is GapStatus.OPEN:
            gap.status, gap.resolved_by = GapStatus.FILLED, user_id
    record.revision += 1
    return fact


def mark_gap_not_applicable(record: CaseRecord, key: str, user_id: str, reason: str) -> Gap:
    gap = next((g for g in record.gaps if g.key == key), None)
    if gap is None:
        raise EvidenceError(f"no gap for {key}")
    gap.status, gap.resolved_by, gap.reason = GapStatus.NOT_APPLICABLE, user_id, reason
    record.revision += 1
    return gap


def verification_queue(record: CaseRecord, auto_accept_threshold: float = 1.01) -> list[Fact]:
    """Facts awaiting a human: material ones always; others when below the auto-accept threshold.

    The default threshold (>1) means nothing is auto-accepted until per-document-type thresholds have
    been set from golden-set measurements during Discovery.
    """
    return [
        f for f in record.facts
        if f.status is FactStatus.EXTRACTED and (f.material or f.confidence < auto_accept_threshold)
    ]
