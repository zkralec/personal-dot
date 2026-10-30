"""Simulated GitHub HTTP service plus real PostgreSQL/RQ; never a live write."""

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import httpx
import pytest
from sqlalchemy import select

from personal_dot import documentation_publish as publishing, jobs
from personal_dot.config import Settings, get_settings
from personal_dot.db import SessionLocal
from personal_dot.documentation_git import AUTHOR, commit_sha, object_sha, tree_sha
from personal_dot.documentation_policy import digest
from personal_dot.github_errors import GitHubError
from personal_dot.github_publication import PublishingGitHubClient
from personal_dot.models import DocumentationPublication, Task, TaskStatus, TaskType
from personal_dot.notification_delivery import deliver_notification
from tests.test_documentation_preview import (COMMIT, TARGET, Models, create_inspection, run_preview, snapshot_file)
from tests.test_github import OWNER, key_file
from tests.test_tasks import run_queued_jobs
from tests.test_execution_reliability import scheduler


class GitHubService:
    def __init__(self):
        self.requests = []
        self.writes = []
        self.permissions = PublishingGitHubClient.permissions
        self.repo = {'id': 11, 'name': 'fixture', 'owner': OWNER, 'default_branch': 'main',
                     'private': False, 'size': 1, 'allow_merge_commit': True}
        entry = {'path': 'README.md', 'mode': '100644', 'type': 'blob', 'sha': snapshot_file('README.md', TARGET)['git_sha']}
        root = tree_sha([entry])
        self.objects = {'trees': {root: {'sha': root, 'tree': [entry], 'truncated': False}},
                        'blobs': {}, 'commits': {COMMIT: {'sha': COMMIT, 'tree': {'sha': root}}}}
        self.refs = {}
        self.base = COMMIT
        self.pr = None
        self.rules = []
        self.temp_rules = []
        self.protection = {}
        self.statuses = []
        self.runs = []
        self.reviews = []
        self.mergeable_state = 'clean'
        self.changed_files = False
        self.timeout_after = None
        self.timeout_before = None
        self.callback = None
        self.permission_failure = False

    def __call__(self, request):
        self.requests.append(request)
        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.content and request.content != b'null' else None
        if path == '/app/installations/176370838':
            return httpx.Response(200, json={'id': 176370838, 'app_id': 5519145,
                'account': OWNER, 'permissions': self.permissions, 'repository_selection': 'all', 'suspended_at': None})
        if path.endswith('/access_tokens'):
            assert body['repositories'] == ['fixture']
            assert set(body['permissions']) == set(self.permissions)
            return httpx.Response(201, json={'token': 'ghs_synthetic_publication_secret',
                'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat(), 'permissions': body['permissions']})
        assert request.headers['authorization'] == 'Bearer ghs_synthetic_publication_secret'
        suffix = path.removeprefix('/repos/zkralec/fixture')
        assert suffix != path
        key = method + ' ' + suffix
        if self.callback:
            self.callback(request)
        if key == self.timeout_before:
            self.timeout_before = None
            raise httpx.ReadTimeout('synthetic before acceptance', request=request)
        status, response = self.dispatch(method, suffix, request, body)
        if method != 'GET':
            self.writes.append((key, body))
        if key == self.timeout_after:
            self.timeout_after = None
            raise httpx.ReadTimeout('synthetic after acceptance', request=request)
        return httpx.Response(status, json=response) if status != 204 else httpx.Response(status)

    def dispatch(self, method, path, request, body):
        if method == 'GET':
            if not path:
                return 200, self.repo
            if path == '/branches/main':
                return 200, {'protected': bool(self.protection), 'commit': {'sha': self.base}}
            if path == '/branches/main/protection':
                return (403, {}) if self.permission_failure else (200, self.protection)
            if path.startswith('/rules/branches/'):
                return 200, self.rules if path == '/rules/branches/main' else self.temp_rules
            if path.startswith('/git/ref/heads/'):
                branch = path.removeprefix('/git/ref/heads/')
                return (200, {'object': {'sha': self.refs[branch]}}) if branch in self.refs else (404, {})
            if path.startswith('/git/'):
                _, _, kind, sha = path.split('/')
                obj = self.objects[kind].get(sha)
                return (200, obj) if obj else (404, {})
            if path == '/pulls':
                return 200, [self.current_pr()] if self.pr else []
            if path == '/pulls/1':
                return 200, self.current_pr()
            if path == '/pulls/1/files':
                commit = self.objects['commits'][self.pr['head']['sha']]
                def flatten(sha, prefix=''):
                    result = {}
                    for entry in self.objects['trees'][sha]['tree']:
                        if entry['type'] == 'tree':
                            result.update(flatten(entry['sha'], prefix + entry['path'] + '/'))
                        else:
                            result[prefix + entry['path']] = entry['sha']
                    return result
                original = flatten(self.objects['commits'][COMMIT]['tree']['sha'])
                updated = flatten(commit['tree']['sha'])
                files = [{'filename': path, 'status': 'modified' if path in original else 'added', 'sha': sha}
                         for path, sha in updated.items() if original.get(path) != sha]
                if self.changed_files:
                    files.append({'filename': 'src/evil.py', 'status': 'added', 'sha': 'e' * 40})
                return 200, files
            if path == '/pulls/1/commits':
                return 200, [{'sha': self.pr['head']['sha']}]
            if path == '/pulls/1/reviews':
                return 200, self.reviews
            if path.endswith('/statuses'):
                return 200, self.statuses
            if path.endswith('/check-runs'):
                return 200, {'total_count': len(self.runs), 'check_runs': [{**r, 'head_sha': self.pr['head']['sha']} for r in self.runs]}
        if method == 'POST' and path in {'/git/blobs', '/git/trees', '/git/commits'}:
            kind = path.rsplit('/', 1)[1]
            if kind == 'blobs':
                sha = object_sha('blob', body['content'].encode())
                obj = {'sha': sha}
            elif kind == 'trees':
                sha = tree_sha(body['tree'])
                obj = {'sha': sha, 'tree': body['tree'], 'truncated': False}
            else:
                sha = commit_sha(body)
                obj = {**body, 'sha': sha, 'tree': {'sha': body['tree']}, 'parents': [{'sha': p} for p in body['parents']]}
            self.objects[kind][sha] = obj
            return 201, obj
        if method == 'POST' and path == '/git/refs':
            branch = body['ref'].removeprefix('refs/heads/')
            assert branch not in self.refs  # No overwrite or force push.
            self.refs[branch] = body['sha']
            return 201, {'object': {'sha': body['sha']}}
        if method == 'POST' and path == '/pulls':
            assert self.pr is None
            assert body['base'] == 'main'
            self.pr = {'number': 1, 'body': body['body'], 'state': 'open', 'merged': False, 'draft': False,
                'head': {'sha': self.refs[body['head']], 'ref': body['head'], 'repo': {'id': 11}},
                'base': {'sha': self.base, 'ref': 'main', 'repo': {'id': 11}}}
            return 201, self.current_pr()
        if method == 'PUT' and path == '/pulls/1/merge':
            assert body == {'sha': self.pr['head']['sha'], 'merge_method': 'merge'}
            assert not self.pr['merged']
            merge_sha = 'f' * 40
            self.objects['commits'][merge_sha] = {'sha': merge_sha, 'parents': [{'sha': self.base}, {'sha': body['sha']}],
                'tree': self.objects['commits'][body['sha']]['tree']}
            self.pr.update(merged=True, state='closed', merge_commit_sha=merge_sha)
            self.base = merge_sha
            return 200, {'merged': True, 'sha': merge_sha}
        if method == 'DELETE' and path.startswith('/git/refs/heads/'):
            branch = path.removeprefix('/git/refs/heads/')
            assert branch in self.refs
            del self.refs[branch]
            return 204, {}
        raise AssertionError('Unexpected simulated GitHub request: ' + method + ' ' + path)

    def current_pr(self):
        pr = copy.deepcopy(self.pr)
        pr.update(mergeable=True, mergeable_state=self.mergeable_state)
        if not pr['merged']:
            pr['base']['sha'] = self.base
            pr['head']['sha'] = self.refs[pr['head']['ref']]
        return pr


@pytest.fixture
def service(monkeypatch, key_file):
    api = GitHubService()
    settings = get_settings()
    monkeypatch.setattr(settings, 'github_owner', 'zkralec')
    monkeypatch.setattr(settings, 'docs_publish_live_enabled', True)
    monkeypatch.setattr(settings, 'docs_publish_check_polls', 1)
    def factory(write):
        s = Settings(_env_file=None, github_owner='zkralec', github_app_id=5519145,
                     github_installation_id=176370838, github_app_private_key_path=str(key_file))
        client = PublishingGitHubClient(s, httpx.Client(transport=httpx.MockTransport(api)))
        if not write:
            client.permissions = {k: 'read' for k in client.permissions}
        return client
    monkeypatch.setattr(publishing, 'get_publication_client', factory)
    return api


@pytest.fixture
def models(monkeypatch):
    stub = Models()
    monkeypatch.setattr('personal_dot.documentation_preview.get_documentation_service', stub.service)
    return stub


async def attempt(client, preview, *, write=True, notify='none'):
    response = await client.post('/tasks', json={'type': 'documentation_publish',
        'payload': {'preview_task_id': preview['id'], 'allow_publish': write}, 'notification_policy': notify})
    assert response.status_code == 202, response.text
    run_queued_jobs()
    task = (await client.get('/tasks/' + response.json()['id'])).json()
    assert task['status'] == 'succeeded', task
    return task


@pytest.mark.anyio
async def test_exact_candidate_merged_author_preserved_cleanup_and_duplicates(client, service, models):
    preview = await run_preview(client, create_inspection())
    task = await attempt(client, preview)
    result = task['result']
    assert result['published'] and result['merged'] and result['branch_deleted'] and not result['deployed']
    assert result['attribution']['author'] == AUTHOR
    assert result['diff_verification']['passed']
    assert result['authorization']['review_record_sha256'] == preview['result']['review_record_sha256']
    assert result['authorization_sha256'] == digest(result['authorization'])
    assert service.refs == {} and service.pr['merged']
    commit_body = next(b for k, b in service.writes if k == 'POST /git/commits')
    assert all(commit_body[role]['email'] == AUTHOR['email'] and commit_body[role]['name'] == AUTHOR['name'] for role in ('author', 'committer'))
    before = len(service.writes)
    jobs.execute_task(task['id'])
    duplicate = await attempt(client, preview)
    assert duplicate['result'] == result and len(service.writes) == before
    assert len(models.requests) == 2
    assert 'ghs_synthetic' not in json.dumps(task)


@pytest.mark.anyio
async def test_preview_reads_requirements_without_write_token_or_job(client, service, models):
    preview = await run_preview(client, create_inspection())
    task = await attempt(client, preview, write=False)
    assert task['result']['mode'] == 'preview' and not service.writes
    tokens = [json.loads(r.content) for r in service.requests if r.url.path.endswith('/access_tokens')]
    assert all(set(t['permissions'].values()) == {'read'} for t in tokens)
    with SessionLocal() as db:
        assert db.scalar(select(DocumentationPublication)) is None


@pytest.mark.anyio
@pytest.mark.parametrize('change', ['rejection', 'candidate', 'base', 'owner', 'author', 'policy', 'operator_gate'])
async def test_local_authorization_invalidated_before_remote_write(client, service, models, monkeypatch, change):
    preview = await run_preview(client, create_inspection())
    with SessionLocal() as db, db.begin():
        source = db.get(Task, uuid.UUID(preview['id']))
        data = copy.deepcopy(source.result)
        if change == 'rejection': data['review']['decision'] = 'changes_requested'
        if change == 'candidate': data['candidate']['diff'] += '+injected\n'
        if change == 'base': data['base_commit'] = 'd' * 40
        source.result = data
    if change == 'owner': monkeypatch.setattr(get_settings(), 'github_owner', 'foreign')
    if change == 'author': monkeypatch.setattr(get_settings(), 'github_commit_author_email', 'guessed@example.com')
    if change == 'policy': monkeypatch.setattr(get_settings(), 'docs_preview_max_changed_lines', 2)
    if change == 'operator_gate': monkeypatch.setattr(get_settings(), 'docs_publish_live_enabled', False)
    task = await attempt(client, preview)
    assert task['result']['blockers'] and not service.writes


@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['github_review', 'linear', 'signatures', 'restriction', 'merge_method', 'unknown', 'branch_creation', 'protection_unreadable'])
async def test_discovery_eligibility_does_not_waive_merge_requirements(client, service, models, kind):
    preview = await run_preview(client, create_inspection())
    if kind == 'github_review': service.rules = [{'type': 'pull_request', 'parameters': {'required_approving_review_count': 1}}]
    if kind == 'linear': service.rules = [{'type': 'required_linear_history'}]
    if kind == 'signatures': service.protection = {'required_signatures': {'enabled': True}}
    if kind == 'restriction': service.protection = {'restrictions': {'apps': [], 'users': [], 'teams': []}}
    if kind == 'merge_method': service.repo['allow_merge_commit'] = False
    if kind == 'unknown': service.rules = [{'type': 'future_rule'}]
    if kind == 'branch_creation': service.temp_rules = [{'type': 'creation'}]
    if kind == 'protection_unreadable': service.protection = {'restrictions': {}}; service.permission_failure = True
    task = await attempt(client, preview)
    assert task['result']['blockers'] and not service.writes
    assert not task['result']['merged']


@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['pending', 'failed', 'missing', 'wrong_app', 'changes_requested', 'mergeability', 'diff', 'base', 'head'])
async def test_published_gate_rejects_changed_or_unready_inputs(client, service, models, kind):
    preview = await run_preview(client, create_inspection())
    service.rules = [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [{'context': 'test', 'integration_id': 42}]}}]
    service.runs = [{'id': 1, 'name': 'test', 'app': {'id': 42}, 'status': 'completed', 'conclusion': 'success'}]
    if kind == 'pending': service.runs[0].update(status='in_progress', conclusion=None)
    if kind == 'failed': service.runs[0]['conclusion'] = 'failure'
    if kind == 'missing': service.runs = []
    if kind == 'wrong_app': service.runs[0]['app']['id'] = 99
    if kind == 'changes_requested': service.reviews = [{'user': {'id': 1}, 'state': 'CHANGES_REQUESTED'}]
    if kind == 'mergeability': service.mergeable_state = 'blocked'
    if kind == 'diff': service.changed_files = True
    if kind in {'base', 'head'}:
        def changed(request):
            if request.url.path.endswith('/pulls/1') and service.pr:
                if kind == 'base': service.base = 'd' * 40
                else: service.refs[service.pr['head']['ref']] = 'e' * 40
        service.callback = changed
    task = await attempt(client, preview)
    assert task['result']['published'] and task['result']['blockers'] and not task['result']['merged']
    assert not any(k.startswith('PUT') or k.startswith('DELETE') for k, _ in service.writes)


@pytest.mark.anyio
@pytest.mark.parametrize('operation', ['blobs', 'trees', 'commits', 'refs', 'pulls', 'merge', 'cleanup'])
@pytest.mark.parametrize('accepted', [True, False])
async def test_ambiguous_operations_reconcile_before_retry_without_duplicates(client, service, models, operation, accepted):
    preview = await run_preview(client, create_inspection())
    path = 'POST /git/' + operation if operation in {'blobs', 'trees', 'commits', 'refs'} else 'POST /pulls' if operation == 'pulls' else 'PUT /pulls/1/merge' if operation == 'merge' else 'DELETE /git/refs/heads/dot/docs-' + uuid.UUID(preview['id']).hex
    setattr(service, 'timeout_after' if accepted else 'timeout_before', path)
    first = await attempt(client, preview)
    assert first['result']['blockers'] == ['timeout']
    second = await attempt(client, preview)
    assert second['result']['merged'] and second['result']['branch_deleted'], second
    assert sum(k == path for k, _ in service.writes) == 1
    assert len(models.requests) == 2
    with SessionLocal() as db:
        job = db.get(DocumentationPublication, uuid.UUID(preview['id']))
        assert job.completed and job.state['merge_commit'] == 'f' * 40


@pytest.mark.anyio
async def test_pending_checks_resume_same_pr_and_one_active_job_per_repo(client, service, models):
    first = await run_preview(client, create_inspection())
    service.mergeable_state = 'blocked'
    a = await attempt(client, first)
    other = await run_preview(client, create_inspection())
    b = await attempt(client, other)
    assert b['result']['blockers'] == ['another_maintenance_job_active']
    service.mergeable_state = 'clean'
    c = await attempt(client, first)
    assert a['result']['pr_number'] == c['result']['pr_number'] == 1 and c['result']['merged']
    assert sum(k == 'POST /pulls' for k, _ in service.writes) == 1


@pytest.mark.anyio
async def test_notification_failure_retries_delivery_only(client, service, models, monkeypatch):
    preview = await run_preview(client, create_inspection())
    calls = []
    class Broken:
        def send_task_notification(self, event):
            calls.append(event)
            raise RuntimeError('synthetic notification failure')
    monkeypatch.setattr(jobs, 'get_notification_service', Broken)
    task = await attempt(client, preview, notify='always')
    assert task['result']['merged'] and len(calls) == 1
    count = len(service.writes)
    deliver_notification(uuid.UUID(task['id']), now=datetime.now(UTC)+timedelta(minutes=2), service_factory=Broken)
    assert len(calls) == 2 and len(service.writes) == count and len(models.requests) == 2


@pytest.mark.anyio
async def test_recovered_owner_cannot_initiate_next_remote_write(client, service, models, monkeypatch):
    preview = await run_preview(client, create_inspection())
    captured = []
    original = publishing.Controller.operation
    def revoke(self, key, call, **kwargs):
        if key == 'branch':
            captured.append(self.task.id)
            with SessionLocal() as db, db.begin():
                db.get(Task, self.task.id).started_at = datetime.now(UTC) - timedelta(days=2)
            assert scheduler()._recover_stale_tasks(datetime.now(UTC)) == 1
        return original(self, key, call, **kwargs)
    monkeypatch.setattr(publishing.Controller, 'operation', revoke)
    response = await client.post('/tasks', json={'type': 'documentation_publish', 'payload': {'preview_task_id': preview['id'], 'allow_publish': True}})
    run_queued_jobs()
    result = (await client.get('/tasks/' + response.json()['id'])).json()
    assert captured and result['status'] == 'uncertain'
    assert not service.refs and service.pr is None
    assert not any(k == 'POST /git/refs' for k, _ in service.writes)


@pytest.mark.anyio
async def test_inflight_write_holds_claim_and_repository_lock(client, service, models):
    preview = await run_preview(client, create_inspection())
    response = await client.post('/tasks', json={'type': 'documentation_publish', 'payload': {'preview_task_id': preview['id'], 'allow_publish': True}})
    task_id = response.json()['id']
    entered, release = Event(), Event()
    original = publishing.Controller.operation
    def age(self, key, call, **kwargs):
        if key == 'branch':
            with SessionLocal() as db, db.begin():
                db.get(Task, self.task.id).started_at = datetime.now(UTC) - timedelta(days=2)
        return original(self, key, call, **kwargs)
    def pause(request):
        if request.method == 'POST' and request.url.path.endswith('/git/refs'):
            entered.set()
            assert release.wait(10)
    service.callback = pause
    from unittest.mock import patch
    with patch.object(publishing.Controller, 'operation', age), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(jobs.execute_task, task_id)
        try:
            assert entered.wait(10)
            assert scheduler()._recover_stale_tasks(datetime.now(UTC)) == 0
            duplicate = await client.post('/tasks', json={'type': 'documentation_publish', 'payload': {'preview_task_id': preview['id'], 'allow_publish': True}})
            overlap = jobs.execute_task(duplicate.json()['id'])
            assert overlap['blockers'] == ['another_maintenance_execution_active']
        finally:
            release.set()
        assert future.result(timeout=15)['merged']


@pytest.mark.anyio
@pytest.mark.parametrize('operation', ['branch', 'pull_request', 'merge', 'cleanup'])
async def test_remote_acceptance_then_database_rollback_reconciles(client, service, models, operation):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    preview = await run_preview(client, create_inspection())
    failed = []
    def fail_commit(session):
        for obj in session.dirty:
            if isinstance(obj, DocumentationPublication) and not failed:
                if obj.state.get('operations', {}).get(operation, {}).get('status') == 'completed':
                    failed.append(True)
                    raise RuntimeError('synthetic database commit failure after remote acceptance')
    event.listen(Session, 'before_commit', fail_commit)
    try:
        response = await client.post('/tasks', json={'type': 'documentation_publish', 'payload': {'preview_task_id': preview['id'], 'allow_publish': True}})
        run_queued_jobs()
        result = (await client.get('/tasks/' + response.json()['id'])).json()
        assert result['status'] == 'failed' and failed
    finally:
        event.remove(Session, 'before_commit', fail_commit)
    with SessionLocal() as db:
        state = db.get(DocumentationPublication, uuid.UUID(preview['id'])).state
        assert state['operations'][operation]['status'] == 'intent'
    final = await attempt(client, preview)
    assert final['result']['merged'] and final['result']['branch_deleted']
    for key in ('POST /git/refs', 'POST /pulls', 'PUT /pulls/1/merge'):
        assert sum(k == key for k, _ in service.writes) == 1


@pytest.mark.anyio
async def test_changed_temporary_branch_is_never_overwritten_or_deleted(client, service, models):
    preview = await run_preview(client, create_inspection())
    service.timeout_after = 'PUT /pulls/1/merge'
    first = await attempt(client, preview)
    branch = first['result']['branch']
    service.refs[branch] = 'e' * 40
    second = await attempt(client, preview)
    assert second['result']['merged'] and second['result']['blockers'] == ['temporary_branch_changed_no_cleanup']
    assert service.refs[branch] == 'e' * 40
    assert not any(k.startswith('DELETE') for k, _ in service.writes)


@pytest.mark.anyio
async def test_check_changes_between_authorization_and_merge_stop_the_write(client, service, models):
    preview = await run_preview(client, create_inspection())
    original = publishing.Controller.operation
    from unittest.mock import patch
    def change(self, key, call, **kwargs):
        if key == 'merge':
            service.statuses = [{'id': 1, 'context': 'new-check', 'state': 'pending'}]
        return original(self, key, call, **kwargs)
    with patch.object(publishing.Controller, 'operation', change):
        result = await attempt(client, preview)
    assert result['result']['blockers'] == ['checks_pending_or_failed']
    assert not any(k.startswith('PUT') for k, _ in service.writes)


@pytest.mark.anyio
async def test_duplicate_remote_pr_and_foreign_markers_fail_closed(client, service, models):
    preview = await run_preview(client, create_inspection())
    service.timeout_after = 'POST /pulls'
    await attempt(client, preview)
    service.pr['body'] = 'unrelated work'
    result = await attempt(client, preview)
    assert result['result']['blockers'] == ['pull_request_ownership_mismatch']
    assert sum(k == 'POST /pulls' for k, _ in service.writes) == 1


@pytest.mark.anyio
async def test_merge_base_race_records_actual_merge_without_claiming_verified_completion(client, service, models):
    preview = await run_preview(client, create_inspection())
    def race(request):
        if request.method == 'PUT': service.base = 'd' * 40
    service.callback = race
    result = await attempt(client, preview)
    assert result['result']['merged'] and not result['result']['deployed']
    assert result['result']['blockers'] == ['merged_revision_requires_owner_reconciliation']
    assert not any(k.startswith('DELETE') for k, _ in service.writes)


def test_publication_transport_rejects_force_push_settings_and_foreign_writes(service):
    client = publishing.get_publication_client(True)
    client.authenticate('fixture')
    for method, path in [('PATCH', '/repos/zkralec/fixture/git/refs/heads/main'),
                         ('PATCH', '/repos/zkralec/fixture'),
                         ('PUT', '/repos/zkralec/fixture/branches/main/protection'),
                         ('POST', '/repos/elsewhere/other/pulls'),
                         ('DELETE', '/repos/zkralec/fixture/git/refs/heads/main')]:
        with pytest.raises(GitHubError): client.request(method, path, {})
    assert not service.writes
    client.close()


def test_git_object_hashes_match_independent_git_hash_object_evidence():
    # Constants were calculated with Git's hash-object, independently of the adapter.
    body = {'tree': 'a' * 40, 'parents': ['c' * 40],
            'author': {**AUTHOR, 'date': '2026-10-30T00:00:00+00:00'},
            'committer': {**AUTHOR, 'date': '2026-10-30T00:00:00+00:00'},
            'message': 'docs: clarify implemented behavior\n'}
    assert commit_sha(body) == 'f7174c9290d02cffbb15e066841a57a648fce035'
    assert tree_sha([{'path': 'README.md', 'mode': '100644', 'type': 'blob', 'sha': 'a' * 40}]) == '53c73438c5d6ccffcab6596d3cf544a3ff2601e8'


@pytest.mark.anyio
async def test_invalidated_review_still_reconciles_lost_merge_without_another_write(client, service, models):
    preview = await run_preview(client, create_inspection())
    service.timeout_after = 'PUT /pulls/1/merge'
    first = await attempt(client, preview)
    assert not first['result']['merged'] and service.pr['merged']
    with SessionLocal() as db, db.begin():
        source = db.get(Task, uuid.UUID(preview['id']))
        result = copy.deepcopy(source.result)
        result['review']['decision'] = 'changes_requested'
        source.result = result
    count = len(service.writes)
    second = await attempt(client, preview)
    assert second['result']['merged'] and second['result']['remote_merge_verified']
    assert second['result']['blockers'] == ['review_or_policy_invalidated']
    assert len(service.writes) == count and service.refs


@pytest.mark.anyio
async def test_pending_checks_finishing_in_bounded_window_merge_automatically(client, service, models, monkeypatch):
    preview = await run_preview(client, create_inspection())
    monkeypatch.setattr(get_settings(), 'docs_publish_check_polls', 2)
    monkeypatch.setattr(get_settings(), 'docs_publish_poll_seconds', .01)
    reads = []
    service.rules = [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [{'context': 'test', 'integration_id': 42}]}}]
    service.runs = [{'id': 1, 'name': 'test', 'app': {'id': 42}, 'status': 'in_progress', 'conclusion': None}]
    def complete(request):
        if request.url.path.endswith('/pulls/1'):
            reads.append(True)
            if len(reads) >= 2:
                service.runs[0].update(status='completed', conclusion='success')
    service.callback = complete
    result = await attempt(client, preview)
    assert result['result']['merged'] and result['result']['check_poll'] == 2
    assert sum(k == 'PUT /pulls/1/merge' for k, _ in service.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['truncated', 'tree_identity', 'target_mode', 'repository_base'])
async def test_ambiguous_or_changed_base_objects_never_publish(client, service, models, kind):
    preview = await run_preview(client, create_inspection())
    tree = next(iter(service.objects['trees'].values()))
    if kind == 'truncated': tree['truncated'] = True
    if kind == 'tree_identity': tree['tree'].append({'path': 'unexpected', 'type': 'blob', 'mode': '100644', 'sha': 'a'*40})
    if kind == 'target_mode': tree['tree'][0]['mode'] = '100755'
    if kind == 'repository_base': service.base = 'd' * 40
    task = await attempt(client, preview)
    assert task['result']['blockers'] and not service.writes


@pytest.mark.anyio
async def test_review_change_between_remote_operations_prevents_next_write(client, service, models):
    preview = await run_preview(client, create_inspection())
    original = publishing.Controller.operation
    from unittest.mock import patch
    def change(self, key, call, **kwargs):
        if key == 'branch':
            with SessionLocal() as db, db.begin():
                source = db.get(Task, uuid.UUID(preview['id']))
                result = copy.deepcopy(source.result)
                result['candidate']['diff'] += '+changed\n'
                source.result = result
        return original(self, key, call, **kwargs)
    with patch.object(publishing.Controller, 'operation', change):
        task = await attempt(client, preview)
    assert task['result']['blockers'] == ['review_or_policy_invalidated']
    assert not service.refs and service.pr is None


@pytest.mark.anyio
async def test_policy_checks_and_status_paths_do_not_allow_scheduling(client):
    response = await client.post('/schedules', json={'name': 'must stay manual', 'schedule_type': 'once',
        'run_at': '2030-01-01T00:00:00Z', 'enabled': False,
        'task': {'type': 'documentation_publish', 'payload': {'preview_task_id': str(uuid.uuid4())}}})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_multiple_targets_preserve_nested_tree_and_reviewed_bytes(client, service, models):
    body = create_inspection({'docs/guide.md': TARGET})
    body['payload']['targets'].append({'path': 'docs/guide.md', 'sha256': snapshot_file('docs/guide.md', TARGET)['sha256']})
    original = models.editor
    def two_targets(context):
        output = original(context)
        output['edits'].append({**output['edits'][0], 'path': 'docs/guide.md'})
        return output
    models.editor = two_targets
    child = [{'path': 'guide.md', 'mode': '100644', 'type': 'blob', 'sha': snapshot_file('docs/guide.md', TARGET)['git_sha']}]
    child_sha = tree_sha(child)
    root_entries = next(iter(service.objects['trees'].values()))['tree'] + [
        {'path': 'docs', 'mode': '040000', 'type': 'tree', 'sha': child_sha}]
    root_sha = tree_sha(root_entries)
    service.objects['trees'][child_sha] = {'sha': child_sha, 'tree': child, 'truncated': False}
    service.objects['trees'][root_sha] = {'sha': root_sha, 'tree': root_entries, 'truncated': False}
    service.objects['commits'][COMMIT]['tree']['sha'] = root_sha
    preview = await run_preview(client, body)
    task = await attempt(client, preview)
    assert task['result']['merged'] and task['result']['diff_verification']['passed']
    assert len([op for op in task['result']['plan'] if op['kind'] == 'trees']) == 2
    commit = service.objects['commits'][task['result']['plan'][-1]['sha']]
    assert commit['parents'] == [{'sha': COMMIT}]


@pytest.mark.anyio
async def test_missing_pr_merge_sha_uses_persisted_merge_receipt(client, service, models):
    preview=await run_preview(client,create_inspection())
    original=service.current_pr
    def missing_sha():
        result=original()
        if result.get('merged'): result['merge_commit_sha']=None
        return result
    service.current_pr=missing_sha
    result=await attempt(client,preview)
    assert result['result']['merged'] and result['result']['branch_deleted']
    assert result['result']['merge_commit']=='f'*40
    assert sum(k=='PUT /pulls/1/merge' for k,_ in service.writes)==1


@pytest.mark.anyio
async def test_confirmed_merge_revalidates_new_publisher_for_cleanup_only(client, service, models, monkeypatch):
    preview=await run_preview(client,create_inspection())
    service.timeout_after='PUT /pulls/1/merge'
    first=await attempt(client,preview)
    assert first['result']['blockers']==['timeout']
    before=len(service.writes)
    monkeypatch.setattr(publishing,'IMPLEMENTATION','repaired-publisher')
    result=await attempt(client,preview)
    assert result['result']['merged'] and result['result']['branch_deleted']
    assert result['result']['binding_revalidation']['reason']=='confirmed_remote_merge_cleanup_only'
    assert all(k.startswith('DELETE') for k,_ in service.writes[before:])
