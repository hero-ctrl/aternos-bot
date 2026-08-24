"""
Centralized Event Logger, Circular Ring Buffer & Real-Time Pub/Sub Broadcaster.
Provides thread-safe and async-safe dispatching to SSE and WebSocket clients.
"""

import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import sys
import threading
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union

import colorama
from colorama import Fore, Style

from src.core.schemas import LogEvent, LogLevel, ServerState

colorama.init(autoreset=True)


class LogBroadcaster:
    """
    Centralized event broadcaster and circular ring-buffer logger.
    Manages SSE generators, WebSocket queues, and non-blocking backpressure.
    """
    def __init__(self, buffer_size: int = 1000) -> None:
        self._max_buffer = buffer_size
        self._buffer: deque[LogEvent] = deque(maxlen=buffer_size)
        self._subscribers: Set[asyncio.Queue[LogEvent]] = set()
        self._state_subscribers: Set[asyncio.Queue[ServerState]] = set()
        self._lock = threading.Lock()

    @property
    def logs(self) -> List[LogEvent]:
        """Direct list access for test compatibility."""
        with self._lock:
            return list(self._buffer)

    def log(
        self,
        *args: Any,
        message: Optional[str] = None,
        level: Optional[str] = None,
        source: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> LogEvent:
        """
        Record a log event, append to ring buffer, and broadcast to active async subscribers.
        Supports all calling signatures:
          log(message: str, level: str = "INFO", ...)
          log(level: str, message: str, ...)
          log(message="...", level="...", source="...", data=...)
        """
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
        if source is None:
            source = "keepalive"

        # Normalize level naming
        if level == "WARNING":
            level = "WARN"

        event = LogEvent(
            level=level,
            message=message,
            source=source,
            data=data,
            timestamp=datetime.now(timezone.utc)
        )

        with self._lock:
            self._buffer.append(event)

        self.broadcast_log(event)
        return event

    def broadcast_log(self, event: LogEvent) -> None:
        """Dispatches LogEvent to all active async subscriber queues safely."""
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                if hasattr(q, "_loop") and q._loop and q._loop.is_running():
                    try:
                        curr_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        curr_loop = None
                    if curr_loop is q._loop:
                        q.put_nowait(event)
                    else:
                        q._loop.call_soon_threadsafe(self._safe_put, q, event)
                else:
                    q.put_nowait(event)
            except Exception:
                pass

    @staticmethod
    def _safe_put(q: asyncio.Queue, item: Any) -> None:
        try:
            q.put_nowait(item)
        except Exception:
            pass

    def broadcast_state(self, state: ServerState) -> None:
        """Dispatches ServerState snapshot to active state subscribers."""
        with self._lock:
            subs = list(self._state_subscribers)
        for q in subs:
            try:
                if hasattr(q, "_loop") and q._loop and q._loop.is_running():
                    try:
                        curr_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        curr_loop = None
                    if curr_loop is q._loop:
                        q.put_nowait(state)
                    else:
                        q._loop.call_soon_threadsafe(self._safe_put, q, state)
                else:
                    q.put_nowait(state)
            except Exception:
                pass

    def get_history(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[LogEvent]:
        """Retrieve recent logs from in-memory ring buffer with optional filtering."""
        with self._lock:
            events = list(self._buffer)

        if level:
            target_level = level.upper()
            if target_level == "WARNING":
                target_level = "WARN"
            events = [e for e in events if e.level == target_level or (target_level == "WARN" and e.level in ("WARN", "WARNING"))]

        if search:
            search_lower = search.lower()
            events = [e for e in events if search_lower in e.message.lower()]

        return events[-limit:]

    def get_logs(
        self,
        level: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100
    ) -> List[LogEvent]:
        """Alias for get_history for test compatibility."""
        return self.get_history(limit=limit, level=level, search=search)

    def clear_history(self) -> None:
        """Clears the in-memory log buffer."""
        with self._lock:
            self._buffer.clear()

    def clear(self) -> None:
        """Alias for clear_history."""
        self.clear_history()

    def subscribe(self) -> AsyncGenerator[LogEvent, None]:
        """
        Async generator yielding real-time LogEvents for Server-Sent Events (SSE).
        Registers queue immediately upon creation to prevent race condition event drops.
        Automatically unregisters on client disconnect.
        """
        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)

        async def _generator() -> AsyncGenerator[LogEvent, None]:
            try:
                while True:
                    event = await queue.get()
                    yield event
                    queue.task_done()
            finally:
                self._subscribers.discard(queue)

        return _generator()

    def subscribe_logs(self) -> AsyncGenerator[LogEvent, None]:
        """Alias for subscribe."""
        return self.subscribe()

    def subscribe_state(self) -> AsyncGenerator[ServerState, None]:
        """Async generator yielding ServerState updates for SSE stream."""
        queue: asyncio.Queue[ServerState] = asyncio.Queue(maxsize=20)
        self._state_subscribers.add(queue)

        async def _generator() -> AsyncGenerator[ServerState, None]:
            try:
                while True:
                    state = await queue.get()
                    yield state
                    queue.task_done()
            finally:
                self._state_subscribers.discard(queue)

        return _generator()

    def subscribe_queue(self) -> asyncio.Queue[LogEvent]:
        """Subscribe direct queue for WebSocket consumer loops."""
        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe_queue(self, queue: asyncio.Queue[LogEvent]) -> None:
        """Unsubscribe WebSocket queue."""
        self._subscribers.discard(queue)


class AppLogger:
    """
    Unified application logger combining standard console output with LogBroadcaster.
    """
    def __init__(self, broadcaster: Optional[LogBroadcaster] = None, log_level: str = "INFO") -> None:
        self.broadcaster = broadcaster or LogBroadcaster(buffer_size=1000)
        self._console_logger = logging.getLogger("aternos_bot")
        self._setup_console_logger(log_level)

    def _setup_console_logger(self, log_level_name: str) -> None:
        level = getattr(logging, log_level_name.upper(), logging.INFO)
        self._console_logger.setLevel(level)
        self._console_logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        self._console_logger.addHandler(handler)

    def info(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        self._console_logger.info(f"{Fore.CYAN}{message}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="INFO", source=source, data=data)

    def success(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        self._console_logger.info(f"{Fore.GREEN}[SUCCESS] {message}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="SUCCESS", source=source, data=data)

    def warning(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        self._console_logger.warning(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="WARN", source=source, data=data)

    def warn(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        return self.warning(message=message, source=source, data=data)

    def error(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        self._console_logger.error(f"{Fore.RED}{message}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="ERROR", source=source, data=data)

    def debug(self, message: str, source: str = "keepalive", data: Optional[Dict[str, Any]] = None) -> LogEvent:
        self._console_logger.debug(f"{Fore.WHITE}{message}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="DEBUG", source=source, data=data)

    def plus_one(
        self,
        message: str,
        remaining_seconds: Optional[int] = None,
        new_seconds: Optional[int] = None,
        tier: Optional[str] = None,
        source: str = "engine",
        data: Optional[Dict[str, Any]] = None
    ) -> LogEvent:
        """Dedicated high-visibility log method for '+1' extension clicks."""
        meta = data or {}
        if remaining_seconds is not None:
            meta["remaining_seconds"] = remaining_seconds
        if new_seconds is not None:
            meta["new_seconds"] = new_seconds
        if tier is not None:
            meta["tier"] = tier

        tier_str = f" (Tier: {tier})" if tier else ""
        self._console_logger.info(f"{Fore.MAGENTA}{Style.BRIGHT}[+1 CLICK] {message}{tier_str}{Style.RESET_ALL}")
        return self.broadcaster.log(message=message, level="PLUS_ONE", source=source, data=meta)

    def log_event(
        self,
        *args: Any,
        level: Optional[str] = None,
        message: Optional[str] = None,
        source: str = "keepalive",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> LogEvent:
        return self.broadcaster.log(*args, level=level, message=message, source=source, data=data, **kwargs)

    def log(
        self,
        *args: Any,
        message: Optional[str] = None,
        level: Optional[str] = None,
        source: str = "keepalive",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> LogEvent:
        return self.broadcaster.log(*args, message=message, level=level, source=source, data=data, **kwargs)


# Global singleton instance
app_logger = AppLogger()
