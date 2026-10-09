"""Loaders for the fact catalogue and per-document-type extraction schemas (configuration, not code)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.domain.values import ValueType

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class FactDefinition(BaseModel):
    key: str
    type: ValueType
    label: str
    material: bool = False
    adviser_input: bool = False


class FieldSpec(BaseModel):
    key: str
    labels: list[str]


class DocumentTypeSchema(BaseModel):
    doc_type: str
    description: str
    classify_keywords: list[str] = Field(default_factory=list)
    fields: list[FieldSpec]


class Catalogue(BaseModel):
    facts: dict[str, FactDefinition]
    document_types: dict[str, DocumentTypeSchema]

    def definition(self, key: str) -> FactDefinition:
        try:
            return self.facts[key]
        except KeyError as exc:
            raise KeyError(f"unknown fact key {key!r}; add it to the fact catalogue") from exc


def load_catalogue(config_dir: Path = CONFIG_DIR) -> Catalogue:
    facts_raw = yaml.safe_load((config_dir / "fact_catalogue.yaml").read_text())["facts"]
    facts = {k: FactDefinition(key=k, **v) for k, v in facts_raw.items()}
    types_raw = yaml.safe_load((config_dir / "extraction_schemas.yaml").read_text())["document_types"]
    doc_types: dict[str, DocumentTypeSchema] = {}
    for name, spec in types_raw.items():
        fields = [FieldSpec(key=k, labels=v["labels"]) for k, v in spec["fields"].items()]
        unknown = [f.key for f in fields if f.key not in facts]
        if unknown:
            raise ValueError(f"extraction schema {name!r} references unknown fact keys: {unknown}")
        doc_types[name] = DocumentTypeSchema(
            doc_type=name,
            description=spec["description"],
            classify_keywords=spec.get("classify_keywords", []),
            fields=fields,
        )
    return Catalogue(facts=facts, document_types=doc_types)


@lru_cache(maxsize=1)
def default_catalogue() -> Catalogue:
    return load_catalogue()
