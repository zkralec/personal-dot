# Daily documentation maintenance

One account-wide daily job uses the existing dedicated scheduler, PostgreSQL
records, worker claim UUIDs, bounded GitHub inspection, independent editor/reviewer,
publishing controller and notification outbox. Redis transports tasks; it does
not own budgets, repository rotation, approvals or publishing outcomes.

## Initial authorized configuration

The owner approved one run at **09:00 America/New_York**, **$0.25 per local day**,
and one **$0.25 pilot**. Both limits apply to the same daily ledger when the
pilot occurs on that local date; the pilot is not a second spending allowance.
All personally owned repositories accessible to the configured GitHub App are
the pool, with **no extra operator exclusions**. Repository access remains
account-wide. At most one repository is assessed with paid models per local day,
with at most one merged improvement per run and local day.

Each assessment permits at most two model-call intents: one editor and one fresh
reviewer, each at most 65,536 serialized input bytes, 2,048 output tokens, 60
seconds, zero SDK retries, no tools and `store=false`. The current configured
model for both roles is `gpt-6-luna`; an independent invocation/context is required.
One existing documentation file is selected per assessment. The original insertion
policy allows at most 300 added lines and can be tightened through existing
settings. Correction attempts are zero. A daily commit is never required.

Activation requires a successful real pilot under the exact configuration and
reviewed implementation: completed editor/reviewer calls with provider identifiers,
usage and configured models, approved deterministic candidate, verified merge,
and the expected GitHub account association for the supplied author. A synthetic
boolean, fixture result, missing reviewer, rejected/no-op preview, or untested
publisher does not satisfy this gate. A successful pilot is observed after the
parent task commits its terminal result. Configuration or implementation drift
invalidates the gate.

## Pool, fairness and paid-work suppression

At run start, discovery refreshes when the previous discovery is at least 24
hours old, through a normal `github_discover` child task.
It retains every granted personal repository and its classification. Removed
access marks a row unavailable; it does not delete history. Initial historical
coverage was 22 repositories; inspect the current discovery record for the live
count. The implementation bounds the pool to 1,000 and inspects at most 32
repositories per run. Larger/incomplete discovery records an actionable blocker.

Rows are considered in least-recently-checked order, with unvisited repositories
first and repository ID as a deterministic tie-breaker. This prevents a busy or
blocked repository from monopolizing selection. Paid work stops after one
assessment; routine no-op and blocked repositories allow the search to continue.
Existing publication jobs are reconciled before generating new candidates for
that repository. A completed merge stops the run immediately.

Discovery eligibility is separate from publishing readiness. Before scheduled
paid analysis, DOT inspects current repository identity, base and temporary-branch
rules, legacy protection where accessible, and supported merge methods. A blocked
target gets an actionable persisted reason while other repositories remain
eligible. Administration read is requested only for protected-branch inspection;
missing access blocks that target. DOT never modifies repository rules or requests
Administration write. See the [publishing requirements](documentation-publishing.md).

Documented exclusions are archived/disabled/unsupported/empty repositories,
operator exclusions (currently none), and private model sharing under the existing
public-snapshot policy. Private repositories remain in the account-wide pool;
they are marked blocked for model sharing, not silently omitted from discovery.
Mixed/protected/executable documentation, unavailable bounded targets/evidence,
and unsupported repository merge requirements cannot enter automatic publication.

A relevant-input fingerprint includes selected eligible documentation/source
hashes, policy, models and preview implementation. Unchanged repositories with
an existing assessment are not repeatedly paid-analyzed. No-useful-change or
insufficient-evidence outcomes may be reassessed after seven days, or sooner when
relevant inputs change. Rejected, invalid, interrupted or already-addressed input
fingerprints remain suppressed until relevant inputs/policy change. An approved
candidate can be reused for publication without regenerating it, provided the
existing publisher still validates its original base and review. DOT's own merged
documentation bytes are recorded as addressed to prevent self-triggered analysis.

A first visit or relevant input change is a reason to assess, not proof of a gap.
Deterministic selection chooses a bounded existing document and up to three source
excerpts. The owner authorizes this deterministic public-input selection; the sharing
acknowledgment records programmatic policy/hash review, not a claim that a human
read every selected file. The editor must identify a substantive evidence-supported gap or return
an honest no-op. This is bounded evidence coverage, not exhaustive understanding
of every repository or guarantee that every gap is detected. It does not inspect
private sources with a model, run repository code, or open arbitrary issues.

## Budget and publication reservations

PostgreSQL reserves the maximum configured assessment estimate before either
model invocation. At the initial limits this is **19,456 micro-USD ($0.019456)**,
using an input-byte/token upper bound plus a 4,096-token framing allowance, a
conservative input/cache-write rate and the output cap for both calls. A local-day
row allows only one paid assessment owner and two call intents. Separate durable
merge ownership permits one merge owner that local day. Overlaps and retries
cannot allocate another assessment or duplicate its paid calls.

The reviewed pricing profile supports `gpt-6-luna` Standard/default processing:
$0.10 per million input tokens, $0.50 output, and $0.125 for the conservative
input reservation. The [official model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
was checked on 2026-10-30. Requests explicitly choose `service_tier=default`.
The profile expires **2026-11-06 00:00 UTC**; paid work then blocks pending price
revalidation and deployment of a reviewed profile. It never silently prices a
different model. This limited validity covers the initial observation period.

`reserved_microusd` is a conservative admission estimate, retained after uncertain
requests rather than refunded speculatively. `estimated_standard_cost_usd` uses
recorded input/output usage at uncached Standard rates, ignoring potential cache
discounts. Neither is an actual invoice or provider billing record. No billing
API/admin credential was added. Price drift, token-accounting changes and taxes
are not independently guaranteed by local estimates. Provider usage is persisted
in each original preview call. If a call would cross its reservation's New York
calendar date, the next call stops; the job is not regenerated after midnight.

Each external paid or publication step checks the current child and parent
execution claims and operator configuration. Publication merge intent reserves
its daily slot before the remote request. The existing expected-head SHA,
exact-tree checks, durable operation journal and ambiguous-outcome reconciliation
remain binding. At most one unfinished publication exists per repository. A
blocked PR is retained for reconciliation and never force-pushed or duplicated.

## Inspect, pause, resume and disable

All commands target the existing loopback-only API. These controls expose private
repository metadata; protect the host/API/database and do not publish responses.

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/maintenance
curl --fail-with-body -sS http://127.0.0.1:8000/maintenance/repositories
curl --fail-with-body -sS http://127.0.0.1:8000/maintenance/budgets
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/TASK_ID
curl --fail-with-body -sS http://127.0.0.1:8000/schedules/SCHEDULE_ID/tasks

curl --fail-with-body -sS -X PATCH http://127.0.0.1:8000/maintenance \
  -H 'Content-Type: application/json' -d '{"action":"pause"}'
curl --fail-with-body -sS -X PATCH http://127.0.0.1:8000/maintenance \
  -H 'Content-Type: application/json' -d '{"action":"resume"}'
curl --fail-with-body -sS -X PATCH http://127.0.0.1:8000/maintenance \
  -H 'Content-Type: application/json' -d '{"action":"disable"}'
```

Pause and disable both turn off future materialization and stop subsequent paid
or publication steps of already-running maintenance, including a pilot. They do
not undo a committed GitHub write or cancel a provider request already accepted.
An in-flight guarded request finishes before the pause can commit; the API may
wait for that bounded request. A persisted pause generation prevents old work
from resuming external writes even after a quick resume. Read-only observation
and durable outcome/audit recording remain allowed. Existing branches/PRs remain
for reconciliation. No model call is automatically retried after interruption.

Resume requires the matching successful live pilot and current gates/pricing,
and schedules only the next future 09:00 occurrence. It does not replay the
paused gap or resume an interrupted model invocation. After downtime, overdue
occurrences coalesce into one task, then advance directly to the next future
wall-clock run. DST spring gaps are skipped and an ambiguous fall time runs only
once; the configured 09:00 time exists on both transitions. Other schedules retain
their existing state. Generic schedule endpoints cannot bypass maintenance's
activation gate or create another maintenance schedule.

## Configure or inspect the one-off pilot

Configuration is explicit and persisted in PostgreSQL. PUT is refused while a
maintenance task is queued/running; changing configuration pauses recurrence and
invalidates a mismatched pilot. Use the same owner-approved limits:

```bash
curl --fail-with-body -sS -X PUT http://127.0.0.1:8000/maintenance/configuration \
  -H 'Content-Type: application/json' -d '{
    "daily_time":"09:00","timezone":"America/New_York",
    "daily_budget_microusd":250000,"max_input_bytes_per_call":65536,
    "max_output_tokens_per_call":2048,"exclusions":[],
    "discovery_hours":24,"reassessment_days":7
  }'
```

`DOCS_MAINTENANCE_LIVE_ENABLED`, `DOCS_PREVIEW_LIVE_ENABLED` and the worker's
`DOCS_PUBLISH_LIVE_ENABLED` are default-off operator gates. Enable them only for
this authorized workflow, preserving worker-only key mounting and non-root UID.
The explicit one-off pilot task is:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"type":"documentation_maintenance","payload":{"pilot":true},"notification_policy":"always"}'
```

Submit once and save the ID. Do not repeat a POST after losing a response; inspect
`/tasks` and the existing task. The pilot may exercise real generation/review on
one otherwise valid public target even if publication access is blocked, solely
for the explicitly authorized paid test. Scheduled runs never pay on such a target.
That limited test cannot unlock recurrence without a verified merge/association.
A genuine rejection or no worthwhile change is recorded without regeneration.

## Notifications and limitations

One result-driven outbox intent sends a fixed, source-free status for a merged
improvement, a new actionable blocker/rejection/failure, or exhausted budget.
Notification titles and bodies both use the maintenance/publication outcome;
the task's infrastructure `succeeded` status does not imply an approved edit or
merge. Inspect the linked task's preview validation codes for a rejection reason.
Known unchanged repository blockers and routine no-op/no-evidence results remain
quiet. Up to three independent delivery attempts cannot rerun generation or
publication. Provider acceptance does not establish phone receipt.

No distributed exactly-once guarantee, billing reconciliation, private model
sharing, exhaustive source analysis, automated PR abandonment, arbitrary review
fulfilment, or deployment detection was added. The GitHub API head/base/rule and
branch-deletion race limitations in the publishing guide still apply. A merge
is distinct from deployment; DOT does not deploy maintained repositories.

## Continue an existing approved candidate without another paid test

A live pilot exposed that GitHub omits merge-method fields from read-scoped
installation-token responses. Readiness now obtains already-granted publication
scopes solely to retrieve those settings when needed. This preview client still
rejects every repository mutation; it never changes settings or grants. Explicit
`allow_merge_commit=false` remains a blocker. Missing/unreadable protection stays
a blocker. The same capability read is used by the existing publisher preview.

After a known publishing/preflight interruption, use the exact original approved
preview ID to request continuation through the same maintenance controller:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"type":"documentation_maintenance","payload":{"pilot":true,"resume_preview_task_id":"ORIGINAL_PREVIEW_TASK_ID"},"notification_policy":"always"}'
```

This creates a new delivery/continuation task, validates that the target remains
in the configured pool and reuses the original candidate/review without any model
request. Its publisher still rechecks source, base, policy, checks and expected
head and reconciles any known remote outcome. Existing daily merge reservations
remain binding; an ambiguous reserved merge can block another attempt for that
local day. Usage shown on the continuation references the original preview; it
is not a second model charge. Never regenerate merely to get a successful pilot.

A second live API edge case returned `merged=true` with a null PR
`merge_commit_sha`. Finalization now uses the durably recorded merge response,
then verifies both expected parents and the complete tree before cleanup. If the
receipt was also lost, the current base identifies the merge only when its exact
parents/tree match; otherwise owner reconciliation is required. An observed
completed merge can be reconciled after a publisher repair only after the full
original object plan is recomputed from the still-valid reviewed source. That
revalidation permits completed-job cleanup, not another merge under old authority.
The original merge authorization and response remain audit evidence.
