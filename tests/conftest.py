import os

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://personal_dot:personal_dot_dev@postgres:5432/personal_dot_test",
)
os.environ.setdefault(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql://personal_dot:personal_dot_dev@postgres:5432/postgres",
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/1")
os.environ.setdefault("RQ_QUEUE_NAME", "personal-dot-test")


def pytest_sessionstart(session: pytest.Session) -> None:
    database_name = "personal_dot_test"
    admin_url = os.environ["TEST_ADMIN_DATABASE_URL"]
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option(
        "sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%")
    )
    command.upgrade(alembic_config, "head")


@pytest.fixture(autouse=True)
def clean_state() -> None:
    from personal_dot.db import SessionLocal
    from personal_dot.models import (
        ApprovalRequest,
        Memory,
        NotificationDelivery,
        Note,
        Schedule,
        Task,
        ToolCall,
    )
    from personal_dot.queue import get_redis

    get_redis().flushdb()
    with SessionLocal() as db:
        db.query(ApprovalRequest).delete()
        db.query(Note).delete()
        db.query(ToolCall).delete()
        db.query(NotificationDelivery).delete()
        db.query(Task).delete()
        db.query(Schedule).delete()
        db.query(Memory).delete()
        db.commit()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from personal_dot.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
