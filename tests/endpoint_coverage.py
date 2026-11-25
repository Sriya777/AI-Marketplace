"""
Endpoint coverage: compares the API calls recorded during the test run (API_ACCESS_LOG) with every operation the
application declares in its OpenAPI schema. Exits non-zero if any endpoint was never exercised.

  API_ACCESS_LOG=tests/results/access_log.txt  (set by scripts/run_all_tests.sh)   ->   tests/results/ENDPOINT_COVERAGE.md
"""
import os, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MARKETPLACE_MASTER_PASSPHRASE", "coverage-report-only-passphrase")
os.environ.setdefault("DB_MODE", "file")
os.environ.setdefault("MARKETPLACE_STORAGE", str(ROOT / ".run" / "coverage-tmp"))
from backend.app.main import app   # noqa: E402

log = Path(os.environ.get("API_ACCESS_LOG", ROOT / "tests" / "results" / "access_log.txt"))
if not log.exists():
    sys.exit(f"no access log at {log}")

ops = []        # (method, template, compiled regex)
for path, item in app.openapi()["paths"].items():
    rx = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(path).replace(r"\{", "{").replace(r"\}", "}")) + "$")
    for method in item:
        ops.append((method.upper(), path, rx))

calls = defaultdict(lambda: defaultdict(int))
for line in log.read_text().splitlines():
    try:
        method, p, status = line.split()
    except ValueError:
        continue
    for m, tpl, rx in ops:
        if m == method and rx.match(p):
            calls[(m, tpl)][status] += 1
            break

rows, missing = [], []
for m, tpl, _ in sorted(ops, key=lambda o: (o[1], o[0])):
    st = calls.get((m, tpl))
    if not st:
        missing.append(f"{m} {tpl}")
    rows.append((m, tpl, sum(st.values()) if st else 0, ", ".join(f"{k}×{v}" for k, v in sorted(st.items())) if st else "—"))

out = [f"# Endpoint coverage", "", f"**{len(ops) - len(missing)} / {len(ops)}** API operations were called during the automated test run.", "",
       "| Method | Path | Calls | Status codes seen |", "|---|---|---|---|"]
out += [f"| {m} | `{t}` | {n} | {s} |" for m, t, n, s in rows]
if missing:
    out += ["", "## NOT exercised", ""] + [f"* {x}" for x in missing]
res = ROOT / "tests" / "results" / "ENDPOINT_COVERAGE.md"
res.write_text("\n".join(out) + "\n")
print(f"endpoint coverage: {len(ops) - len(missing)}/{len(ops)}")
for x in missing:
    print("  NOT COVERED:", x)
sys.exit(1 if missing else 0)
