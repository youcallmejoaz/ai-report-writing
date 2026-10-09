# Infrastructure (Bicep)

This is the reference landing zone for the production environment in **UK South**. It is written to show the security posture described in the proposal. Before first use it needs completing and testing in your own subscription during the Foundations phase.

| File | What it provisions |
|---|---|
| `modules/policy.bicep` | **Subscription scope.** Allowed locations UK South, UK West and global only. Denies Azure OpenAI deployments that are not regional (`Standard` / `ProvisionedManaged`), which blocks Global and DataZone SKUs. |
| `modules/network.bicep` | VNet: App Gateway, Container Apps, PostgreSQL (delegated) and private-endpoint subnets; private DNS zones |
| `modules/keyvault.bicep` | Key Vault Premium (RBAC, purge protection, no public access), with an HSM-backed CMK and rotation policy |
| `modules/storage.bicep` | GZRS storage with CMK, no shared keys, no public access, versioning and soft delete. **Immutability policies** on `final-reports` and `audit-archive` |
| `modules/postgres.bicep` | PostgreSQL 16 Flexible Server: private access, **Entra-only auth**, CMK, zone-redundant HA, TLS 1.2+ |
| `modules/ai.bicep` | Azure OpenAI and Document Intelligence: private endpoints, `disableLocalAuth`, `Standard` regional deployment, `NoAutoUpgrade` model version |
| `modules/servicebus.bicep` | Premium namespace (needed for private endpoints), one queue per pipeline stage with dead-lettering |
| `modules/apps.bicep` | Internal-only Container Apps environment (zone-redundant) running the API and workers under a user-assigned managed identity |
| `modules/appgateway.bicep` | WAF v2 (OWASP 3.2, Prevention), TLS policy 2022, TLS certificate from Key Vault |
| `modules/roles.bicep` | Least-privilege data-plane roles for the app identity |
| `main.bicep` / `main.bicepparam` | Composition and example parameters (no secrets) |

```bash
# validate locally
bicep build main.bicep && bicep build-params main.bicepparam

# deploy (from a pipeline using workload identity federation, not a person's credentials)
az deployment sub create -l uksouth -f modules/policy.bicep
az deployment group create -g rg-airw-prod -f main.bicep -p main.bicepparam
```

## Deliberate gaps, completed in the Foundations phase

- **Model choice:** `chatModelName` and `chatModelVersion` must be a model offered as a **Standard (regional)** deployment in UK South at build time. Check the current Azure OpenAI model availability table. Request quota early.
- **Modified abuse monitoring:** this is applied for through Microsoft's form, not set in IaC.
- **Geo-redundant PostgreSQL backup with CMK** needs a second key and identity in UK West.
- **Worker autoscaling:** a KEDA Service Bus scale rule authenticated by managed identity.
- **Azure Monitor Private Link Scope**, so that log ingestion is private too.
- **Defender for Cloud plans** (Storage with on-upload malware scanning, Key Vault, Databases, Containers), and Sentinel onboarding to the firm's SOC.
- **Container registry** with private endpoint and image signing and scanning, plus a separate non-production stack.
- **Immutability policies:** lock them only after compliance has signed off the retention periods. Locking cannot be undone.
