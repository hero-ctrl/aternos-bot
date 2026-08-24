"""
Aternos Keep-Alive Bot Module.
Provides DOM selectors, Playwright async driver, mock driver, keepalive automation engine,
session cookie vaulting, and mock Aternos server.
"""

from src.bot.selectors import (
    PLUS_ONE_SELECTORS,
    STATUS_LABEL_SELECTORS,
    COUNTDOWN_SELECTORS,
    START_BUTTON_SELECTORS,
    STOP_BUTTON_SELECTORS,
    CONFIRM_BUTTON_SELECTORS,
    RESTART_BUTTON_SELECTORS,
    TIER1_SELECTORS,
    TIER2_SELECTORS,
    TIER3_SELECTORS,
    TIER4_SELECTORS,
    TIER5_JS_EVALUATE,
    parse_countdown_text,
    parse_countdown_str,
)
from src.bot.driver import (
    AternosDriverProtocol,
    AternosDriver,
    MockDriver,
)
from src.bot.engine import (
    KeepAliveEngine,
)
from src.bot.session import (
    CookieVault,
    SessionManager,
)
from src.bot.mock_server import (
    MockAternosServer,
    create_mock_app,
)

__all__ = [
    "PLUS_ONE_SELECTORS",
    "STATUS_LABEL_SELECTORS",
    "COUNTDOWN_SELECTORS",
    "START_BUTTON_SELECTORS",
    "STOP_BUTTON_SELECTORS",
    "CONFIRM_BUTTON_SELECTORS",
    "RESTART_BUTTON_SELECTORS",
    "TIER1_SELECTORS",
    "TIER2_SELECTORS",
    "TIER3_SELECTORS",
    "TIER4_SELECTORS",
    "TIER5_JS_EVALUATE",
    "parse_countdown_text",
    "parse_countdown_str",
    "AternosDriverProtocol",
    "AternosDriver",
    "MockDriver",
    "KeepAliveEngine",
    "CookieVault",
    "SessionManager",
    "MockAternosServer",
    "create_mock_app",
]
