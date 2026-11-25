# Backend (FastAPI)

```bash
uvicorn backend.app.main:app --port 8000        # from the project root, with .env present
```

Interactive docs: http://127.0.0.1:8000/docs · health: `/api/health`.

| Module | Responsibility |
|---|---|
| `routers/` | HTTP API (auth, datasets, models, crypto, chain, marketplace, security) – 55 endpoints |
| `ml.py` | dataset validation, preprocessing, training with progress, evaluation, deployment, inference |
| `protection.py` | SHA3-256 → AES-256-GCM → Merkle → ECDSA signing (Phase 3) |
| `registration.py`, `chain.py` | blockchain registration / reads via web3.py (Phase 4) |
| `verification.py` | 8 integrity checks against the on-chain record, Merkle chunk proofs |
| `distribution.py` | grants, licenses, authorization + ECC key exchange + decryption (Phase 5) |
| `tamper.py` | the 6 security tests (Phase 6) |
| `accounts.py`, `pki.py` | users/sessions/key stores · local X.509 CA + master secret |
| `db.py` | MongoDB, or the persistent file-backed development fallback (single process only) |
| `artifacts.py` | where model files live (`storage/models/<id>/model.enc`) |

Configuration: see `../.env.example`.
