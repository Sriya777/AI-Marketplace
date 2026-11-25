"""
config.py - all runtime configuration, read from environment variables (optionally a .env file
in the project root). See .env.example for documentation of every variable.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------------ general
ENV = os.environ.get("MARKETPLACE_ENV", "development")
STORAGE_DIR = Path(os.environ.get("MARKETPLACE_STORAGE", str(ROOT / "storage")))
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "12"))
CHUNK_SIZE = int(os.environ.get("MERKLE_CHUNK_SIZE", str(16 * 1024)))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
DOWNLOAD_TTL_SECONDS = int(os.environ.get("DOWNLOAD_TTL_SECONDS", "600"))
# Optional audit/coverage log: if set, every /api call is appended as "METHOD path status" (used by tests/endpoint_coverage.py)
ACCESS_LOG = os.environ.get("API_ACCESS_LOG", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

# Operator passphrase: protects the CA private key and the content-key escrow.
# It is read from the environment only and is NEVER written to the database or storage.
MASTER_PASSPHRASE = os.environ.get("MARKETPLACE_MASTER_PASSPHRASE", "")

# ------------------------------------------------------------------ database
DB_MODE = os.environ.get("DB_MODE", "auto").lower()          # auto | mongo | file
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "model_marketplace")

# ------------------------------------------------------------------ blockchain
CHAIN_RPC_URL = os.environ.get("CHAIN_RPC_URL", "http://127.0.0.1:8545")
# Hardhat's well-known Account #0. LOCAL DEVELOPMENT ONLY - override for any real network.
CHAIN_ADMIN_PRIVATE_KEY = os.environ.get(
    "CHAIN_ADMIN_PRIVATE_KEY",
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
DEPLOYMENT_FILE = Path(os.environ.get("DEPLOYMENT_FILE", str(ROOT / "blockchain" / "deployment.json")))
ARTIFACT_FILE = Path(os.environ.get("CONTRACT_ARTIFACT", str(ROOT / "blockchain" / "artifacts-custom" / "ModelRegistry.json")))
AUTO_FUND_WALLETS = _bool("AUTO_FUND_WALLETS", True)          # local chain only: give new developer wallets test ETH
FUND_AMOUNT_ETH = float(os.environ.get("FUND_AMOUNT_ETH", "5"))
