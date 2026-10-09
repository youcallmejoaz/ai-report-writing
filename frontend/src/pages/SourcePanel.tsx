import { api } from "../api/client";
import type { SourceRef } from "../api/types";
import { useAsync } from "./useAsync";

/** Shows the exact source of a fact: document, page and passage (production: page image with bbox highlight). */
export function SourcePanel({ source }: { source: SourceRef }) {
  if (source.kind === "adviser_input") {
    return (
      <div className="source">
        Adviser input by <strong>{source.recorded_by}</strong>
        {source.note && <>: {source.note}</>}
      </div>
    );
  }
  return <SpanSource spanId={source.span_id!} />;
}

function SpanSource({ spanId }: { spanId: string }) {
  const { data, error } = useAsync(() => api.span(spanId), [spanId]);
  if (error) return <div className="error">{error}</div>;
  if (!data) return <div className="source">Loading…</div>;
  return (
    <div className="source">
      <div className="source-meta">
        {data.document.filename} · page {data.span.page} · sha256 {data.document.sha256.slice(0, 12)}…
        {data.span.ocr_confidence < 0.8 && <span className="badge warn">low OCR confidence</span>}
      </div>
      <mark>{data.span.text}</mark>
    </div>
  );
}
