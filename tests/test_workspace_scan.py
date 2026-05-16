from pathlib import Path

from free_codex.services.workspace_scan import guess_named_paths, read_snippets


def test_guess_named_paths_from_text():
    listing = ["main.py", "README.md", "ignored.bin"]
    names = guess_named_paths("Update main.py docs in README.md", listing)
    assert "main.py" in names
    assert "README.md" in names


def test_read_snippets_escapes_root(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    safe = root / "a.txt"
    safe.write_text("hello", encoding="utf-8")
    evil = tmp_path / "secret.txt"
    evil.write_text("x", encoding="utf-8")
    out = read_snippets(root, ["a.txt", "../secret.txt"])
    assert len(out) == 1
    assert out[0][0] == "a.txt"
