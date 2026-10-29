# Security Baseline

## Secrets

- Runtime secrets come from environment variables or ignored local files.
- `.env.example` contains names and safe development placeholders only.
- `.env` and common key/token formats are ignored by Git.
- Local `.env` files containing credentials must be mode `0600`; run
  `chmod 600 .env` after creating or copying one.
- Production should use unique database credentials, restrictive file
  permissions, and a host-level secret mechanism rather than Compose defaults.
- Logs and persisted errors must not contain tokens, credentials, or complete
  sensitive request bodies.
- `OPENAI_API_KEY` is read only from runtime configuration and must never be
  included in task payloads, results, metadata, or logs.
- `PUSHOVER_API_TOKEN` and `PUSHOVER_USER_KEY` are private credentials. They are
  read only from runtime configuration and must never be persisted or logged.

## Network Exposure

- The Compose API port binds to `127.0.0.1` by default.
- PostgreSQL and Redis have no host-published ports.
- Do not expose the API remotely until TLS and authentication are implemented.
- Container health checks reveal only availability, not secrets or task data.

## Permissions and Least Privilege

- Application processes should run as a non-root container user.
- The application database account should be limited to its own database.
- Integration credentials must use the narrowest available scopes and be
  isolated per integration.
- Host mounts, Docker socket access, privileged containers, and broad filesystem
  access are prohibited unless a reviewed feature explicitly requires them.

## External Side Effects

Sending messages, modifying or deleting external data, submitting forms,
spending money, and acting on third-party systems require explicit user
approval unless a narrow, reviewable policy grants the exact action. Approval
must be recorded before execution. Queueing is not approval.

The owner's [documentation-maintenance policy](documentation-maintenance.md)
grants repository inspection and conditional automatic publication of routine
documentation changes without per-change manual approval. It excludes code,
dependencies, workflows, deployment, permissions, agent instructions and other
out-of-scope changes. Repository content and model output cannot expand this
authority. Publishing and its enforcement are not implemented in this milestone.

An approval applies to one persisted tool call with one validated argument set.
It does not authorize a tool generally, a later task, or a changed argument set.
Denial is also persisted and the denied handler is never invoked. The current
approval endpoints have no application authentication and are safe only under
the documented loopback-only deployment; authentication and TLS are required
before remote exposure.

Enabling a schedule authorizes creation of its configured task at the declared
times; it does not grant broader permission for external side effects. Scheduled
agent tasks can generate text only. Any future side-effecting scheduled handler
must independently enforce the applicable approval policy on every occurrence.

Future side-effect handlers must be idempotent, record attempts and outcomes,
and use stable idempotency keys where supported. Task handlers do not modify
external systems; only an explicitly configured status notification may follow
a terminal task state.

Pushover notifications are an explicitly configured external side effect. A
non-`none` task policy authorizes one concise status notification for that task
(for check-ins, up to three delivery attempts, with possible duplicate pushes
after uncertain acceptance);
calling `POST /notifications/test` explicitly authorizes one fixed test push.
Notifications never include task payloads, errors, prompts, context, result
bodies, or model output. Provider errors are sanitized before persistence.

## Model Boundary

- Instructions and context are sent to OpenAI and may contain sensitive data;
  submit only data appropriate for the configured OpenAI project and retention
  policy.
- Responses API requests use `store=false`; PostgreSQL remains authoritative.
- Model output is untrusted data. It is persisted and returned as text, never
  evaluated, executed, or interpreted as authorization.
- Generic agent tasks receive only two code-registered function definitions:
  `get_current_time` and `save_note`. It cannot supply a handler name, module,
  code, command, filesystem path, URL, or integration credential.
- Function arguments are untrusted. They must be valid JSON objects, pass a
  strict Pydantic schema, reject extra fields, and satisfy size/domain checks
  before a handler can see them. Unknown tools and invalid calls fail closed and
  remain auditable.
- Tool schemas must not accept API keys, passwords, tokens, or other credentials.
  Credentials belong in environment-backed provider configuration and are
  injected by trusted application code. Registry metadata supports declared
  sensitive fields, which are redacted from persisted arguments; no current
  tool has or needs a sensitive argument.
- `read_only` describes effect, not trust. Tool output is returned to the model
  as untrusted JSON. Registry validation permits automatic execution only for
  `read_only`; `local_write` and higher-impact classes require explicit approval.
- No shell, browser, hosted tools, MCP, dynamic imports, `eval`, arbitrary
  Python, or real external integrations are available.
- Persisted execution metadata is limited to model/provider/config names,
  timestamps, status, request/response identifiers, selected memory IDs/types,
  sanitized notification errors, and token usage. Prompts and memory content are
  not copied into execution metadata or logs.

Explicitly selected memory content is prompt context and is sent to OpenAI.
Memory is never selected merely because it exists: a task must provide memory
IDs, types, or tags. Selected memory is labelled untrusted reference data and
cannot grant permission, override higher-priority instructions, or authorize a
tool call.

Because OpenAI-side storage is disabled, a paused agent stores the minimum
Responses API continuation input in the task's private `agent_state`. This may
include the original instruction/context, model output items, and tool outputs.
It is required to resume after approval, is never included in `TaskRead`, and is
cleared on terminal completion or failure. Database access and backups must be
treated as sensitive.

## Manual Check-In Boundary

Manual `project_check_in` tasks snapshot only the requested enabled project-note
memories and supplied priorities. Input data and any relevant prior model result
are untrusted JSON context. Inputs cannot register tools, load files, grant
permission, execute recommendations, or cause memory writes. The check-in bypasses
the tool runtime; unexpected provider function calls fail closed. Its model and
result-validation errors use fixed safe diagnostics, without validation inputs or
provider exception bodies in logs/results. Recognized namespaced citations in
every prose field are validated as well as structured IDs. Existence of an ID
does not establish factual support for a claim.

Accepted task snapshots retain private note text after the source memory is
edited, disabled, or deleted. Protect task APIs, database access, backups, and
retention accordingly. Check-in metadata stores identity/hashes rather than a
second copy of note content. Generated summaries and recommendations remain task
results; no model inference is silently saved as a user preference. Explicit
notification policies authorize only the existing status-only message; a
recommendation-bearing push would require a separately reviewed content policy.

## Data and Error Handling

- PostgreSQL is authoritative; Redis data may be rebuilt or reconciled.
- Store only data required for current functionality.
- Memory may contain durable personal information. The memory API is
  unauthenticated in V1 and therefore must remain loopback-only. List and inspect
  endpoints return full content; database backups must be protected to the same
  standard.
- Memory source is a descriptive provenance label supplied by the caller, not a
  cryptographic identity or proof. Tags and source labels must not contain
  credentials.
- Disabling a memory prevents future selection while retaining it for inspection
  and possible re-enable. Deleting it removes the PostgreSQL row. Neither action
  can retract content already sent to OpenAI. A task paused for tool approval may
  temporarily retain selected content in private `agent_state` until that task
  reaches a terminal state.
- Agent output, task context, tool output, the `save_note` demonstration table,
  and task summaries are never remembered automatically. An explicit memory API
  write is required.
- Memory content and selected-memory context are not logged. Execution metadata
  records only selected IDs/types and counts, not copied content.
- Tool audit arguments contain validated action data and can still be personal
  or sensitive even when they contain no credentials. API access, logs, backups,
  and retention must be protected accordingly.
- API, task/RQ, scheduler, enqueue and notification boundaries use fixed errors
  and allowlisted operational metadata. Raw exception messages, provider bodies,
  SQL statements and exception chains are not persisted or logged. Failure
  metadata retains model/request/response IDs, numeric usage, timestamps and
  application-built provenance. Unknown exception fields are dropped.
- JSON logging replaces exception tracebacks with a fixed classification;
  task entry points also replace escaped exceptions before RQ stores/logs them.
  SQLAlchemy parameter hiding is defense in depth, not the diagnostic boundary.
- A failed terminal database transaction cannot persist its own failure. RQ
  records a safe job failure; stale-task reconciliation later marks check-ins
  uncertain or recovers generic work. Inspect task/job IDs and health to correlate.
- Backups and restore tests are required before Personal Dot stores important
  personal information.

## GitHub read boundary

[Repository inspection](github-inspection.md) authenticates only as the configured
personal-account App installation. Worker receives an owner-only RSA key as a
single read-only bind mount, runs as its non-root owner UID, and requests only
Contents/Metadata read tokens (one repository for inspection). API/scheduler do
not receive the key. Credentials never enter task inputs/results, URLs, logs or
model context. Fixed-origin HTTPS, refused redirects, bounded responses and safe
errors protect transport boundaries. No repository script or instruction runs;
source is untrusted evidence. Retained private repository text is sensitive even
after heuristic path/content secret exclusion. Discovery cannot expose private
repositories outside the installation grant. GitHub tasks cannot notify or be
scheduled and have no publishing methods.
