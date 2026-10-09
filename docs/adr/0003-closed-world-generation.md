# ADR 0003: Closed-world generation with mandatory citations

**Status:** Proposed
**Context:** The firm must avoid invented or unsupported statements in client-facing reports.
**Decision:**
- The drafting model receives only verified facts permitted for the slot it is writing. It never receives raw documents.
- Output must be a list of statements, each citing fact IDs.
- Missing support must produce an `INSUFFICIENT_EVIDENCE` statement, never a guess.
- A deterministic verifier (`backend/app/pipeline/verify.py`) rejects uncited statements, citations of unverified or unknown facts, numbers that do not match cited facts, use of facts in unresolved conflict, and prohibited phrases.
**Consequences:**
- Some prose is more constrained than a free-form draft would be.
- Gaps become visible work items rather than being hidden in fluent text.
