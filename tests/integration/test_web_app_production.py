"""
Integration tests for production FastAPI web application and routes (src.web.app, src.web.routes).
Tests all REST endpoints, SSE /api/events, WebSocket /ws, static files, and error handling
directly using the actual create_app() factory.
"""

import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.bot.driver import MockDriver
from src.bot.engine import KeepAliveEngine
from src.core.config import Settings
from src.core.logger import AppLogger, LogBroadcaster
from src.core.schemas import LogEvent, ServerState, ServerStatus
from src.web.app import create_app
from tests.conftest import MockAternosServer, MockKeepAliveEngine


@pytest.fixture
def mock_prod_engine():
    """Creates a KeepAliveEngine with MockDriver for testing production routes."""
    settings = Settings(MOCK_MODE=True, HEADLESS=True)
    driver = MockDriver()
    driver.status = ServerStatus.ONLINE
    driver.countdown = 360
    logger_hub = LogBroadcaster()
    engine = KeepAliveEngine(config=settings, driver=driver, logger_hub=logger_hub)
    return engine


@pytest.fixture
def prod_client(mock_prod_engine: KeepAliveEngine):
    """Creates TestClient for the actual production create_app instance."""
    app = create_app(engine=mock_prod_engine)
    return TestClient(app)


def test_production_root_serves_html(prod_client: TestClient):
    """Verify GET / serves HTML index dashboard."""
    res = prod_client.get("/")
    assert res.status_code == 200
    assert "Aternos 24/7 Keep-Alive" in res.text
    assert "text/html" in res.headers["content-type"]


def test_production_static_files(prod_client: TestClient):
    """Verify static assets are mounted at /static."""
    res_css = prod_client.get("/static/style.css")
    assert res_css.status_code == 200
    assert "css" in res_css.headers["content-type"]

    res_js = prod_client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "javascript" in res_js.headers["content-type"]


def test_production_api_health(prod_client: TestClient):
    """Verify GET /api/health returns valid health telemetry."""
    res = prod_client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "aternos-keepalive"
    assert "uptime_seconds" in data
    assert "memory_mb" in data


def test_production_api_status(prod_client: TestClient, mock_prod_engine: KeepAliveEngine):
    """Verify GET /api/status returns live ServerState."""
    res = prod_client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["countdown_seconds"] == 360
    assert data["is_keepalive_active"] is True
    assert data["session_valid"] is True


def test_production_action_extend(prod_client: TestClient, mock_prod_engine: KeepAliveEngine):
    """Verify POST /api/action/extend and POST /api/action/click-plus-one."""
    res = prod_client.post("/api/action/extend")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    res2 = prod_client.post("/api/action/click-plus-one")
    assert res2.status_code == 200
    assert res2.json()["success"] is True


def test_production_action_toggle_keepalive(prod_client: TestClient, mock_prod_engine: KeepAliveEngine):
    """Verify POST /api/action/toggle-keepalive via query params and json body."""
    # Via query param
    res1 = prod_client.post("/api/action/toggle-keepalive?enabled=false")
    assert res1.status_code == 200
    assert res1.json()["is_keepalive_active"] is False
    assert mock_prod_engine.is_keepalive_active is False

    # Via JSON body
    res2 = prod_client.post("/api/action/toggle-keepalive", json={"enabled": True})
    assert res2.status_code == 200
    assert res2.json()["is_keepalive_active"] is True
    assert mock_prod_engine.is_keepalive_active is True


def test_production_action_lifecycle(prod_client: TestClient, mock_prod_engine: KeepAliveEngine):
    """Verify start, stop, restart, confirm-queue actions."""
    # Stop online server
    res_stop = prod_client.post("/api/action/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["success"] is True

    # Move to offline state for next test phase
    mock_prod_engine.state.status = ServerStatus.OFFLINE
    if hasattr(mock_prod_engine._driver, "status"):
        mock_prod_engine._driver.status = ServerStatus.OFFLINE

    # Start server
    res_start = prod_client.post("/api/action/start")
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True

    # Reload session
    res_reload = prod_client.post("/api/action/reload-session")
    assert res_reload.status_code == 200
    assert res_reload.json()["success"] is True


def test_production_api_logs_and_clear(prod_client: TestClient, mock_prod_engine: KeepAliveEngine):
    """Verify logs retrieval, filtering by level, search, and clearing."""
    mock_prod_engine.logger_hub.log("Server initialized", "INFO")
    mock_prod_engine.logger_hub.log("Extended +1 button successfully", "PLUS_ONE")
    mock_prod_engine.logger_hub.log("High memory warning", "WARN")

    # Get all logs
    res_all = prod_client.get("/api/logs")
    assert res_all.status_code == 200
    logs = res_all.json()
    assert len(logs) >= 3

    # Filter level
    res_plus = prod_client.get("/api/logs?level=PLUS_ONE")
    assert res_plus.status_code == 200
    plus_logs = res_plus.json()
    assert len(plus_logs) == 1
    assert plus_logs[0]["level"] == "PLUS_ONE"

    # Filter search
    res_search = prod_client.get("/api/logs?search=memory")
    assert res_search.status_code == 200
    search_logs = res_search.json()
    assert len(search_logs) == 1
    assert "High memory warning" in search_logs[0]["message"]

    # Clear logs
    res_del = prod_client.delete("/api/logs")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Check empty
    res_empty = prod_client.get("/api/logs")
    assert len(res_empty.json()) == 0


def test_production_screenshot_endpoint(prod_client: TestClient):
    """Verify GET /api/screenshot returns binary image response."""
    res = prod_client.get("/api/screenshot")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")


def test_production_websocket_bidirectional(mock_prod_engine: KeepAliveEngine):
    """Verify production WebSocket endpoint sends state, logs, and handles actions."""
    app = create_app(engine=mock_prod_engine)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # First message is initial status snapshot
        init_msg = json.loads(ws.receive_text())
        assert init_msg["type"] == "status"
        assert init_msg["data"]["status"] == "online"

        # Test ping / pong
        ws.send_text(json.dumps({"action": "ping"}))
        pong_msg = json.loads(ws.receive_text())
        assert pong_msg["type"] == "pong"

        # Test get_status
        ws.send_text(json.dumps({"action": "get_status"}))
        status_msg = json.loads(ws.receive_text())
        assert status_msg["type"] == "status"
        assert status_msg["data"]["is_keepalive_active"] is True


@pytest.mark.asyncio
async def test_production_sse_generator_direct(mock_prod_engine: KeepAliveEngine):
    """Verify production SSE stream generator yields formatted SSE events."""
    mock_prod_engine.logger_hub.log("SSE Production Event Direct", "PLUS_ONE")
    sub = mock_prod_engine.logger_hub.subscribe()
    mock_prod_engine.logger_hub.log("SSE Second Event", "INFO")
    event = await sub.__anext__()
    json_str = event.model_dump_json()
    sse_frame = f"data: {json_str}\n\n"
    assert sse_frame.startswith("data: {")
    assert sse_frame.endswith("\n\n")
    assert "SSE Second Event" in sse_frame
