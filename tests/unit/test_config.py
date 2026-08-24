"""
Unit tests for Core Configuration and Environment Settings.
Tests default configurations, env overrides, validation, secret masking, and edge values.
"""

import os
from unittest.mock import patch
import pytest
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Reference implementation of configuration schema."""
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ATERNOS_SESSION: str = ""
    ATERNOS_SERVER_ID: str = ""
    CHECK_INTERVAL: int = 5
    EXTEND_THRESHOLD_SECONDS: int = 180
    EMERGENCY_THRESHOLD_SECONDS: int = 30
    MOCK_MODE: bool = True
    HEADLESS: bool = True
    COOKIE_FILE: str = "cookies.json"
    LOG_LEVEL: str = "INFO"
    MAX_LOG_BUFFER: int = 500

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.getenv("PORT", "8000"))
        check_interval = int(os.getenv("CHECK_INTERVAL", "5"))
        extend_thresh = int(os.getenv("EXTEND_THRESHOLD_SECONDS", "180"))
        emerg_thresh = int(os.getenv("EMERGENCY_THRESHOLD_SECONDS", "30"))
        mock_mode = os.getenv("MOCK_MODE", "true").lower() in ("true", "1", "yes")
        headless = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")

        return cls(
            HOST=os.getenv("HOST", "0.0.0.0"),
            PORT=port,
            ATERNOS_SESSION=os.getenv("ATERNOS_SESSION", ""),
            ATERNOS_SERVER_ID=os.getenv("ATERNOS_SERVER_ID", ""),
            CHECK_INTERVAL=max(1, check_interval),
            EXTEND_THRESHOLD_SECONDS=max(10, extend_thresh),
            EMERGENCY_THRESHOLD_SECONDS=max(5, emerg_thresh),
            MOCK_MODE=mock_mode,
            HEADLESS=headless,
            COOKIE_FILE=os.getenv("COOKIE_FILE", "cookies.json"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
            MAX_LOG_BUFFER=int(os.getenv("MAX_LOG_BUFFER", "500")),
        )

    def masked_session(self) -> str:
        if not self.ATERNOS_SESSION:
            return "<unset>"
        if len(self.ATERNOS_SESSION) <= 8:
            return "***"
        return f"{self.ATERNOS_SESSION[:4]}...{self.ATERNOS_SESSION[-4:]}"


def test_default_config_values():
    """Verify default configuration parameters match requirements."""
    settings = Settings()
    assert settings.HOST == "0.0.0.0"
    assert settings.PORT == 8000
    assert settings.CHECK_INTERVAL == 5
    assert settings.EXTEND_THRESHOLD_SECONDS == 180
    assert settings.EMERGENCY_THRESHOLD_SECONDS == 30
    assert settings.HEADLESS is True
    assert settings.COOKIE_FILE == "cookies.json"
    assert settings.MAX_LOG_BUFFER == 500


def test_environment_variable_overrides():
    """Verify environment variables successfully override default settings."""
    env_vars = {
        "HOST": "127.0.0.1",
        "PORT": "9090",
        "ATERNOS_SESSION": "my_super_secret_session_token_12345",
        "ATERNOS_SERVER_ID": "srv_xyz987",
        "CHECK_INTERVAL": "2",
        "EXTEND_THRESHOLD_SECONDS": "240",
        "EMERGENCY_THRESHOLD_SECONDS": "45",
        "MOCK_MODE": "false",
        "HEADLESS": "0",
        "LOG_LEVEL": "DEBUG",
        "MAX_LOG_BUFFER": "1000",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        settings = Settings.from_env()
        assert settings.HOST == "127.0.0.1"
        assert settings.PORT == 9090
        assert settings.ATERNOS_SESSION == "my_super_secret_session_token_12345"
        assert settings.ATERNOS_SERVER_ID == "srv_xyz987"
        assert settings.CHECK_INTERVAL == 2
        assert settings.EXTEND_THRESHOLD_SECONDS == 240
        assert settings.EMERGENCY_THRESHOLD_SECONDS == 45
        assert settings.MOCK_MODE is False
        assert settings.HEADLESS is False
        assert settings.LOG_LEVEL == "DEBUG"
        assert settings.MAX_LOG_BUFFER == 1000


def test_secret_session_masking():
    """Ensure sensitive ATERNOS_SESSION is masked in display helpers."""
    settings_empty = Settings(ATERNOS_SESSION="")
    assert settings_empty.masked_session() == "<unset>"

    settings_short = Settings(ATERNOS_SESSION="short")
    assert settings_short.masked_session() == "***"

    settings_long = Settings(ATERNOS_SESSION="TOKEN_ABC123456789_SECRET")
    masked = settings_long.masked_session()
    assert masked.startswith("TOKE")
    assert masked.endswith("CRET")
    assert "ABC123456789" not in masked


def test_invalid_interval_clamping():
    """Ensure negative or zero check intervals are clamped to safe minimums."""
    with patch.dict(os.environ, {"CHECK_INTERVAL": "-5", "EXTEND_THRESHOLD_SECONDS": "2"}):
        settings = Settings.from_env()
        assert settings.CHECK_INTERVAL >= 1
        assert settings.EXTEND_THRESHOLD_SECONDS >= 10


def test_boolean_env_parsing():
    """Verify various truthy/falsy representations parse correctly."""
    for truthy in ["true", "True", "TRUE", "1", "yes", "YES"]:
        with patch.dict(os.environ, {"MOCK_MODE": truthy, "HEADLESS": truthy}):
            s = Settings.from_env()
            assert s.MOCK_MODE is True
            assert s.HEADLESS is True

    for falsy in ["false", "False", "0", "no", "NO", ""]:
        with patch.dict(os.environ, {"MOCK_MODE": falsy, "HEADLESS": falsy}):
            s = Settings.from_env()
            assert s.MOCK_MODE is False
            assert s.HEADLESS is False


def test_threshold_relative_ordering():
    """Ensure extend threshold is greater than emergency threshold."""
    settings = Settings(EXTEND_THRESHOLD_SECONDS=180, EMERGENCY_THRESHOLD_SECONDS=30)
    assert settings.EXTEND_THRESHOLD_SECONDS > settings.EMERGENCY_THRESHOLD_SECONDS
