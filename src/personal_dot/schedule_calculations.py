from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from personal_dot.models import Schedule, ScheduleType


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def next_cron_occurrence(
    expression: str, timezone_name: str, after: datetime
) -> datetime:
    timezone = ZoneInfo(timezone_name)
    local_after = as_utc(after).astimezone(timezone)
    next_local = croniter(expression, local_after).get_next(datetime)
    return as_utc(next_local)


def next_occurrence(schedule: Schedule, occurrence: datetime) -> datetime | None:
    if schedule.schedule_type == ScheduleType.ONCE:
        return None
    if schedule.schedule_type == ScheduleType.INTERVAL:
        if schedule.interval_seconds is None:
            raise ValueError("interval schedule is missing interval_seconds")
        return as_utc(occurrence) + timedelta(seconds=schedule.interval_seconds)
    if schedule.cron_expression is None:
        raise ValueError("cron schedule is missing cron_expression")
    return next_cron_occurrence(
        schedule.cron_expression, schedule.timezone, as_utc(occurrence)
    )


def next_occurrence_after(schedule: Schedule, after: datetime) -> datetime | None:
    """Return the next future recurrence, skipping an intentionally disabled gap."""
    current = schedule.next_run_at
    if current is None or schedule.schedule_type == ScheduleType.ONCE:
        return current
    after_utc = as_utc(after)
    current_utc = as_utc(current)
    if current_utc > after_utc:
        return current_utc
    if schedule.schedule_type == ScheduleType.INTERVAL:
        if schedule.interval_seconds is None:
            raise ValueError("interval schedule is missing interval_seconds")
        elapsed = (after_utc - current_utc).total_seconds()
        steps = int(elapsed // schedule.interval_seconds) + 1
        return current_utc + timedelta(seconds=steps * schedule.interval_seconds)
    if schedule.cron_expression is None:
        raise ValueError("cron schedule is missing cron_expression")
    return next_cron_occurrence(
        schedule.cron_expression, schedule.timezone, after_utc
    )
