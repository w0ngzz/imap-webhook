#!/bin/sh
set -eu

DATA_DIR="${IMAP_WEBHOOK_DATA_DIR:-/data}"
CONFIG_FILE="${IMAP_WEBHOOK_CONFIG:-$DATA_DIR/config.json}"

mkdir -p "$DATA_DIR/state" "$DATA_DIR/logs"

if [ ! -f "$CONFIG_FILE" ]; then
    cp /app/config.example.json "$CONFIG_FILE"
    echo "Created default config at $CONFIG_FILE"
    echo "Edit it from the web UI or on the host before relying on notifications."
fi

exec "$@"
