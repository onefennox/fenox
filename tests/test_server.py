from fastapi.testclient import TestClient

from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def test_setup_login_and_access_control(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        # Before setup: not configured, and the API is closed.
        assert client.get("/api/auth/me").json() == {"configured": False, "authenticated": False}
        assert client.get("/api/system").status_code == 401

        # First-run setup configures the owner and signs the browser in.
        created = client.post("/api/setup", json={"password": PASSWORD})
        assert created.status_code == 201
        assert client.get("/api/system").status_code == 200
        assert client.get("/api/auth/me").json()["authenticated"] is True

        # Setup cannot run twice.
        assert client.post("/api/setup", json={"password": PASSWORD}).status_code == 409

        # Logout closes the session; login with the wrong password is rejected.
        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").json()["authenticated"] is False
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
        assert client.get("/api/system").status_code == 200


def test_setup_rejects_a_short_password(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/setup", json={"password": "short"}).status_code == 422


def test_health_is_public_and_reports_version(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        body = client.get("/api/system/health").json()
        assert body["status"] == "ok"
        assert body["version"]


def test_bearer_token_authenticates_scripts(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        token = app.state.auth.token()

    with TestClient(app) as client:
        assert client.get("/api/system").status_code == 401
        authorized = client.get("/api/system", headers={"Authorization": f"Bearer {token}"})
        assert authorized.status_code == 200


def test_index_page_is_served(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Fenox" in response.text
