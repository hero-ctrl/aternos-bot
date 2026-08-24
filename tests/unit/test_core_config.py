"""
Unit tests specifically for src.core.config Settings, validators, and singleton accessor.
"""

import os
from unittest.mock import patch
import pytest
from pydantic import ValidationError

from src.core.config import Settings, get_settings


def test_core_settings_default_values():
    """Verify default values in src.core.config.Settings."""
    settings = Settings()
    assert settings.HOST == "0.0.0.0"
    assert settings.PORT == 8000
    assert settings.CHECK_INTERVAL == 5.0
    assert settings.COUNTDOWN_THRESHOLD == 180
    assert settings.EMERGENCY_THRESHOLD == 30
    assert settings.HEADLESS is True
    assert settings.MOCK_MODE is False
    assert settings.AUTO_START_ON_OFFLINE is False
    assert settings.AUTO_CONFIRM_QUEUE is True
    assert settings.LOG_LEVEL == "INFO"
    assert settings.LOG_BUFFER_SIZE == 1000


def test_core_settings_threshold_ordering_validation():
    """Verify emergency threshold >= countdown threshold raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(COUNTDOWN_THRESHOLD=60, EMERGENCY_THRESHOLD=60)

    with pytest.raises(ValidationError):
        Settings(COUNTDOWN_THRESHOLD=50, EMERGENCY_THRESHOLD=80)


def test_core_settings_log_level_validation():
    """Verify invalid log level raises ValidationError and valid normalized."""
    s_warn = Settings(LOG_LEVEL="warning")
    assert s_warn.LOG_LEVEL == "WARN"

    s_debug = Settings(LOG_LEVEL="debug")
    assert s_debug.LOG_LEVEL == "DEBUG"

    with pytest.raises(ValidationError):
        Settings(LOG_LEVEL="INVALID_LOG_LEVEL_XYZ")


def test_core_settings_secret_masking():
    """Verify masked_session and masked_session_cookie property behavior."""
    s_empty = Settings(ATERNOS_SESSION="")
    assert s_empty.masked_session() == "<unset>"
    assert s_empty.masked_session_cookie == "<unset>"

    s_short = Settings(ATERNOS_SESSION="short")
    assert s_short.masked_session() == "***"

    s_long = Settings(ATERNOS_SESSION="abc123456789xyz")
    masked = s_long.masked_session()
    assert masked == "abc1...9xyz"
    assert "2345678" not in masked


def test_core_settings_singleton():
    """Verify get_settings returns singleton instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
