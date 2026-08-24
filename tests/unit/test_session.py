"""
Unit tests for Session Cookie Vault & Persistence.
Tests cookie extraction, environment ingestion, JSON file serialization,
Playwright cookie formatting, and error resilience.
"""

import json
import os
import tempfile
from typing import Any, Dict, List, Optional
import pytest

from src.bot.session import CookieVault, SessionManager


def test_load_from_environment_token():
    """Verify cookie vault populates Playwright formatted cookie from env token."""
    vault = CookieVault(cookie_file="non_existent.json", env_token="session_token_xyz12345")
    cookies = vault.load()
    assert len(cookies) == 1
    assert cookies[0]["name"] == "ATERNOS_SESSION"
    assert cookies[0]["value"] == "session_token_xyz12345"
    assert cookies[0]["domain"] == ".aternos.org"
    assert vault.is_valid() is True


def test_save_and_load_from_json_file(tmp_path):
    """Verify cookies can be saved to disk as JSON and reloaded cleanly."""
    cookie_file = str(tmp_path / "test_cookies.json")
    vault = CookieVault(cookie_file=cookie_file, env_token="")

    sample_cookies = [
        {"name": "ATERNOS_SESSION", "value": "token_from_file_789", "domain": ".aternos.org", "path": "/"},
        {"name": "cf_clearance", "value": "cf_token_val_456", "domain": ".aternos.org", "path": "/"},
    ]

    saved = vault.save(sample_cookies)
    assert saved is True
    assert os.path.exists(cookie_file)

    # Reload in new vault instance
    new_vault = CookieVault(cookie_file=cookie_file, env_token="")
    loaded = new_vault.load()
    assert len(loaded) == 2
    assert loaded[0]["name"] == "ATERNOS_SESSION"
    assert loaded[1]["name"] == "cf_clearance"
    assert new_vault.is_valid() is True


def test_cookie_header_string_generation():
    """Verify get_cookie_header produces standard HTTP Cookie header formatting."""
    vault = CookieVault(cookie_file="non_existent.json", env_token="")
    vault.cookies = [
        {"name": "ATERNOS_SESSION", "value": "session123"},
        {"name": "cf_clearance", "value": "cf456"},
    ]
    header = vault.get_cookie_header()
    assert "ATERNOS_SESSION=session123" in header
    assert "cf_clearance=cf456" in header
    assert "; " in header


def test_corrupted_json_file_fallback(tmp_path):
    """Verify corrupted JSON file does not crash the vault and falls back to env token."""
    corrupted_file = str(tmp_path / "corrupt_cookies.json")
    with open(corrupted_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json file [")

    vault = CookieVault(cookie_file=corrupted_file, env_token="fallback_env_token_abc123")
    cookies = vault.load()
    assert len(cookies) == 1
    assert cookies[0]["value"] == "fallback_env_token_abc123"
    assert vault.is_valid() is True


def test_empty_or_too_short_token_is_invalid():
    """Verify empty or trivially short tokens fail validation."""
    vault_empty = CookieVault(cookie_file="non_existent.json", env_token="")
    vault_empty.load()
    assert vault_empty.is_valid() is False

    vault_short = CookieVault(cookie_file="non_existent.json", env_token="short")
    vault_short.load()
    assert vault_short.is_valid() is False


def test_session_manager_backoff_and_retry():
    """Verify SessionManager exponential backoff calculations and retry decisions."""
    vault = CookieVault(env_token="test_token_12345678")
    sm = SessionManager(vault=vault, max_retries=3, backoff_base=2.0, backoff_max=20.0, jitter=False)

    assert sm.is_session_healthy() is True
    assert sm.calculate_backoff(1) == 2.0
    assert sm.calculate_backoff(2) == 4.0
    assert sm.calculate_backoff(3) == 8.0
    assert sm.calculate_backoff(5) == 20.0  # Clamped to max

    # Failure recording
    delay = sm.record_failure()
    assert sm.retry_count == 1
    assert delay >= 2.0
    assert sm.should_retry(502) is True
    assert sm.should_retry(200) is False

    sm.record_failure()
    sm.record_failure()
    assert sm.should_retry(502) is False  # Max retries exhausted

    # Success resets retry count
    sm.record_success()
    assert sm.retry_count == 0
    assert sm.is_authenticated is True


def test_update_cf_clearance():
    """Verify updating Cloudflare clearance token in CookieVault."""
    vault = CookieVault(env_token="test_token_12345678")
    vault.load()
    vault.update_cf_clearance("cf_sample_token_999")
    header = vault.get_cookie_header()
    assert "cf_clearance=cf_sample_token_999" in header
