"""
Data Contracts, Enums, DTOs & Real-Time Event Schemas.
Conforms strictly to Pydantic V2.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, Field


class ServerStatus(str, Enum):
    """Aternos Server Lifecycle Statuses."""
    OFFLINE = "offline"
    IN_QUEUE = "in_queue"
    LOADING = "loading"
    ONLINE = "online"
    STOPPING = "stopping"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


class LogLevel(str, Enum):
    """Application and Event Log Levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    PLUS_ONE = "PLUS_ONE"


class ActionType(str, Enum):
    """Supported Server and Bot Actions."""
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    EXTEND = "extend"
    CONFIRM = "confirm"
    TOGGLE_KEEPALIVE = "toggle_keepalive"
    RELOAD_SESSION = "reload_session"


class EventType(str, Enum):
    """Real-Time SSE/WebSocket Broadcast Event Types."""
    STATUS_CHANGE = "status_change"
    TIMER_TICK = "timer_tick"
    PLUS_ONE_CLICK = "plus_one_click"
    QUEUE_UPDATE = "queue_update"
    LOG = "log"
    SYSTEM = "system"
    HEARTBEAT = "heartbeat"


class ServerState(BaseModel):
    """Live Server State Representation."""
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        use_enum_values=True
    )

    status: ServerStatus = Field(default=ServerStatus.OFFLINE, description="Current server lifecycle status")
    status_code: int = Field(default=0, description="Numeric status code")
    countdown_seconds: Optional[int] = Field(default=None, description="Integer remaining seconds on idle timer")
    countdown_text: Optional[str] = Field(default=None, description="Formatted countdown string 'mm:ss'")
    last_plus_one_click: Optional[datetime] = Field(default=None, description="UTC timestamp of last successful +1 click")
    plus_one_click_count: int = Field(default=0, ge=0, description="Total +1 clicks executed in current session")
    players_current: int = Field(default=0, ge=0, description="Current connected players")
    players_max: int = Field(default=20, ge=1, description="Maximum server player capacity")
    ram_usage: Optional[str] = Field(default=None, description="Current RAM usage string (e.g., '1.2 GB / 2.4 GB')")
    server_ip: Optional[str] = Field(default=None, description="Minecraft server address (e.g., 'myhost.aternos.me')")
    queue_position: Optional[int] = Field(default=None, ge=0, description="Current queue position number")
    queue_time: Optional[str] = Field(default=None, description="Estimated queue wait time")
    is_keepalive_active: bool = Field(default=True, description="Whether automated +1 keepalive polling is enabled")
    session_valid: bool = Field(default=True, description="Whether Aternos session cookies are authenticated")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of last update")
    error_message: Optional[str] = Field(default=None, description="Last error or warning message")

    @property
    def is_online(self) -> bool:
        return self.status == ServerStatus.ONLINE or self.status == "online"

    @property
    def is_countdown_critical(self) -> bool:
        return self.countdown_seconds is not None and self.countdown_seconds <= 30


class LogEvent(BaseModel):
    """Structured unit for application logs, console displays, and SSE/WebSocket events."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8], description="Unique event identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC event creation timestamp")
    level: str = Field(default="INFO", description="Log level (INFO, SUCCESS, WARN, ERROR, PLUS_ONE)")
    message: str = Field(..., min_length=1, description="Human-readable event message")
    source: str = Field(default="keepalive", description="Source component: 'driver', 'engine', 'web', 'session'")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Structured contextual metadata")

    def to_sse_format(self) -> str:
        """Formats the log event into Server-Sent Events (SSE) data frame format."""
        json_data = self.model_dump_json()
        return f"event: log\ndata: {json_data}\n\n"


class ActionResult(BaseModel):
    """Generic action outcome result from driver/engine."""
    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="Whether action succeeded")
    message: str = Field(default="", description="Detailed outcome message")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata or return payload")

    def __bool__(self) -> bool:
        return self.success


class ServerStatusSnapshot(BaseModel):
    """Point-in-time snapshot extracted directly from DOM / mock."""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    status: ServerStatus = Field(default=ServerStatus.UNKNOWN)
    status_code: int = Field(default=0)
    countdown_seconds: Optional[int] = Field(default=None)
    countdown_text: Optional[str] = Field(default=None)
    players_current: int = Field(default=0)
    players_max: int = Field(default=20)
    ram_usage: Optional[str] = Field(default=None)
    server_ip: Optional[str] = Field(default=None)
    queue_position: Optional[int] = Field(default=None)
    queue_time: Optional[str] = Field(default=None)
    session_valid: bool = Field(default=True)
    error_message: Optional[str] = Field(default=None)


class ControlActionRequest(BaseModel):
    """API request payload for executing a server control action."""
    action: ActionType = Field(..., description="Action to execute")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Optional parameters for action")


class ControlActionResponse(BaseModel):
    """API response payload for executed control action."""
    success: bool = Field(..., description="Whether action was dispatched successfully")
    action: ActionType = Field(..., description="Executed action type")
    message: str = Field(..., description="Result message or error details")
    state: Optional[ServerState] = Field(default=None, description="Updated server state after action")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KeepAliveToggleRequest(BaseModel):
    """API request payload for toggling keepalive status."""
    enabled: Optional[bool] = Field(default=None, description="Target state. If None, toggles current state.")


class KeepAliveToggleResponse(BaseModel):
    """API response payload for keepalive toggle."""
    success: bool = Field(default=True)
    is_keepalive_active: bool = Field(...)
    message: str = Field(...)


class StatusResponse(BaseModel):
    """API response payload for /api/status."""
    success: bool = Field(default=True)
    state: ServerState = Field(...)
    uptime_seconds: float = Field(default=0.0, ge=0.0)
    mock_mode: bool = Field(default=False)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthResponse(BaseModel):
    """API response payload for /api/health."""
    status: str = Field(default="healthy")
    version: str = Field(default="1.0.0")
    browser_connected: bool = Field(default=False)
    keepalive_running: bool = Field(default=False)
    memory_mb: float = Field(default=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SSEEventPayload(BaseModel):
    """SSE broadcast payload wrapper."""
    event: EventType = Field(default=EventType.STATUS_CHANGE)
    data: Union[ServerState, LogEvent, Dict[str, Any]] = Field(...)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str = Field(..., description="Message type: 'status', 'log', 'ping', 'pong', 'action'")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
