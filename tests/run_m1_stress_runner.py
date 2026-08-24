"""
Direct empirical test execution script for Milestone 1 Challenger.
Runs all fuzzing, selector resilience, and emergency threshold stress tests directly.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in [PROJECT_ROOT, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.core.config import Settings
from src.core.schemas import ServerStatus, ServerStatusSnapshot, ActionResult
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
from src.core.logger import AppLogger


passed = 0
failed = 0
results = []

def record_pass(test_name: str):
    global passed
    passed += 1
    results.append(f"[PASS] {test_name}")
    print(f"[PASS] {test_name}")

def record_fail(test_name: str, err: Exception):
    global failed
    failed += 1
    results.append(f"[FAIL] {test_name}: {err}")
    print(f"[FAIL] {test_name}: {err}")


# ===========================================================================
# 1. COUNTDOWN PARSER FUZZING
# ===========================================================================

def run_countdown_fuzzing():
    print("\n--- Running Suite 1: Countdown Parser Fuzzing ---")
    
    # 1.1 Valid mm:ss and m:ss
    valid_cases = {
        "00:00": 0, "00:01": 1, "0:05": 5, "0:37": 37, "01:00": 60,
        "03:45": 225, "05:00": 300, "10:00": 600, "59:59": 3599,
        "60:00": 3600, "120:00": 7200, "999:59": 59999
    }
    for inp, expected in valid_cases.items():
        try:
            actual = parse_countdown_str(inp)
            assert actual == expected, f"Expected {expected}, got {actual}"
            record_pass(f"Parser valid format: '{inp}' -> {expected}s")
        except Exception as e:
            record_fail(f"Parser valid format: '{inp}'", e)

    # 1.2 Raw seconds and suffix variations
    raw_cases = {
        "0": 0, "5": 5, "37": 37, "45": 45, "180": 180, "360": 360, "3600": 3600,
        "45s": 45, "45 s": 45, "45sec": 45, "45 sec": 45, "45 SEC": 45,
        "45seconds": 45, "45 SECONDS": 45, "180 seconds": 180
    }
    for inp, expected in raw_cases.items():
        try:
            actual = parse_countdown_str(inp)
            assert actual == expected, f"Expected {expected}, got {actual}"
            record_pass(f"Parser raw seconds: '{inp}' -> {expected}s")
        except Exception as e:
            record_fail(f"Parser raw seconds: '{inp}'", e)

    # 1.3 Whitespace & newlines
    ws_cases = {
        "  03:45  ": 225,
        "\t00:05\t": 5,
        "\n0:37\n": 37,
        "\r\n  05:00  \r\n": 300,
        " 45 s ": 45,
        "  01 : 30  ": 90,
    }
    for inp, expected in ws_cases.items():
        try:
            actual = parse_countdown_str(inp)
            assert actual == expected, f"Expected {expected}, got {actual}"
            record_pass(f"Parser whitespace tolerance: '{repr(inp)}' -> {expected}s")
        except Exception as e:
            record_fail(f"Parser whitespace tolerance: '{repr(inp)}'", e)

    # 1.4 Adversarial & Malformed Fuzzing
    malformed_cases = [
        None, "", "   ", "\t\n\r", "invalid", "abc:def", "03:xx", "xx:45",
        "NaN:NaN", "Infinity", "-01:30", "01:-30", "-5", "-45s",
        "02:60", "02:65", "00:99", "01:02:03", "::", ":", ":30", "05:",
        "1e5:00", "0x10:00", "3.5:20", "03:45.5", "\x0003:45", "03:45\x00",
        "<script>alert(1)</script>", "'; DROP TABLE; --", "${{7*7}}",
        "45ssss", "s45", "sec 45"
    ]
    for inp in malformed_cases:
        try:
            actual = parse_countdown_str(inp)
            assert actual is None, f"Expected None for malformed '{repr(inp)}', got {actual}"
            record_pass(f"Parser malformed rejection: '{repr(inp)}' -> None")
        except Exception as e:
            record_fail(f"Parser malformed rejection: '{repr(inp)}'", e)

    # 1.5 Extreme numbers
    try:
        assert parse_countdown_str("999999:59") == (999999 * 60) + 59
        huge = parse_countdown_str("9" * 50 + ":00")
        assert huge is not None and huge > 0
        record_pass("Parser extreme large number fuzzing")
    except Exception as e:
        record_fail("Parser extreme large number fuzzing", e)


# ===========================================================================
# 2. 5-TIER FALLBACK SELECTOR RESILIENCE
# ===========================================================================

class MockElem:
    def __init__(self, selector: str, text: str = "+1", visible: bool = True, enabled: bool = True):
        self.selector = selector
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.clicked = False

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def inner_text(self):
        return self.text

    async def click(self, timeout=2000):
        if not self.visible or not self.enabled:
            raise RuntimeError(f"Element {self.selector} is not clickable")
        self.clicked = True
        return True


class MockPage:
    def __init__(self):
        self.elements = {}
        self.url = "https://aternos.org/server/"
        self.js_eval_result = {"success": True, "tier": "Tier 5 (JS Evaluation)"}

    def set_element(self, selector: str, text: str = "+1", visible: bool = True, enabled: bool = True):
        elem = MockElem(selector, text, visible, enabled)
        self.elements[selector] = elem
        return elem

    async def query_selector(self, selector: str):
        return self.elements.get(selector)

    async def evaluate(self, script: str):
        return self.js_eval_result

    def is_closed(self):
        return False


async def run_selector_resilience():
    print("\n--- Running Suite 2: 5-Tier Fallback Selector Resilience ---")

    # 2.1 Tier 1 Resolution
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        tier1 = driver._page.set_element("#extend", "+1", visible=True)
        res = await driver.click_plus_one()
        assert res.success is True and tier1.clicked is True and "Tier 1 (#extend)" in res.message
        record_pass("Selector Tier 1 (#extend) direct match")
    except Exception as e:
        record_fail("Selector Tier 1 match", e)

    # 2.2 Tier 2 Fallback
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        tier2 = driver._page.set_element('button[data-action="extend"]', "+1", visible=True)
        res = await driver.click_plus_one()
        assert res.success is True and tier2.clicked is True and "Tier 2" in res.message
        record_pass("Selector Tier 2 (button[data-action='extend']) fallback")
    except Exception as e:
        record_fail("Selector Tier 2 fallback", e)

    # 2.3 Tier 3 Fallback
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        tier3 = driver._page.set_element(".statuslabel-countdown button", "+1", visible=True)
        res = await driver.click_plus_one()
        assert res.success is True and tier3.clicked is True and "Tier 3" in res.message
        record_pass("Selector Tier 3 (.statuslabel-countdown button) fallback")
    except Exception as e:
        record_fail("Selector Tier 3 fallback", e)

    # 2.4 Tier 4 Fallback
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        tier4 = driver._page.set_element('button:has-text("+1")', "+1", visible=True)
        res = await driver.click_plus_one()
        assert res.success is True and tier4.clicked is True and "Tier 4" in res.message
        record_pass("Selector Tier 4 (button:has-text('+1')) fallback")
    except Exception as e:
        record_fail("Selector Tier 4 fallback", e)

    # 2.5 Tier 5 JS Evaluation Fallback
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        driver._page.js_eval_result = {"success": True, "tier": "Tier 5 (JS text scan)"}
        res = await driver.click_plus_one()
        assert res.success is True and "Tier 5" in res.message
        record_pass("Selector Tier 5 (JS evaluate) fallback")
    except Exception as e:
        record_fail("Selector Tier 5 fallback", e)

    # 2.6 Hidden Element Skip
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.set_element(".countdown", "02:30", visible=True)
        driver._page.set_element("#extend", "+1", visible=False)
        tier3 = driver._page.set_element(".statuslabel-countdown button", "+1", visible=True)
        res = await driver.click_plus_one()
        assert res.success is True and tier3.clicked is True and "Tier 3" in res.message
        record_pass("Selector hidden element bypass to active tier")
    except Exception as e:
        record_fail("Selector hidden element bypass", e)

    # 2.7 Complete Failure Graceful Handling
    try:
        driver = AternosDriver()
        driver._page = MockPage()
        driver._page.js_eval_result = {"success": False, "error": "Button not found"}
        res = await driver.click_plus_one()
        assert res.success is False and "failed to locate" in res.message.lower()
        record_pass("Selector graceful handling on all tiers absent")
    except Exception as e:
        record_fail("Selector graceful handling on failure", e)


# ===========================================================================
# 3. EMERGENCY COUNTDOWN THRESHOLDS & RAPID DROP STRESS
# ===========================================================================

async def run_emergency_threshold_stress():
    print("\n--- Running Suite 3: Emergency Countdown Thresholds & Rapid Drop Stress ---")

    # 3.1 Settings validation
    try:
        s = Settings(COUNTDOWN_THRESHOLD=180, EMERGENCY_THRESHOLD=30)
        assert s.COUNTDOWN_THRESHOLD == 180 and s.EMERGENCY_THRESHOLD == 30
        try:
            Settings(COUNTDOWN_THRESHOLD=30, EMERGENCY_THRESHOLD=30)
            record_fail("Settings threshold ordering validation", Exception("Allowed EMERGENCY >= COUNTDOWN"))
        except ValueError:
            record_pass("Settings threshold ordering validation (EMERGENCY < COUNTDOWN strictly enforced)")
    except Exception as e:
        record_fail("Settings validation", e)

    # 3.2 Instant Emergency Trigger at 0:05 (5 seconds)
    try:
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=5)
        logger_hub = AppLogger()
        engine = KeepAliveEngine(driver=driver, logger_hub=logger_hub)
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        snapshot = await driver.get_server_status()
        await engine._update_state_from_snapshot(snapshot)

        assert engine.state.countdown_seconds == 5
        assert engine.state.is_countdown_critical is True

        await engine._handle_online_keepalive()

        assert driver.plus_one_clicks == 1
        assert driver.countdown == 360
        assert engine.state.plus_one_click_count == 1
        record_pass("Instant 0:05 emergency trigger executes immediate +1 click")
    except Exception as e:
        record_fail("Instant 0:05 emergency trigger", e)

    # 3.3 Rapid Drop Multi-Stage Simulation (300s -> 180s -> 20s)
    try:
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=300)
        engine = KeepAliveEngine(driver=driver)
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        # Stage A: 300s -> No click
        snap_300 = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=300, countdown_text="05:00")
        await engine._update_state_from_snapshot(snap_300)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 0

        # Stage B: Drop to 180s -> Standard threshold click
        snap_180 = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=180, countdown_text="03:00")
        await engine._update_state_from_snapshot(snap_180)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 1

        # Stage C: Rapid drop to 20s -> Emergency click
        snap_20 = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=20, countdown_text="00:20")
        await engine._update_state_from_snapshot(snap_20)
        await engine._handle_online_keepalive()
        assert driver.plus_one_clicks == 2
        record_pass("Rapid countdown drop simulation (300s -> 180s -> 20s) triggers standard and emergency clicks")
    except Exception as e:
        record_fail("Rapid countdown drop simulation", e)

    # 3.4 Disabled Keep-Alive suppresses triggers
    try:
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=5)
        engine = KeepAliveEngine(driver=driver)
        engine.toggle_keepalive(enabled=False)

        snap = ServerStatusSnapshot(status=ServerStatus.ONLINE, countdown_seconds=5, countdown_text="00:05")
        await engine._update_state_from_snapshot(snap)
        await engine._handle_online_keepalive()

        assert driver.plus_one_clicks == 0
        assert engine.state.plus_one_click_count == 0
        record_pass("Disabled keep-alive suppresses emergency trigger at 0:05")
    except Exception as e:
        record_fail("Disabled keep-alive check", e)

    # 3.5 Concurrency & Mutex Thread-Safety (50 concurrent clicks)
    try:
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=50)
        engine = KeepAliveEngine(driver=driver)

        tasks = [asyncio.create_task(engine._perform_plus_one_click()) for _ in range(50)]
        results_list = await asyncio.gather(*tasks)

        assert all(r.success for r in results_list)
        assert driver.plus_one_clicks == 50
        assert engine.state.plus_one_click_count == 50
        record_pass("Concurrency stress: 50 simultaneous +1 triggers maintain synchronized state")
    except Exception as e:
        record_fail("Concurrency stress test", e)

    # 3.6 Dynamic Sleep Interval Tuning
    try:
        engine = KeepAliveEngine()
        engine.config.CHECK_INTERVAL = 5.0
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        engine.state.status = ServerStatus.ONLINE
        engine.state.countdown_seconds = 15
        assert engine._calculate_next_sleep_interval() == 1.0

        engine.state.countdown_seconds = 120
        assert engine._calculate_next_sleep_interval() == 2.0

        engine.state.countdown_seconds = 300
        assert engine._calculate_next_sleep_interval() == 5.0

        engine.state.status = ServerStatus.IN_QUEUE
        engine.state.countdown_seconds = None
        assert engine._calculate_next_sleep_interval() == 2.0

        engine.state.status = ServerStatus.OFFLINE
        assert engine._calculate_next_sleep_interval() == 5.0
        record_pass("Dynamic sleep interval tuning across critical/warning/safe/queue/offline states")
    except Exception as e:
        record_fail("Dynamic sleep interval tuning", e)


async def main():
    print("=" * 70)
    print("STARTING EMPIRICAL VERIFICATION & STRESS HARNESS (MILESTONE 1)")
    print("=" * 70)
    
    run_countdown_fuzzing()
    await run_selector_resilience()
    await run_emergency_threshold_stress()

    print("\n" + "=" * 70)
    print(f"STRESS HARNESS COMPLETED: {passed} PASSED, {failed} FAILED")
    print("=" * 70)

    if failed > 0:
        print("\nSUMMARY: FAILURES DETECTED")
        sys.exit(1)
    else:
        print("\nSUMMARY: ALL EMPIRICAL TESTS PASSED SUCCESSFULLY (100% PASS RATE)")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
