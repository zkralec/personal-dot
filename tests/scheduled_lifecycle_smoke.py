"""Run only in the generated isolated stack with synthetic provider commands.

With --manual-only, creates no schedules. Otherwise uses a synthetic recurring
schedule, pauses it after one completed occurrence,
and advances only a notification retry deadline to shorten verification.
Never target a normal deployment: this explicitly enables synthetic recurrence.
"""

import json
import argparse
import os
import time
import uuid
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from personal_dot.db import SessionLocal
from personal_dot.models import NotificationDelivery, Schedule, Task
from personal_dot.queue import get_redis


def request(path, payload=None, method=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {} if data is None else {"Content-Type": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(
        "http://api:8000" + path, data=data, headers=headers, method=method,
    ), timeout=3) as response:
        return json.load(response)


def wait_for(read, check):
    for _ in range(200):
        value = read()
        if check(value):
            return value
        time.sleep(0.1)
    raise AssertionError(f"isolated lifecycle timed out: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-only", action="store_true")
    args = parser.parse_args()
    # Guard against accidentally using the non-stub deployment or populated DB.
    assert os.environ.get("SYNTHETIC_CHECK_IN_PROVIDERS") == "1", "requires isolated stub manifest"
    assert not any(os.environ.get(key) for key in ("OPENAI_API_KEY", "PUSHOVER_API_TOKEN", "PUSHOVER_USER_KEY"))
    with SessionLocal() as db:
        assert db.scalar(select(Task.id).limit(1)) is None, "requires fresh isolated application database"
    assert get_redis().get("synthetic:model-calls") is None
    note = request("/memories", {"type": "project_note", "content": "Synthetic project needs an input-size guard.", "source": "isolated-scheduling-smoke"})
    task_request = {"type": "project_check_in", "notification_policy": "always", "payload": {
        "project_id": "synthetic-container-smoke", "note_ids": [note["id"]],
        "priorities": ["Bound check-in inputs."],
    }}
    if args.manual_only:
        with SessionLocal() as db:
            assert db.scalar(select(Schedule.id).limit(1)) is None
        task_id = request("/tasks", task_request)["id"]
        schedule = None
    else:
        schedule = request("/schedules", {
            "name": "synthetic scheduling smoke", "schedule_type": "interval", "interval_seconds": 60,
            "start_at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat(), "timezone": "America/New_York",
            "task": task_request,
        })
        assert schedule["enabled"] is False
        request("/schedules/" + schedule["id"], {"enabled": True}, "PATCH")
        tasks = wait_for(lambda: request("/schedules/" + schedule["id"] + "/tasks"), lambda rows: len(rows) == 1)
        task_id = tasks[0]["id"]
    completed = wait_for(lambda: request("/tasks/" + task_id), lambda task: task["status"] in {"succeeded", "failed"})
    assert completed["status"] == "succeeded", completed["error"]
    if schedule:
        paused = request("/schedules/" + schedule["id"], {"enabled": False}, "PATCH")
        assert paused["enabled"] is False
    wait_for(lambda: request("/tasks/" + task_id), lambda task: task["execution_metadata"].get("notification", {}).get("delivery_status") == "pending")
    with SessionLocal() as db:
        delivery = db.get(NotificationDelivery, uuid.UUID(task_id))
        assert delivery.attempt_count == 1
        delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    delivered = wait_for(lambda: request("/tasks/" + task_id), lambda task: task["execution_metadata"].get("notification", {}).get("delivery_status") == "sent")
    assert delivered["result"] == completed["result"]
    assert delivered["execution_metadata"]["notification"]["attempt_count"] == 2
    assert get_redis().get("synthetic:model-calls") == b"1"
    print(json.dumps({"schedule_id": schedule["id"] if schedule else None, "task_id": task_id,
        "task_status": delivered["status"], "schedule_enabled": False,
        "model_calls": 1, "notification_attempts": 2, "notification_status": "sent"}, indent=2))


if __name__ == "__main__":
    main()
