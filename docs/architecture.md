# Personal Dot V1 Architecture

## Goal

V1 proves one auditable background-task lifecycle:

```text
client -> API -> PostgreSQL -> Redis/RQ -> worker -> task handler -> PostgreSQL
            ^           ^                         \-> OpenAI Responses API
            |           |                         \-> explicit memory retrieval
            |           |                         \-> validated tool registry
            |           |                         \-> notification service
            |           |
            +-- reads --+-- scheduler (due schedules and delivery recovery)
```

A task is accepted and persisted in PostgreSQL before its RQ job is enqueued.
The worker records `running`, then either `succeeded` with a result or `failed`
with a safe error message. Clients inspect the durable record through the API.

## Processes

- **API:** FastAPI validates requests, persists tasks and schedules, enqueues
  direct jobs, exposes reads, and reports dependency health.
- **Worker:** RQ consumes jobs and performs the small V1 task handlers. It
  atomically claims only a task still in `queued`, making later duplicate queue
  deliveries harmless.
- **Scheduler:** A dedicated process polls PostgreSQL for due schedules,
  materializes occurrences as ordinary tasks, sends them to RQ, repairs lost
  queue delivery for every task, and recovers stale runs.
- **Agent service:** A narrow adapter performs OpenAI Responses API turns and
  normalizes text, native function calls, response/request identifiers, timing,
  and token usage. Requests use `store=false`.
- **Agent runtime:** Coordinates model turns with the fixed tool registry. It
  validates every function call, persists its audit record before execution,
  returns JSON tool output to the model, and durably pauses approval-gated work.
- **Memory service:** Resolves only task-requested memory IDs, types, and tags
  from PostgreSQL, in deterministic order, then formats them as a bounded,
  untrusted reference block. It has no embedding or semantic-search dependency.
- **Tool registry:** Contains code-defined tool metadata, strict Pydantic input
  models, permission policy, and direct handler references. It cannot load a
  handler, module, shell command, or Python expression named by the model.
- **Notification service:** A provider-neutral interface formats concise task
  events. The first provider adapter sends HTTPS requests to Pushover; task
  execution does not import or understand Pushover.
- **Migration job:** A one-shot Alembic container upgrades the schema before
  the API, worker, and scheduler start.
- **PostgreSQL:** Authoritative task, schedule, memory, occurrence, and result
  state.
- **Redis:** Durable-enough queue transport with AOF enabled for local restart
  recovery. It is not the system of record.

The scheduler never calls a task handler or an LLM. An LLM call can happen only
after a due occurrence becomes a task and a worker claims it.

## Code Layout

```text
src/personal_dot/
  config.py              environment-backed settings
  agent_service.py       isolated OpenAI Responses API adapter
  agent_runtime.py       validated tool-call, audit, pause, and resume lifecycle
  check_in.py            bounded input snapshots and tool-free generation
  check_in_schemas.py    check-in request, snapshot, and validated result contracts
  db.py                  SQLAlchemy engine/session/base
  diagnostics.py         fixed failure vocabulary and diagnostic field allowlist
  jobs.py                worker entry points and state transitions
  main.py                FastAPI application and routes
  memory_routes.py       memory CRUD, filtering, disable, and deletion API
  memory_service.py      deterministic explicit-memory selection and formatting
  models.py              persistent task model and enums
  notification_routes.py explicit test-notification endpoint
  notification_service.py provider interface, Pushover adapter, and policy
  notification_delivery.py durable bounded check-in notification retries
  queue.py               Redis/RQ construction
  schedule_calculations.py UTC interval and timezone-aware cron calculations
  schedule_routes.py     schedule API and execution-history reads
  scheduler.py           PostgreSQL poller, materializer, and reconciler
  schemas.py             API request/response models
  server.py              configured Uvicorn process
  structured_logging.py  JSON logging
  task_dispatch.py       shared RQ enqueue boundary
  tool_registry.py       fixed tool definitions and demo implementations
  tool_routes.py         registry, audit, and approval API
  worker.py              configured RQ process
alembic/                  schema migration environment and revisions
tests/                    integration-focused lifecycle tests
```

## Task State Model

```text
queued -> running -> succeeded
                  \-> waiting_for_approval -> queued -> running
                  \-> failed
```

Timestamps use timezone-aware UTC values. Payload and result are JSON objects.
The API supports `echo`, an intentional `fail` handler, `agent`, and
`project_check_in` tasks. Agent tasks
require an instruction and accept optional textual context. Model output is
stored as untrusted text and is never executed.

`waiting_for_approval` is durable and non-terminal. Its task has no completion
timestamp and is not eligible for completion/failure notifications. An approval
decision returns it to `queued`; a new RQ delivery then resumes execution.

Agent execution metadata is stored separately from the result in the task's
`execution_metadata` JSON object. It includes the model, model-call timestamps,
success state, response/request identifiers when available, and token usage.
It never includes credentials or the submitted instruction/context.

## Persistent Memory

Memory is deliberately explicit and relational. A `Memory` row has an ID, one
of four types (`user_preference`, `durable_fact`, `project_note`, or
`agent_task_summary`), content, a descriptive source label, enabled state,
normalized tags, and UTC timestamps. The type `agent_task_summary` permits a
summary to be stored explicitly; Personal Dot does not generate or save task
summaries automatically.

Only calls to the memory create/update API change memory. Task instructions,
context, model responses, tool outputs, notifications, and the demonstration
`save_note` tool are not promoted to memory. This prevents accidental retention
and keeps memory creation inspectable.

An agent task opts in with a `payload.memory` selector:

```json
{
  "ids": ["memory-uuid"],
  "types": ["user_preference"],
  "tags": ["personal-dot"],
  "limit": 10
}
```

No selector means no memory query and no memory context. Enabled explicit IDs
are returned first in request order. An optional filter query then matches any
requested type and any requested tag; when both type and tag filters are
present, both groups must match. Filter matches are ordered by most recently
updated and then ID, with a maximum of ten. Explicit IDs are de-duplicated from
filter matches, and disabled or missing IDs are omitted.

Selected records are added to a separate input block labelled as untrusted
reference data, never as system instructions. Task `execution_metadata` records
the selection strategy, IDs, types, missing/disabled IDs, and count, but not a
second copy of memory content. This small service boundary can later be replaced
or extended by measured semantic retrieval without changing task persistence or
the OpenAI adapter.

Memory APIs support create, list/filter, inspect, patch (including re-enable),
explicit disable, and hard delete. Deletion removes the authoritative memory
row. It cannot retract content already sent to OpenAI or already placed in an
in-progress paused task's private continuation state.

## Manual Project Check-Ins

`POST /tasks` accepts `type=project_check_in` with one `project_id`, explicit
`project_note` memory IDs, and inline priorities. The API gathers these inputs
with a bounded SQL query, validates their type/enabled/content limits, and
snapshots them in the existing task JSON payload before queueing. The
`check_in_schemas.py` contracts and `check_in.py` orchestration own this narrow
workflow. It does not use the generic additive memory selector or tool runtime.

Source IDs are stable memory UUIDs and project/position priority IDs. Source
content hashes, update timestamps, capture time, and a hash of the exact rendered
context make accepted inputs inspectable even if memories later change or are
deleted. Snapshots are intentionally sensitive task data. The latest successful
ready check-in for the same project, note set, and ordered priorities may be
snapshotted as prior untrusted inference; at most five candidates are inspected,
and prior context is omitted when it would exceed the 24,000-character budget.

The worker uses `AgentService.execute` directly, with one model request, no tool
definitions, no SDK retries, and capped request/output budgets. Local validation
requires a versioned summary, sourced blockers, one sourced advisory action (or
an explicit insufficient-information outcome), supporting IDs, and uncertainty.
Structured IDs and namespaced citations in summary, blockers, action description
and rationale, and uncertainty are checked against the snapshot. Prose IDs must
also be listed in supporting IDs. Unknown citations, unsupported action kinds,
invalid JSON, excess output, or an
unexpected tool call fail safely. Current-note and priority references constrain
provenance; they do not establish semantic truth. Generated results are never
promoted to persistent memories.

Existing task/result commits and notification isolation are reused. Notification
policy remains explicit and defaults to none. Migration `0008` supersedes the
manual-only restriction from `0007`, permitting disabled check-in schedules and
adding durable status-only notification intent. The existing dedicated scheduler
snapshots current selected inputs at materialization. Check-ins coalesce overdue
occurrences, skip competing project executions using a PostgreSQL advisory lock,
and become terminal `uncertain` on stale recovery or transport interruption;
they never automatically repeat model execution. See
[scheduled check-ins](scheduled-check-ins.md) for policies and operator commands.
No live recurring execution is enabled by this milestone.

## Tool and Permission Execution

Tools are registered in code with a name, description, strict JSON input
schema, risk class, automatic-execution flag, approval requirement, and direct
handler. The current risk classes are:

- `unclassified`: fail closed; used only to audit an unknown request;
- `read_only`: reads local state without changing it;
- `local_write`: changes Personal Dot's own persistent state;
- `external_communication`: sends data to another person or service;
- `destructive`: deletes or irreversibly changes state;
- `financial`: spends money or creates a purchase/financial commitment.

Risk describes the effect and the registry enforces a fail-closed baseline:
only `read_only` tools may be automatic. Every other risk class must require
approval. For this iteration, `get_current_time` is `read_only` and automatic.
`save_note` is a `local_write` and always requires explicit approval. There are
no external-communication, destructive, financial, shell, browser, filesystem,
arbitrary Python, or integration tools.

The execution loop is:

1. The OpenAI Responses API returns native `function_call` output.
2. The runtime looks up only that exact name in the fixed registry, decodes JSON,
   and validates it with the tool's Pydantic model (`extra=forbid`).
3. A `tool_calls` row records the task, provider call ID, tool, validated audit
   arguments, risk/policy snapshot, timestamps, status, result, and safe error.
4. An automatic call executes its direct handler. Its JSON result is sent back
   as a `function_call_output`, and the model may continue.
5. An approval-gated call creates an `approval_requests` row, stores resumable
   model input in the task's internal `agent_state`, and moves the task to
   `waiting_for_approval` without executing the handler.
6. `POST /approvals/{id}/approve` or `/deny` records the decision. Once every
   call in that paused model turn has a decision, the task is requeued. Approval
   executes the exact validated call; denial returns a denial result to the
   model. Either way, the model can finish the task.

`GET /tools` exposes metadata only. `GET /tasks/{id}/tool-calls` exposes the
audit history, while `GET /approvals?status=pending` exposes understandable
pending actions. The internal handler callable and resumable `agent_state` are
never returned by the API. A local note and its successful tool-call audit are
committed in one PostgreSQL transaction.

The runtime supports multiple sequential tool turns and caps them with
`AGENT_MAX_TOOL_ROUNDS`. Parallel model tool calls are disabled for simpler,
deterministic approval behavior. Token usage is accumulated across turns.

## Notifications

Each task has one persisted notification policy. Schedules store the same
policy and copy it to every materialized task:

- `none`: never notify (the default);
- `on_completion`: notify only after successful completion;
- `on_failure`: notify only after task failure;
- `always`: notify after either terminal state.

The worker commits the task result, error, terminal status, and completion time
before attempting any notification. It then sends a small status-only message
through `NotificationService` and records a nested `notification` object in
`execution_metadata`. That audit object includes the policy, provider,
attempt/completion timestamps, status, the provider request identifier when
available, and a sanitized error on failure. It contains no credentials,
prompt, context, result body, or model output.

Pushover is the only configured provider in this iteration. Adding another
provider requires implementing the provider protocol and selecting it in the
service factory; task execution and policy logic remain unchanged. The
explicit `POST /notifications/test` endpoint sends a fixed, non-sensitive test
message and does not accept caller-controlled message text.

For non-check-in tasks, notification delivery remains best effort. Provider failures are
logged and audited without changing a successful task to failed or replacing a
task's original failure. There is no notification retry/outbox yet: a worker
crash after the task commit but before the provider call can omit a
notification, and a crash after provider acceptance but before audit commit can
leave its delivery unaudited. For check-ins, terminal state and a unique
`notification_deliveries` intent commit atomically. The worker sends after commit;
the dedicated scheduler independently retries with three total claims, 60/300
second failure delays, a 120-second claim lease, and an auditable unknown outcome
after interrupted claims. Delivery cannot rerun model work. A crash after send
but before audit may duplicate a push. A Pushover `sent` audit means its API
accepted the message, not that a device displayed it.

## Persistent Scheduling

A `Schedule` contains its task type and payload plus one timing form:

- `once`: one timezone-aware `run_at` value;
- `interval`: an interval of at least 60 seconds and optional `start_at`;
- `cron`: a five-field expression and an IANA timezone, defaulting to `UTC`.

`next_run_at`, `last_run_at`, and task occurrence times are stored as
timezone-aware PostgreSQL values and normalized to UTC. Cron is evaluated in
the named timezone, so daylight-saving transitions follow that timezone's
rules. Nonexistent wall times are skipped; ambiguous times run once at fold 0.
API timestamps without an offset are rejected.

For every poll, the scheduler:

1. Finds enabled schedules with `next_run_at <= now`.
2. Locks one schedule using `FOR UPDATE SKIP LOCKED`.
3. Inserts a `queued` task carrying `schedule_id` and `scheduled_for`.
4. Advances from the scheduled occurrence—not wall-clock time—and commits the
   occurrence and schedule state in one database transaction.
5. Enqueues the committed task in RQ.

The database constraint `UNIQUE (schedule_id, scheduled_for)` permits only one
task record for an occurrence. Row locks prevent overlapping scheduler
processes from advancing the same row concurrently. Downtime backlog is caught
up chronologically for generic tasks, limited by `SCHEDULER_MAX_CATCH_UP` per
schedule per poll; later polls continue draining remaining occurrences.
Check-ins coalesce all currently due occurrences into the earliest pending
identity and advance directly to the next future occurrence, recording the
covered window in task metadata.

Disabling stops materialization but preserves the schedule. Re-enabling an
overdue recurring schedule resumes at its next future occurrence, intentionally
skipping the disabled window; a still-future occurrence is preserved. An
overdue disabled one-time schedule runs after re-enable. A one-time schedule is
automatically disabled after materialization and cannot be re-enabled once
exhausted. Tasks remain execution history at `GET /schedules/{id}/tasks`.

## Recovery and Delivery Guarantees

PostgreSQL reconstructs task and schedule intent after an application, worker,
Redis, scheduler, or host restart. Manual, approval-resumed, and scheduled tasks
record an enqueue attempt before delivery. The scheduler retries RQ delivery
for every task still recorded as `queued`; a crash between database commit and
enqueue, or loss of Redis data, therefore does not silently lose it. Any task
left `running` beyond the effective stale threshold is returned to `queued` and
redelivered, except check-ins: they become terminal `uncertain`, retain their
snapshot and metadata, and reject late writes. Check-in model execution has no
automatic retry; its notification intent is handled independently.

Every claim assigns a fresh PostgreSQL `execution_id` UUID and resets
`started_at` to the current execution's start, including approval resumes.
Approval waiting time therefore cannot immediately age a resumed execution into
recovery. Recovery revokes ownership; pause, success and failure release it.
Every worker pause/result/failure write locks the current task row and requires
both `running` status and its own execution UUID. An obsolete worker cannot
overwrite recovered state or a newer execution, even while that newer execution
is also running. Duplicate delivery cannot claim an already running task. Waiting
metadata is removed when work resumes and on terminal completion; private
continuation state is retained for recovery and cleared on terminal completion.
Migration `0009` adds only the nullable ownership column; historical rows are
unchanged apart from that null column. Stop old runtime processes before upgrade:
old binaries do not enforce fencing.

This fences task outcomes, not remote requests or arbitrary handler side effects.
Recovery cannot cancel an old handler or provider request. There is no heartbeat,
lease renewal or append-only execution-attempt ledger. Existing tool-call row
locks and successful-call reuse still apply to approved local writes.

The system guarantees at most one PostgreSQL task record per schedule
occurrence. It does **not** guarantee exactly-once handler or model execution.
Delivery is at least once: if a worker or lease fails after a model request
succeeds but before its result commits, recovery may repeat that request. Every
RQ job has an explicit `RQ_JOB_TIMEOUT_SECONDS`. The effective stale
threshold is the greater of `SCHEDULER_STALE_TASK_SECONDS` and the RQ timeout
plus the enqueue-retry interval, so the reconciler does not knowingly reclaim a
job that RQ still permits to run. This is a timeout guard, not a durable lease or
heartbeat. Future side-effecting handlers require their own idempotency keys
and approval controls.

## Reliability Boundaries

PostgreSQL and Redis do not share a transaction. All task sources bridge that
gap with the reconciler above. A synchronous enqueue failure leaves the
accepted task `queued` with a sanitized `enqueue_error`; later scheduler polls
retry delivery. The API can therefore acknowledge durable acceptance even when
Redis is temporarily unavailable.

RQ delivery is at least once. Future handlers with side effects must therefore
be idempotent and governed by an explicit approval policy. Current task handlers
do not modify external systems; configured notifications are a separate,
post-terminal side effect with the limitations documented above.

Automatic tool execution is also at-least-once at the worker boundary. Existing
successful `tool_calls` are reused by provider call ID during a retry, and the
demo database write is transactionally coupled to its audit record. Future
external side effects still require provider idempotency keys; approval alone
does not make an operation exactly once.

Approval decisions survive process, Redis, and host restarts in PostgreSQL. A
crash after a decision commits but before RQ enqueue leaves the task `queued`;
the general reconciler retries it without requiring the user to repeat the
decision.

## Deliberate Stack Choices

- Synchronous SQLAlchemy and Psycopg keep the API and worker persistence model
  identical; V1 does not need async database complexity.
- RQ remains appropriate for a single-node, Python-only worker fleet.
- A single deployable image reduces version skew among API, worker, migration,
  and test processes.
- `croniter` supplies only recurrence calculation; scheduling state and
  execution remain application-owned and PostgreSQL-backed.
- No repository layer, event bus, scheduler framework, or agent framework is
  included.
- No vector database, embeddings, similarity search, implicit recall, or
  automatic memory extraction is included.
- The official OpenAI Python SDK is used directly behind one small service and
  its supported function-call protocol; there is no agent framework or text
  parsing protocol.

## Read-only repository inspection

Manual `github_discover` and `github_inspect` tasks reuse the task API, RQ worker,
execution UUID fencing, recovery and PostgreSQL JSON results. Migration `0010`
adds their task-type constraint values; schedule types remain unchanged. The
GitHub client signs file-backed App JWTs and exchanges them for short-lived,
read-only installation tokens after checking the configured personal owner.
Only the optional worker override mounts the protected key. Inspection holds a
PostgreSQL advisory lock, resolves one default-branch commit, then collects
bounded tree/blob evidence by immutable SHA, with hashes and explicit exclusions.
No model, tools, checkout, script execution, notifications or publishing path is
added. See [configuration, API and bounds](github-inspection.md).

## Documentation preview

Manual `documentation_preview` tasks prepare only explicitly selected immutable
inspection files/ranges into PostgreSQL task inputs. A tool-free editor proposes
bounded explanatory insertions; application policy builds and validates an exact
diff. A separate reviewer receives fresh context, the exact diff and selected
evidence. Candidate/review bindings include repository, base commit, input,
policy, model configuration and outcome. UUID-fenced checkpoints retain stage
intent and candidate/usage before review; the final transaction revalidates the
source inspection and binding under locks. Semantic preview outcomes are distinct
from infrastructure status. No automatic correction, publication or notification
exists. Like check-ins, interrupted previews become terminal uncertain without
model re-execution. Migration `0011` only adds the task type; no new persistence
layer or dependency. See [policy, API and opt-in budget](documentation-preview.md).

## Bounded documentation publication

Manual `documentation_publish` consumes an existing independently approved preview.
Migration `0012` adds a durable publication job and a unique active-repository
constraint. Repository advisory locks serialize handlers; each remote write holds
the current task execution claim lock through reconciliation and outcome recording.
The job persists deterministic Git objects, intent, branch/PR identifiers, exact
revision/check/policy authorization and separate published/merged/deployed outcomes.
Stale executions become uncertain and require explicit same-job reconciliation.
No scheduler materialization, model call, local checkout or repository execution
is added. Existing notification delivery retries independently. See the
[publishing guide](documentation-publishing.md) for supported GitHub requirements,
exact author identity, credential boundary and remote concurrency limitations.

## Daily repository maintenance

`documentation_maintenance` orchestrates ordinary inspection/preview/publication
child tasks. Migration `0013` adds explicit control, repository/assessment cache,
run and daily-reservation records plus child-parent ownership links. The existing
dedicated scheduler materializes one daily New York wall-time occurrence and
coalesces downtime. Global serialization, daily assessment/call/merge reservation,
parent/child fences and a pause generation constrain external actions. Account-wide
inspection access remains; readiness and the existing public model-sharing policy
are separately enforced. See the [operations guide](documentation-schedules.md).
