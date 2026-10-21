# Security policy

## Supported scope

Security fixes are accepted against the latest `main` branch. The repository is public. The default local stack binds to loopback; the optional hosted demonstration template uses public HTTPS ingress while retaining simulated identities and a development scanner bypass. These are demonstration configurations, not approved production services.

## Reporting a vulnerability

Use a private GitHub security advisory for the repository when available. Otherwise contact the repository owner through an existing private project channel. Do not open a public issue containing credentials, signed URLs, object keys, restricted data, precise field locations or personal information.

Include the affected revision, route or component, impact, safe reproduction steps and any correlation ID. Use synthetic fixtures and redact request or response payloads.

## Security boundaries

The demonstration uses development identities and a visible file-scanner bypass. The hosted template adds HTTPS and ingress rate limiting; it does not authenticate institutional users. Production identity, approved malware scanning, managed secrets, reviewed ingress, least-privilege database roles, centralized audit export and incident operations remain required before operational use. Do not upload confidential, personal or precise field-location data to the demonstration.

Published dataset versions, governed analysis evidence and audit events are intentionally immutable. Recovery must use paired database and object-store evidence; destructive downgrade or volume deletion is not an accepted remediation path.
