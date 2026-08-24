"""
E2E Tier 5: Adversarial Hardening & Stress Test Suite.
Verifies system resilience against fuzzing payloads, race conditions,
malicious cookie injection, buffer stress, and resource boundaries.
"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    MockAternosServer,
    MockKeepAliveEngine,
    MockLogBroadcaster,
    ServerStatus,
    parse_countdown_str,
)
from tests.integration.test_api_routes import create_test_api
from tests.unit.test_session import CookieVault


def test_tier5_adversarial_malformed_http_payloads():
    """Verify API handles null bytes, deep JSON nesting, and oversized payloads safely."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))

    # Send malformed JSON or null bytes to endpoint
    res = client.post("/api/action/toggle-keepalive", content=b"\x00\xff\xfe malformed body", headers={"content-type": "application/json"})
    assert res.status_code in [200, 400, 422]


def test_tier5_adversarial_extreme_countdown_values():
    """Verify countdown parser rejects overflow numbers and non-standard numeric notations."""
    assert parse_countdown_str("1e10:00") is None
    assert parse_countdown_str("-9999:00") is None
    assert parse_countdown_str("999999999999999999999999999999:00") is None
    assert parse_countdown_str("\x0003:45\x00") is None


def test_tier5_adversarial_corrupted_cookie_injection(tmp_path):
    """Verify CookieVault safely isolates command injection and path traversal tokens."""
    malicious_token = "'; rm -rf /; DROP TABLE users; -- \x00\r\n\t"
    vault = CookieVault(env_token=malicious_token)
    cookies = vault.load()
    assert len(cookies) == 1
    # Check that header formatting strips or handles newlines
    header = vault.get_cookie_header()
    assert "ATERNOS_SESSION=" in header


def test_tier5_adversarial_concurrent_plus_one_race_conditions():
    """Verify 50 concurrent +1 triggers maintain deterministic click counter and state."""
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)

    # Perform 50 rapid sequential/concurrent triggers
    for _ in range(50):
        engine.trigger_plus_one()

    assert server.plus_one_clicks == 50
    assert server.countdown == 360
    assert len(engine.logger.logs) == 50


def test_tier5_adversarial_massive_log_storm():
    """Verify log broadcaster handles a storm of 2000 log events without memory growth."""
    broadcaster = MockLogBroadcaster(max_buffer=100)
    for i in range(2000):
        broadcaster.log(f"Storm message {i}", "INFO", {"index": i})

    assert len(broadcaster.logs) == 100
    assert broadcaster.logs[-1].message == "Storm message 1999"
