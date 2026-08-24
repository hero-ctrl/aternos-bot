"""
Aternos DOM Selectors Matrix & Countdown Timer Parser.
Defines 5-tier fallback selector matrix for exact +1 button, status bar elements,
action controls, and robust countdown parsing.
"""

import re
from typing import Optional
from src.core.schemas import ServerStatus

# ---------------------------------------------------------------------------
# 5-Tier Fallback Selector Matrix for Exact "+1" Button
# ---------------------------------------------------------------------------

TIER1_SELECTORS = [
    "button:has(i.fa-plus)",
    "button:has(.fa-plus)",
    "button:has(svg.fa-plus)",
    "button:has-text('+1')",
    ".statuslabel-countdown button",
    ".server-status button:has-text('+1')",
    "#extend",
    "#extend-timer",
    "button.btn-extend",
    "#extend-btn",
    ".btn-extend-timer",
    "button#extend-timer",
    "button#extend",
]

TIER2_SELECTORS = [
    'button[data-action="extend"]',
    'button[data-action="extend-timer"]',
    'button[title*="Extend"]',
    'button[title*="extend"]',
    'button[aria-label*="Extend"]',
    'button[aria-label*="extend"]',
    'a[title*="Extend"]',
    "//button[contains(., '+1') or contains(text(), '+1')]",
]

TIER3_SELECTORS = [
    ".statuslabel-countdown button",
    ".server-status-countdown button",
    ".countdown + button",
    ".countdown ~ button",
    ".countdown-wrapper button",
    ".statuslabel-countdown .btn",
    ".status-action-extend",
    ".countdown-extend",
]

TIER4_SELECTORS = [
    'button:has-text("+1")',
    "//button[contains(text(), '+1') or contains(., '+1')]",
    'a:has-text("+1")',
    'button:has-text("+ 1")',
    'button:has(i.fa-plus)',
    'button:has(.fa-plus)',
    'button:has(svg.fa-plus)',
    '.server-status button:has-text("+1")',
]

TIER5_JS_EVALUATE = """
(() => {
    const isVisible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
    };

    // 1. Direct ID/class query
    const directSelectors = '#extend, #extend-timer, button.btn-extend, #extend-btn, [data-action="extend"], button[title*="Extend"], button[title*="extend"], .statuslabel-countdown button, .countdown-wrapper button, .btn-extend-timer';
    let btn = document.querySelector(directSelectors);
    if (btn && isVisible(btn)) {
        btn.click();
        return { success: true, tier: 'Tier 5 (JS querySelector)' };
    }
    
    // 2. Buttons inside status bar
    const statusContainer = document.querySelector('.statuslabel, .server-status, #statuslabel, .statuslabel-countdown');
    if (statusContainer) {
        const btns = Array.from(statusContainer.querySelectorAll('button, a, .btn, div[role="button"]'));
        for (const b of btns) {
            const txt = (b.textContent || '').trim();
            if (txt.includes('+1') || txt.includes('+ 1') || txt.includes('+') || b.querySelector('.fa-plus, svg, i') || isVisible(b)) {
                b.click();
                return { success: true, tier: 'Tier 5 (JS status bar button)' };
            }
        }
    }
    
    // 3. Scan all buttons on page for text "+1" or plus icon
    const buttons = Array.from(document.querySelectorAll('button, a.btn, .btn, [role="button"]'));
    btn = buttons.find(b => {
        const text = (b.textContent || '').trim();
        return (text.includes('+1') || text.includes('+ 1') || text.includes('1+') || b.querySelector('.fa-plus, svg.fa-plus, [class*="plus"]')) && isVisible(b);
    });
    if (btn) {
        btn.click();
        return { success: true, tier: 'Tier 5 (JS global button scan)' };
    }
    
    return { success: false, error: 'Button not found in DOM' };
})()
"""

# Ordered composite list for sequential fallback resolution
PLUS_ONE_SELECTORS = [
    "#extend",
    "button.btn-extend",
    "button[title*='Extend']",
    "//button[contains(text(), '+1') or contains(., '+1')]",
    ".status-action-extend",
    ".countdown-extend",
    "#extend-timer",
    "#extend-btn",
    ".btn-extend-timer",
    'button[data-action="extend"]',
    ".statuslabel-countdown button",
    'button:has-text("+1")',
]

# ---------------------------------------------------------------------------
# Server Status, Timer & Action Controls
# ---------------------------------------------------------------------------

STATUS_LABEL_SELECTORS = [
    ".statuslabel-label",
    ".server-status",
    "#statuslabel",
    "[data-status]",
    ".statuslabel",
    ".status-label",
]

COUNTDOWN_SELECTORS = [
    ".countdown",
    ".statuslabel-countdown",
    "#countdown",
    ".server-countdown",
    ".countdown-time",
    "span.countdown",
    "[data-countdown]",
    ".countdown-wrapper",
]

START_BUTTON_SELECTORS = [
    "#start",
    ".btn-start",
    "button[title*='Start']",
    "[data-action='start']",
    ".server-actions .btn-success",
    "button#start",
    "button:has-text('بدء تشغيل')",
    "button:has-text('بدء')",
    "button:has-text('Start')",
]

STOP_BUTTON_SELECTORS = [
    "#stop",
    ".btn-stop",
    "button[title*='Stop']",
    "[data-action='stop']",
    ".server-actions .btn-danger",
    "button#stop",
    "button:has-text('إيقاف')",
    "button:has-text('ايقاف')",
    "button:has-text('Stop')",
]

CONFIRM_BUTTON_SELECTORS = [
    "#confirm",
    ".btn-confirm",
    "button[title*='Confirm']",
    "[data-action='confirm']",
    "a.btn-confirm",
    "button#confirm",
    "button:has-text('تأكيد')",
    "button:has-text('Confirm')",
]

RESTART_BUTTON_SELECTORS = [
    "#restart",
    ".btn-restart",
    "button[title*='Restart']",
    "[data-action='restart']",
    "button#restart",
    "button:has-text('إعادة تشغيل')",
    "button:has-text('اعادة تشغيل')",
]

EULA_ACCEPT_SELECTORS = [
    "#eula-accept",
    "button.btn-agree",
    ".modal-eula .btn-primary",
    "button[data-action='eula-accept']",
    "button:has-text('Accept')",
    "button:has-text('موافق')",
]

ADBLOCK_DISMISS_SELECTORS = [
    ".btn-continue-adblock",
    "button.btn-continue-adblock",
    "a.btn-continue-adblock",
    "div.btn-continue-adblock",
    "button:has-text('المتابعة مع مانع الإعلانات على أي حال')",
    "a:has-text('المتابعة مع مانع الإعلانات على أي حال')",
    "button:has-text('المتابعة مع مانع الإعلانات')",
    "a:has-text('المتابعة مع مانع الإعلانات')",
    "button:has-text('Continue with adblocker anyway')",
    "a:has-text('Continue with adblocker anyway')",
    "button:has-text('Continue with adblocker')",
    "a:has-text('Continue with adblocker')",
    "button:has-text('Continue anyway')",
    "a:has-text('Continue anyway')",
    "button:has-text('المتابعة')",
    "a:has-text('المتابعة')",
    ".modal-adblock .btn-secondary",
    "[data-dismiss='modal']",
    ".adblock-warning .close",
    ".adblock-warning button",
    ".adblock-warning a",
    "#adblock-warning button",
    "#adblock-warning a",
    ".adblock button",
    ".adblock a",
]

LOGIN_FORM_SELECTORS = [
    "#login-form",
    "input[name='user']",
    ".login-button",
    "form[action*='login']",
    ".user-login",
]


# ---------------------------------------------------------------------------
# Status Classification Helpers
# ---------------------------------------------------------------------------

def classify_status_text(text: Optional[str]) -> ServerStatus:
    """Classifies raw text / class name into ServerStatus enum."""
    if not text:
        return ServerStatus.UNKNOWN
    clean = text.strip().lower()

    if "offline" in clean or "غير متصل" in clean:
        return ServerStatus.OFFLINE
    if "queue" in clean or "waiting" in clean or "طابور" in clean or "انتظار" in clean:
        return ServerStatus.IN_QUEUE
    if "loading" in clean or "starting" in clean or "preparing" in clean or "تحميل" in clean or "تشغيل" in clean or "بدء" in clean or "جاري التشغيل" in clean:
        return ServerStatus.LOADING
    if "online" in clean or "متصل" in clean:
        return ServerStatus.ONLINE
    if "stopping" in clean or "saving" in clean or "إيقاف" in clean or "ايقاف" in clean or "جاري الإيقاف" in clean:
        return ServerStatus.STOPPING
    if "crashed" in clean or "crash" in clean or "معطل" in clean or "توقف" in clean:
        return ServerStatus.CRASHED

    return ServerStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Countdown Parser
# ---------------------------------------------------------------------------

def parse_countdown_str(text: Optional[str]) -> Optional[int]:
    """
    Parse mm:ss or m:ss countdown text to total integer seconds.
    Supports Arabic-Indic digits (٠-٩) and embedded timer strings.
    """
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None

    # Normalize Arabic digits (٠١٢٣٤٥٦٧٨٩ -> 0123456789)
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    for i, d in enumerate(arabic_digits):
        cleaned = cleaned.replace(d, str(i))

    # Try regex match for mm:ss anywhere in the string (e.g., "0:37", "00:37", "الوقت 0:37")
    match = re.search(r'(\d{1,2})\s*:\s*(\d{2})', cleaned)
    if match:
        try:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if 0 <= minutes <= 120 and 0 <= seconds < 60:
                return (minutes * 60) + seconds
        except ValueError:
            pass

    # Match raw seconds e.g. "45s", "360"
    s_match = re.search(r'\b(\d+)\s*(?:s|sec|seconds)?\b', cleaned, re.IGNORECASE)
    if s_match:
        try:
            sec = int(s_match.group(1))
            if 0 <= sec <= 7200:
                return sec
        except ValueError:
            pass

    return None


def parse_countdown_text(text: Optional[str]) -> Optional[int]:
    """Alias for parse_countdown_str."""
    return parse_countdown_str(text)
