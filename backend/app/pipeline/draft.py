"""Stage 4: draft. Fill each AI slot from verified facts only (closed world).

The drafting model is given, per slot: the slot instruction, house style, approved examples and the
verified facts the template allows for that slot. It never receives document text. Missing required
facts short-circuit to an INSUFFICIENT_EVIDENCE statement without calling the model at all.
"""

from __future__ import annotations

import json
from typing import Protocol

from app.domain.catalogue import Catalogue
from app.domain.schemas import (
    INSUFFICIENT_EVIDENCE,
    CaseRecord,
    ConflictStatus,
    Fact,
    GenerationRecord,
    Statement,
)
from app.llm.client import LLMClient
from app.llm.prompts import DRAFTING_PROMPT_VERSION, DRAFTING_SCHEMA, DRAFTING_SYSTEM, DRAFTING_USER
from app.templates_mgmt.pack import AISlotBlock, Section, TemplatePack


class DraftingBlocked(RuntimeError):
    pass


class DraftingModel(Protocol):
    name: str
    prompt_version: str

    def draft_slot(
        self, pack: TemplatePack, slot: AISlotBlock, facts: list[Fact], catalogue: Catalogue
    ) -> tuple[list[Statement], GenerationRecord | None]: ...


def facts_payload(facts: list[Fact], catalogue: Catalogue) -> list[dict]:
    return [
        {"fact_id": f.id, "key": f.key, "label": catalogue.definition(f.key).label, "display": f.display}
        for f in facts
    ]


class LLMDraftingModel:
    prompt_version = DRAFTING_PROMPT_VERSION

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.name = llm.model

    def draft_slot(self, pack, slot, facts, catalogue):
        user = DRAFTING_USER.format(
            instruction=slot.instruction,
            max_words=slot.max_words,
            examples=pack.examples.get(slot.slot, "(none)"),
            facts=json.dumps(facts_payload(facts, catalogue), indent=2),
        )
        resp = self.llm.complete_structured(
            stage="draft",
            prompt_version=self.prompt_version,
            system=DRAFTING_SYSTEM.format(house_style=pack.house_style),
            user=user,
            schema_name="slot_draft",
            json_schema=DRAFTING_SCHEMA,
        )
        statements = [
            Statement(
                slot_id=slot.slot,
                text=s["text"],
                fact_ids=s["fact_ids"],
                insufficient_evidence=s["insufficient_evidence"],
            )
            for s in resp.data["statements"]
        ]
        return statements, resp.record


class ScriptedDraftingModel:
    """Stand-in for the LLM in demos/tests: per-slot (text, [fact keys]) pairs written in advance.

    Keys are resolved to the fact ids provided for the slot; an unknown key is passed through as a
    dangling id so that the verifier's handling of bad citations can be exercised.
    """

    prompt_version = "scripted"

    def __init__(self, script: dict[str, list[tuple[str, list[str]]]], name: str = "scripted-drafter") -> None:
        self.script = script
        self.name = name

    def draft_slot(self, pack, slot, facts, catalogue):
        by_key = {f.key: f.id for f in facts}
        out = [
            Statement(slot_id=slot.slot, text=text, fact_ids=[by_key.get(k, f"missing:{k}") for k in keys])
            for text, keys in self.script.get(slot.slot, [])
        ]
        return out, None


class FactListingDraftingModel:
    """Minimal offline fallback: one plain statement per allowed fact. Used when no model is configured."""

    name = "fact-listing-fallback"
    prompt_version = "none"

    def draft_slot(self, pack, slot, facts, catalogue):
        return [
            Statement(slot_id=slot.slot, text=f"{catalogue.definition(f.key).label}: {f.display}.",
                      fact_ids=[f.id])
            for f in facts
        ], None


def section_included(section: Section, record: CaseRecord) -> bool:
    if section.when is None:
        return True
    fact = record.usable_fact(section.when.fact)
    if fact is None:
        raise DraftingBlocked(
            f"section '{section.id}' depends on {section.when.fact}, which is not verified"
        )
    return fact.value == section.when.equals


def draft_report(
    pack: TemplatePack, record: CaseRecord, model: DraftingModel, catalogue: Catalogue
) -> tuple[list[Statement], list[GenerationRecord]]:
    open_conflicts = [c.key for c in record.conflicts if c.status is ConflictStatus.OPEN]
    if open_conflicts:
        raise DraftingBlocked(f"resolve conflicting evidence before drafting: {sorted(open_conflicts)}")

    statements: list[Statement] = []
    generations: list[GenerationRecord] = []
    for section in pack.sections:
        if not section_included(section, record):
            continue
        for block in section.blocks:
            if not isinstance(block, AISlotBlock):
                continue
            facts = [f for k in block.allowed_facts if (f := record.usable_fact(k)) is not None]
            present = {f.key for f in facts}
            missing = [k for k in block.required_facts if k not in present]
            if missing:
                labels = ", ".join(catalogue.definition(k).label for k in missing)
                statements.append(
                    Statement(
                        slot_id=block.slot,
                        text=f"[{INSUFFICIENT_EVIDENCE}: verified evidence needed for {labels}]",
                        fact_ids=[],
                        insufficient_evidence=True,
                    )
                )
                continue
            slot_statements, generation = model.draft_slot(pack, block, facts, catalogue)
            for s in slot_statements:
                if s.insufficient_evidence and not s.text.startswith(f"[{INSUFFICIENT_EVIDENCE}"):
                    s.text = f"[{INSUFFICIENT_EVIDENCE}: {s.text}]"
            statements.extend(slot_statements)
            if generation:
                generations.append(generation)
    return statements, generations
