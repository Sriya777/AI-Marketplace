"""Phase 5 endpoints: marketplace browsing, access requests, secure download + inference on the distributed copy."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import artifacts, distribution as dist
from ..db import get_db
from ..deps import current_user, get_model_or_404, require_developer
from ..views import marketplace_view

router = APIRouter()


class AccessReq(BaseModel):
    note: str = ""


class Decision(BaseModel):
    approve: bool


class AccessBody(BaseModel):
    password: str


class PredictBody(BaseModel):
    inputs: Any


@router.get("/marketplace/licenses")
def licenses():
    return [{"id": k, **v} for k, v in dist.LICENSES.items()]


@router.get("/marketplace/models")
def browse(user=Depends(current_user)):
    return [marketplace_view(m) for m in get_db().models.find({"status": "registered"}, sort=[("created_at", -1)])]


@router.get("/marketplace/models/{model_id}")
def detail(model_id: str, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if m["status"] != "registered": raise HTTPException(404, "model not in the marketplace")
    v = marketplace_view(m)
    v["per_class"], v["confusion_matrix"] = m.get("per_class"), m.get("confusion_matrix")
    v["classes"], v["feature_columns"] = m.get("classes"), m.get("feature_columns")
    v["license_terms"] = dist.LICENSES[m["license"]]
    g = get_db().grants.find_one({"model_id": model_id, "buyer_id": user["_id"]}, sort=[("requested_at", -1)])
    v["my_access"] = dist.public_grant(g) if g else None
    v["is_owner"] = m["owner_id"] == user["_id"]
    return v


@router.get("/marketplace/models/{model_id}/encrypted")
def encrypted_artifact(model_id: str, user=Depends(current_user)):
    """
    The AES-256-GCM encrypted artifact (ciphertext only). It is deliberately retrievable by any signed-in user: it is
    useless without the content key, and anyone can check its SHA3-256 / Merkle root against the blockchain record.
    """
    m = get_model_or_404(model_id)
    if m["status"] != "registered": raise HTTPException(404, "model not in the marketplace")
    path = artifacts.enc_path(model_id)
    if not path.exists(): raise HTTPException(500, "encrypted artifact missing in storage")
    return FileResponse(path, media_type="application/octet-stream", filename=f"{model_id}_{m['version']}.enc",
                        headers={"X-Encrypted-SHA3-256": m["crypto"]["encrypted_sha3"]})


@router.post("/marketplace/models/{model_id}/access-request", status_code=201)
def request_access(model_id: str, body: AccessReq, user=Depends(current_user)):
    return dist.request_access(user, model_id, body.note)


@router.get("/marketplace/my-requests")
def my_requests(user=Depends(current_user)):
    return [dist.public_grant(g) for g in get_db().grants.find({"buyer_id": user["_id"]}, sort=[("requested_at", -1)])]


@router.get("/marketplace/incoming")
def incoming(user=Depends(require_developer)):
    return [dist.public_grant(g) for g in get_db().grants.find({"owner_id": user["_id"]}, sort=[("requested_at", -1)])]


@router.post("/marketplace/requests/{grant_id}/decision")
def decision(grant_id: str, body: Decision, user=Depends(require_developer)):
    return dist.decide(user, grant_id, body.approve)


@router.post("/marketplace/models/{model_id}/access")
def access(model_id: str, body: AccessBody, user=Depends(current_user)):
    """Verify everything against the blockchain, run the ECC key exchange, decrypt, and issue a download token."""
    return dist.authorize_and_decrypt(user, model_id, body.password)


@router.get("/downloads/{token}")
def download(token: str, user=Depends(current_user)):
    d = dist.get_download(user, token)
    dist.mark_fetched(d)
    return FileResponse(d["path"], media_type="application/octet-stream", filename=d["filename"])


@router.post("/downloads/{token}/predict")
def predict_downloaded(token: str, body: PredictBody, user=Depends(current_user)):
    try:
        return dist.predict_distributed(user, token, body.inputs)
    except ValueError as e:
        raise HTTPException(422, str(e))
