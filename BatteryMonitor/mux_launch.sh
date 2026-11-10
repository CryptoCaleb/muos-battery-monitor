#!/bin/sh
# HELP: Battery Monitor - battery life, drain and charge rates, graphs and health. Created by Caleb Hinton.
# ICON: batterymonitor
# GRID: Battery

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1
export HOME="$APP_DIR"
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "python3 not found on this device" > "$APP_DIR/last_run.log"
    exit 1
fi
"$PY" "$APP_DIR/app.py"
sync
