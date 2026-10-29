import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from personal_dot.db import get_db
from personal_dot.diagnostics import error_class, queue_error
from personal_dot.check_in import CheckInInputError, prepare_check_in
from personal_dot.models import Task, TaskStatus, TaskType
from personal_dot.memory_routes import router as memory_router
from personal_dot.notification_routes import router as notification_router
from personal_dot.queue import get_redis
from personal_dot.schedule_routes import router as schedule_router
from personal_dot.schemas import HealthResponse, TaskCreate, TaskRead
from personal_dot.task_dispatch import enqueue_task
from personal_dot.tool_routes import router as tool_router

logger = logging.getLogger(__name__)
app = FastAPI(title="Personal Dot", version="0.1.0")
app.include_router(schedule_router)
app.include_router(notification_router)
app.include_router(tool_router)
app.include_router(memory_router)
DatabaseSession = Annotated[Session, Depends(get_db)]


@app.exception_handler(RequestValidationError)
async def safe_github_validation(request: Request, exc: RequestValidationError) -> Response:
    body = exc.body if isinstance(exc.body, dict) else {}
    nested = body.get("task") if isinstance(body.get("task"), dict) else {}
    if body.get("type") in ("github_discover", "github_inspect") or nested.get("type") in ("github_discover", "github_inspect"):
        return JSONResponse(status_code=422, content={"detail": "invalid GitHub task request"})
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def safe_unexpected_failure(
    request: Request, call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    # Catch here so the server does not log a raw unhandled DB/provider traceback.
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("API operation failed", extra={
            "event": "api_operation_failed", "error_class": error_class(exc),
        })
        return JSONResponse(status_code=503, content={"detail": "operation unavailable"})


@app.get("/health", response_model=HealthResponse)
def health(db: DatabaseSession) -> HealthResponse | JSONResponse:
    postgres_status = "ok"
    redis_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        postgres_status = "unavailable"
        logger.error("PostgreSQL health check failed", extra={"event": "health"})

    try:
        redis_client: Redis = get_redis()
        redis_client.ping()
    except Exception:
        redis_status = "unavailable"
        logger.error("Redis health check failed", extra={"event": "health"})

    body = {
        "status": "ok"
        if postgres_status == "ok" and redis_status == "ok"
        else "degraded",
        "postgres": postgres_status,
        "redis": redis_status,
    }
    if body["status"] == "degraded":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
    return HealthResponse.model_validate(body)


@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
def create_task(request: TaskCreate, db: DatabaseSession) -> Task:
    attempted_at = datetime.now(UTC)
    payload = request.payload
    if request.type == TaskType.PROJECT_CHECK_IN:
        try:
            payload = prepare_check_in(payload, db)
        except CheckInInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception:
            # SQL errors may contain private priority values in query parameters.
            logger.error(
                "Project check-in input preparation failed",
                extra={"event": "check_in_prepare_failed"},
            )
            raise HTTPException(
                status_code=503, detail="project check-in inputs could not be prepared"
            ) from None
    task = Task(
        type=request.type,
        status=TaskStatus.QUEUED,
        payload=payload,
        notification_policy=request.notification_policy,
        enqueue_attempted_at=attempted_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        enqueue_task(task.id)
    except Exception as exc:
        # PostgreSQL remains authoritative. Leave the task queued so the
        # scheduler can redeliver it after Redis or the API recovers.
        task.enqueue_error = queue_error(exc)
        db.commit()
        logger.error(
            "Task enqueue failed; durable reconciliation will retry",
            extra={"event": "task_enqueue_failed", "task_id": str(task.id),
                   "error_class": error_class(exc)},
        )
        db.refresh(task)
        return task

    logger.info(
        "Task queued",
        extra={
            "event": "task_queued",
            "task_id": str(task.id),
            "task_type": task.type.value,
        },
    )
    return task


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    statement = (
        select(Task)
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: uuid.UUID, db: DatabaseSession) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task
