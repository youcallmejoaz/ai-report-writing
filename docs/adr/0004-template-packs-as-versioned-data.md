# ADR 0004: Template packs as versioned, approved data

**Status:** Proposed
**Context:** Administrators must be able to change templates, approved wording and instructions without code changes, under compliance control.
**Decision:**
- Template packs (structure, clauses, instructions, examples, rules and Word layout) are data held in a registry.
- Lifecycle: draft → in_review → approved → published → retired.
- Maker-checker: the author cannot approve their own version.
- Published versions are immutable and identified by content hash.
- Every report records the pack, clause, prompt and model versions it used.
**Consequences:**
- A schema and validator for pack definitions is needed (`backend/app/templates_mgmt/`).
- Changes go through regression evaluation before publication.
