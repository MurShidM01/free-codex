from unittest.mock import patch

from free_codex.services.responses_sse_chunks import iter_text_deltas, sse_chunk_char_size


def test_iter_text_deltas_empty():
    assert list(iter_text_deltas("")) == [""]


def test_chunk_size_env(monkeypatch):
    monkeypatch.setenv("FREE_CODEX_SSE_DELTA_CHARS", "2048")
    from free_codex.services import responses_sse_chunks as m

    import importlib

    importlib.reload(m)
    assert m.sse_chunk_char_size() == 2048


def test_long_text_splits():
    with patch(
        "free_codex.services.responses_sse_chunks.sse_chunk_char_size",
        return_value=3,
    ):
        parts = list(iter_text_deltas("abcdef"))
        assert parts == ["abc", "def"]
