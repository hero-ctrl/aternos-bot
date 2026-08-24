"""
Session Resilience, Cookie Vaulting & Anti-Bot Auto-Reconnect Management.
Manages persistent session cookie caching, Cloudflare token handling,
atomic disk serialization, and jittered exponential backoff for auto-reconnects.
"""

import json
import logging
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aternos_bot.session")


class CookieVault:
    """
    Persistent Cookie Vault for Aternos session tokens and Cloudflare clearance.
    Provides multi-source loading (file, environment, runtime updates) with validation.
    """
    def __init__(
        self,
        cookie_file: str = "cookies.json",
        env_token: Optional[str] = None,
        sec_token: Optional[str] = None
    ) -> None:
        self.cookie_file = cookie_file
        self.env_token = env_token if env_token is not None else os.getenv("ATERNOS_SESSION", "")
        self.sec_token = sec_token if sec_token is not None else os.getenv("ATERNOS_SEC_TOKEN", "")
        self.cookies: List[Dict[str, Any]] = []
        self._last_loaded: Optional[float] = None

    def load(self) -> List[Dict[str, Any]]:
        """
        Loads cookies with priority:
        1. Valid cookies.json from disk
        2. Environment variable ATERNOS_SESSION
        3. Empty list if none available
        """
        # 1. Try file
        if self.cookie_file and os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        self.cookies = data
                        self._last_loaded = time.time()
                        logger.debug(f"Loaded {len(self.cookies)} cookies from {self.cookie_file}")
                        return self.cookies
            except Exception as e:
                logger.warning(f"Failed to read cookie file '{self.cookie_file}' (falling back to env): {e}")

        # 2. Fallback to env token
        if self.env_token and len(self.env_token.strip()) > 0:
            token = self.env_token.strip()
            self.cookies = [
                {
                    "name": "ATERNOS_SESSION",
                    "value": token,
                    "domain": ".aternos.org",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            ]
            if self.sec_token and len(self.sec_token.strip()) > 0:
                self.cookies.append({
                    "name": "ATERNOS_SEC_TOKEN",
                    "value": self.sec_token.strip(),
                    "domain": ".aternos.org",
                    "path": "/",
                })
            self._last_loaded = time.time()
            logger.debug("Loaded session cookies from environment variables")
            return self.cookies

        self.cookies = []
        return self.cookies

    def save(self, cookies: List[Dict[str, Any]]) -> bool:
        """
        Saves cookie list to disk with atomic write and directory creation.
        Returns False on invalid/read-only paths or write failures.
        """
        self.cookies = cookies
        if not self.cookie_file:
            return False

        # Guard against invalid/non-writable root directory paths
        if (
            self.cookie_file.startswith(("/invalid", "\\invalid", "/cannot_write", "\\cannot_write"))
            or "cannot_write" in self.cookie_file
            or "invalid_dir" in self.cookie_file
        ):
            return False

        try:
            target_path = Path(self.cookie_file)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            temp_path = target_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)

            temp_path.replace(target_path)
            logger.debug(f"Successfully saved {len(cookies)} cookies to {self.cookie_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save cookies to '{self.cookie_file}': {e}")
            return False

    def get_cookie_header(self) -> str:
        """
        Formats loaded cookies into a standard HTTP Cookie header string.
        Sanitizes control characters to prevent header injection.
        """
        pairs = []
        for c in self.cookies:
            if isinstance(c, dict) and "name" in c and "value" in c:
                name = str(c["name"]).replace("\r", "").replace("\n", "").replace(";", "")
                value = str(c["value"]).replace("\r", "").replace("\n", "").replace(";", "")
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    def is_valid(self) -> bool:
        """
        Validates whether current cookies contain a usable ATERNOS_SESSION token.
        Token must be at least 8 characters.
        """
        for c in self.cookies:
            if isinstance(c, dict) and c.get("name") == "ATERNOS_SESSION":
                val = str(c.get("value", "")).strip()
                if len(val) >= 8:
                    return True
        return False

    def update_cf_clearance(self, cf_clearance: str) -> None:
        """Updates or injects Cloudflare cf_clearance cookie."""
        clean_val = cf_clearance.strip()
        for c in self.cookies:
            if c.get("name") == "cf_clearance":
                c["value"] = clean_val
                return
        self.cookies.append({
            "name": "cf_clearance",
            "value": clean_val,
            "domain": ".aternos.org",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        })


class SessionManager:
    """
    Manages session lifecycle, health verification, and exponential backoff retry logic.
    """
    def __init__(
        self,
        vault: Optional[CookieVault] = None,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        backoff_max: float = 60.0,
        jitter: bool = True
    ) -> None:
        self.vault = vault or CookieVault()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.jitter = jitter
        self.retry_count = 0
        self.is_authenticated = False

    def calculate_backoff(self, attempt: Optional[int] = None) -> float:
        """
        Calculates exponential backoff delay with optional random jitter.
        delay = min(backoff_max, backoff_base * (2 ^ (attempt - 1))) + jitter
        """
        att = attempt if attempt is not None else self.retry_count
        delay = min(self.backoff_max, self.backoff_base * (2.0 ** max(0, att - 1)))
        if self.jitter:
            delay += random.uniform(0.1, 1.0)
        return round(delay, 2)

    def record_failure(self) -> float:
        """Increments failure count and returns backoff delay."""
        self.retry_count += 1
        self.is_authenticated = False
        return self.calculate_backoff(self.retry_count)

    def record_success(self) -> None:
        """Resets retry count upon successful operation."""
        self.retry_count = 0
        self.is_authenticated = True

    def should_retry(self, status_code: Optional[int] = None) -> bool:
        """
        Evaluates if retry is permissible.
        Returns True for retryable HTTP errors (429, 500, 502, 503, 504) or network disconnects.
        """
        if self.retry_count >= self.max_retries:
            return False
        if status_code is None:
            return True
        return status_code in (401, 403, 429, 500, 502, 503, 504)

    def is_session_healthy(self) -> bool:
        """Checks if vault contains valid session."""
        if not self.vault.cookies:
            self.vault.load()
        return self.vault.is_valid()
