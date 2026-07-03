import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def sync_client(tmp_path, monkeypatch):
    """Sync TestClient (needed for websocket_connect) with a migrated tmp DB."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import reset_engine

    reset_engine()
    from app.main import _run_migrations_sync, create_app

    _run_migrations_sync()
    with TestClient(create_app()) as client:
        yield client
    reset_engine()
    get_settings.cache_clear()


def register(client, email, name):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "longenough", "display_name": name},
    )
    assert resp.status_code == 200


def test_ws_scene_subscription_and_broadcast(sync_client):
    register(sync_client, "dm@example.com", "DM")
    campaign = sync_client.post("/api/v1/campaigns", json={"name": "C"}).json()
    scene = sync_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "Table", "dm_mode": "human"},
    ).json()

    with sync_client.websocket_connect(f"/ws/campaigns/{campaign['id']}") as ws:
        ws.send_json({"type": "scene.subscribe", "scene_id": scene["id"]})
        assert ws.receive_json() == {"type": "scene.subscribed", "scene_id": scene["id"]}

        sync_client.post(
            f"/api/v1/scenes/{scene['id']}/messages", json={"content": "hello table"}
        )
        event = ws.receive_json()
        assert event["type"] == "message.created"
        assert event["payload"]["content"] == "hello table"
        assert event["payload"]["seq"] == 1

        # dice rolls broadcast too
        sync_client.post(
            f"/api/v1/scenes/{scene['id']}/roll", json={"expression": "1d20"}
        )
        event = ws.receive_json()
        assert event["type"] == "message.created"
        assert event["payload"]["kind"] == "roll"


def test_ws_rejects_non_member(sync_client):
    register(sync_client, "dm@example.com", "DM")
    campaign = sync_client.post("/api/v1/campaigns", json={"name": "C"}).json()

    register(sync_client, "out@example.com", "Out")  # switches session cookie
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with sync_client.websocket_connect(f"/ws/campaigns/{campaign['id']}") as ws:
            ws.receive_json()
