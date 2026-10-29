# Persistent project check-ins

## Hardening verification — 2026-10-29

Citation and diagnostic fixes are deployed at schema `0008`; application sources
match the checkout. Both real schedules remain disabled. Synthetic verification
passed 140 tests (one paid test skipped), all 21 corpus contracts, and a manual
container lifecycle with stub delivery retry. No live quality is established.
See [current evidence and limitations](STATUS.md#citation-and-diagnostic-hardening--2026-10-29).

Recognized prose citations use the literal `memory:<id>`, `task:<id>`, or
`priority:<project_id>:<position>` token, optionally wrapped in Markdown. Every
prose field and structured citation must refer to the accepted snapshot; prose
IDs must also be listed in supporting sources. Ordinary Markdown/brackets/code
are not citation syntax. Namespaced IDs inside code are still checked. An ID's
existence does not prove that a claim follows from that source; inspect source
support during the controlled live review.

Expected validation failure: task `failed`, null result, fixed invalid-result
error, retained usage/request IDs, and no on-completion notification. Generic
failures use fixed classifications (`database_error`, `queue_unavailable`,
`timeout`, `unexpected_error`); queue failures remain queued for durable retry.
Operational logs and RQ failures omit raw exception bodies and chains. Correlate
task/schedule/request/response IDs, timestamps, health and queue state; do not
turn on payload/provider/SQL debug logging to recover withheld error text.
Unexpected API failures return a fixed HTTP 503. If the terminal database write
fails, the task may remain running until stale reconciliation. This deployment
does not repair delayed generic approval resume or stale waiting metadata.

For future synthetic verification, use a fresh isolated manifest with
`--stub-check-in-providers`, then run the existing container smoke harness
without creating or enabling any schedule:

```bash
docker compose -p pd-eval-YOUR-FRESH-NAME -f /tmp/YOUR-ISOLATED-MANIFEST.json \
  exec -T api python -m tests.scheduled_lifecycle_smoke --manual-only
```

The manifest must have blank credentials, paid gates off, an internal network,
no published ports, and fresh disposable data. The smoke harness checks the stub
gate/empty database, submits only a synthetic manual task and advances only its
isolated delivery retry deadline. Do not invoke its default scheduling path when
recurrence is outside authorization. Never run destructive test fixtures against
the normal database. Keep the live runbook's selected-input, budget and single
attempt controls; this milestone authorizes no live submission or notification.

The existing dedicated `personal_dot.scheduler` process materializes check-ins
from PostgreSQL schedules. No live schedule is installed or enabled by this
milestone. Creating a check-in schedule defaults to `enabled=false`; explicitly
requesting `enabled=true` at creation is rejected. A separate PATCH is required.
Enabling authorizes the configured recurring, potentially paid, tool-free model
requests and the selected status-only notification policy. Keep the API local.

For a single live check, use [the controlled verification procedure](#controlled-live-verification)
below. Normal notification delivery permits three attempts; it does not meet a
one-message-attempt test budget without the maintenance procedure.

## Operator commands

Run from the repository root. First build and migrate using the intended
deployment's environment, then start the existing processes:

```bash
docker compose build api worker scheduler migrate
docker compose run --rm migrate
docker compose up -d api worker scheduler
```

For an existing installation, first inspect pending work and take a database
backup before rebuilding/migrating. Do not start a scheduler with enabled
schedules or pending deliveries under a one-attempt authorization. The
controlled procedure below keeps both background services stopped until review.

Routine health checks (no provider call):

```bash
API_BASE=http://127.0.0.1:8000
docker compose ps --all
curl --fail-with-body -sS "$API_BASE/health" | python3 -m json.tool
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

`/health` checks PostgreSQL and Redis. It does not verify installed check-in
support, OpenAI availability, Pushover credentials, or device receipt. Current
source expects migration `0008`; an older image may call its own `0006` revision
"head". Rebuild all application processes together when upgrading.

The following creation command stays disabled. Replace the note UUID with an
existing enabled `project_note` selected by the operator. Use a consistent
project slug across manual and scheduled check-ins for overlap protection.

```bash
API_BASE=http://127.0.0.1:8000
NOTE_ID=replace-with-selected-project-note-uuid
cat > /tmp/project-check-in-schedule.json <<EOF
{
  "name": "Personal Dot weekday check-in",
  "schedule_type": "cron",
  "cron_expression": "0 9 * * 1-5",
  "timezone": "America/New_York",
  "enabled": false,
  "task": {
    "type": "project_check_in",
    "notification_policy": "none",
    "payload": {
      "project_id": "personal-dot",
      "note_ids": ["$NOTE_ID"],
      "priorities": ["Deliver the current milestone with bounded, verified behavior."]
    }
  }
}
EOF
SCHEDULE_ID=$(curl --fail-with-body -sS "$API_BASE/schedules" \
  -H 'Content-Type: application/json' --data-binary @/tmp/project-check-in-schedule.json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

Inspect configuration and occurrence history (these reads include private inputs):

```bash
curl --fail-with-body -sS "$API_BASE/schedules" | python3 -m json.tool
curl --fail-with-body -sS "$API_BASE/schedules/$SCHEDULE_ID" | python3 -m json.tool
curl --fail-with-body -sS "$API_BASE/schedules/$SCHEDULE_ID/tasks" | python3 -m json.tool
docker compose logs --tail=100 scheduler worker
```

Enable only when the operator intends recurring execution. **This command was
not run against any live schedule during this milestone.**

```bash
curl --fail-with-body -sS -X PATCH "$API_BASE/schedules/$SCHEDULE_ID" \
  -H 'Content-Type: application/json' -d '{"enabled":true}'
```

Pause:

```bash
curl --fail-with-body -sS -X PATCH "$API_BASE/schedules/$SCHEDULE_ID" \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

Disable uses the same persisted operation and retains history:

```bash
curl --fail-with-body -sS -X PATCH "$API_BASE/schedules/$SCHEDULE_ID" \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

Pause/disable stops future materialization once the PATCH commits. A concurrent
materialization that committed first, already queued/running tasks, and pending
notification deliveries continue. This is not task cancellation. Re-enable
skips the disabled recurring window and schedules the next future occurrence.
Timing, selected inputs, priorities, and notification policy are immutable on
existing schedules: disable the old schedule and create a disabled replacement.
Do not delete history to alter configuration.

Inspect a particular task, including independent notification delivery history:

```bash
TASK_ID=replace-with-task-uuid-from-history
curl --fail-with-body -sS "$API_BASE/tasks/$TASK_ID" | python3 -m json.tool
```

## Controlled live verification

Preflight on **2026-10-23** was blocked before task submission. The running
API/worker use `gpt-6-luna`, reasoning `low`, verbosity `medium`, configured
output cap 4,096, timeout 120 seconds and SDK retries 2. The check-in handler in
current source would narrow those to 2,048 output tokens, 60 seconds and zero
retries, without changing the model. OpenAI credentials were present; neither
`PUSHOVER_API_TOKEN` nor `PUSHOVER_USER_KEY` was set in `.env` or the running
API/worker. No explicit `project_id`/`note_ids`/`priorities` selection or live-test
budget was configured. Both stored schedules were disabled generic-agent
schedules, not check-in selections. The running image/database were at `0006`
and the worker lacked both the check-in handler and notification outbox module.
Health was OK. No notes were selected/read, no task was submitted, and no model
request or push was attempted. No live result or delivery was therefore verified.

The commands below are a local continuation procedure, **not evidence of a
completed live test**. Run once the operator supplies the missing configuration.
Do not run the synthetic smoke harness against the personal database, substitute
README fixture notes, change the configured model, or test Pushover separately:
that would spend an additional message from the one-attempt allowance.

### Supply the missing configuration privately

From the repository root, edit the ignored `.env` without echoing credentials:

```bash
chmod 600 .env
"${EDITOR:-vi}" .env
# Set PUSHOVER_API_TOKEN and PUSHOVER_USER_KEY; retain the existing OPENAI_* model settings.
umask 077
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/personal-dot-live.XXXXXXXX")
API_BASE=http://127.0.0.1:8000
curl --fail-with-body -sS "$API_BASE/memories?type=project_note&enabled=true&limit=200" \
  > "$RUN_DIR/available-notes.json"
"${EDITOR:-vi}" "$RUN_DIR/available-notes.json"
```

Review the existing personal notes locally and select their actual UUIDs. This
listing is private and is not permission to send every listed note. If no
appropriate notes exist, stop and explicitly create/select personal project
notes; do not use synthetic fixtures. Create these private worksheets:

```bash
cat > "$RUN_DIR/request.json" <<'JSON'
{
  "type": "project_check_in",
  "notification_policy": "always",
  "payload": {"project_id": "", "note_ids": [], "priorities": []}
}
JSON
cat > "$RUN_DIR/budget.json" <<'JSON'
{
  "max_model_requests": 1,
  "max_pushover_attempts": 1,
  "max_total_cost_usd": null,
  "approved": false
}
JSON
"${EDITOR:-vi}" "$RUN_DIR/request.json"
"${EDITOR:-vi}" "$RUN_DIR/budget.json"
```

Fill the real project slug, 1–10 selected note UUIDs, 1–5 operator priorities,
and a positive approved test spend cap. Set `approved=true` only after reviewing
the configured model's current price and the maximum request size against that
cap. These files are operator worksheets, **not new application environment
settings**. The application enforces request/context/output limits, not a hard
USD ceiling. If the required spend cap cannot be established with current
limits and provider controls, stop. Do not infer a budget from a token cap or
invent a price. Record actual billed cost later; unavailable cost stays unknown.
`always` requests one status-only delivery after success, failure or uncertainty.

```bash
python3 - "$RUN_DIR/budget.json" <<'PY'
import json, sys
from decimal import Decimal
b = json.load(open(sys.argv[1]))
assert b['approved'] is True
assert b['max_model_requests'] == b['max_pushover_attempts'] == 1
amount = Decimal(str(b['max_total_cost_usd']))
assert amount.is_finite() and amount > 0
print('Operator budget worksheet approved; currency cap is not enforced by the application.')
PY
```

### Prepare a quiet maintenance window and current runtime

First ensure there is no unrelated queued/running/approval-waiting work and no
enabled schedule. Otherwise stop and arrange a quiet window; do not cancel or
flush existing work to make the test fit. This read works with the older schema:

```bash
docker compose exec -T api python - <<'PY'
from sqlalchemy import text
from personal_dot.db import engine
with engine.connect() as c:
    active = c.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('queued','running','waiting_for_approval')"))
    enabled = c.scalar(text('SELECT count(*) FROM schedules WHERE enabled'))
assert active == enabled == 0, 'Arrange a quiet window before continuing'
print('No active tasks or enabled schedules.')
PY
docker compose stop scheduler worker api
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$RUN_DIR/before.sql"
docker compose build api worker scheduler migrate
docker compose run --rm --no-deps migrate
docker compose up -d --no-deps api
curl --fail-with-body -sS "$API_BASE/health" | python3 -m json.tool
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

Require `0008` and healthy dependencies. Keep the normal worker and scheduler
stopped throughout this test. Other clients must not submit work during the
window. Verify credentials as booleans only, and require no outstanding pushes:

```bash
docker compose exec -T api python - <<'PY'
from sqlalchemy import select, func
from personal_dot.config import get_settings
from personal_dot.db import SessionLocal
from personal_dot.models import NotificationDelivery
s = get_settings()
for key in ('openai_api_key', 'pushover_api_token', 'pushover_user_key'):
    secret = getattr(s, key)
    present = bool(secret and secret.get_secret_value().strip())
    print(key, 'set' if present else 'MISSING')
    assert present, 'Missing credential; stop before task submission'
print('Model:', s.openai_model, 'reasoning:', s.openai_reasoning_effort, 'verbosity:', s.openai_output_verbosity)
with SessionLocal() as db:
    assert db.scalar(select(func.count()).select_from(NotificationDelivery).where(
        NotificationDelivery.status.in_(['pending', 'sending']))) == 0, 'Existing delivery requires separate review'
PY
docker compose exec -T api python -c \
  'import sys; from personal_dot.schemas import TaskCreate; r=TaskCreate.model_validate_json(sys.stdin.read()); assert r.type.value=="project_check_in" and r.notification_policy.value=="always"; print("Request structure valid")' \
  < "$RUN_DIR/request.json" > "$RUN_DIR/request-validation.log" 2>&1
```

Validation errors can include private input; inspect that log locally. The task
API additionally validates the selected notes before durable acceptance.

### Submit exactly once and run one forked RQ job

```bash
date -u +%FT%TZ > "$RUN_DIR/submitted-at.txt"
curl --retry 0 --max-time 30 --fail-with-body -sS "$API_BASE/tasks" \
  -H 'Content-Type: application/json' --data-binary @"$RUN_DIR/request.json" \
  > "$RUN_DIR/accepted.json"
TASK_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$RUN_DIR/accepted.json")
```

Do not repeat the POST after a timeout or lost response: the task may already
exist. With the worker/scheduler stopped, inspect `/tasks` and the saved
submission timestamp locally to identify the original acceptance first. If
acceptance is ambiguous, leave the test stopped; do not invent a replacement ID.

The following one-off worker keeps the existing model configuration, explicitly
disables SDK retries, and narrows the existing delivery module's limit **only in
this verification process and its forked work child**. No provider is stubbed.
The normal three-attempt scheduler must remain stopped. A single failed delivery
becomes exhausted; no HTTP provider retry is configured. Queue ownership is
checked without deleting or rebuilding Redis data:

```bash
docker compose run --rm --no-deps -T -e TASK_ID="$TASK_ID" -e OPENAI_MAX_RETRIES=0 worker python - \
  > "$RUN_DIR/worker.log" 2>&1 <<'PY'
import os, uuid
from rq import Worker
from sqlalchemy import select
from personal_dot import notification_delivery
from personal_dot.db import SessionLocal
from personal_dot.models import Task, TaskStatus, TaskType, Schedule
from personal_dot.queue import get_queue, get_redis
from personal_dot.structured_logging import configure_logging
task_id = os.environ['TASK_ID']
with SessionLocal() as db:
    task = db.get(Task, uuid.UUID(task_id))
    assert task and task.type == TaskType.PROJECT_CHECK_IN and task.schedule_id is None
    assert task.status == TaskStatus.QUEUED and task.notification_policy.value == 'always'
    assert list(db.scalars(select(Task.id).where(Task.status.in_([
        TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_FOR_APPROVAL])))) == [task.id]
    assert not list(db.scalars(select(Schedule.id).where(Schedule.enabled.is_(True))))
queue = get_queue()
jobs = queue.get_jobs()
assert len(jobs) == 1 and tuple(jobs[0].args) == (task_id,)
assert jobs[0].func_name == 'personal_dot.jobs.execute_task'
notification_delivery.MAX_ATTEMPTS = 1
configure_logging('live-verification', 'INFO')
Worker([queue], connection=get_redis()).work(burst=True, max_jobs=1, with_scheduler=False)
PY
```

If queue delivery failed, stop and inspect the existing task's `enqueue_error`.
Do not resubmit the task or run the default scheduler to repair it within this
test. If the worker crashes, do not rerun it or resume background processes:
an unfinished notification claim would otherwise be eligible under the normal
three-attempt policy. Preserve the record and logs for explicit one-task repair.
This maintenance procedure is not a durable per-task retry setting or a
crash-proof spending guarantee.

### Inspect result, sources, usage, and independent delivery

```bash
curl --fail-with-body -sS "$API_BASE/tasks/$TASK_ID" > "$RUN_DIR/result.json"
docker compose exec -T api python -c \
  'import json,sys; from personal_dot.check_in import validate_check_in_output; from personal_dot.check_in_schemas import PreparedCheckIn; t=json.load(sys.stdin); assert t["status"]=="succeeded"; validate_check_in_output(json.dumps(t["result"]), PreparedCheckIn.model_validate(t["payload"])); m=t["execution_metadata"]; print(json.dumps({"task_id":t["id"],"status":t["status"],"model":m.get("model"),"provider":m.get("provider"),"response_id":m.get("response_id"),"request_id":m.get("request_id"),"usage":m.get("usage"),"notification":m.get("notification")},indent=2))' \
  < "$RUN_DIR/result.json" > "$RUN_DIR/evidence.json"
"${EDITOR:-vi}" "$RUN_DIR/result.json"
"${EDITOR:-vi}" "$RUN_DIR/evidence.json"
```

Re-read through the API from a fresh connection and compare the immutable task
snapshot/result; inspect the worker log for exactly one `task_started` and one
`agent_request_started` for this job. Inspect notification metadata separately:
`attempt_count=1`, one attempt entry, `provider=pushover`, and `delivery_status=sent`
establish one recorded provider acceptance. Model metadata and token usage are
reported only where the provider returned them. A schema-valid
`insufficient_information` result has no recommendation; record that honestly
rather than claiming a recommended action was verified. For a ready result,
check that the action references selected current-note and supplied-priority IDs.
The validator checks structured citations; also review prose for invented IDs
and whether the recommendation actually follows from the selected evidence.

`sent` proves provider acceptance only. **The operator must manually check the
phone for receipt, arrival time, content and duplicate notifications.** Neither a
provider ID nor a single audit row establishes device display or exactly-once
delivery. Record "no duplicate observed" only after the log/audit and phone
checks, within the observed test window.

For notification failures, read `execution_metadata.notification.status`,
`delivery_status`, `attempt_count`, `attempts`, fixed `error`, and provider request
ID when present in the saved evidence. A succeeded task with an exhausted push
is a notification failure, not a reason to rerun model work. For failed or
uncertain model work, inspect the full task's safe error locally; result/usage
may be absent. Do not run `/notifications/test`, resend the push, or resubmit the
task after failure without a new authorization and budget.

Check the independent PostgreSQL delivery row and the resume conditions with
a fresh connection; this command never calls either provider:

```bash
docker compose exec -T -e TASK_ID="$TASK_ID" api python - <<'PY'
import os, uuid, json
from sqlalchemy import select, func
from personal_dot.db import SessionLocal
from personal_dot.models import Task, TaskStatus, Schedule, NotificationDelivery
with SessionLocal() as db:
    task = db.get(Task, uuid.UUID(os.environ['TASK_ID']))
    delivery = db.get(NotificationDelivery, task.id)
    assert task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.UNCERTAIN)
    assert delivery and delivery.status in ('sent', 'exhausted')
    assert delivery.attempt_count == len(delivery.attempts) == 1
    assert db.scalar(select(func.count()).select_from(Task).where(Task.status.in_([
        TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_FOR_APPROVAL]))) == 0
    assert db.scalar(select(func.count()).select_from(Schedule).where(Schedule.enabled.is_(True))) == 0
    assert db.scalar(select(func.count()).select_from(NotificationDelivery).where(
        NotificationDelivery.status.in_(['pending', 'sending']))) == 0
    print(json.dumps({'task_id': str(task.id), 'task_status': task.status.value,
        'result_persisted': task.result is not None, 'delivery_status': delivery.status,
        'delivery_attempts': delivery.attempt_count}))
PY
```

Resume the ordinary worker/scheduler **only after** the one-off worker exited,
the tested task is terminal, its delivery is `sent` or `exhausted`, there is no
other queued/running work or pending/sending delivery, and all schedules remain
disabled. Otherwise keep the maintenance window closed for explicit repair.

```bash
docker compose up -d --no-deps worker scheduler
docker compose ps
```

This starts processes; it does not authorize enabling recurrence. Configure a
new disabled check-in schedule from the reviewed selection using the existing
operator commands above. No check-in schedule ID existed at this preflight, so
none is invented here. At the operator's chosen time, set `SCHEDULE_ID` to that
new disabled schedule's returned ID and run exactly:

```bash
curl --fail-with-body -sS -X PATCH "$API_BASE/schedules/$SCHEDULE_ID" \
  -H 'Content-Type: application/json' -d '{"enabled":true}'
```

Pause or disable with the same command and `'{"enabled":false}'`. Resuming
normal scheduling restores its ordinary notification retry policy; the
one-attempt worker override is not permanent.

## Two-week usage log

Copy this template into a private operator log after the first live attempt;
fill dates and task IDs as they occur. No two-week observation or live outcome
is claimed yet. Score usefulness 0 (unhelpful), 1 (partly useful), or 2 (clear
bounded next step); separately record unsupported facts/references and whether
the recommendation repeats completed work. For each day record failures,
uncertainty, phone receipt/duplicates, input/output/reasoning tokens when
available, and **actual billed USD** reconciled against provider usage/billing.
Leave unreported cost as `unknown`; do not present token-based estimates or
monthly Pushover charges as per-run actual cost. Do not put private note text,
recommendations or credentials into Git. Summarize the two weeks only after use.

| Day | UTC date / task ID | Usefulness / factual support | Failures / phone / duplicates | Token usage | Actual billed USD |
| --- | --- | --- | --- | --- | --- |
| 1 | — | — | — | — | unknown |
| 2 | — | — | — | — | unknown |
| 3 | — | — | — | — | unknown |
| 4 | — | — | — | — | unknown |
| 5 | — | — | — | — | unknown |
| 6 | — | — | — | — | unknown |
| 7 | — | — | — | — | unknown |
| 8 | — | — | — | — | unknown |
| 9 | — | — | — | — | unknown |
| 10 | — | — | — | — | unknown |
| 11 | — | — | — | — | unknown |
| 12 | — | — | — | — | unknown |
| 13 | — | — | — | — | unknown |
| 14 | — | — | — | — | unknown |

## Occurrence and downtime policy

- PostgreSQL owns the schedule cursor and the occurrence identity
  `(schedule_id, scheduled_for)` in UTC. The existing unique constraint and
  `FOR UPDATE SKIP LOCKED` transaction prevent duplicate task rows across polls,
  restarts, or concurrent schedulers. Redis/RQ job IDs are transport identities.
- For check-ins, one recovery poll coalesces all currently overdue occurrences
  into one task identified by the **earliest unmaterialized** due timestamp.
  The next cursor jumps strictly into the future. Task metadata records
  `schedule.missed_policy=coalesce`, `scheduled_for`, and `coalesced_through`.
  Other missed timestamps intentionally have no task rows. This prevents an
  enabled schedule's downtime from causing a backlog of paid requests.
  Existing non-check-in schedules retain bounded chronological catch-up.
- A disabled interval/cron gap is skipped on enable. A due one-time schedule
  runs once on enable; an exhausted one-time schedule cannot be re-enabled.
  Interval recurrence is anchored UTC elapsed time, regardless of timezone.
  Cron uses five-field local wall time in the configured IANA zone, including
  `America/New_York`. Nonexistent spring-forward times are skipped. Ambiguous
  fall-back times run once, at the first occurrence (fold 0). A 09:00 New York
  check-in therefore changes UTC offset across DST while retaining 09:00 local.
- At materialization, only the configured note IDs and priorities are selected;
  current note content is snapshotted and hashed using the existing bounded
  check-in contract. Creation and enable also validate current inputs, without
  storing a stale schedule-level snapshot. Missing/disabled/invalid notes later
  produce a failed occurrence with a fixed diagnostic and advance the schedule;
  they never trigger a model request. No implicit memory selection is added.

## Execution and notification bounds

All manual and scheduled check-ins use a PostgreSQL transaction advisory lock
keyed by project slug, held on a dedicated connection across execution and the
initial notification attempt. A competing queued check-in fails immediately
with `execution_outcome=skipped_overlap`; it makes no model call and is not
retried. A duplicate delivery of the same running/completed task is harmless.
Different slugs are independent even if they select the same note; use the same
slug to identify the same project. Hash collisions can cause conservative skips.

Each task permits at most one model request, zero SDK retries, at most 2,048
output tokens, a 60-second SDK timeout (or smaller configured limits), and the
existing RQ job timeout. Redis delivery retries retain the same PostgreSQL task.
There is **no automatic model execution retry** for check-ins. After the existing
stale threshold (at least RQ timeout plus delivery-retry interval), an interrupted
`running` check-in becomes terminal `uncertain`, preserving its snapshot/start
metadata. Transport timeout/connection failures also become `uncertain`, because
the provider may have accepted work. Late worker completion/failure cannot
overwrite that state. An uncertainty record is not proof of model failure,
success, cost, or cancellation; the operator must inspect before submitting a
new manual task. Generic agent/approval recovery is unchanged.

Uncertainty terminates that task; it does not automatically pause the schedule
or block the project forever. Future occurrences remain eligible after the
local project lock is released and still permit only one request per occurrence.
If the interrupted local handler still holds its lock, competing work is skipped.
The regression suite verifies future scheduled execution after an uncertain
task while preserving the original uncertainty. Remote provider work might still
continue after a transport timeout; local serialization cannot establish its
termination. Pause the schedule when operator review is required before further
requests.

For check-ins only, notification intent is inserted in PostgreSQL in the **same
transaction as the terminal task result**. The worker attempts it after commit;
the existing scheduler retries outstanding delivery independently. A non-`none`
policy authorizes up to three attempts of the same status-only message. Delays
after failures are 60 and 300 seconds; `sending` claims expire after 120 seconds,
above the provider timeout cap of 60 seconds. Claims are row-locked and fenced
by a UUID. Attempts and safe outcomes are retained in `notification_deliveries`
and mirrored in `execution_metadata.notification`. Exhaustion stops retries and
is visible as `delivery_status=exhausted`. Uncertain tasks follow failure policy
and explicitly say their outcome is uncertain in the push. No prompts, private
notes, priorities, recommendations, results, or error details are sent.

Provider failure never changes a completed result or reruns model work. A crash
after provider acceptance but before audit commit can duplicate a push; an
expired claim records its prior outcome as `unknown` before retry. At most three
claims are allowed, including interrupted claims. There is no claim of exactly
once delivery or guaranteed device receipt. Existing non-check-in notifications
retain their prior best-effort behavior. Pending delivery is retained even if
the scheduler or Redis is unavailable; no Redis queue is needed for push retry.
Migration `0008` does not backfill intents for already completed historical tasks.

## Isolated verification

Never run the cleanup fixture or smoke harness against the normal stack. The
generator creates a fresh internal network, separate volumes/image, no published
ports, empty provider credentials and disabled paid gates. The optional stubs
exist only in the generated verification commands; production has no stub flag.
Choose fresh names/paths; the generator refuses manifest overwrite.

```bash
python3 evaluations/check_in/isolated_compose.py \
  --project pd-eval-scheduling-20261023 \
  --output /tmp/pd-eval-scheduling-stub-20261023.json --stub-check-in-providers
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json build test
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json run --rm test
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json up -d --no-build --wait api worker scheduler
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json exec -T api alembic current
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json exec -T api alembic check
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json exec -T api python -m tests.scheduled_lifecycle_smoke
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json logs --no-color --tail=100 api worker scheduler migrate postgres redis
```

The smoke harness requires an empty synthetic application database and the
generated stub manifest. It enables only its synthetic interval, completes one
task, pauses that interval, and verifies a failed push retries successfully with
one model call. It advances only that push's persisted retry deadline to shorten
the test. Unit/integration tests additionally control scheduler time for downtime
and DST, contend scheduler/delivery/project locks, enforce occurrence uniqueness,
and simulate late model completion and expired notification claims. The real HTTP/forked RQ test
also runs an independent scheduler process with stub providers.

Only after inspecting evidence, remove this disposable project's resources:

```bash
docker compose -p pd-eval-scheduling-20261023 -f /tmp/pd-eval-scheduling-stub-20261023.json down --volumes
```

No live model quality, real push delivery, host power loss, database connection
partition, backup restoration, or remote security is established by these tests.
The project lock relies on PostgreSQL connection ownership and cannot guarantee
provider-side exclusivity after a lost connection while a remote request is
still executing. Exactly-once paid work is not claimed. There is no general
append-only task-attempt ledger, authentication, or generic approval-resume fix.
