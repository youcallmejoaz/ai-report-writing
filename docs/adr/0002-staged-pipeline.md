# ADR 0002: Staged pipeline with typed contracts between stages

**Status:** Proposed
**Context:** A single "read documents and write the report" prompt is hard to test, hard to audit and open to prompt injection from document content.
**Decision:** Split processing into ingest, extract, evidence, draft, verify, assemble and review. Each stage persists typed outputs (Pydantic contracts in `backend/app/domain/schemas.py`). Stages communicate through queues.
**Consequences:**
- More components to operate.
- In return, each stage can be evaluated on its own, re-run without repeating earlier stages, and audited.
- Failures are contained within a stage.
