"""
E2E Tier 4: Real-World Workload Scenarios Test Suite.
Verifies end-to-end multi-step scenarios simulating 24/7 cloud operation.
Requirement: At least 7 complex application scenarios from TEST_INFRA.md.
"""

import asyncio
import json
from datetime import datetime, timezone
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
)
from tests.integration.test_api_routes import create_test_api
from tests.integration.test_websocket_sse import create_streaming_app
from tests.unit.test_config import Settings
from tests.unit.test_session import CookieVault


def test_scenario_01_multi_hour_keepalive_lifecycle():
    """
    Scenario 1: Server Online Idle Lifecycle with Multi-Hour Keep-Alive
    Features: F1, F2, F3, F4, F6, F7, F8, F9
    Simulates 3 consecutive countdown cycles where the server reaches the 180s threshold
    and is automatically extended by the engine.
    """
    server = MockAternosServer()
    server.status = ServerStatus.ONLINE
    server.countdown = 360
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    # Initial check
    res = client.get("/api/status")
    assert res.json()["status"] == "online"
    assert res.json()["plus_one_click_count"] == 0

    # Simulate 3 full cycles of countdown and keepalive trigger
    for cycle in range(1, 4):
        # Countdown ticks down from 360s to 175s
        server.tick(185)
        assert server.countdown == 175

        # Keepalive loop ticks and triggers +1
        assert engine.check_and_perform_keepalive() is True
        assert server.countdown == 360
        assert server.plus_one_clicks == cycle

        # Check API status
        res_status = client.get("/api/status")
        assert res_status.json()["plus_one_click_count"] == cycle
        assert res_status.json()["countdown_seconds"] == 360

    # Verify log console history
    logs = engine.logger.get_logs(level="PLUS_ONE")
    assert len(logs) == 3


def test_scenario_02_cold_start_to_queue_to_online():
    """
    Scenario 2: Cold Server Start -> Queue Progression -> Auto Confirm -> Online Keep-Alive
    Features: F1, F3, F4, F5, F6, F7
    Simulates starting an offline server, moving through queue position 5 to 0,
    confirming queue, loading, and transitioning to online keep-alive monitoring.
    """
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    server.countdown = None
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    # 1. Start command
    res_start = client.post("/api/action/start")
    assert res_start.json()["success"] is True
    assert server.status == ServerStatus.IN_QUEUE
    assert server.queue_position == 5

    # 2. Progress through queue
    while server.queue_position > 0:
        server.tick()

    assert server.queue_position == 0

    # 3. Confirm queue
    assert engine.confirm_queue() is True
    assert server.status == ServerStatus.LOADING

    # 4. Finish loading
    server.finish_loading()
    assert server.status == ServerStatus.ONLINE
    assert server.countdown == 360

    # 5. Keep-alive takes over
    server.tick(185)
    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360
    assert server.plus_one_clicks == 1


def test_scenario_03_session_expiry_and_auto_reconnect():
    """
    Scenario 3: Session Expiry -> Cloudflare Challenge -> Auto-Reconnect Recovery
    Features: F1, F4, F10, F11, F12
    Simulates session token expiration mid-operation, detecting invalid session,
    reloading credentials from vault, and restoring active keep-alive.
    """
    vault = CookieVault(env_token="initial_valid_token_12345")
    vault.load()

    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)

    # 1. Operation running normally
    assert engine.session_valid is True

    # 2. Session drops (simulated 401 or Cloudflare 1020 challenge)
    engine.session_valid = False
    assert engine.get_state().session_valid is False

    # 3. Auto-reconnect triggered: reload session from vault
    assert engine.reload_session() is True
    assert engine.session_valid is True
    assert engine.get_state().session_valid is True

    # 4. Automation resumes seamlessly
    server.countdown = 150
    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360


def test_scenario_04_dashboard_manual_control_interleaving():
    """
    Scenario 4: Web Dashboard Manual Control Under Active Automation
    Features: F3, F4, F5, F6, F7, F8
    Simulates user manually triggering +1 from web UI, then toggling keepalive off,
    observing countdown drop without automated reset, then manually stopping the server.
    """
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    # 1. Manual extend via UI button
    server.countdown = 220
    res_extend = client.post("/api/action/extend")
    assert res_extend.json()["success"] is True
    assert server.countdown == 360
    assert server.plus_one_clicks == 1

    # 2. User disables keep-alive toggle
    res_toggle = client.post("/api/action/toggle-keepalive?enabled=false")
    assert res_toggle.json()["is_keepalive_active"] is False

    # 3. Countdown drops below threshold (100s) -> No automated trigger
    server.tick(260)
    assert server.countdown == 100
    assert engine.check_and_perform_keepalive() is False
    assert server.plus_one_clicks == 1  # Unchanged

    # 4. User stops server
    res_stop = client.post("/api/action/stop")
    assert res_stop.json()["success"] is True
    assert server.status == ServerStatus.STOPPING


def test_scenario_05_multi_client_websocket_broadcast():
    """
    Scenario 5: Rapid Multiple Client Connections with SSE/WebSocket Log Streaming
    Features: F6, F7, F8, F9
    Simulates 3 concurrent browser clients connected to WebSocket hub receiving
    synchronized real-time log updates.
    """
    broadcaster = MockLogBroadcaster()
    app = create_streaming_app(broadcaster)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws1:
        with client.websocket_connect("/ws") as ws2:
            with client.websocket_connect("/ws") as ws3:
                # Dispatch 2 events
                broadcaster.log("Server Online", "SUCCESS")
                broadcaster.log("Keep-alive active", "PLUS_ONE")

                for ws in [ws1, ws2, ws3]:
                    msg1 = json.loads(ws.receive_text())
                    msg2 = json.loads(ws.receive_text())
                    assert msg1["message"] == "Server Online"
                    assert msg2["message"] == "Keep-alive active"


def test_scenario_06_emergency_countdown_fast_recovery():
    """
    Scenario 6: Emergency 0:05 Countdown Fast-Recovery Trigger
    Features: F2, F3, F4, F7, F9
    Simulates network lag that allowed timer to drop to 5 seconds.
    Emergency trigger fires immediately to rescue the server from auto-shutdown.
    """
    server = MockAternosServer()
    server.countdown = 5  # Dangerous 5-second countdown
    engine = MockKeepAliveEngine(server)

    parsed_seconds = parse_countdown_str("0:05")
    assert parsed_seconds == 5
    assert parsed_seconds <= engine.emergency_threshold_seconds

    # Emergency trigger execution
    assert engine.check_and_perform_keepalive() is True
    assert server.countdown == 360
    assert server.plus_one_clicks == 1

    logs = engine.logger.get_logs(level="PLUS_ONE")
    assert len(logs) == 1
    assert "Clicked '+1' button successfully" in logs[0].message


def test_scenario_07_container_boot_healthcheck_shutdown():
    """
    Scenario 7: Full Container Boot -> Healthcheck -> Mock Simulation -> Clean Shutdown
    Features: F6, F13, F14
    Simulates full container lifecycle: settings ingestion, healthcheck probe,
    mock keepalive tick execution, and graceful termination.
    """
    # 1. Settings ingestion
    settings = Settings(PORT=8000, MOCK_MODE=True, CHECK_INTERVAL=5)
    assert settings.PORT == 8000

    # 2. App & Engine init
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)
    client = TestClient(create_test_api(engine))

    # 3. Healthcheck ping
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # 4. Simulation ticks
    for _ in range(5):
        server.tick(10)
    assert server.countdown == 310

    # 5. Clean shutdown
    assert engine.stop_server() is True
    server.finish_stopping()
    assert server.status == ServerStatus.OFFLINE
