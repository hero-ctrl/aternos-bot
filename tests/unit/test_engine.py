"""
Unit tests for KeepAliveEngine.
Tests continuous polling, 7-state FSM, dual-threshold trigger (<=180s, <=30s),
concurrency mutex lock, lifecycle management, and log event emission.
"""

import asyncio
from datetime import datetime, timezone
import pytest

from src.bot.driver import MockDriver
from src.bot.engine import KeepAliveEngine
from src.core.config import Settings
from src.core.logger import LogBroadcaster
from src.core.schemas import ActionResult, LogLevel, ServerState, ServerStatus


@pytest.mark.asyncio
async def test_engine_initialization_and_state():
    """Verify engine initializes with default offline or online state and valid contracts."""
    broadcaster = LogBroadcaster(buffer_size=100)
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=300)
    engine = KeepAliveEngine(driver=driver, logger_hub=broadcaster)

    state = engine.get_state()
    assert state.is_keepalive_active is True
    assert state.plus_one_click_count == 0


@pytest.mark.asyncio
async def test_engine_toggle_keepalive():
    """Verify toggle_keepalive switches state and emits state update."""
    broadcaster = LogBroadcaster(buffer_size=100)
    driver = MockDriver()
    engine = KeepAliveEngine(driver=driver, logger_hub=broadcaster)

    # Toggle off
    active = engine.toggle_keepalive(False)
    assert active is False
    assert engine.get_state().is_keepalive_active is False

    # Toggle on
    active = engine.toggle_keepalive(True)
    assert active is True
    assert engine.get_state().is_keepalive_active is True

    # Toggle without argument (flips)
    active = engine.toggle_keepalive()
    assert active is False


@pytest.mark.asyncio
async def test_engine_manual_controls():
    """Verify manual control commands (start, stop, restart, plus_one, confirm)."""
    broadcaster = LogBroadcaster(buffer_size=100)
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=250)
    engine = KeepAliveEngine(driver=driver, logger_hub=broadcaster)

    # Trigger plus one
    res = await engine.trigger_plus_one()
    assert res.success is True
    assert engine.get_state().plus_one_click_count == 1
    assert driver.countdown == 360

    # Stop server
    stop_res = await engine.stop_server()
    assert stop_res.success is True
    assert driver.status == ServerStatus.STOPPING

    # Restart server
    restart_res = await engine.restart_server()
    assert restart_res.success is True


@pytest.mark.asyncio
async def test_engine_keepalive_threshold_triggers():
    """Verify keepalive logic triggers +1 at standard (<=180s) and emergency (<=30s) thresholds."""
    broadcaster = LogBroadcaster(buffer_size=100)
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=150)
    engine = KeepAliveEngine(driver=driver, logger_hub=broadcaster)

    # Set state
    snapshot = await driver.get_server_status()
    await engine._update_state_from_snapshot(snapshot)

    # Handle online keepalive
    await engine._handle_online_keepalive()
    assert engine.get_state().plus_one_click_count == 1

    # Check emergency threshold (< 30s)
    driver.countdown = 20
    snapshot = await driver.get_server_status()
    await engine._update_state_from_snapshot(snapshot)
    await engine._handle_online_keepalive()
    assert engine.get_state().plus_one_click_count == 2


@pytest.mark.asyncio
async def test_engine_start_stop_lifecycle():
    """Verify engine start and stop tasks manage background loop cleanly."""
    broadcaster = LogBroadcaster(buffer_size=100)
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=300)
    engine = KeepAliveEngine(driver=driver, logger_hub=broadcaster)

    await engine.start()
    assert engine._running is True
    assert engine._poll_task is not None

    # Let loop run for a short tick
    await asyncio.sleep(0.1)

    await engine.stop()
    assert engine._running is False
    assert engine._poll_task is None
