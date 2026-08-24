"""
Unit tests for Playwright Driver Architecture & MockDriver.
Tests stealth initialization, route interception, selector dispatch, screenshot capture,
and deterministic mock driver lifecycle.
"""

import asyncio
from datetime import datetime, timezone
import pytest

from src.bot.driver import AternosDriver, MockDriver
from src.bot.selectors import classify_status_text, parse_countdown_str
from src.core.config import Settings
from src.core.schemas import ActionResult, ServerStatus, ServerStatusSnapshot


@pytest.mark.asyncio
async def test_mock_driver_initialization():
    """Verify mock driver initializes with expected default status and values."""
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=300)
    await driver.initialize()
    assert driver.is_initialized is True

    snapshot = await driver.get_server_status()
    assert snapshot.status == ServerStatus.ONLINE
    assert snapshot.countdown_seconds == 300
    assert snapshot.countdown_text == "05:00"
    assert snapshot.session_valid is True


@pytest.mark.asyncio
async def test_mock_driver_plus_one_click():
    """Verify click_plus_one extends countdown to 360s and increments click count."""
    driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=120)
    result = await driver.click_plus_one()
    assert isinstance(result, ActionResult)
    assert result.success is True
    assert driver.plus_one_clicks == 1
    assert driver.countdown == 360
    assert driver.last_plus_one is not None

    snapshot = await driver.get_server_status()
    assert snapshot.countdown_seconds == 360


@pytest.mark.asyncio
async def test_mock_driver_lifecycle_actions():
    """Verify mock driver lifecycle transitions for start, confirm, stop, restart."""
    driver = MockDriver(initial_status=ServerStatus.OFFLINE, initial_countdown=None)
    
    # 1. Start server -> enters queue
    start_res = await driver.start_server()
    assert start_res.success is True
    assert driver.status == ServerStatus.IN_QUEUE
    assert driver.queue_position == 5

    # 2. Confirm queue -> starts loading
    confirm_res = await driver.confirm_queue()
    assert confirm_res.success is True
    assert driver.status == ServerStatus.LOADING
    assert driver.queue_position is None

    # 3. Simulate tick -> transitions to online
    driver.tick(1)
    assert driver.status == ServerStatus.ONLINE
    assert driver.countdown == 360

    # 4. Stop server -> stopping -> offline
    stop_res = await driver.stop_server()
    assert stop_res.success is True
    assert driver.status == ServerStatus.STOPPING

    driver.tick(1)
    assert driver.status == ServerStatus.OFFLINE
    assert driver.countdown is None


@pytest.mark.asyncio
async def test_mock_driver_screenshot_and_session():
    """Verify screenshot returns valid PNG bytes and reload_session succeeds."""
    driver = MockDriver()
    img = await driver.get_screenshot()
    assert isinstance(img, bytes)
    assert img.startswith(b"\x89PNG")

    reload_ok = await driver.reload_session()
    assert reload_ok is True
    assert driver.session_valid is True


def test_classify_status_text_variations():
    """Verify classify_status_text maps diverse DOM strings to ServerStatus enum."""
    assert classify_status_text("Offline") == ServerStatus.OFFLINE
    assert classify_status_text("statuslabel-label-offline") == ServerStatus.OFFLINE
    assert classify_status_text("Waiting in queue...") == ServerStatus.IN_QUEUE
    assert classify_status_text("Loading...") == ServerStatus.LOADING
    assert classify_status_text("Starting...") == ServerStatus.LOADING
    assert classify_status_text("Online") == ServerStatus.ONLINE
    assert classify_status_text("Stopping...") == ServerStatus.STOPPING
    assert classify_status_text("Server Crashed") == ServerStatus.CRASHED
    assert classify_status_text("Random Unknown String") == ServerStatus.UNKNOWN
    assert classify_status_text(None) == ServerStatus.UNKNOWN
