#!/bin/bash
# Wave 1 ingestion runner — called by launchd
# Logs go to logs/wave1.log

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/wave1.log"

mkdir -p "$LOG_DIR"

echo "----------------------------------------" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Wave 1 ingestion" >> "$LOG_FILE"

cd "$PROJECT_DIR"

/usr/bin/python3 -m scripts.run_ingestion --wave 1 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finished. Exit code: $EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE