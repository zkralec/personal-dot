"""GitHub publication adapter. No credentials, URLs or transport enter model input."""

import time
from typing import Any
from urllib.parse import quote

from personal_dot.github import GitHubClient
from personal_dot.github_errors import GitHubError


class PublishingGitHubClient(GitHubClient):
    # Administration read is necessary to distinguish legacy branch protection.
    permissions = {'contents': 'write', 'pull_requests': 'write', 'metadata': 'read',
                   'administration': 'read', 'checks': 'read', 'statuses': 'read'}

    def _allowed(self, method: str, path: str) -> bool:
        if super()._allowed(method, path):
            return True
        if not self._repository or self.permissions.get('contents') != 'write':
            return False
        root = f'/repos/{self.settings.github_owner}/{self._repository}'
        suffix = path.removeprefix(root)
        if path == root + suffix:
            if method == 'POST':
                return suffix in {'/git/blobs', '/git/trees', '/git/commits', '/git/refs', '/pulls'}
            if method == 'PUT':
                return suffix.startswith('/pulls/') and suffix.endswith('/merge') and suffix[7:-6].isdigit()
            if method == 'DELETE':
                return suffix.startswith('/git/refs/heads/dot/docs-')
        return False

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        if self._token is None or time.time() >= self._expires - 60:
            self.authenticate(self._repository)
        assert self._token is not None
        return self._request(method, path, self._token.get_secret_value(), body=body)

    def optional(self, path: str) -> dict | None:
        try:
            value = self.request('GET', path)
        except GitHubError as exc:
            if exc.code == 'inaccessible':
                return None
            raise
        if not isinstance(value, dict):
            raise GitHubError('invalid_response')
        return value

    def listing(self, path: str) -> list[dict]:
        """One bounded page, plus a sentinel page to reject incomplete evidence."""
        join = '&' if '?' in path else '?'
        data = self.request('GET', path + join + 'per_page=100&page=1')
        if not isinstance(data, list) or len(data) > 100 or any(not isinstance(x, dict) for x in data):
            raise GitHubError('invalid_response')
        if len(data) == 100 and self.request('GET', path + join + 'per_page=100&page=2'):
            raise GitHubError('response_limit')
        return data

    def requirements(self, root: str, branch: str, temporary: str) -> dict[str, Any]:
        current = self.get(root + '/branches/' + quote(branch, safe=''))
        rules = self.listing(root + '/rules/branches/' + quote(branch, safe=''))
        temp_rules = self.listing(root + '/rules/branches/' + quote(temporary, safe=''))
        # Missing/forbidden protection evidence is a blocker, never inferred absent.
        protection = self.get(root + '/branches/' + quote(branch, safe='') + '/protection') if current['protected'] else {}
        return {'base_sha': current['commit']['sha'], 'rules': rules,
                'temporary_rules': temp_rules, 'protection': protection}


def merge_requirements(requirements: dict[str, Any], repository: dict[str, Any]) -> tuple[list[str], list[dict]]:
    """Conservative supported subset; unknown rules cannot silently grant permission."""
    blockers: set[str] = set()
    checks: list[dict] = []
    if repository.get('allow_merge_commit') is not True:
        blockers.add('merge_commit_required_for_attribution')
    for rule in requirements['temporary_rules']:
        if rule['type'] not in {'deletion', 'non_fast_forward'}:
            blockers.add('temporary_branch_rule:' + rule['type'])
    for rule in requirements['rules']:
        kind, params = rule['type'], rule.get('parameters', {})
        if kind in {'deletion', 'non_fast_forward'}:
            continue
        if kind == 'pull_request':
            if params.get('required_approving_review_count', 0) or params.get('require_code_owner_review'):
                blockers.add('github_approving_review_required')
            if params.get('required_review_thread_resolution'):
                blockers.add('conversation_resolution_unsupported')
            if params.get('allowed_merge_methods') is not None and 'merge' not in params['allowed_merge_methods']:
                blockers.add('merge_commit_required_for_attribution')
            supported = {'required_approving_review_count', 'require_code_owner_review',
                         'dismiss_stale_reviews_on_push', 'require_last_push_approval',
                         'required_review_thread_resolution', 'allowed_merge_methods',
                         'require_extra_approval_for_unattributed_changes'}
            if set(params) - supported or params.get('require_last_push_approval'):
                blockers.add('review_requirement_unsupported')
        elif kind == 'required_status_checks':
            supported = {'required_status_checks', 'strict_required_status_checks_policy', 'do_not_enforce_on_create'}
            if set(params) - supported:
                blockers.add('status_requirement_unsupported')
            checks.extend(params['required_status_checks'])
        else:
            blockers.add('unsupported_rule:' + kind)
    protection = requirements['protection']
    supported_protection = {'url', 'enabled', 'required_status_checks', 'required_pull_request_reviews',
        'enforce_admins', 'restrictions', 'required_signatures', 'required_linear_history',
        'allow_force_pushes', 'allow_deletions', 'block_creations', 'required_conversation_resolution',
        'lock_branch', 'allow_fork_syncing'}
    if set(protection) - supported_protection:
        blockers.add('unknown_legacy_protection')
    if protection.get('block_creations', {}).get('enabled'):
        blockers.add('branch_restriction:block_creations')
    reviews = protection.get('required_pull_request_reviews') or {}
    if reviews.get('required_approving_review_count', 0) or reviews.get('require_code_owner_reviews'):
        blockers.add('github_approving_review_required')
    if reviews.get('require_last_push_approval'):
        blockers.add('review_requirement_unsupported')
    for key in ('restrictions', 'required_signatures', 'required_linear_history',
                'required_conversation_resolution', 'lock_branch'):
        value = protection.get(key)
        if (key == 'restrictions' and value is not None) or value and (not isinstance(value, dict) or value.get('enabled', True)):
            blockers.add('branch_restriction:' + key)
    # Do not rely on bypass privileges, even if the installation possesses them.
    if reviews.get('bypass_pull_request_allowances') and any(reviews['bypass_pull_request_allowances'].values()):
        blockers.add('review_bypass_unsupported')
    status = protection.get('required_status_checks') or {}
    checks.extend({'context': c['context'], 'integration_id': c.get('app_id')}
                  for c in status.get('checks', []))
    known = {c['context'] for c in checks}
    checks.extend({'context': c, 'integration_id': None} for c in status.get('contexts', []) if c not in known)
    return sorted(blockers), checks


def check_evidence(client: PublishingGitHubClient, root: str, sha: str, required: list[dict]) -> tuple[list[str], dict]:
    statuses = client.listing(root + f'/commits/{sha}/statuses')
    runs = client.get(root + f'/commits/{sha}/check-runs?per_page=100')
    if runs['total_count'] != len(runs['check_runs']) or len(runs['check_runs']) > 100:
        raise GitHubError('response_limit')
    blockers: set[str] = set()
    # Latest status for each context; GitHub returns newest first.
    latest: dict[str, dict] = {}
    for status in statuses:
        latest.setdefault(status['context'], status)
    for status in latest.values():
        if status['state'] != 'success':
            blockers.add('checks_pending_or_failed')
    for run in runs['check_runs']:
        if run.get('head_sha') != sha:
            blockers.add('check_head_changed')
        if run['status'] != 'completed' or run.get('conclusion') not in {'success', 'neutral', 'skipped'}:
            blockers.add('checks_pending_or_failed')
    for requirement in required:
        context, app = requirement['context'], requirement.get('integration_id')
        matching = [r for r in runs['check_runs'] if r['name'] == context
                    and (app in {None, -1} or r['app']['id'] == app)]
        status = latest.get(context)
        # Statuses do not expose an App identity. A pinned provider must have a check run.
        if not matching and not (app in {None, -1} and status and status['state'] == 'success'):
            blockers.add('required_check_missing')
    evidence = {'head_sha': sha, 'statuses': [{k: s.get(k) for k in ('id', 'context', 'state', 'updated_at')} for s in latest.values()],
                'check_runs': [{k: r.get(k) for k in ('id', 'name', 'head_sha', 'app', 'status', 'conclusion', 'completed_at')} for r in runs['check_runs']]}
    return sorted(blockers), evidence
