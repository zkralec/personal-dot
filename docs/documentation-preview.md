# Bounded documentation editor and reviewer

`documentation_preview` is one manual task over a completed immutable
`github_inspect` result. It identifies one supported documentation gap with one
editor call, validates its candidate, and requests one independent review with
fresh context. It never applies a patch, runs repository code, publishes, sends
notifications or enables schedules. A reviewer approval is an untrusted preview
assessment, not permission to publish. There is no automatic correction loop.

## Explicit input and editing policy

Policy version: `documentation-preview-v1`. Initial previews accept public,
maintenance-eligible repositories owned by the configured personal account.
Private-repository inspection remains available, but private model previews are
excluded in this first policy. This is a deliberate additional sharing boundary;
a future private-content preview requires a separate policy review.

The caller must select a successful inspection task, its exact base commit,
each existing target path and whole-file SHA-256, and each evidence path,
whole-file SHA-256 and 1-based inclusive line range. No automatic source or
memory selection occurs. The caller must inspect all selected target text and
evidence ranges and set `inputs_reviewed_for_model: true` as an explicit sharing
acknowledgment. The API cannot prove a human read the text; keep its existing
unauthenticated interface loopback-only. Hashes bind that acknowledgment to the
exact accepted bytes, and the server verifies Git blob hashes and inspection
inventory decisions as well as content hashes. Repository text cannot supply
these permissions or override the policy.

This is a deliberately narrow initial editor:

- Existing `README.md` and plain `.md` files under `docs/` only; no file creation,
  rename, deletion or rewriting. Candidates insert explanatory paragraphs at
  original 1-based line anchors, preserving every existing byte and heading.
- At most three changed files and 300 added lines, including blank lines. Trusted
  `DOCS_PREVIEW_MAX_FILES` and `DOCS_PREVIEW_MAX_CHANGED_LINES` can tighten those
  ceilings; raising them requires a new reviewed policy version.
- Agent instructions, authorization/security policies, configuration, source,
  dependencies, workflows, deployment/operations files and related sections are
  protected. `docs/STATUS.md` and `docs/documentation-maintenance.md` are excluded.
  Code fences, indented code and protected sections cannot be insertion anchors.
- No new commands, code blocks, links/HTML, headings, configuration assignments,
  authority changes, successful-check or maturity claims. Existing command
  examples remain unchanged. Executable Markdown templates/frontmatter/scripts
  and unsafe paths/modes are rejected.
- Every insertion needs selected evidence IDs and exact support quotes. References
  and quote presence are deterministic checks, not proof of factual support.
  The reviewer must assess whether the actual claim follows from the evidence.

Safety does not rely on heuristic secret detection alone: public-only sources,
explicit paths/ranges, owner acknowledgment, immutable hashes, extension/path/mode
exclusions, byte/line limits, output schemas and tool-free calls are mandatory.
Secret/control-character screening applies to inputs and decoded model strings;
unsafe output is discarded rather than copied into diagnostics. Unlabelled
secrets can still evade detection, including in public repositories. Review the
selected bytes; do not treat public availability as a declaration that they are
safe to send. No credentials or publishing tools enter model context.

Targets are at most 64 KiB each, evidence at most eight ranges of 200 lines and
32 KiB each. Each request includes a per-call input-byte and output-token budget;
input bytes count serialized input plus role instructions, including schema.
The application cap is 64 KiB input per call, 64 KiB raw structured output, and
`min(request budget, DOCS_PREVIEW_OUTPUT_TOKENS, OPENAI_MAX_OUTPUT_TOKENS)` output tokens (default 2,048,
ceiling 4,096). Review can be skipped if its exact diff/context exceeds the budget;
inputs are never silently truncated. At most two provider calls are permitted,
zero SDK retries, timeout at most 60 seconds per call and `store=false`.

## Exact API requests and results

Live retrieval was verified before implementation using:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"type":"github_inspect","payload":{"repository":"personal-dot"},"notification_policy":"none"}'
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/6d3702e5-c12e-47bf-9725-78a14731016f
```

The existing verified task is `6d3702e5-c12e-47bf-9725-78a14731016f`, commit
`a7e9366afcbde3c18ef602548b59ef680cbc1953`. It predates the local checkpoint and
this implementation. README, architecture and jobs bytes independently match
that exact Git revision; it is not a claim about the current checkout or head.
Use the saved task ID rather than rerunning inspection merely to read it.

After manually reviewing the selected bytes, this exact request selects README
and the execution-claim code as evidence. **It authorizes no paid call**:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{
  "type": "documentation_preview",
  "notification_policy": "none",
  "payload": {
    "inspection_task_id": "6d3702e5-c12e-47bf-9725-78a14731016f",
    "base_commit": "a7e9366afcbde3c18ef602548b59ef680cbc1953",
    "targets": [{
      "path": "README.md",
      "sha256": "8c4962da0978eb11ac39258389745ceb2c609b338acdda3c6a23e53912b6e3ef"
    }],
    "evidence": [{
      "path": "src/personal_dot/jobs.py",
      "sha256": "43bca01b2773bfb54550728789a5820b59013546187a7ee17bb54c0a0fbf1aaa",
      "start_line": 224,
      "end_line": 245
    }],
    "inputs_reviewed_for_model": true,
    "allow_paid_model": false,
    "budget": {
      "max_input_bytes_per_call": 65536,
      "max_output_tokens_per_call": 2048
    }
  }
}
JSON
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/RETURNED_PREVIEW_TASK_ID
```

The API prepares and persists only the explicit selected bytes. On the normal
stack this request fails safely at the paid gate before constructing a provider
client; it does not run a production stub or invent a candidate. Stub providers
are injected only in isolated tests, which exercise this same API/task pipeline.

`Task.status` describes infrastructure execution independently of
`result.outcome`: `approved_candidate`, `changes_requested`, `no_useful_change`,
`insufficient_evidence` or `invalid_candidate` are successful workflow outcomes.
A provider/configuration failure is a failed task with `outcome=null` and safe
partial progress. An interrupted/unknown provider request becomes `uncertain`.
Do not interpret a partial running result as an approval.

Results retain the gap, candidate insertions and exact generated unified diff,
evidence references and hashes, deterministic validation, reviewer decision and
specific findings, requested model/configuration and prompt hashes, actual
provider model/request/response IDs and available usage per call. The aggregate
usage is mirrored in execution metadata. Task payload retains the exact accepted
inputs for audit; prompts/source bodies are not copied into logs. Before each
model request a UUID-fenced checkpoint records intent; after the editor, the
candidate/validation/usage are persisted before requesting review. A crash may
leave an unknown in-flight request; no automatic model retry occurs.

The reviewer has a separate service instance, new instructions and a fresh input
list containing original selected targets/evidence and the exact candidate diff.
It receives no editor rationale/conversation, continuation ID or hidden state.
It echoes an application-generated binding over repository, base commit, input/
evidence identity, candidate hash, policy and model configuration. Final commit
locks the task and source inspection, revalidates deterministic checks, recomputes
bindings/review-record integrity and rejects changed candidates, inputs, owner,
policy, configuration or outcome. Model approval cannot waive a failed check.

An independent context is not proof of independent errors or semantic accuracy,
particularly with the same model. Requested editor/reviewer models default to
`OPENAI_MODEL`; operators may choose separate models through the settings below.
No live quality or prompt-injection robustness is established by authored stubs.

## Later opt-in live preview — not authorized by this delivery

Leave `DOCS_PREVIEW_LIVE_ENABLED=false` now. Do not enable it or send
`allow_paid_model=true` until the owner separately approves the exact selected
public inputs, provider/model choices and budget. For the example above, the
budget is **at most two calls, each at most 65,536 serialized input bytes and
2,048 output tokens**, zero SDK retries; reasoning tokens consume the output cap
according to provider accounting. This is a byte/token budget, not a guaranteed
USD spending cap. Actual billed cost is unknown until reconciled with provider
usage/billing. Review current pricing and approve spending separately before use.
A no-op/invalid editor candidate makes only one call; a rejected review never
starts an automatic correction.

For that separately authorized window, choose explicit models and set in ignored
local configuration (no credentials in the request):

```dotenv
DOCS_PREVIEW_LIVE_ENABLED=true
DOCS_PREVIEW_EDITOR_MODEL=OWNER_APPROVED_MODEL
DOCS_PREVIEW_REVIEWER_MODEL=OWNER_APPROVED_MODEL
DOCS_PREVIEW_OUTPUT_TOKENS=2048
DOCS_PREVIEW_MAX_FILES=3
DOCS_PREVIEW_MAX_CHANGED_LINES=300
```

Use the existing idle-window deployment/backup procedure as appropriate; recreate
**both API and worker** to keep prepared configuration identities consistent.
Keep all schedules disabled and other clients quiet. Verify the provider key only
as present/absent, then submit the reviewed request once with
`allow_paid_model=true`. Save the returned task ID and poll it. Never repeat a
POST after a lost response or interrupted/uncertain model request. Inspect the
existing task, its immutable input, calls, usage, validation, diff and review.
When it is terminal and no work is active, restore the operator gate to false
and recreate API/worker. No test notification or publication follows.

The normal model transport holds its provider credential server-side; neither
model receives credentials in input or tools. The preview path does not load the
GitHub private key, instantiate the GitHub client, or invoke the agent tool runtime.
GitHub's worker-only read-only mount and discovery/inspection remain unchanged.
A candidate is bound to its historical base commit. Any future publisher must
recheck the current head and the full policy; none exists in this milestone.

## Publication handoff

The separate [bounded publisher](documentation-publishing.md) can consume a
completed approved preview, revalidate its exact inputs/review and current GitHub
requirements, and publish through the standing policy. Preview approval remains
policy evidence; it is not a GitHub approving review or authority to ignore branch
rules. Publishing is default-off and this implementation milestone made no live
repository writes. Historical statements above describing a future publisher
apply to the preview milestone, not the current implementation.
