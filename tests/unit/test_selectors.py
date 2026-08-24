"""
Unit tests for Aternos DOM Selectors and Countdown Timer Parser.
Tests 5-tier fallback selector hierarchy, countdown string parsing edge cases,
and DOM element query helpers.
"""

import pytest
from tests.conftest import (
    PLUS_ONE_SELECTORS,
    STATUS_LABEL_SELECTORS,
    COUNTDOWN_SELECTORS,
    START_BUTTON_SELECTORS,
    STOP_BUTTON_SELECTORS,
    CONFIRM_BUTTON_SELECTORS,
    parse_countdown_str,
    MockPlaywrightPage,
)


def test_plus_one_selectors_hierarchy_completeness():
    """Verify 5-tier fallback selectors for the +1 button are present and ordered."""
    assert len(PLUS_ONE_SELECTORS) >= 5
    assert "#extend" in PLUS_ONE_SELECTORS[0]
    assert any("btn-extend" in sel for sel in PLUS_ONE_SELECTORS)
    assert any("Extend" in sel for sel in PLUS_ONE_SELECTORS)
    assert any("+1" in sel for sel in PLUS_ONE_SELECTORS)
    assert any("status-action" in sel or "countdown-extend" in sel for sel in PLUS_ONE_SELECTORS)


def test_parse_countdown_standard_formats():
    """Verify standard mm:ss format strings are parsed correctly into total seconds."""
    assert parse_countdown_str("03:45") == 225
    assert parse_countdown_str("05:00") == 300
    assert parse_countdown_str("01:30") == 90
    assert parse_countdown_str("00:45") == 45
    assert parse_countdown_str("00:01") == 1
    assert parse_countdown_str("00:00") == 0


def test_parse_countdown_single_digit_minutes():
    """Verify single digit m:ss formats (e.g. 3:45 or 0:37) parse correctly."""
    assert parse_countdown_str("3:45") == 225
    assert parse_countdown_str("0:37") == 37
    assert parse_countdown_str("1:05") == 65
    assert parse_countdown_str("0:00") == 0


def test_parse_countdown_boundary_values():
    """Verify boundary values such as 59:59 (3599s) and single seconds."""
    assert parse_countdown_str("59:59") == 3599
    assert parse_countdown_str("10:00") == 600
    assert parse_countdown_str("45") == 45  # Raw second string fallback
    assert parse_countdown_str("360") == 360


def test_parse_countdown_whitespace_handling():
    """Verify leading, trailing, and newline whitespace is stripped gracefully."""
    assert parse_countdown_str("  02:30  ") == 150
    assert parse_countdown_str("\n04:12\t") == 252
    assert parse_countdown_str(" \t 0:15 \n") == 15


def test_parse_countdown_invalid_and_malformed():
    """Verify malformed, non-numeric, or out-of-range strings return None."""
    assert parse_countdown_str(None) is None
    assert parse_countdown_str("") is None
    assert parse_countdown_str("   ") is None
    assert parse_countdown_str("invalid_text") is None
    assert parse_countdown_str("02:65") is None  # seconds >= 60 invalid
    assert parse_countdown_str("-01:30") is None  # negative minute invalid
    assert parse_countdown_str("01:-10") is None  # negative second invalid
    assert parse_countdown_str("01:20:30") is None  # triple colon invalid
    assert parse_countdown_str("NaN:NaN") is None


@pytest.mark.asyncio
async def test_selector_resolution_with_mock_page():
    """Verify mock page resolves selectors across tiers."""
    page = MockPlaywrightPage()
    # Tier 1 missing, Tier 2 present
    page.set_element("button.btn-extend", "+1", visible=True)

    found_elem = None
    for sel in PLUS_ONE_SELECTORS:
        elem = await page.query_selector(sel)
        if elem and await elem.is_visible():
            found_elem = elem
            break

    assert found_elem is not None
    assert found_elem.selector == "button.btn-extend"
    assert await found_elem.text_content() == "+1"
