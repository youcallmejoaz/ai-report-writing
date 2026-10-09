using 'main.bicep'

// Example values only. No secrets belong in this file.
param prefix = 'airw-prod'
param registryServer = 'airwprodacr.azurecr.io'
param apiImage = 'airwprodacr.azurecr.io/airw-api:0.1.0'
param workerImage = 'airwprodacr.azurecr.io/airw-worker:0.1.0'
// Confirm at build time which model/version is offered as a Standard (regional) deployment in UK South.
param chatModelName = 'gpt-4o'
param chatModelVersion = '2024-11-20'
param tlsCertSecretId = 'https://airw-prod-kv.vault.azure.net/secrets/site-tls'
param entraApiAudience = 'api://ai-report-writing'
