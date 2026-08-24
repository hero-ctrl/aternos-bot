"""
Adversarial Empirical Stress Tests for Milestone 1 (M1: Automation & Exact "+1" Button Engine).
Tests:
1. Countdown timer parsing fuzzing (irregular formats, malformed strings, whitespace, large numbers, Unicode, null bytes).
2. 5-tier fallback selector resilience and DOM mutation simulation.
3. Emergency countdown thresholds (rapid drops, instant 0:05 trigger, disabled keepalive, concurrency).
"""

import asyncio
from datetime import datetime, timezone
import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from src.core.config import Settings
from src.core.schemas import ActionResult, LogLevel, ServerState, ServerStatus, ServerStatusSnapshot
from src.bot.selectors import (
    TIER1_SELECTORS,
    TIER2_SELECTORS,
    TIER3_SELECTORS,
    TIER4_SELECTORS,
    TIER5_JS_EVALUATE,
    PLUS_ONE_SELECTORS,
    parse_countdown_str,
    classify_status_text,
)
from src.bot.driver import AternosDriver, MockDriver
from src.bot.engine import KeepAliveEngine
from src.core.logger import AppLogger, LogBroadcaster


# ===========================================================================
# 1. COUNTDOWN TIMER PARSER FUZZING & STRESS TESTS
# ===========================================================================

class TestCountdownParserFuzzing:
    """Fuzz and stress test parse_countdown_str with boundary, irregular, and adversarial inputs."""

    @pytest.mark.parametrize("input_str,expected", [
        ("00:00", 0),
        ("00:01", 1),
        ("0:05", 5),
        ("0:37", 37),
        ("01:00", 60),
        ("03:45", 225),
        ("05:00", 300),
        ("10:00", 600),
        ("59:59", 3599),
        ("60:00", 3600),
        ("120:00", 7200),
        ("999:59", 59999),
    ])
    def test_valid_mm_ss_and_m_ss_formats(self, input_str: str, expected: int):
        """Standard and single-digit minute formats parse to exact integer seconds."""
        assert parse_countdown_str(input_str) == expected

    @pytest.mark.parametrize("input_str,expected", [
        ("0", 0),
        ("5", 5),
        ("37", 37),
        ("45", 45),
        ("180", 180),
        ("360", 360),
        ("3600", 3600),
        ("45s", 45),
        ("45 s", 45),
        ("45sec", 45),
        ("45 sec", 45),
        ("45 SEC", 45),
        ("45seconds", 45),
        ("45 SECONDS", 45),
        ("180 seconds", 180),
    ])
    def test_raw_seconds_variations(self, input_str: str, expected: int):
        """Raw seconds with optional unit suffixes parse correctly."""
        assert parse_countdown_str(input_str) == expected

    @pytest.mark.parametrize("input_str,expected", [
        ("  03:45  ", 225),
        ("\t00:05\t", 5),
        ("\n0:37\n", 37),
        ("\r\n  05:00  \r\n", 300),
        (" 45 s ", 45),
        ("  01 : 30  ", 90),  # spaces around colon inside split
    ])
    def test_whitespace_and_newline_tolerance(self, input_str: str, expected: int):
        """Leading, trailing, and newline whitespace is gracefully stripped."""
        assert parse_countdown_str(input_str) == expected

    @pytest.mark.parametrize("malformed_input", [
        None,
        "",
        "   ",
        "\t\n\r",
        "invalid",
        "abc:def",
        "03:xx",
        "xx:45",
        "NaN:NaN",
        "Infinity",
        "-01:30",       # Negative minutes
        "01:-30",       # Negative seconds
        "-5",           # Negative raw seconds
        "-45s",         # Negative raw seconds with suffix
        "02:60",        # Seconds == 60 (invalid mm:ss)
        "02:65",        # Seconds > 60
        "00:99",        # Out of bounds seconds
        "01:02:03",     # Triple colons
        "::",           # Colons only
        ":",            # Single colon only
        ":30",          # Missing minute (parts[0] empty)
        "05:",          # Missing second (parts[1] empty)
        "1e5:00",       # Scientific notation
        "0x10:00",      # Hexadecimal string
        "3.5:20",       # Float minutes
        "03:45.5",      # Float seconds
        "\x0003:45",    # Leading null byte
        "03:45\x00",    # Trailing null byte
        "<script>alert(1)</script>", # XSS payload
        "'; DROP TABLE; --",         # SQL injection string
        "${{7*7}}",                  # Template injection
        "45ssss",                    # Invalid suffix
        "s45",                       # Prefix instead of suffix
        "sec 45",                    # Prefix unit
    ])
    def test_malformed_and_adversarial_inputs_return_none(self, malformed_input: Optional[str]):
        """Malformed, negative, out-of-bounds, injection, or irregular strings return None safely."""
        assert parse_countdown_str(malformed_input) is None

    def test_extremely_large_numbers(self):
        """Very large minute values parse or return None without throwing unhandled exceptions."""
        res = parse_countdown_str("999999:59")
        assert res == (999999 * 60) + 59

        # Immense integer string
        huge_str = "9" * 100 + ":00"
        res_huge = parse_countdown_str(huge_str)
        assert res_huge is not None and res_huge > 0


# ===========================================================================
# 2. 5-TIER FALLBACK SELECTOR RESILIENCE & DOM MUTATION SIMULATION
# ===========================================================================

class MockElement:
    """Configurable DOM Element for selector fallback tests."""
    def __init__(self, selector: str, text: str = "+1", visible: bool = True, enabled: bool = True):
        self.selector = selector
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.clicked = False
        self.click_count = 0

    async def is_visible(self) -> bool:
        return self.visible

    async def is_enabled(self) -> bool:
        return self.enabled

    async def inner_text(self) -> str:
        return self.text

    async def click(self, timeout: int = 2000):
        if not self.visible or not self.enabled:
            raise RuntimeError(f"Element {self.selector} is not clickable")
        self.clicked = True
        self.click_count += 1
        return True


class SimulatedPlaywrightPage:
    """Mock Playwright Page with configurable DOM presence across tiers."""
    def __init__(self):
        self.elements: Dict[str, MockElement] = {}
        self.url = "https://aternos.org/server/"
        self.closed = False
        self.js_eval_result = {"success": True, "tier": "Tier 5 (JS Evaluation)"}
        self.countdown_val: Optional[str] = "02:30"

    def set_element(self, selector: str, text: str = "+1", visible: bool = True, enabled: bool = True) -> MockElement:
        elem = MockElement(selector, text, visible, enabled)
        self.elements[selector] = elem
        return elem

    def remove_element(self, selector: str):
        self.elements.pop(selector, None)

    async def query_selector(self, selector: str) -> Optional[MockElement]:
        if self.closed:
            raise RuntimeError("Page is closed")
        elem = self.elements.get(selector)
        return elem

    async def evaluate(self, script: str) -> Any:
        return self.js_eval_result

    def is_closed(self) -> bool:
        return self.closed


class TestFiveTierSelectorResilience:
    """Empirical resilience tests verifying fallback progression across all 5 tiers."""

    @pytest.mark.asyncio
    async def test_tier1_primary_selector_resolution(self):
        """Tier 1 selector (#extend) is used when present."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        tier1_elem = driver._page.set_element("#extend", "+1", visible=True)

        res = await driver.click_plus_one()
        assert res.success is True
        assert tier1_elem.clicked is True
        assert "Tier 1 (#extend)" in res.message

    @pytest.mark.asyncio
    async def test_tier2_fallback_when_tier1_absent(self):
        """When all Tier 1 selectors are absent, falls back to Tier 2 (e.g., button[data-action='extend'])."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        # No Tier 1 selectors present
        tier2_elem = driver._page.set_element('button[data-action="extend"]', "+1", visible=True)

        res = await driver.click_plus_one()
        assert res.success is True
        assert tier2_elem.clicked is True
        assert "Tier 2" in res.message

    @pytest.mark.asyncio
    async def test_tier3_fallback_when_tiers_1_and_2_absent(self):
        """When Tiers 1 and 2 are absent, falls back to Tier 3 (e.g., .statuslabel-countdown button)."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        # No Tier 1 or 2 selectors present
        tier3_elem = driver._page.set_element(".statuslabel-countdown button", "+1", visible=True)

        res = await driver.click_plus_one()
        assert res.success is True
        assert tier3_elem.clicked is True
        assert "Tier 3" in res.message

    @pytest.mark.asyncio
    async def test_tier4_fallback_when_tiers_1_2_3_absent(self):
        """When Tiers 1, 2, and 3 are absent, falls back to Tier 4 (e.g., button:has-text('+1'))."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        # No Tier 1, 2, or 3 selectors present
        tier4_elem = driver._page.set_element('button:has-text("+1")', "+1", visible=True)

        res = await driver.click_plus_one()
        assert res.success is True
        assert tier4_elem.clicked is True
        assert "Tier 4" in res.message

    @pytest.mark.asyncio
    async def test_tier5_js_evaluation_fallback_when_all_css_selectors_absent(self):
        """When Tiers 1-4 are all mutated or absent, falls back to Tier 5 JS evaluate."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        driver._page.js_eval_result = {"success": True, "tier": "Tier 5 (JS text scan)"}

        res = await driver.click_plus_one()
        assert res.success is True
        assert "Tier 5" in res.message

    @pytest.mark.asyncio
    async def test_hidden_or_disabled_elements_fall_through_to_next_tier(self):
        """Hidden (visible=False) elements are skipped and execution falls through to next active tier."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.set_element(".countdown", "02:30", visible=True)

        # Tier 1 exists but is HIDDEN
        driver._page.set_element("#extend", "+1", visible=False)
        # Tier 2 exists but is HIDDEN
        driver._page.set_element('button[data-action="extend"]', "+1", visible=False)
        # Tier 3 exists and is VISIBLE
        tier3_elem = driver._page.set_element(".statuslabel-countdown button", "+1", visible=True)

        res = await driver.click_plus_one()
        assert res.success is True
        assert tier3_elem.clicked is True
        assert "Tier 3" in res.message

    @pytest.mark.asyncio
    async def test_complete_selector_failure_returns_graceful_result(self):
        """If all 5 tiers fail, returns ActionResult(success=False) without uncaught exception."""
        driver = AternosDriver()
        driver._page = SimulatedPlaywrightPage()
        driver._page.js_eval_result = {"success": False, "error": "Button not found in DOM"}

        res = await driver.click_plus_one()
        assert res.success is False
        assert "failed to locate" in res.message.lower()


# ===========================================================================
# 3. EMERGENCY COUNTDOWN THRESHOLDS & RAPID DROP SIMULATION
# ===========================================================================

class TestEmergencyCountdownThresholds:
    """Stress tests on emergency countdown drops, instant 0:05 triggers, and threshold boundaries."""

    def test_threshold_validation_ordering(self):
        """Settings enforces EMERGENCY_THRESHOLD < COUNTDOWN_THRESHOLD."""
        # Valid settings
        s = Settings(COUNTDOWN_THRESHOLD=180, EMERGENCY_THRESHOLD=30)
        assert s.COUNTDOWN_THRESHOLD == 180
        assert s.EMERGENCY_THRESHOLD == 30

        # Invalid: Emergency >= Countdown threshold raises ValueError
        with pytest.raises(ValueError, match="EMERGENCY_THRESHOLD.*must be strictly less than"):
            Settings(COUNTDOWN_THRESHOLD=30, EMERGENCY_THRESHOLD=30)

        with pytest.raises(ValueError, match="EMERGENCY_THRESHOLD.*must be strictly less than"):
            Settings(COUNTDOWN_THRESHOLD=20, EMERGENCY_THRESHOLD=50)

    @pytest.mark.asyncio
    async def test_instant_emergency_trigger_at_5_seconds(self):
        """When countdown instantly drops to 0:05 (<= EMERGENCY_THRESHOLD), triggers immediate emergency +1 click."""
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=5)
        logger_hub = AppLogger()
        engine = KeepAliveEngine(driver=driver, logger_hub=logger_hub)
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        # Update state directly as snapshot would
        snapshot = await driver.get_server_status()
        await engine._update_state_from_snapshot(snapshot)

        assert engine.state.countdown_seconds == 5
        assert engine.state.is_countdown_critical is True

        # Run online keepalive evaluation
        await engine._handle_online_keepalive()

        assert driver.plus_one_clicks == 1
        assert driver.countdown == 360
        assert engine.state.plus_one_click_count == 1
        assert engine.state.last_plus_one_click is not None

    @pytest.mark.asyncio
    async def test_rapid_countdown_drop_simulation(self):
        """Simulates rapid countdown drops (300s -> 180s -> 20s) and verifies responsive triggers."""
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=300)
        engine = KeepAliveEngine(driver=driver)
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        # Step 1: At 300s (> 180s), no click should occur
        snapshot = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=300, countdown_text="05:00")
        await engine._update_state_from_snapshot(snapshot)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 0

        # Step 2: Drop to 180s (Standard threshold hit), click should trigger
        snapshot = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=180, countdown_text="03:00")
        await engine._update_state_from_snapshot(snapshot)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 1

        # Step 3: Rapid drop to 20s (Emergency threshold hit), immediate emergency click triggers
        snapshot = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=20, countdown_text="00:20")
        await engine._update_state_from_snapshot(snapshot)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 2

    @pytest.mark.asyncio
    async def test_disabled_keepalive_suppresses_emergency_trigger(self):
        """When is_keepalive_active is False, even critical countdowns (0:05) do NOT trigger +1 click."""
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=5)
        engine = KeepAliveEngine(driver=driver)
        engine.toggle_keepalive(enabled=False)
        assert engine.is_keepalive_active is False

        snapshot = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=5, countdown_text="00:05")
        await engine._update_state_from_snapshot(snapshot)
        await engine._handle_online_keepalive()

        # No click should have occurred
        assert driver.plus_one_clicks == 0
        assert engine.state.plus_one_click_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_plus_one_triggers_thread_safety(self):
        """Verify 50 concurrent +1 triggers are synchronized via asyncio.Lock without race conditions."""
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=50)
        engine = KeepAliveEngine(driver=driver)

        # Launch 50 concurrent trigger tasks
        tasks = [asyncio.create_task(engine._perform_plus_one_click()) for _ in range(50)]
        results = await asyncio.gather(*tasks)

        assert all(r.success for r in results)
        assert driver.plus_one_clicks == 50
        assert engine.state.plus_one_click_count == 50

    def test_dynamic_sleep_interval_tuning(self):
        """Verify _calculate_next_sleep_interval tunes poll frequency based on urgency."""
        engine = KeepAliveEngine()
        engine.config.CHECK_INTERVAL = 5.0
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        # Case 1: Emergency countdown (<= 30s) -> 1.0s fast poll
        engine.state.status = ServerStatus.ONLINE
        engine.state.countdown_seconds = 15
        assert engine._calculate_next_sleep_interval() == 1.0

        # Case 2: Near threshold (<= 180s) -> 2.0s poll
        engine.state.countdown_seconds = 120
        assert engine._calculate_next_sleep_interval() == 2.0

        # Case 3: Safe countdown (300s) -> lead time clamped to CHECK_INTERVAL (5.0s)
        engine.state.countdown_seconds = 300
        assert engine._calculate_next_sleep_interval() == 5.0

        # Case 4: In Queue -> 2.0s
        engine.state.status = ServerStatus.IN_QUEUE
        engine.state.countdown_seconds = None
        assert engine._calculate_next_sleep_interval() == 2.0

        # Case 5: Offline -> default CHECK_INTERVAL (5.0s)
        engine.state.status = ServerStatus.OFFLINE
        assert engine._calculate_next_sleep_interval() == 5.0
