"""Daily admission, persisted spending reservations, pause and execution fences."""

import copy
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
from typing import Any, Iterator
from pathlib import Path
import hashlib
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from personal_dot.config import get_settings
from personal_dot.db import SessionLocal
from personal_dot.documentation_policy import digest, policy_configuration
from personal_dot.maintenance_schemas import MaintenanceConfiguration
from personal_dot.models import MaintenanceControl, MaintenanceDay, MaintenanceRun, Task, TaskStatus

ZONE = ZoneInfo('America/New_York')
PRICE_VALID_UNTIL = datetime(2026, 11, 6, tzinfo=UTC)
PRICING = {'model': 'gpt-6-luna', 'input_usd_per_million': '0.10',
           'input_reservation_usd_per_million': '0.125', 'output_usd_per_million': '0.50',
           'verified_at': '2026-10-30', 'valid_until': PRICE_VALID_UNTIL.isoformat(),
           'source': 'https://developers.openai.com/api/docs/models/gpt-6-luna', 'service_tier': 'default'}


class MaintenanceBlocked(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__('Documentation maintenance blocked: ' + code)


def now_utc() -> datetime:
    return datetime.now(UTC)


def configuration_binding(config: dict) -> str:
    settings = get_settings()
    from personal_dot.documentation_preview import WORKFLOW_SHA256
    from personal_dot.documentation_publish import IMPLEMENTATION
    implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ('maintenance_control.py', 'documentation_maintenance.py')}
    return digest({'configuration': config, 'owner': settings.github_owner,
        'editor_model': settings.docs_preview_editor_model or settings.openai_model,
        'reviewer_model': settings.docs_preview_reviewer_model or settings.openai_model,
        'policy': policy_configuration(), 'pricing': PRICING,
        'preview_implementation': WORKFLOW_SHA256, 'publisher_implementation': IMPLEMENTATION,
        'maintenance_implementation': implementation,
        'author': [settings.github_commit_author_name, settings.github_commit_author_email]})


def require_prices() -> None:
    settings = get_settings()
    if any((getattr(settings, 'docs_preview_' + role + '_model') or settings.openai_model) != PRICING['model']
           for role in ('editor', 'reviewer')):
        raise MaintenanceBlocked('model_pricing_not_configured')
    if now_utc() >= PRICE_VALID_UNTIL:
        raise MaintenanceBlocked('pricing_revalidation_required')


def reservation_amount(config: MaintenanceConfiguration) -> int:
    # Text-only byte bound plus conservative protocol framing allowance; no tools.
    amount = 2 * (Decimal(config.max_input_bytes_per_call + 4096) * Decimal('0.125')
                  + Decimal(config.max_output_tokens_per_call) * Decimal('0.50'))
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def locked_day(session: Session, day: Any) -> MaintenanceDay:
    session.execute(insert(MaintenanceDay).values(day=day, reserved_microusd=0, model_calls=0).on_conflict_do_nothing())
    return session.scalar(select(MaintenanceDay).where(MaintenanceDay.day == day).with_for_update())


def root_permission(session: Session, root: Task, *, allow_paused_pilot: bool = True) -> tuple[MaintenanceControl, MaintenanceRun]:
    control = session.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
    current = session.scalar(select(Task).where(Task.id == root.id).with_for_update())
    run = session.get(MaintenanceRun, root.id)
    if current is None or current.status != TaskStatus.RUNNING or current.execution_id != root.execution_id:
        raise MaintenanceBlocked('execution_ownership_lost')
    if control is None or run is None:
        raise MaintenanceBlocked('maintenance_configuration_missing')
    if not get_settings().docs_maintenance_live_enabled:
        raise MaintenanceBlocked('maintenance_operator_gate_disabled')
    if run.state.get('pause_generation', 0) != control.discovery.get('pause_generation', 0):
        raise MaintenanceBlocked('maintenance_paused')
    if control.paused and not (allow_paused_pilot and current.payload.get('pilot') is True):
        raise MaintenanceBlocked('maintenance_paused')
    if (run.configuration_sha256 != control.configuration_sha256
            or control.configuration_sha256 != configuration_binding(control.configuration)):
        raise MaintenanceBlocked('maintenance_configuration_changed')
    return control, run


def child_permission(session: Session, task: Task) -> tuple[MaintenanceControl, MaintenanceRun] | None:
    if task.maintenance_parent_id is None:
        return None
    parent = session.get(Task, task.maintenance_parent_id)
    if parent is None:
        raise MaintenanceBlocked('execution_ownership_lost')
    # Bind to the parent claim captured when the child was created, not a later claim.
    run = session.get(MaintenanceRun, parent.id)
    if run is None or str(parent.execution_id) != run.state.get('execution_id'):
        raise MaintenanceBlocked('execution_ownership_lost')
    return root_permission(session, parent)


def reserve_generation(root: Task) -> int:
    with SessionLocal() as session, session.begin():
        control, run = root_permission(session, root)
        require_prices()
        config = MaintenanceConfiguration.model_validate(control.configuration)
        day = locked_day(session, now_utc().astimezone(ZONE).date())
        if day.assessment_owner is not None or day.merge_owner not in {None, root.id}:
            raise MaintenanceBlocked('daily_assessment_limit')
        amount = reservation_amount(config)
        if day.reserved_microusd + amount > config.daily_budget_microusd:
            raise MaintenanceBlocked('daily_budget_exhausted')
        day.assessment_owner, day.reserved_microusd = root.id, day.reserved_microusd + amount
        run.budget_day, run.reserved_microusd = day.day, amount
        run.state = {**run.state, 'pricing': PRICING, 'reserved_microusd': amount, 'budget_day': str(day.day)}
        return amount


def paid_intent(task: Task, role: str) -> None:
    if task.maintenance_parent_id is None:
        return
    with SessionLocal() as session, session.begin():
        current = session.scalar(select(Task).where(Task.id == task.id).with_for_update())
        if current is None or current.execution_id != task.execution_id or current.status != TaskStatus.RUNNING:
            raise MaintenanceBlocked('execution_ownership_lost')
        permission = child_permission(session, task)
        assert permission is not None
        _, run = permission
        require_prices()
        if run.budget_day != now_utc().astimezone(ZONE).date() or not run.reserved_microusd:
            raise MaintenanceBlocked('budget_reservation_expired')
        day = locked_day(session, run.budget_day)
        calls = copy.deepcopy(run.state.get('paid_call_intents', {}))
        if role in calls or day.model_calls >= 2 or day.assessment_owner != run.task_id:
            raise MaintenanceBlocked('daily_model_call_limit')
        calls[role] = {'task_id': str(task.id), 'intent_at': now_utc().isoformat()}
        day.model_calls += 1
        run.state = {**run.state, 'paid_call_intents': calls}


@contextmanager
def model_fence(task: Task) -> Iterator[None]:
    if task.maintenance_parent_id is None:
        yield
        return
    with SessionLocal() as session, session.begin():
        current = session.scalar(select(Task).where(Task.id == task.id).with_for_update())
        if current is None or current.execution_id != task.execution_id or current.status != TaskStatus.RUNNING:
            raise MaintenanceBlocked('execution_ownership_lost')
        permission = child_permission(session, task)
        assert permission is not None
        if permission[1].budget_day != now_utc().astimezone(ZONE).date():
            raise MaintenanceBlocked('budget_reservation_expired')
        yield


def merge_intent(session: Session, task: Task, operation: str) -> None:
    permission = child_permission(session, task)
    if permission is None or operation != 'merge':
        return
    _, run = permission
    day = locked_day(session, now_utc().astimezone(ZONE).date())
    preview_id = task.payload['preview_task_id']
    if run.state.get('merge_preview_task_id') not in {None, preview_id}:
        raise MaintenanceBlocked('run_merge_limit')
    if day.merge_owner not in {None, run.task_id}:
        raise MaintenanceBlocked('daily_merge_limit')
    day.merge_owner = run.task_id
    run.state = {**run.state, 'merge_preview_task_id': preview_id, 'merge_intent_day': str(day.day)}


def assert_merge_day(session: Session, task: Task, operation: str) -> None:
    permission = child_permission(session, task)
    if permission is None or operation != 'merge':
        return
    run = permission[1]
    if run.state.get('merge_intent_day') != str(now_utc().astimezone(ZONE).date()):
        raise MaintenanceBlocked('merge_reservation_expired')


def pilot_succeeded(session: Session, control: MaintenanceControl) -> bool:
    pilot = session.get(Task, control.pilot_task_id) if control.pilot_task_id else None
    run = session.get(MaintenanceRun, control.pilot_task_id) if control.pilot_task_id else None
    if not (pilot and run and pilot.status == TaskStatus.SUCCEEDED and pilot.result
            and pilot.result.get('outcome') == 'merged'
            and pilot.result.get('live_verification', {}).get('author_associated') is True
            and run.configuration_sha256 == control.configuration_sha256):
        return False
    try:
        preview = session.get(Task, uuid.UUID(pilot.result['preview_task_id']))
        publication = session.get(Task, uuid.UUID(pilot.result['publication_task_id']))
        if not (preview and publication and preview.status == TaskStatus.SUCCEEDED
                and publication.status == TaskStatus.SUCCEEDED and publication.result.get('merged')
                and not publication.result.get('blockers') and preview.result.get('outcome') == 'approved_candidate'
                and preview.result['review']['decision'] == 'approve' and preview.result['review']['valid']):
            return False
        for role in ('editor', 'reviewer'):
            call = preview.result['calls'][role]
            metadata = call['metadata']
            requested = preview.payload['configuration'][role + '_model']
            if not (call['status'] == 'completed' and metadata.get('provider') == 'openai'
                    and metadata.get('response_id') and metadata.get('request_id')
                    and metadata.get('model', '').startswith(requested)
                    and metadata.get('usage', {}).get('total_tokens', 0) > 0):
                return False
        return True
    except (ValueError, KeyError, TypeError):
        return False
