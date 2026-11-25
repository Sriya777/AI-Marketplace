"""Phase 4 endpoints: blockchain registration and retrieval."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import chain, registration
from ..deps import current_user, get_model_or_404, owned_model, require_developer
from ..views import model_view

router = APIRouter()


class Password(BaseModel):
    password: str


class Confirm(BaseModel):
    tx_hash: str


class LinkWallet(BaseModel):
    address: str


@router.get("/chain/status")
def chain_status():
    return chain.status()


@router.get("/chain/config")
def chain_config():
    if not chain.is_available():
        raise HTTPException(503, chain.status().get("error", "blockchain unavailable"))
    return chain.config_for_frontend()


@router.post("/models/{model_id}/register")
def register(model_id: str, body: Password, m=Depends(owned_model), user=Depends(current_user)):
    """Registers the REAL hashes / Merkle root / signature with a real transaction from the developer's wallet."""
    return registration.register_custodial(m, user, body.password)


@router.get("/models/{model_id}/chain-payload")
def chain_payload(model_id: str, m=Depends(owned_model), user=Depends(current_user)):
    if m["status"] not in ("protected", "packaged", "deployed"): raise HTTPException(409, "model must be packaged (and not yet registered)")
    return registration.payload_json(m, user)


@router.post("/models/{model_id}/register/confirm")
def register_confirm(model_id: str, body: Confirm, m=Depends(owned_model), user=Depends(current_user)):
    return registration.register_confirm(m, user, body.tx_hash)


@router.get("/models/{model_id}/onchain")
def onchain(model_id: str, user=Depends(current_user)):
    """Reads the record directly from the contract (the authoritative source)."""
    if not chain.is_available(): raise HTTPException(503, "blockchain unavailable")
    rec = chain.get_record(model_id)
    if rec is None: raise HTTPException(404, "model is not registered on the blockchain")
    m = get_model_or_404(model_id)
    return {"record": rec, "transaction": m.get("blockchain")}


@router.post("/me/wallets/link")
def link_wallet(body: LinkWallet, user=Depends(require_developer)):
    return registration.link_wallet(user, body.address)
