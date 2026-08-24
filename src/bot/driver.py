"""
Async Playwright Driver Architecture & Deterministic Mock Driver.
Provides stealth browser automation, request routing/adblock memory optimization,
5-tier fallback selector dispatch, screenshot capture, and post-click verification.
"""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union

from src.bot.selectors import (
    ADBLOCK_DISMISS_SELECTORS,
    CONFIRM_BUTTON_SELECTORS,
    COUNTDOWN_SELECTORS,
    EULA_ACCEPT_SELECTORS,
    LOGIN_FORM_SELECTORS,
    PLUS_ONE_SELECTORS,
    RESTART_BUTTON_SELECTORS,
    START_BUTTON_SELECTORS,
    STATUS_LABEL_SELECTORS,
    STOP_BUTTON_SELECTORS,
    TIER1_SELECTORS,
    TIER2_SELECTORS,
    TIER3_SELECTORS,
    TIER4_SELECTORS,
    TIER5_JS_EVALUATE,
    classify_status_text,
    parse_countdown_str,
)
from src.core.config import Settings, get_settings
from src.core.schemas import ActionResult, ServerStatus, ServerStatusSnapshot

logger = logging.getLogger("aternos_bot.driver")


class AternosDriverProtocol(Protocol):
    """Protocol defining the driver interface for both real Playwright and Mock drivers."""
    async def initialize(self) -> None: ...
    async def get_server_status(self) -> ServerStatusSnapshot: ...
    async def get_countdown_seconds(self) -> Optional[int]: ...
    async def click_plus_one(self) -> ActionResult: ...
    async def start_server(self) -> ActionResult: ...
    async def stop_server(self) -> ActionResult: ...
    async def restart_server(self) -> ActionResult: ...
    async def confirm_queue(self) -> ActionResult: ...
    async def reload_session(self) -> bool: ...
    async def get_screenshot(self) -> bytes: ...
    async def is_confirm_button_visible(self) -> bool: ...
    async def is_plus_one_button_visible(self) -> bool: ...
    async def dismiss_adblock_modal(self) -> bool: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Anti-Bot Stealth Script Overrides
# ---------------------------------------------------------------------------

STEALTH_INIT_SCRIPT = """
(() => {
    // 1. Mask navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    try {
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch(e) {}

    // 2. Mock chrome runtime & objects
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };

    // 3. Emulate standard navigator plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ]
    });

    // 4. Emulate language preferences
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

    // 5. Mock permissions query
    if (window.navigator.permissions) {
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    }

    // 6. Spoof WebGL Vendor and Renderer
    if (typeof WebGLRenderingContext !== 'undefined') {
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Google Inc. (NVIDIA)';
            if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return getParameter.apply(this, [parameter]);
        };
    }

    // 7. Spoof AdBlock detection variables so Aternos never triggers adblock warning
    window.canRunAds = true;
    window.isAdBlockActive = false;
    window.google_ad_client = "ca-pub-123456789";
    window.adsbygoogle = window.adsbygoogle || [];
    window.adsbygoogle.loaded = true;
})();
"""


class AternosDriver:
    """
    Playwright async automation driver for the Aternos server management panel.
    """
    def __init__(self, config: Optional[Settings] = None) -> None:
        self.config = config or get_settings()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._is_ready = False

    async def initialize(self) -> None:
        """Launches Chromium browser, injects stealth masks, configures adblock routes, and navigates."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self.config.HEADLESS,
            args=launch_args,
            timeout=int(self.config.BROWSER_TIMEOUT * 1000)
        )

        self._context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="UTC"
        )

        # Inject stealth scripts into all new frames and pages
        await self._context.add_init_script(STEALTH_INIT_SCRIPT)

        # Inject session cookies if configured
        if self.config.ATERNOS_SESSION:
            cookies = [
                {
                    "name": "ATERNOS_SESSION",
                    "value": self.config.ATERNOS_SESSION.strip(),
                    "domain": ".aternos.org",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax"
                }
            ]
            if self.config.ATERNOS_SEC_TOKEN:
                cookies.append({
                    "name": "ATERNOS_SEC_TOKEN",
                    "value": self.config.ATERNOS_SEC_TOKEN.strip(),
                    "domain": ".aternos.org",
                    "path": "/",
                })
            await self._context.add_cookies(cookies)

        self._page = await self._context.new_page()

        # Set up memory-saving adblock route abortion
        await self._setup_route_interception(self._page)

        target_url = self.config.ATERNOS_SERVER_URL
        if self.config.ATERNOS_SERVER_ID:
            target_url = f"{self.config.ATERNOS_BASE_URL}/server/{self.config.ATERNOS_SERVER_ID}/"

        try:
            await self._page.goto(target_url, timeout=int(self.config.BROWSER_TIMEOUT * 1000), wait_until="domcontentloaded")
            await self.dismiss_adblock_modal()
            self._is_ready = True
            logger.info("Aternos driver successfully initialized.")
        except Exception as e:
            logger.warning(f"Initial navigation encountered issue: {e}")
            self._is_ready = True

    async def _setup_route_interception(self, page: Any) -> None:
        """Allows normal browser network traffic to prevent anti-adblock detection."""
        # Intentionally no-op to let Chromium act as a standard browser without triggering Aternos adblock alarms
        pass

    async def dismiss_adblock_modal(self) -> bool:
        """Dismisses anti-adblock modal dialog or full-screen warning if present and purges overlay DOM."""
        if not self._page or self._page.is_closed():
            return False

        # 1. Try clicking standard and Arabic selectors
        for selector in ADBLOCK_DISMISS_SELECTORS:
            try:
                elem = await self._page.query_selector(selector)
                if elem and await elem.is_visible():
                    await elem.click(timeout=1500)
                    logger.info(f"Dismissed adblock overlay via {selector}")
                    await self._page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue

        # 2. Comprehensive JS fallback: click continue button, remove overlay, restore pointer events & overflow
        try:
            dismissed = await self._page.evaluate("""
            (() => {
                let clicked = false;
                // Click any continue button/link
                const elements = Array.from(document.querySelectorAll('button, a, div.btn, .btn-continue-adblock, [class*="adblock"] button, [class*="adblock"] a'));
                for (const el of elements) {
                    const text = (el.textContent || '').trim();
                    if (text.includes('المتابعة') || text.includes('Continue') || text.includes('adblock') || el.classList.contains('btn-continue-adblock')) {
                        el.click();
                        clicked = true;
                    }
                }
                
                // Remove adblock overlay elements from DOM
                const overlays = document.querySelectorAll('.adblock, .adblock-overlay, .modal-adblock, .adblock-warning, #adblock, div[style*="z-index"][style*="fixed"], div[style*="z-index"][style*="absolute"]');
                for (const ov of overlays) {
                    if (ov.textContent && (ov.textContent.includes('مانع') || ov.textContent.includes('إعلانات') || ov.textContent.includes('adblock') || ov.textContent.includes('Adblock'))) {
                        ov.remove();
                        clicked = true;
                    }
                }
                
                // Restore body styles
                document.body.style.overflow = 'auto';
                document.body.style.pointerEvents = 'auto';
                document.documentElement.style.overflow = 'auto';
                document.documentElement.style.pointerEvents = 'auto';
                
                return clicked;
            })()
            """)
            if dismissed:
                logger.info("Dismissed and removed adblock overlay via JS evaluate.")
                await self._page.wait_for_timeout(1000)
                return True
        except Exception:
            pass

        return False

    async def is_confirm_button_visible(self) -> bool:
        """Checks whether the queue confirm button is currently visible."""
        if not self._page:
            return False
        for selector in CONFIRM_BUTTON_SELECTORS:
            try:
                elem = await self._page.query_selector(selector)
                if elem and await elem.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def is_plus_one_button_visible(self) -> bool:
        """Checks whether the '+1' extension button is currently visible on the page."""
        if not self._page or self._page.is_closed():
            return False

        # 1. Check selector matrix
        for selector in PLUS_ONE_SELECTORS + TIER1_SELECTORS + TIER4_SELECTORS:
            try:
                elem = await self._page.query_selector(selector)
                if elem and await elem.is_visible():
                    return True
            except Exception:
                continue

        # 2. Check JavaScript evaluation
        try:
            return bool(await self._page.evaluate("""
            (() => {
                const buttons = Array.from(document.querySelectorAll('button, a, .btn, #extend, [data-action="extend"]'));
                const btn = buttons.find(b => (b.textContent && (b.textContent.includes('+1') || b.textContent.includes('+ 1'))) || b.querySelector('.fa-plus, svg.fa-plus') || b.id === 'extend');
                return !!(btn && btn.offsetParent !== null);
            })()
            """))
        except Exception:
            return False

    async def get_countdown_seconds(self) -> Optional[int]:
        """Extracts and parses current countdown seconds from the page."""
        if not self._page or self._page.is_closed():
            return None

        # 1. Try dedicated countdown selectors
        for selector in COUNTDOWN_SELECTORS:
            try:
                elem = await self._page.query_selector(selector)
                if elem and await elem.is_visible():
                    text = await elem.inner_text()
                    parsed = parse_countdown_str(text)
                    if parsed is not None:
                        return parsed
            except Exception:
                continue

        # 2. Try parsing text inside status bar elements
        for selector in STATUS_LABEL_SELECTORS:
            try:
                elem = await self._page.query_selector(selector)
                if elem and await elem.is_visible():
                    text = await elem.inner_text()
                    parsed = parse_countdown_str(text)
                    if parsed is not None:
                        return parsed
            except Exception:
                continue

        # 3. JavaScript fallback scanning for any timer in the status bar
        try:
            js_timer = await self._page.evaluate("""
            (() => {
                const statusEl = document.querySelector('.statuslabel, .server-status, #statuslabel, .statuslabel-countdown');
                if (statusEl) {
                    const text = statusEl.textContent || '';
                    const match = text.match(/(\\d{1,2})\\s*:\\s*(\\d{2})/);
                    if (match) {
                        return (parseInt(match[1], 10) * 60) + parseInt(match[2], 10);
                    }
                }
                return null;
            })()
            """)
            if js_timer is not None:
                return int(js_timer)
        except Exception:
            pass

        return None

    async def get_server_status(self) -> ServerStatusSnapshot:
        """Extracts complete status snapshot from the Aternos dashboard."""
        if not self._page or self._page.is_closed():
            return ServerStatusSnapshot(status=ServerStatus.UNKNOWN, session_valid=False)

        current_url = self._page.url.lower()

        # Check if redirected to login page
        if "/go/" in current_url or "login" in current_url:
            return ServerStatusSnapshot(
                status=ServerStatus.UNKNOWN,
                session_valid=False,
                error_message="Session expired or redirected to login"
            )

        # Check for visible login form elements
        for sel in LOGIN_FORM_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    return ServerStatusSnapshot(
                        status=ServerStatus.UNKNOWN,
                        session_valid=False,
                        error_message="Login form detected on page"
                    )
            except Exception:
                pass

        # Auto-navigate from /servers/ list to specific server if needed
        if "/servers/" in current_url or current_url.endswith("/servers"):
            try:
                server_card = await self._page.query_selector(".server-body, .server, .server-selector, div.server, a[href*='/server/']")
                if server_card:
                    await server_card.click()
                    await self._page.wait_for_timeout(2000)
            except Exception:
                pass

        # Dismiss adblock modal if present
        await self.dismiss_adblock_modal()

        # Extract status text and class
        status = ServerStatus.UNKNOWN
        for sel in STATUS_LABEL_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    text = await elem.inner_text()
                    status = classify_status_text(text)
                    if status == ServerStatus.UNKNOWN:
                        class_attr = await elem.get_attribute("class") or ""
                        status = classify_status_text(class_attr)
                    if status != ServerStatus.UNKNOWN:
                        break
            except Exception:
                continue

        # Extract countdown if online
        countdown_seconds = None
        countdown_text = None
        if status == ServerStatus.ONLINE:
            countdown_seconds = await self.get_countdown_seconds()
            if countdown_seconds is not None:
                mins, secs = divmod(countdown_seconds, 60)
                countdown_text = f"{mins:02d}:{secs:02d}"

        # Extract queue position if in queue
        queue_pos = None
        queue_time = None
        if status == ServerStatus.IN_QUEUE:
            try:
                q_elem = await self._page.query_selector(".queue-position, .queue-time, [data-queue]")
                if q_elem and await q_elem.is_visible():
                    q_text = await q_elem.inner_text()
                    import re
                    digits = re.findall(r"\d+", q_text)
                    if digits:
                        queue_pos = int(digits[0])
            except Exception:
                pass

        return ServerStatusSnapshot(
            status=status,
            countdown_seconds=countdown_seconds,
            countdown_text=countdown_text,
            queue_position=queue_pos,
            queue_time=queue_time,
            session_valid=True
        )

    async def click_plus_one(self) -> ActionResult:
        """
        Executes 5-tier fallback selector click for '+1' button and verifies timer extension.
        """
        if not self._page:
            return ActionResult(success=False, message="Browser page not initialized")

        await self.dismiss_adblock_modal()
        pre_countdown = await self.get_countdown_seconds()

        clicked_tier = None

        # Tier 1: Explicit ID / Classes
        for sel in TIER1_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click(timeout=2000)
                    clicked_tier = f"Tier 1 ({sel})"
                    break
            except Exception:
                continue

        # Tier 2: Semantic Attributes / Titles
        if not clicked_tier:
            for sel in TIER2_SELECTORS:
                try:
                    elem = await self._page.query_selector(sel)
                    if elem and await elem.is_visible():
                        await elem.click(timeout=2000)
                        clicked_tier = f"Tier 2 ({sel})"
                        break
                except Exception:
                    continue

        # Tier 3: DOM Hierarchy / Sibling Locators
        if not clicked_tier:
            for sel in TIER3_SELECTORS:
                try:
                    elem = await self._page.query_selector(sel)
                    if elem and await elem.is_visible():
                        await elem.click(timeout=2000)
                        clicked_tier = f"Tier 3 ({sel})"
                        break
                except Exception:
                    continue

        # Tier 4: Text Content / Icon Locators
        if not clicked_tier:
            for sel in TIER4_SELECTORS:
                try:
                    elem = await self._page.query_selector(sel)
                    if elem and await elem.is_visible():
                        await elem.click(timeout=2000)
                        clicked_tier = f"Tier 4 ({sel})"
                        break
                except Exception:
                    continue

        # Tier 5: Direct JavaScript Execution Fallback
        if not clicked_tier:
            try:
                js_res = await self._page.evaluate(TIER5_JS_EVALUATE)
                if isinstance(js_res, dict) and js_res.get("success"):
                    clicked_tier = js_res.get("tier", "Tier 5 (JS Evaluation)")
            except Exception as e:
                logger.debug(f"Tier 5 evaluation failed: {e}")

        if not clicked_tier:
            return ActionResult(success=False, message="All 5 selector tiers failed to locate '+1' button")

        # Post-Click Verification Window (up to 3000ms polling)
        verified = False
        post_countdown = None
        for _ in range(12):  # 12 * 250ms = 3000ms
            await asyncio.sleep(0.25)
            post_countdown = await self.get_countdown_seconds()
            if post_countdown is not None and pre_countdown is not None:
                if post_countdown > pre_countdown + 20 or post_countdown >= 240:
                    verified = True
                    break
            elif post_countdown is not None and post_countdown >= 240:
                verified = True
                break

        if verified:
            return ActionResult(
                success=True,
                message=f"Successfully clicked +1 via {clicked_tier} - Timer verified ({post_countdown}s)",
                data={"tier": clicked_tier, "verified": True, "countdown": post_countdown}
            )
        else:
            return ActionResult(
                success=True,
                message=f"Clicked +1 via {clicked_tier} (Verification pending/lag)",
                data={"tier": clicked_tier, "verified": False, "countdown": post_countdown}
            )

    async def start_server(self) -> ActionResult:
        """Clicks Start button and handles EULA modal if present."""
        if not self._page:
            return ActionResult(success=False, message="Page not ready")

        await self.dismiss_adblock_modal()
        for sel in START_BUTTON_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click(timeout=3000)

                    # Check for EULA agreement modal
                    await asyncio.sleep(0.5)
                    for eula_sel in EULA_ACCEPT_SELECTORS:
                        try:
                            eula_elem = await self._page.query_selector(eula_sel)
                            if eula_elem and await eula_elem.is_visible():
                                await eula_elem.click(timeout=1000)
                        except Exception:
                            pass

                    return ActionResult(success=True, message=f"Start command executed via {sel}")
            except Exception:
                continue

        return ActionResult(success=False, message="Start button not found or not clickable")

    async def stop_server(self) -> ActionResult:
        """Clicks Stop button for graceful server shutdown."""
        if not self._page:
            return ActionResult(success=False, message="Page not ready")

        await self.dismiss_adblock_modal()
        for sel in STOP_BUTTON_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click(timeout=3000)
                    return ActionResult(success=True, message=f"Stop command executed via {sel}")
            except Exception:
                continue

        return ActionResult(success=False, message="Stop button not found or not clickable")

    async def restart_server(self) -> ActionResult:
        """Clicks Restart button."""
        if not self._page:
            return ActionResult(success=False, message="Page not ready")

        await self.dismiss_adblock_modal()
        for sel in RESTART_BUTTON_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click(timeout=3000)
                    return ActionResult(success=True, message=f"Restart command executed via {sel}")
            except Exception:
                continue

        return ActionResult(success=False, message="Restart button not found or not clickable")

    async def confirm_queue(self) -> ActionResult:
        """Clicks Confirm button during Queue stage."""
        if not self._page:
            return ActionResult(success=False, message="Page not ready")

        for sel in CONFIRM_BUTTON_SELECTORS:
            try:
                elem = await self._page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click(timeout=2000)
                    return ActionResult(success=True, message=f"Queue confirmed via {sel}")
            except Exception:
                continue

        return ActionResult(success=False, message="Confirm button not visible in queue")

    async def reload_session(self) -> bool:
        """Reloads the browser context with fresh session cookies."""
        if not self._page:
            return False
        try:
            await self._page.reload(wait_until="domcontentloaded", timeout=15000)
            await self.dismiss_adblock_modal()
            return True
        except Exception as e:
            logger.error(f"Error reloading session page: {e}")
            return False

    async def get_screenshot(self) -> bytes:
        """Captures viewport screenshot bytes."""
        if not self._page or self._page.is_closed():
            # Return minimal 1x1 PNG
            return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        try:
            return await self._page.screenshot(type="jpeg", quality=70)
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    async def take_screenshot(self) -> bytes:
        """Alias for get_screenshot."""
        return await self.get_screenshot()

    async def close(self) -> None:
        """Cleanly tears down Playwright resources."""
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._is_ready = False


# ---------------------------------------------------------------------------
# High-Fidelity In-Memory Mock Driver for Offline & Unit Testing
# ---------------------------------------------------------------------------

class MockDriver:
    """
    In-memory mock driver simulating full Aternos lifecycle, status transitions,
    countdown timer ticks, and action responses without requiring network or Chromium.
    """
    def __init__(
        self,
        initial_status: ServerStatus = ServerStatus.ONLINE,
        initial_countdown: Optional[int] = 300,
        players: int = 0,
        tick_rate: float = 1.0,
        session_valid: bool = True
    ) -> None:
        self.status = initial_status
        self.countdown = initial_countdown
        self.players = players
        self.tick_rate = tick_rate
        self.session_valid = session_valid
        self.plus_one_clicks = 0
        self.last_plus_one: Optional[datetime] = None
        self.queue_position: Optional[int] = 5 if initial_status == ServerStatus.IN_QUEUE else None
        self.queue_time: Optional[str] = "1 min" if initial_status == ServerStatus.IN_QUEUE else None
        self.is_initialized = False
        self._last_tick = time.monotonic()

    async def initialize(self) -> None:
        self.is_initialized = True

    def tick(self, seconds: int = 1) -> None:
        """Simulate time progression."""
        if self.status == ServerStatus.ONLINE and self.players == 0 and self.countdown is not None:
            self.countdown = max(0, self.countdown - seconds)
            if self.countdown == 0:
                self.status = ServerStatus.STOPPING
                self.countdown = None
        elif self.status == ServerStatus.IN_QUEUE and self.queue_position is not None:
            self.queue_position = max(0, self.queue_position - 1)
            if self.queue_position == 0:
                self.status = ServerStatus.LOADING
                self.queue_position = None
        elif self.status == ServerStatus.LOADING:
            self.status = ServerStatus.ONLINE
            self.countdown = 360
        elif self.status == ServerStatus.STOPPING:
            self.status = ServerStatus.OFFLINE
            self.countdown = None

    async def get_server_status(self) -> ServerStatusSnapshot:
        now = time.monotonic()
        elapsed = int((now - self._last_tick) * self.tick_rate)
        if elapsed >= 1:
            self.tick(elapsed)
            self._last_tick = now

        countdown_text = None
        if self.status == ServerStatus.ONLINE and self.players == 0 and self.countdown is not None:
            mins, secs = divmod(self.countdown, 60)
            countdown_text = f"{mins:02d}:{secs:02d}"

        return ServerStatusSnapshot(
            status=self.status,
            countdown_seconds=self.countdown if (self.status == ServerStatus.ONLINE and self.players == 0) else None,
            countdown_text=countdown_text,
            players_current=self.players,
            players_max=20,
            ram_usage="1.2 GB / 2.4 GB",
            queue_position=self.queue_position if self.status == ServerStatus.IN_QUEUE else None,
            queue_time=self.queue_time if self.status == ServerStatus.IN_QUEUE else None,
            session_valid=self.session_valid
        )

    async def get_countdown_seconds(self) -> Optional[int]:
        if self.status == ServerStatus.ONLINE and self.players == 0:
            return self.countdown
        return None

    async def is_plus_one_button_visible(self) -> bool:
        return self.status == ServerStatus.ONLINE and self.players == 0

    async def click_plus_one(self) -> ActionResult:
        if self.status == ServerStatus.ONLINE:
            self.plus_one_clicks += 1
            self.countdown = 360  # Reset timer to full 6 minutes
            self.last_plus_one = datetime.now(timezone.utc)
            return ActionResult(
                success=True,
                message=f"Clicked +1 button successfully (Total clicks: {self.plus_one_clicks}) - Timer extended to 360s",
                data={"new_countdown": 360, "tier": "Tier 1 (#extend)", "verified": True}
            )
        return ActionResult(success=False, message="Cannot click +1: server is not online")

    async def start_server(self) -> ActionResult:
        if self.status in (ServerStatus.OFFLINE, ServerStatus.CRASHED):
            self.status = ServerStatus.IN_QUEUE
            self.queue_position = 5
            self.queue_time = "1 min"
            return ActionResult(success=True, message="Server start command dispatched - Entered queue")
        return ActionResult(success=False, message=f"Cannot start: server is currently {self.status.value}")

    async def stop_server(self) -> ActionResult:
        if self.status in (ServerStatus.ONLINE, ServerStatus.LOADING, ServerStatus.IN_QUEUE):
            self.status = ServerStatus.STOPPING
            self.countdown = None
            return ActionResult(success=True, message="Server stop command dispatched")
        return ActionResult(success=False, message=f"Cannot stop: server is currently {self.status.value}")

    async def restart_server(self) -> ActionResult:
        self.status = ServerStatus.STOPPING
        self.countdown = None
        return ActionResult(success=True, message="Server restart command dispatched")

    async def confirm_queue(self) -> ActionResult:
        if self.status == ServerStatus.IN_QUEUE:
            self.status = ServerStatus.LOADING
            self.queue_position = None
            return ActionResult(success=True, message="Queue confirmed - Loading world")
        return ActionResult(success=False, message="Confirm button not active")

    async def is_confirm_button_visible(self) -> bool:
        return self.status == ServerStatus.IN_QUEUE and (self.queue_position is None or self.queue_position <= 1)

    async def dismiss_adblock_modal(self) -> bool:
        return True

    async def reload_session(self) -> bool:
        self.session_valid = True
        return True

    async def get_screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    async def close(self) -> None:
        self.is_initialized = False
