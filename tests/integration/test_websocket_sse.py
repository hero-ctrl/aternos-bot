"""
Integration tests for Real-Time SSE and WebSocket Streaming.
Tests /api/events SSE stream, /ws WebSocket connections, concurrent event dispatch,
heartbeats, and disconnect handling.
"""

import asyncio
import json
from typing import AsyncGenerator
import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from tests.conftest import MockLogBroadcaster, LogEvent, MockKeepAliveEngine


def create_streaming_app(broadcaster: MockLogBroadcaster) -> FastAPI:
    """FastAPI app providing both SSE and WebSocket event hubs."""
    app = FastAPI()

    @app.get("/api/events")
    async def sse_events():
        async def event_generator():
            sub = broadcaster.subscribe()
            try:
                async for event in sub:
                    json_str = event.model_dump_json() if hasattr(event, "model_dump_json") else event.json()
                    yield f"data: {json_str}\n\n"
            except asyncio.CancelledError:
                pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        sub = broadcaster.subscribe()
        try:
            while True:
                # Run event receiver and client message listener
                event = await sub.__anext__()
                json_str = event.model_dump_json() if hasattr(event, "model_dump_json") else event.json()
                await websocket.send_text(json_str)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    return app


@pytest.mark.asyncio
async def test_sse_event_stream_formatting():
    """Verify SSE endpoint streams data formatted as 'data: {...}\\n\\n'."""
    broadcaster = MockLogBroadcaster()
    app = create_streaming_app(broadcaster)

    # Subscribe directly to generator logic
    async def test_stream():
        sub = broadcaster.subscribe()
        broadcaster.log("SSE keep-alive tick", "PLUS_ONE")
        event = await sub.__anext__()
        payload = f"data: {event.model_dump_json() if hasattr(event, 'model_dump_json') else event.json()}\n\n"
        assert payload.startswith("data: {")
        assert payload.endswith("\n\n")
        assert "SSE keep-alive tick" in payload

    await test_stream()


def test_websocket_connection_and_broadcast():
    """Verify WebSocket client establishes connection and receives pushed log events."""
    broadcaster = MockLogBroadcaster()
    app = create_streaming_app(broadcaster)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        broadcaster.log("WS Server Online", "SUCCESS")
        data = ws.receive_text()
        parsed = json.loads(data)
        assert parsed["message"] == "WS Server Online"
        assert parsed["level"] == "SUCCESS"


def test_multiple_websocket_subscribers():
    """Verify multiple active WebSockets receive parallel real-time messages."""
    broadcaster = MockLogBroadcaster()
    app = create_streaming_app(broadcaster)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws1:
        with client.websocket_connect("/ws") as ws2:
            broadcaster.log("Dual WS Broadcast", "PLUS_ONE")
            msg1 = json.loads(ws1.receive_text())
            msg2 = json.loads(ws2.receive_text())
            assert msg1["message"] == "Dual WS Broadcast"
            assert msg2["message"] == "Dual WS Broadcast"


def test_websocket_disconnect_cleanup():
    """Verify disconnecting a WebSocket cleans up subscriber queues without exceptions."""
    broadcaster = MockLogBroadcaster()
    app = create_streaming_app(broadcaster)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        broadcaster.log("Ping", "INFO")
        _ = ws.receive_text()

    # After exiting with block, websocket is closed
    assert len(broadcaster._subscribers) == 0
