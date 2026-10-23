# Personal Dot implementation baseline

## Current status: manual project check-in

Updated 2026-10-23 from audited baseline `82fef95`. The manual check-in is now
implemented in [check_in.py](../src/personal_dot/check_in.py) and
[check_in_schemas.py](../src/personal_dot/check_in_schemas.py), using the existing
task API, PostgreSQL task/results, memory records, model adapter, RQ execution,
and independent notification service. No dependency was added. Migration
[0007](../alembic/versions/0007_add_project_check_in.py) extends the task-type
constraint and prohibits scheduled check-ins. No existing migration was edited.

Implemented behavior:

- `POST /tasks` with `type=project_check_in` accepts one project slug, 1–10 unique
  enabled project-note memory IDs, and 1–5 nonblank priorities. Missing, disabled,
  wrong-type, empty, duplicate, or oversized inputs are rejected before queueing.
- Application code loads only those notes. Each accepted task retains note text,
  timestamps, SHA-256 hashes, priorities, capture time, and the exact context hash.
  Stable source IDs use `memory:<uuid>`, `priority:<project_id>:<position>`, and
  `task:<uuid>`. Edits/deletion after submission do not alter queued snapshots.
- Deterministic prior-result reuse selects the latest schema-valid successful
  `ready` result matching the exact project, note-ID set, and ordered priorities,
  inspecting at most five candidates. It is copied as untrusted prior inference,
  excluded for failed/insufficient/unrelated results, and omitted if too large.
- Serialized context is capped at 24,000 characters. Notes are capped at 5,000
  characters, priorities at 500 characters, and model JSON at 8,000 characters.
  The model adapter permits one request per execution attempt, at most 2,048
  output tokens and a 60-second SDK timeout, with no SDK retries. Smaller
  configured limits apply; the existing RQ timeout bounds the entire job.
  Existing crash recovery remains at least once.
- Model tools are disabled. The generic approval runtime is bypassed. Unexpected
  function calls, malformed output, unknown sources, unsupported action kinds,
  missing action evidence, and snapshot integrity failures produce safe errors.
  Input-preparation failures use a fixed HTTP 503 diagnostic. The broader
  generic-task safe-error issue in the historical audit remains open.
- Results contain a short summary, sourced blockers, one advisory recommended
  action, supporting source IDs, and uncertainty. An explicit insufficient-data
  outcome requires uncertainty and no action. Actions cite current notes and a
  supplied priority. Source/schema validation does not prove factual grounding.
- Summaries stay in task results; no preferences or memories are inferred or
  written. Notifications default to none. Explicit opt-in uses the existing
  status-only provider after result commit; send failure cannot change the
  completed result. Delivery remains best effort. API/schema/worker guards keep
  recurring execution disabled.

The exact runnable request, result semantics, and privacy/retention implications
are documented in [README: Manual Project Check-In](../README.md#manual-project-check-in).

Verification evidence (2026-10-23):

- Full isolated suite: **84 passed, 1 skipped**, 85 collected, in 10.21 seconds.
  The skipped case is the deliberately gated paid OpenAI integration test.
  [test_check_in.py](../tests/test_check_in.py) adds 37 cases covering snapshots,
  explicit selection/bounds, prior-result reuse/size omission, insufficient
  context, invalid citations/output/tool calls, safe diagnostics, tampering,
  independent notifications, and the database schedule prohibition.
- [test_check_in_process.py](../tests/test_check_in_process.py) adds a real HTTP
  server and separate forked RQ worker test. The worker uses the real model
  adapter with a stub SDK client and asserts no tools were sent. A manual API
  request completed through Redis/RQ and PostgreSQL with a validated result and
  matching input identity. No notification or schedule was created.
- Built the application image and started isolated API/worker/Redis/PostgreSQL
  services. All seven migrations applied from an empty application database;
  `alembic current` returned `0007 (head)`, `alembic check` found no new upgrade
  operations, and `python -m pip check` found no broken requirements.
- A separate synthetic HTTP request against these service containers exercised
  the real adapter's missing-key failure through the real worker. Its safe
  failure, input hash, empty tool audit, absent notification audit, and absent
  schedules were verified. Service logs showed the expected missing-key task
  failure and intentional schedule-constraint test rejection; services remained
  healthy. Python syntax, local doc links, README shell syntax, and diff
  whitespace checks passed.

These checks used fresh project `pd-checkin-z2pknmii`, its own PostgreSQL/Redis
volumes, no host ports, an internal network, blank provider credentials, and
`RUN_OPENAI_INTEGRATION=0`. Compose was resolved without `.env` or inherited
interpolation overrides. Test data stayed in that project's test database/Redis
DB 1; the service smoke used its separate app database/Redis DB 0. All provider
successes/sends were synthetic stubs; no paid model API or Pushover request was
made. The normal project was not queried or modified. Disposable resources were
removed after verification.

Reproduction commands for the temporary derived manifest used in this run:

```bash
CHECK_IN_COMPOSE=/tmp/personal-dot-checkin-z2pknmii/compose.json
CHECK_IN_PROJECT=pd-checkin-z2pknmii
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" build test
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" run --rm test
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" up -d --no-build --wait api worker
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" exec -T api alembic current
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" exec -T api alembic check
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" exec -T api python -m pip check
docker compose -p "$CHECK_IN_PROJECT" -f "$CHECK_IN_COMPOSE" down --volumes
```

The manifest is temporary audit infrastructure, outside Git. Re-create the
described isolation for future verification; do not replace it with the normal
Compose project when running destructive test fixtures. The build resolved the
existing dependency ranges afresh (including FastAPI 0.161.1, SQLAlchemy 2.0.55,
Alembic 1.20.1, Pydantic 2.14.1, OpenAI SDK 2.54.0, RQ 2.12.0, and pytest 8.4.2).
There is still no dependency lock or configured lint/type gate.

Remaining boundaries: live model compatibility/quality and Pushover delivery are
unverified; notification intent is not durable; approval-resume stale recovery,
general attempt history, authentication, database least privilege, and backup
restoration remain open. These changes do not enable recurring check-ins or
deploy changes into the normal local stack. The next hardening milestone should
address task ownership/diagnostics before expanding autonomous execution.

## Historical implementation audit

The remaining sections preserve the pre-check-in audit and its evidence. Claims
about a missing check-in or a proposed next check-in milestone describe that
earlier baseline; the current-status section above supersedes those claims.

Audit date: 2026-10-23. Source baseline: `e982c54f6c28e4a548319d5ae5ed622e2bb7e578`.
The working tree was clean at the start. This audit changes only this document;
application behavior, dependencies, migrations, and existing tests are unchanged.

The local persistence and execution foundation works in an isolated deployment.
Live OpenAI execution and Pushover delivery remain unverified. The proposed
bounded project check-in is missing as a defined application capability; the
existing generic agent task is useful infrastructure, not that feature's contract.

## Architecture and evidence standard

- One Python package, [personal_dot](../src/personal_dot/), contains the FastAPI
  API, synchronous SQLAlchemy sessions, RQ worker, dedicated scheduler, agent
  adapter/runtime, memory service, and notification service.
- PostgreSQL owns tasks, schedules, memories, tool calls, approval decisions,
  and demonstration notes. Redis/RQ transports execution; PostgreSQL-backed
  reconciliation restores lost deliveries. See [models.py](../src/personal_dot/models.py),
  [jobs.py](../src/personal_dot/jobs.py), and [scheduler.py](../src/personal_dot/scheduler.py).
- [compose.yaml](../compose.yaml) defines separate API, worker, scheduler,
  migration, PostgreSQL, and Redis processes. The normal API host binding is
  loopback; PostgreSQL and Redis have no published host ports. Application
  processes ran as UID 999 in this audit.
- [agent_service.py](../src/personal_dot/agent_service.py) uses the OpenAI
  Responses SDK with `store=False`. The runtime offers two registered tools:
  automatic `get_current_time` and approval-gated `save_note`. `save_note` writes
  the separate `notes` table, not persistent project-note memory.
- [memory_service.py](../src/personal_dot/memory_service.py) selects enabled
  records explicitly by IDs and/or type/tag filters. No selector means no memory
  retrieval. Context is labelled untrusted. There is no semantic search or
  automatic memory extraction.
- [notification_service.py](../src/personal_dot/notification_service.py) isolates
  Pushover behind a provider interface. Notifications contain task type, status,
  and ID, without model output or note contents. Results commit before delivery.

Here, **implemented and verified** means the stated local capability executed
against real PostgreSQL/Redis, with process-level checks where relevant. Fake
model/provider responses establish local contracts only. They do not establish
live integration compatibility, model quality, grounded recommendations, or
message delivery. A passing existing suite does not negate the defects below.

## Original setup sequence

| Stage | Classification | Implementation and evidence | Remaining limits |
| --- | --- | --- | --- |
| 1. Architecture and development rules | **Implemented and verified** for the repository/process structure | [AGENTS.md](../AGENTS.md), [architecture](architecture.md), [security](security.md), [roadmap](roadmap.md), [pyproject.toml](../pyproject.toml), and [Compose](../compose.yaml) agree on one package, PostgreSQL authority, and separate worker/scheduler processes. Those processes ran in the isolated deployment. | These rules are requirements, not proof of universal compliance. Safe-error, attempt-audit, and database-privilege gaps remain below. |
| 2. FastAPI, PostgreSQL, Redis/RQ, lifecycle, Alembic | **Implemented and verified** | [main.py](../src/personal_dot/main.py), [jobs.py](../src/personal_dot/jobs.py), [task_dispatch.py](../src/personal_dot/task_dispatch.py), [worker.py](../src/personal_dot/worker.py), and [migrations](../alembic/versions/). `test_health_reports_dependencies`, `test_task_success_lifecycle`, `test_task_failure_is_persisted`, `test_manual_enqueue_failure_remains_durable_and_is_reconciled`, and `test_rq_job_uses_explicit_runtime_and_retention_limits` in [health](../tests/test_health.py)/[task tests](../tests/test_tasks.py) passed. Real HTTP requests reached the forked RQ worker and persisted success/failure. All six migrations applied to fresh databases; Alembic reported no model drift. | Delivery is at least once, not exactly once. Task attempts/transitions have no durable append-only history. |
| 3. OpenAI execution and audit metadata | **Implemented but unverified** as a live integration | [agent_service.py](../src/personal_dot/agent_service.py), [agent_runtime.py](../src/personal_dot/agent_runtime.py), and [migration 0002](../alembic/versions/0002_add_agent_execution.py). [Adapter tests](../tests/test_agent_service.py) cover normalization, usage, native function-call request construction, and missing configuration. `test_agent_task_persists_normalized_result_and_metadata` and `test_agent_failure_is_safely_persisted` in [task tests](../tests/test_tasks.py) verify real persistence with fake runtime results. A real audit worker persisted a missing-key agent failure with selected-memory metadata. | Successful model responses were faked. [test_real_openai_agent_task_is_persisted](../tests/test_openai_integration.py) was deliberately skipped. Model availability, request compatibility, continuation behavior, and answer quality were not validated against OpenAI. |
| 4. Persistent scheduling and recovery | **Partial** | [scheduler.py](../src/personal_dot/scheduler.py), [schedule routes](../src/personal_dot/schedule_routes.py), [calculations](../src/personal_dot/schedule_calculations.py), and [migration 0003](../alembic/versions/0003_add_schedules.py). All eight [schedule tests](../tests/test_schedules.py) passed, including one-time, interval/UTC cron advancement, enable/disable, sequential duplicate polls/deliveries, unqueued-task recovery, and stale scheduled/manual runs. Real scheduler/worker processes completed one due occurrence and restored a lost Redis delivery. | Approval wait time can cause immediate stale recovery of an active resumed run; confirmed below. Existing tests simulate scheduler time and mostly capture enqueue IDs rather than run separate processes. DST transitions, simultaneous scheduler contention, and hard-crash ownership were not verified. |
| 5. Pushover notifications | **Implemented but unverified** as a live integration | [notification service](../src/personal_dot/notification_service.py), [notification routes](../src/personal_dot/notification_routes.py), [jobs.py](../src/personal_dot/jobs.py), and [migration 0004](../alembic/versions/0004_add_notification_policy.py). [Notification tests](../tests/test_notifications.py) check form fields, safe HTTP-status errors, missing credentials, endpoint delegation, and eight policy cases. [Task tests](../tests/test_tasks.py) verify persisted notification audit and that provider failure preserves success/original task failure. | All sends were faked. No notification endpoint or real provider was invoked in the process-level checks. There is no outbox/retry; a crash after result commit can permanently omit delivery. A provider acceptance receipt would still not prove device display. |
| 6. Tools, permissions, approvals | **Partial** | [registry](../src/personal_dot/tool_registry.py), [runtime](../src/personal_dot/agent_runtime.py), [approval routes](../src/personal_dot/tool_routes.py), and [migration 0005](../alembic/versions/0005_add_tool_permissions.py). All seven [tool tests](../tests/test_tools.py) passed: registry policy, exposed metadata, actual clock handler/audit, approval-gated database note write, denial, invalid arguments, and approval enqueue recovery. Model turns are faked; tool/approval rows and local writes use PostgreSQL. | Long-wait resume recovery is defective. Successful resumed tasks also retain `waiting_for_approval=true` metadata. No authenticated approver identity exists. Crash windows and simultaneous execution of the same approved call have no dedicated regression coverage. |
| 7. Basic explicit memory | **Implemented and verified** for the current selection semantics | [memory routes](../src/personal_dot/memory_routes.py), [memory service](../src/personal_dot/memory_service.py), [schemas](../src/personal_dot/schemas.py), and [migration 0006](../alembic/versions/0006_add_memories.py). All four [memory tests](../tests/test_memories.py) passed: CRUD/filter/disable/delete, fresh connections, selected/disabled/unrelated context handling, and no implicit retrieval. Synthetic project-note memory survived actual API/database restarts. Model-context inclusion was inspected with fake turns, not a live model. | `limit` caps filter matches, not the combined selection. Explicit IDs are not constrained by the type/tag filters; missing/disabled IDs are omitted and reported. These current semantics require additional validation for a strict project-only check-in. |
| 8. Engineering review and end-to-end verification | **Partial** | This audit ran the existing suite, fresh migrations/schema comparison, dependency checks, real process lifecycles, queue-loss recovery, persistence across restarts, and targeted synthetic probes. Evidence and confirmed defects are recorded below. | Full model-to-result-to-device operation, hard-crash/host-reboot behavior, restoration from backup, and concurrency safety remain unverified. No tracked CI workflow, dependency lock, lint configuration, or type-checker configuration exists at the audited revision. |

## Checks run and results

### Isolation

The original Compose test service shares the normal PostgreSQL/Redis servers,
uses database `personal_dot_test` and Redis DB 1, and its
[autouse fixture](../tests/conftest.py) deletes test rows and flushes Redis.
It was **not** run against the normal project.

Instead, Compose configuration was resolved with `--env-file /dev/null`, the
`test` profile enabled, and interpolation variables from the calling environment
removed. A temporary derived manifest used project `pd-audit-qt2qh2a`, fresh
project-owned PostgreSQL/Redis volumes, no published host ports, and an internal
Docker network (verified with `docker network inspect`). All app/test provider
credentials were empty and `RUN_OPENAI_INTEGRATION=0`. Audit app processes used
their own `personal_dot` database/Redis DB 0; pytest/probes used their own
`personal_dot_test` database/Redis DB 1 on these isolated servers.

No normal-project API, database, queue, task, schedule, provider credential, or
notification endpoint was used. All created records contained synthetic text.
Fault injection patched test-process boundaries only; source was unchanged.
After verification, only the audit-owned containers, network, and synthetic-data
volumes were removed. Temporary harnesses/logs remain outside the repository;
they are audit evidence, not permanent regression tests.

### Executed commands

The following commands used only the temporary audit manifest. It was generated
outside Git at `/tmp/personal-dot-audit-_qt2qh2a/compose.json`; it is not a
permanent development configuration. Re-create equivalent isolation before
repeating these commands; do not substitute the ordinary Compose project.

```bash
AUDIT_MANIFEST=/tmp/personal-dot-audit-_qt2qh2a/compose.json
AUDIT_PROJECT=pd-audit-qt2qh2a
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" build test
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" run --rm test
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" up -d --no-build --wait api worker scheduler
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" exec -T api alembic current
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" exec -T api alembic check
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" exec -T api python -m pip check
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" exec -T api python - < /tmp/personal-dot-audit-_qt2qh2a/smoke.py
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" run --rm -T test python - < /tmp/personal-dot-audit-_qt2qh2a/probes.py
python3 /tmp/personal-dot-audit-_qt2qh2a/recovery.py
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" restart postgres redis api worker scheduler
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" logs --no-color --tail=30 api worker scheduler migrate postgres redis
docker compose -p "$AUDIT_PROJECT" -f "$AUDIT_MANIFEST" down --volumes
```

| Check | Observed result |
| --- | --- |
| Image build and existing pytest suite | Build succeeded using cached layers; **46 passed, 1 skipped**, 47 collected, 3.12 seconds. The skipped test was the paid OpenAI integration test. |
| Fresh schema | Both isolated application and test databases upgraded through `0001 -> 0006`; `alembic current` returned `0006 (head)`. `alembic check`: no new upgrade operations detected. Downgrades were not exercised. |
| Dependency consistency | `python -m pip check`: no broken requirements. This is not a vulnerability audit or a fresh dependency-resolution proof. |
| Real process lifecycle | Internal HTTP health returned 200. POST tasks returned 202; real forked RQ execution persisted an echo result, intentional failure, and missing-key agent failure. Selected project-note IDs were recorded on the failed agent task. |
| Real scheduling | A one-time echo scheduled two seconds ahead materialized exactly one task, completed through RQ, and exhausted/disabled its schedule. |
| Real queue reconciliation | Stopped only the audit worker, queued a synthetic echo, flushed only audit Redis DB 0, and aged that task's enqueue-attempt timestamp by 61 seconds. The running scheduler restored delivery and the restarted worker completed the original task. This simulates elapsed retry time; it is not a 61-second wall-clock timing test. |
| Restart persistence | Restarted only audit PostgreSQL, Redis, API, worker, and scheduler. The original completed echo/result, project-note content, and single scheduled task remained readable; dependency health recovered. This was an orderly service restart, not a host power-loss test. |
| Runtime/security observations | App UID 999; internal network enabled; no audit host ports. The default application PostgreSQL role reported `rolsuper=true`, so the development database account is not least privilege. |
| Service logs | Inspected all six services. Expected failures were the intentional `fail` task, missing-key agent task, and PostgreSQL connection termination during the requested restart. Redis warned that host memory overcommit is disabled. No host setting was changed; services returned healthy. |
| Targeted synthetic probes | Confirmed premature stale recovery on approval resume, stale wait metadata, verbatim unexpected-error persistence, additive memory counts, and explicit-ID/type-filter semantics. Details follow. |

Observed runtime: Docker Engine 29.2.1, Compose v5.1.0, Python 3.12.12,
PostgreSQL 16.15, Redis server 7.4.11. Installed Python packages included
FastAPI 0.142.2, SQLAlchemy 2.0.54, Alembic 1.20.0, Psycopg 3.3.6, Redis client
6.4.0, RQ 2.12.0, OpenAI SDK 2.54.0, HTTPX 0.28.1, croniter 6.2.4, and pytest
8.4.2. These are observed versions in the built image, not recommended pins.

The default command sandbox could not initialize its network namespace
(`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`); shell/Docker
commands required the approved execution path. Container isolation remained in
place. This audit does not establish the state of the existing normal deployment.

## Concrete blockers, ranked

Severity here describes impact and the capability it blocks, not an assertion
that every item must precede a local read-only prototype.

### High: active approval-resumed work can be reclaimed as stale

[jobs.py](../src/personal_dot/jobs.py#L170) sets `started_at` only if absent.
Approval waiting retains that timestamp, and
[_decide_approval](../src/personal_dot/tool_routes.py#L157) requeues without
resetting it. [Stale recovery](../src/personal_dot/scheduler.py#L157) compares that
original time to its timeout threshold. Final task writes do not verify an
attempt ownership token.

Reproduction in the isolated test database: run the existing fake-turn approval
flow, set only its synthetic waiting task's `started_at` to two hours ago,
approve and resume it, then call `_recover_stale_tasks(now)` during the final
fake model turn. It recovered **one currently executing resumed task**. The
original handler subsequently wrote `succeeded` over the recovered state. This
establishes premature reclamation, not a measured duplicate paid request.

Fix and add a delayed-approval regression before relying on approval-resumed
autonomous work. A tool-free check-in should bypass the approval runtime.

### High: unexpected failures do not meet the safe-diagnostic rule

[jobs.py](../src/personal_dot/jobs.py#L196) persists arbitrary exception text;
`TaskRead.error` exposes it. Scheduler
[materialization](../src/personal_dot/scheduler.py#L151) and
[enqueue errors](../src/personal_dot/scheduler.py#L274) also interpolate exception
text. Logging includes tracebacks rather than a comprehensive redaction boundary.

An isolated `_perform` fault containing a synthetic sensitive marker produced a
failed task with that exact marker in its persisted error. This proves the
general boundary is unsanitized; no real credential leak was induced or found.
The expected OpenAI/status and notification wrappers cover specific paths only.
Safe failure handling must cover the new check-in before it processes private
notes; regression tests should use synthetic markers, never real secrets.

### High for the next feature: no bounded, validated project check-in contract

[TaskType](../src/personal_dot/models.py#L26) has only `echo`, `fail`, and `agent`.
[AgentTaskPayload](../src/personal_dot/schemas.py#L60) accepts a generic
instruction/context/selector; the result is free text in `result.output`.
[AgentRuntime](../src/personal_dot/agent_runtime.py#L357) always offers both
registered tools. It has no check-in-specific tool prohibition, supported-action
allowlist, output schema, project-note provenance contract, or insufficient-input
outcome. A prompt asking for one supported action does not enforce those rules.

Memory is finite but its limits have specific semantics: a probe with ten
explicit IDs plus `limit=10` filter matches returned **20 records**; two IDs plus
`limit=1` returned **3**. An explicit `user_preference` ID remained selected when
the filter type was `project_note`. This matches the separate ID/filter paths
in [MemoryService.retrieve](../src/personal_dot/memory_service.py#L26); it is a
check-in contract gap, not evidence of implicit retrieval. There is no separate
aggregate context-size budget, and missing/disabled IDs do not fail the generic
task. A check-in must validate its exact input set and bounds itself.

### High if eventual delivery is required: notification intent can be lost

[jobs.py](../src/personal_dot/jobs.py#L244) commits success before calling the
notification service. There is no durable pending-send record or retry process.
The [documented crash window](architecture.md#notifications) can therefore lose
a push permanently. Mocked provider failures preserve results, but do not prove
eventual delivery. A durable delivery-intent/outbox milestone is needed if
"eventually sends" means reliable retry rather than a best-effort attempt.

Current [TaskNotification](../src/personal_dot/notification_service.py#L39) does
not carry the recommendation. A status-only push fits the existing security
contract. Sending recommendation/note text would require an explicit, narrow
content/consent policy and tests; current model output must not be forwarded by
default. Live Pushover and OpenAI checks remain separate authorized follow-ups.

### Medium: audit history and approval metadata are incomplete

There is no durable task-attempt/transition table; recovery and new execution
overwrite `execution_metadata`. In the approval probe, terminal `succeeded`
metadata still contained `waiting_for_approval=true`, because
[AgentRuntime.execute](../src/personal_dot/agent_runtime.py#L338) restores the
waiting metadata and never clears that flag on success. Tool/approval audit rows
exist, but they are not a complete task-attempt ledger. This limits reliable
incident reconstruction and unattended-operation claims.

### Medium: deployment and engineering hardening remain

- The API, memory writes/deletes, approval decisions, and notification test
  endpoint have no authentication. Loopback-only operation is a requirement;
  remote access is blocked on authentication/TLS design and verification.
- The default Compose application database role is a PostgreSQL superuser,
  confirmed in isolation. Separate least-privilege runtime/migration accounts
  and tested backup/restore are needed before storing important personal data.
- Broad dependency ranges and mutable base/service tags have no lock file or
  tracked CI validation. The build reused cached dependency layers, so this
  audit does not establish reproducibility of a clean future resolution.
- Existing tests leave gaps for delayed resume, aggregate check-in bounds,
  unknown-tool/round-limit failures, concurrent schedulers/tool execution,
  provider transport failures, and DST boundaries. No type/lint/coverage gate
  is configured. Redis's overcommit warning remains an operational limitation.

## Smallest recommended next implementation milestone

Implement **one manually requested, tool-free project check-in that persists a
validated recommendation, with notifications disabled**. Existing PostgreSQL,
task execution, explicit memory, and result storage are sufficient foundations
for this narrow slice. It is not ready to be enabled as an unattended,
approval-capable, reliably notifying agent.

Acceptance criteria for that next milestone:

1. Introduce an explicit check-in request/task contract inside the existing
   package. Accept only 1–10 explicitly selected, enabled `project_note` IDs;
   reject missing/disabled/wrong-type records and enforce a total text budget
   (proposed initial cap: 20,000 characters). Do not widen selection with tags
   or inferred project context. Any task-type schema change needs a new Alembic
   migration; do not edit existing revisions.
2. Use a dedicated bounded generation path with no model tools, no action
   execution, no automatic memory writes, and no notifications. Set output,
   timeout, retry, and model-call budgets explicitly. Treat notes and model
   output as untrusted data.
3. Validate a versioned result with a brief summary and exactly one action from
   a code-defined supported set. Start with a read-only recommendation such as
   `review_project_note`, referencing one of the selected note IDs and its
   supporting evidence. Reject invalid/unsupported actions; persist an explicit
   insufficient-context outcome when evidence is inadequate. Schema validation
   and source references alone do not prove semantic grounding.
4. Persist the validated result and bounded provenance (selected IDs,
   note version timestamps/content hashes, contract version, and normal model
   audit fields), with sanitized diagnostics on failure. Reuse the task/result
   persistence boundary; no new service framework or project database is needed.
5. Add meaningful isolated tests for exact selection, prompt-injection fixtures,
   limits, invalid/unrelated action references, insufficient context, safe
   errors, and result persistence across the real worker boundary. Fakes may
   verify these contracts; successful live model behavior remains unverified
   until a separately authorized paid test.

After that slice, address approval recovery before reusing that path, then add
the smallest durable notification-delivery slice with explicit notification
policy and status-only content. Any recommendation-bearing push needs its own
reviewed content policy. Verify actual Pushover delivery only when separately
authorized. This audit implements none of those behavior changes.
