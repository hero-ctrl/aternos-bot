# Original User Request

## Initial Request — 2026-08-24T06:10:06Z

# Aternos 24/7 Keep-Alive Automation & Web Dashboard

Build an automated 24/7 Aternos Minecraft server keep-alive system that monitors the server state, automatically detects and clicks the exact `+1` countdown extension button (located next to the timer on the server status bar), prevents automatic shutdowns, and exposes a lightweight web dashboard for real-time monitoring and control. The application must be fully containerized (Docker) and ready for 24/7 free cloud deployment (e.g., Render, Railway, Fly.io, or VPS) without requiring the user's personal computer or browser to remain open.

Working directory: ~/teamwork_projects/aternos_247_bot
Integrity mode: demo

## Requirements

### R1. Aternos Automation & Exact "+1" Button Clicking Engine
The system must handle authentication with Aternos (via credentials or saved session cookies/tokens) and continuously monitor the server dashboard (`https://aternos.org/server/`). When the server is online and the idle countdown widget (e.g., `0:37` with the `+1` button) appears on the status bar, the engine must immediately and automatically click the `+1` button to reset/extend the timer indefinitely.

### R2. Lightweight Web Dashboard & Control Interface
Provide a responsive, lightweight web dashboard accessible via any mobile or desktop browser:
- Live Aternos server status (Offline, In Queue, Loading, Online).
- Active countdown timer value and last `+1` click timestamp.
- Real-time action logs (e.g., `[07:09:12] Clicked '+1' button successfully - Timer extended`).
- Manual controls to toggle keep-alive monitoring and trigger server start/stop.

### R3. Cloud & Docker Ready Deployment (24/7 No-PC Operation)
Package the entire solution with a clean `Dockerfile` and `docker-compose.yml` configured for zero-overhead background execution on free cloud platforms (Render, Railway, Fly.io, Koyeb, or Linux VPS). Configuration (Aternos cookies/credentials, port, check intervals) must be strictly managed through environment variables or `.env`.

### R4. Anti-Bot & Session Resilience
Implement browser stealth mechanisms (Playwright/Puppeteer Stealth with session cookie caching) to handle Cloudflare challenges and protect against session timeouts or disconnections. The service must auto-reconnect and re-authenticate seamlessly if the session drops.

## Acceptance Criteria

### Automation & Logic
- [ ] Automation script precisely locates and triggers the `+1` countdown button element on the Aternos server status bar.
- [ ] Keep-alive loop continuously monitors the countdown and resets the timer before it reaches 0:00.
- [ ] Auto-reconnects and retries on transient network disconnects or session drops.

### Dashboard & API
- [ ] Web dashboard serves an intuitive UI showing real-time server status, current timer, and recent event logs.
- [ ] Live log streaming via WebSockets/SSE without needing manual page reloads.

### Deployment & Packaging
- [ ] Project contains a working `Dockerfile` and step-by-step instructions for deploying to free cloud hosting.
- [ ] Includes a comprehensive `README.md` explaining deployment and usage.
