"""Bounded evidence collection; repository bytes are never executable authority."""

import base64
import hashlib
import json
import re
from collections import deque
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from personal_dot.github import GitHubClient, SHA, repository_name
from personal_dot.github_errors import GitHubError

POLICY = "github-inspection-v1"
SKIP_DIRS = frozenset({'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', 'vendor',
    'dist', 'build', 'generated', '__pycache__', '.next', '.nuxt', 'coverage', 'target',
    'secrets', 'credentials', 'workflows', 'site-packages'})
TEXT_SUFFIXES = frozenset({'.md', '.rst', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx',
    '.go', '.rs', '.rb', '.java', '.c', '.h', '.cpp', '.toml'})
MANIFESTS = frozenset({'package.json', 'go.mod', 'cargo.toml', 'pyproject.toml'})
SECRET_NAMES = re.compile(r"(?i)(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pypirc|id_rsa.*|id_ed25519.*|credentials.*|secrets?.*|token.*|.*\.(?:pem|key|p12|pfx|keystore))")
SECRET_CONTENT = re.compile(
    r"(?i:(?:password|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)['\"]?\s*[:=]\s*['\"][^'\"\r\n]+['\"])|"
    r"-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----|"
    r"\bgh[pousr]_[A-Za-z0-9_]{16,}|\bgithub_pat_[A-Za-z0-9_]{16,}|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9_-]{20,}|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
    r"(?i:(?:password|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_+/=-]{12,})"
)


def safe_path(path: str) -> bool:
    return (0 < len(path.encode('utf-8')) <= 512 and not path.startswith('/')
            and '\\' not in path and '%' not in path and ':' not in path
            and all(32 <= ord(c) < 127 for c in path)
            and all(part not in {'', '.', '..'} for part in path.split('/')))


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise GitHubError('invalid_response')
    return value


def identity(raw: dict[str, Any], client: GitHubClient) -> dict[str, Any]:
    owner = raw.get('owner', {})
    if (not isinstance(owner, dict) or owner.get('id') != client.installation['owner_id']
            or str(owner.get('login', '')).lower() != client.settings.github_owner.lower()
            or owner.get('type') != 'User'):
        raise GitHubError('installation_mismatch')
    try:
        name = repository_name(raw['name'])
        if type(raw['id']) is not int or raw['id'] <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise GitHubError('invalid_response') from None
    classification = ('disabled' if raw.get('disabled') else 'archived' if raw.get('archived')
                      else 'unsupported' if not raw.get('default_branch')
                      else 'empty_candidate' if raw.get('size') == 0
                      else 'fork' if raw.get('fork') else 'eligible')
    branch = raw.get('default_branch')
    if branch is not None and (not isinstance(branch, str) or len(branch) > 255
                              or not re.fullmatch(r'[A-Za-z0-9_./-]+', branch)
                              or any(p in {'', '.', '..'} for p in branch.split('/'))):
        classification, branch = 'unsupported', None
    return {'id': raw['id'], 'owner': client.settings.github_owner,
            'owner_id': owner['id'], 'name': name, 'default_branch': branch,
            'private': bool(raw.get('private')), 'fork': bool(raw.get('fork')),
            'archived': bool(raw.get('archived')), 'classification': classification,
            'maintenance_eligible': classification in {'eligible', 'fork', 'empty_candidate'}}


def discover(client: GitHubClient, page: int = 1) -> dict[str, Any]:
    client.authenticate()
    repositories: dict[int, dict[str, Any]] = {}
    excluded_owner_count = 0
    seen = (page - 1) * 100
    complete = False
    next_page: int | None = page
    total = 0
    consistent = True
    for current in range(page, page + client.settings.github_max_pages):
        data = client.get(f'/installation/repositories?per_page=100&page={current}')
        batch = data.get('repositories')
        total = data.get('total_count')
        if not isinstance(batch, list) or len(batch) > 100 or type(total) is not int or total < 0:
            raise GitHubError('invalid_response')
        for raw in batch:
            if not isinstance(raw, dict):
                raise GitHubError('invalid_response')
            owner = raw.get('owner', {})
            if not isinstance(owner, dict) or str(owner.get('login', '')).lower() != client.settings.github_owner.lower():
                excluded_owner_count += 1
                continue
            repo = identity(raw, client)
            if repo['id'] in repositories:
                consistent = False
            repositories[repo['id']] = repo
        seen += len(batch)
        next_page = current + 1
        if seen >= total:
            complete, next_page = consistent, None
            break
        if not batch:
            break  # Concurrent changes/invalid pagination; never claim complete.
    return {'policy_version': POLICY, 'installation': client.installation,
            'captured_at': datetime.now(UTC).isoformat(),
            'coverage': 'installation_accessible_only', 'complete': complete,
            'next_page': next_page, 'reported_total': total,
            'excluded_owner_count': excluded_owner_count,
            'repositories': sorted(repositories.values(), key=lambda r: r['name'].lower())}


def _priority(path: str) -> tuple[int, str]:
    name = PurePosixPath(path).name.lower()
    return (0 if name.startswith('readme') else 1 if path.lower().startswith(('docs/', 'doc/'))
            else 2 if name in MANIFESTS else 3, path)


def _reason(path: str, item: dict[str, Any]) -> str | None:
    parts = path.lower().split('/')
    if any(SECRET_NAMES.fullmatch(part) for part in parts):
        return 'secret_path'
    if any(part in SKIP_DIRS or (part.startswith('.') and part != '.github') for part in parts):
        return 'generated_vendor_or_hidden'
    if item.get('mode') == '120000':
        return 'symlink'
    if item.get('mode') == '160000' or item.get('type') == 'commit':
        return 'submodule'
    if item.get('type') == 'tree' and item.get('mode') == '040000':
        return None
    if item.get('type') != 'blob' or item.get('mode') != '100644':
        return 'unsupported_file_mode'
    name = parts[-1]
    if name in {'agents.md', 'skill.md'}:
        return 'agent_instructions'
    if name.endswith(('.min.js', '.map', '.lock')):
        return 'generated_vendor_or_hidden'
    if PurePosixPath(name).suffix not in TEXT_SUFFIXES and name not in MANIFESTS and name not in {'license', 'copying', 'readme'}:
        return 'unsupported_or_binary_extension'
    return None


def inspect_repository(client: GitHubClient, repository: str) -> dict[str, Any]:
    repository_name(repository)
    client.authenticate(repository)
    base = f'/repos/{client.settings.github_owner}/{repository}'
    repo = identity(client.get(base), client)
    if repo['name'].lower() != repository.lower():
        raise GitHubError('installation_mismatch')
    result: dict[str, Any] = {'policy_version': POLICY, 'installation': client.installation,
        'repository': repo, 'captured_at': datetime.now(UTC).isoformat(),
        'commit': None, 'tree_sha': None, 'inventory_complete': True,
        'inventory': [], 'files': [], 'exclusions': [], 'context_bytes': 2,
        'files_read': 0, 'trust': 'untrusted_repository_evidence',
        'limits': {key: getattr(client.settings, 'github_' + key) for key in
                   ('inventory_entries', 'tree_requests', 'max_files', 'file_bytes', 'context_bytes')}}
    if repo['classification'] in {'unsupported', 'disabled'}:
        result['exclusions'].append({'reason': repo['classification']})
        return result
    try:
        commit = client.get(base + '/commits/' + quote(repo['default_branch'], safe=''))
    except GitHubError as exc:
        if exc.code != 'empty':
            raise
        repo.update(classification='empty', maintenance_eligible=False)
        result['exclusions'].append({'reason': 'empty'})
        return result
    result['commit'] = _sha(commit.get('sha'))
    try:
        root = _sha(commit['commit']['tree']['sha'])
    except (KeyError, TypeError):
        raise GitHubError('invalid_response') from None
    result['tree_sha'] = root
    pending = deque([('', root)])
    entries: list[dict[str, Any]] = result['inventory']
    requests = 0
    while pending and len(entries) < client.settings.github_inventory_entries and requests < client.settings.github_tree_requests:
        prefix, tree_sha = pending.popleft()
        data = client.get(base + '/git/trees/' + tree_sha)
        requests += 1
        tree = data.get('tree')
        if not isinstance(tree, list) or data.get('truncated') is not False:
            result['inventory_complete'] = False
            result['exclusions'].append({'path': prefix or '.', 'reason': 'truncated_tree'})
            continue
        if data.get('sha') != tree_sha:
            raise GitHubError('invalid_response')
        # GitHub order is not policy: prioritize documentation deterministically.
        if any(not isinstance(item, dict) or not isinstance(item.get('path'), str) for item in tree):
            raise GitHubError('invalid_response')
        for index, item in enumerate(sorted(tree, key=lambda i: _priority(i['path']))):
            if len(entries) >= client.settings.github_inventory_entries:
                result['inventory_complete'] = False
                result['exclusions'].append({'path': prefix or '.', 'reason': 'inventory_limit',
                                             'remaining_entries': len(tree) - index})
                break
            local = item['path']
            path = prefix + local
            if '/' in local or not safe_path(path):
                entries.append({'path_sha256': hashlib.sha256(path.encode()).hexdigest(), 'decision': 'unsafe_path'})
                continue
            entry = {'path': path, 'git_sha': _sha(item.get('sha')),
                     'mode': item.get('mode'), 'type': item.get('type')}
            entries.append(entry)
            reason = _reason(path, item)
            if reason:
                entry['decision'] = reason
            elif item['type'] == 'tree':
                entry['decision'] = 'directory'
                pending.append((path + '/', entry['git_sha']))
            else:
                size = item.get('size')
                if type(size) is not int or size < 0:
                    raise GitHubError('invalid_response')
                entry['bytes'] = size
                entry['decision'] = 'file_size_limit' if size > client.settings.github_file_bytes else 'candidate'
    if pending:
        result['inventory_complete'] = False
        for prefix, _ in pending:
            result['exclusions'].append({'path': prefix, 'reason': 'inventory_or_tree_request_limit'})
    for entry in sorted(entries, key=lambda e: _priority(e.get('path', ''))):
        if entry['decision'] != 'candidate':
            continue
        if result['files_read'] >= client.settings.github_max_files:
            entry['decision'] = 'file_count_limit'
            continue
        cap = ((entry['bytes'] + 2) // 3) * 4 + 16_384
        result['files_read'] += 1
        blob = client.get(base + '/git/blobs/' + entry['git_sha'], limit=cap)
        try:
            if blob['encoding'] != 'base64' or blob['sha'] != entry['git_sha'] or blob['size'] != entry['bytes']:
                raise ValueError
            content = base64.b64decode(''.join(blob['content'].splitlines()), validate=True)
            if len(content) != entry['bytes'] or len(content) > client.settings.github_file_bytes:
                raise ValueError
            git_hash = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            if git_hash != entry['git_sha']:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise GitHubError('invalid_response') from None
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            entry['decision'] = 'binary_or_non_utf8'
            continue
        if any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            entry['decision'] = 'binary_or_non_utf8'
            continue
        if SECRET_CONTENT.search(text):
            entry['decision'] = 'sensitive_content'
            continue
        selected = {'path': entry['path'], 'git_sha': entry['git_sha'],
                    'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'text': text}
        context_bytes = len(json.dumps(result['files'] + [selected], ensure_ascii=False, separators=(',', ':')).encode())
        if context_bytes > client.settings.github_context_bytes:
            entry['decision'] = 'total_context_limit'
            continue
        result['files'].append(selected)
        result['context_bytes'] = context_bytes
        entry['decision'] = 'selected'
    result['exclusions'].extend({k: v for k, v in entry.items() if k != 'text'}
                                for entry in entries if entry['decision'] not in {'selected', 'directory'})
    return result
