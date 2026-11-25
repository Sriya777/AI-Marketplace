"""
main.py - FastAPI application: AI Model Marketplace backend.

Run (from the project root):   uvicorn backend.app.main:app --port 8000
"""
import threading
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import accounts, chain, config, pki
from .db import get_db
from .distribution import DistributionError
from .routers import auth, chain as chain_router, crypto, datasets, marketplace, models, security

app = FastAPI(title="Decentralized AI Model Marketplace", version="2.0.0",
              description="Training -> deployment -> AES-GCM/SHA3/ECDSA/Merkle/X.509 -> blockchain -> secure distribution")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


_log_lock = threading.Lock()


@app.middleware("http")
async def access_log(request: Request, call_next):
    response = await call_next(request)
    if config.ACCESS_LOG and request.url.path.startswith("/api"):
        with _log_lock, open(config.ACCESS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{request.method} {request.url.path} {response.status_code}\n")
    return response


@app.on_event("startup")
def startup():
    pki.init()                       # fail fast with a clear message if the master passphrase is missing
    get_db()
    chain.is_available()
    print("[startup] chain:", chain.status())


@app.exception_handler(accounts.AccountError)
async def account_error(request: Request, exc: accounts.AccountError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(DistributionError)
async def distribution_error(request: Request, exc: DistributionError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.reason, "steps": exc.report})


@app.exception_handler(pki.ConfigError)
async def config_error(request: Request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version, "database": get_db().status(), "chain": chain.status(),
            "ca": {"initialised": bool(pki._state)}}


for r in (auth.router, datasets.router, models.router, crypto.router, chain_router.router, marketplace.router, security.router):
    app.include_router(r, prefix="/api")
