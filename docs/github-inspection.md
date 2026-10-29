# Read-only GitHub discovery and inspection

This milestone adds `github_discover` and `github_inspect` to the existing task
API, worker and PostgreSQL task history. No separate interface or repository
allowlist exists. All repositories accessible to the installation and owned by
the explicitly configured personal account can be selected. These tasks never
call models, execute repository files, write memories, notify, publish, or merge.
They cannot be scheduled. The existing loopback-only, unauthenticated task API
returns private evidence: keep it local and protect PostgreSQL and backups.

## GitHub App and key setup

Use a GitHub App installed on the **personal User account**, with repository
permission **Contents: Read-only** and automatically granted **Metadata: Read-only**.
No account, organization, workflow, pull-request, webhook or write permission is
needed. Select **All repositories** in the installation settings to include all
currently accessible personally owned repositories and future additions. A
selected-repository installation can only expose its granted subset; DOT reports
`repository_selection` and cannot discover private repositories outside that
access. It never changes installation permissions or repository selection.

Configured owner-supplied identifiers for this installation:

```dotenv
GITHUB_OWNER=zkralec
GITHUB_APP_ID=5519145
GITHUB_INSTALLATION_ID=176370838
GITHUB_APP_PRIVATE_KEY_HOST_PATH=/home/zkralec/.config/personal-dot/secrets/github-app.pem
DOT_GITHUB_UID=1000
DOT_GITHUB_GID=1000
COMPOSE_FILE=compose.yaml:compose.github.yaml
```

Add these settings to the existing **ignored** `.env`, preserving its database
and provider settings, and keep `.env` at `0600`. Do not put PEM contents, JWTs,
installation tokens, or token-bearing URLs in that file, commands, tasks or Git.
The original private key stays outside the checkout. The secrets directory
should be owner-only (`0700`); the key must be a regular, unencrypted RSA PEM,
at least 2048 bits, owned by the worker UID and mode `0400` or `0600`. Symlinks,
group/world-readable keys, missing files and invalid keys fail with fixed errors.
Determine UID/GID with `stat -c '%u:%g' /absolute/path/to/key.pem`; the configured
values above match this host. No key replacement or rotation is automatic.

`compose.github.yaml` mounts only that individual file into **worker**, read-only,
at **`/run/secrets/github-app.pem`**, and sets its
`GITHUB_APP_PRIVATE_KEY_PATH` accordingly. `create_host_path: false` prevents
Docker silently making a directory when the source is missing. Worker runs as
the non-root file-owner UID/GID, so its original owner-only permissions need not
be broadened. API, scheduler, migrate and test receive no key mount. Recreate
application services using the documented backup/maintenance procedure whenever
runtime/schema changes require it. With `COMPOSE_FILE` in `.env`, ordinary
`docker compose` commands use the override; equivalently use:

```bash
docker compose -f compose.yaml -f compose.github.yaml up -d --no-deps --no-build worker
docker compose exec -T worker python -c \
  'from personal_dot.config import get_settings; from personal_dot.github import private_key; private_key(get_settings().github_app_private_key_path); print("Worker key is readable and valid")'
```

For a non-Docker worker, set the same owner/app/installation identifiers and
`GITHUB_APP_PRIVATE_KEY_PATH` to the protected absolute host key path; run as its
owner. `GITHUB_APP_PRIVATE_KEY_HOST_PATH`, `DOT_GITHUB_UID/GID` and `COMPOSE_FILE`
are Compose settings, not application secrets. Commit author Zachary Kralec
(`157630586+zkralec@users.noreply.github.com`) is owner-supplied future publishing
configuration; this read-only implementation does not use or configure it.

DOT signs an RS256 JWT (`iat` backdated 60 seconds, expiration 9 minutes ahead),
reads the configured installation and verifies its app ID, installation ID,
User owner login/ID and suspension/Contents permission state before issuing an
installation token. It explicitly requests **only contents/metadata read**, even
if the App has broader permissions; inspection also limits the token to the
selected repository. Tokens remain process-local, are refreshed before expiry
and are never persisted or included in results, URLs, logs or model context.
Only `https://api.github.com` is used, without environment proxy inheritance,
redirect following, provider retries or arbitrary pagination URLs. The sole POST
is the installation-token exchange; repository operations are GET requests.
See GitHub's official [JWT guidance](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)
and [installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation).

## Existing task API

List accessible personally owned repositories (asynchronous, persisted task):

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"type":"github_discover","payload":{}}'
# Read the returned task ID; do not resubmit just because work is still queued.
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/TASK_ID
```

After the task succeeds, list just eligible entries using the existing read API:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/TASK_ID | python3 -c \
  'import json,sys; t=json.load(sys.stdin); print(json.dumps([r for r in t["result"]["repositories"] if r["maintenance_eligible"]], indent=2))'
```

`result.repositories` contains safe identity fields, default branch, private/fork/
archived flags, `classification` and `maintenance_eligible`. Forks remain eligible
when otherwise supported; archived repositories are inspectable but not eligible
for maintenance, disabled/unsupported ones are classified without text collection.
A zero GitHub size is `empty_candidate`, not proof of emptiness; inspection
confirms `empty` only when GitHub reports no commit. A selected missing/ungranted
repository fails with `execution_metadata.github.error_code=inaccessible`.
Foreign owners are excluded and counted. Discovery has
`coverage=installation_accessible_only`: it cannot enumerate unseen private
repositories and does not claim they are absent.

Pagination uses numeric pages of 100. `complete` means the requested page range
was exhausted consistently, not a transactionally stable account-wide inventory.
If `next_page` is present, continue with a new discovery task, for example
`{"type":"github_discover","payload":{"page":101}}`, and combine results by ID.
`page` defaults to 1; `reported_total` is GitHub's observation, not proof against
concurrent additions/deletions. Repeat discovery after installation changes.
If `complete=false` has no continuation, pagination changed during collection;
repeat from page 1. There is no permanent per-repository enable step.

Inspect exactly one selected repository name, under the configured owner:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"type":"github_inspect","payload":{"repository":"personal-dot"}}'
curl --fail-with-body -sS http://127.0.0.1:8000/tasks/TASK_ID
```

Do not supply an owner, URL, credentials, branch, filesystem path or executable
instructions. Notifications must remain `none`. PostgreSQL serializes inspection
with a transaction advisory lock across collection; a competing task fails with
`overlap` before authenticating. Submit one at a time. Duplicate queue deliveries
and late completion retain the existing execution-ownership protections. Read
recovery remains at least once; an interrupted attempt may resolve a newer head
on recovery. A completed snapshot is never refreshed silently.

## Snapshot bounds and exclusions

Inspection resolves the default branch once to a commit SHA and root tree SHA.
Subsequent tree/blob reads use only immutable Git SHAs, never mutable Contents
URLs, raw download links, clones, submodules or Git LFS downloads. Blob size and
Git object SHA-1 are verified; selected UTF-8 text also gets a SHA-256 hash.
`repository`, `commit`, `tree_sha`, `captured_at`, policy version, limits,
`inventory`, selected `files`, `context_bytes`, `files_read`, `exclusions` and
`inventory_complete` record the observed evidence. No repository metadata URL or
unbounded provider body is retained. File text is explicitly untrusted evidence;
embedded instructions do not grant permission or alter DOT's policy.

Trusted worker environment settings and defaults (also forwarded by the optional
override):

| Setting | Default | Bound |
| --- | ---: | --- |
| `GITHUB_TIMEOUT_SECONDS` | 15 | per HTTP operation, no retries |
| `GITHUB_RESPONSE_BYTES` | 2097152 | decompressed JSON response bytes |
| `GITHUB_MAX_PAGES` | 100 | discovery pages per task, continuation returned |
| `GITHUB_INVENTORY_ENTRIES` | 2000 | encountered entries, including exclusions |
| `GITHUB_TREE_REQUESTS` | 64 | nonrecursive tree requests |
| `GITHUB_MAX_FILES` | 40 | downloaded blobs, including rejected contents |
| `GITHUB_FILE_BYTES` | 65536 | raw bytes per selected candidate |
| `GITHUB_CONTEXT_BYTES` | 262144 | UTF-8 bytes of compact selected-files JSON, including text/path/hash overhead |

Files are not truncated to fit: oversized files and further files are excluded.
Incomplete trees and unvisited subtrees are reported explicitly. Collection
prioritizes README, docs, manifests, then source text from a fixed extension
allowlist. Inventory traversal and text selection are bounded, not exhaustive
semantic dependency analysis. Giant individual API responses fail safely at the
response cap; no archive fallback downloads the entire repository.

Credential paths (`.env*`, credentials, secrets, key/token files and hidden
credential directories), binary/unsupported extensions, generated/vendor/build
content, executable modes, symlinks, submodules and agent-instruction files are
excluded. Unsafe absolute/traversal/encoded/control/non-ASCII/overlong paths are
not fetched; only their path hash and fixed reason are retained. Known secret
formats, private-key material, literal credential assignments, invalid UTF-8 and
binary controls cause whole-file exclusion before persistence. Detection is
conservative and heuristic: arbitrary unlabelled secrets cannot be guaranteed
absent, and useful example/configuration text can be excluded. Protect retained
private source text as sensitive data. No secret text is retained in exclusion
records or diagnostics. No scripts, hooks, builds or repository instructions run.

Errors distinguish missing/unreadable/insecure/invalid key configuration,
installation mismatch/suspension, missing Contents permission, rejected auth,
forbidden/missing resources, rate limits, transport/timeouts, redirects, malformed
or oversized responses and concurrent inspection. Messages are fixed; provider
response bodies, headers, token values and exception chains are not diagnostics.
Failed tasks remain PostgreSQL records. Inspect the fixed task error/code and
GitHub App settings; do not automatically rotate credentials or expand access.

Publishing, deterministic change-policy enforcement, independent review,
commit/PR/merge automation and schedules remain future milestones. No live model
quality, exhaustive secret detection, host-crash recovery or exactly-once
execution is established by repository snapshots.
