"""
Configuration Subsystem for Aternos 24/7 Keep-Alive Automation & Web Dashboard.
Parses environment variables and .env configuration with Pydantic V2 BaseSettings.
"""

from functools import lru_cache
import os
from typing import Any, Dict, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and/or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Server Bind & Network Configuration
    HOST: str = Field(default="0.0.0.0", description="Web dashboard bind host")
    PORT: int = Field(default=8000, ge=1, le=65535, description="Web dashboard port")

    # Aternos Authentication & Target Server
    ATERNOS_SESSION: str = Field(default="", description="Aternos session cookie token")
    ATERNOS_SEC_TOKEN: str = Field(default="", description="Optional secondary CSRF token")
    ATERNOS_USER: Optional[str] = Field(default=None, description="Aternos username/email")
    ATERNOS_PASSWORD: Optional[str] = Field(default=None, description="Aternos password")
    ATERNOS_SERVER_ID: Optional[str] = Field(default="", description="Target Aternos server ID")
    ATERNOS_BASE_URL: str = Field(default="https://aternos.org", description="Aternos base URL")
    ATERNOS_SERVER_URL: str = Field(default="https://aternos.org/server/", description="Server dashboard URL")

    # Automation Engine Timing
    CHECK_INTERVAL: float = Field(default=5.0, ge=1.0, le=60.0, description="Keepalive poll interval in seconds")
    COUNTDOWN_THRESHOLD: int = Field(default=180, ge=10, le=600, description="Seconds remaining to trigger +1 button")
    EMERGENCY_THRESHOLD: int = Field(default=30, ge=5, description="Emergency countdown threshold in seconds")

    # Browser & Automation Behavior
    HEADLESS: bool = Field(default=True, description="Run browser in headless mode")
    MOCK_MODE: bool = Field(default=False, description="Enable offline mock simulation mode")
    AUTO_START_ON_OFFLINE: bool = Field(default=True, description="Auto-start server if offline")
    AUTO_CONFIRM_QUEUE: bool = Field(default=True, description="Auto-confirm queue dialogs")
    BROWSER_TIMEOUT: float = Field(default=30.0, ge=5.0, le=120.0, description="Browser action timeout in seconds")

    # Resilience & Exponential Backoff
    MAX_RETRY_ATTEMPTS: int = Field(default=5, ge=1, le=20, description="Max reconnect retry attempts")
    RETRY_BACKOFF_BASE: float = Field(default=2.0, ge=1.1, le=5.0, description="Exponential backoff base")
    RETRY_BACKOFF_MAX: float = Field(default=60.0, ge=10.0, le=300.0, description="Max exponential backoff seconds")

    # Logging & Telemetry
    LOG_LEVEL: str = Field(default="INFO", description="Application logging level")
    LOG_BUFFER_SIZE: int = Field(default=1000, ge=50, le=10000, description="In-memory log buffer size")

    # Persistence & Screenshots
    COOKIE_FILE_PATH: str = Field(default="data/cookies.json", description="Session cookie cache file")
    STORAGE_STATE_PATH: str = Field(default="data/storage_state.json", description="Browser storage state file")
    SCREENSHOT_ON_ERROR: bool = Field(default=True, description="Save screenshot on error")
    SCREENSHOT_DIR: str = Field(default="data/screenshots", description="Screenshots output directory")
    MOCK_SERVER_PORT: int = Field(default=3000, ge=1, le=65535, description="Mock Aternos server port")

    # Compatibility properties and aliases
    @property
    def EXTEND_THRESHOLD_SECONDS(self) -> int:
        return self.COUNTDOWN_THRESHOLD

    @property
    def EMERGENCY_THRESHOLD_SECONDS(self) -> int:
        return self.EMERGENCY_THRESHOLD

    @property
    def check_interval_seconds(self) -> float:
        return self.CHECK_INTERVAL

    @property
    def click_threshold_seconds(self) -> int:
        return self.COUNTDOWN_THRESHOLD

    @property
    def emergency_threshold_seconds(self) -> int:
        return self.EMERGENCY_THRESHOLD

    @property
    def MAX_LOG_BUFFER(self) -> int:
        return self.LOG_BUFFER_SIZE

    @property
    def COOKIE_FILE(self) -> str:
        return self.COOKIE_FILE_PATH

    @property
    def AUTO_START_ENABLED(self) -> bool:
        return self.AUTO_START_ON_OFFLINE

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL", "SUCCESS", "PLUS_ONE"}
        upper_v = v.strip().upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of: {', '.join(valid_levels)}")
        return "WARN" if upper_v == "WARNING" else upper_v

    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> "Settings":
        if self.EMERGENCY_THRESHOLD >= self.COUNTDOWN_THRESHOLD:
            raise ValueError(
                f"EMERGENCY_THRESHOLD ({self.EMERGENCY_THRESHOLD}s) must be strictly less than "
                f"COUNTDOWN_THRESHOLD ({self.COUNTDOWN_THRESHOLD}s)."
            )
        return self

    @property
    def masked_session_cookie(self) -> str:
        """Returns masked session cookie for safe telemetry and logging."""
        return self.masked_session()

    def masked_session(self) -> str:
        """Helper to mask sensitive Aternos session token."""
        if not self.ATERNOS_SESSION:
            return "<unset>"
        if len(self.ATERNOS_SESSION) <= 8:
            return "***"
        return f"{self.ATERNOS_SESSION[:4]}...{self.ATERNOS_SESSION[-4:]}"

    @classmethod
    def from_env(cls) -> "Settings":
        """Factory method to construct Settings with manual environment parsing & clamping."""
        port_raw = os.getenv("PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError:
            port = 8000

        check_int_raw = os.getenv("CHECK_INTERVAL", "5")
        try:
            check_interval = max(1.0, float(check_int_raw))
        except ValueError:
            check_interval = 5.0

        extend_thresh_raw = os.getenv("EXTEND_THRESHOLD_SECONDS", os.getenv("COUNTDOWN_THRESHOLD", "180"))
        try:
            extend_thresh = max(10, int(extend_thresh_raw))
        except ValueError:
            extend_thresh = 180

        emerg_thresh_raw = os.getenv("EMERGENCY_THRESHOLD_SECONDS", os.getenv("EMERGENCY_THRESHOLD", "30"))
        try:
            emerg_thresh = max(5, int(emerg_thresh_raw))
        except ValueError:
            emerg_thresh = 30

        mock_mode_raw = os.getenv("MOCK_MODE", "false").strip().lower()
        mock_mode = mock_mode_raw in ("true", "1", "yes")

        headless_raw = os.getenv("HEADLESS", "true").strip().lower()
        headless = headless_raw in ("true", "1", "yes")

        cookie_file = os.getenv("COOKIE_FILE", os.getenv("COOKIE_FILE_PATH", "cookies.json"))
        max_log = int(os.getenv("MAX_LOG_BUFFER", os.getenv("LOG_BUFFER_SIZE", "1000")))

        return cls(
            HOST=os.getenv("HOST", "0.0.0.0"),
            PORT=port,
            ATERNOS_SESSION=os.getenv("ATERNOS_SESSION", ""),
            ATERNOS_SEC_TOKEN=os.getenv("ATERNOS_SEC_TOKEN", ""),
            ATERNOS_USER=os.getenv("ATERNOS_USER", None),
            ATERNOS_PASSWORD=os.getenv("ATERNOS_PASSWORD", None),
            ATERNOS_SERVER_ID=os.getenv("ATERNOS_SERVER_ID", ""),
            ATERNOS_BASE_URL=os.getenv("ATERNOS_BASE_URL", "https://aternos.org"),
            ATERNOS_SERVER_URL=os.getenv("ATERNOS_SERVER_URL", "https://aternos.org/server/"),
            CHECK_INTERVAL=check_interval,
            COUNTDOWN_THRESHOLD=extend_thresh,
            EMERGENCY_THRESHOLD=emerg_thresh,
            HEADLESS=headless,
            MOCK_MODE=mock_mode,
            COOKIE_FILE_PATH=cookie_file,
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
            LOG_BUFFER_SIZE=max_log,
        )


@lru_cache()
def get_settings() -> Settings:
    """Singleton cached configuration accessor."""
    return Settings()
