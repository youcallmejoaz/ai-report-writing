import { useState } from "react";
import { api } from "../api/client";
import { run, useAsync } from "./useAsync";

export default function CaseList({ open }: { open: (caseId: string) => void }) {
  const { data: cases, error, setError, reload } = useAsync(api.listCases, []);
  const [ref, setRef] = useState("");
  const [team, setTeam] = useState("north");

  return (
    <section>
      <h1>Cases</h1>
      {error && <p className="error">{error}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(() => api.createCase(ref, team), reload, setError);
        }}
      >
        <input placeholder="CRM client reference" value={ref} onChange={(e) => setRef(e.target.value)} required />
        <input placeholder="Team" value={team} onChange={(e) => setTeam(e.target.value)} required />
        <button>Create case</button>
      </form>
      <table>
        <thead>
          <tr><th>Client ref</th><th>Team</th><th>Template</th><th>Created</th><th /></tr>
        </thead>
        <tbody>
          {cases?.map((c) => (
            <tr key={c.id}>
              <td>{c.client_ref}{c.restricted && <span className="badge">restricted</span>}</td>
              <td>{c.team}</td>
              <td>{c.template_pack_id}</td>
              <td>{new Date(c.created_at).toLocaleString("en-GB")}</td>
              <td><button onClick={() => open(c.id)}>Open</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
