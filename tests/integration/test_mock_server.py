"""
Integration tests for Standalone Mock Aternos Server.
Tests HTML page rendering, AJAX endpoints, state transitions, countdown ticks, and health status.
"""

from fastapi.testclient import TestClient
import pytest

from src.bot.mock_server import MockAternosServer, create_mock_app
from src.core.schemas import ServerStatus


def test_mock_server_html_page_rendering():
    """Verify mock server serves HTML dashboard mimicking Aternos web panel."""
    server = MockAternosServer(initial_status=ServerStatus.ONLINE, initial_countdown=300)
    app = create_mock_app(server)
    client = TestClient(app)

    res = client.get("/server/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Aternos Minecraft Server" in res.text
    assert "Online" in res.text
    assert "05:00" in res.text
    assert 'id="extend"' in res.text


def test_mock_server_ajax_status_endpoint():
    """Verify /ajax/status.php returns JSON state."""
    server = MockAternosServer(initial_status=ServerStatus.ONLINE, initial_countdown=240)
    app = create_mock_app(server)
    client = TestClient(app)

    res = client.get("/ajax/status.php")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["countdown"] == 240
    assert data["plus_one_clicks"] == 0


def test_mock_server_ajax_extend_endpoint():
    """Verify /ajax/extend.php resets countdown and increments plus_one_clicks."""
    server = MockAternosServer(initial_status=ServerStatus.ONLINE, initial_countdown=120)
    app = create_mock_app(server)
    client = TestClient(app)

    res = client.post("/ajax/extend.php")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["countdown"] == 360
    assert data["clicks"] == 1


def test_mock_server_lifecycle_endpoints():
    """Verify start, confirm, stop AJAX lifecycle endpoints."""
    server = MockAternosServer(initial_status=ServerStatus.OFFLINE)
    app = create_mock_app(server)
    client = TestClient(app)

    # 1. Start
    res_start = client.post("/ajax/start.php")
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True
    assert server.status == ServerStatus.IN_QUEUE

    # 2. Confirm queue
    res_confirm = client.post("/ajax/confirm.php")
    assert res_confirm.status_code == 200
    assert res_confirm.json()["success"] is True
    assert server.status == ServerStatus.LOADING

    # Finish loading
    server.finish_loading()
    assert server.status == ServerStatus.ONLINE

    # 3. Stop
    res_stop = client.post("/ajax/stop.php")
    assert res_stop.status_code == 200
    assert res_stop.json()["success"] is True
    assert server.status == ServerStatus.STOPPING


def test_mock_server_tick_endpoint():
    """Verify /api/mock/tick decrements countdown."""
    server = MockAternosServer(initial_status=ServerStatus.ONLINE, initial_countdown=300)
    app = create_mock_app(server)
    client = TestClient(app)

    res = client.post("/api/mock/tick?seconds=15")
    assert res.status_code == 200
    assert res.json()["countdown"] == 285


def test_mock_server_health():
    """Verify /health endpoint on mock server."""
    server = MockAternosServer()
    app = create_mock_app(server)
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
