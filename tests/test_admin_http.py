from fastapi.testclient import TestClient

from free_codex.app import create_app


def test_admin_html_reachable():
    app = create_app()
    client = TestClient(app)
    r = client.get("/admin/")
    assert r.status_code == 200
    assert "Free Codex Admin" in r.text


def test_admin_static_css():
    app = create_app()
    client = TestClient(app)
    r = client.get("/admin/static/styles.css")
    assert r.status_code == 200
    assert "background" in r.text.lower()


def test_admin_save_forbidden_when_remote_and_no_token(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(
        "free_codex.services.admin_env.free_codex_dotenv",
        lambda: env_file,
    )
    monkeypatch.delenv("FREE_CODEX_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(
        "free_codex.routes.admin_common.is_trusted_localhost",
        lambda _req: False,
    )
    app = create_app()
    client = TestClient(app)
    body = {
        "content": "NVIDIA_NIM_BASE_URL=https://x/v1\nNVIDIA_NIM_API_KEY=k\nNVIDIA_NIM_MODEL=m\n"
    }
    r = client.post("/admin/api/env", json=body)
    assert r.status_code == 403


def test_admin_save_with_token(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(
        "free_codex.services.admin_env.free_codex_dotenv",
        lambda: env_file,
    )
    monkeypatch.setenv("FREE_CODEX_ADMIN_TOKEN", "testtok")
    app = create_app()
    client = TestClient(app)
    body = {
        "content": "NVIDIA_NIM_BASE_URL=https://x/v1\nNVIDIA_NIM_API_KEY=k\nNVIDIA_NIM_MODEL=m\n"
    }
    r = client.post(
        "/admin/api/env",
        json=body,
        headers={"Authorization": "Bearer testtok"},
    )
    assert r.status_code == 200
    assert env_file.is_file()


def test_admin_save_succeeds_local_trust_without_token(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(
        "free_codex.services.admin_env.free_codex_dotenv",
        lambda: env_file,
    )
    monkeypatch.delenv("FREE_CODEX_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(
        "free_codex.routes.admin_common.is_trusted_localhost",
        lambda _req: True,
    )
    app = create_app()
    client = TestClient(app)
    body = {
        "content": "NVIDIA_NIM_BASE_URL=https://x/v1\nNVIDIA_NIM_API_KEY=k\nNVIDIA_NIM_MODEL=m\n"
    }
    r = client.post("/admin/api/env", json=body)
    assert r.status_code == 200
    assert env_file.is_file()
