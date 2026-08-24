"""
Unit tests for Log Broadcaster, Ring Buffer, and Real-Time Event Hub.
Tests log event creation, subscriber dispatch, filtering by level/keyword,
buffer capping, and formatted export.
"""

import asyncio
import pytest
from tests.conftest import MockLogBroadcaster, LogEvent


def test_log_broadcaster_basic_logging():
    """Verify logging messages appends to internal buffer with correct levels."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    event = broadcaster.log("Test info message", "INFO")
    assert isinstance(event, LogEvent)
    assert event.message == "Test info message"
    assert event.level == "INFO"
    assert len(broadcaster.logs) == 1


def test_log_broadcaster_ring_buffer_capping():
    """Verify ring buffer caps at max_buffer and discards oldest messages."""
    max_buf = 10
    broadcaster = MockLogBroadcaster(max_buffer=max_buf)
    for i in range(25):
        broadcaster.log(f"Message {i}", "INFO")

    assert len(broadcaster.logs) == max_buf
    assert broadcaster.logs[0].message == "Message 15"
    assert broadcaster.logs[-1].message == "Message 24"


def test_log_filtering_by_level():
    """Verify get_logs filters by exact level case-insensitively."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    broadcaster.log("Info message 1", "INFO")
    broadcaster.log("Success message", "SUCCESS")
    broadcaster.log("Clicked +1 button", "PLUS_ONE")
    broadcaster.log("Warning happened", "WARN")
    broadcaster.log("Error occurred", "ERROR")

    plus_one_logs = broadcaster.get_logs(level="PLUS_ONE")
    assert len(plus_one_logs) == 1
    assert plus_one_logs[0].level == "PLUS_ONE"
    assert "Clicked +1" in plus_one_logs[0].message

    warn_logs = broadcaster.get_logs(level="warn")
    assert len(warn_logs) == 1
    assert warn_logs[0].level == "WARN"


def test_log_filtering_by_search_keyword():
    """Verify get_logs filters messages containing search substring."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    broadcaster.log("Aternos server is starting up", "INFO")
    broadcaster.log("Server online, countdown at 03:00", "SUCCESS")
    broadcaster.log("Queue position changed to 1", "INFO")

    results = broadcaster.get_logs(search="countdown")
    assert len(results) == 1
    assert "countdown at 03:00" in results[0].message


@pytest.mark.asyncio
async def test_log_broadcaster_async_subscriber():
    """Verify async subscriber queue receives dispatched log events."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    subscriber_gen = broadcaster.subscribe()

    # Log in background
    broadcaster.log("Dispatched to subscriber", "SUCCESS")

    received = await asyncio.wait_for(subscriber_gen.__anext__(), timeout=1.0)
    assert received.message == "Dispatched to subscriber"
    assert received.level == "SUCCESS"


@pytest.mark.asyncio
async def test_log_broadcaster_multiple_subscribers():
    """Verify multiple concurrent subscribers all receive the broadcasted event."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    sub1 = broadcaster.subscribe()
    sub2 = broadcaster.subscribe()

    broadcaster.log("Broadcast event", "PLUS_ONE")

    ev1 = await asyncio.wait_for(sub1.__anext__(), timeout=1.0)
    ev2 = await asyncio.wait_for(sub2.__anext__(), timeout=1.0)

    assert ev1.message == "Broadcast event"
    assert ev2.message == "Broadcast event"
    assert ev1.level == "PLUS_ONE"
    assert ev2.level == "PLUS_ONE"
