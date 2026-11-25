"""FastAPI dependencies: authentication, role checks, model lookup."""
from fastapi import Depends, Header, HTTPException

from . import accounts
from .db import get_db


def current_user(authorization: str = Header(default="")):
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    u = accounts.user_from_token(token)
    if not u:
        raise HTTPException(401, "authentication required (missing/invalid/expired token)")
    return u


def require_developer(user=Depends(current_user)):
    if user["role"] != "developer":
        raise HTTPException(403, "this action requires a developer account")
    return user


def get_model_or_404(model_id: str) -> dict:
    m = get_db().models.find_one({"_id": model_id})
    if not m:
        raise HTTPException(404, f"model '{model_id}' not found")
    return m


def owned_model(model_id: str, user=Depends(require_developer)) -> dict:
    m = get_model_or_404(model_id)
    if m["owner_id"] != user["_id"]:
        raise HTTPException(403, "you do not own this model")
    return m


def strip(doc: dict, extra_hidden=()) -> dict:
    """Remove internal/secret fields before returning a document through the API."""
    hidden = {"_id_", *extra_hidden}
    out = {k: v for k, v in doc.items() if k not in hidden}
    if "_id" in out:
        out["id"] = out.pop("_id")
    return out
