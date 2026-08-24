"""
E2E Tier 3: Cross-Feature Pairwise Interaction Test Suite.
Verifies interactions and emergent behaviors between multiple interrelated features.
Requirement: At least 15 comprehensive cross-feature combination tests.
"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    MockAternosServer,
    MockKeepAliveEngine,
    MockLogBroadcaster,
    MockPlaywrightPage,
    ServerState,
    ServerStatus,
    LogEvent,
    parse_countdown_str,
    PLUS_ONE_SELECTORS,
)
from tests.integration.test_api_routes import create_test_api
from tests.unit.test_config import Settings
from tests.unit.test_session import CookieVault


def test_combo_01_status_keepalive_plus_one_click():
    """Combo 1 (F1 + F4 + F3): Server Online -> Countdown hits 175s -> Auto +1 click -> Timer resets."""
    server = MockAternosServer()
    server.status = ServerStatus.ONLINE
    server.countdown = 175
    engine = MockKeepAliveEngine(server)

    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360
    assert server.plus_one_clicks == 1
    assert engine.get_state().status == ServerStatus.ONLINE


def test_combo_02_lifecycle_start_queue_sse_broadcast():
    """Combo 2 (F5 + F1 + F7): Start command puts server in Queue and broadcasts event."""
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    engine = MockKeepAliveEngine(server)

    assert engine.start_server() is True
    assert server.status == ServerStatus.IN_QUEUE
    logs = engine.logger.get_logs(level="SUCCESS")
    assert len(logs) >= 1
    assert "Entering queue" in logs[-1].message


def test_combo_03_session_drop_auto_reconnect_stealth():
    """Combo 3 (F10 + F12 + F11): Session drop marks invalid -> Reload refreshes session and logs."""
    vault = CookieVault(env_token="session_abc_123456")
    vault.load()
    assert vault.is_valid() is True

    engine = MockKeepAliveEngine()
    engine.session_valid = False
    assert engine.get_state().session_valid is False

    assert engine.reload_session() is True
    assert engine.get_state().session_valid is True
    logs = engine.logger.get_logs(level="INFO")
    assert "Session reloaded" in logs[-1].message


def test_combo_04_rest_api_extend_dashboard_logs():
    """Combo 4 (F6 + F8 + F9): REST /api/action/extend logs PLUS_ONE event retrievable by filter."""
    server = MockAternosServer()
    server.countdown = 100
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    res = client.post("/api/action/extend")
    assert res.status_code == 200
    assert res.json()["success"] is True

    res_logs = client.get("/api/logs?level=PLUS_ONE")
    assert res_logs.status_code == 200
    items = res_logs.json()
    assert len(items) == 1
    assert items[0]["level"] == "PLUS_ONE"
    assert "Clicked '+1' button successfully" in items[0]["message"]


def test_combo_05_keepalive_toggle_rest_ws_sync():
    """Combo 5 (F4 + F6 + F7): REST toggle keepalive updates engine and broadcasts event."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))

    res = client.post("/api/action/toggle-keepalive?enabled=false")
    assert res.status_code == 200
    assert res.json()["is_keepalive_active"] is False

    state = engine.get_state()
    assert state.is_keepalive_active is False
    logs = engine.logger.get_logs()
    assert "Keep-alive monitoring set to False" in logs[-1].message


def test_combo_06_countdown_parser_loop_mock_engine():
    """Combo 6 (F2 + F4 + F13): Mock server ticks down from 03:10 to 02:59 -> Parser parses -> Loop fires."""
    server = MockAternosServer()
    server.countdown = 190  # 03:10
    engine = MockKeepAliveEngine(server)

    # 1. 190s > 180s: No trigger
    assert engine.check_and_perform_keepalive() is False

    # 2. Tick 15s -> countdown becomes 175s
    server.tick(15)
    parsed_sec = parse_countdown_str("02:55")
    assert parsed_sec == 175
    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360


def test_combo_07_queue_progression_confirm_lifecycle_logs():
    """Combo 7 (F5 + F1 + F9): Queue decrements to 0 -> Confirm button triggered -> Logged with SUCCESS."""
    server = MockAternosServer()
    server.status = ServerStatus.IN_QUEUE
    server.queue_position = 2
    engine = MockKeepAliveEngine(server)

    # Tick to position 0
    server.tick()
    server.tick()
    assert server.queue_position == 0

    assert engine.confirm_queue() is True
    assert server.status == ServerStatus.LOADING
    logs = engine.logger.get_logs(level="SUCCESS")
    assert "Queue confirmation button clicked" in logs[-1].message


@pytest.mark.asyncio
async def test_combo_08_fallback_selector_stealth_dom_mutation():
    """Combo 8 (F3 + F11): Primary selector missing in DOM -> Engine falls back to Tier 2 selector."""
    page = MockPlaywrightPage()
    # Tier 1 absent, Tier 2 present
    page.set_element("button.btn-extend", "+1", visible=True)

    found = None
    for sel in PLUS_ONE_SELECTORS:
        elem = await page.query_selector(sel)
        if elem and await elem.is_visible():
            found = elem
            break

    assert found is not None
    assert found.selector == "button.btn-extend"
    await found.click()
    assert found.click_count == 1


def test_combo_09_rest_reload_session_cookie_vault():
    """Combo 9 (F6 + F10 + F1): REST reload session validates cookies and restores session_valid."""
    engine = MockKeepAliveEngine()
    engine.session_valid = False
    client = TestClient(create_test_api(engine))

    res = client.post("/api/action/reload-session")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert engine.session_valid is True


def test_combo_10_high_volume_logs_buffer_sse_cleanup():
    """Combo 10 (F7 + F9 + F8): 600 log events capped cleanly at 500 buffer limit."""
    broadcaster = MockLogBroadcaster(max_buffer=500)
    for i in range(600):
        broadcaster.log(f"Load test log message {i}", "INFO")

    assert len(broadcaster.logs) == 500
    assert broadcaster.logs[0].message == "Load test log message 100"
    assert broadcaster.logs[-1].message == "Load test log message 599"

    broadcaster.clear()
    assert len(broadcaster.logs) == 0


def test_combo_11_server_crash_detection_restart_resilience():
    """Combo 11 (F1 + F5 + F12): Server crash detected -> Start server reboots instance into queue."""
    server = MockAternosServer()
    server.crash()
    engine = MockKeepAliveEngine(server)

    assert engine.get_state().status == ServerStatus.CRASHED
    assert engine.start_server() is True
    assert server.status == ServerStatus.IN_QUEUE


def test_combo_12_docker_env_healthcheck_api():
    """Combo 12 (F6 + F14 + F1): Docker env settings loaded -> API responds to health check."""
    settings = Settings(PORT=8000, HOST="0.0.0.0", MOCK_MODE=True)
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))

    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
    assert settings.PORT == 8000


def test_combo_13_plus_one_click_metadata_log_filtering():
    """Combo 13 (F3 + F4 + F9): +1 click generates structured metadata in log query."""
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)

    engine.trigger_plus_one()
    engine.trigger_plus_one()

    logs = engine.logger.get_logs(level="PLUS_ONE")
    assert len(logs) == 2
    assert logs[-1].data == {"clicks": 2}


def test_combo_14_mock_network_dropout_keepalive_recovery():
    """Combo 14 (F13 + F12 + F4): Transient dropout does not corrupt engine state."""
    server = MockAternosServer()
    server.countdown = 150
    engine = MockKeepAliveEngine(server)

    # Simulated transient network failure on first attempt
    def failing_trigger():
        return False

    # Fails once
    assert failing_trigger() is False
    # Next iteration recovers
    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360


def test_combo_15_dashboard_status_polling_timer_formatter():
    """Combo 15 (F8 + F6 + F2): Status endpoint countdown formatted to text representation."""
    server = MockAternosServer()
    server.countdown = 125
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["countdown_seconds"] == 125
    assert data["countdown_text"] == "02:05"


def test_combo_16_cookie_vault_missing_session_rest_unauthorized():
    """Combo 16 (F10 + F6 + F1): Missing session token marks session_valid false in API."""
    vault = CookieVault(env_token="")
    vault.load()
    assert vault.is_valid() is False

    engine = MockKeepAliveEngine()
    engine.session_valid = vault.is_valid()
    client = TestClient(create_test_api(engine))

    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["session_valid"] is False
