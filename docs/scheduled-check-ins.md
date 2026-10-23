# Persistent project check-ins

The existing dedicated `personal_dot.scheduler` process materializes check-ins
from PostgreSQL schedules. No live schedule is installed or enabled by this
milestone. Creating a check-in schedule defaults to `enabled=false`; explicitly
requesting `enabled=true` at creation is rejected. A separate PATCH is required.
Enabling authorizes the configured recurring, potentially paid, tool-free model
requests and the selected status-only notification policy. Keep the API local.

## Operator commands

Run from the repository root. First build and migrate using the intended
deployment's environment, then start the existing processes:

```bash
docker compose build api worker scheduler migrate
docker compose run --rm migrate
docker compose up -d api worker scheduler
```

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
