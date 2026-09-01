# Contributing

This repository contains a local platform demonstration. Changes should be small enough to review, preserve governed evidence and keep restricted or unapproved source data outside Git.

## Development workflow

1. Start from the latest `main` and create a focused branch.
2. Create a recovery point before changing persistent schemas or data.
3. Use a new Alembic revision for schema changes; do not edit released revisions.
4. Keep Data Hub, Investment and Extension write boundaries separate.
5. Add backend authorization, negative controls and browser coverage in proportion to risk.
6. Open a pull request using the repository template and wait for all checks.

## Local checks

```bash
docker compose config
docker compose run --rm --no-deps api python -m pytest -q
python -m pip install -r api/requirements-dev.txt
python -m ruff check api/app api/tests scripts
python scripts/check_contracts.py
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web audit --audit-level=high
```

Run the full stack and E2E checks for workflow changes:

```bash
docker compose up -d --build
python scripts/e2e_datahub.py
python scripts/e2e_negative_controls.py
python scripts/e2e_investment.py
python scripts/demo_smoke.py
npm --prefix web run test:e2e
docker compose down
```

Never stop this project with volume deletion. Follow the backup runbook for recovery.

## Commit and review rules

- Use normal Conventional Commit messages.
- Do not commit `.env`, recovery dumps, source datasets, signed URLs or local execution notes.
- Do not weaken published immutability, append-only audit or separation of duties.
- Do not describe synthetic results as operational evidence or infer missing real indicators.
- Do not add production claims without the corresponding deployment, security and business validation evidence.
