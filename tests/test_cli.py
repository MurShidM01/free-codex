from unittest.mock import patch

from free_codex.cli_codex import resolve_codex_executable


def test_resolve_codex_executable_found():
    with patch("free_codex.cli_codex.shutil.which", return_value=r"C:\npm\codex.cmd"):
        assert resolve_codex_executable() == r"C:\npm\codex.cmd"


def test_resolve_codex_executable_missing():
    with patch("free_codex.cli_codex.shutil.which", return_value=None):
        assert resolve_codex_executable() is None
