# ── Phonebooth V2 — Dockerfile ────────────────────────────────────────────────
# Multi-stage build: keeps the final image small (~100 MB).
# Tested on Python 3.11. Compatible with Cloud Run, Compute Engine, or any VPS.

FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Create a non-root user — good practice and required by some GCP policies
RUN useradd --create-home appuser
WORKDIR /app
USER appuser

# Copy dependencies from builder
COPY --from=builder /install /usr/local

# Copy source (the .dockerignore keeps secrets and caches out)
COPY --chown=appuser:appuser . .

# SQLite DB lives in /data so it can be mounted as a persistent volume on GCP
ENV DB_PATH=/data/phonebooth.db

# Discord gateway bots don't need an HTTP port, but Cloud Run requires one.
# A tiny health-check HTTP server runs on PORT alongside the bot.
# See gcp/healthcheck.py — it is started automatically by main.py when PORT is set.
EXPOSE 8080

CMD ["python", "main.py"]
