# Personal Dot

Personal Dot is a small, self-hosted foundation for a persistent personal AI
agent. It provides a durable API-to-queue-to-worker lifecycle, a narrow OpenAI
Responses API execution layer, PostgreSQL-backed scheduling, and concise
Pushover task notifications, and a permission-gated tool foundation without
arbitrary execution or real external integrations. Persistent memory is
explicitly selected and uses ordinary PostgreSQL queries—no embeddings or vector
database.

## V1 Services

- FastAPI API for tasks, schedules, and dependency health
- PostgreSQL authoritative task and schedule storage
- Redis/RQ background queue and worker
- Dedicated scheduler that materializes due schedules as ordinary tasks
- OpenAI Responses API agent handler through one isolated service
- Provider-neutral notification service with a Pushover adapter
- Fixed agent tool registry with durable call audits and approval/resume APIs
- Explicit persistent memory with deterministic ID/type/tag selection
- Manual project check-ins with bounded source snapshots and validated recommendations
- Alembic one-shot migration service
- Pytest integration tests against real PostgreSQL and Redis

## Requirements

- Docker Engine with Docker Compose
- `curl` for the example requests

## Start

```bash
cp .env.example .env
chmod 600 .env
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

`docker compose up` runs the one-shot `migrate` service before starting the API,
worker, and scheduler. To apply migrations explicitly after pulling a schema
change:

```bash
docker compose run --rm migrate
```

## Exercise the Lifecycle

```bash
curl --fail --request POST http://127.0.0.1:8000/tasks \
  --header 'Content-Type: application/json' \
  --data '{"type":"echo","payload":{"message":"hello"}}'

curl --fail http://127.0.0.1:8000/tasks
```

The worker should change the task from `queued` to `running` and then
`succeeded`. The `fail` task type intentionally exercises persisted failures.

To submit an agent task, first set `OPENAI_API_KEY` in the ignored `.env` file,
then recreate the API and worker so they receive the configuration:

```bash
docker compose up -d --build --force-recreate api worker

curl --fail --request POST http://127.0.0.1:8000/tasks \
  --header 'Content-Type: application/json' \
  --data '{"type":"agent","payload":{"instruction":"Summarize the context.","context":"Personal Dot runs locally."}}'
```

Agent results contain untrusted model text under `result.output`. The separate
`execution_metadata` object records model and token details without copying the
prompt or API key.

## Tool Calls and Approvals

The agent can request only two demonstration tools. `get_current_time` is a
read-only automatic call. `save_note` writes only to Personal Dot's local
database and pauses the task until the exact call is approved or denied.

```bash
curl --fail http://127.0.0.1:8000/tools
curl --fail 'http://127.0.0.1:8000/approvals?status=pending'
curl --fail http://127.0.0.1:8000/tasks/TASK_ID/tool-calls

curl --fail --request POST \
  http://127.0.0.1:8000/approvals/APPROVAL_ID/approve \
  --header 'Content-Type: application/json' \
  --data '{"reason":"I requested this specific note."}'

# Or deny it; the handler will not run and the model can continue.
curl --fail --request POST \
  http://127.0.0.1:8000/approvals/APPROVAL_ID/deny \
  --header 'Content-Type: application/json' \
  --data '{"reason":"Do not perform this action."}'
```

The API is intentionally unauthenticated and bound to loopback. Do not expose
approval endpoints remotely until authentication and TLS exist. Model arguments
and tool results are untrusted, schema-validated/audited data; neither provides
authorization.

## Persistent Memory

Memories are created explicitly and are never inferred automatically from task
history or model output:

```bash
curl --fail --request POST http://127.0.0.1:8000/memories \
  --header 'Content-Type: application/json' \
  --data '{"type":"user_preference","content":"Use metric units.","source":"manual","tags":["profile"]}'

curl --fail 'http://127.0.0.1:8000/memories?type=user_preference&tag=profile&enabled=true'
```

Pass an explicit selector in an agent task. Without `memory`, no stored memories
are sent to the model:

```bash
curl --fail --request POST http://127.0.0.1:8000/tasks \
  --header 'Content-Type: application/json' \
  --data '{"type":"agent","payload":{"instruction":"Give me a measurement.","memory":{"ids":["MEMORY_ID"],"types":[],"tags":[],"limit":10}}}'
```

Inspect, edit, disable, re-enable, or permanently delete a memory with:

```bash
curl --fail http://127.0.0.1:8000/memories/MEMORY_ID
curl --fail --request PATCH http://127.0.0.1:8000/memories/MEMORY_ID \
  --header 'Content-Type: application/json' --data '{"enabled":true}'
curl --fail --request POST http://127.0.0.1:8000/memories/MEMORY_ID/disable
curl --fail --request DELETE http://127.0.0.1:8000/memories/MEMORY_ID
```

Selected content is sent to OpenAI as untrusted reference context. Disabling or
deleting it prevents future retrieval but cannot retract content already sent in
an earlier model request.

Add `notification_policy` to any manual task or nested scheduled task. Supported
values are `none` (default), `on_completion`, `on_failure`, and `always`:

```bash
curl --fail --request POST http://127.0.0.1:8000/tasks \
  --header 'Content-Type: application/json' \
  --data '{"type":"agent","payload":{"instruction":"Reply briefly."},"notification_policy":"on_completion"}'
```

The task result is committed before notification delivery. Notification audit
data is then recorded under `execution_metadata.notification`; delivery failure
does not change the task's result or terminal status.

## Manual Project Check-In

Apply migrations and rebuild the API/worker after updating the application:

```bash
docker compose build api worker migrate
docker compose run --rm migrate
docker compose up -d api worker
```

Configure `OPENAI_API_KEY` in the ignored `.env` file as described above. Running
a real check-in makes one paid model request. Development tests use stub
providers and never require a real key or send a notification.

Create a project note through the existing memory API. This example captures its
ID using Python 3; existing `project_note` memory IDs work as well:

```bash
CHECK_IN_NOTE_ID=$(curl --fail --silent --show-error \
  --request POST http://127.0.0.1:8000/memories \
  --header 'Content-Type: application/json' \
  --data '{"type":"project_note","content":"The project check-in has no input-size guard yet. A boundary test is also missing.","source":"manual","tags":["personal-dot"]}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl --fail --request POST http://127.0.0.1:8000/tasks \
  --header 'Content-Type: application/json' \
  --data "{\"type\":\"project_check_in\",\"payload\":{\"project_id\":\"personal-dot\",\"note_ids\":[\"$CHECK_IN_NOTE_ID\"],\"priorities\":[\"Bound project inputs before accepting a check-in.\"]},\"notification_policy\":\"none\"}"

# Replace TASK_ID with the returned task ID; poll until succeeded or failed.
curl --fail http://127.0.0.1:8000/tasks/TASK_ID
```

Each request covers one project key (`project_id`, a lowercase slug of up to 64
characters), 1–10 unique, enabled `project_note` IDs, and 1–5 nonblank priorities
of at most 500 characters each. Selection is explicit; no files, repositories,
tags, or other memories are crawled. A note may contain at most 5,000 characters.
The serialized context, including identities and any reused prior result, is
capped at 24,000 characters. Missing, disabled, wrong-type, empty, duplicate, and
oversized inputs return HTTP 422 before a task is queued.

The API snapshots the accepted note contents, timestamps, SHA-256 hashes, and
priorities in `task.payload`. Stable IDs are `memory:<uuid>`,
`priority:<project_id>:<position>`, and `task:<uuid>` for prior results. The exact
context hash is recorded in `execution_metadata.check_in`. Edits, disabling, or
deleting a memory after submission do not erase or change an already accepted
task snapshot; task records/backups contain private input data.

At submission, the application may reuse the latest successful `ready` result
with the same project key, exact note-ID set, and exact ordered priorities.
Failed, insufficient, and unrelated results are excluded. Prior results are
labelled untrusted model inferences, and omitted if they would exceed the context
budget. This uses ordinary task queries, with no semantic memory.

The worker calls the existing model adapter with tools disabled, at most 2,048
output tokens, a 60-second SDK timeout, and no SDK retries. Smaller configured
limits still apply; the existing RQ job timeout bounds the whole job.
Queue delivery remains at least once. Interrupted check-in execution becomes
terminal `uncertain` without automatic model retry. The result must be
valid JSON with:

- `schema_version: 1`, a short `summary`, `blockers`, and `uncertainty`;
- `status: "ready"` and one `recommended_action` with `kind`, `description`,
  `rationale`, and `source_ids`; or `status: "insufficient_information"`, a null
  action, and nonempty uncertainty;
- `supporting_source_ids` containing every cited source. Blockers require current
  note evidence; an action requires a current note and a supplied priority.

Action kinds are advisory: `advance_priority`, `resolve_blocker`, and
`clarify_context`. No action is executed. Schema and structured citation checks reject
invalid output; they cannot prove that a model's interpretation is correct.
Model/validation failures persist a safe task error, and summaries remain task
results rather than becoming user preferences or new memories.

The [check-in evaluation guide](evaluations/check_in/README.md) provides 21
synthetic cases, deterministic contract checks, a human quality rubric, and
explicitly gated paid generation. Default evaluation makes no model API calls
and supplies no evidence of real model quality. See [STATUS](docs/STATUS.md) for
the independent review and current validation limits.

Notifications default to `none`. An explicit `on_completion` policy opts in to
the existing status-only Pushover notification after the result commits; provider
failure is audited without changing the result or terminal status. A successful
insufficient-information result also counts as task completion. Notifications do
not include the recommendation or note text. Check-ins now persist notification
intent with the terminal result and retry delivery independently, up to three
attempts. Interrupted requests become `uncertain` without automatic model retry.

Check-ins can use the existing persistent scheduler. Creation defaults to
disabled and a separate operator enable is required; this milestone enables no
live recurrence. The [scheduled check-in guide](docs/scheduled-check-ins.md)
defines occurrence identity, downtime coalescing, timezone/DST behavior, overlap
prevention, notification retry limits, and exact inspect/enable/pause/disable
commands.

For a controlled live check with one model request and one push attempt, follow
the [operations procedure](docs/scheduled-check-ins.md#controlled-live-verification).
It requires explicitly selected personal notes, credentials and an approved
budget; normal notification retries must remain stopped during the test.

## Configure Pushover

[Register a Pushover application](https://pushover.net/api), then copy its
application/API token and your user or group key into the ignored `.env` file:

```dotenv
NOTIFICATION_PROVIDER=pushover
PUSHOVER_API_TOKEN=replace-with-your-application-token
PUSHOVER_USER_KEY=replace-with-your-user-or-group-key
```

Recreate the API and worker so they receive the environment values, then send
one fixed test notification:

```bash
docker compose up -d --force-recreate api worker
curl --fail --request POST http://127.0.0.1:8000/notifications/test
```

Credentials are never accepted through the API. The test endpoint does not
accept custom text, and automated tests always mock the external request.

## Schedule a Task

All API datetimes must include an offset and are normalized to UTC. Cron
expressions use exactly five fields and an IANA timezone name.

```bash
# Run once. Use a future UTC timestamp.
curl --fail --request POST http://127.0.0.1:8000/schedules \
  --header 'Content-Type: application/json' \
  --data '{"name":"one-time check","schedule_type":"once","run_at":"2030-01-01T12:00:00Z","task":{"type":"echo","payload":{"message":"scheduled"}}}'

# Run every five minutes, beginning five minutes after creation.
curl --fail --request POST http://127.0.0.1:8000/schedules \
  --header 'Content-Type: application/json' \
  --data '{"name":"interval check","schedule_type":"interval","interval_seconds":300,"task":{"type":"echo","payload":{"message":"scheduled"}}}'

# Five-field cron in an explicit timezone.
curl --fail --request POST http://127.0.0.1:8000/schedules \
  --header 'Content-Type: application/json' \
  --data '{"name":"weekday check","schedule_type":"cron","cron_expression":"0 9 * * 1-5","timezone":"America/New_York","task":{"type":"echo","payload":{"message":"scheduled"}}}'

curl --fail http://127.0.0.1:8000/schedules
curl --fail http://127.0.0.1:8000/schedules/SCHEDULE_ID/tasks
curl --fail --request PATCH http://127.0.0.1:8000/schedules/SCHEDULE_ID \
  --header 'Content-Type: application/json' \
  --data '{"enabled":false}'
```

The scheduler catches up missed generic recurring occurrences in bounded
batches. Project check-ins coalesce downtime into one occurrence. See
[scheduled check-ins](docs/scheduled-check-ins.md) and `docs/architecture.md` for
duplicate prevention, recovery, and delivery limitations.

## Test

```bash
docker compose run --rm --build test
```

The test service uses a separate `personal_dot_test` database and Redis database
1. It creates the test database if needed, applies migrations, and runs the
health, task lifecycle, scheduling, recovery, duplicate-prevention, and
notification tests plus automatic, approved, denied, and invalid tool-call
lifecycles, memory persistence, memory CRUD, and explicit memory inclusion
without making external notification calls.

Normal tests mock agent execution and never make a paid API request. A single
live lifecycle test is available only when both a key and an explicit opt-in
are provided:

```bash
RUN_OPENAI_INTEGRATION=1 docker compose run --rm --build test \
  pytest -m integration tests/test_openai_integration.py
```

This creates a real Responses API request, so it may incur API charges.

## Logs and Shutdown

```bash
docker compose logs --tail=100 api worker scheduler migrate postgres redis
docker compose down
```

`docker compose down` preserves named data volumes. `docker compose down -v`
also deletes all local PostgreSQL and Redis data and should be used only when
that data is intentionally disposable.

## Configuration

Configuration is environment-backed; see `.env.example`. `OPENAI_MODEL`,
`OPENAI_REASONING_EFFORT`, and `OPENAI_OUTPUT_VERBOSITY` control model behavior
centrally. `AGENT_MAX_TOOL_ROUNDS` caps model/tool loops.
`RQ_JOB_TIMEOUT_SECONDS` bounds worker runtime, while stale recovery is kept
beyond that timeout and reconciles every durable queued task. Agent tasks fail
with a persisted configuration error when
`OPENAI_API_KEY` is missing. Compose binds the API to loopback and does not
publish PostgreSQL or Redis ports. Do not expose the API remotely until
authentication and TLS are added.

Architecture, scope, and security rationale live in `docs/`.

## Host Note for Redis

Redis may warn on Linux when `vm.overcommit_memory` is disabled. The stack still
runs, but enabling it is recommended for reliable background saves under memory
pressure. Inspect it with `sysctl vm.overcommit_memory`; make any persistent
change through the Ubuntu host's normal sysctl configuration after reviewing
the machine-wide impact. Compose intentionally does not modify host settings.
