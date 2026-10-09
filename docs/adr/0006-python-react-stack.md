# ADR 0006: Python (FastAPI) backend and workers, React/TypeScript frontend, Bicep IaC

**Status:** Proposed
**Context:** The system relies on document processing and LLM integration, and needs a maintainable stack that other engineers can take over.
**Decision:**
- Python 3.12+ with FastAPI, Pydantic v2 and SQLAlchemy 2. Word generation uses python-docx (Open XML).
- React with TypeScript (Vite) for the UI.
- Bicep for Azure infrastructure.
**Consequences:**
- Python has a broad ecosystem for document and AI work.
- Strict typing (Pydantic, TypeScript) keeps the contracts between stages explicit.
- A .NET team could take over the infrastructure and UI easily, and the backend would need Python skills.
