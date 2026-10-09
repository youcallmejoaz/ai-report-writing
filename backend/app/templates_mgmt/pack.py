"""Template pack definitions: structure, approved clauses, AI slots, rules. Data, not code.

Template text is rendered with a deliberately tiny placeholder syntax (``{{ fact.key }}``) rather than
a general template engine, so that administrator-edited content cannot execute logic.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.audit import canonical_json, sha256_hex
from app.domain.catalogue import Catalogue

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+\.[a-z_]+)\s*\}\}")


class Condition(BaseModel):
    fact: str
    equals: str | bool | int


class ClauseBlock(BaseModel):
    kind: Literal["clause"]
    clause: str


class FactsTableBlock(BaseModel):
    kind: Literal["facts_table"]
    rows: list[str]


class AISlotBlock(BaseModel):
    kind: Literal["ai"]
    slot: str
    instruction: str
    allowed_facts: list[str]
    required_facts: list[str] = Field(default_factory=list)
    max_words: int = 150

    @model_validator(mode="after")
    def _required_subset(self) -> AISlotBlock:
        missing = set(self.required_facts) - set(self.allowed_facts)
        if missing:
            raise ValueError(f"slot {self.slot}: required_facts not in allowed_facts: {sorted(missing)}")
        return self


Block = Annotated[ClauseBlock | FactsTableBlock | AISlotBlock, Field(discriminator="kind")]


class Section(BaseModel):
    id: str
    heading: str
    when: Condition | None = None
    blocks: list[Block]


class Rules(BaseModel):
    prohibited_phrases: list[str] = Field(default_factory=list)
    entailment_check: bool = False


class Clause(BaseModel):
    id: str
    version: str
    text: str
    owner: str
    approved_by: str
    approved_on: date
    effective_from: date

    @property
    def placeholders(self) -> list[str]:
        return PLACEHOLDER.findall(self.text)


class TemplatePack(BaseModel):
    id: str
    version: str
    name: str
    description: str = ""
    rules: Rules = Field(default_factory=Rules)
    sections: list[Section]
    clauses: dict[str, Clause]
    house_style: str
    examples: dict[str, str] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(mode="json")))

    def ai_slots(self) -> list[AISlotBlock]:
        return [b for s in self.sections for b in s.blocks if isinstance(b, AISlotBlock)]

    def slot(self, slot_id: str) -> AISlotBlock:
        for block in self.ai_slots():
            if block.slot == slot_id:
                return block
        raise KeyError(slot_id)

    def required_keys(self) -> dict[str, list[str]]:
        """Fact key -> section/slot ids that need it (drives gap detection)."""
        needed: dict[str, list[str]] = {}

        def add(key: str, by: str) -> None:
            needed.setdefault(key, []).append(by)

        for section in self.sections:
            if section.when:
                add(section.when.fact, section.id)
            for block in section.blocks:
                if isinstance(block, ClauseBlock):
                    for key in self.clauses[block.clause].placeholders:
                        add(key, f"{section.id}/{block.clause}")
                elif isinstance(block, FactsTableBlock):
                    for key in block.rows:
                        add(key, section.id)
                else:
                    for key in block.required_facts:
                        add(key, block.slot)
        return needed


class PackValidationError(ValueError):
    pass


def validate_pack(pack: TemplatePack, catalogue: Catalogue) -> None:
    errors: list[str] = []
    slot_ids = [s.slot for s in pack.ai_slots()]
    if len(slot_ids) != len(set(slot_ids)):
        errors.append("duplicate AI slot ids")
    for section in pack.sections:
        if section.when and section.when.fact not in catalogue.facts:
            errors.append(f"{section.id}: condition on unknown fact {section.when.fact}")
        for block in section.blocks:
            if isinstance(block, ClauseBlock):
                clause = pack.clauses.get(block.clause)
                if clause is None:
                    errors.append(f"{section.id}: unknown clause {block.clause}")
                    continue
                errors += [f"clause {clause.id}: unknown placeholder {k}"
                           for k in clause.placeholders if k not in catalogue.facts]
            elif isinstance(block, FactsTableBlock):
                errors += [f"{section.id}: unknown fact {k}" for k in block.rows if k not in catalogue.facts]
            else:
                errors += [f"slot {block.slot}: unknown fact {k}"
                           for k in block.allowed_facts if k not in catalogue.facts]
    if errors:
        raise PackValidationError("; ".join(errors))


def load_pack(directory: Path, catalogue: Catalogue) -> TemplatePack:
    definition = yaml.safe_load((directory / "pack.yaml").read_text())
    clauses_raw = yaml.safe_load((directory / "clauses.yaml").read_text())["clauses"]
    clauses = {c["id"]: Clause(**c) for c in clauses_raw}
    examples = {p.stem: p.read_text() for p in sorted((directory / "examples").glob("*.md"))}
    pack = TemplatePack(
        **definition,
        clauses=clauses,
        house_style=(directory / "instructions.md").read_text(),
        examples=examples,
    )
    validate_pack(pack, catalogue)
    return pack
