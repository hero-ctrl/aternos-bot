"""
Web Application Subsystem for Aternos 24/7 Keep-Alive Automation.
Provides FastAPI application factory, REST endpoints, SSE, and WebSocket streams.
"""

from src.web.app import create_app
from src.web.routes import router

__all__ = ["create_app", "router"]
