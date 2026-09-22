import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_readyz_returns_ready_when_db_reachable(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
