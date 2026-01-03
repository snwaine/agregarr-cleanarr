#!/bin/sh
set -eu

: "${CRON_SCHEDULE:=15 3 * * *}"
: "${WEBUI_PORT:=7575}"
: "${CONFIG_DIR:=/config}"

mkdir -p "$CONFIG_DIR"
touch /var/log/agregarr-cleanarr.log

# Cron uses env CRON_SCHEDULE; note: actual schedule can be edited in WebUI too,
# but cron won't pick it up until container restart unless we implement dynamic reload.
echo "${CRON_SCHEDULE} python /app/app.py >> /var/log/agregarr-cleanarr.log 2>&1" > /etc/crontabs/root

# Start WebUI
echo "[agregarr-cleanarr] Starting WebUI on :${WEBUI_PORT}"
python /app/webui.py --host 0.0.0.0 --port "${WEBUI_PORT}" >/dev/null 2>&1 &
WEBUI_PID=$!

# Optional run on startup
if [ "${RUN_ON_STARTUP:-false}" = "true" ]; then
  echo "[agregarr-cleanarr] RUN_ON_STARTUP=true => running once now"
  python /app/app.py || true
fi

# Background watcher: if /config/run_now.flag appears, run immediately
(
  while true; do
    if [ -f "${CONFIG_DIR}/run_now.flag" ]; then
      rm -f "${CONFIG_DIR}/run_now.flag"
      echo "[agregarr-cleanarr] Run Now triggered"
      python /app/app.py || true
    fi
    sleep 5
  done
) &

# Start cron in foreground
echo "[agregarr-cleanarr] Starting cron"
exec crond -f -l 2
