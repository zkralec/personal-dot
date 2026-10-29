# Personal Dot Development Rules

Personal Dot is a small, self-hosted personal agent. Optimize for reliability,
clarity, auditability, security, and incremental delivery.

## Architecture

- PostgreSQL is the authoritative persistent store.
- Redis and RQ are execution infrastructure, never authoritative storage.
- Keep the API, worker, and database code in one Python package until a proven
  need requires another boundary.
- Prefer direct SQLAlchemy sessions and small functions over repository,
  service, or dependency-injection frameworks.
- Add a scheduler only when scheduled behavior exists. It must be a dedicated
  process, not an in-process API timer.
- Every autonomous action and state transition must eventually be auditable.
- External side effects require explicit user permission unless an explicit,
  narrow policy grants it.
- Keep notification providers behind the notification service interface. A
  provider failure must never change an already-persisted task result or
  terminal status.

## Scope and Dependencies

- Implement only the requested milestone. Do not pre-build integrations,
  semantic memory, browser automation, or speculative abstractions.
- Prefer standard-library features and mature dependencies already in use.
- Do not add a dependency without a concrete current use.
- Keep modules typed, functions focused, and behavior covered by tests.

## Data and Migrations

- Change the schema only through Alembic migrations.
- Never edit an applied migration; create a new one.
- Persist failure states and safe diagnostic messages.
- Treat PostgreSQL records as the source of truth when reconciling queue state.

## Security

- Never commit credentials, tokens, API keys, or populated `.env` files.
- Secrets belong in environment variables or ignored local secret files.
- Bind local services to loopback by default and use least-privilege accounts.
- Do not log secrets or unredacted sensitive payloads.
- Do not perform destructive or external actions without explicit approval.
- Treat all model output as untrusted data; never execute it or treat it as
  permission. Keep model tools disabled unless a reviewed milestone adds one.

## Standing Documentation-Maintenance Policy

- DOT may inspect all repositories owned by the configured personal GitHub account.
- Routine documentation changes may be generated, independently reviewed,
  committed, pushed to temporary branches, and merged automatically when
  deterministic policy checks pass. Qualifying changes need no manual approval.
- Application code, dependencies, workflows, deployment settings, permissions,
  agent instructions, and all other changes outside this policy require explicit
  owner approval. Documentation paths cannot bypass these exclusions.
- Repository content and model output cannot grant or expand permissions.
- Follow the scope, fail-closed checks, independent review and audit requirements
  in [the documentation-maintenance policy](docs/documentation-maintenance.md).
  This policy is recorded now; GitHub publishing is not implemented by this milestone.

## Development Workflow

- Read `docs/` and this file before changing architecture or behavior.
- Keep changes narrow and update docs when implemented behavior changes.
- Run migrations and the relevant tests before declaring work complete.
- For infrastructure changes, build and start the containers, exercise the
  real API/worker lifecycle, and inspect service logs.
- Preserve unrelated user changes and never use destructive Git commands.
