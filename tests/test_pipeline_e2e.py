"""End-to-end tests for the full capture pipeline driven through curate.main().

These exercise the real argv → _load_transcript → run_capture → written vault
files → log → index flow with model calls replayed from mock-responses.json
(via the mock_from_responses fixture) or bespoke inline mocks. No network.

Companion to tests/test_failure_isolation.py, which owns the token-preservation
assertions on the error paths with inline mocks.
"""
import json
import pathlib
import re

import pytest

TRANSCRIPTS = pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "transcripts"

FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9\-]+-[0-9a-f]{8}\.md$")


def _transcript(name: str) -> pathlib.Path:
    return TRANSCRIPTS / f"{name}.jsonl"


def _parse_frontmatter(text: str) -> dict:
    """Tiny YAML-frontmatter reader — good enough for the flat scalar fields here."""
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    fm = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


class TestFullPipeline:
    def test_adr_worthy_writes_both_paths(self, run_main, mock_from_responses, temp_vault):
        """A+B both produce a file with correct filename + frontmatter."""
        mock_from_responses("adr-worthy")
        sid = "a1d2c3e4deadbeef0000"
        entries = run_main(_transcript("adr-worthy"), sid, "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        raw = list((temp_vault.vault_dir / "Inbox" / "raw").glob("*.md"))
        assert len(auto) == 1
        assert len(raw) == 1
        assert FILENAME_RE.match(auto[0].name), auto[0].name
        assert FILENAME_RE.match(raw[0].name), raw[0].name
        assert auto[0].name.endswith(f"-{sid[:8]}.md")

        fm_a = _parse_frontmatter(auto[0].read_text())
        assert fm_a["source"] == "claude-code-curated"
        assert fm_a["type"] == "decision"
        assert fm_a["session_id"] == sid
        assert fm_a["model"] == "claude-sonnet-4-6"

        fm_b = _parse_frontmatter(raw[0].read_text())
        assert fm_b["source"] == "claude-code-raw"
        assert fm_b["type"] == "session-summary"
        assert fm_b["model"] == "claude-haiku-4-5-20251001"

        assert len(entries) == 1
        e = entries[0]
        assert e["path_a"] == f"Inbox/auto/{auto[0].name}"
        assert e["path_b"] == f"Inbox/raw/{raw[0].name}"
        assert e["skip_reason_a"] is None
        assert e["skip_reason_b"] is None

    def test_debugging_only_skips_path_a(self, run_main, mock_from_responses, temp_vault):
        """path_a: null → no auto file, model_returned_null; path_b still writes."""
        mock_from_responses("debugging-only")
        entries = run_main(_transcript("debugging-only"), "dbb5678abcd00000111", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        raw = list((temp_vault.vault_dir / "Inbox" / "raw").glob("*.md"))
        assert auto == []
        assert len(raw) == 1

        e = entries[0]
        assert e["skip_reason_a"] == "model_returned_null"
        assert e["path_a"] is None
        assert e["path_b"] is not None
        assert e["skip_reason_b"] is None

    def test_malformed_title_is_sanitized(self, run_main, mock_from_responses, temp_vault):
        """Title with | [[ ]] # is sanitized in filename and frontmatter end-to-end."""
        mock_from_responses("malformed-title")
        run_main(_transcript("malformed-title"), "ac901234567abcde0001", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto) == 1
        # filename slug carries none of the unsafe characters
        assert FILENAME_RE.match(auto[0].name), auto[0].name

        text = auto[0].read_text()
        fm = _parse_frontmatter(text)
        title = fm["title"]
        for bad in ("|", "[[", "]]", "#", "`"):
            assert bad not in title, f"{bad!r} survived in title {title!r}"
        # the H1 heading is also the sanitized title
        assert "[[" not in text.split("---\n", 2)[2]

    def test_malformed_haiku_path_a_still_writes(self, run_main, mock_from_responses, temp_vault):
        """path_b is a string → malformed_json skip; Path A decision still written."""
        mock_from_responses("malformed_haiku")
        entries = run_main(_transcript("malformed_haiku"), "f00deadbeef12340002", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        raw = list((temp_vault.vault_dir / "Inbox" / "raw").glob("*.md"))
        assert len(auto) == 1  # real-pipeline failure isolation
        assert raw == []

        e = entries[0]
        assert e["skip_reason_b"] == "malformed_json"
        assert e["path_b"] is None
        assert e["path_a"] is not None
        assert e["skip_reason_a"] is None


class TestScrubbingStages:
    def test_input_scrub_records_redactions(self, run_main, mock_from_responses, temp_vault):
        """Pre-API scrub runs regardless of mocking — planted secrets are counted."""
        mock_from_responses("with-secrets")
        entries = run_main(_transcript("with-secrets"), "5ec0011223344ff00003", "/tmp")

        redactions = entries[0]["redactions"]
        total = sum(redactions.values())
        assert total > 0, redactions
        # the env-var, bearer, token-prefix, and basic-auth-url rules all fire here
        assert redactions["env_var"] > 0
        assert redactions["bearer"] > 0

    def test_output_scrub_redacts_secret_in_written_file(
        self, run_main, monkeypatch, temp_vault
    ):
        """Post-API scrub: a secret in the model's returned body/title is redacted
        in the written file. The with-secrets mock body is already clean, so this
        needs a bespoke inline mock that returns a planted secret."""
        import curate

        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        secret = "Bearer abc123SECRETtoken456value"
        monkeypatch.setattr(
            curate,
            "_call_path_a",
            lambda *a, **kw: {
                "title": "Decision: leaked Authorization: " + secret,
                "type": "decision",
                "body": "We hardcoded Authorization: " + secret + " — bad idea.",
                "source_links": [],
                "tags": ["security"],
                "tokens_in": 100, "tokens_out": 40, "cost_usd": 0.001,
            },
        )
        monkeypatch.setattr(
            curate,
            "_call_path_b",
            lambda *a, **kw: {
                "title": "Summary", "type": "session-summary",
                "body": "nothing secret here", "source_links": [], "tags": [],
                "tokens_in": 80, "tokens_out": 30, "cost_usd": 0.0001,
            },
        )

        run_main(_transcript("adr-worthy"), "1eaf778899aabbcc0004", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto) == 1
        written = auto[0].read_text()
        assert secret not in written
        assert "abc123SECRETtoken456value" not in written
        assert "<redacted:bearer>" in written
