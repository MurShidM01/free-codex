from fastapi.testclient import TestClient

from free_codex.app import create_app


def _remote_client(monkeypatch):
    monkeypatch.delenv("FREE_CODEX_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(
        "free_codex.routes.admin_common.is_trusted_localhost",
        lambda _req: False,
    )
    return TestClient(create_app())


def test_admin_nim_defaults_forbidden_when_remote(monkeypatch):
    client = _remote_client(monkeypatch)
    r = client.get("/admin/api/nim/defaults")
    assert r.status_code == 403


def test_admin_nim_defaults_ok_when_local_trusted(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NVIDIA_NIM_BASE_URL=https://ex/v1\n"
        "NVIDIA_NIM_API_KEY=secret\n"
        "NVIDIA_NIM_MODEL=m1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "free_codex.services.admin_env.free_codex_dotenv",
        lambda: env_file,
    )
    monkeypatch.delenv("FREE_CODEX_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(
        "free_codex.routes.admin_common.is_trusted_localhost",
        lambda _req: True,
    )
    client = TestClient(create_app())
    r = client.get("/admin/api/nim/defaults")
    assert r.status_code == 200
    assert r.json() == {
        "base_url": "https://ex/v1",
        "api_key": "secret",
        "model": "m1",
    }


def test_admin_nim_models_requires_local_or_token(monkeypatch):
    client = _remote_client(monkeypatch)
    r = client.post("/admin/api/nim/models", json={})
    assert r.status_code == 403


def test_admin_nim_test_requires_local_or_token(monkeypatch):
    client = _remote_client(monkeypatch)
    r = client.post("/admin/api/nim/test", json={})
    assert r.status_code == 403
