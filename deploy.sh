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

echo "Deploying MockMate backend to Cloud Run"
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Service:  $SERVICE_NAME"
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
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE"

# ── Print URL ─────────────────────────────────────────────────────────────────
URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format 'value(status.url)' 2>/dev/null)
echo ""
echo "Deployment complete!"
echo "Backend URL: $URL"
echo ""
echo "Next steps:"
echo "  1. Set environment variables in Cloud Run (GCS_BUCKET, Firestore, Postgres, etc.)"
echo "  2. Update your frontend's NEXT_PUBLIC_API_URL to: $URL"
