#!/usr/bin/env bash
# gcp/deploy.sh — One-time GCP setup + manual deploy helper.
#
# Run this ONCE to create all the GCP resources, then use Cloud Build
# (cloudbuild.yaml) for all future deploys.
#
# Prerequisites:
#   1. gcloud CLI installed: https://cloud.google.com/sdk/docs/install
#   2. Docker Desktop running locally
#   3. You are logged in: gcloud auth login
#   4. Billing is enabled on your project
#
# Usage:
#   chmod +x gcp/deploy.sh
#   ./gcp/deploy.sh

set -euo pipefail

# ── CONFIG — edit these ────────────────────────────────────────────────────────
PROJECT_ID=""          # e.g. my-phonebooth-project
REGION="us-central1"   # https://cloud.google.com/run/docs/locations
SERVICE="phonebooth-v2"
REPO="phonebooth"

# ── Validate ───────────────────────────────────────────────────────────────────
if [[ -z "$PROJECT_ID" ]]; then
  echo "❌  Set PROJECT_ID at the top of gcp/deploy.sh before running."
  exit 1
fi

echo "▶ Project : $PROJECT_ID"
echo "▶ Region  : $REGION"
echo "▶ Service : $SERVICE"
echo ""

gcloud config set project "$PROJECT_ID"

# ── 1. Enable required APIs ───────────────────────────────────────────────────
echo "⚙️  Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com

# ── 2. Create Artifact Registry repo ─────────────────────────────────────────
echo "📦  Creating Artifact Registry repo '$REPO'..."
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Phonebooth V2 container images" \
  2>/dev/null || echo "   (already exists, skipping)"

# ── 3. Create Secret Manager secrets ─────────────────────────────────────────
echo "🔑  Creating secrets in Secret Manager..."
echo "    → DISCORD_TOKEN"
echo "PASTE YOUR BOT TOKEN, then press Ctrl-D:"
gcloud secrets create DISCORD_TOKEN --replication-policy=automatic 2>/dev/null || true
gcloud secrets versions add DISCORD_TOKEN --data-file=-

echo ""
echo "    → REPORT_LOG_CHANNEL_ID (the channel ID for GIF report logs, or 0)"
read -rp "Enter REPORT_LOG_CHANNEL_ID: " REPORT_CH
echo -n "$REPORT_CH" | gcloud secrets versions add REPORT_LOG_CHANNEL_ID --data-file=- 2>/dev/null || \
  (gcloud secrets create REPORT_LOG_CHANNEL_ID --replication-policy=automatic && \
   echo -n "$REPORT_CH" | gcloud secrets versions add REPORT_LOG_CHANNEL_ID --data-file=-)

# ── 4. Create GCS bucket for SQLite persistence ───────────────────────────────
BUCKET="${PROJECT_ID}-phonebooth-data"
echo "🗄️  Creating Cloud Storage bucket for SQLite: gs://$BUCKET"
gcloud storage buckets create "gs://$BUCKET" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  2>/dev/null || echo "   (already exists, skipping)"

# ── 5. Build & push Docker image ─────────────────────────────────────────────
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest"
echo "🐳  Building Docker image..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" -q
docker build -t "$IMAGE" .
docker push "$IMAGE"

# ── 6. Deploy to Cloud Run ────────────────────────────────────────────────────
echo "🚀  Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --min-instances=1 \
  --max-instances=1 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=3600 \
  --set-secrets="DISCORD_TOKEN=DISCORD_TOKEN:latest,REPORT_LOG_CHANNEL_ID=REPORT_LOG_CHANNEL_ID:latest" \
  --set-env-vars="DB_PATH=/data/phonebooth.db" \
  --update-volume="name=phonebooth-data,type=cloud-storage,bucket=${BUCKET},mount-path=/data"

echo ""
echo "✅  Phonebooth V2 is live on Cloud Run!"
echo "    View logs: gcloud run services logs tail $SERVICE --region $REGION"
echo ""
echo "📌  Next: connect your GitHub repo in Cloud Build → Triggers"
echo "    so future pushes auto-deploy (uses gcp/cloudbuild.yaml)."
