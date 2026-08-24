"""
Integration tests for KeepAliveEngine and MockAternosServer.
Validates state machine transitions, automated +1 extension loop,
lifecycle actions, queue confirmations, and error state handling.
"""

import pytest
from tests.conftest import (
    MockAternosServer,
    MockKeepAliveEngine,
    ServerStatus,
)


def test_engine_initial_state(mock_engine: MockKeepAliveEngine):
    """Verify engine starts in a consistent initial state."""
    state = mock_engine.get_state()
    assert state.status == ServerStatus.ONLINE
    assert state.countdown_seconds == 360
    assert state.is_keepalive_active is True
    assert state.plus_one_click_count == 0
    assert state.session_valid is True


def test_keepalive_auto_trigger_at_threshold(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify keep-alive triggers +1 click when timer drops below threshold (<= 180s)."""
    # 1. Timer at 300s (> 180s) -> should NOT trigger
    mock_server.countdown = 300
    triggered = mock_engine.check_and_perform_keepalive()
    assert triggered is False
    assert mock_server.plus_one_clicks == 0

    # 2. Timer ticks down to 175s (<= 180s) -> should trigger +1
    mock_server.countdown = 175
    triggered = mock_engine.check_and_perform_keepalive()
    assert triggered is True
    assert mock_server.plus_one_clicks == 1
    assert mock_server.countdown == 360  # Reset back to full countdown


def test_keepalive_disabled_does_not_trigger(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify disabled keep-alive prevents automated +1 clicking."""
    mock_engine.toggle_keepalive(False)
    assert mock_engine.is_keepalive_active is False

    mock_server.countdown = 60  # Well below threshold
    triggered = mock_engine.check_and_perform_keepalive()
    assert triggered is False
    assert mock_server.plus_one_clicks == 0


def test_manual_plus_one_trigger(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify manual trigger_plus_one successfully resets timer and logs event."""
    mock_server.countdown = 200
    success = mock_engine.trigger_plus_one()
    assert success is True
    assert mock_server.plus_one_clicks == 1
    assert mock_server.countdown == 360

    logs = mock_engine.logger.get_logs(level="PLUS_ONE")
    assert len(logs) >= 1
    assert "Clicked '+1' button successfully" in logs[-1].message


def test_server_lifecycle_start_to_queue_to_online(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify start lifecycle moves server through queue, confirmation, and online states."""
    # Put server offline
    mock_server.status = ServerStatus.OFFLINE
    mock_server.countdown = None

    # 1. Start server
    assert mock_engine.start_server() is True
    assert mock_server.status == ServerStatus.IN_QUEUE
    assert mock_server.queue_position == 5

    # 2. Progress queue
    for _ in range(5):
        mock_server.tick()
    assert mock_server.queue_position == 0
    assert mock_server.status == ServerStatus.LOADING or mock_engine.confirm_queue()

    # 3. Finish loading
    mock_server.finish_loading()
    assert mock_server.status == ServerStatus.ONLINE
    assert mock_server.countdown == 360


def test_server_stop_lifecycle(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify stop command transitions server through STOPPING to OFFLINE."""
    assert mock_server.status == ServerStatus.ONLINE
    assert mock_engine.stop_server() is True
    assert mock_server.status == ServerStatus.STOPPING

    mock_server.finish_stopping()
    assert mock_server.status == ServerStatus.OFFLINE
    assert mock_server.countdown is None


def test_crash_detection_and_safety(mock_engine: MockKeepAliveEngine, mock_server: MockAternosServer):
    """Verify engine handles crash state without attempting invalid +1 clicks."""
    mock_server.crash()
    state = mock_engine.get_state()
    assert state.status == ServerStatus.CRASHED

    # Keep-alive check should do nothing on crashed server
    triggered = mock_engine.check_and_perform_keepalive()
    assert triggered is False
    assert mock_server.plus_one_clicks == 0


def test_screenshot_capture(mock_engine: MockKeepAliveEngine):
    """Verify get_screenshot returns valid PNG binary stream."""
    img_bytes = mock_engine.get_screenshot()
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 8
    assert img_bytes.startswith(b"\x89PNG")
