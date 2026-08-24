"""
Standalone High-Fidelity Mock Aternos HTTP Server & State Machine Simulator.
Provides realistic DOM HTML pages and AJAX API endpoints for offline testing,
CI pipelines, and local simulation without external Aternos dependencies.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from src.core.schemas import ServerStatus

logger = logging.getLogger("aternos_bot.mock_server")


class MockAternosServer:
    """
    High-fidelity state machine and simulation engine for Aternos backend.
    """
    def __init__(
        self,
        initial_status: ServerStatus = ServerStatus.ONLINE,
        initial_countdown: int = 360,
        initial_queue_position: Optional[int] = None
    ) -> None:
        self.status: ServerStatus = initial_status
        self.countdown: Optional[int] = initial_countdown if initial_status == ServerStatus.ONLINE else None
        self.queue_position: Optional[int] = initial_queue_position
        self.queue_time: Optional[str] = "1 min" if initial_queue_position else None
        self.plus_one_clicks: int = 0
        self.last_plus_one: Optional[datetime] = None
        self.is_running: bool = True
        self.crash_mode: bool = False
        self.cloudflare_blocked: bool = False
        self.players_current: int = 0
        self.players_max: int = 20

    def tick(self, seconds: int = 1) -> None:
        """Simulates passage of time across all lifecycle states."""
        if self.status == ServerStatus.ONLINE and self.countdown is not None:
            self.countdown = max(0, self.countdown - seconds)
            if self.countdown == 0 and self.players_current == 0:
                self.status = ServerStatus.STOPPING
                self.countdown = None
        elif self.status == ServerStatus.IN_QUEUE and self.queue_position is not None:
            self.queue_position = max(0, self.queue_position - 1)
            if self.queue_position == 0:
                self.status = ServerStatus.LOADING
        elif self.status == ServerStatus.LOADING:
            # Auto-transition to online after loading
            pass

    def trigger_plus_one(self) -> bool:
        """Simulates clicking the +1 extension button."""
        if self.status == ServerStatus.ONLINE:
            self.countdown = 360  # Resets back to full 6 minutes
            self.plus_one_clicks += 1
            self.last_plus_one = datetime.now(timezone.utc)
            return True
        return False

    def start(self) -> bool:
        """Simulates initiating server boot."""
        if self.status in (ServerStatus.OFFLINE, ServerStatus.CRASHED):
            self.status = ServerStatus.IN_QUEUE
            self.queue_position = 5
            self.queue_time = "1 min"
            self.crash_mode = False
            return True
        return False

    def confirm_queue(self) -> bool:
        """Simulates clicking the Queue Confirm button."""
        if self.status in (ServerStatus.IN_QUEUE, ServerStatus.LOADING):
            self.status = ServerStatus.LOADING
            self.queue_position = None
            self.queue_time = None
            return True
        return False

    def finish_loading(self) -> bool:
        """Simulates server finishing startup and transitioning to ONLINE."""
        if self.status == ServerStatus.LOADING:
            self.status = ServerStatus.ONLINE
            self.countdown = 360
            return True
        return False

    def stop(self) -> bool:
        """Simulates issuing Stop command."""
        if self.status in (ServerStatus.ONLINE, ServerStatus.LOADING, ServerStatus.IN_QUEUE):
            self.status = ServerStatus.STOPPING
            self.countdown = None
            return True
        return False

    def finish_stopping(self) -> bool:
        """Simulates server finishing shutdown and transitioning to OFFLINE."""
        if self.status == ServerStatus.STOPPING:
            self.status = ServerStatus.OFFLINE
            return True
        return False

    def crash(self) -> None:
        """Simulates unexpected server crash."""
        self.status = ServerStatus.CRASHED
        self.countdown = None
        self.crash_mode = True


def generate_aternos_html(server: MockAternosServer) -> str:
    """Renders HTML page mimicking the actual Aternos server panel DOM."""
    mins = (server.countdown // 60) if server.countdown is not None else 0
    secs = (server.countdown % 60) if server.countdown is not None else 0
    cd_text = f"{mins:02d}:{secs:02d}" if server.countdown is not None else ""
    status_label = server.status.value.capitalize()
    if server.status == ServerStatus.IN_QUEUE:
        status_label = "In queue"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Aternos Server Dashboard (Mock)</title>
    <style>
        body {{ font-family: sans-serif; background: #1e293b; color: #f8fafc; padding: 20px; }}
        .server-status {{ background: #334155; padding: 20px; border-radius: 8px; max-width: 600px; margin: 0 auto; }}
        .statuslabel-label {{ font-size: 24px; font-weight: bold; color: #10b981; }}
        .statuslabel-countdown {{ margin: 15px 0; font-size: 20px; }}
        .countdown {{ font-family: monospace; font-weight: bold; background: #0f172a; padding: 4px 8px; border-radius: 4px; }}
        button {{ cursor: pointer; padding: 8px 16px; margin: 5px; font-weight: bold; border-radius: 4px; border: none; }}
        .btn-extend {{ background: #3b82f6; color: white; }}
        .btn-start {{ background: #10b981; color: white; }}
        .btn-stop {{ background: #ef4444; color: white; }}
        .btn-confirm {{ background: #f59e0b; color: white; }}
    </style>
</head>
<body>
    <div class="server-status">
        <h2>Aternos Minecraft Server</h2>
        <div class="statuslabel">
            Status: <span class="statuslabel-label">{status_label}</span>
        </div>
        <div class="statuslabel-countdown">
            Timer: <span class="countdown" id="countdown">{cd_text}</span>
            <button id="extend" class="btn btn-extend btn-extend-timer" data-action="extend" title="Extend timer">+1</button>
        </div>
        <div class="server-actions">
            <button id="start" class="btn btn-start" title="Start server">Start</button>
            <button id="stop" class="btn btn-stop" title="Stop server">Stop</button>
            <button id="confirm" class="btn btn-confirm" title="Confirm queue">Confirm</button>
            <button id="restart" class="btn btn-restart" title="Restart server">Restart</button>
        </div>
        <div class="queue-info" style="display: {'block' if server.status == ServerStatus.IN_QUEUE else 'none'}">
            Queue Position: <span class="queue-position">{server.queue_position or 0}</span> (Estimated: <span class="queue-time">{server.queue_time or ''}</span>)
        </div>
    </div>
</body>
</html>
"""


def create_mock_app(server: Optional[MockAternosServer] = None) -> FastAPI:
    """
    Factory for FastAPI mock server mimicking Aternos web panel.
    """
    mock_state = server or MockAternosServer()
    app = FastAPI(title="Mock Aternos Server", docs_url=None, redoc_url=None)
    app.state.server = mock_state

    @app.get("/")
    @app.get("/server/")
    @app.get("/server/{server_id}/")
    async def serve_server_page():
        return HTMLResponse(content=generate_aternos_html(mock_state), status_code=200)

    @app.get("/ajax/status.php")
    @app.get("/api/mock/status")
    async def get_mock_status():
        return {
            "status": mock_state.status.value,
            "countdown": mock_state.countdown,
            "plus_one_clicks": mock_state.plus_one_clicks,
            "queue_position": mock_state.queue_position,
            "players": mock_state.players_current,
        }

    @app.post("/ajax/extend.php")
    @app.post("/api/mock/extend")
    async def mock_extend():
        success = mock_state.trigger_plus_one()
        return {"success": success, "countdown": mock_state.countdown, "clicks": mock_state.plus_one_clicks}

    @app.post("/ajax/start.php")
    @app.post("/api/mock/start")
    async def mock_start():
        success = mock_state.start()
        return {"success": success, "status": mock_state.status.value}

    @app.post("/ajax/stop.php")
    @app.post("/api/mock/stop")
    async def mock_stop():
        success = mock_state.stop()
        return {"success": success, "status": mock_state.status.value}

    @app.post("/ajax/confirm.php")
    @app.post("/api/mock/confirm")
    async def mock_confirm():
        success = mock_state.confirm_queue()
        return {"success": success, "status": mock_state.status.value}

    @app.post("/api/mock/tick")
    async def mock_tick(seconds: int = 1):
        mock_state.tick(seconds)
        return {"countdown": mock_state.countdown, "status": mock_state.status.value}

    @app.get("/health")
    async def health():
        return {"status": "healthy", "mode": "mock_aternos_server"}

    return app


# Default singleton instance for ASGI runners
mock_server_instance = MockAternosServer()
app = create_mock_app(mock_server_instance)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
