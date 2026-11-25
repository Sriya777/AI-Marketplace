#!/usr/bin/env bash
# Stops every process started by start.sh (uses the PID files in .run/).
cd "$(dirname "$0")/.."
for name in frontend backend hardhat mongod; do
  f=".run/$name.pid"
  if [ -f "$f" ]; then
    pid=$(cat "$f"); if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null; pkill -P "$pid" 2>/dev/null; echo "stopped $name ($pid)"; fi
    rm -f "$f"
  fi
done
