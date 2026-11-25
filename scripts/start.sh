#!/usr/bin/env bash
# One-command start for Linux / macOS / WSL / Git-Bash.
#   ./scripts/start.sh                 start MongoDB (if available), Hardhat, contract, backend, frontend
#   ./scripts/start.sh --no-frontend   skip the Next.js frontend
#   ./scripts/start.sh --prod-frontend build + serve the optimised frontend instead of `next dev`
# Environment: MONGOD_BIN=/path/to/mongod   USE_SYSTEM_PYTHON=1 (skip the .venv)   DB_MODE=file|mongo|auto
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"; RUN="$ROOT/.run"; LOGS="$RUN/logs"; mkdir -p "$LOGS" "$RUN/mongodata"
FRONTEND=1; PROD=0
for a in "$@"; do case "$a" in --no-frontend) FRONTEND=0;; --prod-frontend) PROD=1;; esac; done

say()  { printf '\033[1;36m[start]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*"; exit 1; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0 || return 1; }
wait_for() { # name, command, seconds
  for ((i=1;i<=$3;i++)); do if eval "$2" >/dev/null 2>&1; then say "$1 is up (${i}s)"; return 0; fi; sleep 1; done
  warn "$1 did not become ready within $3 s - see $LOGS"; return 1; }
bg() { # name, command...   (detached, logs to .run/logs/<name>.log, pid in .run/<name>.pid)
  local name="$1"; shift
  setsid nohup "$@" > "$LOGS/$name.log" 2>&1 < /dev/null &
  echo $! > "$RUN/$name.pid"; }

# ---- prerequisites
command -v node >/dev/null || die "Node.js 18+ is required (https://nodejs.org)"
command -v npm  >/dev/null || die "npm is required"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif command -v python3 >/dev/null; then PY=python3; elif command -v python >/dev/null; then PY=python; else die "Python 3.10+ is required"; fi

# ---- .env (generated once; holds the operator master passphrase)
if [ ! -f .env ]; then
  say "creating .env with a freshly generated master passphrase"
  sed "s|^MARKETPLACE_MASTER_PASSPHRASE=.*|MARKETPLACE_MASTER_PASSPHRASE=$($PY -c 'import secrets;print(secrets.token_urlsafe(32))')|" .env.example > .env
fi

# ---- Python dependencies
if [ "${USE_SYSTEM_PYTHON:-0}" != "1" ]; then
  [ -d .venv ] || { say "creating Python virtual environment (.venv)"; "$PY" -m venv .venv || die "could not create venv"; }
  PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"
  if [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
    say "installing Python dependencies"; "$PY" -m pip install -q -r requirements.txt || die "pip install failed"; touch .venv/.deps_installed
  fi
fi

# ---- Node dependencies
[ -d blockchain/node_modules ] || { say "installing blockchain dependencies"; (cd blockchain && npm install --no-audit --no-fund) || die "npm install (blockchain) failed"; }
if [ $FRONTEND = 1 ] && [ ! -d frontend/node_modules ]; then say "installing frontend dependencies (first run takes a few minutes)"; (cd frontend && npm install --no-audit --no-fund) || die "npm install (frontend) failed"; fi

# ---- MongoDB
MONGOD="${MONGOD_BIN:-$(command -v mongod || true)}"
if port_open 27017; then say "MongoDB already running on :27017"
elif [ -n "$MONGOD" ]; then
  say "starting MongoDB ($MONGOD)"; bg mongod "$MONGOD" --dbpath "$RUN/mongodata" --bind_ip 127.0.0.1 --port 27017
  wait_for MongoDB "port_open 27017" 30
else warn "MongoDB not found. The backend will use the FILE-BACKED DEVELOPMENT FALLBACK (see README: MongoDB setup)."; fi

# ---- local blockchain + contract
if port_open 8545; then say "blockchain node already running on :8545"
else say "starting Hardhat local blockchain"; (cd blockchain && bg hardhat ./node_modules/.bin/hardhat node) ; wait_for "Hardhat node" "port_open 8545" 90; fi
say "compiling / deploying ModelRegistry"; (cd blockchain && node scripts/ensure_deployed.js) || die "contract deployment failed"

# ---- backend
if port_open 8000; then say "backend already running on :8000"
else
  say "starting FastAPI backend"; bg backend "$PY" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
  wait_for backend "curl -sf http://127.0.0.1:8000/api/health" 60 || { tail -15 "$LOGS/backend.log"; die "backend failed to start"; }
fi

# ---- frontend
if [ $FRONTEND = 1 ]; then
  if port_open 3000; then say "frontend already running on :3000"
  elif [ $PROD = 1 ]; then
    if [ ! -f frontend/.next/BUILD_ID ] || [ -n "$(find frontend/src frontend/next.config.mjs -newer frontend/.next/BUILD_ID 2>/dev/null | head -1)" ]; then
      say "building the frontend"; (cd frontend && npm run build >"$LOGS/frontend-build.log" 2>&1) || die "frontend build failed (see $LOGS/frontend-build.log)"
    fi
    (cd frontend && bg frontend npm run start); wait_for frontend "curl -sf http://127.0.0.1:3000" 90
  else (cd frontend && bg frontend npm run dev); wait_for frontend "curl -sf http://127.0.0.1:3000" 120; fi
fi

echo
say "ready:"
[ $FRONTEND = 1 ] && echo "   Frontend   http://localhost:3000"
echo "   API docs   http://127.0.0.1:8000/docs"
echo "   Health     http://127.0.0.1:8000/api/health"
echo "   Logs       $LOGS     (stop everything with ./scripts/stop.sh)"
