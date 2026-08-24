"""
Keep-Alive Automation Engine & Finite State Machine (FSM).
Manages continuous background polling, dual-threshold +1 triggering (<=180s, <=30s),
concurrency mutex protection, queue confirmation, and real-time event telemetry.
"""

import asyncio
from datetime import datetime, timezone
import logging
import random
from typing import Any, Dict, Optional, Union

from src.bot.driver import AternosDriver, AternosDriverProtocol, MockDriver
from src.core.config import Settings, get_settings
from src.core.logger import AppLogger, LogBroadcaster, app_logger
from src.core.schemas import ActionResult, LogLevel, ServerState, ServerStatus, ServerStatusSnapshot

logger = logging.getLogger("aternos_bot.engine")


class KeepAliveEngine:
    """
    Continuous keep-alive engine orchestrating server lifecycle, countdown monitoring,
    exact +1 button extension triggers, and concurrency control.
    """
    def __init__(
        self,
        config: Optional[Settings] = None,
        driver: Optional[AternosDriverProtocol] = None,
        logger_hub: Optional[Union[AppLogger, LogBroadcaster]] = None,
        mock_server: Optional[Any] = None
    ) -> None:
        self.config = config or get_settings()
        
        # Configure logging hub
        if isinstance(logger_hub, AppLogger):
            self._app_logger = logger_hub
            self.logger_hub = logger_hub.broadcaster
        elif isinstance(logger_hub, LogBroadcaster):
            self._app_logger = AppLogger(broadcaster=logger_hub)
            self.logger_hub = logger_hub
        else:
            self._app_logger = app_logger
            self.logger_hub = app_logger.broadcaster

        # Alias for test compatibility
        self.logger = self.logger_hub

        # Configure driver
        if driver is not None:
            self._driver = driver
        elif mock_server is not None or self.config.MOCK_MODE:
            self._driver = MockDriver()
        else:
            self._driver = AternosDriver(config=self.config)

        self.mock_server = mock_server
        self.state = ServerState()
        if hasattr(self._driver, "status") and self._driver.status is not None:
            self.state.status = self._driver.status
        if hasattr(self._driver, "countdown") and self._driver.countdown is not None:
            self.state.countdown_seconds = self._driver.countdown
            mins, secs = divmod(self._driver.countdown, 60)
            self.state.countdown_text = f"{mins:02d}:{secs:02d}"

        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._action_lock = asyncio.Lock()
        self._last_status: ServerStatus = ServerStatus.OFFLINE
        self._consecutive_failures = 0

    @property
    def threshold_seconds(self) -> int:
        return self.config.COUNTDOWN_THRESHOLD

    @threshold_seconds.setter
    def threshold_seconds(self, value: int) -> None:
        self.config.COUNTDOWN_THRESHOLD = value

    @property
    def emergency_threshold_seconds(self) -> int:
        return self.config.EMERGENCY_THRESHOLD

    @emergency_threshold_seconds.setter
    def emergency_threshold_seconds(self, value: int) -> None:
        self.config.EMERGENCY_THRESHOLD = value

    @property
    def is_keepalive_active(self) -> bool:
        return self.state.is_keepalive_active

    @is_keepalive_active.setter
    def is_keepalive_active(self, value: bool) -> None:
        self.state.is_keepalive_active = value

    @property
    def session_valid(self) -> bool:
        return self.state.session_valid

    @session_valid.setter
    def session_valid(self, value: bool) -> None:
        self.state.session_valid = value

    def get_state(self) -> ServerState:
        """Returns an atomic snapshot copy of the current server state."""
        return self.state.model_copy()

    def toggle_keepalive(self, enabled: Optional[bool] = None) -> bool:
        """Enables, disables, or toggles automated +1 keepalive extension."""
        if enabled is None:
            self.state.is_keepalive_active = not self.state.is_keepalive_active
        else:
            self.state.is_keepalive_active = enabled

        status_str = "ENABLED" if self.state.is_keepalive_active else "DISABLED"
        self._app_logger.info(f"Keep-Alive automation mode set to: {status_str}", source="engine")
        self.logger_hub.broadcast_state(self.state)
        return self.state.is_keepalive_active

    async def start(self) -> None:
        """Initializes driver, warms session, and spawns the background polling worker."""
        if self._running:
            self._app_logger.warning("KeepAliveEngine.start() called, but engine is already running.")
            return

        self._app_logger.info("Initializing Keep-Alive Automation Engine...", source="engine")
        self._running = True

        try:
            await self._driver.initialize()
            self.state.session_valid = True
        except Exception as e:
            self._app_logger.error(f"Driver initialization encountered error: {e}", source="driver")
            self.state.session_valid = False

        self._poll_task = asyncio.create_task(self._poll_loop(), name="aternos-keepalive-loop")
        self._app_logger.success("Keep-Alive Engine successfully started.", source="engine")

    async def stop(self) -> None:
        """Cancels background polling tasks and cleanly shuts down driver."""
        if not self._running:
            return

        self._app_logger.info("Stopping Keep-Alive Engine...", source="engine")
        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        try:
            await self._driver.close()
        except Exception as e:
            self._app_logger.warning(f"Error while closing driver: {e}", source="driver")

        self._app_logger.info("Keep-Alive Engine shut down cleanly.", source="engine")

    async def _update_state_from_snapshot(self, snapshot: ServerStatusSnapshot) -> None:
        """Updates internal state from fresh DOM / driver snapshot."""
        old_status = self.state.status
        self.state.status = snapshot.status
        self.state.status_code = snapshot.status_code
        self.state.countdown_seconds = snapshot.countdown_seconds
        self.state.countdown_text = snapshot.countdown_text
        self.state.players_current = snapshot.players_current
        self.state.players_max = snapshot.players_max
        self.state.ram_usage = snapshot.ram_usage
        self.state.server_ip = snapshot.server_ip
        self.state.queue_position = snapshot.queue_position
        self.state.queue_time = snapshot.queue_time
        self.state.session_valid = snapshot.session_valid
        self.state.error_message = snapshot.error_message
        self.state.last_updated = datetime.now(timezone.utc)

        # Detect status transitions
        if snapshot.status != old_status:
            if snapshot.status == ServerStatus.ONLINE:
                self._app_logger.success(f"Server is now ONLINE! Active timer: {snapshot.countdown_text or 'N/A'}", source="engine")
            elif snapshot.status == ServerStatus.IN_QUEUE:
                self._app_logger.info(f"Server entered queue. Position: #{snapshot.queue_position or 'N/A'}", source="engine")
            elif snapshot.status == ServerStatus.CRASHED:
                self._app_logger.error("ALERT: Server has CRASHED.", source="engine")
            elif snapshot.status == ServerStatus.STOPPING:
                self._app_logger.warning("Server is currently STOPPING.", source="engine")
            elif snapshot.status == ServerStatus.OFFLINE:
                self._app_logger.info("Server is OFFLINE.", source="engine")

            self.logger_hub.broadcast_state(self.state)

    async def _handle_online_keepalive(self) -> None:
        """Evaluates countdown threshold AND checks for visible +1 button to execute click automatically."""
        if not self.state.is_keepalive_active:
            return

        countdown = self.state.countdown_seconds
        is_btn_visible = await self._driver.is_plus_one_button_visible()

        # Cooldown guard: Avoid rapid spamming if clicked in the last 8 seconds
        now = datetime.now(timezone.utc)
        if self.state.last_plus_one_click:
            elapsed = (now - self.state.last_plus_one_click).total_seconds()
            if elapsed < 8.0:
                return

        should_click = False
        reason = ""
        is_emergency = False

        if is_btn_visible:
            # Humanized delay between 59s and 50s
            if countdown is not None and countdown >= 50:
                # Randomize wait time to simulate human reaction (e.g. click at random second between 50s and 57s)
                max_delay = min(float(countdown - 48), 7.5)
                if max_delay > 1.0:
                    jitter = random.uniform(1.2, max_delay)
                    await asyncio.sleep(jitter)
            should_click = True
            reason = f"'+1' button is visible on status bar (Humanized click window 50s-59s, Timer: {self.state.countdown_text or 'active'})"
        elif countdown is not None and countdown <= self.config.EMERGENCY_THRESHOLD:
            should_click = True
            is_emergency = True
            reason = f"EMERGENCY: Countdown critical ({countdown}s <= {self.config.EMERGENCY_THRESHOLD}s)"

        if should_click:
            self._app_logger.info(
                f"Auto Keep-Alive triggered: {reason}. Executing automated '+1' click...",
                source="engine"
            )
            res = await self._perform_plus_one_click(is_emergency=is_emergency)
            if res.success:
                self._app_logger.success(f"Automated '+1' click succeeded: {res.message}", source="engine")
            else:
                self._app_logger.warning(f"Automated '+1' click attempt failed: {res.message}", source="engine")

    async def _handle_queue_state(self) -> None:
        """Handles queue confirmation if auto-confirm is enabled."""
        if not self.config.AUTO_CONFIRM_QUEUE:
            return

        is_visible = await self._driver.is_confirm_button_visible()
        if is_visible:
            self._app_logger.warning("Queue confirmation prompt detected! Auto-confirming slot...", source="engine")
            res = await self.confirm_queue()
            if res.success:
                self._app_logger.success(f"Queue slot confirmed: {res.message}", source="engine")
            else:
                self._app_logger.error(f"Queue confirmation click failed: {res.message}", source="engine")

    async def _perform_plus_one_click(self, is_emergency: bool = False) -> ActionResult:
        """Executes driver click_plus_one within lock, updates counters and logs."""
        async with self._action_lock:
            result = await self._driver.click_plus_one()

        if result.success:
            self.state.plus_one_click_count += 1
            self.state.last_plus_one_click = datetime.now(timezone.utc)
            tier_info = result.data.get("tier") if result.data else None
            new_countdown = None
            if result.data:
                new_countdown = result.data.get("new_countdown") or result.data.get("countdown")
            if new_countdown is None and hasattr(self._driver, "countdown"):
                new_countdown = self._driver.countdown
            elif new_countdown is None and self.mock_server is not None:
                new_countdown = self.mock_server.countdown
            if new_countdown is None:
                new_countdown = self.state.countdown_seconds

            if new_countdown is not None:
                self.state.countdown_seconds = new_countdown
                mins, secs = divmod(new_countdown, 60)
                self.state.countdown_text = f"{mins:02d}:{secs:02d}"
            
            self._app_logger.plus_one(
                message=f"Clicked '+1' button successfully (Total clicks: {self.state.plus_one_click_count}) - Timer extended",
                remaining_seconds=self.state.countdown_seconds,
                new_seconds=new_countdown,
                tier=tier_info,
                source="engine",
                data={"click_count": self.state.plus_one_click_count, "result": result.message}
            )
            self.logger_hub.broadcast_state(self.state)
        return result

    def check_and_perform_keepalive(self) -> bool:
        """
        Synchronous/Deterministic keep-alive evaluation for test fixtures and mock server loops.
        """
        if not self.state.is_keepalive_active:
            return False

        if self.mock_server is not None:
            # Sync state with mock server
            s = self.mock_server
            self.state.status = s.status
            self.state.countdown_seconds = s.countdown
            self.state.plus_one_click_count = s.plus_one_clicks
            if s.countdown is not None:
                mins, secs = divmod(s.countdown, 60)
                self.state.countdown_text = f"{mins:02d}:{secs:02d}"

            if s.status == ServerStatus.ONLINE and s.countdown is not None:
                if s.countdown <= self.config.COUNTDOWN_THRESHOLD:
                    return self.trigger_plus_one_sync()
            elif s.status == ServerStatus.IN_QUEUE and s.queue_position == 0:
                return self.confirm_queue_sync()
            return False

        # If running with async mock driver
        if isinstance(self._driver, MockDriver):
            if self._driver.status == ServerStatus.ONLINE and self._driver.countdown is not None:
                if self._driver.countdown <= self.config.COUNTDOWN_THRESHOLD:
                    self._driver.plus_one_clicks += 1
                    self._driver.countdown = 360
                    self.state.plus_one_click_count = self._driver.plus_one_clicks
                    self.state.last_plus_one_click = datetime.now(timezone.utc)
                    self._app_logger.plus_one(
                        f"Clicked '+1' button successfully - Timer extended to {self._driver.countdown}s",
                        source="engine",
                        data={"clicks": self._driver.plus_one_clicks}
                    )
                    return True
            elif self._driver.status == ServerStatus.IN_QUEUE and (self._driver.queue_position is None or self._driver.queue_position == 0):
                self._driver.status = ServerStatus.LOADING
                return True
        return False

    def trigger_plus_one_sync(self) -> bool:
        """Synchronous version of trigger_plus_one for mock fixtures."""
        if self.mock_server is not None:
            success = self.mock_server.trigger_plus_one()
            if success:
                self.state.plus_one_click_count = self.mock_server.plus_one_clicks
                self.state.last_plus_one_click = datetime.now(timezone.utc)
                self.state.countdown_seconds = self.mock_server.countdown
                self._app_logger.plus_one(
                    f"Clicked '+1' button successfully - Timer extended to {self.mock_server.countdown}s",
                    source="engine",
                    data={"clicks": self.mock_server.plus_one_clicks}
                )
            return success
        return False

    def confirm_queue_sync(self) -> bool:
        """Synchronous version of confirm_queue for mock fixtures."""
        if self.mock_server is not None:
            return self.mock_server.confirm_queue()
        return False

    def _calculate_next_sleep_interval(self) -> float:
        """Dynamically tunes sleep duration to balance responsiveness and low CPU/RAM usage."""
        if self.state.status == ServerStatus.ONLINE and self.state.countdown_seconds is not None:
            if self.state.countdown_seconds <= self.config.EMERGENCY_THRESHOLD:
                return 1.0  # Fast polling during emergency
            elif self.state.countdown_seconds <= self.config.COUNTDOWN_THRESHOLD:
                return 2.0
            else:
                # Safe zone: calculate optimal sleep time before threshold
                safe_lead = max(2.0, float(self.state.countdown_seconds - self.config.COUNTDOWN_THRESHOLD))
                return min(self.config.CHECK_INTERVAL, safe_lead)

        if self.state.status in (ServerStatus.IN_QUEUE, ServerStatus.LOADING):
            return 2.0

        return self.config.CHECK_INTERVAL

    async def _poll_loop(self) -> None:
        """Continuous background worker loop."""
        self._app_logger.info("Keep-Alive Engine polling loop active.", source="engine")

        while self._running:
            try:
                # Read snapshot safely
                async with self._action_lock:
                    snapshot = await self._driver.get_server_status()
                    await self._update_state_from_snapshot(snapshot)

                # Process state-specific automation
                if self.state.status == ServerStatus.ONLINE:
                    await self._handle_online_keepalive()
                elif self.state.status == ServerStatus.IN_QUEUE:
                    await self._handle_queue_state()
                elif self.state.status == ServerStatus.OFFLINE and self.config.AUTO_START_ON_OFFLINE:
                    self._app_logger.info("Auto-start enabled and server is offline. Starting...", source="engine")
                    await self.start_server()

                self._consecutive_failures = 0
                sleep_duration = self._calculate_next_sleep_interval()
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_failures += 1
                self._app_logger.error(f"Error during keep-alive polling cycle: {e}", source="engine")
                self.state.status = ServerStatus.UNKNOWN
                self.state.session_valid = False
                self.logger_hub.broadcast_state(self.state)
                await asyncio.sleep(min(self.config.CHECK_INTERVAL, 5.0))

    # -----------------------------------------------------------------------
    # Manual Control API Methods
    # -----------------------------------------------------------------------

    async def trigger_plus_one(self) -> ActionResult:
        """Manually triggers +1 extension button."""
        if self.mock_server is not None:
            success = self.trigger_plus_one_sync()
            return ActionResult(
                success=success,
                message="Clicked '+1' button successfully" if success else "Failed to click +1 button",
                data={"clicks": self.state.plus_one_click_count}
            )

        self._app_logger.info("Manual command received: Extending timer via '+1' button...", source="engine")
        return await self._perform_plus_one_click(is_emergency=False)

    async def start_server(self) -> ActionResult:
        """Manually triggers server startup."""
        if self.mock_server is not None:
            success = self.mock_server.start()
            if success:
                self.state.status = self.mock_server.status
                self._app_logger.success("Server start initiated - Entering queue", source="engine")
                return ActionResult(success=True, message="Server starting...")
            return ActionResult(success=False, message="Cannot start server: already active")

        async with self._action_lock:
            if hasattr(self._driver, "status") and self._driver.status in (ServerStatus.OFFLINE, ServerStatus.CRASHED):
                self.state.status = self._driver.status
            if self.state.status in (ServerStatus.ONLINE, ServerStatus.LOADING, ServerStatus.IN_QUEUE):
                return ActionResult(success=False, message=f"Cannot start: server is already {self.state.status}")
            self._app_logger.info("Manual command received: Starting server...", source="engine")
            result = await self._driver.start_server()
            if result.success:
                self.state.status = ServerStatus.LOADING
                self.logger_hub.broadcast_state(self.state)
            return result

    async def stop_server(self) -> ActionResult:
        """Manually triggers graceful server shutdown."""
        if self.mock_server is not None:
            success = self.mock_server.stop()
            if success:
                self.state.status = self.mock_server.status
                self._app_logger.warning("Server stop command issued", source="engine")
                return ActionResult(success=True, message="Server stopping...")
            return ActionResult(success=False, message="Cannot stop server: already offline")

        async with self._action_lock:
            if hasattr(self._driver, "status") and self._driver.status in (ServerStatus.ONLINE, ServerStatus.LOADING, ServerStatus.IN_QUEUE):
                self.state.status = self._driver.status
            if self.state.status in (ServerStatus.OFFLINE, ServerStatus.STOPPING):
                return ActionResult(success=False, message=f"Cannot stop: server is already {self.state.status}")
            self._app_logger.info("Manual command received: Stopping server...", source="engine")
            result = await self._driver.stop_server()
            if result.success:
                self.state.status = ServerStatus.STOPPING
                self.logger_hub.broadcast_state(self.state)
            return result

    async def restart_server(self) -> ActionResult:
        """Manually triggers server restart."""
        if self.mock_server is not None:
            self.mock_server.stop()
            self.mock_server.start()
            self.state.status = ServerStatus.IN_QUEUE
            return ActionResult(success=True, message="Server restarting...")

        async with self._action_lock:
            self._app_logger.info("Manual command received: Restarting server...", source="engine")
            result = await self._driver.restart_server()
            if result.success:
                self.state.status = ServerStatus.STOPPING
                self.logger_hub.broadcast_state(self.state)
            return result

    async def confirm_queue(self) -> ActionResult:
        """Manually or automatically confirms queue slot readiness."""
        if self.mock_server is not None:
            success = self.confirm_queue_sync()
            return ActionResult(success=success, message="Queue confirmed" if success else "Failed to confirm")

        async with self._action_lock:
            self._app_logger.info("Confirming queue slot...", source="engine")
            result = await self._driver.confirm_queue()
            if result.success:
                self.state.status = ServerStatus.LOADING
                self.logger_hub.broadcast_state(self.state)
            return result

    async def reload_session(self) -> bool:
        """Reloads session cookies and refreshes browser page."""
        if self.mock_server is not None:
            self.session_valid = True
            self.state.session_valid = True
            return True

        async with self._action_lock:
            self._app_logger.info("Reloading browser session cookies and refreshing dashboard...", source="engine")
            success = await self._driver.reload_session()
            self.state.session_valid = success
            self.logger_hub.broadcast_state(self.state)
            return success

    async def get_screenshot(self) -> bytes:
        """Captures viewport screenshot bytes."""
        if self.mock_server is not None:
            return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

        async with self._action_lock:
            return await self._driver.get_screenshot()
