"""Stage 5: verify. Deterministic checks on every drafted statement, plus an optional entailment check.

Blocking findings prevent approval (see ``workflow.approve``); they cannot be dismissed, only fixed.
Warnings can be dismissed by a reviewer with a recorded reason.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from app.domain.catalogue import Catalogue
from app.domain.schemas import (
    CaseRecord,
    Fact,
    Finding,
    GenerationRecord,
    Severity,
    Statement,
)
from app.domain.values import ValueType, numbers_and_dates
from app.llm.client import LLMClient
from app.llm.prompts import ENTAILMENT_PROMPT_VERSION, ENTAILMENT_SCHEMA, ENTAILMENT_SYSTEM, ENTAILMENT_USER
from app.pipeline.draft import facts_payload
from app.templates_mgmt.pack import TemplatePack


class EntailmentChecker(Protocol):
    def check(self, statement: Statement, facts: list[Fact], catalogue: Catalogue
              ) -> tuple[bool, str, GenerationRecord | None]: ...


class LLMEntailmentChecker:
    """Second, independent model call: is the statement fully supported by its cited facts?"""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def check(self, statement, facts, catalogue):
        resp = self.llm.complete_structured(
            stage="verify",
            prompt_version=ENTAILMENT_PROMPT_VERSION,
            system=ENTAILMENT_SYSTEM,
            user=ENTAILMENT_USER.format(statement=statement.text,
                                        facts=json.dumps(facts_payload(facts, catalogue))),
            schema_name="entailment",
            json_schema=ENTAILMENT_SCHEMA,
        )
        return resp.data["supported"], resp.data["explanation"], resp.record


def _allowed_figures(facts: list[Fact]):
    numbers, dates = set(), set()
    for f in facts:
        if f.value_type in (ValueType.MONEY, ValueType.PERCENT, ValueType.INTEGER):
            numbers.add(f.value)
        elif f.value_type is ValueType.DATE:
            dates.add(f.value)
            numbers.add(f.value.year)
        n, d = numbers_and_dates(f.display)  # figures inside text facts, e.g. "Balanced (4 out of 7)"
        numbers |= n
        dates |= d
    return numbers, dates


def _finding(code: str, severity: Severity, message: str, s: Statement) -> Finding:
    return Finding(code=code, severity=severity, message=message, slot_id=s.slot_id, statement_id=s.id)


def verify_statements(
    statements: list[Statement],
    record: CaseRecord,
    pack: TemplatePack,
    catalogue: Catalogue,
    entailment: EntailmentChecker | None = None,
) -> tuple[list[Finding], list[GenerationRecord]]:
    findings: list[Finding] = []
    generations: list[GenerationRecord] = []
    conflicted = record.open_conflict_keys()
    prohibited = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in pack.rules.prohibited_phrases]
    words_by_slot: dict[str, int] = {}
    B, W = Severity.BLOCKING, Severity.WARNING

    for s in statements:
        words_by_slot[s.slot_id] = words_by_slot.get(s.slot_id, 0) + len(s.text.split())
        if s.insufficient_evidence:
            findings.append(_finding("INSUFFICIENT_EVIDENCE", B, s.text, s))
            continue

        try:
            slot = pack.slot(s.slot_id)
        except KeyError:
            findings.append(_finding("UNKNOWN_SLOT", B, f"slot {s.slot_id} is not in the template", s))
            continue

        if not s.fact_ids:
            findings.append(_finding("UNCITED_STATEMENT", B, "statement cites no facts", s))

        cited: list[Fact] = []
        for fid in s.fact_ids:
            fact = record.fact(fid)
            if fact is None:
                findings.append(_finding("UNKNOWN_FACT", B, f"cites a fact that does not exist ({fid})", s))
                continue
            label = catalogue.definition(fact.key).label
            if not fact.usable:
                findings.append(_finding("FACT_NOT_VERIFIED", B, f"cites '{label}' which is {fact.status}", s))
            if fact.key in conflicted:
                findings.append(_finding("FACT_IN_CONFLICT", B, f"'{label}' has unresolved conflicting evidence", s))
            if fact.key not in slot.allowed_facts:
                findings.append(_finding("FACT_NOT_ALLOWED", B, f"'{label}' is not permitted in this section", s))
            cited.append(fact)

        numbers, dates = numbers_and_dates(s.text)
        ok_numbers, ok_dates = _allowed_figures(cited)
        for n in sorted(numbers - ok_numbers):
            findings.append(_finding("UNSUPPORTED_FIGURE", B,
                                     f"figure {n:f} does not match any cited fact", s))
        for d in sorted(dates - ok_dates):
            findings.append(_finding("UNSUPPORTED_DATE", B,
                                     f"date {d.isoformat()} does not match any cited fact", s))

        for phrase, rx in prohibited:
            if rx.search(s.text):
                findings.append(_finding("PROHIBITED_PHRASE", B, f"contains prohibited wording '{phrase}'", s))

        if entailment and pack.rules.entailment_check and cited:
            supported, why, generation = entailment.check(s, cited, catalogue)
            if generation:
                generations.append(generation)
            if not supported:
                findings.append(_finding("POSSIBLY_UNSUPPORTED", W, why, s))

    for slot_id, words in words_by_slot.items():
        try:
            limit = pack.slot(slot_id).max_words
        except KeyError:
            continue
        if words > limit:
            findings.append(Finding(code="TOO_LONG", severity=W, slot_id=slot_id,
                                    message=f"{words} words exceeds the {limit}-word limit"))
    return findings, generations
