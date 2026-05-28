#!/usr/bin/env bash
# Run the batch pipeline DETACHED so it survives SSH disconnect / closing your laptop.
#
# Pass only the city + sector flags; the export dir is added automatically.
#
# Usage:
#   ./run-pipeline.sh --city antwerpen --all-sectors
#   ./run-pipeline.sh --city antwerpen --sector elektriciens --sector accountants
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"
EXPORT_DATE="$(date +%F)"

if [[ $# -eq 0 ]]; then
    echo "Error: pass pipeline args, e.g. --city antwerpen --all-sectors" >&2
    echo "Usage: $0 --city antwerpen --all-sectors" >&2
    exit 1
fi

echo "Starting detached pipeline run -> /data/exports/$EXPORT_DATE ..."
CID=$(docker compose -f "$COMPOSE_FILE" run -d pipeline \
    be-leads-pipeline-batch "$@" --export-dir "/data/exports/$EXPORT_DATE")

echo
echo "Pipeline is running in the background. Safe to close your laptop now."
echo "  Container id:         $CID"
echo "  Follow live logs:     docker logs -f $CID"
echo "  Still running?        docker ps --filter id=$CID"
echo "  Finished? (exit code) docker inspect -f '{{.State.ExitCode}}' $CID"
echo "  CSV results land in:  /opt/be-leads/exports/$EXPORT_DATE/"
