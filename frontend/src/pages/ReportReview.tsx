import { useState } from "react";
import { api } from "../api/client";
import type { Statement } from "../api/types";
import { SourcePanel } from "./SourcePanel";
import { run, useAsync } from "./useAsync";

/** Findings first, then each AI-drafted section with statement-level evidence. */
export default function ReportReview({ reportId }: { reportId: string }) {
  const { data: report, error, setError, reload } = useAsync(() => api.report(reportId), [reportId]);
  const { data: record } = useAsync(
    () => (report ? api.record(report.case_id) : Promise.resolve(null)),
    [report?.case_id],
  );
  const [focus, setFocus] = useState<Statement | null>(null);
  const [comment, setComment] = useState("");

  if (!report) return <p>{error ?? "Loading report…"}</p>;
  const open = report.findings.filter((f) => !f.dismissed_by);
  const slots = [...new Set(report.statements.map((s) => s.slot_id))];

  return (
    <section>
      <h1>
        Report {report.id} <small>rev {report.revision} · {report.status}</small>
      </h1>
      <p className="meta">
        Template {report.template_pack_id}@{report.template_version} · model {report.drafting_model} · prompt{" "}
        {report.prompt_version} · prepared by {report.prepared_by}
      </p>
      {error && <p className="error">{error}</p>}

      <div className="panel findings">
        <h3>Verification findings ({open.length})</h3>
        {open.length === 0 && <p>No open findings.</p>}
        <ul>
          {open.map((f) => (
            <li key={f.id} className={f.severity}>
              <strong>{f.severity === "blocking" ? "Blocking" : "Warning"}</strong> {f.code} in {f.slot_id}: {f.message}
            </li>
          ))}
        </ul>
      </div>

      <div className="split">
        <div>
          {slots.map((slot) => (
            <div key={slot} className="panel slot">
              <h3>
                {slot} <span className="badge ai">AI-drafted</span>
                {report.reviewed_slots.includes(slot) ? (
                  <span className="badge ok">reviewed</span>
                ) : (
                  report.status === "in_review" && (
                    <button onClick={() => run(() => api.markReviewed(report.id, slot), reload, setError)}>
                      Mark section reviewed
                    </button>
                  )
                )}
              </h3>
              {report.statements.filter((s) => s.slot_id === slot).map((s) => (
                <p
                  key={s.id}
                  className={`statement ${s.insufficient_evidence ? "insufficient" : ""} ${focus?.id === s.id ? "selected" : ""}`}
                  onClick={() => setFocus(s)}
                >
                  {s.text}
                </p>
              ))}
            </div>
          ))}
        </div>
        <aside>
          <h3>Evidence for selected statement</h3>
          {!focus && <p>Click a sentence to see the facts and source passages it relies on.</p>}
          {focus && record && focus.fact_ids.map((fid) => {
            const fact = record.facts.find((f) => f.id === fid);
            if (!fact) return <p key={fid} className="error">Unknown fact {fid}</p>;
            return (
              <div key={fid}>
                <strong>{fact.key}</strong> = {fact.display} <small>({fact.status} by {fact.verified_by})</small>
                {fact.sources.map((src, i) => <SourcePanel key={i} source={src} />)}
              </div>
            );
          })}
        </aside>
      </div>

      <div className="toolbar">
        {report.status === "draft" && <button onClick={() => run(() => api.submit(report.id), reload, setError)}>Submit for review</button>}
        {report.status === "in_review" && (
          <>
            <input placeholder="Reviewer comment" value={comment} onChange={(e) => setComment(e.target.value)} />
            <button onClick={() => run(() => api.approve(report.id, comment), reload, setError)}>Approve</button>
            <button onClick={() => run(() => api.requestChanges(report.id, comment), reload, setError)}>Request changes</button>
          </>
        )}
        {report.status === "approved" && <button onClick={() => run(() => api.finalise(report.id), reload, setError)}>Finalise</button>}
        <button onClick={() => run(() => api.download(report.id, "review"), () => {}, setError)}>Download review copy</button>
        {report.status === "final" && (
          <>
            <button onClick={() => run(() => api.download(report.id, "client"), () => {}, setError)}>Download client copy</button>
            <button onClick={() => run(() => api.download(report.id, "evidence"), () => {}, setError)}>Download evidence appendix</button>
          </>
        )}
      </div>
    </section>
  );
}
