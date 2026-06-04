"""Unit tests — each skip_reason variant produces a schema-valid JSON line."""

import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import build_log_entry, LOG_REQUIRED_KEYS


def _valid(entry: dict) -> bool:
    """Schema invariant: exactly one of path_*/skip_reason_* is non-null per path."""
    for path in ("a", "b"):
        p = entry.get(f"path_{path}")
        s = entry.get(f"skip_reason_{path}")
        # exactly one must be non-null
        if not ((p is None) ^ (s is None)):
            return False
    return True


class TestLogSchema:
    def _base(self, **overrides):
        base = dict(
            schema_version=1,
            timestamp="2026-04-23T14:32:11Z",
            date="2026-04-23",
            session_id="abc-123",
            path_a=None,
            path_b=None,
            skip_reason_a=None,
            skip_reason_b=None,
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=None,
            tokens_out_b=None,
            cost_usd_a=None,
            cost_usd_b=None,
            redactions={"env_var": 0, "jwt": 0},
        )
        base.update(overrides)
        return base

    def test_happy_path(self):
        e = build_log_entry(
            session_id="s1",
            path_a="Inbox/auto/f.md",
            skip_reason_a=None,
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=100,
            tokens_out_a=50,
            tokens_in_b=100,
            tokens_out_b=30,
            cost_usd_a=0.01,
            cost_usd_b=0.001,
            redactions={"env_var": 0},
        )
        assert e["schema_version"] == 1
        assert "timestamp" in e
        assert "date" in e
        assert _valid(e)
        assert all(k in e for k in LOG_REQUIRED_KEYS)

    def test_threshold_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="threshold",
            path_b=None,
            skip_reason_b="threshold",
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=None,
            tokens_out_b=None,
            cost_usd_a=None,
            cost_usd_b=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "threshold"
        assert e["skip_reason_b"] == "threshold"
        assert e["path_a"] is None
        assert e["path_b"] is None

    def test_token_limit_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="token_limit",
            path_b=None,
            skip_reason_b="token_limit",
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=None,
            tokens_out_b=None,
            cost_usd_a=None,
            cost_usd_b=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "token_limit"

    def test_model_returned_null(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="model_returned_null",
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=200,
            tokens_out_a=5,
            tokens_in_b=200,
            tokens_out_b=50,
            cost_usd_a=0.005,
            cost_usd_b=0.001,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "model_returned_null"
        assert e["path_b"] == "Inbox/raw/f.md"

    def test_timeout_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="timeout",
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=200,
            tokens_out_b=50,
            cost_usd_a=None,
            cost_usd_b=0.001,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "timeout"

    def test_malformed_json_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a="Inbox/auto/f.md",
            skip_reason_a=None,
            path_b=None,
            skip_reason_b="malformed_json",
            tokens_in_a=200,
            tokens_out_a=100,
            tokens_in_b=200,
            tokens_out_b=0,
            cost_usd_a=0.01,
            cost_usd_b=0.0002,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_b"] == "malformed_json"

    def test_error_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="error:RuntimeError",
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=200,
            tokens_out_b=50,
            cost_usd_a=None,
            cost_usd_b=0.001,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"].startswith("error:")

    def test_duplicate_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="duplicate",
            path_b=None,
            skip_reason_b="duplicate",
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=None,
            tokens_out_b=None,
            cost_usd_a=None,
            cost_usd_b=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "duplicate"
        assert e["skip_reason_b"] == "duplicate"

    def test_invariant_never_both_null(self):
        """Both path and skip_reason cannot be null simultaneously per path."""
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a=None,  # INVALID — both null
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=None,
            tokens_out_a=None,
            tokens_in_b=100,
            tokens_out_b=50,
            cost_usd_a=None,
            cost_usd_b=0.001,
            redactions={},
        )
        assert not _valid(e)

    def test_json_serializable(self):
        e = build_log_entry(
            session_id="s1",
            path_a="Inbox/auto/f.md",
            skip_reason_a=None,
            path_b="Inbox/raw/f.md",
            skip_reason_b=None,
            tokens_in_a=100,
            tokens_out_a=50,
            tokens_in_b=100,
            tokens_out_b=30,
            cost_usd_a=0.01,
            cost_usd_b=0.001,
            redactions={"env_var": 0},
        )
        line = json.dumps(e)
        parsed = json.loads(line)
        assert parsed["session_id"] == "s1"
