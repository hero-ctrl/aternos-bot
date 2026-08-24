"""
Pytest configuration and shared fixtures for Aternos 24/7 Keep-Alive Automation.
Provides mock browser contexts, mock Aternos engine, simulated event streams,
and deterministic test fixtures.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ConfigDict, Field

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for path in [PROJECT_ROOT, SRC_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

# ---------------------------------------------------------------------------
# Core Data Models & Schemas (Authoritative Contracts)
# ---------------------------------------------------------------------------

class ServerStatus(str, Enum):
    OFFLINE = "offline"
    IN_QUEUE = "in_queue"
    LOADING = "loading"
    ONLINE = "online"
    STOPPING = "stopping"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


class ServerState(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    status: ServerStatus = ServerStatus.OFFLINE
    countdown_seconds: Optional[int] = None
    countdown_text: Optional[str] = None
    last_plus_one_click: Optional[datetime] = None
    plus_one_click_count: int = 0
    queue_position: Optional[int] = None
    queue_time: Optional[str] = None
    is_keepalive_active: bool = True
    session_valid: bool = True
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LogEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = "INFO"  # INFO, SUCCESS, WARN, ERROR, PLUS_ONE
    message: str = ""
    data: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Selector Constants & Parser Logic
# ---------------------------------------------------------------------------

STATUS_LABEL_SELECTORS = [
    ".statuslabel-label",
    ".server-status",
    "#statuslabel",
    "[data-status]",
]

COUNTDOWN_SELECTORS = [
    ".countdown",
    ".statuslabel-countdown",
    "#countdown",
    ".server-countdown",
]

PLUS_ONE_SELECTORS = [
    "#extend",
    "button.btn-extend",
    "button[title*='Extend']",
    "//button[contains(text(), '+1') or contains(., '+1')]",
    ".status-action-extend",
    ".countdown-extend",
]

START_BUTTON_SELECTORS = ["#start", ".btn-start", "button[title*='Start']"]
STOP_BUTTON_SELECTORS = ["#stop", ".btn-stop", "button[title*='Stop']"]
CONFIRM_BUTTON_SELECTORS = ["#confirm", ".btn-confirm", "button[title*='Confirm']"]
RESTART_BUTTON_SELECTORS = ["#restart", ".btn-restart"]


def parse_countdown_str(text: Optional[str]) -> Optional[int]:
    """Parse mm:ss or m:ss countdown text to total seconds."""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    
    # Reject scientific notation or non-standard characters
    if "e" in cleaned.lower() or "x" in cleaned.lower():
        return None

    # Handle formats like "03:45", "3:45", "0:30", "00:00"
    parts = cleaned.split(":")
    if len(parts) == 2:
        try:
            m_str, s_str = parts[0].strip(), parts[1].strip()
            if "-" in m_str or "-" in s_str or len(m_str) > 4 or len(s_str) > 2:
                return None
            minutes = int(m_str)
            seconds = int(s_str)
            if minutes < 0 or seconds < 0 or seconds >= 60 or minutes > 1440:
                return None
            return (minutes * 60) + seconds
        except ValueError:
            return None
    elif len(parts) == 1:
        try:
            s_str = parts[0].strip()
            if "-" in s_str or len(s_str) > 6:
                return None
            sec = int(s_str)
            return sec if (0 <= sec <= 86400) else None
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# In-Memory Log Broadcaster (SSE & WebSocket)
# ---------------------------------------------------------------------------

class MockLogBroadcaster:
    def __init__(self, max_buffer: int = 500):
        self.max_buffer = max_buffer
        self.logs: List[LogEvent] = []
        self._subscribers: List[asyncio.Queue[LogEvent]] = []

    def log(
        self,
        *args: Any,
        message: Optional[str] = None,
        level: Optional[str] = None,
        source: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> LogEvent:
        valid_levels = {"DEBUG", "INFO", "SUCCESS", "WARN", "WARNING", "ERROR", "CRITICAL", "PLUS_ONE"}

        # Positional args
        if len(args) == 1:
            if message is None:
                message = str(args[0])
            elif level is None and str(args[0]).upper() in valid_levels:
                level = str(args[0]).upper()
        elif len(args) == 2:
            first, second = str(args[0]), str(args[1])
            if first.upper() in valid_levels and second.upper() not in valid_levels:
                if level is None:
                    level = first.upper()
                if message is None:
                    message = second
            else:
                if message is None:
                    message = first
                if level is None:
                    level = second.upper()
        elif len(args) >= 3:
            first, second = str(args[0]), str(args[1])
            if first.upper() in valid_levels and second.upper() not in valid_levels:
                if level is None:
                    level = first.upper()
                if message is None:
                    message = second
            else:
                if message is None:
                    message = first
                if level is None:
                    level = second.upper()
            if isinstance(args[2], dict):
                if data is None:
                    data = args[2]
            else:
                if source is None:
                    source = str(args[2])
            if len(args) >= 4 and data is None:
                data = args[3] if isinstance(args[3], dict) else {"data": args[3]}

        # Keyword args
        if "message" in kwargs and kwargs["message"] is not None:
            message = str(kwargs["message"])
        if "level" in kwargs and kwargs["level"] is not None:
            level = str(kwargs["level"])
        if "source" in kwargs and kwargs["source"] is not None:
            source = str(kwargs["source"])
        if "data" in kwargs and kwargs["data"] is not None:
            data = kwargs["data"]

        if message is None:
            message = ""
        if level is None:
            level = "INFO"
        else:
            level = str(level).upper()

        if level == "WARNING":
            level = "WARN"

        event = LogEvent(level=level, message=message, data=data)
        self.logs.append(event)
        if len(self.logs) > self.max_buffer:
            self.logs = self.logs[-self.max_buffer:]
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except Exception:
                pass
        return event

    def subscribe(self) -> AsyncGenerator[LogEvent, None]:
        queue: asyncio.Queue[LogEvent] = asyncio.Queue()
        self._subscribers.append(queue)

        async def _generator() -> AsyncGenerator[LogEvent, None]:
            try:
                while True:
                    event = await queue.get()
                    yield event
            finally:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)

        return _generator()

    def get_logs(self, level: Optional[str] = None, search: Optional[str] = None, limit: int = 100) -> List[LogEvent]:
        filtered = self.logs
        if level:
            target_level = level.upper()
            if target_level == "WARNING":
                target_level = "WARN"
            filtered = [l for l in filtered if l.level.upper() == target_level]
        if search:
            search_lower = search.lower()
            filtered = [l for l in filtered if search_lower in l.message.lower()]
        return filtered[-limit:]

    def clear(self):
        self.logs.clear()


# ---------------------------------------------------------------------------
# High-Fidelity Mock Aternos Server & Engine
# ---------------------------------------------------------------------------

class MockAternosServer:
    """Simulates Aternos backend state machine and AJAX responses."""
    def __init__(self):
        self.status = ServerStatus.ONLINE
        self.countdown = 360  # 6 minutes default
        self.queue_position: Optional[int] = None
        self.queue_time: Optional[str] = None
        self.plus_one_clicks = 0
        self.last_plus_one: Optional[datetime] = None
        self.is_running = True
        self.crash_mode = False
        self.cloudflare_blocked = False

    def tick(self, seconds: int = 1):
        if self.status == ServerStatus.ONLINE and self.countdown is not None:
            self.countdown = max(0, self.countdown - seconds)
        elif self.status == ServerStatus.IN_QUEUE and self.queue_position is not None:
            self.queue_position = max(0, self.queue_position - 1)
            if self.queue_position == 0:
                self.status = ServerStatus.LOADING

    def trigger_plus_one(self) -> bool:
        if self.status == ServerStatus.ONLINE:
            self.countdown = 360  # Resets to 6 minutes
            self.plus_one_clicks += 1
            self.last_plus_one = datetime.now(timezone.utc)
            return True
        return False

    def start(self) -> bool:
        if self.status in [ServerStatus.OFFLINE, ServerStatus.CRASHED]:
            self.status = ServerStatus.IN_QUEUE
            self.queue_position = 5
            self.queue_time = "1 min"
            return True
        return False

    def confirm_queue(self) -> bool:
        if self.status in [ServerStatus.IN_QUEUE, ServerStatus.LOADING]:
            self.status = ServerStatus.LOADING
            self.queue_position = None
            return True
        return False

    def finish_loading(self) -> bool:
        if self.status == ServerStatus.LOADING:
            self.status = ServerStatus.ONLINE
            self.countdown = 360
            return True
        return False

    def stop(self) -> bool:
        if self.status in [ServerStatus.ONLINE, ServerStatus.LOADING, ServerStatus.IN_QUEUE]:
            self.status = ServerStatus.STOPPING
            self.countdown = None
            return True
        return False

    def finish_stopping(self) -> bool:
        if self.status == ServerStatus.STOPPING:
            self.status = ServerStatus.OFFLINE
            return True
        return False

    def crash(self):
        self.status = ServerStatus.CRASHED
        self.countdown = None
        self.crash_mode = True


class MockKeepAliveEngine:
    """Mock engine implementing full interface contracts with high-fidelity control."""
    def __init__(self, mock_server: Optional[MockAternosServer] = None):
        self.mock_server = mock_server or MockAternosServer()
        self.logger = MockLogBroadcaster()
        self.is_keepalive_active = True
        self.session_valid = True
        self.threshold_seconds = 180
        self.emergency_threshold_seconds = 30
        self._loop_running = False

    def get_state(self) -> ServerState:
        s = self.mock_server
        countdown = s.countdown if s.status == ServerStatus.ONLINE else None
        countdown_text = None
        if countdown is not None:
            mins, secs = divmod(countdown, 60)
            countdown_text = f"{mins:02d}:{secs:02d}"

        return ServerState(
            status=s.status,
            countdown_seconds=countdown,
            countdown_text=countdown_text,
            last_plus_one_click=s.last_plus_one,
            plus_one_click_count=s.plus_one_clicks,
            queue_position=s.queue_position if s.status == ServerStatus.IN_QUEUE else None,
            queue_time=s.queue_time if s.status == ServerStatus.IN_QUEUE else None,
            is_keepalive_active=self.is_keepalive_active,
            session_valid=self.session_valid,
            last_updated=datetime.now(timezone.utc)
        )

    def toggle_keepalive(self, enabled: Optional[bool] = None) -> bool:
        if enabled is None:
            self.is_keepalive_active = not self.is_keepalive_active
        else:
            self.is_keepalive_active = enabled
        self.logger.log(f"Keep-alive monitoring set to {self.is_keepalive_active}", "INFO")
        return self.is_keepalive_active

    def trigger_plus_one(self) -> bool:
        success = self.mock_server.trigger_plus_one()
        if success:
            self.logger.log(
                f"Clicked '+1' button successfully - Timer extended to {self.mock_server.countdown}s",
                "PLUS_ONE",
                {"clicks": self.mock_server.plus_one_clicks}
            )
        else:
            self.logger.log("Failed to click '+1' button: server not online or button missing", "WARN")
        return success

    def start_server(self) -> bool:
        success = self.mock_server.start()
        if success:
            self.logger.log("Server start initiated - Entering queue", "SUCCESS")
        else:
            self.logger.log("Cannot start server: server is already running or loading", "WARN")
        return success

    def stop_server(self) -> bool:
        success = self.mock_server.stop()
        if success:
            self.logger.log("Server stop command issued", "WARN")
        else:
            self.logger.log("Cannot stop server: server is already offline", "WARN")
        return success

    def confirm_queue(self) -> bool:
        success = self.mock_server.confirm_queue()
        if success:
            self.logger.log("Queue confirmation button clicked - Loading server", "SUCCESS")
        return success

    def reload_session(self) -> bool:
        self.session_valid = True
        self.logger.log("Session reloaded and validated successfully", "INFO")
        return True

    def get_screenshot(self) -> bytes:
        # Return a valid 1x1 PNG pixel
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    def check_and_perform_keepalive(self) -> bool:
        """Executes one tick of keep-alive logic."""
        if not self.is_keepalive_active:
            return False
        state = self.get_state()
        if state.status == ServerStatus.ONLINE and state.countdown_seconds is not None:
            if state.countdown_seconds <= self.threshold_seconds:
                return self.trigger_plus_one()
        elif state.status == ServerStatus.IN_QUEUE and self.mock_server.queue_position == 0:
            return self.confirm_queue()
        return False


# ---------------------------------------------------------------------------
# Mock Playwright Driver Hierarchy
# ---------------------------------------------------------------------------

class MockPlaywrightElement:
    def __init__(self, selector: str, text: str = "", visible: bool = True, is_enabled: bool = True):
        self.selector = selector
        self._text = text
        self._visible = visible
        self._enabled = is_enabled
        self.click_count = 0

    async def click(self):
        if not self._enabled or not self._visible:
            raise RuntimeError(f"Element {self.selector} is not clickable")
        self.click_count += 1
        return True

    async def text_content(self) -> str:
        return self._text

    async def inner_text(self) -> str:
        return self._text

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled


class MockPlaywrightPage:
    def __init__(self):
        self.url = "https://aternos.org/server/"
        self.elements: Dict[str, MockPlaywrightElement] = {}
        self.cookies: List[Dict[str, Any]] = []
        self.closed = False
        self._init_scripts: List[str] = []

    def set_element(self, selector: str, text: str = "", visible: bool = True, enabled: bool = True):
        self.elements[selector] = MockPlaywrightElement(selector, text, visible, enabled)

    async def goto(self, url: str, **kwargs):
        self.url = url
        return MagicMock(status=200)

    async def query_selector(self, selector: str) -> Optional[MockPlaywrightElement]:
        return self.elements.get(selector)

    async def wait_for_selector(self, selector: str, timeout: int = 5000) -> Optional[MockPlaywrightElement]:
        if selector in self.elements and self.elements[selector]._visible:
            return self.elements[selector]
        return None

    async def click(self, selector: str, **kwargs):
        elem = self.elements.get(selector)
        if elem:
            return await elem.click()
        raise RuntimeError(f"Element not found for selector: {selector}")

    async def screenshot(self, **kwargs) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    async def add_init_script(self, script: str):
        self._init_scripts.append(script)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        if "navigator.webdriver" in expression:
            return False
        return True

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_server() -> MockAternosServer:
    return MockAternosServer()


@pytest.fixture
def mock_engine(mock_server: MockAternosServer) -> MockKeepAliveEngine:
    return MockKeepAliveEngine(mock_server=mock_server)


@pytest.fixture
def sample_state_online() -> ServerState:
    return ServerState(
        status=ServerStatus.ONLINE,
        countdown_seconds=120,
        countdown_text="02:00",
        plus_one_click_count=3,
        is_keepalive_active=True,
        session_valid=True
    )


@pytest.fixture
def sample_state_queue() -> ServerState:
    return ServerState(
        status=ServerStatus.IN_QUEUE,
        queue_position=2,
        queue_time="30s",
        is_keepalive_active=True,
        session_valid=True
    )


@pytest.fixture
def sample_state_offline() -> ServerState:
    return ServerState(
        status=ServerStatus.OFFLINE,
        countdown_seconds=None,
        countdown_text=None,
        is_keepalive_active=True,
        session_valid=True
    )


@pytest.fixture
def mock_browser_page() -> MockPlaywrightPage:
    page = MockPlaywrightPage()
    page.set_element(".statuslabel-label", "Online", visible=True)
    page.set_element(".countdown", "02:45", visible=True)
    page.set_element("#extend", "+1", visible=True)
    page.set_element("#start", "Start", visible=True)
    page.set_element("#stop", "Stop", visible=True)
    page.set_element("#confirm", "Confirm", visible=True)
    return page
