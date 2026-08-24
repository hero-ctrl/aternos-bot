"""
Application Entrypoint for Aternos 24/7 Keep-Alive Automation & Web Dashboard.
Bootstraps configuration, engine subsystem, FastAPI application, and ASGI server.
"""

import logging
import os
import sys
import uvicorn

from src.bot.engine import KeepAliveEngine
from src.core.config import Settings, get_settings
from src.core.logger import app_logger
from src.web.app import create_app

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aternos_bot.main")


def main() -> None:
    """
    Main runtime entrypoint.
    Initializes configuration, engine, and starts uvicorn ASGI server.
    """
    settings = get_settings()
    app_logger.info(
        f"Starting Aternos 24/7 Keep-Alive Bot on {settings.HOST}:{settings.PORT} (Mock mode: {settings.MOCK_MODE})",
        source="main"
    )

    # Initialize keep-alive engine
    engine = KeepAliveEngine(config=settings)

    # Create FastAPI web application
    app = create_app(engine=engine, settings=settings)

    # Run uvicorn server
    uvicorn_log_level = settings.LOG_LEVEL.lower()
    if uvicorn_log_level == "warn":
        uvicorn_log_level = "warning"

    try:
        uvicorn.run(
            app,
            host=settings.HOST,
            port=settings.PORT,
            log_level=uvicorn_log_level,
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Fatal error in server runner: {e}")
        sys.exit(1)


# Expose default ASGI application object for uvicorn CLI commands (e.g. uvicorn src.main:app)
settings = get_settings()
default_engine = KeepAliveEngine(config=settings)
app = create_app(engine=default_engine, settings=settings)


if __name__ == "__main__":
    main()
