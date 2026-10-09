# ADR 0005: Append-only, hash-chained audit log with WORM archive

**Status:** Proposed
**Context:** The firm must be able to show who did what, when, and with which AI outputs, possibly years later, to compliance, the FOS or the FCA.
**Decision:**
- Every material action emits an `AuditEvent` whose hash covers its content and the previous event's hash (`backend/app/audit.py`).
- Events are indexed in PostgreSQL and copied continuously to a Blob container with a time-based immutability policy.
**Consequences:**
- Tampering is detectable by re-verifying the chain.
- Storage grows with usage, and retention follows the firm's schedule.
