"""One bounded account-wide maintenance run, using the existing task handlers."""

import copy
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from personal_dot.config import get_settings
from personal_dot.db import SessionLocal, engine
from personal_dot.documentation_errors import DocumentationError
from personal_dot.documentation_policy import (EXECUTABLE, canonical, digest, eligible_path,
                                                policy_configuration, text_hash)
from personal_dot.documentation_preview import WORKFLOW_SHA256, prepare_documentation
from personal_dot.documentation_publish import get_publication_client
from personal_dot.github_errors import GitHubError
from personal_dot.github_publication import merge_requirements
from personal_dot.maintenance_control import (MaintenanceBlocked, PRICING, configuration_binding,
    now_utc, pilot_succeeded, reserve_generation, root_permission)
from personal_dot.maintenance_schemas import MaintenanceConfiguration, MaintenanceRequest
from personal_dot.models import (DocumentationPublication, MaintenanceAssessment, MaintenanceControl,
    MaintenanceRepository, MaintenanceRun, NotificationPolicy, Task, TaskStatus, TaskType)

MAX_REPOSITORIES_PER_RUN = 32


def _patch(root: Task, **fields: Any) -> dict:
    with SessionLocal() as session, session.begin():
        current = session.scalar(select(Task).where(Task.id == root.id).with_for_update())
        if current.status != TaskStatus.RUNNING or current.execution_id != root.execution_id:
            raise MaintenanceBlocked('execution_ownership_lost')
        run = session.get(MaintenanceRun, root.id)
        run.state = {**run.state, **copy.deepcopy(fields)}
        return copy.deepcopy(run.state)


def _child(root: Task, kind: TaskType, payload: dict, key: str) -> Task:
    with SessionLocal() as session, session.begin():
        _, run = root_permission(session, root)
        children = dict(run.state.get('children', {}))
        if key not in children:
            prepared = prepare_documentation(payload, session) if kind == TaskType.DOCUMENTATION_PREVIEW else payload
            child = Task(type=kind, status=TaskStatus.QUEUED, payload=prepared,
                         notification_policy=NotificationPolicy.NONE, maintenance_parent_id=root.id)
            session.add(child)
            session.flush()
            children[key] = str(child.id)
            run.state = {**run.state, 'children': children, 'stage': key}
        child_id = children[key]
    from personal_dot.jobs import execute_task
    try:
        execute_task(child_id)
    except RuntimeError:
        pass  # The existing job boundary has already persisted its safe failure.
    with SessionLocal() as session:
        child = session.get(Task, uuid.UUID(child_id))
        if child.status not in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.UNCERTAIN}:
            raise MaintenanceBlocked('child_outcome_pending')
        return child


def _refresh(root: Task, config: MaintenanceConfiguration) -> None:
    with SessionLocal() as session:
        control = session.get(MaintenanceControl, 1)
        if control.discovered_at and now_utc() - control.discovered_at < timedelta(hours=config.discovery_hours):
            return
    child = _child(root, TaskType.GITHUB_DISCOVER, {'page': 1}, 'discovery')
    if child.status != TaskStatus.SUCCEEDED or not child.result.get('complete'):
        raise MaintenanceBlocked('discovery_incomplete')
    repos = child.result['repositories']
    if len(repos) > 1000:
        raise MaintenanceBlocked('discovery_pool_limit')
    with SessionLocal() as session, session.begin():
        control, _ = root_permission(session, root)
        for row in session.scalars(select(MaintenanceRepository)):
            row.available = False
        for repo in repos:
            row = session.get(MaintenanceRepository, repo['id'])
            if row is None:
                row = MaintenanceRepository(repository_id=repo['id'], name=repo['name'], identity=repo, available=True, state={})
                session.add(row)
            row.name, row.identity, row.available = repo['name'], repo, True
        control.discovered_at = now_utc()
        control.discovery = {**control.discovery, 'task_id': str(child.id), 'accessible_count': len(repos),
                             'eligible_count': sum(bool(r['maintenance_eligible']) for r in repos),
                             'coverage': child.result.get('coverage'), 'complete': True}


def assessment_fingerprint(snapshot: dict) -> str:
    settings = get_settings()
    return digest({'files': sorted((f['path'], f['sha256']) for f in snapshot['files']
                                  if eligible_path(f['path'], target=False)),
                   'policy': policy_configuration(), 'workflow_sha256': WORKFLOW_SHA256,
                   'models': [settings.docs_preview_editor_model or settings.openai_model,
                              settings.docs_preview_reviewer_model or settings.openai_model]})


def choose_inputs(snapshot: dict, inspection_id: uuid.UUID, config: MaintenanceConfiguration) -> dict | None:
    targets = [f for f in snapshot['files'] if eligible_path(f['path'], target=True)
               and not EXECUTABLE.search(f['text']) and not f['text'].startswith('---\n')]
    source = [f for f in snapshot['files'] if eligible_path(f['path'], target=False)
              and not f['path'].endswith('.md') and len(f['text'].splitlines()) > 0]
    if not targets or not source:
        return None
    targets.sort(key=lambda f: (f['path'] != 'README.md', len(f['text']), f['path']))
    source.sort(key=lambda f: (not bool(re.search(r'(?m)^(?:async )?def [a-zA-Z]|^class ', f['text'])), f['path']))
    # This is an initial assessment/relevant-change signal, not proof of a gap.
    # The editor may return no_useful_change and is never instructed to force an edit.
    for target in targets[:3]:
        evidence = []
        for f in source[:3]:
            lines = f['text'].splitlines()
            public = next((i for i, line in enumerate(lines) if re.match(r'^(?:async )?def [A-Za-z]|^class ', line)), 0)
            start, end = public + 1, min(len(lines), public + 80)
            evidence.append({'path': f['path'], 'sha256': f['sha256'], 'start_line': start, 'end_line': end})
        payload = {'inspection_task_id': str(inspection_id), 'base_commit': snapshot['commit'],
            'targets': [{'path': target['path'], 'sha256': target['sha256']}], 'evidence': evidence,
            'inputs_reviewed_for_model': True, 'allow_paid_model': True,
            'budget': {'max_input_bytes_per_call': config.max_input_bytes_per_call,
                       'max_output_tokens_per_call': config.max_output_tokens_per_call}}
        with SessionLocal() as session:
            try:
                prepare_documentation(payload, session)
                return payload
            except DocumentationError:
                continue
    return None


def _repo_state(root: Task, repository_id: int, **fields: Any) -> bool:
    with SessionLocal() as session, session.begin():
        root_permission(session, root)
        row = session.get(MaintenanceRepository, repository_id)
        old = row.state.get('blocker')
        new = fields.get('blocker')
        actionable = bool(new and old != new)
        row.state = {**row.state, **fields}
        row.last_checked_at = now_utc()
        return actionable


def _readiness(root: Task, repository: dict) -> tuple[list[str], dict]:
    client = get_publication_client(False)
    try:
        client.authenticate(repository['name'])
        base = f"/repos/{get_settings().github_owner}/{repository['name']}"
        raw = client.repository_metadata(base)
        if raw['id'] != repository['id']:
            return ['repository_identity_changed'], {}
        requirements = client.requirements(base, raw['default_branch'], 'dot/docs-' + root.id.hex)
        blockers, checks = merge_requirements(requirements, raw)
        return blockers, {'requirements': requirements, 'required_checks': checks}
    except GitHubError as exc:
        return ['github:' + exc.code], {}
    finally:
        client.close()


def _remember(root: Task, repository_id: int, fingerprint: str, outcome: str, task: Task, state: dict | None = None) -> None:
    with SessionLocal() as session, session.begin():
        root_permission(session, root)
        assessment = session.get(MaintenanceAssessment, (repository_id, fingerprint))
        if assessment is None:
            assessment = MaintenanceAssessment(repository_id=repository_id, fingerprint=fingerprint,
                outcome=outcome, assessed_at=now_utc(), task_id=task.id, state=state or {})
            session.add(assessment)
        else:
            assessment.outcome, assessment.assessed_at, assessment.task_id = outcome, now_utc(), task.id
            assessment.state = state or {}


def _verify_live(publication: dict, repository: dict) -> dict:
    client = get_publication_client(False)
    try:
        client.authenticate(repository['name'])
        base = f"/repos/{get_settings().github_owner}/{repository['name']}"
        head = publication['plan'][-1]['sha']
        remote = client.get(base + '/commits/' + head)
        author = remote.get('author') or {}
        git_author = remote['commit']['author']
        settings = get_settings()
        associated = (author.get('login', '').lower() == settings.github_owner.lower()
            and author.get('id') == repository['owner_id']
            and git_author['name'] == settings.github_commit_author_name
            and git_author['email'] == settings.github_commit_author_email)
        return {'author_associated': associated, 'author_login': author.get('login'),
                'author_id': author.get('id'), 'author_name': git_author['name'], 'author_email': git_author['email'],
                'candidate_commit': head, 'merge_commit': publication['merge_commit'],
                'commit_url': base.replace('/repos/', 'https://github.com/') + '/commit/' + head,
                'merge_url': base.replace('/repos/', 'https://github.com/') + '/commit/' + publication['merge_commit'],
                'pr_url': base.replace('/repos/', 'https://github.com/') + '/pull/' + str(publication['pr_number']),
                'exact_tree_verified': not publication.get('blockers')}
    finally:
        client.close()


def _publish(root: Task, preview_id: uuid.UUID, repository: dict) -> dict:
    child = _child(root, TaskType.DOCUMENTATION_PUBLISH,
                   {'preview_task_id': str(preview_id), 'allow_publish': True}, 'publish:' + str(preview_id))
    result = child.result or {}
    with SessionLocal() as session:
        source = session.get(Task, preview_id)
        usage = (source.execution_metadata or {}).get('usage', {})
    _patch(root, usage=usage, estimated_standard_cost_usd=(usage.get('input_tokens', 0)*.10 + usage.get('output_tokens', 0)*.50)/1_000_000, billing='not_observed', preview_task_id=str(preview_id), publication_task_id=str(child.id), publication=result)
    if result.get('merged') and not result.get('blockers'):
        verification = _verify_live(result, repository)
        with SessionLocal() as session:
            inspection_id = uuid.UUID(source.payload['request']['inspection_task_id'])
            snapshot = copy.deepcopy(session.get(Task, inspection_id).result)
        _remember(root, repository['id'], assessment_fingerprint(snapshot), 'addressed', source)
        for f in snapshot['files']:
            edits = [e for e in source.result['candidate']['editor']['edits'] if e['path'] == f['path']]
            if edits:
                lines = f['text'].splitlines(keepends=True)
                for edit in sorted(edits, key=lambda e: e['after_line'], reverse=True):
                    lines.insert(edit['after_line'], edit['text'])
                f['sha256'] = text_hash(''.join(lines))
        _remember(root, repository['id'], assessment_fingerprint(snapshot), 'addressed', source)
        _repo_state(root, repository['id'], blocker=None, last_merged_commit=result['merge_commit'])
        return {'outcome': 'merged', 'notify': True, 'live_verification': verification,
                'publication_task_id': str(child.id), 'repository': repository, 'deployed': False}
    return {'outcome': 'blocked', 'notify': 'maintenance_paused' not in result.get('blockers', []), 'blockers': result.get('blockers') or ['publication_failed'],
            'publication_task_id': str(child.id), 'repository': repository}


def _assess(root: Task, repository: dict, inspection: Task, fingerprint: str, payload: dict, readiness: list[str]) -> dict:
    reserve_generation(root)
    _patch(root, repository=repository, inspection_task_id=str(inspection.id), assessment_fingerprint=fingerprint)
    # Remember the paid intent before generation so an interrupted analysis is not reopened.
    _remember(root, repository['id'], fingerprint, 'assessment_started', inspection)
    preview = _child(root, TaskType.DOCUMENTATION_PREVIEW, payload, 'preview')
    result = preview.result or {}
    outcome = result.get('outcome') or 'uncertain'
    stopped = preview.execution_metadata.get('maintenance_blocker')
    if stopped:
        _remember(root, repository['id'], fingerprint, 'interrupted', preview)
        return {'outcome': 'blocked', 'notify': stopped not in {'maintenance_paused', 'execution_ownership_lost'},
                'blockers': [stopped], 'preview_task_id': str(preview.id),
                'usage': preview.execution_metadata.get('usage', {})}
    _remember(root, repository['id'], fingerprint, outcome, preview,
              {'candidate_sha256': result.get('candidate_sha256')})
    usage = preview.execution_metadata.get('usage', {})
    cost = (usage.get('input_tokens', 0) * .10 + usage.get('output_tokens', 0) * .50) / 1_000_000
    _patch(root, preview_task_id=str(preview.id), usage=usage, estimated_standard_cost_usd=cost,
           billing='not_observed', reviewer_decision=result.get('review', {}).get('decision'))
    if outcome != 'approved_candidate':
        return {'outcome': outcome, 'notify': outcome not in {'no_useful_change', 'insufficient_evidence'},
                'repository': repository, 'preview_task_id': str(preview.id), 'usage': usage,
                'estimated_standard_cost_usd': cost, 'billing': 'not_observed'}
    if readiness:
        return {'outcome': 'blocked', 'notify': True, 'blockers': readiness, 'repository': repository,
                'preview_task_id': str(preview.id), 'usage': usage, 'estimated_standard_cost_usd': cost,
                'billing': 'not_observed', 'reviewer_decision': result['review']['decision']}
    published = _publish(root, preview.id, repository)
    return {**published, 'usage': usage, 'estimated_standard_cost_usd': cost, 'billing': 'not_observed'}


def _run(root: Task, config: MaintenanceConfiguration) -> dict:
    _refresh(root, config)
    resume_id = root.payload.get('resume_preview_task_id')
    if resume_id:
        with SessionLocal() as session:
            source = session.get(Task, uuid.UUID(resume_id))
            if source is None or source.type != TaskType.DOCUMENTATION_PREVIEW:
                raise MaintenanceBlocked('approved_preview_required')
            repository = source.payload['context']['repository']
            row = session.get(MaintenanceRepository, repository['id'])
            if (row is None or not row.available or repository['owner'].lower() != get_settings().github_owner.lower()
                    or repository['name'].lower() in config.exclusions or repository['private']):
                raise MaintenanceBlocked('repository_outside_maintenance_pool')
        readiness, requirements = _readiness(root, repository)
        _repo_state(root, repository['id'], blocker=','.join(readiness) if readiness else None, publishing_readiness=requirements)
        if readiness:
            return {'outcome': 'blocked', 'notify': True, 'blockers': readiness, 'preview_task_id': str(source.id)}
        return _publish(root, source.id, repository)
    with SessionLocal() as session:
        rows = list(session.scalars(select(MaintenanceRepository).where(MaintenanceRepository.available.is_(True))
                    .order_by(MaintenanceRepository.last_checked_at.asc().nullsfirst(), MaintenanceRepository.repository_id)
                    .limit(MAX_REPOSITORIES_PER_RUN)))
        repositories = [copy.deepcopy(row.identity) for row in rows]
    new_blockers, recorded, deferred = [], [], None
    for repository in repositories:
        repo_id = repository['id']
        if repository['name'].lower() in config.exclusions or not repository['maintenance_eligible']:
            _repo_state(root, repo_id, skipped='operator_exclusion' if repository['name'].lower() in config.exclusions else repository['classification'])
            continue
        if repository['private']:
            if _repo_state(root, repo_id, blocker='private_model_sharing_not_in_policy'):
                new_blockers.append({'repository_id': repo_id, 'code': 'private_model_sharing_not_in_policy'})
            continue
        with SessionLocal() as session:
            active = session.scalar(select(DocumentationPublication).where(
                DocumentationPublication.repository_id == repo_id, DocumentationPublication.completed.is_(False)))
            active_id = active.preview_task_id if active else None
        if active_id:
            reconciled = _publish(root, active_id, repository)
            if reconciled['outcome'] == 'merged':
                return reconciled
            code = ','.join(reconciled.get('blockers', []))
            if _repo_state(root, repo_id, blocker=code):
                new_blockers.append({'repository_id': repo_id, 'code': code})
            continue
        readiness, requirements = _readiness(root, repository)
        if readiness and not root.payload.get('pilot'):
            if _repo_state(root, repo_id, blocker=','.join(readiness), publishing_readiness=requirements):
                new_blockers.append({'repository_id': repo_id, 'code': ','.join(readiness)})
            continue
        inspection = _child(root, TaskType.GITHUB_INSPECT, {'repository': repository['name']}, 'inspect:' + str(repo_id))
        if inspection.status != TaskStatus.SUCCEEDED or not inspection.result.get('commit'):
            if _repo_state(root, repo_id, blocker='inspection_failed'):
                new_blockers.append({'repository_id': repo_id, 'code': 'inspection_failed'})
            continue
        fingerprint = assessment_fingerprint(inspection.result)
        with SessionLocal() as session:
            previous = session.get(MaintenanceAssessment, (repo_id, fingerprint))
            reusable = previous.task_id if previous and previous.outcome == 'approved_candidate' and not readiness else None
            skip = bool(previous and (previous.outcome not in {'no_useful_change', 'insufficient_evidence'}
                 or now_utc() - previous.assessed_at < timedelta(days=config.reassessment_days)))
        if reusable:
            return _publish(root, reusable, repository)
        if skip:
            _repo_state(root, repo_id, skipped='unchanged_assessed_inputs', fingerprint=fingerprint)
            continue
        payload = choose_inputs(inspection.result, inspection.id, config)
        if payload is None:
            _repo_state(root, repo_id, skipped='no_bounded_documentation_inputs', fingerprint=fingerprint)
            _remember(root, repo_id, fingerprint, 'insufficient_evidence', inspection)
            continue
        _repo_state(root, repo_id, blocker=','.join(readiness) if readiness else None,
                    publishing_readiness=requirements, fingerprint=fingerprint)
        if readiness:
            # Explicit one-off pilot may test real generation despite a publication
            # access blocker; scheduled runs never spend on these repositories.
            if deferred is None:
                deferred = (repository, inspection, fingerprint, payload, readiness)
            continue
        result = _assess(root, repository, inspection, fingerprint, payload, [])
        if new_blockers:
            result['pool_blockers'] = new_blockers
            result['notify'] = True
        return result
    if deferred and root.payload.get('pilot'):
        return _assess(root, *deferred)
    return {'outcome': 'blocked' if new_blockers else 'no_op', 'notify': bool(new_blockers),
            'blockers': new_blockers, 'repositories_considered': len(repositories)}


def execute_maintenance(root: Task) -> tuple[dict, dict]:
    with engine.connect() as connection, connection.begin():
        if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(743203, 1)')):
            return {'outcome': 'skipped_overlap', 'notify': False}, {'handler': 'documentation_maintenance'}
        try:
            with SessionLocal() as session, session.begin():
                control = session.get(MaintenanceControl, 1)
                if control is None:
                    raise MaintenanceBlocked('maintenance_configuration_missing')
                config = MaintenanceConfiguration.model_validate(control.configuration)
                if session.get(MaintenanceRun, root.id) is None:
                    session.add(MaintenanceRun(task_id=root.id, configuration_sha256=control.configuration_sha256,
                        reserved_microusd=0, state={'children': {}, 'execution_id': str(root.execution_id),
                            'pause_generation': control.discovery.get('pause_generation', 0)}))
                    session.flush()
                root_permission(session, root)
                if not root.payload.get('pilot') and not pilot_succeeded(session, control):
                    raise MaintenanceBlocked('successful_pilot_required')
            result = _run(root, config)
            state = _patch(root, **result, stage='completed')
            if root.payload.get('pilot') and result.get('outcome') == 'merged' and result['live_verification']['author_associated']:
                with SessionLocal() as session, session.begin():
                    control, _ = root_permission(session, root)
                    control.pilot_task_id = root.id
            return state, {'handler': 'documentation_maintenance', 'success': result['outcome'] == 'merged'}
        except (MaintenanceBlocked, DocumentationError, GitHubError) as exc:
            result = {'outcome': 'budget_exhausted' if exc.code in {'daily_budget_exhausted', 'daily_assessment_limit', 'daily_model_call_limit'} else 'blocked',
                      'blockers': [exc.code], 'notify': exc.code not in {'maintenance_paused', 'execution_ownership_lost'}}
            with SessionLocal() as session, session.begin():
                run = session.get(MaintenanceRun, root.id)
                if run:
                    result = {**copy.deepcopy(run.state), **result}
                control = session.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
                current = session.scalar(select(Task).where(Task.id == root.id).with_for_update())
                if control and result['notify'] and current.execution_id == root.execution_id:
                    from personal_dot.maintenance_control import ZONE
                    key = digest([exc.code, control.configuration_sha256,
                        str(now_utc().astimezone(ZONE).date()) if result['outcome'] == 'budget_exhausted' else None])
                    result['notify'] = control.discovery.get('last_global_blocker') != key
                    control.discovery = {**control.discovery, 'last_global_blocker': key}
            return result, {'handler': 'documentation_maintenance', 'success': False}
