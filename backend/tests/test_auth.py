REGISTER = {"email": "dm@example.com", "password": "correcthorse", "display_name": "The DM"}


async def test_register_login_me_flow(app_client):
    resp = await app_client.post("/api/v1/auth/register", json=REGISTER)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "dm@example.com"
    assert body["is_admin"] is True  # first account administers the install

    resp = await app_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "The DM"

    # second user is not admin
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p1@example.com", "password": "longenough", "display_name": "P1"},
    )
    assert resp.json()["is_admin"] is False

    # duplicate email rejected
    resp = await app_client.post("/api/v1/auth/register", json=REGISTER)
    assert resp.status_code == 400

    # wrong password rejected
    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": "dm@example.com", "password": "wrong-pass"}
    )
    assert resp.status_code == 400

    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": "dm@example.com", "password": "correcthorse"}
    )
    assert resp.status_code == 200

    await app_client.post("/api/v1/auth/logout")
    resp = await app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_requires_auth(app_client):
    resp = await app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
