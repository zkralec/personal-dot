# Personal Dot Roadmap

## V1: Infrastructure Lifecycle

- Containerized FastAPI API, RQ worker, PostgreSQL, and Redis.
- Alembic-managed task schema.
- Create, list, and retrieve tasks.
- Execute `echo` and intentional `fail` jobs.
- Persist queued, running, succeeded, and failed states.
- Dependency health checks, JSON logs, and lifecycle tests.
- Local Docker Compose operations and documented security baseline.

The initial V1 slice excluded notifications, approvals, integrations, browser
automation, and semantic memory; later numbered slices add only the capabilities
listed below.

## V1.1: Agent Execution

- OpenAI Responses API behind a narrow, mockable service.
- Persisted `agent` task with instruction and optional context.
- Configurable model, reasoning effort, verbosity, output limit, timeout, and
  retry count.
- Persisted response/request identifiers, model-call timing, and token usage.
- Model output treated as untrusted text with no tool execution.
- Automated mock coverage plus an explicitly gated paid integration test.

## V1.2: Persistent Scheduling

- PostgreSQL-authoritative one-time, interval, and five-field cron schedules.
- Enabled/disabled state, UTC `next_run_at`/`last_run_at`, and schedule-to-task
  execution history.
- Dedicated polling process with row locks and occurrence uniqueness.
- Recovery of committed-but-not-enqueued and stale-running scheduled tasks.
- Bounded catch-up after downtime and timezone-aware cron calculations.
- Automated recurrence, disable/enable, recovery, and duplicate-delivery tests.

## V1.3: Modular Notifications

- Provider-neutral notification interface with Pushover as the first adapter.
- Per-task and per-schedule `none`, `on_completion`, `on_failure`, and `always`
  policies.
- Result-first task lifecycle with persisted notification audit metadata.
- Explicit test-notification endpoint and environment-only credentials.
- Mocked network tests covering successful and failed delivery.

## V1.4: Tool Permissions

- Fixed code-defined tool registry with strict argument validation.
- Risk classifications, automatic-read policy, and durable approval-gated
  local writes.
- Persisted tool-call and approval audit trails with resumable agent tasks.
- No arbitrary shell, Python, browser, or integration execution.

## V1.5: Explicit Persistent Memory

- PostgreSQL-backed user preferences, durable facts, project notes, and
  explicitly created task summaries.
- CRUD, filtering, disable, re-enable, and hard-delete APIs.
- Bounded deterministic retrieval by explicit ID, type, and tag.
- Opt-in untrusted memory context for agent tasks with selection metadata.
- No embeddings, vector database, implicit recall, or automatic memory writes.

## V1.6: Manual Project Check-In

- Manual `project_check_in` tasks with explicit project-note IDs and priorities.
- Bounded accepted-input snapshots, stable source IDs, and content hashes.
- Deterministic reuse of relevant successful task results without semantic memory.
- Model tools disabled; validated sourced recommendations or insufficient context.
- Results remain task results; optional status notifications remain independent.
- API and database reject check-in schedules; recurring execution stays disabled.
- Synthetic provider tests cover the manual API/queue/worker workflow and errors.

## Next: Harden the Core

- Add durable task-attempt/audit-event records.
- Add general task retry policy, timeouts, and cancellation semantics.
- Extend the scheduled-task reconciler or use an outbox for direct tasks.
- Add a durable notification outbox/retry policy if missed pushes prove
  operationally important.
- Add authentication before exposing the API beyond loopback.

## Future Capabilities

- Explicit approval policies and an external-action ledger.
- Gmail and Google Calendar integrations with minimal OAuth scopes.
- Browser automation in an isolated runtime.
- User-facing task history and operational dashboards.
- Backups, restore drills, retention policies, and deployment monitoring.
- Semantic retrieval only after concrete failures of explicit selection are
  measured.

Each future capability should enter as one narrow vertical slice with its own
threat model, audit trail, failure behavior, and tests.
