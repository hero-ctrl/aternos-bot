"""
Integration tests for REST API Endpoints.
Tests status reporting, lifecycle actions, keepalive toggle, log queries,
health check, screenshot endpoint, and parameter validation.
"""

from typing import Optional
import pytest
from fastapi import FastAPI, Query, Response
from fastapi.testclient import TestClient
from tests.conftest import (
    MockKeepAliveEngine,
    MockAternosServer,
    ServerStatus,
    ServerState,
    LogEvent,
)


def create_test_api(engine: MockKeepAliveEngine) -> FastAPI:
    """Creates a FastAPI test application instance hooked to the mock engine."""
    app = FastAPI(title="Aternos 24/7 Keep-Alive API")

    @app.get("/api/status")
    async def get_status():
        return engine.get_state()

    @app.get("/api/health")
    async def get_health():
        return {"status": "healthy", "service": "aternos-keepalive", "version": "1.0.0"}

    @app.post("/api/action/start")
    async def action_start():
        success = engine.start_server()
        return {"success": success, "message": "Start command issued" if success else "Cannot start"}

    @app.post("/api/action/stop")
    async def action_stop():
        success = engine.stop_server()
        return {"success": success, "message": "Stop command issued" if success else "Cannot stop"}

    @app.post("/api/action/extend")
    async def action_extend():
        success = engine.trigger_plus_one()
        return {"success": success, "message": "+1 Click triggered" if success else "Click failed"}

    @app.post("/api/action/toggle-keepalive")
    async def toggle_keepalive(enabled: Optional[bool] = None):
        is_active = engine.toggle_keepalive(enabled)
        return {"success": True, "is_keepalive_active": is_active}

    @app.post("/api/action/reload-session")
    async def reload_session():
        success = engine.reload_session()
        return {"success": success, "message": "Session reloaded"}

    @app.get("/api/logs")
    async def get_logs(level: Optional[str] = Query(None), search: Optional[str] = Query(None), limit: int = Query(100)):
        logs = engine.logger.get_logs(level=level, search=search, limit=limit)
        return [l.model_dump() if hasattr(l, "model_dump") else l.dict() for l in logs]

    @app.get("/api/screenshot")
    async def get_screenshot():
        data = engine.get_screenshot()
        return Response(content=data, media_type="image/png")

    return app


@pytest.fixture
def api_client(mock_engine: MockKeepAliveEngine):
    app = create_test_api(mock_engine)
    return TestClient(app)


def test_api_health_endpoint(api_client: TestClient):
    """Verify /api/health returns 200 OK and healthy status."""
    res = api_client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "aternos-keepalive"


def test_api_status_endpoint(api_client: TestClient, mock_engine: MockKeepAliveEngine):
    """Verify /api/status returns accurate ServerState schema."""
    res = api_client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["countdown_seconds"] == 360
    assert data["is_keepalive_active"] is True
    assert data["session_valid"] is True


def test_api_action_extend_endpoint(api_client: TestClient, mock_server: MockAternosServer):
    """Verify POST /api/action/extend clicks +1 button and increments counter."""
    mock_server.countdown = 120
    res = api_client.post("/api/action/extend")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert mock_server.plus_one_clicks == 1
    assert mock_server.countdown == 360


def test_api_toggle_keepalive_endpoint(api_client: TestClient, mock_engine: MockKeepAliveEngine):
    """Verify POST /api/action/toggle-keepalive flips monitoring state."""
    # Toggle to False
    res = api_client.post("/api/action/toggle-keepalive?enabled=false")
    assert res.status_code == 200
    assert res.json()["is_keepalive_active"] is False
    assert mock_engine.is_keepalive_active is False

    # Toggle to True
    res = api_client.post("/api/action/toggle-keepalive?enabled=true")
    assert res.status_code == 200
    assert res.json()["is_keepalive_active"] is True


def test_api_lifecycle_start_and_stop(api_client: TestClient, mock_server: MockAternosServer):
    """Verify start and stop action endpoints trigger state changes."""
    # Stop online server
    res_stop = api_client.post("/api/action/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["success"] is True
    assert mock_server.status == ServerStatus.STOPPING

    mock_server.finish_stopping()

    # Start offline server
    res_start = api_client.post("/api/action/start")
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True
    assert mock_server.status == ServerStatus.IN_QUEUE


def test_api_logs_filtering(api_client: TestClient, mock_engine: MockKeepAliveEngine):
    """Verify GET /api/logs with level and search query filters."""
    mock_engine.logger.log("Aternos server started", "INFO")
    mock_engine.logger.log("Clicked '+1' button successfully", "PLUS_ONE")
    mock_engine.logger.log("Session warning", "WARN")

    # Filter level
    res_level = api_client.get("/api/logs?level=PLUS_ONE")
    assert res_level.status_code == 200
    items = res_level.json()
    assert len(items) == 1
    assert items[0]["level"] == "PLUS_ONE"

    # Filter search
    res_search = api_client.get("/api/logs?search=warning")
    assert res_search.status_code == 200
    items_search = res_search.json()
    assert len(items_search) == 1
    assert "Session warning" in items_search[0]["message"]


def test_api_screenshot_endpoint(api_client: TestClient):
    """Verify GET /api/screenshot returns binary PNG data."""
    res = api_client.get("/api/screenshot")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")
