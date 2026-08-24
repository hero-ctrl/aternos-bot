# =============================================================================
# Production Dockerfile for Aternos 24/7 Keep-Alive Automation
# Fully compatible with Render, Railway, Fly.io, and Cloud PaaS
# =============================================================================

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    HEADLESS=true \
    CHECK_INTERVAL=5.0 \
    COUNTDOWN_THRESHOLD=180 \
    EMERGENCY_THRESHOLD=30 \
    COOKIE_FILE_PATH=/app/data/cookies.json \
    SCREENSHOT_DIR=/app/data/screenshots \
    PYTHONPATH=/app

# Install base utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium with all system dependencies
RUN python -m playwright install --with-deps chromium

# Create data directories
RUN mkdir -p /app/data /app/data/screenshots

# Copy application files
COPY . .

# Expose web dashboard port
EXPOSE 8000

# Start Keep-Alive Web Server
CMD ["python", "-m", "src.main"]

