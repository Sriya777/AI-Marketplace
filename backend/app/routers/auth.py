from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from .. import accounts, chain, pki
from ..deps import current_user
from crypto import identity as idn

router = APIRouter()


class Register(BaseModel):
    username: str
    password: str
    role: str


class Login(BaseModel):
    username: str
    password: str


class CertIn(BaseModel):
    cert_pem: str


@router.post("/auth/register", status_code=201)
def register(body: Register):
    u = accounts.create_user(body.username, body.password, body.role)
    return accounts.public_user(u)


@router.post("/auth/login")
def login(body: Login):
    return accounts.login(body.username, body.password)


@router.post("/auth/logout")
def logout(authorization: str = Header(default=""), user=Depends(current_user)):
    accounts.logout(authorization[7:])
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    out = accounts.public_user(user)
    out["certificate_status"] = accounts.cert_status(user)
    if user.get("wallet_address") and chain.is_available():
        try:
            out["wallet_balance_eth"] = chain.balance_eth(user["wallet_address"])
            out["wallet_authorized"] = chain.is_authorized(user["wallet_address"])
        except Exception:
            pass
    return out


@router.get("/ca/certificate")
def ca_certificate():
    c = pki.ca_cert()
    return {"pem": idn.cert_to_pem(c).decode(), "summary": idn.cert_summary(c)}


@router.post("/certificates/validate")
def validate_certificate(body: CertIn, user=Depends(current_user)):
    try:
        return pki.validate_cert_pem(body.cert_pem)
    except Exception as e:
        return {"valid": False, "checks": [], "reason": f"not a parsable X.509 certificate: {str(e)[:100]}"}
