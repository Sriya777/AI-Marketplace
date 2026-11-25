#!/usr/bin/env bash
# Full validation on a CLEAN stack (separate test DB + storage, so real data is never touched).
#   ./scripts/run_all_tests.sh              crypto + contract + integration + restart/persistence
#   ./scripts/run_all_tests.sh --browser    ...plus the real-browser (Selenium/Firefox) end-to-end test
#   ./scripts/run_all_tests.sh --keep       leave the stack running afterwards
# Results: tests/results/*.txt and tests/results/TEST_REPORT.md
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"; RES="$ROOT/tests/results"; mkdir -p "$RES"
BROWSER=0; KEEP=0
for a in "$@"; do case "$a" in --browser) BROWSER=1;; --keep) KEEP=1;; esac; done

export MARKETPLACE_STORAGE="$ROOT/.run/test-storage"
export MONGODB_DB="model_marketplace_test"
export API_ACCESS_LOG="$ROOT/tests/results/access_log.txt"
say() { printf '\033[1;36m[tests]\033[0m %s\n' "$*"; }
PY="${PYTHON:-python3}"; [ "${USE_SYSTEM_PYTHON:-0}" != "1" ] && [ -x .venv/bin/python ] && PY="$ROOT/.venv/bin/python"

./scripts/stop.sh >/dev/null 2>&1
rm -rf "$MARKETPLACE_STORAGE" "$RES/screenshots" "$RES/.state.json"; mkdir -p "$RES/screenshots"; : > "$API_ACCESS_LOG"
"$PY" - << 'PY' 2>/dev/null
import os
try:
    from pymongo import MongoClient
    MongoClient(os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=1500).drop_database(os.environ["MONGODB_DB"])
except Exception:
    pass
PY

say "starting a clean stack"
FLAGS="--no-frontend"; [ $BROWSER = 1 ] && FLAGS="--prod-frontend"
./scripts/start.sh $FLAGS > "$RES/stack_start.log" 2>&1 || { cat "$RES/stack_start.log"; exit 1; }
HEALTH=$(curl -s http://127.0.0.1:8000/api/health)
DBMODE=$(echo "$HEALTH" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(d['database']['mode'])")
export EXPECT_DB="$DBMODE"

declare -A RESULT
run() { # name, outfile, command...
  local name="$1" out="$2"; shift 2
  say "$name"; "$@" > "$RES/$out" 2>&1; RESULT[$name]=$?
  # a suite that only SKIPPED tests did not pass (pytest exits 0 in that case)
  if grep -qE "[0-9]+ skipped" "$RES/$out" && ! grep -qE "[0-9]+ passed" "$RES/$out"; then RESULT[$name]=1; fi
  tail -3 "$RES/$out" | sed 's/^/    /'; }

run "Cryptography unit tests (+CIFAR conversion)" crypto_unit_tests.txt "$PY" -m pytest tests/test_crypto_suite.py tests/test_cifar_prepare.py -v
run "Smart contract tests (live chain)" contract_tests.txt bash -c "cd blockchain && node scripts/test_contract.js"
run "Integration tests (API + MongoDB/fallback + blockchain)" integration_tests.txt "$PY" -m pytest tests/test_integration.py -v

say "restarting the backend to test persistence"
kill "$(cat .run/backend.pid)" 2>/dev/null; sleep 2; rm -f .run/backend.pid
./scripts/start.sh $FLAGS > "$RES/stack_restart.log" 2>&1
run "Persistence across restart (encrypted-artifact reload)" persistence_test.txt "$PY" -m pytest tests/test_persistence.py -v

if [ $BROWSER = 1 ]; then
  run "Real-browser end-to-end (Firefox + Selenium)" browser_e2e_tests.txt "$PY" -m pytest tests/test_browser_e2e.py -v
fi

run "Endpoint coverage (every API operation exercised)" endpoint_coverage.txt "$PY" tests/endpoint_coverage.py

# ---- report
{
echo "# Test report"; echo
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)  "
echo "Python $("$PY" --version 2>&1 | cut -d' ' -f2) · Node $(node --version) · $("$PY" -c 'import sklearn,web3,fastapi,cryptography;print("scikit-learn",sklearn.__version__,"· web3",web3.__version__,"· FastAPI",fastapi.__version__,"· cryptography",cryptography.__version__)')  "
echo "Database under test: **$DBMODE**  ·  Chain: $(echo "$HEALTH" | "$PY" -c "import sys,json; c=json.load(sys.stdin)['chain']; print('Hardhat chain', c['chainId'], 'contract', c['contractAddress'])")"
echo; echo "| Suite | Result | Summary |"; echo "|---|---|---|"
for name in "Cryptography unit tests (+CIFAR conversion)" "Smart contract tests (live chain)" "Integration tests (API + MongoDB/fallback + blockchain)" "Persistence across restart (encrypted-artifact reload)" "Real-browser end-to-end (Firefox + Selenium)" "Endpoint coverage (every API operation exercised)"; do
  [ -z "${RESULT[$name]+x}" ] && continue
  case "$name" in
    Crypto*) f=crypto_unit_tests.txt;; Smart*) f=contract_tests.txt;; Integration*) f=integration_tests.txt;; Persist*) f=persistence_test.txt;; Endpoint*) f=endpoint_coverage.txt;; *) f=browser_e2e_tests.txt;; esac
  summ=$(grep -E "passed|failed|skipped|endpoint coverage" "$RES/$f" | tail -1 | sed 's/=//g;s/^ *//')
  [ "${RESULT[$name]}" = 0 ] && r="PASS" || r="**FAIL**"
  echo "| $name | $r | $summ |"
done
echo; echo "Raw outputs: \`tests/results/*.txt\`. Browser screenshots: \`tests/results/screenshots/\` (if the browser test was run)."
} > "$RES/TEST_REPORT.md"

FAILS=0; for k in "${!RESULT[@]}"; do [ "${RESULT[$k]}" != 0 ] && FAILS=$((FAILS+1)); done
cat "$RES/TEST_REPORT.md"
[ $KEEP = 0 ] && ./scripts/stop.sh >/dev/null 2>&1
exit $FAILS
