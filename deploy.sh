#!/usr/bin/env bash
# deploy.sh — Deploy MockMate backend to Google Cloud Run
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - GCP project set (gcloud config set project YOUR_PROJECT)
#   - Required APIs enabled: Cloud Run, Cloud Build, Artifact Registry

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="mockmate-backend"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
MEMORY="2Gi"
TIMEOUT="3600"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Error: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

# ── Load environment variables from backend/.env ──────────────────────────────
ENV_FILE="./backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found. Copy backend/.env.example to backend/.env and fill in your values."
  exit 1
fi

# Parse .env into a comma-separated KEY=VALUE string for Cloud Run.
# Skips comments, blank lines, and strips surrounding whitespace/quotes.
ENV_VARS=""
while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip empty lines and comments
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  # Extract key and value
  key="${line%%=*}"
  value="${line#*=}"
  # Trim whitespace from key
  key="$(echo "$key" | xargs)"
  # Trim whitespace and surrounding quotes from value
  value="$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'\'']//' -e 's/["'\'']*$//')"
  [[ -z "$key" ]] && continue
  if [[ -n "$ENV_VARS" ]]; then
    ENV_VARS="${ENV_VARS},${key}=${value}"
  else
    ENV_VARS="${key}=${value}"
  fi
done < "$ENV_FILE"

echo "Deploying MockMate backend to Cloud Run"
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Service:  $SERVICE_NAME"
echo "  Env file: $ENV_FILE"
echo ""

# ── Build ─────────────────────────────────────────────────────────────────────
echo "Building container image..."
gcloud builds submit --tag "$IMAGE" ./backend

# ── Deploy ────────────────────────────────────────────────────────────────────
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --memory "$MEMORY" \
  --timeout "$TIMEOUT" \
  --allow-unauthenticated \
  --set-env-vars "$ENV_VARS"

# ── Print URL ─────────────────────────────────────────────────────────────────
URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format 'value(status.url)' 2>/dev/null)
echo ""
echo "Deployment complete!"
echo "Backend URL: $URL"
echo ""
echo "Next steps:"
echo "  1. Update your frontend's NEXT_PUBLIC_API_URL to: $URL"
