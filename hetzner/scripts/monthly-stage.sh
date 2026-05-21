#!/usr/bin/env bash
# Monthly KBO Open Data staging script.
# Run this after downloading the latest KBO Open Data ZIP.
#
# Usage:
#   ./monthly-stage.sh /opt/be-leads/KBO_zip/KboOpenData_202601.zip
#
# Or set KBO_ZIP_PATH env var:
#   KBO_ZIP_PATH=/opt/be-leads/KBO_zip/KboOpenData_202601.zip ./monthly-stage.sh
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ZIP_PATH="${1:-${KBO_ZIP_PATH:-}}"

if [[ -z "$ZIP_PATH" ]]; then
    echo "Error: supply zip path as argument or set KBO_ZIP_PATH env var" >&2
    echo "Usage: $0 /path/to/KboOpenData_YYYYMM.zip" >&2
    exit 1
fi

if [[ ! -f "$ZIP_PATH" ]]; then
    echo "Error: file not found: $ZIP_PATH" >&2
    exit 1
fi

ZIP_FILENAME="$(basename "$ZIP_PATH")"
KBO_ZIP_DIR="/opt/be-leads/KBO_zip"

# Copy ZIP to the volume directory if it isn't already there.
if [[ "$ZIP_PATH" != "$KBO_ZIP_DIR/$ZIP_FILENAME" ]]; then
    echo "Copying $ZIP_FILENAME to $KBO_ZIP_DIR ..."
    cp "$ZIP_PATH" "$KBO_ZIP_DIR/$ZIP_FILENAME"
fi

echo "Staging $ZIP_FILENAME ..."
docker compose -f "$COMPOSE_DIR/docker-compose.prod.yml" \
    run --rm kbo-stage \
    be-leads-kbo-stage "/kbo_zip/$ZIP_FILENAME"

echo "Cleaning up old stage snapshots (keeping 3) ..."
docker compose -f "$COMPOSE_DIR/docker-compose.prod.yml" \
    run --rm kbo-stage \
    be-leads-cleanup-stage --keep 3

echo "Done. KBO data staged from $ZIP_FILENAME."
