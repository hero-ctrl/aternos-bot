"""
FastAPI Web Application Factory for Aternos 24/7 Keep-Alive Automation & Web Dashboard.
Configures CORS, static asset mounting, routing, lifespan lifecycle management, and error handling.
"""

from contextlib import asynccontextmanager
import inspect
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import Settings, get_settings
from src.web.routes import router

logger = logging.getLogger("aternos_bot.web.app")


def create_app(
    engine: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.

    Args:
        engine: Optional KeepAliveEngine instance to attach to app.state.engine.
        settings: Optional application Settings.

    Returns:
        Configured FastAPI application ready for ASGI servers (uvicorn).
    """
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI lifespan context manager handling graceful startup and shutdown.
        """
        active_engine = getattr(app.state, "engine", None)
        if active_engine is not None and hasattr(active_engine, "start"):
            if not getattr(active_engine, "_running", False):
                try:
                    logger.info("Lifespan: Starting Keep-Alive Engine background task...")
                    import asyncio
                    if inspect.iscoroutinefunction(active_engine.start):
                        asyncio.create_task(active_engine.start())
                    else:
                        active_engine.start()
                except Exception as e:
                    logger.warning(f"Lifespan startup error: {e}")

        yield

        # Shutdown phase
        if active_engine is not None and hasattr(active_engine, "stop"):
            try:
                logger.info("Lifespan: Shutting down Keep-Alive Engine...")
                if inspect.iscoroutinefunction(active_engine.stop):
                    await active_engine.stop()
                else:
                    active_engine.stop()
            except Exception as e:
                logger.warning(f"Lifespan shutdown error: {e}")

    app = FastAPI(
        title="Aternos 24/7 Keep-Alive Automation",
        description="Real-time monitoring, exact +1 countdown extension, and automated keep-alive for Aternos Minecraft servers.",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Attach engine and configuration to app state
    app.state.engine = engine
    app.state.settings = cfg

    # Configure CORS for cross-origin management / mobile access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static assets directory
    static_dir = Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Include REST, SSE, and WebSocket routes
    app.include_router(router)

    # Root route serves index.html
    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(
                str(index_file),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return JSONResponse(
            status_code=200,
            content={"message": "Aternos 24/7 Keep-Alive API is running. Static dashboard building in progress."},
        )

    return app
