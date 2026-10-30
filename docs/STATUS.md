# Personal Dot implementation baseline


## Controlled live documentation pilot preflight — 2026-10-30

**Blocked before task creation. No live maintenance job was started.** The owner
authorized one real editor/reviewer/publication job, conditional on an explicitly
configured pilot repository and live-test budget. Neither was found in the local
`.env`, deployed worker environment, host pilot/budget environment settings, or
pilot/budget-named files under the existing Personal Dot configuration/data
locations. Historical examples and application defaults were not treated as a
new repository selection or spending authorization.

The previously verified implementation was committed and pushed first, as
requested: `d43c59816b8e3007f4b6cda897db61acf48cb7a9` on `origin/main` at
`https://github.com/zkralec/personal-dot`. The earlier checkpoint `654c859` was
included in that normal, non-force push. Both author and committer of this
implementation commit are Zachary Kralec
`157630586+zkralec@users.noreply.github.com`, using a per-command override. The
existing checkout's Git email is different; its local/global configuration was
preserved. This operator-requested implementation push is **not** a DOT-generated
documentation candidate, pilot branch, PR or merge.

### Observed configuration and deployment

- Pilot repository and pilot task identifier: **none configured / none created**.
  No target was chosen from examples, the checkout or GitHub discovery.
- Deployed API schema: `0011 (head)` in the old image. The worker has no
  `personal_dot.documentation_publish` module or publication/author settings.
  Deployment of schema `0012` and matching API/worker/scheduler is required.
  No production build, stop, migration or recreation was performed in this
  blocked preflight; the established backup/restore procedure remains required.
- Runtime `OPENAI_MODEL=gpt-6-luna`; editor/reviewer overrides are blank, so both
  effective roles use that configured model in independent invocations. No
  model substitution was made. The paid preview gate is false.
- Deployed output defaults are 4,096 globally and 2,048 for previews; neither is
  an explicitly approved live-test budget. No per-call input/output budget or
  overall pilot spend limit was supplied. No budget was inferred.
- The publisher's reviewed identity is Zachary Kralec with the exact account-linked
  noreply email above. Its settings are not available in the old deployed worker.
  Explicit worker configuration is shown below for deployment.
- Provider credentials were checked only for presence; model and notification
  credentials are present. No secret values were printed, changed or copied.
  Worker remains non-root UID 1000.
- PostgreSQL has ten existing tasks, zero queued/running/approval-wait tasks,
  two schedules, **zero enabled schedules**, and zero pending/sending notification
  deliveries. No new task or delivery record was created by this preflight.

### Outcome and unperformed verification

No repository-content inspection, documentation improvement, supporting evidence
selection, editor/reviewer request, candidate, deterministic candidate validation,
PR, publication commit, merge or deployment resulted from this pilot. Reviewer
outcome is **not invoked**, rather than rejection or approval. There are no pilot
PR/commit/merge links or GitHub author-association observations to report.

Zero pilot model requests were initiated; there is no new provider usage record,
model-cost estimate or actual billing observation for this pilot. Notification
credentials are present, but no notification was sent: the required publication
workflow is not deployed and there is no persisted maintenance task whose blocked
status its existing notification outbox can deliver. No synthetic task, test push
or manually constructed publication was substituted. Provider acceptance and
phone receipt are therefore both **unverified / not attempted**.

### Precise local configuration needed before resuming

Keep secrets in the existing ignored `.env` (mode `0600`) and keep all live gates
off until deployment/preflight is complete. Create an owner-only operator worksheet
at `/home/zkralec/.config/personal-dot/documentation-pilot.json` with the following
structure, replacing every placeholder with an explicit owner choice:

```json
{
  "repository": "EXPLICITLY_SELECTED_REPOSITORY_NAME_UNDER_CONFIGURED_OWNER",
  "budget": {
    "max_input_bytes_per_call": "APPROVED_INTEGER_1024_THROUGH_65536",
    "max_output_tokens_per_call": "APPROVED_INTEGER_128_THROUGH_4096"
  },
  "max_model_calls": 2,
  "max_estimated_cost_usd": "OWNER_CHOSEN_CAP_IF_A_DOLLAR_CAP_IS_REQUIRED"
}
```

The worksheet is operator input for this one job, not a new automatically consumed
application setting. The budget fields must be JSON integers when completed.
The workflow permits at most one editor and one reviewer call, zero SDK retries
and at most 60 seconds per call; the effective output cap is the smaller of the
approved request, preview and global caps. Input bytes/tokens are bounded, but
this implementation does not enforce an exact USD ceiling. If a dollar cap is
required, evaluate the selected model and explicit limits before submitting.
Do not populate the worksheet with repository source or credentials. Keep it and
its parent owner-only (`0600` file, `0700` directory).

For the new worker, configure the existing supported identity/model settings in
ignored `.env`, preserving the existing provider keys and GitHub installation:

```dotenv
GITHUB_COMMIT_AUTHOR_NAME=Zachary Kralec
GITHUB_COMMIT_AUTHOR_EMAIL=157630586+zkralec@users.noreply.github.com
DOCS_PREVIEW_EDITOR_MODEL=gpt-6-luna
DOCS_PREVIEW_REVIEWER_MODEL=gpt-6-luna
DOCS_PREVIEW_LIVE_ENABLED=false
DOCS_PUBLISH_LIVE_ENABLED=false
```

Then follow the [publishing runbook](documentation-publishing.md#commands-for-preview-and-one-later-live-maintenance-job):
quiet-window backup/isolated restore and migration rehearsal; deploy `0012` with
matching images and the preserved worker-only key mount; verify schedules remain
disabled, identity, App permissions and the selected repository's actual merge
requirements. Grant no extra repository-rule bypass. Once those checks and the
explicit input/budget selection are complete, use the existing two live gates for
only the already-authorized job, with real configured model calls. If review,
policy, budget or repository requirements block it, record that outcome without
regeneration or a manufactured edit. The later merged content and author
association must be verified independently of any subsequent deployment.

## Bounded automatic documentation publishing — 2026-10-30

**Implemented and verified with simulated GitHub, at new schema `0012`.
Production remains at its previous deployment; this milestone did not migrate or
recreate production, make live GitHub writes, call paid models, send real
notifications, or enable any schedule. Both publishing gates default off.**
This supersedes earlier statements below that no publisher exists. Earlier live
read-only inspection evidence does not establish publishing readiness/access.

### Checkpoint and independent implementation findings

Created clean-tree checkpoint `654c8597d485513ead2c6f49a14457106d0d8f49`, with
both author and committer **Zachary Kralec
<157630586+zkralec@users.noreply.github.com>**, before implementation. Read the
instructions, policy, status, implementation and regressions directly; historical
deployment claims were not treated as new live verification.

The previously requested ownership and delayed approval-resume repairs are
present: fresh claim UUID/start time, claim revocation, fenced completion/failure/
pause, continuation preservation and removal of stale approval-wait metadata.
Their existing 21 focused cases (19 execution-reliability and two manual late
check-in cases) passed again. Those completion guards alone were insufficient
for publication: an obsolete handler could otherwise issue another remote write.
The publisher now commits intent, then holds the current task-claim row lock
through source revalidation, remote reconciliation, write and outcome recording.
A dedicated regression proves recovery skips a locked in-flight write and a
revoked execution cannot begin its next write.

The new concurrency probe also exposed and fixed a publisher lock-order blocker:
a duplicate initially waited for the review-source row before checking the
repository lock. Repository locking now precedes review-source locking, so an
overlap returns promptly. Added explicit checks that result repository/base/input/
policy fields still match their prepared source; current preview sealing alone
did not bind every copied display field. Added a final expected-ref check before
opening the PR. Three legacy manual transport regressions still expected the
inner provider failure to escape the already-sanitized job boundary; corrected
the assertions and verified persisted uncertainty, diagnostic and no retry.

### Implemented boundary and audit

One manual `documentation_publish` task consumes an existing independently
approved candidate, with no generation/review loop or model access. It rechecks
the original snapshot, deterministic insertion policy and review binding. New
migration `0012` adds only this task type and a durable publication table keyed
by preview, including a unique unfinished-repository constraint. No dependency
or schedule type was added.

Content-addressed Git blobs/trees/commit preserve exact reviewed insertions and
unrelated base entries. Ancestor trees and object-plan bytes are bounded. Only a
new job-specific DOT ref is created; no force push/update-ref exists. The
controller opens/reconciles one PR, verifies files, sole commit, complete tree and
head/base identities, binds authorization to repository/base/candidate/head/
review/checks/requirements/policy/implementation, and sends GitHub's expected-head
SHA when merging. Checks/mergeability are polled within a bounded worker window;
qualifying changes merge automatically without a manual approval step.

Discovery eligibility is insufficient. Each target's active base/temporary rules
and legacy protection are inspected and recorded. Unknown, unreadable or
unsupported requirements block. Required GitHub approving/code-owner reviews
are blockers in this initial subset: DOT's model reviewer is policy evidence,
not a GitHub approval. Required checks include exact-head and App-provider
identity. No rules/settings/review/status mutation or protection bypass path is
implemented. GitHub changes-requested reviews also block merging.

Durable intents and deterministic identities reconcile lost responses and
post-acceptance DB rollback before retrying branches, objects, PRs, merges or
cleanup. Same-preview delivery tasks reuse the same job; repository locking and
the database constraint prevent overlapping jobs. Stale publication tasks become
uncertain, with no automatic execution retry. Read-only reconciliation can record
a merge accepted before authorization changed. A verified merge is durable before
cleanup; only the job's unchanged temporary branch is removed. Blocked jobs keep
the repository slot pending reconciliation.

Candidate author **and committer** use the exact supplied name/email; mismatched
trusted configuration blocks. Independent Git `hash-object` evidence verifies
serialization. Only merge commits are selected, retaining the original attributed
candidate commit as a parent; GitHub creates an additional integration-authored
merge commit. Squash/rebase-only targets block. The candidate's name/email and
merge parents/tree are verified after acceptance. Account-linked rendering on
real GitHub remains for the live pilot.

`published`, `merged` and `deployed` are separate; deployment remains false.
Existing notification outbox/service delivers fixed concise statuses, with
independent bounded retries. Provider failure cannot change the result or repeat
model/publication work. Inspection still mints Contents/Metadata read tokens;
publication tokens are separately repository scoped and stay outside model
context. Worker-only read-only key mount/non-root execution are preserved; the
existing worker metadata still shows UID/GID `1000:1000` and a read-only key mount.
No runtime secret or populated local configuration was modified. All 38 installed
Python modules in the final image match the checkout byte-for-byte.

### Verification evidence

The final application image (`dc5f5af9b6b7`, non-root `app`) passed **347 tests, 1 skipped** in 73.56 seconds,
plus **12 manual-only recovery/notification/process cases** in 7.32 seconds:
**359 passed total**. The 64 new publication cases include independent-review
rejection, local binding drift, exact multi-file/nested trees, changed remote
diff/head/base, pending/failed/missing/wrong-provider checks, automatic merge when
checks finish, GitHub review/protection blockers, concurrent/duplicate attempts,
stale ownership, before/after-acceptance timeouts at every write stage,
post-acceptance DB rollback, merge-base races, changed cleanup refs, notification
failure and authorization invalidation after a lost merge response. A real HTTP
API plus forked non-root RQ worker completes the workflow using authored model
stubs, an ephemeral synthetic App key and an HTTPX simulated GitHub service.

Used disposable project `pd-eval-publishing-20261030`: internal Docker network,
no published ports, tmpfs PostgreSQL/Redis, blank provider credentials, default-off
live gates, no production key mount, and no source mounts in final-image runs.
Fresh `0001 -> 0012` migrations, `0012 -> 0011 -> 0012` round trip,
`alembic check` and `pip check` passed. Paid integration remained skipped; five
existing RQ deprecation warnings remain. Schedule-enabling cases were excluded,
including from isolation. Process/service logs were inspected. The standalone harness initially omitted
`pg_isready`'s database argument, producing missing-default-database probe logs;
the correct test database probe passed and the harness command was corrected.
Redis reported the host's existing overcommit warning; no host settings were
changed. Disposable resources were removed after verification. Local evidence is under `/tmp` in
`pd-publishing-*.log` and `pd-publishing-process-evidence/`, not durable backup.

### Limits and live-pilot readiness

Ready for an owner-authorized, quiet-window live pilot after deployment and App
permission preflight, **not live verified or deployed by this delivery**. The
previously recorded read-only installation does not have established publication
permissions. Owner-granted Contents/Pull requests write and Administration/Checks/
Commit statuses/Metadata read are needed; DOT does not change App grants or
repository rules. No real target's current merge requirements were fetched here.
They must pass the read-only publishing preview before a live job.

The supported subset excludes required GitHub approving reviews, signing, linear
history, restricted pushes, conversation resolution, deployment/workflow/code
scanning rules, merge queues and unknown rules. Pending checks beyond the bounded
window need an explicit same-job reconciliation task. No automatic abandonment,
PR closure or repository-slot release for blocked work is implemented.

GitHub's REST merge API protects the expected head, but supplies no atomic
expected-base/rule/check-snapshot condition. The controller rechecks immediately
before writing and verifies merge parents/tree afterward; a remote race is
recorded as merged with an owner-reconciliation blocker and retained branch.
Ref deletion likewise lacks atomic compare-and-delete; an external actor updating
the ref between read and delete cannot be excluded. This does not establish
host-crash/distributed exactly-once behavior, live CI, live App attribution,
model quality or deployment. Use a quiet repository/window for the first pilot.

[Exact preview and one-live-job commands, permissions, supported rules and recovery
procedure](documentation-publishing.md) are documented. No live pilot was started.

## Bounded documentation editor and independent reviewer — 2026-10-29

**Implemented, synthetically verified and deployed at schema `0011`. Live GitHub
file retrieval is now verified. No paid editor/reviewer call or candidate
publication occurred; both real schedules and paid preview gates remain off.**
This supersedes the earlier unexercised-inspection and unavailable-preview
statements below. Model quality and live preview behavior remain unmeasured.

### Checkpoint and required live inspection first

Saved the previous GitHub implementation as local checkpoint `b6d46db`, preserving
older unrelated documentation edits. No push preceded the live check. Submitted
`github_inspect` for `personal-dot` through the existing `POST /tasks` interface:
task `6d3702e5-c12e-47bf-9725-78a14731016f` succeeded at immutable commit
`a7e9366afcbde3c18ef602548b59ef680cbc1953`, root tree
`ee0831ee2a16a8ecdf69959cd52a7aa7e2c964d2`. It downloaded 40 bounded blobs and
selected 38 text files, totaling 250,358 selected-context bytes under 262,144.
Inventory completed; file-count, file-size, total-context, sensitive-content,
secret-path, agent-instruction, generated/hidden and unsupported-extension
exclusions were recorded. This was real read-only GitHub retrieval, not a fixture.

All selected text lengths, Git blob hashes and SHA-256 values checked locally.
README (16,110 bytes), architecture (22,113) and jobs source (13,972) also matched
`git show`/Git blob identity for that exact revision byte-for-byte; the root tree
matched the commit object. No scripts/hooks/builds or repository instructions
were executed. No concrete inspection blocker needed repair; authentication,
discovery and inspection implementation were reused unchanged.

### Preview task, policy and persisted review

New manual `documentation_preview` uses existing task/result, RQ, PostgreSQL and
execution UUID conventions. Migration `0011` adds only its task-type constraint
value, with no dependency, table or publisher. It accepts a completed inspection
ID/base commit, explicit target paths/full-file hashes and evidence paths/hashes/
line ranges, a reviewed-input sharing acknowledgment, and a per-call byte/token
budget. Public, maintenance-eligible snapshots of the configured personal owner
are the initial supported sharing boundary; private inspection remains available.

Policy `documentation-preview-v1` allows explanatory insertions into selected
existing README/docs Markdown only, at most three files and 300 added lines,
configurable downward. Existing bytes/headings remain unchanged. Protected
instructions/security/authorization/policy, code/configuration/dependencies,
workflows, deployment/operations files/sections and executable-document content
are denied. New commands, code blocks, links/HTML, headings, configuration and
successful-check/maturity/authority claims fail deterministic checks. Every
insertion needs existing selected evidence IDs and exact support quotes. Those
checks establish identity and quote presence, not semantic truth.

Input selection, public-only sharing, explicit acknowledgment, path/mode/hash
validation and byte/line caps are mandatory in addition to secret screening.
Secrets/control characters are screened after model JSON decoding as well as in
raw output. No implicit files/memories, scripts, instructions or generated
commands execute. Models receive no credentials, tools or publishing access.

Exactly one editor pass identifies a concrete gap and proposes a candidate. A
separate service instance invokes one reviewer with fresh instructions, original
selected targets/evidence and the exact generated diff, without editor rationale,
conversation or continuation state. There is no correction loop. Model approval
cannot override application policy. Review binds repository, base commit,
selected input/evidence identity, candidate/diff hash, policy/implementation,
SDK/model configuration and outcome. Final task commit rechecks those identities
and deterministic policy under task/source locks; any relevant drift invalidates
approval. `approved_candidate` remains a preview outcome, never publishing permission.

Fenced checkpoints retain call intent and editor candidate/validation/usage before
review. Results retain gap, candidate, exact diff, evidence references, checks,
review decision/findings, requested and returned model/configuration identities,
prompt/input/output hashes, request/response IDs and available per-call usage.
Semantic outcomes (`approved_candidate`, `changes_requested`, `no_useful_change`,
`insufficient_evidence`, `invalid_candidate`) are separate from infrastructure
status. Provider/configuration failures retain safe partial results with
`outcome=null`. Timeout/stale interruption becomes terminal `uncertain` without
automatic model re-execution; obsolete workers cannot checkpoint or complete it.

Paid generation requires both the default-off operator gate and explicit boolean
per-task permission/budget. Models use `store=false`, no tools, zero SDK retries,
at most two calls, at most 60 seconds each, and the smaller configured/requested/
global output cap (default 2,048 per call). Calls are byte/token bounded; this is
not a guaranteed USD spending cap. Actual usage/cost and output quality need a
separately approved live preview.

### Synthetic and deployed verification

The exact final image passed **286 tests, 1 skipped** in 38.39 seconds, including
60 new preview cases. Covered supported improvements, unsupported claims,
malicious source instructions, forbidden paths/sections/commands, invalid IDs/
quotes, reviewer rejection/contracts, no-op/insufficient work, limits, explicit
sharing/permission fields, decoded secrets, candidate/source/owner/policy/outcome
changes, partial checkpoints/usage, model timeouts, late completion and disabled
paid gates. A real HTTP/forked-RQ process case completed both authored stub model
passes. These fixtures prove contracts, not model quality or injection robustness.
Existing GitHub, execution reliability, task, agent, check-in/evaluation, memory,
tool, notification, diagnostic and manual recovery suites passed. The paid
integration was skipped; five existing RQ deprecation warnings remain.

Verification used fresh internal-network project `pd-eval-docs-20261029`, no
published ports, tmpfs data, blank provider credentials and paid gates off. Final
verification had no source mounts. No schedule-enabling cases were run. Its
service/process evidence was inspected and disposable resources removed.

The exact documented real snapshot selection also passed read-only preparation.
After deployment, API task `aa11c0f9-45b1-4810-b59c-266993e0488c` accepted that request
with paid permission false and stopped at the disabled operator gate: failed task,
`outcome=null`, no candidate and **zero model calls**. This is live API/gate evidence,
not live generation. Three fixed expected gate-failure log records were retained;
no provider bodies or input contents entered logs.

### Deployment, data preservation and remaining limits

Followed idle/target preflight, build, application-only stop, protected backup,
network-isolated tmpfs restore pinned to the running PostgreSQL image, complete
count/data-fingerprint/schema comparisons, and rehearsal of `0010 -> 0011` before
the real migration. Only the expected task-type constraint changed; idempotent
migration and application-only recreation preserved PostgreSQL/Redis containers,
images and volumes. The existing equivalent array-cast representation is narrowly
normalized during restore comparison. Installed Python sources match the checkout.

Protected archive/checksum, local configuration, restore/rehearsal/schema/data
fingerprints, source/image/mount identities, logs, final tests, live inspection/
revision checks, gate-check requests/results and operator helpers (directory
`0700`, files `0600`) remain outside Git:

```text
/home/zkralec/.local/share/personal-dot/backups/docs-preview-20261029T022019Z/
```

Backup is local, not encrypted/off-host; ownership/ACL application and global
roles are excluded from restore, so this is not full disaster recovery. API image
prefix `8b4c1da95a89`, worker `5f13d153fe3f`, scheduler `2572538edc7f`. Schema is
`0011 (head)`; `alembic check`, `pip check` and `/health` pass. The key remains
read-only only in non-root worker UID 1000; API receives only the public owner
setting needed to bind preview scope. Both paid gates remain false. No model,
notification or schedule-materialization activity appears in deployed logs.

Ten terminal tasks now include the authorized live inspection and disabled-gate
preview test. All nine pre-deployment tasks and all other existing records are
preserved. Both schedules remain disabled; active queue registries, execution
claims and notification outbox are empty. Original unrelated edits are preserved.

[Exact task requests, result commands, policy and a later opt-in input/budget
procedure](documentation-preview.md) are documented. This first editor supports
insertions/public snapshots only. No live editor/reviewer quality, actual usage/
cost, exhaustive secret detection or independent model-error behavior is verified.
Same-model review can share errors; valid references are not factual proof.
Private previews, general document rewriting, branch/head freshness enforcement
for publishing, publishing itself, general attempt history, authentication and
host-crash/exactly-once guarantees remain outside scope. No candidate patch was
applied or published, no PR/merge was created, and no schedule was enabled.
## Bounded GitHub discovery and inspection — 2026-10-29

**Implemented and deployed at schema `0010`. Live read-only installation
verification succeeded. Both real schedules remain disabled. No paid model,
real notification, repository-content inspection, branch, commit publication,
PR or merge occurred.** Source is the current working tree based on `a7e9366`;
no new commit or push was made in this milestone. Earlier statements that GitHub
inspection is unavailable are superseded here; publishing remains unavailable.

### Implemented boundary

Two manual task types reuse `POST /tasks`, RQ execution, UUID ownership fencing,
recovery, safe diagnostics and PostgreSQL results: `github_discover` and
`github_inspect`. No new interface framework, repository allowlist or persistence
layer. Migration `0010` only extends `ck_tasks_type`; GitHub tasks are prohibited
from schedules and notifications. Added `PyJWT[crypto]` for the concrete RS256
GitHub App authentication requirement, using existing HTTPX for transport.

Discovery paginates installation repositories, filters by configured personal
owner login and verified account ID, and reports eligibility, fork/archive/
disabled/empty-candidate/unsupported classifications, access coverage and bounded
pagination continuation. All accessible personally owned repositories are
selectable; forks remain eligible when otherwise supported. Archived repositories
are inspectable but ineligible for maintenance. Empty repositories are confirmed
at commit lookup; inaccessible selections persist fixed failure classifications.
Unseen private repositories outside the installation grant cannot be enumerated.

Inspection accepts one repository name under the configured owner and holds a
PostgreSQL advisory lock across collection. It resolves the default branch once,
then reads immutable commit/tree/blob SHAs. Bounded inventories and selected
UTF-8 text record repository identity, commit, paths, Git blob hashes, SHA-256,
limits and explicit exclusions. Blob size and identity are verified. Default
limits: 2,000 entries, 64 tree requests, 40 downloaded blobs (including rejected
contents), 64 KiB/file and 256 KiB selected-files JSON context. README/docs/
manifests precede source. Unsafe paths, symlinks/submodules, credential paths,
agent-instruction files, executable modes, unsupported/binary/generated/vendor
content and detected secrets are excluded. No checkout, script, hook, build,
repository instruction, model, memory write or publishing path runs.

### Configured and verified GitHub authentication

[Exact setup, API requests, bounds and limitations](github-inspection.md) are
recorded in the new operations guide. The existing ignored `.env` now uses
`COMPOSE_FILE=compose.yaml:compose.github.yaml`, owner `zkralec`, App ID `5519145`
and installation `176370838`, preserving prior database/provider settings.

The supplied original key at
`/home/zkralec/.config/personal-dot/secrets/github-app.pem` exists, is a valid
unencrypted RSA PEM of at least 2048 bits and remains unchanged, owner UID/GID
`1000:1000`, mode `0600`, secrets directory `0700`. The previous worker UID `999`
could not read this owner-only file. The optional Compose override runs worker
as non-root `1000:1000` and mounts only this file read-only at
`/run/secrets/github-app.pem`; API/scheduler/migrate/test receive no key mount.
The **actual deployed worker** validated ownership, readability and RSA parsing.
No permission widening, credential replacement or rotation was performed.

Signed App JWTs verify installation/app identity, personal User ownership,
suspension and Contents permission before minting short-lived installation
tokens. Requested token permissions are only contents/metadata read; inspection
tokens are also repository-scoped. Tokens stay in memory and are refreshed before
expiry. Fixed-origin HTTPS rejects redirects, untrusted pagination URLs,
unbounded responses and raw provider diagnostics. Credentials never enter task
inputs/results, URLs, logs or model context. The supplied commit-author identity
is documented for future use; this read-only milestone does not configure it.

Live task `5f5cf357-048d-4239-ac33-ba8acb4ef2d0` completed through the deployed API
and normal worker. GitHub accepted the supplied key for App `5519145` and confirmed
installation `176370838` belongs to personal User `zkralec`, account ID
`157630586`, with `repository_selection=all`. One-page discovery completed with
**22 accessible personally owned repositories, all 22 currently eligible**.
Repository names/private metadata remain in PostgreSQL and protected operator
evidence, not this status document. No live file selection/content download was
needed for the authorized listing verification.

### Verification and deployment evidence

The final reviewed application image passed **226 tests, 1 skipped** in 29.07
seconds. This includes 63 new GitHub fixture/process cases: RSA/JWT signatures,
read-only scopes and expiry refresh, installation mismatch/permissions, key
failures, HTTP/transport/rate/redirect errors, pagination and owner filtering,
classification, immutable hashes, bounds/truncation, unsafe paths, credentials,
binary/generated/vendor content, persistence, duplicate delivery, advisory-lock
overlap and secret-safe API/DB/RQ/log diagnostics. Real HTTP plus forked RQ
processes completed fixture discovery and inspection with an ephemeral test key
and MockTransport. The existing execution-reliability, manual recovery,
agent/check-in/evaluation/notification/tool/memory/diagnostic suites also passed.
The paid integration was skipped; five existing RQ deprecation warnings remain.
No schedule-enabling tests were selected, including in isolation.

Used fresh internal-network project `pd-eval-github-20261029`, no published
ports, tmpfs PostgreSQL/Redis, blank provider credentials and paid gates off.
Inspected service/process evidence and removed only its disposable resources.
No live credentials were mounted into tests.

Followed the existing maintenance procedure: idle/target preflight, build all
application images, stop application processes, recheck quiet controls, protected
backup, fresh network-isolated tmpfs restore pinned to the running PostgreSQL
image, compare all counts/data fingerprints/columns/indexes/validated constraints,
rehearse `0009 -> 0010`, verify only the expected task-type constraint changed,
then upgrade the real database and recreate only application services. Existing
varchar-array/text-array constraint rendering is narrowly normalized for restore
comparison. Original records fingerprint identically after upgrade and startup.

Protected archive/checksum, original local configuration, restore/rehearsal/schema
and data fingerprints, source hashes, container/image/mount identities, test and
live-discovery results, logs and operator helpers (directory `0700`, files `0600`):

```text
/home/zkralec/.local/share/personal-dot/backups/github-20261029T012137Z/
```

Backup is local, not encrypted/off-host; restore excludes ownership/ACL application
and cluster-global roles, so it is not full disaster recovery. API image prefix
`0b5b4b6699f0`, worker `e0297041a76f`, scheduler `0156af687355`; all installed Python
sources match the working tree. PostgreSQL/Redis containers/images/volumes are
unchanged. `alembic current`: `0010 (head)`; schema check has no new operations;
`pip check` is clean; `/health` reports PostgreSQL/Redis OK. Six deployed service
logs show exactly the expected discovery task start/success and safe HTTP request
events, with no errors, model starts, notifications or schedule materializations.
API remains loopback-only.

Eight terminal tasks now include exactly the authorized discovery. All fields of
all seven original tasks and all other pre-existing tables are preserved. Both
schedules remain disabled; queues/claims/outbox are idle and other application
tables remain empty. Unrelated pre-existing documentation edits are preserved.

### Remaining limitations

Ready for an explicitly selected repository inspection through the documented
API. Live authentication/listing is verified; live repository-content collection
has not been exercised. Pagination, malformed data and snapshot safety are proven
with authored fixtures, not every real repository format. Inventory is bounded,
not exhaustive; non-ASCII/unsupported paths and giant responses may be excluded
or fail safely. Secret detection is heuristic and can miss unlabelled secrets or
exclude harmless examples: retained private source text still requires protection.
GitHub pagination is not an account-wide transaction, and access can change.

No publishing, independent-review orchestration, deterministic change-policy
checks, commits/PRs/merges or recurrence were implemented. Generic execution
remains at least once; recovery can resolve a newer head before a final snapshot
commits. Advisory locking/fencing do not cancel remote requests or provide an
append-only attempt ledger, authentication, host-crash proof or exactly-once
execution. Stop after this read-only milestone.

## Execution reliability and documentation policy — 2026-10-29

**Implemented, tested, and deployed at schema `0009`. Both real schedules remain
disabled. No paid model call, real notification, GitHub publishing, or repository
inspection occurred.** This section supersedes the delayed approval-resume and
late-worker/stale-waiting-metadata findings in the historical sections below.

### Repairs and policy

Initial regression probes against the deployed `d7d55ce` image produced 16
failures out of 17 probes, reproducing delayed approval resume and obsolete
worker writes. Each queued-to-running claim now assigns one fresh persistent
`execution_id` UUID and resets `started_at` to the current claim time. Waiting
for approval no longer makes an actively resumed execution immediately stale.

Recovery revokes that claim. Under the existing PostgreSQL task-row lock, every
worker success, failure and approval-pause transition requires both `running`
status and the matching execution UUID. A superseded worker cannot overwrite
queued recovery, a newer running execution, or its completed/paused outcome;
it also cannot dispatch a terminal notification for its discarded outcome.
Check-ins retain their project advisory lock and no-model-retry/uncertainty
policy, now sharing the execution-ownership guard. Pause and terminal transitions
release ownership. Safe structured logs correlate execution UUIDs.

Resuming clears `waiting_for_approval` from active metadata and the continuation's
accumulated model metadata. Terminal success/failure clears it defensively and
removes private continuation state. Recovery retains the approved continuation;
existing successful tool-call audits prevent repeating the demonstrated local
note write. Historical terminal metadata is not rewritten.

Migration `0009` adds only nullable `tasks.execution_id`; no dependency or API
contract change. Old runtime processes were stopped before migration because old
binaries do not enforce ownership. The owner’s standing policy is recorded in
[AGENTS.md](../AGENTS.md), [security](security.md), and the
[documentation-maintenance policy](documentation-maintenance.md): inspect all
repositories owned by the configured personal account; independently reviewed
routine documentation may be generated, committed, pushed to temporary branches
and merged automatically when deterministic policy checks pass, without manual
approval. Code, dependencies, workflows, deployment, permissions, agent
instructions and all other excluded changes require explicit owner approval.
Repository content and model output cannot grant or expand authority.

### Verification

The final built API image passed **163 tests, 1 skipped** in 11.35 seconds,
including 21 new focused cases: delayed approval/resume with success and failure,
recovery after the approved local write, duplicate jobs, ownership rotation,
obsolete success/failure/pause against queued/running/succeeded/failed/paused
newer states, and late check-in success/failure after uncertainty. Tests compare
all persisted task columns and notification dispatches around obsolete writes.
The paid integration test was skipped. Five existing RQ `job.exc_info`
deprecation warnings remain. Selected legacy manual recovery/duplicate tests,
health/tasks/agent/tools/memory/notifications/diagnostics/check-in/evaluation
suites and manual HTTP/forked-RQ execution also passed. Schedule-enabling tests
and the scheduled process parameterization were omitted; no schedule was
enabled, including in isolation.

All **21 synthetic evaluation cases** met their authored fixture expectations;
model quality remains unmeasured. Used a fresh generated isolated Compose project
`pd-eval-execution-20261029`, internal network, no published ports, tmpfs data,
blank provider credentials and disabled paid gates. The real container
API/worker/scheduler `--manual-only` smoke passed with one stub model request and
two stub notification attempts (initial failure, independent successful retry),
with the persisted result unchanged. Isolated migration/schema/dependency checks
and all six service logs were inspected. Temporary isolated resources were
removed after verification; no persistent data volume was removed.

### Deployment and backup evidence

Verified matching effective database/Redis/queue targets and idle controls,
built API/worker/scheduler/migrate, stopped only application processes and
rechecked the quiet window. Created a protected custom-format backup, restored
into fresh tmpfs PostgreSQL pinned to the running database image with no network,
then compared all table counts, ordered data fingerprints, columns, indexes and
validated constraints. The first schema comparison stopped on the documented
equivalent varchar-array/text-array cast rendering; a narrowly scoped comparison
normalization resolved that representation difference. Row fingerprints already
matched. Rehearsed `0008 -> 0009` on the restored database before the real upgrade,
verified the sole new nullable UUID column and unchanged pre-existing data, then
ran the normal migration job twice and recreated only application services.

Protected archive/checksum, original/restored/rehearsed/after fingerprints and
schema catalogs, source hashes, identities, logs, test/corpus/smoke results and
operator helpers are retained outside Git, directory `0700`, files `0600`:

```text
/home/zkralec/.local/share/personal-dot/backups/execution-20261029T003803Z/
```

The backup is local, not encrypted/off-host; restore excludes ownership/ACL
application and cluster-global roles, so this is not full disaster recovery.
Deployed image prefixes: API `0430dcf37815`, worker `fd66beaa5b25`, scheduler
`d2250f5e6e87`. Every installed application Python source matches this milestone's
checkout. PostgreSQL/Redis container/image/volume identities are unchanged.
`alembic current`: `0009 (head)`; `alembic check`: no new operations; `pip check`:
no broken requirements; `/health`: PostgreSQL/Redis OK. All six deployed service
logs contain no errors, task/model starts, notification attempts or schedule
materializations during maintenance. API remains loopback-only.

Seven terminal tasks and two disabled schedules remain; all pre-existing fields,
results and metadata fingerprint identically before/after. All execution owners
are null. Memories, notes, tool calls, approvals and notification deliveries
remain empty; queued/started/deferred/scheduled RQ counts are zero.

### Readiness and remaining limitations

Ready for the next bounded repository-inspection step under the recorded owner
policy. No repository-selection, GitHub publishing, deterministic diff checks,
independent-review orchestration or automatic merge implementation is added.
Those enforcement/audit paths must be built and verified before DOT can publish
automatically. This milestone stops here; schedules stay disabled.

Ownership fences task-state writes; it does not cancel an obsolete handler or
remote request and cannot make arbitrary side effects exactly once. Generic
execution/recovery remains at least once, without a heartbeat, lease renewal or
append-only task-attempt ledger. Check-ins retain one-request/uncertainty bounds.
Hard process death, host power loss and network partitions were not tested in
these new regressions. Authentication, least-privilege DB roles, generic durable
notification delivery, prior-inference freshness and live model/phone quality
remain outside scope. No new external integration or broader model tool exists.

## Citation and diagnostic hardening — 2026-10-29

**Implemented, tested, and deployed. Both real schedules remain disabled. No live
model call, external notification, or private-note selection occurred.** This
section supersedes older citation/diagnostic findings below. The delayed generic
approval-resume defect and stale waiting metadata remain open and unchanged.

### Defects reproduced and changes

Ran four new regression probes against the previously deployed application image
in fresh isolated PostgreSQL/Redis: all four failed, reproducing unknown prose
citation acceptance, arbitrary unexpected-task error disclosure, queue error
logging/reconciliation disclosure, and typed notification error disclosure.

Production now validates explicit `memory:<id>`, `task:<id>`, and
`priority:<project_id>:<position>` references in summary, blocker text, action
description/rationale, and every uncertainty item. Only source IDs from the
accepted input snapshot are allowed; prose IDs must also be in
`supporting_source_ids`. Markdown wrappers do not bypass validation; ordinary
brackets, Markdown and code without namespaced source tokens are unaffected.
The former known-gap corpus case now requires rejection. Evaluation and
production share the recognizer; independent test expectations cover every text
field, three namespaces, wrappers, prior-result selection and ordinary syntax.
Invalid output cannot commit a successful result or dispatch an on-completion
notification; usage and request/response identities survive safe rejection.
Source existence/selection does **not** prove factual support for a claim.

Unexpected task failures, manual/approval enqueue and scheduler reconciliation
use fixed classifications/messages instead of arbitrary exception text or class
names. Agent failure metadata has an explicit field allowlist and numeric usage
fields. API and RQ boundaries catch escaped provider/database/commit errors;
service logs omit exception bodies/chains. Notification API/audits and tool
failure diagnostics use fixed messages. SQLAlchemy parameter hiding remains a
secondary measure. Correlation task/schedule/request/response IDs and operational
events remain available; no schema change, dependency, or approval redesign.

### Verification

The final rebuilt API image, also used for isolated verification, passed
**140 tests, 1 skipped** in 10.96 seconds. The skipped test is the paid OpenAI
integration. Selected suites: health, tasks, agent adapter, notifications, tools,
memories, check-ins, evaluation, diagnostic regressions and the manual HTTP/
forked-RQ process case. Tests that enable schedules were deliberately omitted,
including the scheduled process parameterization. New scheduler diagnostics
coverage uses queued manual work and a disabled synthetic schedule with an
injected materialization error; no schedule was enabled, even in isolation.
Five RQ `job.exc_info` deprecation warnings do not affect these assertions.

Unmistakable synthetic sensitive markers in unexpected/typed agent exceptions,
SQL statements/parameters/server errors, provider exceptions and transport chains
were absent from API responses, persisted errors/audits, RQ failures, applicable
logs and notification content. Commit-failure tests verify safe RQ diagnostics
when the terminal transaction itself cannot persist. All 21 corpus expectations
passed; the compact baseline was regenerated with source/prompt/corpus hashes.
These authored fixtures establish contracts, not real model quality.

Reused `isolated_compose.py --stub-check-in-providers` with fresh project
`pd-eval-harden-20261029`: internal network, no published ports, tmpfs data,
blank provider credentials and both live gates off. The existing container smoke
harness now supports `--manual-only`; that path created no schedules and passed
through the HTTP API, worker and scheduler with exactly one stub model request,
initial stub notification failure and a successful independent second attempt.
The persisted result stayed identical. Inspected all six isolated service logs.
Temporary isolated containers/network were removed after verification.

### Deployment and data preservation

Used the existing maintenance procedure: verify matching effective database/
Redis/queue targets and an idle window; build API/worker/scheduler/migrate;
stop application processes; recheck quiet controls; make a protected backup;
restore into a fresh network-isolated tmpfs PostgreSQL container pinned to the
running database image; compare all table counts/ordered row-data fingerprints;
rehearse `upgrade head`; run the normal idempotent migration job; recreate only
application services. No database/Redis recreation, volume removal, downgrade,
schedule enable, real task creation or provider request occurred.

Protected backup/evidence directory (`0700`, files `0600`, outside Git):

```text
/home/zkralec/.local/share/personal-dot/backups/harden-20261029T001637Z/
```

It contains the custom-format archive/checksum, original/restored/rehearsed/after
fingerprints, source hashes, container/image/volume identities and inspected logs.
Restoration excludes ownership/ACL application and cluster-global roles; this is
not full disaster recovery. The backup is local, not encrypted/off-host.

API image prefix `45991bfc1801`, worker `2f15215aec1b`, scheduler
`5379c83fa2a7`. Installed Python sources in all three match the checkout exactly.
PostgreSQL/Redis container/image/volume identities are unchanged. Schema remains
`0008 (head)`; isolated and deployed `alembic check` report no new operations,
`pip check` reports no broken requirements, and `/health` reports PostgreSQL/
Redis OK. All six deployed logs contain no tracebacks/errors, model starts,
notification attempts or schedule materializations during maintenance.

All table fingerprints are unchanged: seven terminal tasks, two disabled
schedules, no memories/notes/tool calls/approvals/outbox rows. RQ queued/started/
deferred/scheduled counts and pending deliveries are zero. API remains loopback
only. No application migration was added or applied beyond idempotent head.

### Readiness and remaining limits

DOT is technically ready for **one separately authorized controlled live
check-in** using the existing maintenance runbook, explicit project-note IDs,
priorities and an approved budget. No live quality, provider compatibility,
actual usage/cost, phone receipt or duplicate behavior has been established.
The process-local one-push-attempt live procedure remains unverified. Both real
schedules remain disabled; recurrence requires separate authorization.

Citation checks validate recognized identifiers, not semantic support or every
possible alternate citation spelling. Error sanitization is prospective; old
records/logs were not rewritten. If a terminal database transaction fails, safe
RQ diagnostics survive but the task can remain running until stale reconciliation
marks a check-in uncertain or recovers generic work. General attempt history,
authentication, least-privilege DB roles, generic notification outbox, host/crash
recovery guarantees, prior-result freshness policy and the approval-resume
findings remain outside this milestone.

## Deployment and isolated verification — 2026-10-24

**Existing check-in code is now deployed at schema `0008`. No live model request
or notification was made. All real schedules remain disabled.**

Started from clean `main` at `6dfc652ea426361507ee00359e4a252cb6026c83`, after
reading development rules, status, README, architecture/security/operations
documentation, Compose, migrations and verification harnesses. Application code,
dependencies, Compose and migrations were unchanged; this delivery updates only
operations/status documentation.

### Reconfirmed baseline and deployed identities

Before maintenance: database `0006`, no notification outbox, installed
API/worker/scheduler lacking `check_in` and `notification_delivery`. Health was
OK; seven terminal tasks, two disabled generic-agent schedules, and no active
tasks or queued/started/deferred/scheduled RQ work. The previous successful
`notification_test_sent` event at `2026-10-23T19:50:58.332044+00:00` was reconfirmed
without sending a push. Effective Compose database/Redis/queue targets matched
the running installation. Intended provider credentials were present (checked
only as booleans; no validity test or secret output).

SHA-256 image prefixes; full identities are retained in protected evidence:

| Service | Before | Deployed |
| --- | --- | --- |
| API | `0e6dbd4a08dc` | `56cb16e543d5` |
| Worker | `136d02f1f0ae` | `43eedbf87a50` |
| Scheduler | `65f496a1d5c7` | `c51ba65745de` |
| Migration service | `54a0b7c2a999` | `53db3695ec34` |
| PostgreSQL | `721873c34ceb` | unchanged |
| Redis | `858f009f9709` | unchanged |

Application images have identical filesystem layers/config except Compose
service labels, accounting for their different IDs. Every installed Python
application source file in API/worker/scheduler hashes identically to the
checkout. PostgreSQL/Redis container IDs and named-volume attachments are
unchanged. API remains loopback-only; data ports remain unpublished.

### Protected backup and verified restoration

Preserved directory outside Git:

```text
/home/zkralec/.local/share/personal-dot/backups/deploy-20261024T020055Z/
```

Archive: `personal_dot-before-0008.dump`, custom format, 20,112 bytes. SHA-256:
`d40cf23e4957045806e7cf695f0d0d1de01bff885a4f49004543fbc63bec42c2`.
Directory `0700`, files `0600`; filesystem protected, not encrypted/off-host.
`SHA256SUMS`, before/restored/upgraded/after fingerprints and
`restore-verification.json` accompany it. Detailed logs, commands, full image
identities and module checks are preserved under its private `evidence/`
directory; working evidence also remains at `/tmp/pd-deploy-20261024T020055Z/`.

Stopped only API/worker/scheduler, rechecked the quiet window, and dumped via the
running PostgreSQL service. Restored using
`pg_restore --exit-on-error --no-owner --no-privileges` into a fresh database in a
container pinned to the exact running PostgreSQL image, with `--network none`,
no published ports and tmpfs data. Every table's count/ordered row-data MD5
matched. Columns/indexes matched; all constraints were validated and matched
after narrowly normalizing PostgreSQL's equivalent varchar-array/text-array
cast rendering. No private row contents were displayed.

The initial connection raced PostgreSQL's temporary initialization socket; no
restore data was applied. Waiting for the final TCP listener fixed the temporary
operator helper. The successful restore then exposed only the equivalent
constraint rendering described above. Neither required a repository repair.
Original ownership/ACL application and cluster-global roles were excluded from
this restore test; it is not a complete disaster-recovery drill.

Rehearsed the existing migrations on this restored copy using the new migration
image and the restore container's network namespace, still without external
network access. Revision reached `0008`, all existing row fingerprints remained
identical, and the outbox was empty. Only then upgraded the real database:

| Table | Before | After |
| --- | ---: | ---: |
| tasks | 7 | 7 |
| schedules | 2 | 2 |
| memories / notes / tool_calls / approval_requests | 0 each | 0 each |
| notification_deliveries | absent | 0 |

Every pre-existing non-version table fingerprint remained identical, including
task results/metadata and complete schedule records. No real test task/memory
was added; no shared Redis flush, persistent-volume removal, real database reset,
downgrade or schedule enable occurred.

### Commands and deployed checks

Maintenance order, with protected backup/restore checks between stop and upgrade:

```bash
docker compose stop api worker scheduler
docker compose exec -T postgres sh -c 'pg_dump --format=custom -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP_DIR/personal_dot-before-0008.dump"
# Restore, compare, build, then rehearse migrations on the isolated restored copy.
docker compose build api worker scheduler migrate
docker compose run --rm --no-deps migrate
docker compose up --no-deps --no-build --force-recreate --exit-code-from migrate migrate
docker compose up -d --no-deps --no-build --force-recreate --wait --wait-timeout 60 api worker scheduler
docker compose exec -T api alembic current
docker compose exec -T api alembic check
docker compose exec -T api python -m pip check
curl --fail http://127.0.0.1:8000/health
```

The second `upgrade head` refreshed the stopped Compose migration service and
verified idempotent startup with the new image. Real revision:
**0006 -> 0007 -> 0008**. `alembic current`: `0008 (head)`; `alembic check`: no
new operations; `pip check`: no broken requirements; `/health`: PostgreSQL/Redis
OK. API OpenAPI advertises `project_check_in` and terminal `uncertain`.
API/worker/scheduler and data services are healthy; migration service exited zero.
Inspected all six deployed service logs since deployment: normal startup and no
errors, task/model starts, schedule materializations or notification attempts.
RQ remains idle with one registered worker. Check-in configuration retains
`gpt-6-luna`, output cap 2,048, timeout 60 seconds, SDK retries zero; inspecting
these settings made no provider call.

### Isolated synthetic verification

Reused `evaluations/check_in/isolated_compose.py --stub-check-in-providers`, fresh
project `pd-eval-deploy-20261024t020055z`, and the exact built API image tagged for
that project. Validated an internal network, no published ports, blank provider
credentials and both paid gates disabled. Only the temporary manifest's
PostgreSQL/Redis mounts were changed to tmpfs to avoid persistent test volumes.
Selected existing tests without enabling any schedules:

```bash
pytest tests/test_health.py tests/test_tasks.py tests/test_agent_service.py \
  tests/test_notifications.py tests/test_tools.py tests/test_memories.py \
  tests/test_check_in.py tests/test_check_in_evaluation.py \
  'tests/test_check_in_process.py::test_check_in_through_http_and_forked_worker[False]' \
  tests/test_openai_integration.py
```

**104 passed, 1 skipped**, 105 collected, 9.29 seconds. The paid integration test
was skipped. All 21 authored evaluation cases and the manual real-HTTP/forked-RQ
workflow are covered. This is not a rerun of the historical 133-pass scheduling
suite; scheduling suites/parameterization were omitted to keep every schedule
disabled, even in isolation.

Also started isolated API/worker/scheduler services and ran a temporary
manual-only adaptation of `tests/scheduled_lifecycle_smoke.py`, reusing its
HTTP/wait helpers and existing provider bootstraps. Synthetic task
`4d94fe08-d716-49e6-9f70-248e6497cabc` succeeded with one stub model call. Initial
stub delivery failed; after advancing only its isolated retry deadline, the
scheduler recorded the second stub attempt as sent. Snapshot identity and
result remained unchanged and matched fresh HTTP/database reads. No tool calls
or schedules existed. Inspected all six isolated service logs; no unexpected
errors/tracebacks. No real external notification or model request occurred.

Removed only this run's temporary verification/restore containers and isolated
network; tmpfs data disappeared. No persistent volumes were removed. Protected
backup/evidence and built images remain.

### Readiness and limits

Ready for separately scoped citation/diagnostic fixes, then a separately
authorized controlled live check-in. No live request is authorized by this
deployment milestone. Live provider compatibility, output quality, actual usage
and cost, phone receipt/duplicates, and the process-local one-push-attempt live
procedure remain unverified. No private notes were selected or submitted; actual
inputs and budget remain operator decisions.

Remaining findings relevant to real use: unknown IDs in prose bypass production
citation checks; valid structured IDs do not prove factual support; generic
unexpected/queue/DB diagnostics need broader safe boundaries; delayed generic
approval resume and stale waiting metadata remain defective; prior inference
has no age/content-change exclusion, and capture time is absent from model
context. General attempt history, authentication, least-privilege database roles,
generic notification outbox, host-power-loss/partition recovery and full role/ACL
restoration were not added or verified. Check-ins retain the tool-free boundary.
Both real schedules remain disabled; no check-in schedules, active tasks or
pending/sending notification deliveries exist. Recurrence requires separate
authorization. Older deployment/credential claims below are historical and are
superseded where verified above.

## Controlled live verification preflight — 2026-10-23

**Blocked before submission; no model request, Pushover attempt, or task creation.**
Read the development rules/status and inspected configuration without displaying
secrets. This was a read-only check of the normal running stack, not a repeat of
the prior synthetic test suite. No service, schema, task, memory or schedule was
changed. No live credentials or private notes were copied into Git.

Observed configuration and smallest required repairs:

| Check | Evidence | Required continuation |
| --- | --- | --- |
| Model configuration | API and worker agree on `gpt-6-luna`, reasoning `low`, verbosity `medium`, output cap 4,096, SDK timeout 120 seconds, retries 2. `OPENAI_API_KEY` is present; validity was not tested. | Retain the existing model. Current check-in code caps output to 2,048, timeout to 60 seconds and SDK retries to zero. |
| Pushover | `PUSHOVER_API_TOKEN` and `PUSHOVER_USER_KEY` are absent in `.env` and the running API/worker. `.env` permissions are `0600`. | Supply both secrets locally in ignored `.env`, then recreate application processes. No additional test push is authorized beyond the one controlled attempt. |
| Selected personal inputs | No explicit check-in request/configured `project_id`, `note_ids`, or `priorities`; no stored check-in schedule. Only two generic-agent schedules exist, both disabled. Note content was not read or selected. | Operator must choose actual enabled `project_note` UUIDs and provide the project slug and priorities. Do not substitute README/evaluation fixtures or infer a selection. |
| Test budget | No explicit live-test spend cap/configuration was supplied or found. The runtime output-token setting is not an approved total spend budget. | Operator must approve a concrete cap against the existing model/limits before submission. The runbook worksheet is an operator gate, not a new application-enforced USD budget. |
| Running version | API's installed Alembic reports `0006 (head)`; worker module inspection finds neither `personal_dot.check_in` nor `personal_dot.notification_delivery`. Repository schema head is `0008`. | Back up the database, rebuild API/worker/scheduler/migration image and apply existing migrations in a quiet maintenance window. Healthy old containers alone do not establish check-in readiness. |
| Availability/recurrence | API `/health` reports PostgreSQL/Redis OK. Compose API/worker/scheduler are healthy; API binds `127.0.0.1:8000`. Both stored schedules remain disabled. | Keep recurring execution disabled. No check-in schedule ID exists to enable yet; create a reviewed disabled schedule before using its returned ID. |

Consequently the real check-in API/worker execution, live persisted result,
source validity of a live recommendation, returned usage/provider metadata,
Pushover acceptance and duplicate-observation checks **remain unverified**.
No cost was measured or billed usage queried. A presence check is not credential
validation, and there was no push for the operator to check on the phone.

Updated the existing [operations guide](scheduled-check-ins.md#controlled-live-verification)
with startup/health checks, private input/budget worksheets, upgrade/backup
commands, a single-submission maintenance procedure using a one-job forked RQ
worker with SDK retries disabled and the existing notification limit narrowed
to one in that process, independent delivery inspection, failure stop rules,
schedule controls and a blank 14-day usefulness/failures/actual-cost log. The
normal scheduler must remain stopped during this procedure; a crash can leave
a claim pending under its normal three-attempt policy. No permanent retry
configuration or unrelated feature was added. These continuation commands have
not been executed on personal data; phone arrival requires the operator's
manual check even if a future provider response says `sent`.

Documentation verification: 37 shell blocks passed `bash -n`; 10 embedded
Python snippets parsed; documentation file links and Git whitespace checks
passed. Read-only inspection confirmed installed RQ supports `burst`, `max_jobs`
and `with_scheduler` controls plus queue inspection. The maintenance procedure
and its process-local delivery override were not exercised end to end here.
No migrations or application tests were run against the normal personal database.
The earlier isolated **133 passed, 1 skipped** evidence below remains a synthetic
baseline, not evidence of this requested live verification.

## Persistent project check-in scheduling — 2026-10-23

Implemented from clean baseline `bed1abe`, reusing the existing dedicated
scheduler, schedule API, PostgreSQL occurrence key, task worker, check-in
contracts, and notification interface. No dependency or additional process was
added. [Migration 0008](../alembic/versions/0008_schedule_check_ins.py) permits
check-in schedules, adds terminal `uncertain`, and creates durable check-in
notification delivery intent. Applied migrations were not edited.

**No live recurring schedule was created or enabled. Real user data and the
normal stack were not accessed or changed.** Only synthetic schedules in the
isolated verification project were enabled; its container smoke schedule was
paused immediately after its one successful occurrence.

Implemented policies:

- Check-in schedules default to disabled and reject enabled creation. A separate
  operator PATCH enables them after current note selection is validated.
  Materialization snapshots current selected notes with the existing input
  bounds, hashes, provenance, prior-result selection and no-tools contract.
  Invalid later inputs create safe failed occurrences without model work.
- PostgreSQL owns `(schedule_id, scheduled_for)` uniqueness and schedule
  advancement in one row-locked transaction. Concurrent scheduler polls and
  duplicate queue deliveries cannot create a second task for that occurrence.
- Enabled downtime coalesces all due check-ins into one task keyed by the
  earliest pending timestamp, recording the covered window, then advances to
  the next future occurrence. Disabled recurring windows are skipped on enable.
  Generic schedules keep their existing bounded chronological catch-up policy.
- Configured IANA cron timezones include `America/New_York`. Spring gaps skip
  nonexistent wall times; fall folds run only the first occurrence. Interval
  schedules retain UTC elapsed-time anchoring.
- Manual and scheduled check-ins share a PostgreSQL project advisory lock.
  Competing executions fail promptly with `skipped_overlap`, without a model
  request or retry. Each task permits one model request, zero SDK retries,
  at most 2,048 output tokens, a maximum 60-second SDK timeout and the existing
  RQ timeout. Queued delivery recovery retains task identity and snapshot.
- Stale running work, transport interruptions and RQ timeouts during generation
  become terminal `uncertain`; automatic model retry is disabled. Late worker
  completion cannot overwrite that state. Future occurrences remain eligible
  after lock release; uncertainty does not automatically pause recurrence.
  This bounds local execution, without claiming remote provider work stopped.
- Terminal result and unique notification intent commit atomically for check-ins.
  Delivery retries independently in the existing scheduler, with three total
  claims, 60/300-second failure delays, a 120-second claim lease and fenced
  updates. Interrupted claims retain an unknown outcome. Exhaustion is visible
  in task notification metadata and never reruns or changes completed model
  work. Notifications remain status-only; uncertain outcomes are described
  explicitly. Historical completed tasks are not backfilled.
- SQLAlchemy hides bound parameters, and schedule materialization errors use
  fixed diagnostics. This is a limited reduction in diagnostic disclosure, not
  resolution of all generic error/logging findings below.

Exact deployment and **inspect, enable, pause and disable commands**, plus the
full duplicate/downtime/DST/notification policies and isolated reproduction,
are in [the scheduled check-in guide](scheduled-check-ins.md).

### Verification evidence

- Full final-code isolated suite: **133 passed, 1 skipped**, 134 collected,
  in 19.84 seconds.
  The skipped test is the explicitly gated paid OpenAI integration test. No
  real model generation or external notification occurred.
- The [scheduling regressions](../tests/test_scheduled_check_in.py) cover
  disabled creation, enable/pause, disabled gaps, simultaneous schedulers,
  database uniqueness rejection, 100-day downtime coalescing, current snapshots,
  deleted inputs, queue loss/recovery, New York spring/fall boundaries,
  concurrent project execution, late completion fencing, future execution after
  uncertainty, SDK/RQ timeouts, notification backoff/exhaustion, expired final
  claims, independent retries and simultaneous delivery claims.
- The [process test](../tests/test_check_in_process.py) runs actual HTTP,
  independent scheduler and forked RQ processes with synthetic SDK/push providers.
  The [container smoke harness](../tests/scheduled_lifecycle_smoke.py) additionally
  exercised actual API/worker/scheduler services: task
  `47369bd7-d61e-4c56-bf47-14978570c2c2` succeeded with one synthetic model call;
  its initial push failed, scheduler retry succeeded, and delivery audit recorded
  two attempts. Its result stayed unchanged and schedule
  `50d8a6f6-21f2-4398-b5fa-da7f0343ddfe` ended disabled. Only the synthetic push's
  retry deadline was advanced to shorten the wait.
- Built the shared application image and started API, worker, scheduler,
  migration, PostgreSQL and Redis containers. All eight migrations applied to
  fresh isolated test/application databases. `alembic current` returned
  `0008 (head)`; `alembic check` found no new operations; `pip check` passed.
  API, worker and scheduler were healthy. Docker network inspection confirmed
  `Internal=true`; no host ports were published.
- Inspected all six service logs: expected materialize/enqueue/start/success and
  failed-then-sent notification events; no unexpected application errors.
  PostgreSQL logged the deliberate duplicate-key rejection. Redis retained the
  known host overcommit warning; no host settings were changed.
- Isolation used project `pd-eval-scheduling-20261023`, final manifest
  `/tmp/pd-eval-scheduling-final-20261023.json`, its own volumes/image/network,
  no inherited application interpolation or `.env`, blank credentials and both
  paid gates disabled. The generator's `--stub-check-in-providers` option changes
  only isolated verification commands. Build/suite/service evidence is retained
  locally under `/tmp/pd-scheduling-*.log`; reproducible commands are in the guide.
  Source syntax and Git whitespace checks passed.
  The disposable containers, network and PostgreSQL/Redis volumes were removed
  after evidence inspection; temporary logs/manifests and the built image remain.

### Remaining limits

No paid model quality, real provider/device delivery, hard worker kill during a
paid request, host power loss, database connection partition, backup restoration,
or remote security was verified. Downtime, stale work and lease expiry use a
controlled clock or synthetic persisted deadlines; concurrency uses independent
database connections and real threads/processes. PostgreSQL project locks cannot
prove provider-side exclusivity after a connection loss or timeout while remote
work may continue. Future occurrences can still execute; operators can pause
the schedule to require review. Notification acceptance followed by a crash may
duplicate a push; three exhausted/unknown claims can leave it undelivered.
Exactly-once model work and push delivery are not claimed. Migration downgrade
with new-type data was not exercised. There is no general attempt ledger,
authentication, generic approval-resume repair, generic notification outbox,
or deployment to the normal stack. Prior semantic-quality and security findings
remain open unless explicitly superseded above.

The following reports describe earlier revisions. Their manual-only schedule,
automatic stale check-in retry and best-effort check-in notification statements
are superseded by this milestone; generic-task limitations still apply.

## Independent check-in review and evaluation — 2026-10-23

Reviewed source baseline `0e96b26` from a clean working tree. Read `AGENTS.md`,
the README and documentation below, the check-in contracts/orchestration,
adapter, API, worker, scheduler, notification boundary, models, all seven
migrations, and relevant tests. Earlier completion statements were treated as
claims and checked against source and a new isolated run.

No critical or high-severity check-in defect was confirmed within the documented
trusted-local, manual, advisory milestone. No critical/high fix was therefore
required. The generic approval-resume and generic error-disclosure findings in
the historical audit remain open; check-ins bypass that approval runtime and
sanitize model/output failures. Authentication, a notification outbox, durable
attempt history and remote deployment were not added to this milestone.

### Findings, failure scenarios and recommended fixes

| Severity | Finding and evidence | Failure scenario | Recommended follow-up |
| --- | --- | --- | --- |
| Medium | **Valid citation identifiers do not establish factual support.** [`_validate_sources`](../src/personal_dot/check_in.py#L129) and [`CheckInResult`](../src/personal_dot/check_in_schemas.py#L56) validate structure and selected IDs. The new `test_valid_source_ids_do_not_establish_factual_support` demonstrates acceptance of an invented production deployment and client approval when valid IDs accompany it. | A successful task can contain a false completion claim or repeat completed work. No real-model frequency or actual model failure is established by this authored probe. | Require the human factual-support/usefulness rubric before treating output as reliable advice. Keep deployment/readiness claims distinct from structural validation. Claim-level evidence would require a separately reviewed contract change. |
| Medium | **Unknown references in prose bypass production source checks.** The same validator checks `supporting_source_ids` and action/blocker citation arrays, not IDs written inside `summary`, descriptions or rationale. The `unsupported_prose_reference` case is accepted by production and separately flagged by the evaluation runner. | A summary cites `memory:00000000-0000-0000-0000-000000000000` while its structured arrays contain selected sources. A reader may mistake the invented reference for audited evidence. | Consider forbidding inline source identifiers or validating them in the output contract. The new evaluation flags identifier-shaped unknown prose references; this detection does not fix production or validate meaning. |
| Medium | **Prior inference can be arbitrarily old and refer to superseded content.** [`prepare_check_in`](../src/personal_dot/check_in.py#L90) matches project, note-ID set and priorities, without comparing content hashes or limiting age. `test_reuses_only_relevant_prior_successful_results` confirms reuse after a selected note is edited. | A prior recommendation to implement a guard is included after the current note says it is complete. Memory IDs remain the same despite changed evidence. The prompt labels prior inference untrusted, but model compliance has not been measured. | Review the stale/unchanged cases against genuine outputs. If anchoring appears, add explicit changed-source provenance or an omission policy for stale inference. Do not treat timestamps or an unchanged note as progress. |
| Medium | **Recovery does not retain a durable model-attempt history.** [`_recover_stale_tasks`](../src/personal_dot/scheduler.py#L187) replaces execution metadata, and [`execute_task`](../src/personal_dot/jobs.py#L180) replaces it again on execution and completion. This is the existing shared lifecycle, not a new check-in regression. | A worker dies after a paid request, and reconciliation repeats it. PostgreSQL retains the accepted inputs and final task but cannot reconstruct all earlier attempts, costs or recovery transitions. | Add append-only attempt/transition records in the existing hardening milestone. Preserve the current at-least-once disclosure; do not claim exactly-once paid execution. |
| Medium | **Model-error sanitization does not cover database-write diagnostics.** [`db.py`](../src/personal_dot/db.py#L13) uses the default parameter rendering, while task commits in [`main.py`](../src/personal_dot/main.py#L100) and the worker sit outside the check-in-specific safe-error boundary. A deliberately invalid foreign-key insert, rolled back in the isolated database, included a synthetic private project identifier from task JSON in its SQLAlchemy exception string. | A database write failure can expose task parameter previews in protected API/RQ diagnostics. This probe established parameter rendering, not an actual production leak or disclosure of complete notes. | In the shared diagnostic hardening milestone, hide bound parameters and add fixed database-error boundaries; account for database exception details as well as SQLAlchemy parameter rendering. Do not interpret check-in model-error tests as comprehensive log redaction. |
| Low | **Capture time is persisted but not supplied to the model.** [`render_context`](../src/personal_dot/check_in.py#L46) omits `PreparedCheckIn.captured_at`. Notes have edit timestamps, which are not the request's as-of time. | Notes using relative dates or an old unchanged status do not establish today's state. | Supply an explicit as-of timestamp in a future versioned context and evaluate temporal interpretation; avoid resolving dates without evidence meanwhile. |

### Changes made

- Added the [21-case corpus](../evaluations/check_in/cases.json),
  [runner](../src/personal_dot/check_in_evaluation.py),
  [rubric and commands](../evaluations/check_in/README.md), and
  [compact contract baseline](../evaluations/check_in/contract-baseline.json).
  Twelve cases have human quality expectations; nine probe deterministic
  contract failures/limits. No evaluation platform or dependency was added.
  The image includes the corpus so normal container tests and the standalone
  runner work without a source-directory mount.
- Extracted the existing prompt and result validator so production and
  evaluation share them verbatim; added an optional service injection point to
  the handler. Compared the prompt expression against `0e96b26` using Python
  ASTs: unchanged. The result schema, production model settings, permissions,
  database schema, migrations and public API behavior remain unchanged.
- Default evaluation uses clearly labelled authored SDK fixtures, reports
  `quality=not_evaluated`, and programmatically checks source identifiers.
  Both `--live` and `RUN_CHECK_IN_LIVE_EVAL=1` are required for paid generation;
  environment opt-in alone does not enable it. Live results still require
  human review; no automated semantic-quality score is produced.
- Reports record prompt/corpus/schema/code hashes, model/configuration identity,
  Python/SDK versions, per-case input identity, and response metadata when
  available. The baseline identifies the reviewed source plus working changes
  through code hashes. This resolves the absence of comparable evaluation
  evidence, not the open model-quality findings above.
- Added deterministic corpus/gating/report tests and a check-in-specific stale
  recovery regression. Recovery preserves the queued snapshot even after source
  deletion, resets its start time, and completes without tools or notification.
  The suspected immediate stale retry from retaining the original start time
  was ruled out: the reconciler clears it before requeueing. The separately
  documented generic approval-resume defect is unchanged.

### Verification and commands

Final image run: **113 passed, 1 skipped**, 114 collected, in 12.19 seconds
(the earlier run passed in 10.07 seconds).
The skip is the explicitly gated paid generic OpenAI integration test. All
success responses and notification sends in the suite were synthetic. The
live-runner plumbing test also uses an SDK stub and proves no model quality.

The standalone corpus run met **21/21 authored fixture expectations**. It made
20 synthetic SDK invocations and rejected one invalid request before generation.
Its unknown-prose-source case deliberately records production acceptance plus
an evaluation flag; it is not a quality pass. Prompt identity:
`78fdd1331898b68e3831a18d3492def53cc16eb5619a95c7eafedb644c02ce84`.
Configured model was `gpt-6-luna`, reasoning `low`, verbosity `medium`, at most
2,048 output tokens, timeout 60 seconds, retries zero, no tools and `store=false`.
Returned fixture model was `synthetic-contract-fixture`. Full identities and
per-case outcomes are in the committed baseline; no real model was queried.

Reproducible isolation is now tracked in
[`isolated_compose.py`](../evaluations/check_in/isolated_compose.py). This run used
fresh project `pd-eval-review-20261023`, its own volumes/image/network, no host
ports, an internal network, blank provider credentials, both paid gates disabled,
and no inherited application interpolation or `.env`. The normal stack was not
queried or modified. Run from the repository root:

```bash
python3 evaluations/check_in/isolated_compose.py \
  --project pd-eval-review-20261023 --output /tmp/pd-eval-review-20261023.json
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json build test
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json run --rm test
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json up -d --no-build --wait api worker
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json exec -T api alembic current
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json exec -T api alembic check
docker compose -p pd-eval-review-20261023 -f /tmp/pd-eval-review-20261023.json exec -T api python -m pip check
```

All seven migrations applied to fresh test and application databases;
`alembic current` returned `0007 (head)`, `alembic check` found no new upgrade
operations, and `pip check` found no broken requirements. The full suite includes
the real HTTP/forked RQ process workflow with a synthetic SDK provider. A separate
HTTP request against the isolated API/worker services exercised the real
adapter's missing-key failure: PostgreSQL retained the accepted snapshot/hash and
fixed error, with no result, tool calls, schedules or notification. Logs showed
the expected safe failure and healthy API/worker startup.
After packaging the corpus, the image was rebuilt, the full suite and standalone
runner passed without a source mount, and the final API/worker containers started
healthy. The final manifest was `/tmp/pd-eval-review-final.json` for the same
disposable project. Syntax, documentation file links, baseline code/corpus hashes
and Git whitespace checks passed.
The disposable review containers, network and PostgreSQL/Redis volumes were
removed after verification; the built image and temporary local reports remain.

The deterministic evaluator can also run without PostgreSQL/Redis, using an
installed project environment:

```bash
python -m personal_dot.check_in_evaluation \
  --revision "$(git rev-parse HEAD)" --output /tmp/check-in-contracts.json
```

Image-only report collection and the optional paid command are documented in
the [evaluation guide](../evaluations/check_in/README.md). Use a new report path
and fresh Compose project/path on reruns. The manifest generator and report
writer refuse overwrites. Only remove the disposable project's volumes when
finished; do not run cleanup commands against the normal stack.

### Exactly what remains untested in this review

- No paid OpenAI call: actual configured-model availability, request compatibility,
  provider timeout/refusal/rate-limit behavior, real token usage and live output
  quality remain unverified. Incomplete/unavailable/empty responses were synthetic.
- No genuine model outputs were human-scored. Factual support, usefulness,
  uncertainty, stale-result handling and resistance to embedded instructions or
  external-action requests remain unmeasured. The rubric is ready for future use.
  Relative-date interpretation was inspected as a context limitation, not tested
  against a model. This small corpus does not establish general robustness.
- No real Pushover delivery or other external action. Provider success/failure
  notifications were stubs; crash windows around notification send/audit and a
  durable delivery outbox remain untested/unimplemented.
- Stale recovery was simulated through real PostgreSQL, not by killing a worker
  during a paid call. Concurrent recovery, late-worker completion/fencing, host
  reboot, network partitions and backup restoration were not exercised. The
  suite's sequential scheduling tests do not prove those guarantees.
- Authentication/authorization, remote exposure, database least privilege,
  retention/deletion of task snapshots, broad adversarial testing, dependency
  locking, static typing and linting were not newly verified or implemented.
  The documented local-only trust boundary and historical findings still apply.
- No deployment or data operation against the normal local stack.

## Prior milestone completion report: manual project check-in

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
