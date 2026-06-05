#!/usr/bin/env bash
# paperfinder-status.sh - at-a-glance health of the paper-finder system.
# Usage:  bash scripts/paperfinder-status.sh

set -u
LABEL="com.bioratio.paperfinder.sync"
CONTAINER="paperfinder-qdrant"
QDRANT_URL="http://localhost:6533"
LOG="$HOME/Library/Logs/paperfinder-sync.log"

ok(){ printf "  [ok] %s\n" "$1"; }
no(){ printf "  [--] %s\n" "$1"; }

echo "paper-finder status"
echo "-------------------"

# 1. Docker daemon
if docker info >/dev/null 2>&1; then
  ok "Docker daemon running"
else
  no "Docker daemon NOT running   -> open -a Docker"
fi

# 2. Qdrant container
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
  ok "container '$CONTAINER' up"
else
  no "container '$CONTAINER' not running   -> docker start $CONTAINER"
fi

# 3. Qdrant API
if curl -fs "$QDRANT_URL/collections" >/dev/null 2>&1; then
  ncol=$(curl -fs "$QDRANT_URL/collections" \
    | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["result"]["collections"]))' \
    2>/dev/null || echo "?")
  ok "Qdrant API answering at $QDRANT_URL  ($ncol collections)"
else
  no "Qdrant API not answering at $QDRANT_URL"
fi

# 4. launchd agent (column 2 of `launchctl list` is the last exit code)
line=$(launchctl list 2>/dev/null | grep "$LABEL" || true)
if [ -n "$line" ]; then
  code=$(printf "%s" "$line" | awk '{print $2}')
  ok "launchd agent loaded   (last exit code: $code)"
else
  no "launchd agent not loaded   -> launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/$LABEL.plist"
fi

# 5. recent sync log
echo
if [ -f "$LOG" ]; then
  echo "last sync log lines ($LOG):"
  tail -n 3 "$LOG" | sed 's/^/  /'
else
  no "no sync log yet at $LOG"
fi
