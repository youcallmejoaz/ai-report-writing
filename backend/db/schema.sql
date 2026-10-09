-- Target PostgreSQL schema (Azure Database for PostgreSQL Flexible Server).
-- The reference implementation keeps these records in memory (app/service.py, Store); this DDL
-- shows the production shape, including case-scoped row-level security and an append-only audit log.

CREATE SCHEMA IF NOT EXISTS app;

-- Roles: the API connects as app_api (managed identity mapped to a database role). Nobody, including
-- app_api, may UPDATE or DELETE audit rows. Retention purges run as app_retention through a reviewed
-- procedure that writes a deletion certificate first.
-- CREATE ROLE app_api; CREATE ROLE app_retention; CREATE ROLE app_readonly_audit;

CREATE TABLE app.cases (
  id                 text PRIMARY KEY,
  client_ref         text NOT NULL,              -- reference into CRM/back office
  team               text NOT NULL,
  template_pack_id   text NOT NULL,
  restricted         boolean NOT NULL DEFAULT false,
  legal_hold         boolean NOT NULL DEFAULT false,
  created_by         text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  retention_class    text NOT NULL,              -- maps to the firm's retention schedule
  delete_after       date                         -- computed from retention_class and case close date
);

CREATE TABLE app.case_assignments (
  case_id  text REFERENCES app.cases(id),
  user_oid text NOT NULL,                         -- Entra ID object id
  PRIMARY KEY (case_id, user_oid)
);

CREATE TABLE app.documents (
  id            text PRIMARY KEY,
  case_id       text NOT NULL REFERENCES app.cases(id),
  sha256        char(64) NOT NULL,
  media_type    text NOT NULL,
  size_bytes    bigint NOT NULL,
  blob_uri      text NOT NULL,                    -- original, never modified
  rendition_uri text,
  doc_type      text,
  doc_type_confirmed_by text,
  uploaded_by   text NOT NULL,
  uploaded_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (case_id, sha256)
);

CREATE TABLE app.source_spans (
  id             text PRIMARY KEY,
  document_id    text NOT NULL REFERENCES app.documents(id),
  page           int NOT NULL,
  bbox           jsonb NOT NULL,
  text           text NOT NULL,
  ocr_confidence real NOT NULL
);

CREATE TABLE app.facts (
  id                text PRIMARY KEY,
  case_id           text NOT NULL REFERENCES app.cases(id),
  key               text NOT NULL,
  value             jsonb NOT NULL,
  value_type        text NOT NULL,
  status            text NOT NULL CHECK (status IN ('extracted','verified','corrected','rejected')),
  material          boolean NOT NULL,
  confidence        real NOT NULL,
  verified_by       text,
  verified_at       timestamptz,
  correction_reason text,
  record_revision   int NOT NULL
);

CREATE TABLE app.fact_sources (
  fact_id     text REFERENCES app.facts(id),
  kind        text NOT NULL CHECK (kind IN ('span','adviser_input')),
  span_id     text REFERENCES app.source_spans(id),
  recorded_by text,
  note        text,
  CHECK ((kind = 'span') = (span_id IS NOT NULL))
);

CREATE TABLE app.conflicts (
  id             text PRIMARY KEY,
  case_id        text NOT NULL REFERENCES app.cases(id),
  key            text NOT NULL,
  candidate_ids  text[] NOT NULL,
  status         text NOT NULL CHECK (status IN ('open','resolved','unresolved')),
  chosen_fact_id text REFERENCES app.facts(id),
  resolved_by    text,
  reason         text,
  CHECK (status = 'open' OR (resolved_by IS NOT NULL AND reason IS NOT NULL))
);

CREATE TABLE app.template_versions (
  pack_id      text NOT NULL,
  version      text NOT NULL,
  status       text NOT NULL CHECK (status IN ('draft','in_review','approved','published','retired')),
  definition   jsonb NOT NULL,
  content_hash char(64) NOT NULL,
  author       text NOT NULL,
  approver     text,
  approved_at  timestamptz,
  published_at timestamptz,
  PRIMARY KEY (pack_id, version),
  CHECK (approver IS NULL OR approver <> author)
);

-- Published/retired template versions are immutable.
CREATE FUNCTION app.forbid_published_template_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('published','retired') AND
     (NEW.definition IS DISTINCT FROM OLD.definition OR NEW.content_hash IS DISTINCT FROM OLD.content_hash) THEN
    RAISE EXCEPTION 'template % % is % and cannot be changed', OLD.pack_id, OLD.version, OLD.status;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER template_immutable BEFORE UPDATE ON app.template_versions
  FOR EACH ROW EXECUTE FUNCTION app.forbid_published_template_change();

CREATE TABLE app.reports (
  id                   text PRIMARY KEY,
  case_id              text NOT NULL REFERENCES app.cases(id),
  pack_id              text NOT NULL,
  pack_version         text NOT NULL,
  template_hash        char(64) NOT NULL,
  drafting_model       text NOT NULL,
  prompt_version       text NOT NULL,
  case_record_revision int NOT NULL,
  status               text NOT NULL,
  prepared_by          text NOT NULL,
  revision             int NOT NULL,
  final_sha256         char(64),
  final_blob_uri       text,                     -- WORM container
  FOREIGN KEY (pack_id, pack_version) REFERENCES app.template_versions(pack_id, version)
);

CREATE TABLE app.statements (
  id                    text PRIMARY KEY,
  report_id             text NOT NULL REFERENCES app.reports(id),
  slot_id               text NOT NULL,
  ordinal               int NOT NULL,
  text                  text NOT NULL,
  fact_ids              text[] NOT NULL,
  insufficient_evidence boolean NOT NULL,
  edited_by             text
);

CREATE TABLE app.review_decisions (
  report_id       text REFERENCES app.reports(id),
  reviewer        text NOT NULL,
  decision        text NOT NULL CHECK (decision IN ('approved','changes_requested')),
  report_revision int NOT NULL,
  comment         text,
  at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.generation_records (
  report_id      text REFERENCES app.reports(id),
  stage          text NOT NULL,
  model          text NOT NULL,
  prompt_version text NOT NULL,
  input_sha256   char(64) NOT NULL,
  output_sha256  char(64) NOT NULL,
  payload_uri    text,                           -- full prompt/response, retained per schedule
  usage          jsonb,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- Append-only, hash-chained audit log (see app/audit.py). Mirrored to an immutable Blob container.
CREATE TABLE app.audit_events (
  seq        bigint PRIMARY KEY,
  at         timestamptz NOT NULL,
  actor      text NOT NULL,
  action     text NOT NULL,
  object_type text NOT NULL,
  object_id  text NOT NULL,
  case_id    text,
  details    jsonb NOT NULL,
  prev_hash  char(64) NOT NULL,
  hash       char(64) NOT NULL UNIQUE
);
REVOKE UPDATE, DELETE, TRUNCATE ON app.audit_events FROM PUBLIC;
-- GRANT INSERT, SELECT ON app.audit_events TO app_api;
-- GRANT SELECT ON app.audit_events TO app_readonly_audit;

-- Case-scoped row-level security. The API sets the caller's identity per transaction:
--   SET LOCAL app.user_oid = '<oid>'; SET LOCAL app.user_teams = 'north,south'; SET LOCAL app.is_compliance = 'false';
ALTER TABLE app.cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY case_scope ON app.cases
  USING (
    current_setting('app.is_compliance', true) = 'true'
    OR EXISTS (SELECT 1 FROM app.case_assignments a
               WHERE a.case_id = cases.id AND a.user_oid = current_setting('app.user_oid', true))
    OR (NOT restricted AND team = ANY (string_to_array(current_setting('app.user_teams', true), ',')))
  );
-- Equivalent policies apply to documents, facts, reports, etc. via case_id.
