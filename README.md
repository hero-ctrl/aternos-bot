# ⚡ Aternos 24/7 Keep-Alive Automation & Web Dashboard

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-Async%20Stealth-45ba4b.svg)](https://playwright.dev/)
[![Docker Ready](https://img.shields.io/badge/Docker-Multi--Stage%20<250MB-2496ed.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An enterprise-grade, lightweight, fully containerized **24/7 Aternos Minecraft server keep-alive automation bot** and **real-time web dashboard**. Automatically detects and clicks the exact `+1` countdown extension button on the server status bar, handles queue progression, bypasses anti-bot/Cloudflare challenges, and streams real-time status and logs to any desktop or mobile browser.

---

## 🌟 Key Features

- 🎯 **Exact `+1` Countdown Button Engine**: Locates and triggers the exact `+1` button next to the idle countdown timer using a 5-tier fallback selector matrix (IDs, semantic attributes, DOM hierarchy, text locators, and direct JS evaluate).
- 🔄 **Dual-Threshold Keep-Alive Loop**: Intelligently polls timer values, firing automated extension at standard threshold (`≤ 180s`) with fast-recovery emergency trigger (`≤ 30s`).
- 🛡️ **Anti-Bot Stealth & Resilience**: Masks `navigator.webdriver`, plugins, platform signatures, and WebGL context. Features persistent cookie vaulting (`ATERNOS_SESSION`, `cf_clearance`) and auto-reconnect with exponential backoff.
- 📊 **Modern Web Dashboard**: Real-time server status badge, animated countdown circular gauge, live connected player counts, and manual server controls (Start, Stop, Extend, Confirm Queue, Toggle Keep-Alive).
- ⚡ **Dual SSE & WebSocket Log Streaming**: Real-time terminal log viewer with level filtering (INFO, WARN, SUCCESS, PLUS_ONE), search queries, auto-scroll lock, and JSON log export.
- 🐳 **Cloud-Optimized Docker Architecture**: Ultra-lean multi-stage container with `dumb-init`, non-root user `appuser`, and adblock route interception resulting in `<250MB RAM` consumption.
- 🚀 **One-Click Cloud Deployment**: Ready-to-deploy configuration manifests for **Render**, **Fly.io**, **Railway**, **Koyeb**, and **Linux VPS (systemd)**.
- 🧪 **Deterministic Mock Mode**: Offline mock simulation engine and ASGI server for testing without live Aternos credentials.

---

## 🏗️ Architecture Overview

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

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+ (or Docker)
- Aternos Account & Server (`https://aternos.org/server/`)

### 2. Extracting Aternos Session Cookie
1. Open your browser and log in to [Aternos](https://aternos.org/server/).
2. Open Developer Tools (`F12` or `Ctrl+Shift+I`) and go to the **Application / Storage** tab.
3. Under **Cookies** -> `https://aternos.org`, copy the value of `ATERNOS_SESSION`.

---

### Option A: Run with Docker (Recommended)

```bash
# Clone repository
git clone https://github.com/your-repo/aternos-247-bot.git
cd aternos-247-bot

# Copy environment template and fill in your session cookie
cp .env.example .env
# Edit .env and set ATERNOS_SESSION=your_cookie_here

# Build and run container
docker build -t aternos-bot .
docker run -d --name aternos-bot -p 8000:8000 --env-file .env aternos-bot
```

Open `http://localhost:8000` in your browser to access the dashboard.

---

### Option B: Run with Docker Compose

```bash
# Start container with volume persistence
docker compose up -d

# View real-time container logs
docker compose logs -f
```

---

### Option C: Run Locally with Python

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser binary
playwright install chromium

# Run server
python -m src.main
```

---

## 🌐 24/7 Cloud Deployment Guides (Free Tier Ready)

### 1. Render.com
1. Fork or push this repository to GitHub.
2. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New +** -> **Blueprint**.
3. Connect your repository. Render automatically reads `render.yaml`.
4. In Environment Settings, provide your `ATERNOS_SESSION` token.
5. Click **Apply**. Render will build and deploy the Docker container with healthcheck monitoring.

### 2. Fly.io
```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Authenticate with Fly
fly auth login

# Launch application (uses fly.toml)
fly launch --no-deploy

# Set secret cookie token
fly secrets set ATERNOS_SESSION="your_cookie_token_here"

# Deploy
fly deploy
```

### 3. Railway.app
1. Create a new project on [Railway](https://railway.app/).
2. Select **Deploy from GitHub repo**. Railway automatically detects `Dockerfile` and `railway.json`.
3. Under **Variables**, add `ATERNOS_SESSION` and `PORT=8000`.
4. Generate a public domain under service settings to access your web dashboard.

### 4. Koyeb
1. Create a new App on [Koyeb](https://www.koyeb.com/).
2. Choose **GitHub** as deployment method and select Dockerfile builder.
3. Configure environment variable `ATERNOS_SESSION`.
4. Set port to `8000` and healthcheck path to `/api/health`.

### 5. Linux VPS (Ubuntu / Debian / systemd)
```bash
# Clone to /opt
sudo git clone https://github.com/your-repo/aternos-247-bot.git /opt/aternos-bot
cd /opt/aternos-bot

# Set up user and permissions
sudo useradd -r -s /bin/false aternos
sudo chown -R aternos:aternos /opt/aternos-bot

# Set up Python environment
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/playwright install chromium
sudo ./venv/bin/playwright install-deps chromium

# Configure systemd service
sudo cp aternos-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aternos-bot

# Check service status
sudo systemctl status aternos-bot
```

---

## ⚙️ Configuration Reference

All settings can be configured via environment variables or `.env` file:

| Variable | Type | Default | Description |
|---|---|---|---|
| `ATERNOS_SESSION` | string | `""` | **Required**: Aternos session authentication cookie |
| `ATERNOS_SEC_TOKEN` | string | `""` | Optional secondary security token |
| `ATERNOS_SERVER_ID` | string | `""` | Specific Aternos server ID if managing multiple servers |
| `HOST` | string | `0.0.0.0` | Bind host for FastAPI web server |
| `PORT` | integer | `8000` | Bind port for dashboard and REST API |
| `CHECK_INTERVAL` | float | `5.0` | Seconds between keepalive polling loops |
| `COUNTDOWN_THRESHOLD` | integer | `180` | Countdown seconds remaining to trigger `+1` click |
| `EMERGENCY_THRESHOLD` | integer | `30` | Emergency countdown threshold in seconds |
| `HEADLESS` | boolean | `true` | Run Playwright Chromium in headless mode |
| `MOCK_MODE` | boolean | `false` | Run in offline deterministic mock simulation mode |
| `AUTO_CONFIRM_QUEUE` | boolean | `true` | Automatically confirm queue dialog prompts |
| `AUTO_START_ON_OFFLINE` | boolean | `false` | Automatically trigger server start when offline |
| `LOG_LEVEL` | string | `INFO` | Log severity level (`DEBUG`, `INFO`, `WARN`, `ERROR`) |
| `COOKIE_FILE_PATH` | string | `data/cookies.json` | Persistent cookie cache location |

---

## 📡 REST API & Streaming Endpoints

### REST API Endpoints

- `GET /api/status` — Returns current server status, countdown seconds, player count, and session validity.
- `GET /api/health` — Health check endpoint for Docker, Render, and Kubernetes probes.
- `GET /api/logs?level=PLUS_ONE&limit=50&search=keyword` — Query recent log history with filtering.
- `GET /api/screenshot` — Returns live JPEG screenshot of the browser viewport.
- `POST /api/action/extend` — Manually trigger exact `+1` button click.
- `POST /api/action/start` — Trigger server boot / queue entry.
- `POST /api/action/stop` — Trigger graceful server shutdown.
- `POST /api/action/restart` — Trigger server restart.
- `POST /api/action/confirm-queue` — Confirm server queue slot.
- `POST /api/action/toggle-keepalive?enabled=true` — Enable or disable automated keep-alive polling.
- `POST /api/action/reload-session` — Force reload session cookies and refresh dashboard page.

### Real-Time Streaming Endpoints

- `GET /api/events` — Server-Sent Events (SSE) streaming live logs and server state changes.
- `WebSocket /ws` — High-performance bi-directional WebSocket hub streaming JSON event frames.

---

## 🧪 Testing & Verification

The project includes an exhaustive 217-test multi-tier end-to-end and unit test suite:

```bash
# Run complete test suite across all 5 tiers
pytest -v --asyncio-mode=auto tests/

# Run unit tests only
pytest -v tests/unit/

# Run integration tests only
pytest -v tests/integration/

# Run E2E multi-tier scenarios
pytest -v tests/e2e/
```

---

## 🔒 Security & Privacy

- **Non-Root Execution**: Runs under unprivileged user `appuser` (UID 1001) in Docker and dedicated service user in systemd.
- **Cookie Masking**: Sensitive session tokens are masked in all console logs, API responses, and telemetry (`***` or `abc1...456`).
- **Resource Sandboxing**: Adblock request routing prevents third-party tracking scripts, audio/video streams, and memory bloating.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
