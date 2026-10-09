import type { Case, CaseRecord, Report, SourceSpan, TemplateVersionSummary } from "./types";

// Production: acquire an Entra ID access token with MSAL (@azure/msal-browser) for the API scope and
// send it as a bearer token. Local development: the backend accepts X-Dev-User when APP_ENV=local.
let devUser = "alice";
export const setDevUser = (u: string) => (devUser = u);
export const getDevUser = () => devUser;

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Dev-User": devUser };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listCases: () => request<Case[]>("GET", "/cases"),
  createCase: (client_ref: string, team: string) => request<Case>("POST", "/cases", { client_ref, team }),
  upload: (caseId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request("POST", `/cases/${caseId}/documents`, form);
  },
  record: (caseId: string) => request<CaseRecord>("GET", `/cases/${caseId}/record`),
  span: (spanId: string) =>
    request<{ span: SourceSpan; document: { id: string; filename: string; sha256: string } }>("GET", `/spans/${spanId}`),
  verifyFact: (caseId: string, factId: string) => request("POST", `/cases/${caseId}/facts/${factId}/verify`),
  resolveConflict: (caseId: string, conflictId: string, chosen_fact_id: string | null, reason: string) =>
    request("POST", `/cases/${caseId}/conflicts/${conflictId}/resolve`, { chosen_fact_id, reason }),
  adviserInput: (caseId: string, key: string, value: string, note?: string) =>
    request("POST", `/cases/${caseId}/adviser-inputs`, { key, value, note }),
  reports: (caseId: string) =>
    request<{ id: string; status: string; revision: number; prepared_by: string; template: string }[]>(
      "GET", `/cases/${caseId}/reports`),
  generate: (caseId: string) => request<Report>("POST", `/cases/${caseId}/reports`),
  report: (reportId: string) => request<Report>("GET", `/reports/${reportId}`),
  submit: (reportId: string) => request<Report>("POST", `/reports/${reportId}/submit`),
  markReviewed: (reportId: string, slot: string) => request<Report>("POST", `/reports/${reportId}/slots/${slot}/reviewed`),
  approve: (reportId: string, comment?: string) => request<Report>("POST", `/reports/${reportId}/approve`, { comment }),
  requestChanges: (reportId: string, comment: string) =>
    request<Report>("POST", `/reports/${reportId}/request-changes`, { comment }),
  finalise: (reportId: string) => request<Report>("POST", `/reports/${reportId}/finalise`),
  download: async (reportId: string, variant: "review" | "client" | "evidence") => {
    const res = await fetch(`/api/reports/${reportId}/download?variant=${variant}`, {
      headers: { "X-Dev-User": devUser },
    });
    if (!res.ok) throw new Error(res.statusText);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `${reportId}-${variant}.docx` });
    a.click();
    URL.revokeObjectURL(url);
  },
  templates: () => request<TemplateVersionSummary[]>("GET", "/templates"),
};
