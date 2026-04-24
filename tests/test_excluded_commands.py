"""Unit tests for uses_excluded_command filter."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import uses_excluded_command, EXCLUDED_COMMANDS


def _msgs(*user_texts):
    msgs = []
    for text in user_texts:
        msgs.append({"role": "user", "content": text})
        msgs.append({"role": "assistant", "content": "ok"})
    return msgs


class TestUsesExcludedCommand:
    def test_daily_devlog_triggers(self):
        assert uses_excluded_command(_msgs("/daily-devlog")) is True

    def test_weekly_recap_triggers(self):
        assert uses_excluded_command(_msgs("/weekly-recap")) is True

    def test_command_at_start_of_line_triggers(self):
        assert uses_excluded_command(_msgs("context\n/daily-devlog\nmore text")) is True

    def test_command_mid_sentence_does_not_trigger(self):
        assert uses_excluded_command(_msgs("please run /daily-devlog now")) is False

    def test_command_quoted_in_prose_does_not_trigger(self):
        assert uses_excluded_command(_msgs('exclude "/daily-devlog" from capture')) is False

    def test_normal_session_passes(self):
        assert uses_excluded_command(_msgs("fix the bug", "looks good", "ship it")) is False

    def test_assistant_turn_ignored(self):
        msgs = [
            {"role": "user", "content": "summarise the week"},
            {"role": "assistant", "content": "/weekly-recap output here"},
        ]
        assert uses_excluded_command(msgs) is False

    def test_empty_transcript(self):
        assert uses_excluded_command([]) is False

    def test_custom_excluded_commands(self):
        msgs = _msgs("/my-custom-cmd")
        assert uses_excluded_command(msgs, excluded_commands=["/my-custom-cmd"]) is True
        assert uses_excluded_command(msgs, excluded_commands=["/other"]) is False

    def test_excluded_commands_constant_contains_expected(self):
        assert "/daily-devlog" in EXCLUDED_COMMANDS
        assert "/weekly-recap" in EXCLUDED_COMMANDS
