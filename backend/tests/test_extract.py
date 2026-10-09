import pytest

from app.domain.schemas import Document
from app.llm.client import ScriptedLLMClient
from app.pipeline.extract import (
    Candidate,
    LLMExtractor,
    PlainTextLayoutProvider,
    classify,
    extract_document,
    validate_candidates,
)
from app.pipeline.ingest import AllowAllScanner, IngestError, ingest
from tests.conftest import ROOT


def _doc(name):
    data = (ROOT / "samples" / name).read_bytes()
    doc = Document(case_id="c1", filename=name, media_type="text/plain", sha256="x", size_bytes=len(data),
                   uploaded_by="alice")
    return doc, PlainTextLayoutProvider().analyze(doc, data)


def test_classification_and_cited_extraction(catalogue):
    from app.pipeline.extract import LabelMatchingExtractor

    doc, spans = _doc("pension_statement.txt")
    assert classify(spans, catalogue) == "pension_statement"
    result, _ = extract_document(doc, spans, "pension_statement", LabelMatchingExtractor(), catalogue)
    by_key = {f.key: f for f in result.fields}
    fund = by_key["pension.fund_value"]
    span = next(s for s in spans if s.id == fund.span_id)
    assert "125,400.00" in span.text and span.page == 1
    assert str(fund.value) == "125400.00"


def test_value_not_in_cited_span_is_rejected(catalogue):
    """A model that cites the right line but reports the wrong number is caught by the quote check."""
    doc, spans = _doc("pension_statement.txt")
    fund_span = next(s for s in spans if "Total fund value" in s.text)
    schema = catalogue.document_types["pension_statement"]
    result = validate_candidates(doc, schema, spans, [Candidate("pension.fund_value", "£152,400.00", fund_span.id)],
                                 catalogue)
    assert result.fields == []
    assert "quote check" in result.issues[0].reason


def test_fabricated_span_reference_is_rejected(catalogue):
    doc, spans = _doc("pension_statement.txt")
    schema = catalogue.document_types["pension_statement"]
    result = validate_candidates(doc, schema, spans, [Candidate("pension.fund_value", "£125,400.00", "span_fake")],
                                 catalogue)
    assert result.fields == [] and "does not exist" in result.issues[0].reason


def test_llm_extractor_output_passes_same_gate(catalogue):
    doc, spans = _doc("pension_statement.txt")
    fund_span = next(s for s in spans if "Total fund value" in s.text)
    def field(key, value, span_id):
        return {"key": key, "found": value is not None, "value": value, "span_id": span_id, "notes": None}

    llm = ScriptedLLMClient([{"fields": [
        field("pension.fund_value", "£125,400.00", fund_span.id),
        field("pension.annual_charge_pct", "0.5%", fund_span.id),
        field("pension.policy_number", None, None),
    ]}])
    result, record = extract_document(doc, spans, "pension_statement", LLMExtractor(llm), catalogue)
    assert [f.key for f in result.fields] == ["pension.fund_value"]
    assert result.issues[0].key == "pension.annual_charge_pct"  # hallucinated value rejected
    assert "pension.policy_number" in result.not_found
    assert record.prompt_version.startswith("extract-") and len(record.input_sha256) == 64
    # document text reaches the extraction prompt only as quoted data
    assert f'{fund_span.id} | p1 | "Total fund value' in llm.calls[0]["user"]


def test_ingest_rejects_disguised_and_empty_files():
    with pytest.raises(IngestError):
        ingest(case_id="c", filename="statement.pdf", data=b"MZ\x90\x00binary", uploaded_by="a",
               scanner=AllowAllScanner())
    with pytest.raises(IngestError):
        ingest(case_id="c", filename="empty.pdf", data=b"", uploaded_by="a", scanner=AllowAllScanner())

    class Infected:
        def scan(self, data):
            return False

    with pytest.raises(IngestError, match="malware"):
        ingest(case_id="c", filename="x.pdf", data=b"%PDF-1.7 ...", uploaded_by="a", scanner=Infected())


def test_ingest_fingerprints_pdf():
    f = ingest(case_id="c", filename="x.pdf", data=b"%PDF-1.7 test", uploaded_by="a",
               scanner=AllowAllScanner())
    assert f.document.media_type == "application/pdf" and len(f.document.sha256) == 64
