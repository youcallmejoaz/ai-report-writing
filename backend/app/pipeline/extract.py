"""Stage 2: extract. Layout/OCR into citable spans, classify, then schema-driven field extraction.

Whatever produces candidate fields (generative model, custom Document Intelligence model, or the
deterministic label matcher), every candidate passes the same gate in ``validate_candidates``:
the cited span must exist in this document, the value must parse to the catalogue type, and the value
must actually appear in the cited span text (quote check).
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Protocol

from app.domain.catalogue import Catalogue, DocumentTypeSchema
from app.domain.schemas import (
    BBox,
    Document,
    ExtractedField,
    ExtractionIssue,
    ExtractionResult,
    GenerationRecord,
    SourceSpan,
)
from app.domain.values import ValueParseError, ValueType, numbers_and_dates, parse_value
from app.llm.client import LLMClient
from app.llm.prompts import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    extraction_schema,
)
from app.pipeline.ingest import DOCX, TEXT

LOW_CONFIDENCE = 0.80

# --------------------------------------------------------------------------- layout


class LayoutProvider(Protocol):
    def analyze(self, document: Document, data: bytes) -> list[SourceSpan]: ...


class PlainTextLayoutProvider:
    """Plain text: form feed separates pages, each non-empty line is a span. bbox y = line index."""

    def analyze(self, document: Document, data: bytes) -> list[SourceSpan]:
        spans: list[SourceSpan] = []
        for page_no, page in enumerate(data.decode("utf-8").split("\f"), start=1):
            for line_no, line in enumerate(page.splitlines()):
                if line.strip():
                    spans.append(
                        SourceSpan(
                            document_id=document.id,
                            page=page_no,
                            bbox=BBox(x0=0, y0=line_no, x1=len(line), y1=line_no + 1),
                            text=line.strip(),
                        )
                    )
        return spans


class DocxLayoutProvider:
    """Word documents parsed locally: paragraphs and table cells become spans (single logical page)."""

    def analyze(self, document: Document, data: bytes) -> list[SourceSpan]:
        import docx

        d = docx.Document(io.BytesIO(data))
        texts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                texts.append(": ".join(c.text.strip() for c in row.cells if c.text.strip()))
        return [
            SourceSpan(document_id=document.id, page=1, bbox=BBox(x0=0, y0=i, x1=1, y1=i + 1), text=t.strip())
            for i, t in enumerate(texts)
            if t.strip()
        ]


class AzureDocumentIntelligenceLayoutProvider:
    """prebuilt-layout via a private endpoint in UK South, managed identity auth.

    Paragraphs become spans with page number and bounding box (converted from polygon) so reviewers
    can be taken to the exact region of the page. Word-level confidence is aggregated per paragraph.
    """

    def __init__(self, endpoint: str) -> None:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.identity import DefaultAzureCredential

        self._client = DocumentIntelligenceClient(endpoint=endpoint, credential=DefaultAzureCredential())

    def analyze(self, document: Document, data: bytes) -> list[SourceSpan]:
        poller = self._client.begin_analyze_document("prebuilt-layout", body=io.BytesIO(data))
        result = poller.result()
        word_conf: dict[int, list[float]] = {}
        for page in result.pages or []:
            word_conf[page.page_number] = [w.confidence for w in page.words or []]
        spans: list[SourceSpan] = []
        for para in result.paragraphs or []:
            region = para.bounding_regions[0]
            xs, ys = region.polygon[0::2], region.polygon[1::2]
            confs = word_conf.get(region.page_number) or [1.0]
            spans.append(
                SourceSpan(
                    document_id=document.id,
                    page=region.page_number,
                    bbox=BBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys)),
                    text=para.content,
                    ocr_confidence=min(confs),  # conservative; refine to per-span words in build phase
                )
            )
        return spans


def layout_for(media_type: str) -> LayoutProvider:
    if media_type == TEXT:
        return PlainTextLayoutProvider()
    if media_type == DOCX:
        return DocxLayoutProvider()
    raise NotImplementedError(
        f"{media_type} requires Azure Document Intelligence (configure DOCUMENT_INTELLIGENCE_ENDPOINT)"
    )


# --------------------------------------------------------------------------- classification


def classify(spans: list[SourceSpan], catalogue: Catalogue) -> str | None:
    """Deterministic keyword rules first; None means 'ask the model / ask the user'."""
    head = " ".join(s.text.lower() for s in spans[:15])
    for doc_type, schema in catalogue.document_types.items():
        if any(k in head for k in schema.classify_keywords):
            return doc_type
    return None


# --------------------------------------------------------------------------- field candidates


@dataclass(frozen=True)
class Candidate:
    key: str
    raw_value: str | None
    span_id: str | None
    confidence: float = 1.0
    notes: str | None = None


class ExtractionModel(Protocol):
    def extract(
        self, schema: DocumentTypeSchema, spans: list[SourceSpan]
    ) -> tuple[list[Candidate], GenerationRecord | None]: ...


class LabelMatchingExtractor:
    """Deterministic extractor for well-labelled forms ("Label: value" on one line).

    Used as a cheap first pass in production for known layouts, and as the extractor in tests/demo.
    """

    def extract(self, schema, spans):
        candidates: list[Candidate] = []
        for spec in schema.fields:
            hits: list[tuple[str, str]] = []
            for span in spans:
                for label in spec.labels:
                    m = re.match(rf"^\s*{re.escape(label)}\s*[:\-–]\s*(.+)$", span.text, re.IGNORECASE)
                    if m:
                        hits.append((m[1].strip(), span.id))
                        break
            distinct = {v for v, _ in hits}
            if len(distinct) == 1:
                value, span_id = hits[0]
                candidates.append(Candidate(spec.key, value, span_id, confidence=0.95))
            elif len(distinct) > 1:
                notes = "multiple values in document: " + ", ".join(s for _, s in hits)
                candidates.append(Candidate(spec.key, None, None, notes=notes))
            else:
                candidates.append(Candidate(spec.key, None, None))
        return candidates, None


class LLMExtractor:
    """Generative extraction with strict JSON Schema output and one span id per field."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def extract(self, schema, spans):
        keys = [f.key for f in schema.fields]
        user = EXTRACTION_USER.format(
            doc_type=schema.doc_type,
            description=schema.description,
            field_list="\n".join(f"- {f.key}: {', '.join(f.labels)}" for f in schema.fields),
            spans="\n".join(f"{s.id} | p{s.page} | {json.dumps(s.text)}" for s in spans),
        )
        resp = self.llm.complete_structured(
            stage="extract",
            prompt_version=EXTRACTION_PROMPT_VERSION,
            system=EXTRACTION_SYSTEM,
            user=user,
            schema_name="extraction",
            json_schema=extraction_schema(keys),
        )
        candidates = [
            Candidate(
                key=f["key"],
                raw_value=f["value"] if f["found"] else None,
                span_id=f["span_id"] if f["found"] else None,
                confidence=0.85,  # generative extraction is never auto-accepted for material facts
                notes=f.get("notes"),
            )
            for f in resp.data["fields"]
        ]
        return candidates, resp.record


# --------------------------------------------------------------------------- validation gate


def _quote_check(value, value_type: ValueType, raw: str, span_text: str) -> bool:
    """The extracted value must be visible in the cited span, not merely somewhere in the document."""
    if value_type is ValueType.TEXT:
        return raw.lower() in span_text.lower()
    if value_type is ValueType.BOOLEAN:
        return raw.lower() in span_text.lower()
    numbers, dates = numbers_and_dates(span_text)
    if value_type is ValueType.DATE:
        return value in dates
    return value in numbers


def validate_candidates(
    document: Document,
    schema: DocumentTypeSchema,
    spans: list[SourceSpan],
    candidates: list[Candidate],
    catalogue: Catalogue,
) -> ExtractionResult:
    by_id = {s.id: s for s in spans}
    fields: list[ExtractedField] = []
    issues: list[ExtractionIssue] = []
    not_found: list[str] = []
    allowed = {f.key for f in schema.fields}
    for c in candidates:
        if c.key not in allowed:
            issues.append(ExtractionIssue(key=c.key, document_id=document.id, reason="field not in schema"))
            continue
        if c.raw_value is None:
            if c.notes:
                issues.append(ExtractionIssue(key=c.key, document_id=document.id, reason=c.notes))
            else:
                not_found.append(c.key)
            continue
        span = by_id.get(c.span_id or "")
        if span is None:
            issues.append(ExtractionIssue(key=c.key, document_id=document.id,
                                          reason="cited span does not exist in this document",
                                          raw_value=c.raw_value, span_id=c.span_id))
            continue
        definition = catalogue.definition(c.key)
        try:
            value = parse_value(c.raw_value, definition.type)
        except ValueParseError as exc:
            issues.append(ExtractionIssue(key=c.key, document_id=document.id, reason=str(exc),
                                          raw_value=c.raw_value, span_id=span.id))
            continue
        if not _quote_check(value, definition.type, c.raw_value, span.text):
            issues.append(ExtractionIssue(key=c.key, document_id=document.id,
                                          reason="value not found in cited span (quote check failed)",
                                          raw_value=c.raw_value, span_id=span.id))
            continue
        fields.append(
            ExtractedField(
                key=c.key,
                raw_value=c.raw_value,
                value=value,
                value_type=definition.type,
                span_id=span.id,
                document_id=document.id,
                confidence=min(c.confidence, span.ocr_confidence),
            )
        )
    return ExtractionResult(
        document_id=document.id, doc_type=schema.doc_type, fields=fields, issues=issues, not_found=not_found
    )


def extract_document(
    document: Document,
    spans: list[SourceSpan],
    doc_type: str,
    model: ExtractionModel,
    catalogue: Catalogue,
) -> tuple[ExtractionResult, GenerationRecord | None]:
    schema = catalogue.document_types[doc_type]
    candidates, record = model.extract(schema, spans)
    return validate_candidates(document, schema, spans, candidates, catalogue), record
