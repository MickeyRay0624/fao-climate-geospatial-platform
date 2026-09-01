## Purpose

Describe the user or operational outcome and the bounded scope of this change.

## Changes

- 

## Data and migration safety

- [ ] No published source bytes or historical evidence are overwritten.
- [ ] Schema changes use a new Alembic revision and preserve a single head.
- [ ] A recovery point and before/after reconciliation exist when persistent data changes.
- [ ] Real, synthetic and demonstration records remain clearly distinguished.

## Security and governance

- [ ] Backend authorization is tested for new actions and sensitive reads.
- [ ] No secrets, local data, recovery artifacts or execution notes are tracked.
- [ ] Separation of duties, audit and immutability remain enforced.

## Verification

- [ ] Backend tests and lint
- [ ] Frontend tests, typecheck, build and dependency audit
- [ ] Module contracts, OpenAPI and Compose checks
- [ ] Relevant E2E and browser journeys

## Rollback

Describe the non-destructive recovery or feature-disable path.
