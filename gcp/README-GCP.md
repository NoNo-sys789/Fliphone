# Phonebooth V2 — Hosting on Google Cloud

## Architecture

```
GitHub push
    │
    ▼
Cloud Build (CI/CD)
    │  builds Docker image
    ▼
Artifact Registry
    │  stores image
    ▼
Cloud Run (min 1 instance, max 1 instance)
    │  runs the bot 24/7
    ├─ Secret Manager → DISCORD_TOKEN, REPORT_LOG_CHANNEL_ID
    └─ Cloud Storage bucket → /data/phonebooth.db (persistent SQLite)
```

**Why Cloud Run and not Compute Engine?**
Cloud Run is cheaper, fully managed (no VM to patch), and scales to zero
when idle — except we set `min-instances=1` so the Discord gateway connection
is never dropped. Cost is typically **$5–10/month** for a small bot.

---

## First-time setup (run once)

### 1. Install prerequisites

```bash
# Install gcloud CLI
https://cloud.google.com/sdk/docs/install

# Log in
gcloud auth login
gcloud auth application-default login

# Install Docker Desktop
https://docs.docker.com/get-docker/
```

### 2. Create a GCP project

Go to https://console.cloud.google.com → New Project → note the Project ID.
Enable billing on the project (a free-tier account works).

### 3. Run the setup script

```bash
# Edit the PROJECT_ID at the top of the file first
nano gcp/deploy.sh

chmod +x gcp/deploy.sh
./gcp/deploy.sh
```

The script will:
- Enable all required APIs
- Create an Artifact Registry Docker repo
- Store your bot token in Secret Manager (never in the image)
- Create a Cloud Storage bucket to hold `phonebooth.db`
- Build & push the Docker image
- Deploy to Cloud Run

### 4. Verify it's running

```bash
# Live log stream
gcloud run services logs tail phonebooth-v2 --region us-central1

# You should see:
# ✅ Extensions loaded.
# 📞 Phonebooth V2  |  YourBot#1234  |  N server(s)
```

---

## Auto-deploy on every git push (optional but recommended)

1. Go to **Cloud Build → Triggers** in the GCP console
2. Click **Connect Repository** → choose GitHub → authorise → select your repo
3. Create a trigger:
   - Event: Push to branch `main`
   - Config: Cloud Build configuration file → `gcp/cloudbuild.yaml`
4. Push any commit — Cloud Build will build and redeploy automatically

---

## Updating secrets

```bash
# Rotate bot token
echo -n "NEW_TOKEN" | gcloud secrets versions add DISCORD_TOKEN --data-file=-

# Update report channel
echo -n "1234567890" | gcloud secrets versions add REPORT_LOG_CHANNEL_ID --data-file=-

# Restart the service to pick up new secrets
gcloud run services update phonebooth-v2 --region us-central1
```

---

## Estimated monthly cost (us-central1)

| Resource | Free tier | Typical cost |
|---|---|---|
| Cloud Run (1 vCPU, 512 MB, always-on) | 180k vCPU-seconds free | ~$7–12/mo |
| Artifact Registry | 0.5 GB free | ~$0 |
| Cloud Storage (SQLite DB ~5 MB) | 5 GB free | ~$0 |
| Secret Manager | 6 active versions free | ~$0 |
| Cloud Build | 120 min/day free | ~$0 |
| **Total** | | **~$7–12/month** |

---

## Useful commands

```bash
# View running service
gcloud run services describe phonebooth-v2 --region us-central1

# Tail live logs
gcloud run services logs tail phonebooth-v2 --region us-central1

# Manual redeploy (without CI/CD)
./gcp/deploy.sh

# Delete everything (careful!)
gcloud run services delete phonebooth-v2 --region us-central1
```
