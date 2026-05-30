# Hetzner Deployment Runbook

Step-by-step guide for deploying be-leads-cloud on a Hetzner Cloud server.
Written for users who know SSH and Docker basics.

---

## Recommended Hetzner Server

| Setting | Value |
|---------|-------|
| Type    | **CCX23** — 4 dedicated vCPU, 16 GB RAM |
| OS      | **Ubuntu 22.04 LTS** |

Chromium (used by the goudengids scraper) needs roughly 1 GB of free RAM.
Postgres + Python take the rest, so 16 GB is the practical minimum.

---

## Initial Server Setup

```bash
# 1. Install Docker + Docker Compose plugin (Ubuntu 22.04)
apt-get update && apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 2. Clone the repository
git clone https://github.com/your-org/be-leads-cloud.git /opt/be-leads-cloud

# 3. Create host directories for persistent data
mkdir -p /opt/be-leads/{KBO_zip,exports,logs,backups}

# 4. Copy the example env file
cp /opt/be-leads-cloud/hetzner/.env.example /opt/be-leads-cloud/hetzner/.env

# 5. Edit .env — change the Postgres password and set DATABASE_URL
nano /opt/be-leads-cloud/hetzner/.env
```

---

## Build the Image

```bash
cd /opt/be-leads-cloud
docker build -t be-leads-cloud:latest .
```

---

## First-Time Database Setup

```bash
cd /opt/be-leads-cloud/hetzner

# Start Postgres
docker compose -f docker-compose.prod.yml up -d pg

# Apply all migrations
docker compose -f docker-compose.prod.yml run --rm migrate
```

Verify Postgres is healthy before continuing:

```bash
docker compose -f docker-compose.prod.yml ps
```

---

## First KBO Data Load

Download the KBO Open Data ZIP from
[kbopub.economie.fgov.be/kbo-open-data](https://kbopub.economie.fgov.be/kbo-open-data)
and place it in `/opt/be-leads/KBO_zip/`.

Then stage it:

```bash
docker compose -f docker-compose.prod.yml run --rm kbo-stage \
    be-leads-kbo-stage /kbo_zip/KboOpenData_YYYYMM.zip
```

Replace `KboOpenData_YYYYMM.zip` with the actual filename.

---

## Running the Pipeline

### Basic: city + one or more sectors

```bash
docker compose -f docker-compose.prod.yml run --rm pipeline \
    be-leads-pipeline-batch \
    --city antwerpen \
    --sector elektriciens \
    --export-dir /data/exports/$(date +%F)
```

### All sectors for a city

```bash
docker compose -f docker-compose.prod.yml run --rm pipeline \
    be-leads-pipeline-batch \
    --city antwerpen \
    --all-sectors \
    --export-dir /data/exports/$(date +%F)
```

### Skip dedup window (force re-scrape)

Add these flags to any pipeline command to bypass the recent-run deduplication window:

```bash
    --goudengids-skip-recent-hours 0 \
    --ddg-brave-skip-recent-hours 0
```

---

## Running Unattended (close your laptop)

Use the helper script so the pipeline survives SSH disconnect:

```bash
# Make executable once
chmod +x /opt/be-leads-cloud/hetzner/scripts/run-pipeline.sh

# Then run — returns immediately and prints a container id
/opt/be-leads-cloud/hetzner/scripts/run-pipeline.sh --city antwerpen --all-sectors
/opt/be-leads-cloud/hetzner/scripts/run-pipeline.sh --city antwerpen --sector elektriciens
```

The script starts the container detached (managed by Docker, not your terminal) and prints:
- The container id
- The exact commands to follow logs, check if it's still running, and verify the exit code

**After closing and reopening your laptop:**

```bash
# Watch live output (Ctrl+C to stop watching — pipeline keeps running)
docker logs -f <container-id>

# Check if it finished
docker inspect -f '{{.State.ExitCode}}' <container-id>
# 0 = success, anything else = error

# Clean up the stopped container when done
docker container prune
```

CSVs appear in `/opt/be-leads/exports/<YYYY-MM-DD>/` once the run completes.

---

## Running the UI on the Server (browser control panel)

A long-running Streamlit `ui` service replaces most day-to-day bash. From it you can
stage KBO ZIPs, trigger batch runs (**Run Batch Pipeline** page), monitor **Live
Progress**, run the new-leads diff, and download CSVs.

It is published on the server **loopback only** (`127.0.0.1:8501`) — never exposed to
the internet. Reach it from your laptop through an SSH tunnel.

```bash
# On the server — start (and keep) the UI running
cd /opt/be-leads-cloud/hetzner
docker compose -f docker-compose.prod.yml up -d ui
```

```powershell
# On your laptop — open the tunnel, then browse http://localhost:8501
./hetzner/scripts/tunnel-ui.ps1 -Server root@YOUR_HETZNER_IP
```

The UI talks to Postgres over the internal Docker network (`pg:5432`), so no DB
password is needed in the browser. Trigger a batch run with **Goudengids OFF** (the
server IP is blocked — see below); watch it advance on the Live Progress tab.

> A batch run started from the server UI executes inside the `ui` container. Leave the
> container running until it finishes; if it restarts mid-run the job stops (progress is
> recorded in the DB, so you'll see where it halted).

---

## Running Goudengids Locally (Imperva workaround)

Goudengids/Pagesdor sit behind Imperva, which blocks the Hetzner **datacenter IP**
(the scraper receives an `_Incapsula_Resource` challenge page). Your laptop's
**residential IP** is not blocked. So run *only* goudengids from your laptop, writing
into the same remote DB; consolidation then links the goudengids placeholders to the
real KBOs your server batch already loaded.

```powershell
# 1. Open the DB tunnel (leave this window open)
./hetzner/scripts/tunnel-db.ps1 -Server root@YOUR_HETZNER_IP

# 2. In a second window, launch the local UI against the remote DB
$env:LEADS_PG_PASSWORD = "<the POSTGRES_PASSWORD from hetzner/.env>"
./hetzner/scripts/run-ui-local.ps1
```

In the UI sidebar: **deselect every source except Goudengids** (optionally keep
Company websites), pick the sector(s) + city, and click **Run pipeline**. The
single-run consolidation pass matches the new `9%` placeholders against the real KBOs
in the remote DB and refreshes the materialised view + prospect scores.

---

## Retrieving CSV Results

From your laptop:

```bash
scp -r user@YOUR_HETZNER_IP:/opt/be-leads/exports/YYYY-MM-DD/ ./
```

Or use the UI's **New Leads** / results tabs and the **Download CSV** buttons — no SSH needed.

---

## Monthly KBO Refresh

KBO Open Data is published monthly. Refresh the staged data like this:

1. Download the new ZIP to `/opt/be-leads/KBO_zip/`.
2. Run the helper script:

```bash
/opt/be-leads-cloud/hetzner/scripts/monthly-stage.sh \
    /opt/be-leads/KBO_zip/KboOpenData_NEWMONTH.zip
```

Or do it manually:

```bash
cd /opt/be-leads-cloud/hetzner

docker compose -f docker-compose.prod.yml run --rm kbo-stage \
    be-leads-kbo-stage /kbo_zip/KboOpenData_NEWMONTH.zip

docker compose -f docker-compose.prod.yml run --rm kbo-stage \
    be-leads-cleanup-stage --keep 3
```

Then run the pipeline as usual when ready.

---

## Optional: Monthly Cron for Staging

See `hetzner/crontab.example` for a ready-made cron entry.

Install it with:

```bash
crontab -e
# Paste the relevant line from hetzner/crontab.example
```

---

## Backup Recommendation

### Daily Postgres dump via cron

Add to root crontab (`crontab -e`):

```
0 2 * * * docker exec $(docker ps -q -f name=pg) pg_dumpall -U leads | gzip > /opt/be-leads/backups/$(date +%F).sql.gz
```

### Remote backup target

Attach a Hetzner Storage Box and mount it at `/opt/be-leads/backups/` using SFTP/SSHFS or an rclone cron job.

---

## Troubleshooting

| Symptom | What to check |
|---------|---------------|
| Pipeline hangs or exits silently | `docker compose -f docker-compose.prod.yml logs --tail=100 pipeline` |
| Chromium crashes | Check `/opt/be-leads/logs/`; increase server RAM to 16 GB if < 16 GB |
| Postgres unreachable | `docker compose -f docker-compose.prod.yml ps` — `pg` service must show healthy |
| KBO staging error | Verify the ZIP is fully downloaded (check file size vs. kbopub portal) |
| Empty results / thin enrichment | A KBO Open Data ZIP must be staged; without it, goudengids placeholders are never enriched |
