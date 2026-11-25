"""
Run AFTER restarting the backend (see scripts/run_all_tests.sh): proves data persisted, sessions survive,
and the deployed model reloads from the ENCRYPTED artifact (the plaintext was deleted when it was protected).
"""
import json, os
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "tests" / "results" / ".state.json"


@pytest.mark.skipif(not STATE.exists(), reason="run test_integration.py first")
def test_after_restart(api):
    s = json.load(open(STATE)); A = s["A"]
    import sys; sys.path.insert(0, str(ROOT))
    from backend.app import config
    storage = config.STORAGE_DIR
    assert not (storage / "models" / A / "model.joblib").exists(), "plaintext must not exist at rest"
    assert (storage / "models" / A / "model.enc").exists()
    me = api.get("/auth/me", s["dev_token"]); assert me.status_code == 200 and me.json()["username"] == s["dev_user"]   # session persisted
    m = api.get(f"/models/{A}", s["dev_token"]).json()
    assert m["status"] == "registered" and m["blockchain"]["tx_hash"] == s["A_tx"] and m["crypto"]["merkle"]["root"] == s["A_root"]
    # the in-memory deployment was lost on restart; inference must transparently reload from the encrypted artifact
    p = api.post(f"/models/{A}/predict", s["dev_token"], json={"inputs": [s["A_sample"]["inputs"]]})
    assert p.status_code == 200 and p.json()["predictions"][0]["prediction"] == s["A_pred"]
    assert api.post(f"/models/{A}/verify", s["dev_token"]).json()["status"] == "PASS"
    assert api.get("/marketplace/models", s["dev_token"]).json()
    h = api.get("/health").json(); assert h["chain"]["connected"]
