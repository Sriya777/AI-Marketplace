"""Phase 6 endpoints: integrity verification + tamper tests + logs, and the dashboard."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import chain, tamper, verification
from ..db import get_db
from ..deps import current_user, get_model_or_404, owned_model

router = APIRouter()


class TestBody(BaseModel):
    password: Optional[str] = None


@router.post("/models/{model_id}/verify")
def verify(model_id: str, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if m["status"] != "registered": raise HTTPException(409, "only blockchain-registered models can be verified end-to-end")
    return verification.verify_model(m, actor=user["username"], kind="verification", label="manual")


@router.get("/security/tests")
def list_tests(user=Depends(current_user)):
    return [{"id": k, "title": t, "expected": e} for k, (t, e) in tamper.TESTS.items()]


@router.post("/security/{model_id}/tests/{test_name}")
def run_test(model_id: str, test_name: str, body: TestBody = TestBody(), m=Depends(owned_model), user=Depends(current_user)):
    if test_name not in tamper.TESTS: raise HTTPException(404, "unknown test")
    if m["status"] != "registered": raise HTTPException(409, "security tests need a blockchain-registered model")
    if not chain.is_available(): raise HTTPException(503, "blockchain unavailable")
    return tamper.run_test(test_name, m, user, body.password)


@router.post("/security/{model_id}/run-all")
def run_all(model_id: str, body: TestBody = TestBody(), m=Depends(owned_model), user=Depends(current_user)):
    if m["status"] != "registered": raise HTTPException(409, "security tests need a blockchain-registered model")
    if not chain.is_available(): raise HTTPException(503, "blockchain unavailable")
    return tamper.run_all(m, user, body.password)


@router.get("/security/logs")
def logs(model_id: Optional[str] = None, limit: int = 50, user=Depends(current_user)):
    flt = {"model_id": model_id} if model_id else {}
    out = []
    for l in get_db().verification_logs.find(flt, sort=[("at", -1)], limit=min(limit, 200)):
        l["id"] = l.pop("_id"); l.pop("checks", None); out.append(l)
    return out


@router.get("/dashboard/stats")
def stats(user=Depends(current_user)):
    db = get_db()
    mine = {"owner_id": user["_id"]} if user["role"] == "developer" else {}
    models = db.models.find(mine)
    logs = db.verification_logs.find({"kind": "verification"})
    tests = db.verification_logs.find({"kind": "tamper_test"})
    return {
        "models_total": len(models),
        "models_trained": sum(1 for m in models if m.get("training", {}).get("status") == "completed"),
        "models_deployed": sum(1 for m in models if m.get("deployment", {}).get("status") == "deployed"),
        "models_protected": sum(1 for m in models if m["status"] in ("protected", "registered")),
        "models_registered": db.models.count_documents({"status": "registered"}) if user["role"] == "buyer" else sum(1 for m in models if m["status"] == "registered"),
        "verifications_passed": sum(1 for l in logs if l["status"] == "PASS"),
        "verifications_failed": sum(1 for l in logs if l["status"] != "PASS"),
        "tamper_tests_run": len(tests), "tamper_tests_as_expected": sum(1 for l in tests if l.get("matched")),
        "access_denied": db.verification_logs.count_documents({"kind": "distribution", "status": "DENIED"}),
        "datasets": db.datasets.count_documents({"owner_id": user["_id"]}),
        "pending_requests": db.grants.count_documents({"owner_id": user["_id"], "status": "pending"}),
        "chain": chain.status(),
    }
