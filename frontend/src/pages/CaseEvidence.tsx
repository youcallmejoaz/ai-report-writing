import { useState } from "react";
import { api } from "../api/client";
import type { Fact } from "../api/types";
import { SourcePanel } from "./SourcePanel";
import { run, useAsync } from "./useAsync";

const display = (f: Fact) => f.display;

export default function CaseEvidence({ caseId, openReport }: { caseId: string; openReport: (id: string) => void }) {
  const { data: record, error, setError, reload } = useAsync(() => api.record(caseId), [caseId]);
  const { data: reports } = useAsync(() => api.reports(caseId), [caseId]);
  const [selected, setSelected] = useState<Fact | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [input, setInput] = useState({ key: "", value: "", note: "" });

  if (!record) return <p>{error ?? "Loading case record…"}</p>;
  const openConflicts = record.conflicts.filter((c) => c.status === "open");
  const openGaps = record.gaps.filter((g) => g.status === "open");
  const pending = record.facts.filter((f) => f.status === "extracted");

  return (
    <section>
      <h1>Case record <small>revision {record.revision}</small></h1>
      {error && <p className="error">{error}</p>}

      <div className="toolbar">
        <input type="file" onChange={(e) => e.target.files?.[0] && run(() => api.upload(caseId, e.target.files![0]), reload, setError)} />
        <button
          disabled={openConflicts.length > 0}
          title={openConflicts.length ? "Resolve conflicts first" : ""}
          onClick={() => run(async () => openReport((await api.generate(caseId)).id), () => {}, setError)}
        >
          Generate draft report
        </button>
        <span>{pending.length} fact(s) awaiting verification · {openConflicts.length} conflict(s) · {openGaps.length} gap(s)</span>
      </div>

      {reports && reports.length > 0 && (
        <div className="panel">
          <h3>Reports</h3>
          {reports.map((r) => (
            <div key={r.id}>
              <button onClick={() => openReport(r.id)}>Open {r.id}</button> {r.status} · rev {r.revision} · {r.template} ·
              prepared by {r.prepared_by}
            </div>
          ))}
        </div>
      )}

      {openConflicts.map((c) => (
        <div key={c.id} className="panel conflict">
          <h3>Conflicting evidence: {c.key}</h3>
          <input
            placeholder="Reason for your choice (required)"
            value={reasons[c.id] ?? ""}
            onChange={(e) => setReasons({ ...reasons, [c.id]: e.target.value })}
          />
          {c.candidate_fact_ids.map((fid) => {
            const f = record.facts.find((x) => x.id === fid)!;
            return (
              <div key={fid} className="candidate">
                <strong>{display(f)}</strong>
                {f.sources.map((s, i) => <SourcePanel key={i} source={s} />)}
                <button onClick={() => run(() => api.resolveConflict(caseId, c.id, fid, reasons[c.id] ?? ""), reload, setError)}>
                  Use this value
                </button>
              </div>
            );
          })}
          <button onClick={() => run(() => api.resolveConflict(caseId, c.id, null, reasons[c.id] ?? ""), reload, setError)}>
            Leave unresolved (dependent sections will show insufficient evidence)
          </button>
        </div>
      ))}

      {openGaps.length > 0 && (
        <div className="panel gap">
          <h3>Information required by the template but not found in documents</h3>
          <ul>{openGaps.map((g) => <li key={g.key}>{g.key} <small>needed by {g.required_by.join(", ")}</small></li>)}</ul>
          <form onSubmit={(e) => { e.preventDefault(); run(() => api.adviserInput(caseId, input.key, input.value, input.note), reload, setError); }}>
            <select value={input.key} onChange={(e) => setInput({ ...input, key: e.target.value })} required>
              <option value="">Record adviser input for…</option>
              {openGaps.map((g) => <option key={g.key}>{g.key}</option>)}
            </select>
            <input placeholder="Value" value={input.value} onChange={(e) => setInput({ ...input, value: e.target.value })} required />
            <input placeholder="Note / source of information" value={input.note} onChange={(e) => setInput({ ...input, note: e.target.value })} />
            <button>Record</button>
          </form>
        </div>
      )}

      <div className="split">
        <table>
          <thead><tr><th>Fact</th><th>Value</th><th>Status</th><th /></tr></thead>
          <tbody>
            {record.facts.filter((f) => f.status !== "rejected").map((f) => (
              <tr key={f.id} className={selected?.id === f.id ? "selected" : ""} onClick={() => setSelected(f)}>
                <td>{f.key}{f.material && <span className="badge">material</span>}</td>
                <td>{display(f)}</td>
                <td><span className={`status ${f.status}`}>{f.status}</span>{f.verified_by && <small> by {f.verified_by}</small>}</td>
                <td>
                  {f.status === "extracted" && (
                    <button onClick={(e) => { e.stopPropagation(); run(() => api.verifyFact(caseId, f.id), reload, setError); }}>
                      Verify against source
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <aside>
          <h3>Source</h3>
          {selected ? selected.sources.map((s, i) => <SourcePanel key={i} source={s} />) : <p>Select a fact to see where it came from.</p>}
        </aside>
      </div>
    </section>
  );
}
