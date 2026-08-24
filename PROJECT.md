# Project: Aternos 24/7 Keep-Alive Automation & Web Dashboard

## Architecture
The system is built on **Python 3.11+ / FastAPI / Async Playwright / Asyncio / Tailwind CSS** for ultra-lightweight, memory-efficient (<250MB RAM in Docker), 24/7 continuous operation on free cloud platforms (Render, Fly.io, Railway, Koyeb, Linux VPS).

```
+-------------------------------------------------------------------------+
|                              FastAPI Server                             |
|  +---------------------------+  +------------------------------------+  |
|  | Web Dashboard (HTML/JS)   |  | REST API & SSE / WebSocket Hub     |  |
|  | - Status Badge & Timer    |  | - /api/status, /api/action/*       |  |
|  | - Live Log Console (SSE)  |  | - /api/events (SSE) / /ws (WS)     |  |
|  | - Controls (Start/Stop/+1)|  | - /api/logs, /api/screenshot       |  |
|  +---------------------------+  +------------------------------------+  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                         Keep-Alive Engine                               |
|  - Continuous Status Polling & State Machine (Offline/Queue/Online)     |
|  - Countdown Timer Monitoring (mm:ss) & Dynamic Reset Threshold (<180s) |
|  - Exact "+1" Button Trigger Engine with 5-Tier Fallback Selectors      |
|  - Event Dispatcher & Real-Time Log Broadcaster                         |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|             Browser Controller (Playwright Stealth / Mock)              |
|  - Playwright Async Driver with Resource Route Abort (AdBlock/RAM opt)  |
|  - Anti-Bot Stealth Masking (navigator.webdriver, plugins, WebGL)       |
|  - Session Cookie Vault (ATERNOS_SESSION, cf_clearance, auto-reconnect) |
|  - Deterministic Mock Driver & Mock Aternos Server (for offline CI/test)|
+-------------------------------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Status Bar State Monitoring | Real-time detection of Aternos status (Offline, In Queue, Starting, Online, Stopping, Crashed) | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Countdown Timer Parser | Robust parser extracting integer remaining seconds from `mm:ss` or `m:ss` in `.countdown` | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Exact `+1` Button Clicker | 5-tier fallback selector engine locating and clicking the status bar `+1` extension button | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Keep-Alive Monitoring Loop | Async loop monitoring countdown, firing `+1` click when `<= 180s` and emergency retry `<= 30s` | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Server Lifecycle Controls | Programmatic triggers to Start, Confirm Queue (`#confirm`), Stop, and Restart server | M1 | ORIGINAL_REQUEST §R1 |
| 6 | REST Control & Status API | REST endpoints (`/api/status`, `/api/action/*`, `/api/logs`, `/api/health`, `/api/screenshot`) | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Real-Time Log & Event Streaming | Dual SSE (`/api/events`) and WebSocket (`/ws`) real-time broadcasting to client browsers | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Responsive Web Dashboard UI | Modern dark-mode UI with status badge, animated countdown ring, metrics, and controls | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Live Terminal Log Console | Web log viewer with auto-scroll lock, search/severity filters, pause, and export | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Session Cookie Persistence | Multi-source cookie vault (`ATERNOS_SESSION`, `cookies.json`, env) bypassing Cloudflare login | M3 | ORIGINAL_REQUEST §R4 |
| 11 | Anti-Bot Stealth Evasion | Playwright stealth masks (`navigator.webdriver`, plugins, platform, WebGL) and ad blocker | M3 | ORIGINAL_REQUEST §R4 |
| 12 | Auto-Reconnect & Resilience | Jittered exponential backoff auto-reconnect on session drop, 502/503, or network outage | M3 | ORIGINAL_REQUEST §R4 |
| 13 | Deterministic Mock Aternos Mode | Full offline mock server/driver simulating login, dashboard, timer, and `+1` AJAX responses | M3 | ORIGINAL_REQUEST §R4 |
| 14 | Multi-Stage Docker Packaging | Optimized Dockerfile with `dumb-init`, non-root user, Chromium deps, and `<250MB` RAM footprint | M4 | ORIGINAL_REQUEST §R3 |
| 15 | Cloud Deployment Manifests | Ready configurations for Render, Fly.io, Railway, Koyeb, and Linux VPS with anti-sleep ping | M4 | ORIGINAL_REQUEST §R3 |
| 16 | Comprehensive README & Config | Detailed documentation, `.env.example`, architecture diagrams, and quickstart guide | M4 | ORIGINAL_REQUEST §R3 |
| 17 | 100% E2E Test Suite Pass | Passing 100% of Tiers 1-4 tests and adversarial hardening (Tier 5) | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Automation & Exact `+1` Button Engine | `bot/driver.py`, `bot/engine.py`, `bot/selectors.py`, `core/config.py`, `core/schemas.py` | none | DONE |
| M2 | Web Dashboard & Real-Time Streaming | `web/app.py`, `web/routes.py`, `web/static/` (HTML/CSS/JS), `core/logger.py` | M1 | DONE |
| M3 | Anti-Bot Stealth, Resilience & Mock Server | `bot/session.py`, `bot/mock_server.py`, cookie vaulting, auto-reconnect, offline mock mode | M1 | DONE |
| M4 | Docker Containerization, Cloud Ready & Docs | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `fly.toml`, `railway.json`, `koyeb.yaml`, `.env.example`, `README.md` | M2, M3 | DONE |
| M5 | 100% E2E Test Pass & Adversarial Hardening | Verification against all E2E test tiers (Tiers 1-5) until 100% pass (339/339 passing) | M1, M2, M3, M4 | DONE |

## Interface Contracts

### `core/schemas.py`
```python
class ServerStatus(str, Enum):
    OFFLINE = "offline"
    IN_QUEUE = "in_queue"
    LOADING = "loading"
    ONLINE = "online"
    STOPPING = "stopping"
    CRASHED = "crashed"
    UNKNOWN = "unknown"

class ServerState(BaseModel):
    status: ServerStatus = ServerStatus.OFFLINE
    countdown_seconds: Optional[int] = None
    countdown_text: Optional[str] = None
    last_plus_one_click: Optional[datetime] = None
    plus_one_click_count: int = 0
    queue_position: Optional[int] = None
    queue_time: Optional[str] = None
    is_keepalive_active: bool = True
    session_valid: bool = True
    last_updated: datetime = Field(default_factory=datetime.utcnow)

class LogEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: str = "INFO" # INFO, SUCCESS, WARN, ERROR, PLUS_ONE
    message: str
    data: Optional[Dict[str, Any]] = None
```

### `bot/engine.py` ↔ `web/app.py`
- `engine.get_state() -> ServerState`
- `engine.toggle_keepalive(enabled: Optional[bool] = None) -> bool`
- `engine.trigger_plus_one() -> bool`
- `engine.start_server() -> bool`
- `engine.stop_server() -> bool`
- `engine.reload_session() -> bool`
- `engine.get_screenshot() -> bytes`
- `log_broadcaster.subscribe() -> AsyncGenerator[LogEvent, None]`

## Code Layout
```
c:/Users/Visastore/Documents/antigravity/focused-curie/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── README.md
├── render.yaml
├── fly.toml
├── railway.json
├── koyeb.yaml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── schemas.py
│   │   └── logger.py
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── selectors.py
│   │   ├── session.py
│   │   ├── driver.py
│   │   ├── engine.py
│   │   └── mock_server.py
│   └── web/
│       ├── __init__.py
│       ├── app.py
│       ├── routes.py
│       └── static/
│           ├── index.html
│           ├── app.js
│           └── style.css
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   ├── test_config.py
    │   ├── test_schemas.py
    │   ├── test_selectors.py
    │   ├── test_session.py
    │   └── test_logger.py
    ├── integration/
    │   ├── test_engine_mock.py
    │   ├── test_api_routes.py
    │   └── test_websocket_sse.py
    └── e2e/
        ├── test_tier1_features.py
        ├── test_tier2_boundaries.py
        ├── test_tier3_combinations.py
        ├── test_tier4_scenarios.py
        └── test_tier5_adversarial.py
```
