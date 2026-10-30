"""Loopback-only controls for one daily, account-wide maintenance schedule."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_dot.db import get_db
from personal_dot.maintenance_control import configuration_binding, pilot_succeeded
from personal_dot.maintenance_schemas import MaintenanceConfiguration, MaintenanceStateUpdate
from personal_dot.models import (MaintenanceControl, MaintenanceDay, MaintenanceRepository,
                                 MaintenanceRun, NotificationPolicy, Schedule, ScheduleType,
                                 Task, TaskStatus, TaskType)
from personal_dot.schedule_calculations import next_cron_occurrence

router = APIRouter(prefix='/maintenance', tags=['maintenance'])
DatabaseSession = Annotated[Session, Depends(get_db)]


def configuration_schedule(config: MaintenanceConfiguration) -> str:
    hour, minute = config.daily_time.split(':')
    return f'{int(minute)} {int(hour)} * * *'


def require_activation(session: Session, control: MaintenanceControl) -> None:
    from personal_dot.config import get_settings
    settings = get_settings()
    if control.configuration_sha256 != configuration_binding(control.configuration):
        raise HTTPException(409, 'Maintenance configuration changed; a matching pilot is required')
    if not pilot_succeeded(session, control):
        raise HTTPException(409, 'A successful real maintenance pilot with this configuration is required')
    if not settings.docs_maintenance_live_enabled or not settings.docs_preview_live_enabled:
        raise HTTPException(409, 'Maintenance and preview operator gates must be configured')
    from personal_dot.maintenance_control import MaintenanceBlocked, require_prices
    try:
        require_prices()
    except MaintenanceBlocked as exc:
        raise HTTPException(409, str(exc)) from None


@router.put('/configuration')
def configure(request: MaintenanceConfiguration, db: DatabaseSession) -> dict:
    if db.scalar(select(func.count()).select_from(Task).where(
            Task.type == TaskType.DOCUMENTATION_MAINTENANCE,
            Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED]))):
        raise HTTPException(409, 'Pause and finish active maintenance before changing configuration')
    control = db.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
    expression = configuration_schedule(request)
    if control is None:
        schedule = Schedule(name='Daily documentation maintenance', schedule_type=ScheduleType.CRON,
            task_type=TaskType.DOCUMENTATION_MAINTENANCE, payload={'pilot': False},
            notification_policy=NotificationPolicy.ALWAYS, enabled=False, cron_expression=expression,
            timezone=request.timezone, next_run_at=next_cron_occurrence(expression, request.timezone, datetime.now(UTC)))
        db.add(schedule)
        db.flush()
        control = MaintenanceControl(id=1, paused=True, configuration=request.model_dump(),
            configuration_sha256=configuration_binding(request.model_dump()), schedule_id=schedule.id, discovery={})
        db.add(control)
    else:
        schedule = db.get(Schedule, control.schedule_id)
        schedule.enabled = False
        schedule.cron_expression, schedule.timezone = expression, request.timezone
        schedule.next_run_at = next_cron_occurrence(expression, request.timezone, datetime.now(UTC))
        binding = configuration_binding(request.model_dump())
        if binding != control.configuration_sha256:
            control.pilot_task_id = None
        control.configuration, control.configuration_sha256, control.paused = request.model_dump(), binding, True
    db.commit()
    return {'configured': True, 'paused': True, 'schedule_id': str(control.schedule_id),
            'configuration_sha256': control.configuration_sha256}


@router.get('')
def inspect(db: DatabaseSession) -> dict:
    control = db.get(MaintenanceControl, 1)
    if control is None:
        return {'configured': False, 'paused': True}
    schedule = db.get(Schedule, control.schedule_id)
    return {'configured': True, 'paused': control.paused, 'configuration': control.configuration,
            'configuration_sha256': control.configuration_sha256, 'schedule_id': str(control.schedule_id),
            'enabled': schedule.enabled, 'next_run_at': schedule.next_run_at,
            'pilot_task_id': control.pilot_task_id, 'pilot_succeeded': pilot_succeeded(db, control),
            'discovered_at': control.discovered_at, 'discovery': control.discovery}


@router.patch('')
def change_state(request: MaintenanceStateUpdate, db: DatabaseSession) -> dict:
    control = db.scalar(select(MaintenanceControl).where(MaintenanceControl.id == 1).with_for_update())
    if control is None:
        raise HTTPException(409, 'Maintenance configuration is missing')
    schedule = db.get(Schedule, control.schedule_id)
    if request.action == 'resume':
        require_activation(db, control)
        schedule.next_run_at = next_cron_occurrence(schedule.cron_expression, schedule.timezone, datetime.now(UTC))
        schedule.enabled, control.paused = True, False
    else:
        control.paused, schedule.enabled = True, False
        control.discovery = {**control.discovery, 'pause_generation': control.discovery.get('pause_generation', 0) + 1}
    db.commit()
    return {'paused': control.paused, 'enabled': schedule.enabled, 'schedule_id': str(schedule.id), 'next_run_at': schedule.next_run_at}


@router.get('/repositories')
def repositories(db: DatabaseSession) -> list[dict]:
    return [{'repository_id': row.repository_id, 'name': row.name, 'available': row.available,
             'last_checked_at': row.last_checked_at, 'state': row.state}
            for row in db.scalars(select(MaintenanceRepository).order_by(MaintenanceRepository.repository_id).limit(1000))]


@router.get('/budgets')
def budgets(db: DatabaseSession) -> list[dict]:
    return [{'day': row.day, 'reserved_microusd': row.reserved_microusd, 'model_call_intents': row.model_calls,
             'assessment_owner': row.assessment_owner, 'merge_owner': row.merge_owner}
            for row in db.scalars(select(MaintenanceDay).order_by(MaintenanceDay.day.desc()).limit(31))]
