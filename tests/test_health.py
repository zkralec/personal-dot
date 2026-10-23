import pytest


@pytest.mark.anyio
async def test_health_reports_dependencies(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "postgres": "ok",
        "redis": "ok",
    }
