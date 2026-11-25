import json, os, sys, time
from pathlib import Path
import pytest, requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = os.environ.get("API_URL", "http://127.0.0.1:8000/api")


class Api:
    def __init__(self): self.s = requests.Session()
    def call(self, method, path, token=None, **kw):
        h = {"Authorization": f"Bearer {token}"} if token else {}
        return self.s.request(method, BASE + path, headers=h, timeout=240, **kw)
    def get(self, p, t=None, **kw): return self.call("GET", p, t, **kw)
    def post(self, p, t=None, **kw): return self.call("POST", p, t, **kw)


@pytest.fixture(scope="session")
def api(): return Api()

@pytest.fixture(scope="session")
def S():
    """Shared state across the ordered integration tests."""
    return {}

def wait_trained(api, token, model_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = api.get(f"/models/{model_id}/training", token).json()
        if s["training"]["status"] != "running":
            return s
        time.sleep(0.4)
    raise TimeoutError("training did not finish")

@pytest.fixture(scope="session")
def helpers():
    return type("H", (), {"wait_trained": staticmethod(wait_trained)})
