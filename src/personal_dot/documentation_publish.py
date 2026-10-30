"""Bounded publication controller; PostgreSQL owns intent, GitHub owns outcomes.

Each external write holds the task claim row lock through reconciliation and
outcome persistence. Recovery cannot revoke an in-flight claim under that lock.
A process crash leaves durable intent; the next explicit attempt reads GitHub
before it may send the same operation. No model or Git subprocess runs here.
"""

import copy
import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from sqlalchemy import select, text

from personal_dot.config import get_settings
from personal_dot.db import SessionLocal, engine
from personal_dot.documentation_git import AUTHOR, object_plan, verify_commit
from personal_dot.documentation_policy import digest
from personal_dot.documentation_preview import seal_documentation_result
from personal_dot.documentation_schemas import PublicationRequest
from personal_dot.github_errors import GitHubError
from personal_dot.github_publication import PublishingGitHubClient, check_evidence, merge_requirements
from personal_dot.models import DocumentationPublication, Task, TaskStatus, TaskType
from personal_dot.repository_inspection import identity

POLICY = 'documentation-publishing-v1'
IMPLEMENTATION = digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
    (Path(__file__), Path(__file__).with_name('github_publication.py'), Path(__file__).with_name('documentation_git.py'), Path(__file__).with_name('github.py'))})


class PublicationBlocked(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__('Documentation publication blocked: ' + code)


def get_publication_client(write: bool) -> PublishingGitHubClient:
    client = PublishingGitHubClient(get_settings())
    if not write:
        client.permissions = {k: 'read' for k in client.permissions}
    return client


def reviewed_source(session: Any, preview_id: uuid.UUID) -> tuple[Task, str]:
    source = session.scalar(select(Task).where(Task.id == preview_id).with_for_update())
    if source is None or source.type != TaskType.DOCUMENTATION_PREVIEW or source.status != TaskStatus.SUCCEEDED:
        raise PublicationBlocked('approved_preview_required')
    result = source.result or {}
    sealed = seal_documentation_result(session, source, copy.deepcopy(result))
    if (sealed != result or result.get('base_commit') != source.payload['context']['base_commit']
            or result.get('repository') != source.payload['context']['repository']
            or result.get('input_sha256') != source.payload['input_sha256']
            or result.get('policy') != source.payload['policy']
            or result.get('outcome') != 'approved_candidate'
            or result.get('review', {}).get('decision') != 'approve'
            or not result.get('review', {}).get('valid') or not result.get('validation', {}).get('passed')
            or any(result.get('calls', {}).get(role, {}).get('status') != 'completed' for role in ('editor', 'reviewer'))):
        raise PublicationBlocked('review_or_policy_invalidated')
    settings = get_settings()
    if {'name': settings.github_commit_author_name, 'email': settings.github_commit_author_email} != AUTHOR:
        raise PublicationBlocked('configured_author_mismatch')
    binding = digest({'policy': POLICY, 'implementation': IMPLEMENTATION, 'prepared': source.payload,
                      'result': result, 'author': AUTHOR, 'merge_method': 'merge'})
    return source, binding


def _owner(session: Any, task: Task) -> Task:
    current = session.scalar(select(Task).where(Task.id == task.id).with_for_update())
    if current is None or current.status != TaskStatus.RUNNING or current.execution_id != task.execution_id:
        raise PublicationBlocked('execution_ownership_lost')
    return current


class Controller:
    def __init__(self, task: Task, client: PublishingGitHubClient, preview_id: uuid.UUID, binding: str):
        self.task, self.client, self.preview_id, self.binding = task, client, preview_id, binding
        self.state: dict[str, Any] = {}
        self.root = ''
        self.repository: dict = {}

    def save(self) -> None:
        with SessionLocal() as session, session.begin():
            _owner(session, self.task)
            job = session.get(DocumentationPublication, self.preview_id)
            assert job is not None
            job.state = copy.deepcopy(self.state)

    def remote_gate(self) -> tuple[dict, list[str], list[dict]]:
        raw = self.client.get(self.root)
        repo = identity(raw, self.client)
        if (repo['id'] != self.repository['id'] or repo['name'] != self.repository['name']
                or repo['owner_id'] != self.repository['owner_id']
                or repo['private'] is not False or not repo['maintenance_eligible']
                or repo.get('default_branch') != self.state['base_branch']):
            raise PublicationBlocked('repository_identity_changed')
        requirements = self.client.requirements(self.root, self.state['base_branch'], self.state['branch'])
        blockers, checks = merge_requirements(requirements, raw)
        if requirements['base_sha'] != self.state['base_commit']:
            blockers.append('base_changed_requires_new_inspection_and_review')
        self.state['requirements'] = requirements
        self.state['requirements_sha256'] = digest(requirements)
        return requirements, blockers, checks

    def operation(self, key: str, call: Callable[[], dict], *, merged: bool = False) -> dict:
        """Two transactions: durable intent, then fenced reconciliation/write/outcome."""
        journal = self.state.setdefault('operations', {})
        previous = journal.get(key, {})
        journal[key] = {**previous, 'status': 'intent', 'intent_at': datetime.now(UTC).isoformat(),
                        'write_attempts': previous.get('write_attempts', 0) + 1}
        self.save()
        error: BaseException | None = None
        result: dict = {}
        with SessionLocal() as session, session.begin():
            _owner(session, self.task)
            source, binding = reviewed_source(session, self.preview_id)
            if binding != self.binding or not get_settings().docs_publish_live_enabled:
                raise PublicationBlocked('authorization_invalidated')
            job = session.scalar(select(DocumentationPublication).where(
                DocumentationPublication.preview_task_id == self.preview_id).with_for_update())
            assert job is not None
            try:
                # Cleanup has a different gate: the persisted, verified merge and
                # exact job-owned ref must remain identifiable after base advances.
                if not merged:
                    _, blockers, _ = self.remote_gate()
                    if blockers:
                        raise PublicationBlocked(blockers[0])
                self.state['current_operation'] = key
                self.state['write_attempts'] = previous.get('write_attempts', 0)
                result = call()
                journal[key].update(status='completed', result=result)
            except BaseException as exc:
                # RQ timeouts derive from BaseException. Persist only fixed codes.
                journal[key].update(status='unknown', error=exc.code if isinstance(exc, (GitHubError, PublicationBlocked)) else 'operation_interrupted')
                error = exc
            journal[key]['write_attempts'] = self.state.pop('write_attempts', 0)
            self.state.pop('current_operation', None)
            job.state = copy.deepcopy(self.state)
        if error:
            raise error
        return result

    def write(self, method: str, path: str, body: dict | None = None) -> dict:
        # Called only from operation() while the current task row is locked.
        if self.state['write_attempts'] >= 3:
            raise PublicationBlocked('operation_retry_limit')
        self.state['write_attempts'] += 1
        return self.client.request(method, path, body)

    def run(self, source: Task) -> dict:
        self.repository = source.payload['context']['repository']
        self.root = f"/repos/{get_settings().github_owner}/{self.repository['name']}"
        self.client.authenticate(self.repository['name'])
        with SessionLocal() as session, session.begin():
            _owner(session, self.task)
            job = session.get(DocumentationPublication, self.preview_id)
            if job is None:
                active = session.scalar(select(DocumentationPublication).where(
                    DocumentationPublication.repository_id == self.repository['id'],
                    DocumentationPublication.completed.is_(False)))
                if active:
                    raise PublicationBlocked('another_maintenance_job_active')
                raw = self.client.get(self.root)
                self.state = {'policy_version': POLICY, 'implementation_sha256': IMPLEMENTATION,
                    'binding_sha256': self.binding, 'preview_task_id': str(self.preview_id),
                    'repository_id': self.repository['id'], 'repository_name': self.repository['name'],
                    'owner': get_settings().github_owner, 'base_commit': source.result['base_commit'],
                    'base_branch': raw['default_branch'], 'branch': 'dot/docs-' + self.preview_id.hex,
                    'created_at': datetime.now(UTC).replace(microsecond=0).isoformat(),
                    'published': False, 'merged': False, 'deployed': False, 'operations': {}}
                job = DocumentationPublication(preview_task_id=self.preview_id, repository_id=self.repository['id'], state=self.state)
                session.add(job)
            else:
                self.state = copy.deepcopy(job.state)
                if self.state['binding_sha256'] != self.binding:
                    raise PublicationBlocked('authorization_invalidated')
                if job.completed:
                    return self.state
        # Reconcile an existing PR before any freshness gate: merge acceptance can
        # advance the base while the preceding response is lost.
        if self.state.get('pr_number'):
            pr = self.client.get(self.root + '/pulls/' + str(self.state['pr_number']))
            if pr.get('merged'):
                return self.finish_merge(pr)
        _, blockers, required = self.remote_gate()
        self.state['blockers'] = blockers
        self.save()
        if blockers:
            return self.state
        if 'plan' not in self.state:
            ref = self.client.optional(self.root + '/git/ref/heads/' + self.state['branch'])
            if ref:
                raise PublicationBlocked('temporary_branch_already_exists')
            self.state['branch_observed_absent'] = True
            self.state['plan'] = object_plan(self.client, self.root,
                {**source.payload, 'candidate': source.result['candidate']}, self.state['created_at'])
            self.state['plan_sha256'] = digest(self.state['plan'])
            self.save()
        plan = self.state['plan']
        if digest(plan) != self.state['plan_sha256']:
            raise PublicationBlocked('publication_plan_changed')
        head = plan[-1]['sha']
        for item in plan:
            def publish_object(item=item):
                path = self.root + '/git/' + item['kind']
                remote = self.client.optional(path + '/' + item['sha'])
                if remote is None:
                    remote = self.write('POST', path, item['body'])
                if remote['sha'] != item['sha']:
                    raise PublicationBlocked('git_object_identity_mismatch')
                return {'sha': item['sha']}
            self.operation('object:' + item['sha'], publish_object)
        self.state['attribution'] = verify_commit(self.client, self.root, plan)
        self.save()

        def branch():
            path = self.root + '/git/ref/heads/' + self.state['branch']
            ref = self.client.optional(path)
            if ref is None:
                ref = self.write('POST', self.root + '/git/refs', {'ref': 'refs/heads/' + self.state['branch'], 'sha': head})
            if ref['object']['sha'] != head or not self.state['branch_observed_absent']:
                raise PublicationBlocked('temporary_branch_changed')
            return {'ref': 'refs/heads/' + self.state['branch'], 'sha': head}
        self.operation('branch', branch)
        marker = 'DOT publication ' + str(self.preview_id) + '\nBinding: ' + self.binding

        def pull_request():
            ref = self.client.optional(self.root + '/git/ref/heads/' + self.state['branch'])
            if ref is None or ref['object']['sha'] != head:
                raise PublicationBlocked('temporary_branch_changed')
            pulls = self.client.listing(self.root + '/pulls?state=all&head=' + quote(get_settings().github_owner + ':' + self.state['branch'], safe=''))
            if len(pulls) > 1:
                raise PublicationBlocked('duplicate_remote_pull_requests')
            pr = pulls[0] if pulls else self.write('POST', self.root + '/pulls', {
                'title': 'docs: clarify implemented behavior', 'body': marker,
                'head': self.state['branch'], 'base': self.state['base_branch']})
            if pr.get('body') != marker:
                raise PublicationBlocked('pull_request_ownership_mismatch')
            return {'number': pr['number']}
        pr_record = self.operation('pull_request', pull_request)
        self.state['pr_number'] = pr_record['number']
        self.state['published'] = True
        self.save()
        settings = get_settings()
        waitable = {'checks_pending_or_failed', 'required_check_missing', 'github_mergeability_blocked_or_pending'}
        for poll in range(settings.docs_publish_check_polls):
            _, restrictions, required = self.remote_gate()
            pr = self.client.get(self.root + '/pulls/' + str(self.state['pr_number']))
            if pr.get('merged'):
                return self.finish_merge(pr)
            blockers, evidence = self.verify_pull(pr, source, required)
            blockers = sorted(set(restrictions + blockers))
            self.state.update(checks=evidence, blockers=blockers, check_poll=poll + 1)
            self.save()
            if not blockers or any(b not in waitable for b in blockers):
                break
            if poll + 1 < settings.docs_publish_check_polls:
                time.sleep(settings.docs_publish_poll_seconds)
        if blockers:
            return self.state

        def merge():
            current = self.client.get(self.root + '/pulls/' + str(self.state['pr_number']))
            if current.get('merged'):
                return {'reconciled': True}
            requirements, restrictions, checks = self.remote_gate()
            blockers, evidence = self.verify_pull(current, source, checks)
            if restrictions or blockers:
                raise PublicationBlocked((restrictions + blockers)[0])
            authorization = {'repository_id': self.repository['id'], 'base_commit': self.state['base_commit'],
                'candidate_sha256': source.result['candidate_sha256'], 'head_commit': head,
                'review_record_sha256': source.result['review_record_sha256'],
                'checks': evidence, 'requirements': requirements, 'policy_version': POLICY,
                'policy_implementation': IMPLEMENTATION, 'preview_binding': self.binding}
            # This record is committed before the merge operation's separate intent
            # transaction below. Recomputed evidence must match exactly here.
            if digest(authorization) != self.state['authorization_sha256']:
                raise PublicationBlocked('merge_inputs_changed_requires_revalidation')
            response = self.write('PUT', self.root + '/pulls/' + str(self.state['pr_number']) + '/merge',
                                  {'sha': head, 'merge_method': 'merge'})
            if response.get('merged') is not True:
                raise PublicationBlocked('github_merge_rejected')
            return {'sha': response['sha']}
        requirements = self.state['requirements']
        authorization = {'repository_id': self.repository['id'], 'base_commit': self.state['base_commit'],
            'candidate_sha256': source.result['candidate_sha256'], 'head_commit': head,
            'review_record_sha256': source.result['review_record_sha256'], 'checks': evidence,
            'requirements': requirements, 'policy_version': POLICY,
            'policy_implementation': IMPLEMENTATION, 'preview_binding': self.binding}
        self.state['authorization'] = authorization
        self.state['authorization_sha256'] = digest(authorization)
        self.save()
        self.operation('merge', merge)
        return self.finish_merge(self.client.get(self.root + '/pulls/' + str(self.state['pr_number'])))

    def verify_pull(self, pr: dict, source: Task, required: list[dict]) -> tuple[list[str], dict]:
        head = self.state['plan'][-1]['sha']
        blockers: list[str] = []
        if (pr['head']['sha'] != head or pr['base']['sha'] != self.state['base_commit']
                or pr['head']['ref'] != self.state['branch'] or pr['base']['ref'] != self.state['base_branch']
                or pr['head']['repo']['id'] != self.repository['id'] or pr['base']['repo']['id'] != self.repository['id']):
            blockers.append('pull_request_revision_changed_requires_new_review')
            return blockers, {'head_sha': pr['head']['sha'], 'revision_changed': True}
        if pr.get('draft') or pr['state'] != 'open' or pr.get('mergeable') is not True or pr.get('mergeable_state') != 'clean':
            blockers.append('github_mergeability_blocked_or_pending')
        files = self.client.listing(self.root + '/pulls/' + str(pr['number']) + '/files')
        expected = {edit['path'] for edit in source.result['candidate']['editor']['edits']}
        blob_shas = {x['sha'] for x in self.state['plan'] if x['kind'] == 'blobs'}
        if ({f['filename'] for f in files} != expected or len(files) != len(expected)
                or any(f['status'] != 'modified' or f['sha'] not in blob_shas for f in files)):
            blockers.append('published_diff_changed')
        commits = self.client.listing(self.root + '/pulls/' + str(pr['number']) + '/commits')
        if [c['sha'] for c in commits] != [head]:
            blockers.append('published_commits_changed')
        verify_commit(self.client, self.root, self.state['plan'])
        check_blockers, evidence = check_evidence(self.client, self.root, head, required)
        # A real GitHub changes-requested decision must never be ignored merely
        # because this repository currently requires zero approving reviews.
        reviews = self.client.listing(self.root + '/pulls/' + str(pr['number']) + '/reviews')
        latest: dict[int, dict] = {}
        for review in reviews:
            if review['state'] != 'COMMENTED':
                latest[review['user']['id']] = review
        if any(r['state'] == 'CHANGES_REQUESTED' for r in latest.values()):
            blockers.append('github_changes_requested')
        self.state['diff_verification'] = {'candidate_sha256': source.result['candidate_sha256'],
            'reviewed_diff_sha256': digest(source.result['candidate']['diff']), 'head_commit': head,
            'passed': not blockers}
        return sorted(set(blockers + check_blockers)), evidence

    def finish_merge(self, pr: dict) -> dict:
        head = self.state['plan'][-1]['sha']
        if not pr.get('merged') or pr['head']['sha'] != head:
            raise PublicationBlocked('merge_outcome_not_confirmed')
        commit = self.client.get(self.root + '/git/commits/' + pr['merge_commit_sha'])
        # Expected-head protects the head; REST offers no expected-base parameter.
        # Verify both parents/tree after acceptance and report any race explicitly.
        if ([p['sha'] for p in commit['parents']] != [self.state['base_commit'], head]
                or commit['tree']['sha'] != self.state['plan'][-1]['body']['tree']):
            self.state.update(merged=True, merge_commit=pr['merge_commit_sha'], blockers=['merged_revision_requires_owner_reconciliation'])
            self.save()
            return self.state
        verify_commit(self.client, self.root, self.state['plan'])
        self.state.update(published=True, merged=True, merge_commit=pr['merge_commit_sha'], deployed=False, blockers=[])
        self.save()  # Merge outcome is durable before cleanup can start.

        def cleanup():
            path = self.root + '/git/refs/heads/' + self.state['branch']
            ref = self.client.optional(self.root + '/git/ref/heads/' + self.state['branch'])
            if ref is not None:
                if ref['object']['sha'] != head or 'branch' not in self.state['operations']:
                    raise PublicationBlocked('temporary_branch_changed_no_cleanup')
                self.write('DELETE', path)
            return {'deleted': True}
        self.operation('cleanup', cleanup, merged=True)
        self.state['branch_deleted'] = True
        with SessionLocal() as session, session.begin():
            _owner(session, self.task)
            job = session.get(DocumentationPublication, self.preview_id)
            job.state, job.completed = copy.deepcopy(self.state), True
        return self.state



def reconcile_blocked(task: Task, preview_id: uuid.UUID, reason: str) -> dict:
    """Observe prior side effects even when fresh authorization is unavailable."""
    with SessionLocal() as session:
        job = session.get(DocumentationPublication, preview_id)
        if job is None:
            return {}
        state = copy.deepcopy(job.state)
    if state.get('owner') != get_settings().github_owner:
        return state  # Never authenticate as a newly configured owner for old work.
    with engine.connect() as connection, connection.begin():
        if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:repository, 743202))'),
                                 {'repository': str(state['repository_id'])}):
            return state
        client = get_publication_client(False)
        try:
            client.authenticate(state['repository_name'])
            root = f"/repos/{state['owner']}/{state['repository_name']}"
            if identity(client.get(root), client)['id'] != state['repository_id']:
                return state
            if not state.get('pr_number') and 'pull_request' in state['operations']:
                pulls = client.listing(root + '/pulls?state=all&head=' + quote(state['owner'] + ':' + state['branch'], safe=''))
                marker = 'DOT publication ' + str(preview_id) + '\nBinding: ' + state['binding_sha256']
                if len(pulls) == 1 and pulls[0].get('body') == marker:
                    state['pr_number'] = pulls[0]['number']
            if state.get('pr_number'):
                pr = client.get(root + '/pulls/' + str(state['pr_number']))
                if pr['head']['sha'] == state['plan'][-1]['sha'] and pr['head']['repo']['id'] == state['repository_id']:
                    state['published'] = True
                    if pr.get('merged'):
                        state.update(merged=True, merge_commit=pr['merge_commit_sha'], deployed=False)
                        commit = client.get(root + '/git/commits/' + pr['merge_commit_sha'])
                        state['remote_merge_verified'] = (
                            [p['sha'] for p in commit['parents']] == [state['base_commit'], state['plan'][-1]['sha']]
                            and commit['tree']['sha'] == state['plan'][-1]['body']['tree'])
            state['blockers'] = [reason]
            state['reconciled_read_only_at'] = datetime.now(UTC).isoformat()
            with SessionLocal() as session, session.begin():
                _owner(session, task)
                session.get(DocumentationPublication, preview_id).state = copy.deepcopy(state)
            return state
        finally:
            client.close()


def execute_publication(task: Task) -> tuple[dict, dict]:
    request = PublicationRequest.model_validate(task.payload)
    controller: Controller | None = None
    client: PublishingGitHubClient | None = None
    try:
        with SessionLocal() as session, session.begin():
            _owner(session, task)
            source = session.get(Task, request.preview_task_id)
            if source is None or source.type != TaskType.DOCUMENTATION_PREVIEW:
                raise PublicationBlocked('approved_preview_required')
            repository_id = source.payload['context']['repository']['id']
        if request.allow_publish and not get_settings().docs_publish_live_enabled:
            raise PublicationBlocked('publishing_operator_gate_disabled')
        with engine.connect() as connection, connection.begin():
            if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:repository, 743202))'), {'repository': str(repository_id)}):
                raise PublicationBlocked('another_maintenance_execution_active')
            with SessionLocal() as session, session.begin():
                _owner(session, task)
                source, binding = reviewed_source(session, request.preview_task_id)
                if repository_id != source.payload['context']['repository']['id']:
                    raise PublicationBlocked('repository_identity_changed')
            client = get_publication_client(request.allow_publish)
            controller = Controller(task, client, request.preview_task_id, binding)
            if not request.allow_publish:
                repository = source.payload['context']['repository']
                controller.repository = repository
                controller.root = f"/repos/{get_settings().github_owner}/{repository['name']}"
                client.authenticate(repository['name'])
                controller.state = {'base_commit': source.result['base_commit'],
                    'base_branch': client.get(controller.root)['default_branch'],
                    'branch': 'dot/docs-' + request.preview_task_id.hex}
                _, blockers, checks = controller.remote_gate()
                result = {**controller.state, 'mode': 'preview', 'blockers': blockers,
                          'required_checks': checks, 'published': False, 'merged': False, 'deployed': False}
            else:
                result = controller.run(source)
        return result, {'handler': 'documentation_publish', 'success': not result.get('blockers')}
    except (PublicationBlocked, GitHubError, KeyError, TypeError, ValueError) as exc:
        result = copy.deepcopy(controller.state) if controller else {}
        code = exc.code if isinstance(exc, (PublicationBlocked, GitHubError)) else 'invalid_response'
        if code in {'review_or_policy_invalidated', 'authorization_invalidated', 'configured_author_mismatch', 'publishing_operator_gate_disabled'}:
            try:
                result = reconcile_blocked(task, request.preview_task_id, code) or result
            except (GitHubError, KeyError, TypeError, ValueError):
                result['reconciliation_pending'] = True
        result.update(blockers=[code], published=result.get('published', False),
                      merged=result.get('merged', False), deployed=False)
        if controller and controller.state.get('binding_sha256') == binding:
            controller.state = result
            controller.save()
        return result, {'handler': 'documentation_publish', 'success': False,
                        'request_outcome': 'unknown' if isinstance(exc, GitHubError) else 'blocked'}
    finally:
        if client:
            client.close()
