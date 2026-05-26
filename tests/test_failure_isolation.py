"""Unit tests for per-path failure isolation and token capture on error paths.

Path A error must not prevent Path B write, and vice versa.
Token/cost data must be preserved even when JSON parsing fails or model returns null.
Uses CAPTURE_MOCK_SDK=1 with a mock entry that raises.
"""
import sys, pathlib, os, json, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

import pytest


def _make_transcript(n_turns=3, chars=600) -> list[dict]:
    msgs = []
    for _ in range(n_turns):
        msgs.append({"role": "user", "content": "a" * chars})
        msgs.append({"role": "assistant", "content": "reply"})
    return msgs


def _run_with_mocks(tmp_path, monkeypatch, mock_a, mock_b, sid="test-session"):
    inbox_auto = tmp_path / "Inbox" / "auto"
    inbox_raw = tmp_path / "Inbox" / "raw"
    inbox_auto.mkdir(parents=True, exist_ok=True)
    inbox_raw.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "log.md"
    index_file = tmp_path / "session-index.tsv"

    monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
    import curate
    monkeypatch.setattr(curate, "_call_path_a", mock_a)
    monkeypatch.setattr(curate, "_call_path_b", mock_b)

    curate.run_capture(
        transcript=_make_transcript(),
        session_id=sid,
        cwd=str(tmp_path),
        vault_dir=str(tmp_path),
        log_path=log_file,
        index_path=index_file,
        date_str="2026-05-10",
    )
    log_lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    return json.loads(log_lines[-1])


class TestFailureIsolation:
    def test_path_a_error_path_b_still_writes(self, tmp_path, monkeypatch):
        """When Path A raises, Path B should still produce a file."""
        inbox_auto = tmp_path / "Inbox" / "auto"
        inbox_raw = tmp_path / "Inbox" / "raw"
        inbox_auto.mkdir(parents=True)
        inbox_raw.mkdir(parents=True)
        log_file = tmp_path / "log.md"
        index_file = tmp_path / "session-index.tsv"

        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        # Mock that raises for Path A, returns valid data for Path B
        import curate
        monkeypatch.setattr(curate, "_call_path_a", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(curate, "_call_path_b", lambda *a, **kw: {
            "title": "Test Summary",
            "type": "session-summary",
            "body": "## What happened\n- Something",
            "source_links": [],
            "tags": ["test"],
            "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001,
        })

        from curate import run_capture
        run_capture(
            transcript=_make_transcript(),
            session_id="test-session-isolation-1",
            cwd=str(tmp_path),
            vault_dir=str(tmp_path),
            log_path=log_file,
            index_path=index_file,
            date_str="2026-04-23",
        )

        # Path B file should exist
        raw_files = list(inbox_raw.glob("*.md"))
        assert len(raw_files) == 1

        # Path A inbox should be empty
        auto_files = list(inbox_auto.glob("*.md"))
        assert len(auto_files) == 0

        # Log entry should reflect the error on path A and success on path B
        log_lines = [l for l in log_file.read_text().splitlines() if l.strip()]
        assert len(log_lines) == 1
        entry = json.loads(log_lines[0])
        assert entry["path_a"] is None
        assert entry["skip_reason_a"].startswith("error:")
        assert entry["path_b"] is not None
        assert entry["skip_reason_b"] is None

    def test_path_b_error_path_a_still_writes(self, tmp_path, monkeypatch):
        """When Path B raises, Path A should still produce a file."""
        inbox_auto = tmp_path / "Inbox" / "auto"
        inbox_raw = tmp_path / "Inbox" / "raw"
        inbox_auto.mkdir(parents=True)
        inbox_raw.mkdir(parents=True)
        log_file = tmp_path / "log.md"
        index_file = tmp_path / "session-index.tsv"

        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        import curate
        monkeypatch.setattr(curate, "_call_path_a", lambda *a, **kw: {
            "title": "Decision: Use PostgreSQL",
            "type": "decision",
            "body": "We decided to use PostgreSQL because...",
            "source_links": [],
            "tags": ["backend"],
            "tokens_in": 200, "tokens_out": 100, "cost_usd": 0.01,
        })
        monkeypatch.setattr(curate, "_call_path_b", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("b-boom")))

        from curate import run_capture
        run_capture(
            transcript=_make_transcript(),
            session_id="test-session-isolation-2",
            cwd=str(tmp_path),
            vault_dir=str(tmp_path),
            log_path=log_file,
            index_path=index_file,
            date_str="2026-04-23",
        )

        # Path A should have written
        auto_files = list(inbox_auto.glob("*.md"))
        assert len(auto_files) == 1

        # Path B should be empty
        raw_files = list(inbox_raw.glob("*.md"))
        assert len(raw_files) == 0

        log_lines = [l for l in log_file.read_text().splitlines() if l.strip()]
        entry = json.loads(log_lines[0])
        assert entry["path_a"] is not None
        assert entry["skip_reason_a"] is None
        assert entry["path_b"] is None
        assert entry["skip_reason_b"].startswith("error:")


class TestTokenCaptureOnFailure:
    """Tokens and cost must be logged even when JSON parsing fails or model returns null."""

    def _mock_b_ok(self, *a, **kw):
        return {
            "title": "Summary", "type": "session-summary",
            "body": "content", "source_links": [], "tags": [],
            "tokens_in": 500, "tokens_out": 80, "cost_usd": 0.0002,
        }

    def test_model_returned_null_preserves_tokens(self, tmp_path, monkeypatch):
        """Path A returning null should still log token usage."""
        entry = _run_with_mocks(
            tmp_path, monkeypatch,
            mock_a=lambda *a, **kw: {"_null": True, "tokens_in": 1200, "tokens_out": 5, "cost_usd": 0.0036},
            mock_b=self._mock_b_ok,
            sid="test-null-tokens",
        )
        assert entry["skip_reason_a"] == "model_returned_null"
        assert entry["tokens_in_a"] == 1200
        assert entry["tokens_out_a"] == 5
        assert entry["cost_usd_a"] == 0.0036

    def test_malformed_json_preserves_tokens(self, tmp_path, monkeypatch):
        """Path B malformed_json should still log token usage via exc.usage."""
        def mock_b_malformed(*a, **kw):
            exc = json.JSONDecodeError("bad", "", 0)
            exc.usage = {"tokens_in": 800, "tokens_out": 60, "cost_usd": 0.0003}
            raise exc

        entry = _run_with_mocks(
            tmp_path, monkeypatch,
            mock_a=self._mock_b_ok,  # re-use as a valid path A mock
            mock_b=mock_b_malformed,
            sid="test-malformed-tokens",
        )
        assert entry["skip_reason_b"] == "malformed_json"
        assert entry["tokens_in_b"] == 800
        assert entry["tokens_out_b"] == 60
        assert entry["cost_usd_b"] == 0.0003

    def test_malformed_json_without_usage_attr(self, tmp_path, monkeypatch):
        """Graceful fallback when exc.usage is absent (pre-fix callers)."""
        def mock_b_plain_error(*a, **kw):
            raise json.JSONDecodeError("bad", "", 0)

        entry = _run_with_mocks(
            tmp_path, monkeypatch,
            mock_a=self._mock_b_ok,
            mock_b=mock_b_plain_error,
            sid="test-malformed-no-usage",
        )
        assert entry["skip_reason_b"] == "malformed_json"
        assert entry["tokens_in_b"] is None
        assert entry["cost_usd_b"] is None
