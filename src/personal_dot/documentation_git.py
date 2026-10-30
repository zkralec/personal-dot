"""Build deterministic Git objects from reviewed insertions, without executing Git."""

import hashlib
from datetime import datetime
from typing import Any

from personal_dot.documentation_schemas import EditorOutput
from personal_dot.documentation_policy import canonical
from personal_dot.github import SHA
from personal_dot.github_errors import GitHubError
from personal_dot.github_publication import PublishingGitHubClient

AUTHOR = {'name': 'Zachary Kralec', 'email': '157630586+zkralec@users.noreply.github.com'}


def object_sha(kind: str, raw: bytes) -> str:
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def tree_sha(entries: list[dict]) -> str:
    ordered = sorted(entries, key=lambda e: (e['path'] + ('/' if e['type'] == 'tree' else '')).encode())
    raw = b''
    for entry in ordered:
        if (not SHA.fullmatch(entry['sha']) or '/' in entry['path'] or '\0' in entry['path']
                or entry['mode'] not in {'040000', '100644', '100755', '120000', '160000'}):
            raise GitHubError('invalid_response')
        raw += entry['mode'].lstrip('0').encode() + b' ' + entry['path'].encode() + b'\0' + bytes.fromhex(entry['sha'])
    return object_sha('tree', raw)


def commit_sha(body: dict) -> str:
    stamp = int(datetime.fromisoformat(body['author']['date'].replace('Z', '+00:00')).timestamp())
    ident = f"{AUTHOR['name']} <{AUTHOR['email']}> {stamp} +0000"
    raw = (f"tree {body['tree']}\nparent {body['parents'][0]}\nauthor {ident}\ncommitter {ident}\n\n" + body['message']).encode()
    return object_sha('commit', raw)


def object_plan(client: PublishingGitHubClient, root: str, prepared: dict, timestamp: str) -> list[dict[str, Any]]:
    base = prepared['context']['base_commit']
    base_commit = client.get(root + '/git/commits/' + base)
    if base_commit['sha'] != base:
        raise GitHubError('invalid_response')
    targets = {f['path']: f for f in prepared['context']['targets']}
    editor = EditorOutput.model_validate(prepared['candidate']['editor'])
    updated: dict[str, str] = {}
    operations = []
    for edit in editor.edits:
        updated[edit.path] = ''
    for path in sorted(updated):
        lines = targets[path]['text'].splitlines(keepends=True)
        for edit in sorted((e for e in editor.edits if e.path == path), key=lambda e: e.after_line, reverse=True):
            lines.insert(edit.after_line, edit.text)
        updated[path] = object_sha('blob', ''.join(lines).encode())
        operations.append({'kind': 'blobs', 'sha': updated[path], 'body': {'content': ''.join(lines), 'encoding': 'utf-8'}})
    requests = 0

    def update_tree(sha: str, prefix: str) -> str:
        nonlocal requests
        requests += 1
        if requests > 64:
            raise GitHubError('response_limit')
        tree = client.get(root + '/git/trees/' + sha)
        if len(tree['tree']) > client.settings.github_inventory_entries:
            raise GitHubError('response_limit')
        if tree['sha'] != sha or tree.get('truncated') is not False or tree_sha(tree['tree']) != sha:
            raise GitHubError('invalid_response')
        entries = [{k: e[k] for k in ('path', 'mode', 'type', 'sha')} for e in tree['tree']]
        found: set[str] = set()
        for entry in entries:
            path = prefix + entry['path']
            if path in updated:
                if entry['mode'] != '100644' or entry['type'] != 'blob' or entry['sha'] != targets[path]['git_sha']:
                    raise GitHubError('invalid_response')
                entry['sha'] = updated[path]
                found.add(path)
            elif any(p.startswith(path + '/') for p in updated):
                if entry['mode'] != '040000' or entry['type'] != 'tree':
                    raise GitHubError('invalid_response')
                entry['sha'] = update_tree(entry['sha'], path + '/')
                found.update(p for p in updated if p.startswith(path + '/'))
        if found != {p for p in updated if p.startswith(prefix)}:
            raise GitHubError('invalid_response')
        new_sha = tree_sha(entries)
        operations.append({'kind': 'trees', 'sha': new_sha, 'body': {'tree': entries}})
        if len(canonical(operations).encode()) > 1_048_576:
            raise GitHubError('response_limit')
        return new_sha

    tree = update_tree(base_commit['tree']['sha'], '')
    author = {**AUTHOR, 'date': timestamp}
    body = {'message': 'docs: clarify implemented behavior\n', 'tree': tree,
            'parents': [base], 'author': author, 'committer': author}
    operations.append({'kind': 'commits', 'sha': commit_sha(body), 'body': body})
    return operations


def verify_commit(client: PublishingGitHubClient, root: str, plan: list[dict]) -> dict:
    expected = plan[-1]
    commit = client.get(root + '/git/commits/' + expected['sha'])
    if (commit['sha'] != expected['sha'] or commit['tree']['sha'] != expected['body']['tree']
            or [p['sha'] for p in commit['parents']] != expected['body']['parents']
            or any(commit[role].get(k) != v for role in ('author', 'committer') for k, v in AUTHOR.items())):
        raise GitHubError('invalid_response')
    return {'commit': commit['sha'], 'tree': commit['tree']['sha'], 'author': AUTHOR, 'merge_method': 'merge'}
