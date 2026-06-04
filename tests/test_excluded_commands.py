"""Unit tests for uses_excluded_command filter.

The public default for EXCLUDED_COMMANDS is empty (the pipeline captures
everything); extensions populate it via CAPTURE_EXCLUDED_COMMANDS. These tests
exercise the matching *mechanism* by passing the command list explicitly.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import uses_excluded_command, EXCLUDED_COMMANDS

# The list an extension like claude-vault-capture-private would configure.
CMDS = ["/daily-devlog", "/weekly-recap"]


def _msgs(*user_texts):
    msgs = []
    for text in user_texts:
        msgs.append({"role": "user", "content": text})
        msgs.append({"role": "assistant", "content": "ok"})
    return msgs


class TestUsesExcludedCommand:
    def test_daily_devlog_triggers(self):
        assert uses_excluded_command(_msgs("/daily-devlog"), excluded_commands=CMDS) is True

    def test_weekly_recap_triggers(self):
        assert uses_excluded_command(_msgs("/weekly-recap"), excluded_commands=CMDS) is True

    def test_command_at_start_of_line_triggers(self):
        assert uses_excluded_command(
            _msgs("context\n/daily-devlog\nmore text"), excluded_commands=CMDS
        ) is True

    def test_command_mid_sentence_does_not_trigger(self):
        assert uses_excluded_command(
            _msgs("please run /daily-devlog now"), excluded_commands=CMDS
        ) is False

    def test_command_quoted_in_prose_does_not_trigger(self):
        assert uses_excluded_command(
            _msgs('exclude "/daily-devlog" from capture'), excluded_commands=CMDS
        ) is False

    def test_normal_session_passes(self):
        assert uses_excluded_command(
            _msgs("fix the bug", "looks good", "ship it"), excluded_commands=CMDS
        ) is False

    def test_assistant_turn_ignored(self):
        msgs = [
            {"role": "user", "content": "summarise the week"},
            {"role": "assistant", "content": "/weekly-recap output here"},
        ]
        assert uses_excluded_command(msgs, excluded_commands=CMDS) is False

    def test_empty_transcript(self):
        assert uses_excluded_command([], excluded_commands=CMDS) is False

    def test_custom_excluded_commands(self):
        msgs = _msgs("/my-custom-cmd")
        assert uses_excluded_command(msgs, excluded_commands=["/my-custom-cmd"]) is True
        assert uses_excluded_command(msgs, excluded_commands=["/other"]) is False

    def test_public_default_is_empty_so_nothing_is_excluded(self):
        # With no CAPTURE_EXCLUDED_COMMANDS set, the gate is dormant: even a
        # /daily-devlog turn is captured (not skipped).
        assert EXCLUDED_COMMANDS == []
        assert uses_excluded_command(_msgs("/daily-devlog")) is False
