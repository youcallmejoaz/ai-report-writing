import { api } from "../api/client";
import { useAsync } from "./useAsync";

/** Read-only registry view. Build phase adds: draft editing, clause diffing, submit/approve/publish actions. */
export default function TemplateAdmin() {
  const { data, error } = useAsync(api.templates, []);
  return (
    <section>
      <h1>Template registry</h1>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr><th>Pack</th><th>Version</th><th>Status</th><th>Author</th><th>Approver</th><th>Content hash</th></tr>
        </thead>
        <tbody>
          {data?.map((t) => (
            <tr key={`${t.id}@${t.version}`}>
              <td>{t.name}<br /><small>{t.id}</small></td>
              <td>{t.version}</td>
              <td><span className={`status ${t.status}`}>{t.status}</span></td>
              <td>{t.author}</td>
              <td>{t.approver ?? "—"}</td>
              <td><code>{t.content_hash.slice(0, 16)}…</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
