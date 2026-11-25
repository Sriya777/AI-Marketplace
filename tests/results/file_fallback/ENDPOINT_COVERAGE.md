# Endpoint coverage

**55 / 55** API operations were called during the automated test run.

| Method | Path | Calls | Status codes seen |
|---|---|---|---|
| POST | `/api/auth/login` | 6 | 200×5, 401×1 |
| POST | `/api/auth/logout` | 2 | 200×1, 401×1 |
| GET | `/api/auth/me` | 8 | 200×5, 401×3 |
| POST | `/api/auth/register` | 8 | 201×4, 400×3, 409×1 |
| GET | `/api/ca/certificate` | 1 | 200×1 |
| POST | `/api/certificates/validate` | 3 | 200×3 |
| GET | `/api/chain/config` | 1 | 200×1 |
| GET | `/api/chain/status` | 1 | 200×1 |
| GET | `/api/dashboard/stats` | 2 | 200×2 |
| GET | `/api/datasets` | 2 | 200×2 |
| GET | `/api/datasets/samples` | 1 | 200×1 |
| POST | `/api/datasets/samples/{name}/use` | 3 | 201×3 |
| POST | `/api/datasets/upload` | 8 | 201×7, 422×1 |
| GET | `/api/datasets/{dataset_id}` | 1 | 404×1 |
| GET | `/api/downloads/{token}` | 3 | 200×1, 401×1, 404×1 |
| POST | `/api/downloads/{token}/predict` | 1 | 200×1 |
| GET | `/api/health` | 5 | 200×5 |
| GET | `/api/marketplace/incoming` | 3 | 200×2, 403×1 |
| GET | `/api/marketplace/licenses` | 1 | 200×1 |
| GET | `/api/marketplace/models` | 3 | 200×3 |
| GET | `/api/marketplace/models/{model_id}` | 2 | 200×1, 404×1 |
| POST | `/api/marketplace/models/{model_id}/access` | 14 | 200×5, 401×2, 403×6, 409×1 |
| POST | `/api/marketplace/models/{model_id}/access-request` | 6 | 201×5, 400×1 |
| GET | `/api/marketplace/models/{model_id}/encrypted` | 3 | 200×1, 401×1, 404×1 |
| GET | `/api/marketplace/my-requests` | 2 | 200×2 |
| POST | `/api/marketplace/requests/{grant_id}/decision` | 5 | 200×2, 403×1, 404×1, 409×1 |
| POST | `/api/me/wallets/link` | 2 | 200×1, 422×1 |
| GET | `/api/ml/algorithms` | 1 | 200×1 |
| GET | `/api/models` | 1 | 200×1 |
| POST | `/api/models/train` | 23 | 202×12, 403×1, 404×2, 422×8 |
| GET | `/api/models/{model_id}` | 8 | 200×7, 403×1 |
| GET | `/api/models/{model_id}/chain-payload` | 1 | 200×1 |
| GET | `/api/models/{model_id}/crypto` | 1 | 200×1 |
| POST | `/api/models/{model_id}/crypto/encrypt` | 3 | 200×1, 409×2 |
| POST | `/api/models/{model_id}/crypto/hash` | 4 | 200×1, 409×3 |
| POST | `/api/models/{model_id}/crypto/merkle` | 3 | 200×1, 409×2 |
| POST | `/api/models/{model_id}/crypto/sign` | 3 | 200×1, 401×1, 409×1 |
| POST | `/api/models/{model_id}/deploy` | 6 | 200×4, 403×1, 409×1 |
| GET | `/api/models/{model_id}/evaluation` | 5 | 200×1, 401×1, 403×1, 404×1, 409×1 |
| POST | `/api/models/{model_id}/license` | 4 | 200×2, 409×1, 422×1 |
| GET | `/api/models/{model_id}/merkle/proof` | 5 | 200×5 |
| POST | `/api/models/{model_id}/merkle/verify-chunk` | 7 | 200×5, 422×2 |
| GET | `/api/models/{model_id}/onchain` | 2 | 200×1, 404×1 |
| POST | `/api/models/{model_id}/predict` | 16 | 200×10, 403×1, 409×2, 422×3 |
| POST | `/api/models/{model_id}/protect` | 6 | 200×2, 403×2, 409×2 |
| POST | `/api/models/{model_id}/register` | 7 | 200×2, 401×1, 403×2, 409×2 |
| POST | `/api/models/{model_id}/register/confirm` | 4 | 200×1, 400×2, 403×1 |
| GET | `/api/models/{model_id}/schema` | 2 | 200×2 |
| GET | `/api/models/{model_id}/training` | 29 | 200×29 |
| POST | `/api/models/{model_id}/undeploy` | 3 | 200×2, 403×1 |
| POST | `/api/models/{model_id}/verify` | 7 | 200×6, 409×1 |
| GET | `/api/security/logs` | 2 | 200×2 |
| GET | `/api/security/tests` | 1 | 200×1 |
| POST | `/api/security/{model_id}/run-all` | 4 | 200×1, 403×2, 409×1 |
| POST | `/api/security/{model_id}/tests/{test_name}` | 2 | 200×1, 404×1 |
