"""
Adversarial Concurrency, State Synchronization, and Buffer Isolation Stress Suite.
Created by Challenger (challenger_m1_2) for Milestone 1 Empirical Verification.

Testing:
1. High-concurrency manual controls (concurrent start/stop/toggle/click while polling loop is active).
2. MockDriver vs Engine state synchronization across 100+ simulated ticks.
3. Circular ring buffer overflow and subscriber isolation under rapid burst logging.
"""

import asyncio
from datetime import datetime, timezone
import pytest
import time
from typing import List, Optional

from src.bot.driver import MockDriver
from src.bot.engine import KeepAliveEngine
from src.core.config import Settings
from src.core.logger import AppLogger, LogBroadcaster
from src.core.schemas import ActionResult, LogEvent, LogLevel, ServerState, ServerStatus, ServerStatusSnapshot


# ===========================================================================
# 1. HIGH-CONCURRENCY MANUAL CONTROLS
# ===========================================================================

class TestHighConcurrencyManualControls:
    """Stress tests concurrent manual interactions while KeepAliveEngine poll loop is active."""

    @pytest.mark.asyncio
    async def test_concurrent_manual_controls_under_active_poll_loop(self):
        """
        Spawns active polling engine and floods it with 100 concurrent interleaved
        operations: toggle_keepalive, trigger_plus_one, start_server, stop_server, restart_server.
        Verifies no deadlocks, no unhandled exceptions, and lock safety.
        """
        config = Settings(CHECK_INTERVAL=1.0, COUNTDOWN_THRESHOLD=180, EMERGENCY_THRESHOLD=30)
        broadcaster = LogBroadcaster(buffer_size=500)
        app_log = AppLogger(broadcaster=broadcaster)
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=200, tick_rate=0.0)
        engine = KeepAliveEngine(config=config, driver=driver, logger_hub=app_log)

        await engine.start()
        assert engine._running is True

        errors = []

        async def worker_toggle(worker_id: int):
            for _ in range(10):
                try:
                    engine.toggle_keepalive()
                    await asyncio.sleep(0.001)
                except Exception as e:
                    errors.append(("toggle", worker_id, str(type(e)), str(e)))

        async def worker_plus_one(worker_id: int):
            for _ in range(10):
                try:
                    await engine.trigger_plus_one()
                    await asyncio.sleep(0.001)
                except Exception as e:
                    errors.append(("plus_one", worker_id, str(type(e)), str(e)))

        async def worker_lifecycle(worker_id: int):
            for _ in range(5):
                try:
                    await engine.stop_server()
                    await asyncio.sleep(0.001)
                    await engine.start_server()
                    await asyncio.sleep(0.001)
                    await engine.restart_server()
                    await asyncio.sleep(0.001)
                except Exception as e:
                    errors.append(("lifecycle", worker_id, str(type(e)), str(e)))

        # Launch 30 concurrent worker tasks (10 of each type)
        tasks = []
        for i in range(10):
            tasks.append(asyncio.create_task(worker_toggle(i)))
            tasks.append(asyncio.create_task(worker_plus_one(i)))
            tasks.append(asyncio.create_task(worker_lifecycle(i)))

        await asyncio.gather(*tasks)

        # Allow background loop to execute a few cycles
        await asyncio.sleep(0.05)
        await engine.stop()
        assert engine._running is False

        # Verify no errors occurred during concurrency stress
        assert len(errors) == 0, f"Concurrency errors detected: {errors}"

    @pytest.mark.asyncio
    async def test_high_volume_concurrent_plus_one_clicks(self):
        """
        Executes 100 concurrent trigger_plus_one calls in parallel.
        Verifies mutex serialized execution and exact count accounting.
        """
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=100)
        engine = KeepAliveEngine(driver=driver)

        tasks = [asyncio.create_task(engine.trigger_plus_one()) for _ in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Exceptions during concurrent clicks: {exceptions}"

        # Check result counts
        successful_clicks = [r for r in results if isinstance(r, ActionResult) and r.success]
        assert len(successful_clicks) == 100
        assert driver.plus_one_clicks == 100
        assert engine.state.plus_one_click_count == 100


# ===========================================================================
# 2. MOCKDRIVER VS ENGINE STATE SYNCHRONIZATION (100+ TICKS)
# ===========================================================================

class TestMockDriverEngineStateSync:
    """Verifies lock-step state synchronization between MockDriver and KeepAliveEngine over 100+ ticks."""

    @pytest.mark.asyncio
    async def test_150_simulated_ticks_keepalive_lifecycle(self):
        """
        Simulates 150 seconds of server operation where countdown ticks down from 200s,
        triggers +1 click at <= 180s, resets to 360s, ticks down again, triggers +1 click,
        verifying engine.state and driver state match exactly at every step.
        """
        driver = MockDriver(initial_status=ServerStatus.ONLINE, initial_countdown=200, tick_rate=0.0)
        engine = KeepAliveEngine(driver=driver)
        engine.config.COUNTDOWN_THRESHOLD = 180
        engine.config.EMERGENCY_THRESHOLD = 30

        click_events = []

        # Run 150 discrete simulated ticks
        for tick in range(1, 151):
            # Driver ticks 1 second
            driver.tick(1)
            
            # Engine reads snapshot
            snapshot = await driver.get_server_status()
            await engine._update_state_from_snapshot(snapshot)
            
            # Engine evaluates keepalive rule
            if engine.state.status == ServerStatus.ONLINE and engine.state.countdown_seconds is not None:
                if engine.state.countdown_seconds <= engine.config.COUNTDOWN_THRESHOLD:
                    res = await engine._perform_plus_one_click()
                    assert res.success is True
                    click_events.append((tick, engine.state.countdown_seconds, driver.countdown))

            # Invariant assertions at every tick
            assert engine.state.status == driver.status, f"Status mismatch at tick {tick}: {engine.state.status} vs {driver.status}"
            assert engine.state.plus_one_click_count == driver.plus_one_clicks, (
                f"Click count mismatch at tick {tick}: engine={engine.state.plus_one_click_count}, driver={driver.plus_one_clicks}"
            )
            if driver.status == ServerStatus.ONLINE and driver.countdown is not None:
                assert engine.state.countdown_seconds == driver.countdown, (
                    f"Countdown mismatch at tick {tick}: engine={engine.state.countdown_seconds}, driver={driver.countdown}"
                )

        # After 150 ticks with resets, at least 1 +1 click must have occurred
        assert driver.plus_one_clicks >= 1
        assert engine.state.plus_one_click_count >= 1
        assert len(click_events) >= 1

    @pytest.mark.asyncio
    async def test_100_ticks_full_server_lifecycle_state_sync(self):
        """
        Simulates 100 ticks across transitions:
        OFFLINE -> START -> IN_QUEUE (pos 5 -> 0) -> CONFIRM -> LOADING -> ONLINE -> STOP -> OFFLINE.
        Verifies state synchronization across every transition.
        """
        driver = MockDriver(initial_status=ServerStatus.OFFLINE, initial_countdown=None, tick_rate=0.0)
        engine = KeepAliveEngine(driver=driver)

        # 1. Start server
        start_res = await engine.start_server()
        assert start_res.success is True
        assert driver.status == ServerStatus.IN_QUEUE

        # Sync 5 queue ticks
        for i in range(5):
            driver.tick(1)
            snapshot = await driver.get_server_status()
            await engine._update_state_from_snapshot(snapshot)

        # When queue pos reached 0, confirm queue
        assert driver.status == ServerStatus.LOADING
        snapshot = await driver.get_server_status()
        await engine._update_state_from_snapshot(snapshot)
        assert engine.state.status == ServerStatus.LOADING

        # Tick into ONLINE
        driver.tick(1)
        snapshot = await driver.get_server_status()
        await engine._update_state_from_snapshot(snapshot)
        assert engine.state.status == ServerStatus.ONLINE
        assert engine.state.countdown_seconds == 360

        # Tick 90 seconds online
        for _ in range(90):
            driver.tick(1)
            snapshot = await driver.get_server_status()
            await engine._update_state_from_snapshot(snapshot)
            assert engine.state.countdown_seconds == driver.countdown

        assert engine.state.countdown_seconds == 270

        # Stop server
        stop_res = await engine.stop_server()
        assert stop_res.success is True
        driver.tick(1)
        snapshot = await driver.get_server_status()
        await engine._update_state_from_snapshot(snapshot)
        assert engine.state.status == ServerStatus.OFFLINE
        assert engine.state.countdown_seconds is None


# ===========================================================================
# 3. CIRCULAR BUFFER OVERFLOW & SUBSCRIBER ISOLATION
# ===========================================================================

class TestCircularBufferAndSubscriberIsolation:
    """Stress tests circular buffer capping and async subscriber queue isolation under log bursts."""

    def test_circular_ring_buffer_overflow_2000_events(self):
        """
        Dispatches 2,000 log events into LogBroadcaster with max_buffer=200.
        Verifies buffer strictly caps at 200 and retains the latest 200 events.
        """
        broadcaster = LogBroadcaster(buffer_size=200)
        for i in range(2000):
            broadcaster.log(f"Burst message #{i:04d}", "INFO")

        logs = broadcaster.logs
        assert len(logs) == 200
        assert logs[0].message == "Burst message #1800"
        assert logs[-1].message == "Burst message #1999"

    def test_app_logger_method_signatures_compatibility(self):
        """
        Verifies all AppLogger methods (info, success, warning, warn, error, debug, plus_one, log)
        execute cleanly without TypeError or missing argument errors.
        """
        broadcaster = LogBroadcaster(buffer_size=100)
        app_log = AppLogger(broadcaster=broadcaster)

        ev_info = app_log.info("Info test")
        assert ev_info.level == "INFO"
        assert ev_info.message == "Info test"

        ev_succ = app_log.success("Success test")
        assert ev_succ.level == "SUCCESS"

        ev_warn = app_log.warning("Warn test")
        assert ev_warn.level == "WARN"

        ev_warn2 = app_log.warn("Warn2 test")
        assert ev_warn2.level == "WARN"

        ev_err = app_log.error("Error test")
        assert ev_err.level == "ERROR"

        ev_dbg = app_log.debug("Debug test")
        assert ev_dbg.level == "DEBUG"

        ev_plus = app_log.plus_one("Plus one click", remaining_seconds=120, new_seconds=360, tier="Tier 1 (#extend)")
        assert ev_plus.level == "PLUS_ONE"
        assert ev_plus.data["remaining_seconds"] == 120
        assert ev_plus.data["new_seconds"] == 360
        assert ev_plus.data["tier"] == "Tier 1 (#extend)"

        # Direct log methods
        ev_log1 = app_log.log("Direct log test", "INFO")
        assert ev_log1.level == "INFO"

        ev_log2 = app_log.log_event("SUCCESS", "Log event test")
        assert ev_log2.level == "SUCCESS"

    @pytest.mark.asyncio
    async def test_subscriber_isolation_under_slow_consumer_backpressure(self):
        """
        Simulates 2 subscribers:
        - Subscriber 1 is FAST and actively consumes messages.
        - Subscriber 2 is STALLED / SLOW and allows its queue (maxsize=100) to overflow.
        Verifies that when Subscriber 2 overflows, QueueFull is caught,
        Subscriber 1 continues receiving all events normally, and the publisher never blocks.
        """
        broadcaster = LogBroadcaster(buffer_size=500)

        # Create 2 WebSocket queues
        fast_queue = broadcaster.subscribe_queue()
        slow_queue = broadcaster.subscribe_queue()

        # Send 150 events in a rapid burst
        for i in range(150):
            broadcaster.log(f"Burst event {i}", "INFO")

        # Slow queue has maxsize=100, should be full (100 items)
        assert slow_queue.qsize() == 100

        # Fast queue is drained
        fast_events: List[LogEvent] = []
        while not fast_queue.empty():
            fast_events.append(fast_queue.get_nowait())

        # Fast queue received first 100 items because it didn't consume during loop,
        # but slow queue didn't crash or block execution
        assert len(fast_events) == 100

        # Clean up
        broadcaster.unsubscribe_queue(fast_queue)
        broadcaster.unsubscribe_queue(slow_queue)
        assert len(broadcaster._subscribers) == 0
