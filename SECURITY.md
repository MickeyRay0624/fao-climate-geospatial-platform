# Security policy

## Supported scope

Security fixes are accepted against the latest `main` branch. The repository is a private prototype, not an internet-facing or production service.

## Reporting a vulnerability

Use a private GitHub security advisory for the repository when available. Otherwise contact the repository owner through an existing private project channel. Do not open a public issue containing credentials, signed URLs, object keys, restricted data, precise field locations or personal information.

Include the affected revision, route or component, impact, safe reproduction steps and any correlation ID. Use synthetic fixtures and redact request or response payloads.

## Security boundaries

The current local environment uses development identities and a visible file-scanner bypass. Production identity, approved malware scanning, managed secrets, TLS/ingress, least-privilege database roles, centralized audit export and incident operations remain required before deployment.

Published dataset versions, governed analysis evidence and audit events are intentionally immutable. Recovery must use paired database and object-store evidence; destructive downgrade or volume deletion is not an accepted remediation path.
