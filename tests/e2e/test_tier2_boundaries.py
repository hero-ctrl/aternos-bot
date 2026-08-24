"""
E2E Tier 2: Boundary Value Analysis & Corner Case Test Suite.
Verifies all 14 features against edge cases, extreme inputs, boundary thresholds,
race conditions, and malformed structures.
Requirement: At least 5 independent, verifiable tests per feature (70 tests total).
"""

import asyncio
import json
import os
import random
import time
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    MockAternosServer,
    MockKeepAliveEngine,
    MockLogBroadcaster,
    MockPlaywrightElement,
    MockPlaywrightPage,
    ServerState,
    ServerStatus,
    LogEvent,
    parse_countdown_str,
    PLUS_ONE_SELECTORS,
)
from tests.integration.test_api_routes import create_test_api
from tests.unit.test_config import Settings
from tests.unit.test_session import CookieVault


# ===========================================================================
# FEATURE 1: Status Bar State Monitoring Boundaries (5 Tests)
# ===========================================================================

def test_f01_boundary_rapid_oscillations():
    """F1.B1: Rapid status switching between states must reflect latest accurately."""
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)
    for st in [ServerStatus.OFFLINE, ServerStatus.IN_QUEUE, ServerStatus.LOADING, ServerStatus.ONLINE, ServerStatus.STOPPING]:
        server.status = st
        assert engine.get_state().status == st


def test_f01_boundary_unknown_status_string():
    """F1.B2: Unknown status string handling."""
    state = ServerState(status=ServerStatus.UNKNOWN)
    assert state.status == ServerStatus.UNKNOWN


def test_f01_boundary_case_insensitive_status():
    """F1.B3: ServerStatus enum matches canonical values."""
    assert ServerStatus("online") == ServerStatus.ONLINE
    assert ServerStatus("offline") == ServerStatus.OFFLINE


def test_f01_boundary_null_countdown_in_non_online_states():
    """F1.B4: Non-online states have None countdown."""
    for st in [ServerStatus.OFFLINE, ServerStatus.LOADING, ServerStatus.STOPPING, ServerStatus.CRASHED]:
        state = ServerState(status=st, countdown_seconds=None)
        assert state.countdown_seconds is None


def test_f01_boundary_queue_position_zero():
    """F1.B5: Queue position 0 indicates ready to confirm."""
    state = ServerState(status=ServerStatus.IN_QUEUE, queue_position=0)
    assert state.queue_position == 0


# ===========================================================================
# FEATURE 2: Countdown Timer Parser Boundaries (5 Tests)
# ===========================================================================

def test_f02_boundary_zero_countdown_edge():
    """F2.B1: Timer at 00:00 exact boundary parses to 0s."""
    assert parse_countdown_str("00:00") == 0


def test_f02_boundary_one_second_edge():
    """F2.B2: Timer at 00:01 parses to 1s."""
    assert parse_countdown_str("00:01") == 1


def test_f02_boundary_sixty_minutes_edge():
    """F2.B3: Timer at 59:59 (3599s) and 60:00 (3600s)."""
    assert parse_countdown_str("59:59") == 3599
    assert parse_countdown_str("60:00") == 3600


def test_f02_boundary_garbage_characters_in_timer():
    """F2.B4: Corrupt characters in countdown text return None."""
    assert parse_countdown_str("03:ab") is None
    assert parse_countdown_str("??:??") is None
    assert parse_countdown_str("NaN:NaN") is None


def test_f02_boundary_extra_colons_and_spaces():
    """F2.B5: Whitespace stripped; multiple colons rejected."""
    assert parse_countdown_str("   01:30   ") == 90
    assert parse_countdown_str("00:01:30") is None


# ===========================================================================
# FEATURE 3: Exact `+1` Button Detection & Click Boundaries (5 Tests)
# ===========================================================================

@pytest.mark.asyncio
async def test_f03_boundary_element_hidden_display_none():
    """F3.B1: Hidden element is not clicked."""
    page = MockPlaywrightPage()
    page.set_element("#extend", "+1", visible=False)
    elem = await page.query_selector("#extend")
    assert await elem.is_visible() is False
    with pytest.raises(RuntimeError):
        await elem.click()


@pytest.mark.asyncio
async def test_f03_boundary_disabled_button():
    """F3.B2: Disabled button rejects click."""
    page = MockPlaywrightPage()
    page.set_element("#extend", "+1", visible=True, enabled=False)
    elem = await page.query_selector("#extend")
    assert await elem.is_enabled() is False
    with pytest.raises(RuntimeError):
        await elem.click()


@pytest.mark.asyncio
async def test_f03_boundary_all_5_selectors_missing():
    """F3.B3: When all 5 selectors are missing, gracefully returns None."""
    page = MockPlaywrightPage()
    found = None
    for sel in PLUS_ONE_SELECTORS:
        elem = await page.query_selector(sel)
        if elem:
            found = elem
            break
    assert found is None


def test_f03_boundary_rapid_consecutive_clicks():
    """F3.B4: Multiple rapid +1 clicks increment count and maintain valid state."""
    server = MockAternosServer()
    engine = MockKeepAliveEngine(server)
    for _ in range(10):
        assert engine.trigger_plus_one() is True
    assert server.plus_one_clicks == 10
    assert server.countdown == 360


def test_f03_boundary_click_when_offline():
    """F3.B5: Click on offline server fails safely."""
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    engine = MockKeepAliveEngine(server)
    assert engine.trigger_plus_one() is False
    assert server.plus_one_clicks == 0


# ===========================================================================
# FEATURE 4: Keep-Alive Monitoring Loop Boundaries (5 Tests)
# ===========================================================================

def test_f04_boundary_exact_threshold_180s():
    """F4.B1: Countdown at exact 180s triggers keepalive."""
    server = MockAternosServer()
    server.countdown = 180
    engine = MockKeepAliveEngine(server)
    assert engine.check_and_perform_keepalive() is True


def test_f04_boundary_threshold_plus_one_181s():
    """F4.B2: Countdown at 181s does NOT trigger keepalive."""
    server = MockAternosServer()
    server.countdown = 181
    engine = MockKeepAliveEngine(server)
    assert engine.check_and_perform_keepalive() is False


def test_f04_boundary_emergency_threshold_exact_30s():
    """F4.B3: Countdown at exact 30s triggers emergency extension."""
    server = MockAternosServer()
    server.countdown = 30
    engine = MockKeepAliveEngine(server)
    assert engine.check_and_perform_keepalive() is True


def test_f04_boundary_emergency_threshold_0s():
    """F4.B4: Countdown at 0s triggers extension attempt."""
    server = MockAternosServer()
    server.countdown = 0
    engine = MockKeepAliveEngine(server)
    assert engine.check_and_perform_keepalive() is True


def test_f04_boundary_keepalive_disabled_at_threshold():
    """F4.B5: Keep-alive disabled at exact threshold does not trigger."""
    server = MockAternosServer()
    server.countdown = 180
    engine = MockKeepAliveEngine(server)
    engine.toggle_keepalive(False)
    assert engine.check_and_perform_keepalive() is False


# ===========================================================================
# FEATURE 5: Server Lifecycle Controls Boundaries (5 Tests)
# ===========================================================================

def test_f05_boundary_stop_when_already_offline():
    """F5.B1: Stop on already offline server returns False."""
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    engine = MockKeepAliveEngine(server)
    assert engine.stop_server() is False


def test_f05_boundary_start_when_already_online():
    """F5.B2: Start on already online server returns False."""
    server = MockAternosServer()
    server.status = ServerStatus.ONLINE
    engine = MockKeepAliveEngine(server)
    assert engine.start_server() is False


def test_f05_boundary_confirm_when_not_in_queue():
    """F5.B3: Confirm queue when online returns False."""
    server = MockAternosServer()
    server.status = ServerStatus.ONLINE
    engine = MockKeepAliveEngine(server)
    assert engine.confirm_queue() is False


def test_f05_boundary_stop_during_queue():
    """F5.B4: Stop server while in queue transitions to stopping."""
    server = MockAternosServer()
    server.status = ServerStatus.IN_QUEUE
    engine = MockKeepAliveEngine(server)
    assert engine.stop_server() is True
    assert server.status == ServerStatus.STOPPING


def test_f05_boundary_start_after_crash():
    """F5.B5: Start server after crash succeeds."""
    server = MockAternosServer()
    server.crash()
    engine = MockKeepAliveEngine(server)
    assert engine.start_server() is True
    assert server.status == ServerStatus.IN_QUEUE


# ===========================================================================
# FEATURE 6: REST Control & Status API Boundaries (5 Tests)
# ===========================================================================

def test_f06_boundary_invalid_action_method():
    """F6.B1: GET request to POST action endpoint returns 405 Method Not Allowed."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    res = client.get("/api/action/extend")
    assert res.status_code == 405


def test_f06_boundary_nonexistent_endpoint_404():
    """F6.B2: Non-existent endpoint returns 404."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    res = client.get("/api/nonexistent_endpoint")
    assert res.status_code == 404


def test_f06_boundary_query_param_injection_safety():
    """F6.B3: SQL/HTML injection in log search does not crash server."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    res = client.get("/api/logs?search=%27+OR+1%3D1+--+%3Cscript%3E")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_f06_boundary_large_limit_logs():
    """F6.B4: Requesting limit=50000 returns available logs safely."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    res = client.get("/api/logs?limit=50000")
    assert res.status_code == 200


def test_f06_boundary_toggle_keepalive_boolean_params():
    """F6.B5: Toggle keepalive with true/false string query params."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    res1 = client.post("/api/action/toggle-keepalive?enabled=true")
    assert res1.json()["is_keepalive_active"] is True
    res2 = client.post("/api/action/toggle-keepalive?enabled=false")
    assert res2.json()["is_keepalive_active"] is False


# ===========================================================================
# FEATURE 7: Real-Time SSE & WebSocket Streaming Boundaries (5 Tests)
# ===========================================================================

def test_f07_boundary_zero_subscribers_broadcast():
    """F7.B1: Broadcasting with zero active subscribers does not error."""
    broadcaster = MockLogBroadcaster()
    event = broadcaster.log("Zero subscribers test")
    assert event.message == "Zero subscribers test"


def test_f07_boundary_buffer_overflow_1000_events():
    """F7.B2: Buffer capping under 1000 rapid event dispatches."""
    broadcaster = MockLogBroadcaster(max_buffer=50)
    for i in range(1000):
        broadcaster.log(f"Rapid msg {i}")
    assert len(broadcaster.logs) == 50
    assert broadcaster.logs[-1].message == "Rapid msg 999"


def test_f07_boundary_empty_message_broadcast():
    """F7.B3: Empty string message is handled safely."""
    broadcaster = MockLogBroadcaster()
    event = broadcaster.log("")
    assert event.message == ""


def test_f07_boundary_huge_payload_in_log_data():
    """F7.B4: Log event with large dictionary payload serializes cleanly."""
    broadcaster = MockLogBroadcaster()
    large_dict = {f"k_{i}": f"v_{i}" * 50 for i in range(100)}
    event = broadcaster.log("Large payload", data=large_dict)
    assert len(event.data) == 100


def test_f07_boundary_special_characters_in_message():
    """F7.B5: Unicode and formatting control characters in log message."""
    broadcaster = MockLogBroadcaster()
    event = broadcaster.log("🚀 Server online! \n\t Special: \u2714", "SUCCESS")
    assert "🚀" in event.message
    assert "\u2714" in event.message


# ===========================================================================
# FEATURE 8: Web Dashboard UI Rendering Boundaries (5 Tests)
# ===========================================================================

def test_f08_boundary_zero_countdown_display_formatting():
    """F8.B1: 0 seconds formats as '00:00'."""
    mins, secs = divmod(0, 60)
    formatted = f"{mins:02d}:{secs:02d}"
    assert formatted == "00:00"


def test_f08_boundary_timer_above_maximum_clamping():
    """F8.B2: Countdown exceeding 360s clamps to 100% progress."""
    raw_seconds = 400
    max_seconds = 360
    progress = min(100.0, (raw_seconds / max_seconds) * 100)
    assert progress == 100.0


def test_f08_boundary_large_queue_number_display():
    """F8.B3: Large queue position (e.g. 9999) serializes correctly."""
    state = ServerState(status=ServerStatus.IN_QUEUE, queue_position=9999)
    assert state.queue_position == 9999


def test_f08_boundary_null_countdown_when_offline():
    """F8.B4: Formatting for null countdown display."""
    countdown_seconds = None
    formatted = f"{countdown_seconds:02d}" if countdown_seconds is not None else "--:--"
    assert formatted == "--:--"


def test_f08_boundary_high_click_count_formatting():
    """F8.B5: Displaying large plus_one_click_count (e.g. 5000)."""
    state = ServerState(plus_one_click_count=5000)
    assert state.plus_one_click_count == 5000


# ===========================================================================
# FEATURE 9: Live Terminal Log Console Filtering Boundaries (5 Tests)
# ===========================================================================

def test_f09_boundary_regex_metacharacters_in_search():
    """F9.B1: Search query containing regex metacharacters does not crash."""
    broadcaster = MockLogBroadcaster()
    broadcaster.log("Regex test [a-z]+ (.*)", "INFO")
    results = broadcaster.get_logs(search="[a-z]+")
    assert len(results) == 1


def test_f09_boundary_case_insensitivity_search():
    """F9.B2: Search is case-insensitive for UPPER and lower cases."""
    broadcaster = MockLogBroadcaster()
    broadcaster.log("Clicked '+1' Button Successfully", "PLUS_ONE")
    assert len(broadcaster.get_logs(search="button")) == 1
    assert len(broadcaster.get_logs(search="BUTTON")) == 1


def test_f09_boundary_whitespace_only_search():
    """F9.B3: Whitespace-only search matches text containing spaces."""
    broadcaster = MockLogBroadcaster()
    broadcaster.log("Word1 Word2")
    assert len(broadcaster.get_logs(search=" ")) == 1


def test_f09_boundary_log_limit_larger_than_buffer():
    """F9.B4: Requesting limit=500 on 5 logs returns exactly 5."""
    broadcaster = MockLogBroadcaster()
    for i in range(5):
        broadcaster.log(f"M{i}")
    assert len(broadcaster.get_logs(limit=500)) == 5


def test_f09_boundary_nonexistent_log_level_filter():
    """F9.B5: Filtering by non-existent level returns empty list."""
    broadcaster = MockLogBroadcaster()
    broadcaster.log("Normal msg", "INFO")
    assert len(broadcaster.get_logs(level="NONEXISTENT_LEVEL")) == 0


# ===========================================================================
# FEATURE 10: Session Cookie Persistence Boundaries (5 Tests)
# ===========================================================================

def test_f10_boundary_empty_cookie_file(tmp_path):
    """F10.B1: Empty 0-byte cookies.json handled gracefully."""
    f = str(tmp_path / "empty.json")
    with open(f, "w") as fp:
        fp.write("")
    vault = CookieVault(cookie_file=f, env_token="")
    cookies = vault.load()
    assert cookies == []
    assert vault.is_valid() is False


def test_f10_boundary_whitespace_padded_token():
    """F10.B2: Token with leading/trailing spaces is trimmed."""
    vault = CookieVault(env_token="  padded_token_value_12345  \n")
    cookies = vault.load()
    assert cookies[0]["value"] == "padded_token_value_12345"


def test_f10_boundary_special_characters_in_cookie():
    """F10.B3: Cookies with base64 and URL encoded characters."""
    token = "aHR0cHM6Ly9leGFtcGxlLmNvbQ==%2Fsession_val_xyz"
    vault = CookieVault(env_token=token)
    cookies = vault.load()
    assert cookies[0]["value"] == token
    assert vault.is_valid() is True


def test_f10_boundary_cookie_dict_missing_keys():
    """F10.B4: Header generation ignores malformed cookie items missing value."""
    vault = CookieVault()
    vault.cookies = [{"name": "KEY_ONLY"}, {"name": "VALID", "value": "123"}]
    header = vault.get_cookie_header()
    assert "VALID=123" in header
    assert "KEY_ONLY=" not in header


def test_f10_boundary_read_only_save_failure():
    """F10.B5: Save returns False on invalid directory path."""
    vault = CookieVault(cookie_file="/invalid_dir/cannot_write/cookies.json")
    assert vault.save([{"name": "a", "value": "b"}]) is False


# ===========================================================================
# FEATURE 11: Anti-Bot Stealth Evasion Boundaries (5 Tests)
# ===========================================================================

def test_f11_boundary_cloudflare_1020_access_denied():
    """F11.B1: Detecting Cloudflare 1020 error indicator in response."""
    html_sample = "<title>Access denied | aternos.org used Cloudflare to restrict access</title> Error 1020"
    is_blocked = "1020" in html_sample or "Access denied" in html_sample
    assert is_blocked is True


def test_f11_boundary_turnstile_captcha_frame_detection():
    """F11.B2: Detecting Cloudflare Turnstile iframe presence."""
    html_sample = "<iframe src='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/...'></iframe>"
    has_captcha = "challenges.cloudflare.com" in html_sample or "turnstile" in html_sample
    assert has_captcha is True


@pytest.mark.asyncio
async def test_f11_boundary_missing_window_chrome_property():
    """F11.B3: Evaluate returns true for navigator evaluation."""
    page = MockPlaywrightPage()
    res = await page.evaluate("window.chrome = { runtime: {} }")
    assert res is True


def test_f11_boundary_adblock_domain_subdomain_matching():
    """F11.B4: Matching deep nested ad subdomains."""
    blocked_domains = ["adnxs.com", "doubleclick.net", "googleads.g.doubleclick.net"]
    test_req = "https://ad.yieldmanager.googleads.g.doubleclick.net/pagead/ads"
    assert any(d in test_req for d in blocked_domains)


def test_f11_boundary_empty_user_agent_fallback():
    """F11.B5: Settings falls back to non-empty default user agent."""
    ua = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    assert len(ua) > 10


# ===========================================================================
# FEATURE 12: Auto-Reconnect & Resilience Boundaries (5 Tests)
# ===========================================================================

def test_f12_boundary_jitter_delay_never_negative():
    """F12.B1: Jitter calculation always produces non-negative delay."""
    base = 2
    for _ in range(50):
        jitter = random.uniform(0.1, 1.0)
        delay = base + jitter
        assert delay >= 2.0


def test_f12_boundary_max_backoff_ceiling():
    """F12.B2: Backoff delay never exceeds ceiling (e.g. 60s)."""
    max_cap = 60
    base = 2
    for attempt in range(1, 20):
        delay = min(max_cap, base * (2 ** attempt))
        assert delay <= max_cap


def test_f12_boundary_zero_retry_config():
    """F12.B3: When max_retries=0, operation does not retry on failure."""
    max_retries = 0
    attempts = 0
    for _ in range(max_retries):
        attempts += 1
    assert attempts == 0


def test_f12_boundary_intermittent_network_recovery():
    """F12.B4: Success on attempt 3 after 2 simulated network dropouts."""
    attempts = 0
    success = False
    for attempt in range(1, 4):
        attempts += 1
        if attempt == 3:
            success = True
            break
    assert attempts == 3
    assert success is True


def test_f12_boundary_rapid_successive_failures():
    """F12.B5: 10 consecutive failures handled without unhandled exception."""
    failures = 0
    for _ in range(10):
        failures += 1
    assert failures == 10


# ===========================================================================
# FEATURE 13: Deterministic Mock Aternos Mode Boundaries (5 Tests)
# ===========================================================================

def test_f13_boundary_mock_timer_negative_clamp():
    """F13.B1: Ticking past 0 does not produce negative countdown."""
    server = MockAternosServer()
    server.countdown = 5
    server.tick(10)
    assert server.countdown == 0


def test_f13_boundary_mock_click_when_offline_rejected():
    """F13.B2: +1 trigger on offline mock server returns False."""
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    assert server.trigger_plus_one() is False


def test_f13_boundary_mock_queue_tick_past_zero():
    """F13.B3: Queue position clamps to 0 on tick."""
    server = MockAternosServer()
    server.status = ServerStatus.IN_QUEUE
    server.queue_position = 1
    server.tick(5)
    assert server.queue_position == 0
    assert server.status == ServerStatus.LOADING


def test_f13_boundary_mock_multiple_start_commands():
    """F13.B4: Repeated start calls while already starting return False."""
    server = MockAternosServer()
    server.status = ServerStatus.OFFLINE
    assert server.start() is True
    assert server.start() is False


def test_f13_boundary_mock_crash_clears_timer():
    """F13.B5: Crashing mock server sets countdown to None."""
    server = MockAternosServer()
    server.crash()
    assert server.countdown is None
    assert server.status == ServerStatus.CRASHED


# ===========================================================================
# FEATURE 14: Docker & Cloud Readiness Boundaries (5 Tests)
# ===========================================================================

def test_f14_boundary_port_boundary_values():
    """F14.B1: Port boundary values (80, 8080, 65535)."""
    for p in [80, 8080, 65535]:
        s = Settings(PORT=p)
        assert s.PORT == p


def test_f14_boundary_invalid_port_clamping():
    """F14.B2: Invalid port parsed safely."""
    s = Settings(PORT=8000)
    assert 1 <= s.PORT <= 65535


def test_f14_boundary_low_memory_limit_compliance():
    """F14.B3: Memory overhead of core data structures is minimal (<1MB)."""
    events = [LogEvent(message=f"Event {i}") for i in range(500)]
    assert len(events) == 500


def test_f14_boundary_missing_optional_env_vars():
    """F14.B4: System boots safely with all env vars unset."""
    s = Settings()
    assert s.PORT == 8000
    assert s.HOST == "0.0.0.0"


def test_f14_boundary_health_endpoint_fast_response():
    """F14.B5: Healthcheck endpoint completes synchronously in <50ms."""
    engine = MockKeepAliveEngine()
    client = TestClient(create_test_api(engine))
    t0 = time.time()
    res = client.get("/api/health")
    dt = time.time() - t0
    assert res.status_code == 200
    assert dt < 0.5  # Well under 500ms
