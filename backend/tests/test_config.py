"""Tests for Config validation and normalisation."""

import os

import pytest

from samantha.config import Config, _load_env_file


def test_config_mode_is_normalized():
    assert Config(mode="REAL").mode == "real"
    assert Config(mode=" Mock ").mode == "mock"


def test_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="SAMANTHA_MODE"):
        Config(mode="reall")


class TestLoadEnvFile:
    """Tests for `_load_env_file`, the stdlib `.env` loader.

    Uses `tmp_path` throughout — never the real `~/.samantha/.env`.
    """

    def test_key_absent_from_environ_is_loaded(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAMANTHA_TEST_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("SAMANTHA_TEST_KEY=from_file\n")

        _load_env_file(env_file)

        assert os.environ["SAMANTHA_TEST_KEY"] == "from_file"

    def test_key_already_in_environ_is_not_overwritten(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAMANTHA_TEST_KEY", "from_shell")
        env_file = tmp_path / ".env"
        env_file.write_text("SAMANTHA_TEST_KEY=from_file\n")

        _load_env_file(env_file)

        assert os.environ["SAMANTHA_TEST_KEY"] == "from_shell"

    def test_comments_blank_and_malformed_lines_are_ignored(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAMANTHA_TEST_A", raising=False)
        monkeypatch.delenv("SAMANTHA_TEST_B", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# a comment\n"
            "\n"
            "   # indented comment\n"
            "not_a_valid_line_no_equals\n"
            "=no_key_here\n"
            "SAMANTHA_TEST_A=alpha\n"
            "   \n"
            "SAMANTHA_TEST_B=beta\n"
        )

        _load_env_file(env_file)

        assert os.environ["SAMANTHA_TEST_A"] == "alpha"
        assert os.environ["SAMANTHA_TEST_B"] == "beta"

    def test_single_and_double_quoted_values_are_unquoted(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAMANTHA_TEST_SINGLE", raising=False)
        monkeypatch.delenv("SAMANTHA_TEST_DOUBLE", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SAMANTHA_TEST_SINGLE='hello world'\nSAMANTHA_TEST_DOUBLE=\"hello there\"\n"
        )

        _load_env_file(env_file)

        assert os.environ["SAMANTHA_TEST_SINGLE"] == "hello world"
        assert os.environ["SAMANTHA_TEST_DOUBLE"] == "hello there"

    def test_whitespace_around_key_and_value_is_stripped(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAMANTHA_TEST_WS", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("  SAMANTHA_TEST_WS   =   padded value   \n")

        _load_env_file(env_file)

        assert os.environ["SAMANTHA_TEST_WS"] == "padded value"

    def test_missing_file_is_a_silent_noop(self, tmp_path):
        missing = tmp_path / "does-not-exist" / ".env"

        # Must not raise.
        _load_env_file(missing)

    def test_unreadable_file_is_a_silent_noop(self, tmp_path):
        # A directory in place of the expected file makes reads fail
        # with IsADirectoryError — loader must swallow this too.
        env_dir = tmp_path / ".env"
        env_dir.mkdir()

        # Must not raise.
        _load_env_file(env_dir)
