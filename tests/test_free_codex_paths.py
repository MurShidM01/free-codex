import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from free_codex.cli_codex import run_codex
from free_codex.utils.free_codex_paths import default_server_health_url, free_codex_config_toml, free_codex_dir


def test_paths_under_dot_config():
    fake_home = Path("C:/Users/tester")
    with patch.object(Path, "home", return_value=fake_home):
        assert free_codex_dir() == fake_home / ".config" / "free-codex"
        assert (
            free_codex_config_toml()
            == fake_home / ".config" / "free-codex" / "config.toml"
        )


def test_default_health_url_respects_port_env():
    with patch.dict(os.environ, {"FREE_CODEX_PORT": "9999"}, clear=False):
        assert default_server_health_url() == "http://127.0.0.1:9999/health"


def _exit(code: int = 0) -> None:
    raise SystemExit(code)


def test_run_codex_exits_when_config_missing():
    mock_path = MagicMock()
    mock_path.is_file.return_value = False
    with patch("free_codex.cli_codex.free_codex_config_toml", return_value=mock_path):
        with patch("free_codex.cli_codex.sys.exit", side_effect=_exit):
            try:
                run_codex()
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("expected SystemExit")


def test_run_codex_exits_when_proxy_down():
    mock_path = MagicMock()
    mock_path.is_file.return_value = True
    with patch("free_codex.cli_codex.free_codex_config_toml", return_value=mock_path):
        with patch("free_codex.cli_codex._proxy_healthy", return_value=False):
            with patch("free_codex.cli_codex.sys.exit", side_effect=_exit):
                try:
                    run_codex()
                except SystemExit as e:
                    assert e.code == 3
                else:
                    raise AssertionError("expected SystemExit")
