"""Daily controls and real task orchestration, isolated PostgreSQL and stub HTTP."""

import base64
import copy
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from sqlalchemy import select

from personal_dot import documentation_maintenance as maintenance, maintenance_control, jobs, documentation_preview
from personal_dot.config import Settings, get_settings
from personal_dot.db import SessionLocal
from personal_dot.documentation_git import AUTHOR, object_sha, tree_sha
from personal_dot.documentation_policy import digest
from personal_dot.github import GitHubClient
from personal_dot.github_publication import PublishingGitHubClient
from personal_dot.maintenance_control import MaintenanceBlocked, reservation_amount, pilot_succeeded
from personal_dot.maintenance_schemas import MaintenanceConfiguration
from personal_dot.models import (Task, TaskType, TaskStatus, Schedule, ScheduleType, MaintenanceControl,
    MaintenanceDay, MaintenanceRun, MaintenanceRepository, MaintenanceAssessment, NotificationDelivery)
from personal_dot.schedule_calculations import next_cron_occurrence
from personal_dot.scheduler import SchedulerService
from tests.test_documentation_preview import Models, TARGET, EVIDENCE, COMMIT
from tests.test_documentation_publish import GitHubService
from tests.test_github import key_file, OWNER
from tests.test_tasks import run_queued_jobs

CONFIG = {'daily_time': '09:00', 'timezone': 'America/New_York', 'daily_budget_microusd': 250000,
          'max_input_bytes_per_call': 65536, 'max_output_tokens_per_call': 2048, 'exclusions': []}


class MaintenanceGitHub(GitHubService):
    def __init__(self):
        super().__init__()
        source_sha = object_sha('blob', EVIDENCE.encode())
        source_entries = [{'path': 'core.py', 'type': 'blob', 'mode': '100644', 'sha': source_sha}]
        source_tree = tree_sha(source_entries)
        self.objects['trees'][source_tree] = {'sha': source_tree, 'tree': source_entries, 'truncated': False}
        root_entries = next(iter(self.objects['trees'].values()))['tree'] + [
            {'path': 'src', 'type': 'tree', 'mode': '040000', 'sha': source_tree}]
        root_sha = tree_sha(root_entries)
        self.objects['trees'][root_sha] = {'sha': root_sha, 'tree': root_entries, 'truncated': False}
        self.objects['commits'][COMMIT]['tree']['sha'] = root_sha
        for text in (TARGET, EVIDENCE):
            sha = object_sha('blob', text.encode())
            self.objects['blobs'][sha] = {'sha': sha, 'encoding': 'base64', 'size': len(text.encode()),
                                         'content': base64.b64encode(text.encode()).decode()}
        self.repositories = [self.repo]

    def __call__(self, request):
        if request.url.path.endswith('/access_tokens'):
            self.requests.append(request)
            body = json.loads(request.content)
            assert set(body['permissions']) <= set(self.permissions)
            return httpx.Response(201, json={'token': 'ghs_synthetic_publication_secret',
                'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat(), 'permissions': body['permissions']})
        if request.url.path == '/installation/repositories':
            self.requests.append(request)
            return httpx.Response(200, json={'total_count': len(self.repositories), 'repositories': self.repositories})
        return super().__call__(request)

    def dispatch(self, method, path, request, body):
        if method == 'GET' and path.startswith('/git/trees/'):
            if path.rsplit('/', 1)[1] not in self.objects['trees']:
                return 404, {}
            tree = copy.deepcopy(self.objects['trees'][path.rsplit('/', 1)[1]])
            for entry in tree['tree']:
                if entry['type'] == 'blob':
                    entry['size'] = self.objects['blobs'][entry['sha']]['size']
            return 200, tree
        if method == 'POST' and path == '/git/blobs':
            status, obj = super().dispatch(method, path, request, body)
            self.objects['blobs'][obj['sha']] = {**obj, 'encoding': 'base64', 'size': len(body['content'].encode()),
                'content': base64.b64encode(body['content'].encode()).decode()}
            return status, obj
        if method == 'GET' and path == '/commits/main':
            return 200, {'sha': self.base, 'commit': {'tree': self.objects['commits'][self.base]['tree']}}
        if method == 'GET' and path.startswith('/commits/') and not path.endswith(('/statuses', '/check-runs')):
            sha = path.split('/')[2]
            if sha in self.objects['commits']:
                obj = self.objects['commits'][sha]
                return 200, {'sha': sha, 'author': OWNER, 'commit': {'author': obj['author']}}
        return super().dispatch(method, path, request, body)


@pytest.fixture
def setup(monkeypatch, key_file):
    settings = get_settings()
    for name, value in {'github_owner': 'zkralec', 'docs_maintenance_live_enabled': True,
                        'docs_preview_live_enabled': True, 'docs_publish_live_enabled': True,
                        'docs_publish_check_polls': 1}.items():
        monkeypatch.setattr(settings, name, value)
    api = MaintenanceGitHub()
    s = Settings(_env_file=None, github_owner='zkralec', github_app_id=5519145,
                 github_installation_id=176370838, github_app_private_key_path=str(key_file))
    monkeypatch.setattr(jobs, 'get_github_client', lambda: GitHubClient(s, httpx.Client(transport=httpx.MockTransport(api))))
    def publishing(write):
        client = PublishingGitHubClient(s, httpx.Client(transport=httpx.MockTransport(api)))
        if not write: client.permissions = {k: 'read' for k in client.permissions}
        return client
    monkeypatch.setattr(maintenance, 'get_publication_client', publishing)
    monkeypatch.setattr('personal_dot.documentation_publish.get_publication_client', publishing)
    models = Models()
    def service(role, request):
        service = models.service(role, request)
        create = service.create_turn
        def call(*args, **kwargs):
            turn = create(*args, **kwargs)
            return replace(turn, metadata={**turn.metadata, 'model': documentation_preview.configuration(request)[role + '_model']})
        service.create_turn = call
        return service
    monkeypatch.setattr(documentation_preview, 'get_documentation_service', service)
    # No live notifications during fixtures. Their durable intent is still tested.
    monkeypatch.setattr(jobs, '_notify_terminal_task', lambda _: None)
    return api, models


async def configure(client, **changes):
    response = await client.put('/maintenance/configuration', json={**CONFIG, **changes})
    assert response.status_code == 200, response.text
    return response.json()


async def run(client, pilot=True):
    response = await client.post('/tasks', json={'type': 'documentation_maintenance', 'payload': {'pilot': pilot}, 'notification_policy': 'always'})
    assert response.status_code == 202, response.text
    run_queued_jobs()
    return (await client.get('/tasks/' + response.json()['id'])).json()


@pytest.mark.anyio
async def test_unterminated_readme_reaches_review_and_exact_publication(client, setup):
    api, models = setup
    original = TARGET + '\nPreserved final line'
    raw = original.encode()
    blob = object_sha('blob', raw)
    api.objects['blobs'][blob] = {'sha': blob, 'encoding': 'base64', 'size': len(raw),
                                'content': base64.b64encode(raw).decode()}
    base = api.objects['commits'][COMMIT]
    entries = copy.deepcopy(api.objects['trees'][base['tree']['sha']]['tree'])
    next(e for e in entries if e['path'] == 'README.md')['sha'] = blob
    tree = tree_sha(entries)
    api.objects['trees'][tree] = {'sha': tree, 'tree': entries, 'truncated': False}
    base['tree']['sha'] = tree
    await configure(client)
    task = await run(client)
    assert task['result']['outcome'] == 'merged', task
    assert [r[0] for r in models.requests] == ['editor', 'reviewer']
    assert '\\ No newline at end of file' in models.requests[1][2]['diff']
    writes = [json.loads(r.content) for r in api.requests
              if r.method == 'POST' and r.url.path.endswith('/git/blobs')]
    assert [w['content'] for w in writes] == [TARGET + '\nTask results remain in PostgreSQL.\n\nPreserved final line']


@pytest.mark.anyio
async def test_real_handlers_pilot_merge_usage_and_activation(client, setup):
    api, models = setup
    await configure(client)
    before = await client.patch('/maintenance', json={'action': 'resume'})
    assert before.status_code == 409
    task = await run(client)
    assert task['status'] == 'succeeded', task
    assert task['result']['outcome'] == 'merged', task
    assert len(models.requests) == 2
    assert task['result']['live_verification']['author_associated']
    assert task['result']['usage']['total_tokens'] == 40
    assert task['result']['reserved_microusd'] == 19456
    assert task['result']['billing'] == 'not_observed'
    assert (await client.get('/maintenance')).json()['pilot_succeeded']
    resumed = await client.patch('/maintenance', json={'action': 'resume'})
    assert resumed.status_code == 200 and resumed.json()['enabled']
    assert all(r[1].get('service_tier') == 'default' for r in models.requests)
    with SessionLocal() as db:
        assert len(list(db.scalars(select(NotificationDelivery)))) == 1
        day = db.scalar(select(MaintenanceDay))
        assert day.model_calls == 2 and day.merge_owner == uuid.UUID(task['id'])


@pytest.mark.anyio
async def test_no_useful_change_cached_and_quiet(client, setup):
    api, models = setup
    original = models.editor
    models.editor = lambda context: {**original(context), 'outcome': 'no_useful_change', 'edits': []}
    await configure(client)
    first = await run(client)
    assert first['result']['outcome'] == 'no_useful_change' and not first['result']['notify']
    second = await run(client)
    assert second['result']['outcome'] == 'no_op' and len(models.requests) == 1
    with SessionLocal() as db:
        assert db.scalar(select(NotificationDelivery)) is None
    assert not (await client.get('/maintenance')).json()['pilot_succeeded']


@pytest.mark.anyio
async def test_rejection_not_reopened_even_after_reassessment_interval(client, setup, monkeypatch):
    api, models = setup
    models.reviewer = lambda c: {'binding_sha256': c['binding_sha256'], 'decision': 'changes_requested',
        'findings': [{'code': 'accuracy', 'description': 'Authored rejection.', 'evidence_refs': ['evidence:1']}]}
    await configure(client)
    first = await run(client)
    assert first['result']['outcome'] == 'changes_requested'
    with SessionLocal() as db, db.begin():
        db.scalar(select(MaintenanceAssessment)).assessed_at -= timedelta(days=30)
    second = await run(client)
    assert second['result']['outcome'] == 'no_op' and len(models.requests) == 2
    assert not api.writes


@pytest.mark.anyio
async def test_budget_reservation_atomic_and_blocks_payment(client, setup):
    api, models = setup
    await configure(client, daily_budget_microusd=100)
    result = await run(client)
    assert result['result']['outcome'] == 'budget_exhausted'
    assert not models.requests and not api.writes
    assert (await client.get('/maintenance/budgets')).json() == []


@pytest.mark.parametrize('after,expected', [
    ('2026-10-31T13:00:00+00:00', '2026-11-01T14:00:00+00:00'),
    ('2027-03-13T14:00:00+00:00', '2027-03-14T13:00:00+00:00'),
    ('2026-10-30T12:59:00+00:00', '2026-10-30T13:00:00+00:00')])
def test_new_york_daily_dst(after, expected):
    assert next_cron_occurrence('0 9 * * *', 'America/New_York', datetime.fromisoformat(after)) == datetime.fromisoformat(expected)


@pytest.mark.anyio
async def test_downtime_coalesces_and_duplicate_triggers_are_unique(client, setup):
    configured = await configure(client)
    with SessionLocal() as db, db.begin():
        control = db.get(MaintenanceControl, 1)
        schedule = db.get(Schedule, control.schedule_id)
        schedule.enabled, control.paused = True, False
        schedule.next_run_at = datetime(2026, 10, 25, 13, tzinfo=UTC)
    service = SchedulerService(enqueue_func=lambda _: None)
    now = datetime(2026, 10, 30, 14, tzinfo=UTC)
    assert service.run_once(now).tasks_created == 1
    assert service.run_once(now).tasks_created == 0
    with SessionLocal() as db:
        tasks = list(db.scalars(select(Task).where(Task.schedule_id == uuid.UUID(configured['schedule_id']))))
        assert len(tasks) == 1
        assert db.get(Schedule, uuid.UUID(configured['schedule_id'])).next_run_at == datetime(2026, 10, 31, 13, tzinfo=UTC)


@pytest.mark.anyio
async def test_pause_stops_new_steps_and_resume_needs_successful_pilot(client, setup):
    await configure(client)
    assert (await client.patch('/maintenance', json={'action': 'pause'})).json()['paused']
    result = await run(client, pilot=False)
    assert result['result']['blockers'] == ['maintenance_paused'] and not setup[1].requests
    assert (await client.patch('/maintenance', json={'action': 'resume'})).status_code == 409
    assert not (await client.patch('/maintenance', json={'action': 'disable'})).json()['enabled']


@pytest.mark.anyio
async def test_exclusions_and_private_policy_are_recorded_without_paid_calls(client, setup):
    api, models = setup
    await configure(client, exclusions=['fixture'])
    task = await run(client)
    assert task['result']['outcome'] == 'no_op' and not models.requests
    assert (await client.get('/maintenance/repositories')).json()[0]['state']['skipped'] == 'operator_exclusion'


@pytest.mark.anyio
async def test_real_provider_model_proof_required_to_activate(client, setup):
    await configure(client)
    task = await run(client)
    with SessionLocal() as db, db.begin():
        preview = db.get(Task, uuid.UUID(task['result']['preview_task_id']))
        result = copy.deepcopy(preview.result)
        result['calls']['reviewer']['metadata']['model'] = 'synthetic-unapproved-substitute'
        preview.result = result
    assert not (await client.get('/maintenance')).json()['pilot_succeeded']
    assert (await client.patch('/maintenance', json={'action': 'resume'})).status_code == 409


@pytest.mark.anyio
async def test_overlapping_trigger_is_quiet_and_does_not_duplicate_calls(client, setup):
    api, models = setup
    await configure(client)
    first = await client.post('/tasks', json={'type': 'documentation_maintenance', 'payload': {'pilot': True}})
    second = await client.post('/tasks', json={'type': 'documentation_maintenance', 'payload': {'pilot': True}})
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(10)
    models.after_editor = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(jobs.execute_task, first.json()['id'])
        try:
            assert entered.wait(10)
            overlap = jobs.execute_task(second.json()['id'])
            assert overlap['outcome'] == 'skipped_overlap' and not overlap['notify']
        finally:
            release.set()
        assert future.result(timeout=15)['outcome'] == 'merged'
    assert len(models.requests) == 2


@pytest.mark.anyio
async def test_atomic_daily_reservation_two_claimants(client, setup):
    await configure(client)
    roots = []
    with SessionLocal() as db, db.begin():
        control = db.get(MaintenanceControl, 1)
        for _ in range(2):
            task = Task(type=TaskType.DOCUMENTATION_MAINTENANCE, status=TaskStatus.RUNNING,
                        execution_id=uuid.uuid4(), payload={'pilot': True})
            db.add(task); db.flush()
            db.add(MaintenanceRun(task_id=task.id, configuration_sha256=control.configuration_sha256,
                reserved_microusd=0, state={'execution_id': str(task.execution_id)}))
            roots.append(task)
    def reserve(root):
        try: return maintenance_control.reserve_generation(root)
        except MaintenanceBlocked as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, roots))
    assert sorted(map(str, results)) == ['19456', 'daily_assessment_limit']
    with SessionLocal() as db:
        assert db.scalar(select(MaintenanceDay)).reserved_microusd == 19456


@pytest.mark.anyio
async def test_expired_daily_reservation_stops_reviewer_without_second_paid_call(client, setup, monkeypatch):
    api, models = setup
    await configure(client)
    current = maintenance_control.now_utc()
    def midnight():
        monkeypatch.setattr(maintenance_control, 'now_utc', lambda: current + timedelta(days=1))
    models.after_editor = midnight
    result = await run(client)
    assert result['result']['blockers'] == ['budget_reservation_expired']
    assert len(models.requests) == 1 and not api.writes


@pytest.mark.anyio
async def test_unchanged_merged_work_is_not_generated_again(client, setup):
    api, models = setup
    await configure(client)
    first = await run(client)
    assert first['result']['outcome'] == 'merged'
    second = await run(client)
    assert second['result']['outcome'] == 'no_op' and len(models.requests) == 2


@pytest.mark.anyio
async def test_publication_timeout_reconciles_next_run_without_model_retry(client, setup):
    api, models = setup
    await configure(client)
    api.timeout_after = 'PUT /pulls/1/merge'
    first = await run(client)
    assert first['result']['outcome'] == 'blocked' and api.pr['merged']
    second = await run(client)
    assert second['result']['outcome'] == 'merged'
    assert len(models.requests) == 2
    assert sum(k == 'POST /pulls' for k, _ in api.writes) == 1
    assert sum(k == 'PUT /pulls/1/merge' for k, _ in api.writes) == 1


@pytest.mark.anyio
async def test_repository_rotation_and_relevant_change_reassessment(client, setup, monkeypatch):
    api, models = setup
    other = MaintenanceGitHub()
    other.repo.update(id=12, name='second')
    api.repositories = [api.repo, other.repo]
    client_factory = maintenance.get_publication_client
    # Dispatch the second fixture repository through an independent remote state.
    def multi(request):
        if request.url.path.startswith('/repos/zkralec/second'):
            translated = request.url.copy_with(path=request.url.path.replace('/repos/zkralec/second', '/repos/zkralec/fixture'))
            return other(httpx.Request(request.method, translated, headers=request.headers, content=request.content))
        return api(request)
    sample = client_factory(False).settings
    def pubs(write):
        c = PublishingGitHubClient(sample, httpx.Client(transport=httpx.MockTransport(multi)))
        if not write: c.permissions = {k: 'read' for k in c.permissions}
        return c
    monkeypatch.setattr(maintenance, 'get_publication_client', pubs)
    monkeypatch.setattr(jobs, 'get_github_client', lambda: GitHubClient(sample, httpx.Client(transport=httpx.MockTransport(multi))))
    original = models.editor
    models.editor = lambda c: {**original(c), 'outcome': 'no_useful_change', 'edits': []}
    await configure(client)
    first = await run(client)
    assert first['result']['repository']['name'] == 'fixture'
    current = maintenance_control.now_utc()
    monkeypatch.setattr(maintenance_control, 'now_utc', lambda: current + timedelta(days=1))
    monkeypatch.setattr(maintenance, 'now_utc', lambda: current + timedelta(days=1))
    second = await run(client)
    assert second['result']['repository']['name'] == 'second'
    assert len(models.requests) == 2  # One editor, honest no-op, for each repository.


@pytest.mark.anyio
async def test_unchanged_blockers_notify_only_when_actionable(client, setup):
    api, models = setup
    api.repo['private'] = True
    await configure(client)
    first = await run(client)
    assert first['result']['notify']
    second = await run(client)
    assert second['result']['outcome'] == 'no_op' and not second['result']['notify']
    assert not models.requests


@pytest.mark.anyio
@pytest.mark.parametrize("pilot", [False, True])
async def test_pause_waits_for_inflight_call_and_stops_review(client, setup, pilot):
    import asyncio
    api, models = setup
    await configure(client)
    # Run as scheduled work with an authored prerequisite, then pause mid-call.
    with SessionLocal() as db, db.begin():
        control = db.get(MaintenanceControl, 1)
        control.paused = pilot
    from unittest.mock import patch
    entered, release = Event(), Event()
    def wait():
        entered.set(); assert release.wait(10)
    models.after_editor = wait
    accepted = await client.post('/tasks', json={'type':'documentation_maintenance','payload':{'pilot':pilot},'notification_policy':'always'})
    with patch.object(maintenance, 'pilot_succeeded', lambda *_: True), ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(jobs.execute_task,accepted.json()['id'])
        try:
            assert entered.wait(10)
            pause=asyncio.create_task(client.patch('/maintenance',json={'action':'pause'}))
            await asyncio.sleep(.1)
            assert not pause.done()  # The current call's ownership/pause fence is held.
            release.set()
            assert (await pause).json()['paused']
            result=future.result(timeout=15)
        finally: release.set()
    assert result['blockers']==['maintenance_paused'] and not result['notify']
    assert len(models.requests)==1 and not api.writes


@pytest.mark.anyio
async def test_blocked_repository_does_not_stop_ready_repository(client, setup, monkeypatch):
    api, models=setup
    other=MaintenanceGitHub(); other.repo.update(id=12,name='second')
    api.repositories=[api.repo,other.repo]
    sample=maintenance.get_publication_client(False).settings
    def multi(request):
        if request.url.path.startswith('/repos/zkralec/second'):
            url=request.url.copy_with(path=request.url.path.replace('/repos/zkralec/second','/repos/zkralec/fixture'))
            return other(httpx.Request(request.method,url,headers=request.headers,content=request.content))
        return api(request)
    monkeypatch.setattr(jobs,'get_github_client',lambda:GitHubClient(sample,httpx.Client(transport=httpx.MockTransport(multi))))
    monkeypatch.setattr(maintenance,'_readiness',lambda root,repo: (['github_approving_review_required'],{}) if repo['id']==11 else ([],{}))
    original=models.editor
    models.editor=lambda c:{**original(c),'outcome':'no_useful_change','edits':[]}
    await configure(client)
    with SessionLocal() as db,db.begin(): db.get(MaintenanceControl,1).paused=False
    monkeypatch.setattr(maintenance,'pilot_succeeded',lambda *_:True)
    result=await run(client,pilot=False)
    assert result['result']['repository']['name']=='second' and len(models.requests)==1
    with SessionLocal() as db:
        assert db.get(MaintenanceRepository,11).state['blocker']=='github_approving_review_required'


@pytest.mark.anyio
async def test_budget_exhaustion_notice_is_not_repeated_on_unchanged_attempt(client, setup):
    await configure(client,daily_budget_microusd=100)
    first=await run(client)
    second=await run(client)
    assert first['result']['notify'] and not second['result']['notify']
    assert second['result']['outcome']=='budget_exhausted' and not setup[1].requests


@pytest.mark.anyio
async def test_read_scoped_missing_capabilities_are_read_with_granted_write_scope(client, setup):
    api,models=setup
    original=api.dispatch
    scope={'write':False}
    original_call=api.__class__.__call__
    # Simulate GitHub's actual omission, found by the paid live pilot.
    def metadata(method,path,request,body):
        status,data=original(method,path,request,body)
        if method=='GET' and path=='':
            data=copy.deepcopy(data)
            if not scope['write']: data.pop('allow_merge_commit',None)
        return status,data
    api.dispatch=metadata
    class Transport:
        def __call__(self,request):
            if request.url.path.endswith('/access_tokens'):
                scope['write']=json.loads(request.content)['permissions']['contents']=='write'
            return api(request)
    sample=maintenance.get_publication_client(False).settings
    c=PublishingGitHubClient(sample,httpx.Client(transport=httpx.MockTransport(Transport())))
    c.permissions={k:'read' for k in c.permissions}
    c.authenticate('fixture')
    assert c.repository_metadata('/repos/zkralec/fixture')['allow_merge_commit'] is True
    assert c.repository_writes_enabled is False
    from personal_dot.github_errors import GitHubError
    with pytest.raises(GitHubError): c.request('POST','/repos/zkralec/fixture/pulls',{})
    assert not api.writes
    c.close()


@pytest.mark.anyio
async def test_resume_exact_approved_candidate_without_more_model_calls(client, setup, monkeypatch):
    api,models=setup
    await configure(client)
    original=maintenance._readiness
    monkeypatch.setattr(maintenance,'_readiness',lambda *_:(['metadata_missing'],{}))
    first=await run(client)
    assert first['result']['outcome']=='blocked' and len(models.requests)==2
    preview_id=first['result']['preview_task_id']
    monkeypatch.setattr(maintenance,'_readiness',original)
    response=await client.post('/tasks',json={'type':'documentation_maintenance',
        'payload':{'pilot':True,'resume_preview_task_id':preview_id}})
    run_queued_jobs()
    task=(await client.get('/tasks/'+response.json()['id'])).json()
    assert task['result']['outcome']=='merged' and len(models.requests)==2
    assert task['result']['preview_task_id']==preview_id
    assert task['result']['usage']['total_tokens']==40
    assert (await client.get('/maintenance')).json()['pilot_succeeded']
    repeated=await run(client)
    assert repeated['result']['outcome']=='no_op' and len(models.requests)==2
