async def test_healthz(app_client):
    resp = await app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
