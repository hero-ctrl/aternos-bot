# =============================================================================
# Multi-Stage Production Dockerfile for Aternos 24/7 Keep-Alive Automation
# Optimized for <250MB RAM footprint, zero-overhead execution & cloud deployment
# =============================================================================

# --- Stage 1: Build & Dependency Wheel Cache ---
FROM python:3.11-slim-bullseye AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# --- Stage 2: Minimal Secure Runtime Stage ---
FROM python:3.11-slim-bullseye AS runtime

LABEL maintainer="Aternos Keep-Alive Automation Team"
LABEL description="24/7 Aternos Keep-Alive Bot & Web Dashboard"

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
    PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright \
    PYTHONPATH=/app

# Install runtime system packages, dumb-init, curl for healthchecks & Chromium dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    curl \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python wheels from builder
COPY --from=builder /install /usr/local

# Create non-privileged service user and application directories
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -m -s /bin/bash appuser && \
    mkdir -p /app/data /app/data/screenshots /app/.cache/ms-playwright && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Install headless Chromium browser binary only
RUN python -m playwright install chromium

# Copy application source code
COPY --chown=appuser:appgroup src/ /app/src/

# Expose web dashboard port
EXPOSE 8000

# Docker healthcheck probe against REST health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Process supervisor entrypoint
ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["python", "-m", "src.main"]
