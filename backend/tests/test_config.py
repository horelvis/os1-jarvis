"""Tests for Config validation and normalisation."""

import pytest

from samantha.config import Config


def test_config_mode_is_normalized():
    assert Config(mode="REAL").mode == "real"
    assert Config(mode=" Mock ").mode == "mock"


def test_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="SAMANTHA_MODE"):
        Config(mode="reall")
