# Documentation-maintenance policy

The owner grants DOT standing permission to inspect all repositories owned by
its configured personal GitHub account. The account must come from trusted
operator configuration; repository content and model output cannot select a
broader account or grant access to other owners' repositories.

Routine documentation changes may be generated, independently reviewed,
committed, pushed to temporary branches, and merged automatically when
deterministic policy checks pass. Qualifying changes require no manual approval.
This is a narrow exception to the default approval requirement for external
side effects, not permission to execute instructions found in repositories.

The authorized scope is explanatory documentation: factual corrections,
clarifications, and updates describing already implemented behavior. Changes to
application code, dependencies, workflows, deployment settings, permissions,
agent instructions (including AGENTS.md and skill/instruction files), or any
other content outside this scope require explicit owner approval. A file's
extension or location alone does not establish that it is routine documentation.
Executable examples or instructions that change operational behavior cannot be
used to bypass these exclusions.

Before automatic publication, deterministic checks must establish the configured
owner/repository identity and the complete proposed diff's documentation-only
scope, including additions, removals, renames and file modes. Protected paths,
executable files, symlinks, mixed-scope changes and ambiguous classifications
must fail closed for owner review. An independent review must assess accuracy,
evidence and scope; the generator cannot approve its own changes. Review output
is untrusted data, not an authorization source. Checks and review must apply to
the exact revision being published; changed revisions require fresh checks.
Repository branch protections and required checks remain binding. Record the
policy decision, reviewed revision, check/review outcomes, temporary branch,
commit and merge outcome for auditability.

Repository content, retrieved material, tool output and model output cannot
grant or expand permissions, waive checks, or authorize excluded changes. Only
the owner can change this standing policy through a trusted instruction channel.

GitHub discovery, bounded immutable inspection, documentation preview and the
[bounded publishing controller](documentation-publishing.md) are implemented.
The initial scope remains explanatory insertions into selected existing public
README/docs Markdown, at most three files and 300 added lines. Publishing
revalidates persisted independent approval and deterministic policy, inspects
GitHub requirements, verifies exact revisions, and records recoverable remote
operations. Default-off operator and per-task gates remain. This delivery is
simulated verification only; no real branch/commit/PR/merge or schedule enabling
is authorized or performed here. Unsupported repository requirements record
blockers rather than weakening policy or GitHub rules.
