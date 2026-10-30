# Bounded automatic documentation publishing

Implementation and simulated verification only. Production is not migrated or
deployed by this milestone. No live GitHub writes, paid model calls or schedule
enabling were performed. `DOCS_PUBLISH_LIVE_ENABLED` defaults to false, and the
per-task `allow_publish` flag also defaults to false.

## Eligibility and authorization

`documentation_publish` consumes one existing successful `documentation_preview`
task. It does not discover repositories, generate text, request a review, or run
repository code. It reuses the immutable inspection snapshot, insertion policy,
exact candidate and independent reviewer record. A rejected, changed, stale or
incomplete review cannot publish. Current policy, workflow/model configuration,
source snapshot and configured personal owner must still match the reviewed
inputs. Keep preview configuration consistent through publication: switching its
live gate/model/SDK/policy also invalidates that preview's binding.

Discovery's `maintenance_eligible` flag grants no publishing eligibility. Each
attempt reads repository identity/default branch, active base and temporary
branch rulesets, and legacy protection for a protected base. Requirements and
blockers are retained in PostgreSQL. Unreadable, incomplete, unknown or unsupported
requirements fail closed. No repository settings, protection, review, status,
workflow or bypass endpoint is writable by this adapter.

The supported automatic subset has zero required GitHub approving reviews,
permits merge commits, and has no unsupported protection. DOT's independent model
review is policy evidence; it is never submitted or counted as a GitHub approving
review. Required GitHub reviews/code owners/last-push approval, conversation
resolution, restricted pushes, signatures, linear history, merge queues,
deployment/workflow/code-scanning rules, temporary branch creation restrictions
and unknown rules record blockers. DOT never weakens them. Such repositories
are outside this initial automatic subset, even when the App has bypass access.

Required status checks and check runs are read at the exact PR head; provider
pinned requirements need a matching App check run. Missing, pending, failed or
wrong-provider evidence blocks merging. All reported checks must be acceptable,
including optional checks. GitHub must report the exact PR as open, non-draft,
mergeable and `clean`. GitHub changes-requested reviews block it. Lists are
bounded to 100 entries, with a sentinel page where needed; incomplete evidence
blocks rather than silently dropping checks/reviews/rules.

Authorization binds repository identity, base commit, candidate hash, PR head,
independent review record, current GitHub requirements/check evidence, policy
version and publisher implementation. Source/policy/configuration/candidate drift
requires fresh inspection/preview/review. Check and rule observations are
revalidated before the merge; any observed change stops that merge attempt.
The worker polls checks/mergeability up to `DOCS_PUBLISH_CHECK_POLLS` times
(default 12, maximum 60), separated by `DOCS_PUBLISH_POLL_SECONDS` (default 5,
maximum 30). A qualifying PR merges automatically within that bounded window.
After the window expires, a later explicit attempt can revalidate the same job/PR.
This is bounded waiting inside a worker job, not a scheduled behavior or API timer.

## Exact bytes and attribution

The controller constructs content-addressed blobs, trees and a single commit from
the approved insertions over their original base. It reads only affected tree
ancestors (at most 64), verifies Git tree identities and original target modes/
blob hashes, and retains the entire deterministic object plan. No checkout,
hook, shell, build or model is involved. Creating the Git ref publishes the
commit using the Git database API, equivalent to pushing a temporary branch;
there is no force push or update-ref operation.

The temporary branch is `dot/docs-PREVIEW_UUID_WITHOUT_HYPHENS`. Its initial
absence, intents, expected SHA and discovered PR number are durable. PR files,
sole commit, head/base/repository and complete commit tree must match the reviewed
candidate. This compares exact content/tree identities rather than relying on
GitHub's textual patch formatting or potentially truncated patch fields.

Both candidate author and committer must be exactly:

```text
Zachary Kralec
157630586+zkralec@users.noreply.github.com
```

Trusted settings `GITHUB_COMMIT_AUTHOR_NAME` and `GITHUB_COMMIT_AUTHOR_EMAIL`
default to that supplied identity; any mismatch blocks. Commit object hashes
were independently checked against Git's `hash-object`. The only selected merge
method is `merge`, preserving the original candidate commit and its attribution.
GitHub authors the additional merge commit using the authenticated integration;
DOT does not claim that this integration-created merge commit is owner-authored.
Squash/rebase-only repositories block rather than silently replacing authorship.
After merging, the original attributed commit, both merge parents and exact merged
tree are verified. GitHub account-link rendering for this supplied noreply email
still needs the live pilot; fixture verification proves the exact name/email.

## Durable operations and recovery

Migration `0012` adds a publication job keyed by preview task ID and a partial
unique index allowing one unfinished job per repository. PostgreSQL owns its
object plan, input binding, operation intents/outcomes, branch, PR, authorization,
merge and cleanup state. Delivery attempts remain ordinary tasks. A repository
advisory lock spans a handler; it is acquired before locking the review source,
so overlapping attempts stop without waiting on an active remote write.

Before each external write, the intent is committed. The next transaction locks
the current task claim, rechecks its execution UUID and reviewed source, then
holds the claim lock through remote reconciliation, write and outcome commit.
Stale recovery skips an in-flight locked write; a revoked worker cannot start
the next one. Recovery marks an interrupted publishing task `uncertain`, retains
the publication journal, and does not automatically retry publication.

Each resumed operation reads its deterministic object/ref/PR/merge outcome before
writing. Immutable objects can be retrieved by their locally computed Git SHA.
PR lookup includes closed PRs and checks the job marker. Accepted-but-lost merge
responses reconcile through the existing PR before the changed-base gate. The
actual merge is persisted before branch cleanup. Even after review or operator
authorization is invalidated, an explicit attempt can reconcile already accepted
outcomes with read-scoped credentials; it cannot make another repository write.
Each operation permits at most three write attempts across delivery tasks.

Only a completed job's exact temporary ref at the expected head is deleted.
Changed refs are retained with a blocker. No default branch, foreign branch,
unrelated PR or repository setting can be deleted or overwritten. Failed/blocked
jobs retain the repository slot, including when a PR needs owner reconciliation;
there is no automatic abandonment/cancellation or PR closing feature in this
milestone. Do not edit database records to release a slot during the pilot.

`published`, `merged` and `deployed` are separate result booleans. Deployment is
always false: merging provides no deployment evidence. Infrastructure task
success can carry semantic blockers; inspect `result.blockers`, not just task
status. Optional status notifications reuse the existing three-attempt delivery
outbox, contain a fixed publication status and task ID, and never dispatch model
or publishing work. Notification failure cannot alter the persisted result.

## App permissions and credential boundary

Reuse the configured personal-account GitHub App and worker-only owner-readable
private key. No key mount or root execution is added to API/scheduler/migrate/test.
For a separately authorized pilot, an operator must explicitly grant the App:

- Contents and Pull requests: write.
- Checks, Commit statuses and Metadata: read.
- Administration: read only when protected-branch inspection requires it.

Administration read is requested only to inspect protected branches; unprotected
targets do not need that grant. Missing access blocks the protected target. Administration
write is neither requested nor supported. Installation tokens are repository
scoped, short lived and process local. Ordinary discovery/inspection continues
to request only Contents/Metadata read. Publishing previews normally request read scopes. When GitHub omits merge
settings, the preview obtains already-granted publication scopes for a GET-only
capability read; repository writes remain disabled on that client. No credentials enter model inputs, task data, Git config, URLs or logs.
The previously documented read-only installation will block publication until
its permissions are separately changed by the owner; this milestone makes no
App permission or installation changes.

## Commands for preview and one later live maintenance job

These are operator commands for a separately approved pilot, not instructions
executed during implementation. First deploy schema `0012` and matching API/
worker/scheduler through the existing backup/restore and idle-window procedure.
Keep schedules disabled. Keep both paid and publishing gates off initially.

1. Submit a fresh read-only inspection and inspect its immutable evidence:

   ```bash
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
     -H 'Content-Type: application/json' \
     -d '{"type":"github_inspect","payload":{"repository":"personal-dot"}}'
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks/INSPECTION_TASK_ID
   ```

2. Follow [the exact selection/budget preview procedure](documentation-preview.md)
   using this fresh snapshot. Submit the owner-reviewed local request once:

   ```bash
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
     -H 'Content-Type: application/json' --data-binary @/protected/preview-request.json
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks/PREVIEW_TASK_ID
   ```

   Paid generation needs separate owner permission for the exact public inputs,
   model and budget, plus its operator gate and `allow_paid_model=true`. A
   disabled-gate test cannot produce an approved candidate. Require a completed
   `approved_candidate`, inspect the exact diff/review, and keep its configuration
   stable. Publication does not make any additional paid call.

3. Preview that candidate's current publishing requirements, without repository
   writes or a publication-job reservation:

   ```bash
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
     -H 'Content-Type: application/json' \
     -d '{"type":"documentation_publish","payload":{"preview_task_id":"PREVIEW_TASK_ID","allow_publish":false}}'
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks/PUBLISHING_PREVIEW_TASK_ID
   ```

   Review blockers and required checks. Do not change repository rules to pass.
   Grant only the separately authorized App permissions described above.

4. For exactly one later authorized live job, set
   `DOCS_PUBLISH_LIVE_ENABLED=true` in ignored operator configuration and recreate
   only the worker with the existing worker-only key override:

   ```bash
   docker compose -f compose.yaml -f compose.github.yaml up -d --no-deps --no-build worker
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
     -H 'Content-Type: application/json' \
     -d '{"type":"documentation_publish","payload":{"preview_task_id":"PREVIEW_TASK_ID","allow_publish":true},"notification_policy":"always"}'
   curl --fail-with-body -sS http://127.0.0.1:8000/tasks/MAINTENANCE_TASK_ID
   ```

   Save every returned ID; do not repeat a POST after losing its response. List
   `/tasks` and inspect the existing task first. For a known interrupted/pending
   job, submit another delivery task referencing the **same** preview ID only
   after inspecting the existing result; it reconciles the same durable job/PR.
   Never generate a replacement preview to retry an ambiguous publication.
   After the job is terminal and no worker is active, restore the publishing
   gate to false and recreate the worker. Restore the preview gate separately
   after its authorization window. Do not interpret a merge as a deployment.

## Verification limits

Simulated GitHub behavior and database rollback probes exercise lost responses,
retry/reconciliation, attribution, protection gates and stale ownership. They do
not establish live App write access, GitHub account attribution rendering,
real CI/check behavior, model quality, or production deployment. Host termination
while PostgreSQL itself is unavailable remains outside the fixture guarantees.

The REST merge endpoint has expected **head** SHA protection, with no atomic
expected-base or expected-rule/check-snapshot parameter. DOT rereads these inputs
under its local execution fence immediately before merging and verifies merge
parents/tree afterward. Another GitHub actor can still race this remote request.
An observed raced merge is recorded as merged with an owner-reconciliation
blocker, never retried or claimed fully verified; its branch is retained.
GitHub ref deletion likewise has no compare-and-delete SHA argument: DOT checks
the job-owned ref immediately before deletion. A concurrent external ref update
in that interval cannot be atomically excluded. The initial pilot must use a
quiet repository/window; this is not a claim of distributed exactly-once or
transactional remote snapshots.

Relevant GitHub contracts: [active branch rules](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch),
[legacy protection permissions](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection),
and [expected-head merge behavior](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request).

## Scheduled operation

The [daily maintenance guide](documentation-schedules.md) describes the account-wide
pool, explicit New York time, budget reservations, cached assessments, one-job
limits, successful-pilot gate and pause semantics. Publication remains this same
controller; the scheduler does not implement a second GitHub writer.

If a merged PR omits its merge SHA, finalization uses the persisted merge receipt
and verifies the expected parents/tree. Read-only reconciliation remains possible
when authorization changes. A repaired publisher may revalidate an already merged
job's exact original plan for cleanup; it cannot use that exception to create or
merge an unmerged PR. Daily maintenance continuation never regenerates its candidate.
