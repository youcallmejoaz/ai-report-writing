// Mirrors backend/app/domain/schemas.py. Keep in sync (generate from OpenAPI in the build phase).

export type FactStatus = "extracted" | "verified" | "corrected" | "rejected";
export type ReportStatus = "draft" | "in_review" | "changes_requested" | "approved" | "final";

export interface Case {
  id: string;
  client_ref: string;
  team: string;
  template_pack_id: string;
  restricted: boolean;
  created_at: string;
}

export interface SourceRef {
  kind: "span" | "adviser_input";
  span_id: string | null;
  recorded_by: string | null;
  note: string | null;
}

export interface Fact {
  id: string;
  key: string;
  value: string | number | boolean;
  value_type: string;
  display: string; // house-formatted value from the server
  sources: SourceRef[];
  status: FactStatus;
  confidence: number;
  material: boolean;
  verified_by: string | null;
}

export interface Conflict {
  id: string;
  key: string;
  candidate_fact_ids: string[];
  status: "open" | "resolved" | "unresolved";
  reason: string | null;
}

export interface Gap {
  key: string;
  required_by: string[];
  status: "open" | "filled" | "not_applicable";
}

export interface CaseRecord {
  case_id: string;
  facts: Fact[];
  conflicts: Conflict[];
  gaps: Gap[];
  revision: number;
}

export interface SourceSpan {
  id: string;
  document_id: string;
  page: number;
  bbox: { x0: number; y0: number; x1: number; y1: number };
  text: string;
  ocr_confidence: number;
}

export interface Statement {
  id: string;
  slot_id: string;
  text: string;
  fact_ids: string[];
  insufficient_evidence: boolean;
}

export interface Finding {
  id: string;
  code: string;
  severity: "blocking" | "warning";
  message: string;
  slot_id: string | null;
  statement_id: string | null;
  dismissed_by: string | null;
}

export interface Report {
  id: string;
  case_id: string;
  template_pack_id: string;
  template_version: string;
  drafting_model: string;
  prompt_version: string;
  statements: Statement[];
  findings: Finding[];
  status: ReportStatus;
  prepared_by: string;
  revision: number;
  reviewed_slots: string[];
}

export interface TemplateVersionSummary {
  id: string;
  version: string;
  name: string;
  status: string;
  author: string;
  approver: string | null;
  content_hash: string;
}
