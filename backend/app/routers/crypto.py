"""Phase 3 endpoints: the applied-cryptography pipeline."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import protection, verification
from ..db import get_db
from ..deps import current_user, get_model_or_404, owned_model
from ..views import model_view

router = APIRouter()


class Password(BaseModel):
    password: str


class LicenseBody(BaseModel):
    license: str


class ChunkBody(BaseModel):
    index: int


@router.post("/models/{model_id}/license")
def set_license(model_id: str, body: LicenseBody, m=Depends(owned_model)):
    protection.set_license(model_id, body.license)
    return {"license": body.license}


@router.post("/models/{model_id}/crypto/hash")
def hash_step(model_id: str, m=Depends(owned_model)):
    return protection.step_hash(model_id)


@router.post("/models/{model_id}/crypto/encrypt")
def encrypt_step(model_id: str, m=Depends(owned_model), user=Depends(current_user)):
    return protection.step_encrypt(model_id, user)


@router.post("/models/{model_id}/crypto/merkle")
def merkle_step(model_id: str, m=Depends(owned_model)):
    return protection.step_merkle(model_id)


@router.post("/models/{model_id}/crypto/sign")
def sign_step(model_id: str, body: Password, m=Depends(owned_model), user=Depends(current_user)):
    return protection.step_sign(model_id, user, body.password)


@router.post("/models/{model_id}/protect")
def protect(model_id: str, body: Password, m=Depends(owned_model), user=Depends(current_user)):
    """Runs hash -> encrypt -> merkle -> sign in order, each step consuming the previous step's output."""
    return protection.protect_all(model_id, user, body.password)


@router.get("/models/{model_id}/crypto")
def crypto_summary(model_id: str, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if m["owner_id"] != user["_id"] and m["status"] != "registered":
        raise HTTPException(403, "private to its developer")
    cr = model_view(m)["crypto"] if m.get("crypto") else {}
    return {"id": model_id, "status": m["status"], "license": m["license"], "crypto": cr, "lifecycle": model_view(m)["lifecycle"]}


@router.get("/models/{model_id}/merkle/proof")
def merkle_proof(model_id: str, index: int, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if not m.get("crypto", {}).get("merkle"): raise HTTPException(409, "Merkle tree not built yet")
    try:
        return verification.chunk_proof(m, index)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/models/{model_id}/merkle/verify-chunk")
def merkle_verify_chunk(model_id: str, body: ChunkBody, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if not m.get("crypto", {}).get("merkle"): raise HTTPException(409, "Merkle tree not built yet")
    try:
        return verification.verify_chunk(m, body.index)
    except ValueError as e:
        raise HTTPException(422, str(e))
