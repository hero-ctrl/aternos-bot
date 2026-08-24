"""
REST API Endpoints, Server-Sent Events (SSE), and WebSocket Real-Time Handlers.
Provides full programmatic control and real-time observability for Aternos Keep-Alive Bot.
"""

import asyncio
from datetime import datetime, timezone
import inspect
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import psutil
from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.logger import LogBroadcaster, app_logger
from src.core.schemas import (
    ActionResult,
    ActionType,
    ControlActionRequest,
    ControlActionResponse,
    HealthResponse,
    KeepAliveToggleRequest,
    KeepAliveToggleResponse,
    LogEvent,
    LogLevel,
    ServerState,
    ServerStatus,
    StatusResponse,
)

logger = logging.getLogger("aternos_bot.web.routes")

router = APIRouter()

# Application startup timestamp for uptime calculation
START_TIME = datetime.now(timezone.utc)


def _get_engine(request: Request) -> Any:
    """Helper to retrieve KeepAliveEngine attached to app state or fallback."""
    if hasattr(request.app.state, "engine") and request.app.state.engine is not None:
        return request.app.state.engine
    # Fallback to engine attribute if available
    return getattr(request.app, "engine", None)


async def _execute_engine_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Safely executes either synchronous or asynchronous engine functions."""
    if func is None:
        return None
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    res = func(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res


# ===========================================================================
# 1. Health and Status Endpoints
# ===========================================================================

@router.get("/health", response_model=Dict[str, Any], tags=["System"])
@router.get("/api/health", response_model=Dict[str, Any], tags=["System"])
async def get_health(request: Request) -> Dict[str, Any]:
    """
    Health check endpoint for Docker container checks, Render, Fly.io, and uptime monitors.
    """
    engine = _get_engine(request)
    uptime_sec = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    
    session_valid = True
    is_keepalive = True
    if engine is not None:
        if hasattr(engine, "session_valid"):
            session_valid = bool(engine.session_valid)
        elif hasattr(engine, "state") and hasattr(engine.state, "session_valid"):
            session_valid = bool(engine.state.session_valid)
        if hasattr(engine, "is_keepalive_active"):
            is_keepalive = bool(engine.is_keepalive_active)
        elif hasattr(engine, "state") and hasattr(engine.state, "is_keepalive_active"):
            is_keepalive = bool(engine.state.is_keepalive_active)

    memory_mb = 0.0
    try:
        process = psutil.Process()
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        pass

    return {
        "status": "healthy",
        "service": "aternos-keepalive",
        "version": "1.0.0",
        "uptime_seconds": round(uptime_sec, 1),
        "browser_connected": session_valid,
        "keepalive_running": is_keepalive,
        "memory_mb": memory_mb,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/status", tags=["Status"])
async def get_status(request: Request) -> Any:
    """
    Retrieves the complete current ServerState snapshot.
    Returns the ServerState model directly for seamless serialization.
    """
    engine = _get_engine(request)
    if engine is not None:
        if hasattr(engine, "get_state"):
            state = engine.get_state()
            return state
        if hasattr(engine, "state"):
            return engine.state
    # Default fallback state
    return ServerState()


# ===========================================================================
# 2. Control Action Endpoints
# ===========================================================================

@router.post("/api/action/start", tags=["Actions"])
async def action_start(request: Request) -> Dict[str, Any]:
    """
    Triggers server startup sequence.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "start_server"):
        return {"success": False, "message": "Engine not available", "action": "start"}

    res = await _execute_engine_call(engine.start_server)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    msg = res.message if isinstance(res, ActionResult) and res.message else ("Start command issued" if success else "Cannot start server")
    return {"success": success, "message": msg, "action": "start"}


@router.post("/api/action/stop", tags=["Actions"])
async def action_stop(request: Request) -> Dict[str, Any]:
    """
    Triggers graceful server shutdown sequence.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "stop_server"):
        return {"success": False, "message": "Engine not available", "action": "stop"}

    res = await _execute_engine_call(engine.stop_server)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    msg = res.message if isinstance(res, ActionResult) and res.message else ("Stop command issued" if success else "Cannot stop server")
    return {"success": success, "message": msg, "action": "stop"}


@router.post("/api/action/restart", tags=["Actions"])
async def action_restart(request: Request) -> Dict[str, Any]:
    """
    Triggers server restart sequence.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "restart_server"):
        return {"success": False, "message": "Engine not available", "action": "restart"}

    res = await _execute_engine_call(engine.restart_server)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    msg = res.message if isinstance(res, ActionResult) and res.message else ("Server restart initiated" if success else "Restart failed")
    return {"success": success, "message": msg, "action": "restart"}


@router.post("/api/action/confirm-queue", tags=["Actions"])
async def action_confirm_queue(request: Request) -> Dict[str, Any]:
    """
    Confirms queue position slot when required by Aternos.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "confirm_queue"):
        return {"success": False, "message": "Engine not available", "action": "confirm"}

    res = await _execute_engine_call(engine.confirm_queue)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    msg = res.message if isinstance(res, ActionResult) and res.message else ("Queue confirmed" if success else "Queue confirm failed")
    return {"success": success, "message": msg, "action": "confirm"}


@router.post("/api/action/extend", tags=["Actions"])
@router.post("/api/action/click-plus-one", tags=["Actions"])
async def action_extend(request: Request) -> Dict[str, Any]:
    """
    Manually triggers the +1 countdown timer extension click.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "trigger_plus_one"):
        return {"success": False, "message": "Engine not available"}

    res = await _execute_engine_call(engine.trigger_plus_one)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    data = res.data if isinstance(res, ActionResult) and res.data else {}
    msg = res.message if isinstance(res, ActionResult) and res.message else ("+1 Click triggered" if success else "Click failed")
    return {
        "success": success,
        "message": msg,
        "data": data,
        "clicked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/action/toggle-keepalive", tags=["Actions"])
async def action_toggle_keepalive(
    request: Request,
    enabled: Optional[bool] = Query(None),
) -> Dict[str, Any]:
    """
    Toggles or sets the automated background keepalive monitoring state.
    Supports both query param (?enabled=true/false) and JSON body ({'enabled': bool}).
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "toggle_keepalive"):
        return {"success": False, "is_keepalive_active": False, "message": "Engine not available"}

    # Check for body parameter if not in query param
    target_enabled = enabled
    if target_enabled is None:
        try:
            body = await request.json()
            if isinstance(body, dict) and "enabled" in body:
                target_enabled = body["enabled"]
        except Exception:
            pass

    is_active = engine.toggle_keepalive(target_enabled)
    status_str = "ENABLED" if is_active else "DISABLED"
    return {
        "success": True,
        "is_keepalive_active": is_active,
        "message": f"Keep-alive mode set to {status_str}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/action/reload-session", tags=["Actions"])
async def action_reload_session(request: Request) -> Dict[str, Any]:
    """
    Forces reload of browser session cookies and refreshes Aternos dashboard page.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "reload_session"):
        return {"success": False, "message": "Engine not available"}

    res = await _execute_engine_call(engine.reload_session)
    success = res.success if isinstance(res, ActionResult) else bool(res)
    return {
        "success": success,
        "message": "Session reloaded" if success else "Session reload failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/action/launch-visible-browser", tags=["Actions"])
async def action_launch_visible_browser(request: Request) -> Dict[str, Any]:
    """
    Spawns Run_Visible_Browser.bat to open the real browser window on desktop.
    """
    import subprocess
    import os
    bat_path = os.path.join(os.getcwd(), "Run_Visible_Browser.bat")
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd.exe", "/c", "start", bat_path], shell=True)
            return {"success": True, "message": "Visible browser window launched on desktop"}
    except Exception as e:
        return {"success": False, "message": f"Failed to launch: {e}"}
    return {"success": False, "message": "Visible mode is available on Windows desktop"}


# ===========================================================================
# 3. Log History and Management Endpoints
# ===========================================================================

@router.get("/api/logs", tags=["Logs"])
async def get_logs(
    request: Request,
    level: Optional[str] = Query(None, description="Filter logs by level (INFO, SUCCESS, WARN, ERROR, PLUS_ONE)"),
    search: Optional[str] = Query(None, description="Search keyword in log messages"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of logs to return"),
) -> List[Dict[str, Any]]:
    """
    Retrieves historical log entries from the circular memory ring buffer.
    """
    engine = _get_engine(request)
    broadcaster = None

    if engine is not None:
        if hasattr(engine, "logger"):
            broadcaster = engine.logger
        elif hasattr(engine, "logger_hub"):
            broadcaster = engine.logger_hub

    if broadcaster is None:
        broadcaster = app_logger.broadcaster

    if hasattr(broadcaster, "get_logs"):
        logs = broadcaster.get_logs(level=level, search=search, limit=limit)
    elif hasattr(broadcaster, "get_history"):
        logs = broadcaster.get_history(limit=limit, level=level, search=search)
    else:
        logs = []

    return [
        l.model_dump(mode="json") if hasattr(l, "model_dump") else (l.dict() if hasattr(l, "dict") else l)
        for l in logs
    ]


@router.delete("/api/logs", tags=["Logs"])
async def clear_logs(request: Request) -> Dict[str, Any]:
    """
    Clears the in-memory log circular buffer.
    """
    engine = _get_engine(request)
    broadcaster = None

    if engine is not None:
        if hasattr(engine, "logger"):
            broadcaster = engine.logger
        elif hasattr(engine, "logger_hub"):
            broadcaster = engine.logger_hub

    if broadcaster is None:
        broadcaster = app_logger.broadcaster

    if hasattr(broadcaster, "clear"):
        broadcaster.clear()
    elif hasattr(broadcaster, "clear_history"):
        broadcaster.clear_history()

    return {"success": True, "message": "Log buffer cleared"}


# ===========================================================================
# 4. Viewport Screenshot Endpoint
# ===========================================================================

@router.get("/api/screenshot", tags=["Diagnostics"])
async def get_screenshot(request: Request) -> Response:
    """
    Captures or retrieves the latest headless browser viewport snapshot as a PNG image.
    """
    engine = _get_engine(request)
    screenshot_bytes = None

    if engine is not None and hasattr(engine, "get_screenshot"):
        try:
            screenshot_bytes = await _execute_engine_call(engine.get_screenshot)
        except Exception as e:
            logger.warning(f"Error retrieving screenshot: {e}")

    # Fallback 1x1 transparent/valid PNG if engine screenshot unavailable
    if not screenshot_bytes or not isinstance(screenshot_bytes, bytes):
        screenshot_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    return Response(
        content=screenshot_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/api/viewport/click", tags=["Diagnostics"])
async def viewport_click(request: Request) -> Dict[str, Any]:
    """
    Forwards a mouse click from the dashboard viewport image to the real browser page.
    Accepts { x_pct: float, y_pct: float } (0.0 to 1.0) representing relative position on the screenshot.
    """
    engine = _get_engine(request)
    if engine is None:
        return {"success": False, "message": "Engine not available"}

    try:
        body = await request.json()
        x_pct = float(body.get("x_pct", 0))
        y_pct = float(body.get("y_pct", 0))
    except Exception:
        return {"success": False, "message": "Invalid body. Expected {x_pct, y_pct}"}

    # Get page from driver
    driver = getattr(engine, "_driver", None)
    if driver is None:
        return {"success": False, "message": "Driver not available"}

    page = getattr(driver, "_page", None)
    if page is None or page.is_closed():
        return {"success": False, "message": "Browser page not active"}

    try:
        viewport = page.viewport_size
        if viewport is None:
            viewport = {"width": 1280, "height": 800}

        actual_x = int(x_pct * viewport["width"])
        actual_y = int(y_pct * viewport["height"])

        await page.mouse.click(actual_x, actual_y)

        # Take fresh screenshot after click
        await page.wait_for_timeout(800)

        return {
            "success": True,
            "message": f"Clicked at ({actual_x}, {actual_y}) on browser page",
            "x": actual_x,
            "y": actual_y,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ===========================================================================
# 5. Server-Sent Events (SSE) Stream
# ===========================================================================

@router.get("/api/events", tags=["Real-Time Streaming"])
async def sse_events(request: Request) -> StreamingResponse:
    """
    Server-Sent Events (SSE) real-time stream broadcasting live LogEvents and ServerState updates.
    Includes X-Accel-Buffering: no for Nginx/reverse proxy compatibility and keep-alive heartbeats.
    """
    engine = _get_engine(request)
    broadcaster = None

    if engine is not None:
        if hasattr(engine, "logger"):
            broadcaster = engine.logger
        elif hasattr(engine, "logger_hub"):
            broadcaster = engine.logger_hub

    if broadcaster is None:
        broadcaster = app_logger.broadcaster

    async def sse_generator() -> AsyncGenerator[str, None]:
        # Subscribe to broadcaster log generator
        if hasattr(broadcaster, "subscribe"):
            sub = broadcaster.subscribe()
        elif hasattr(broadcaster, "subscribe_logs"):
            sub = broadcaster.subscribe_logs()
        else:
            # Fallback queue
            q: asyncio.Queue = asyncio.Queue()
            sub = q

        # Send initial state snapshot on connection
        try:
            if engine is not None and hasattr(engine, "get_state"):
                initial_state = engine.get_state()
                json_state = initial_state.model_dump_json() if hasattr(initial_state, "model_dump_json") else json.dumps(initial_state)
                yield f"event: status_update\ndata: {json_state}\n\n"
        except Exception:
            pass

        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Wait for next event with a 15s timeout for heartbeats
                    if hasattr(sub, "__anext__"):
                        event_task = asyncio.create_task(sub.__anext__())
                        done, pending = await asyncio.wait([event_task], timeout=15.0)
                        if done:
                            event = event_task.result()
                            json_str = event.model_dump_json() if hasattr(event, "model_dump_json") else (
                                json.dumps(event.dict()) if hasattr(event, "dict") else json.dumps(event)
                            )
                            yield f"data: {json_str}\n\n"
                        else:
                            event_task.cancel()
                            try:
                                await event_task
                            except asyncio.CancelledError:
                                pass
                            # Send periodic keep-alive heartbeat comment
                            yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
                    else:
                        await asyncio.sleep(1.0)
                        yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"

                except (asyncio.CancelledError, GeneratorExit):
                    break
                except Exception as e:
                    logger.debug(f"SSE stream loop exception: {e}")
                    break

        finally:
            logger.debug("SSE client disconnected.")

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# 6. WebSocket Real-Time Hub
# ===========================================================================

@router.websocket("/ws")
@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Bidirectional WebSocket connection providing sub-second telemetry, live logs,
    and instantaneous client action execution with ping/pong keepalive.
    """
    await websocket.accept()
    engine = _get_engine(websocket)

    broadcaster = None
    if engine is not None:
        if hasattr(engine, "logger"):
            broadcaster = engine.logger
        elif hasattr(engine, "logger_hub"):
            broadcaster = engine.logger_hub

    if broadcaster is None:
        broadcaster = app_logger.broadcaster

    sub = None
    if hasattr(broadcaster, "subscribe"):
        sub = broadcaster.subscribe()
    elif hasattr(broadcaster, "subscribe_logs"):
        sub = broadcaster.subscribe_logs()

    # Send initial state snapshot upon connection
    try:
        if engine is not None and hasattr(engine, "get_state"):
            state = engine.get_state()
            state_dict = state.model_dump(mode="json") if hasattr(state, "model_dump") else (state.dict() if hasattr(state, "dict") else state)
            await websocket.send_text(json.dumps({"type": "status", "data": state_dict}))
    except Exception as e:
        logger.debug(f"Error sending initial WS state: {e}")

    async def client_listener() -> None:
        """Processes incoming commands from the connected client."""
        while True:
            try:
                raw_msg = await websocket.receive_text()
                if not raw_msg:
                    continue

                try:
                    payload = json.loads(raw_msg)
                except Exception:
                    payload = {"action": raw_msg.strip()}

                action = payload.get("action") or payload.get("type", "")

                if action == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }))

                elif action in ("get_status", "status"):
                    if engine is not None and hasattr(engine, "get_state"):
                        curr_state = engine.get_state()
                        s_data = curr_state.model_dump(mode="json") if hasattr(curr_state, "model_dump") else curr_state.dict()
                        await websocket.send_text(json.dumps({"type": "status", "data": s_data}))

                elif action in ("click_plus_one", "extend"):
                    if engine is not None and hasattr(engine, "trigger_plus_one"):
                        res = await _execute_engine_call(engine.trigger_plus_one)
                        success = res.success if isinstance(res, ActionResult) else bool(res)
                        await websocket.send_text(json.dumps({
                            "type": "action_result",
                            "action": "extend",
                            "success": success,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }))

                elif action == "toggle_keepalive":
                    if engine is not None and hasattr(engine, "toggle_keepalive"):
                        target_en = payload.get("enabled")
                        is_active = engine.toggle_keepalive(target_en)
                        await websocket.send_text(json.dumps({
                            "type": "action_result",
                            "action": "toggle_keepalive",
                            "is_keepalive_active": is_active,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }))

                elif action == "start":
                    if engine is not None and hasattr(engine, "start_server"):
                        res = await _execute_engine_call(engine.start_server)
                        success = res.success if isinstance(res, ActionResult) else bool(res)
                        await websocket.send_text(json.dumps({
                            "type": "action_result",
                            "action": "start",
                            "success": success,
                        }))

                elif action == "stop":
                    if engine is not None and hasattr(engine, "stop_server"):
                        res = await _execute_engine_call(engine.stop_server)
                        success = res.success if isinstance(res, ActionResult) else bool(res)
                        await websocket.send_text(json.dumps({
                            "type": "action_result",
                            "action": "stop",
                            "success": success,
                        }))

                elif action == "reload_session":
                    if engine is not None and hasattr(engine, "reload_session"):
                        res = await _execute_engine_call(engine.reload_session)
                        success = res.success if isinstance(res, ActionResult) else bool(res)
                        await websocket.send_text(json.dumps({
                            "type": "action_result",
                            "action": "reload_session",
                            "success": success,
                        }))

            except (WebSocketDisconnect, asyncio.CancelledError):
                break
            except Exception as e:
                logger.debug(f"WS client listener exception: {e}")
                break

    async def broadcast_forwarder() -> None:
        """Forwards real-time log broadcasts to the connected WebSocket."""
        if sub is None or not hasattr(sub, "__anext__"):
            return

        while True:
            try:
                event = await sub.__anext__()
                json_str = event.model_dump_json() if hasattr(event, "model_dump_json") else (
                    json.dumps(event.dict()) if hasattr(event, "dict") else json.dumps(event)
                )
                await websocket.send_text(json_str)
            except (WebSocketDisconnect, asyncio.CancelledError):
                break
            except Exception as e:
                logger.debug(f"WS forwarder exception: {e}")
                break

    # Run client listener and broadcast forwarder concurrently
    listener_task = asyncio.create_task(client_listener())
    forwarder_task = asyncio.create_task(broadcast_forwarder())

    try:
        done, pending = await asyncio.wait(
            [listener_task, forwarder_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        logger.debug("WebSocket client closed and cleaned up.")
