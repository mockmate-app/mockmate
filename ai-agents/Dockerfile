# ─────────────────────────────────────────────────────────────────────────────
# MockMate AI Agents — Cloud Run container
# Runs the ADK API server (production-grade, no dev UI).
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout/stderr for Cloud Logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY . .

# Cloud Run injects $PORT at runtime (default 8080)
ENV PORT=8080

# ADK API server — serves /run, /run_sse and agent introspection endpoints
# --port reads $PORT via shell expansion so Cloud Run can override it
CMD ["sh", "-c", "adk api_server --port $PORT"]
