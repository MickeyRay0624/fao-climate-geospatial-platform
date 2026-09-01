# Development authentication and OIDC boundary

## Status

The identity abstraction and OIDC token-validation boundary are implemented. **FAO SSO is not connected or certified.** Local development identity is a visible test facility, not an authentication substitute.

## Unified principal

Both providers resolve to the same `Principal`:

- immutable local user UUID and external subject/issuer;
- display name and optional email;
- active workspace and all membership summaries;
- active group memberships;
- role assignments and effective permission codes;
- enabled modules and application entitlements;
- explicit `dev_auth` marker.

No local password is stored. An identity is rejected if the user is inactive, workspace membership is suspended/expired, the module is disabled, or required entitlement/permission is absent.

## Development provider

The development provider is accepted only when all are true:

```text
APP_ENV is development or test
AUTH_MODE=dev
ALLOW_DEV_IDENTITY_HEADERS=true
the subject maps to an active seeded user and membership
```

The optional `X-Dev-User-Subject` header chooses a seeded persona. Without it, `DEFAULT_DEV_USER_SUBJECT` is used. The UI always displays “Development identity · Local persona simulation · not FAO SSO”.

Configuration validation fails startup if staging/production attempts to use development auth headers. This prevents an accidentally deployed persona header from becoming a login mechanism.

Seeded email addresses use the reserved `@example.invalid` domain. The legacy Mickey attribution has no invented real email.

## OIDC provider

Set:

```text
APP_ENV=staging|production
AUTH_MODE=oidc
ALLOW_DEV_IDENTITY_HEADERS=false
OIDC_ISSUER=<approved issuer>
OIDC_AUDIENCE=<platform client/audience>
OIDC_JWKS_URL=<approved HTTPS JWKS URL>
```

The adapter expects an `Authorization: Bearer <JWT>` request, validates signature with the issuer JWKS, algorithm/key ID, issuer, audience, expiry, and standard temporal claims, then maps the validated `sub` plus issuer to an existing local user/workspace context. Raw unverified claims never grant access.

OIDC establishes identity only. Workspace membership, groups, roles, resource grants, module enablement, and classification remain local authorization decisions.

## Integration checklist

Before enabling FAO SSO:

1. Confirm issuer, audience, JWKS rotation/cache policy, permitted signing algorithms, clock-skew policy, and TLS trust.
2. Agree claim mapping for stable subject, display name, email, locale, and organization; never use mutable email as the primary key.
3. Define just-in-time provisioning versus pre-provisioned users and the authoritative source for workspace/group membership.
4. Exercise active, inactive, expired, wrong-audience, wrong-issuer, unknown-key, rotated-key, and revoked-user cases.
5. Confirm logout/session/token storage behavior at the chosen ingress/browser architecture.
6. Disable all development identities and verify startup plus request-level rejection.
7. Review login-context audit retention and privacy with FAO security/data protection owners.

## Token and secret handling

- The API never logs bearer tokens, authorization headers, MinIO secrets, or signed URL query strings.
- `.env` is ignored; `.env.example` contains local placeholders only.
- Browser object access uses short-lived signed URLs, not S3 credentials.
- Production secrets require a managed secret store and rotation procedure; Compose environment variables are for local development.

## Break-glass boundary

The policy model reserves reasoned, audited exceptions, but Phase 1 does not provide an unbounded administrator bypass. Any production support-access process must define approver, expiry, resource scope, incident/reference ID, monitoring, and post-use review before implementation.
