# ADR 0001: Azure UK South with Azure OpenAI Standard regional deployments

**Status:** Proposed
**Context:** The firm is Microsoft-centric and processes confidential personal and financial data under UK GDPR and FCA rules. It wants processing to stay in the UK.
**Decision:** Host everything in UK South, with UK West as the backup and DR target. Use Azure OpenAI **Standard (regional)** deployments only. Deny Global and DataZone deployment SKUs and non-UK locations through Azure Policy. Apply for modified abuse monitoring.
**Consequences:**
- Model choice is limited to versions offered as regional deployments in UK South. New models may arrive late.
- Quota must be requested early.
- The model provider sits behind an `LLMClient` interface (`backend/app/llm/client.py`), so an alternative such as AWS Bedrock in eu-west-2 remains possible.
