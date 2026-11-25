# Endpoint coverage

**55 / 55** API operations were called during the automated test run.

| Method | Path | Calls | Status codes seen |
|---|---|---|---|
| POST | `/api/auth/login` | 21 | 200×19, 401×2 |
| POST | `/api/auth/logout` | 12 | 200×11, 401×1 |
| GET | `/api/auth/me` | 51 | 200×48, 401×3 |
| POST | `/api/auth/register` | 14 | 201×9, 400×4, 409×1 |
| GET | `/api/ca/certificate` | 1 | 200×1 |
| POST | `/api/certificates/validate` | 3 | 200×3 |
| GET | `/api/chain/config` | 14 | 200×14 |
| GET | `/api/chain/status` | 10 | 200×10 |
| GET | `/api/dashboard/stats` | 25 | 200×25 |
| GET | `/api/datasets` | 8 | 200×8 |
| GET | `/api/datasets/samples` | 3 | 200×3 |
| POST | `/api/datasets/samples/{name}/use` | 6 | 201×6 |
| POST | `/api/datasets/upload` | 10 | 201×9, 422×1 |
| GET | `/api/datasets/{dataset_id}` | 1 | 404×1 |
| GET | `/api/downloads/{token}` | 4 | 200×2, 401×1, 404×1 |
| POST | `/api/downloads/{token}/predict` | 2 | 200×2 |
| GET | `/api/health` | 27 | 200×27 |
| GET | `/api/marketplace/incoming` | 6 | 200×5, 403×1 |
| GET | `/api/marketplace/licenses` | 1 | 200×1 |
| GET | `/api/marketplace/models` | 7 | 200×7 |
| GET | `/api/marketplace/models/{model_id}` | 15 | 200×14, 404×1 |
| POST | `/api/marketplace/models/{model_id}/access` | 17 | 200×7, 401×3, 403×6, 409×1 |
| POST | `/api/marketplace/models/{model_id}/access-request` | 9 | 201×8, 400×1 |
| GET | `/api/marketplace/models/{model_id}/encrypted` | 4 | 200×2, 401×1, 404×1 |
| GET | `/api/marketplace/my-requests` | 6 | 200×6 |
| POST | `/api/marketplace/requests/{grant_id}/decision` | 7 | 200×4, 403×1, 404×1, 409×1 |
| POST | `/api/me/wallets/link` | 3 | 200×2, 422×1 |
| GET | `/api/ml/algorithms` | 3 | 200×3 |
| GET | `/api/models` | 47 | 200×47 |
| POST | `/api/models/train` | 27 | 202×16, 403×1, 404×2, 422×8 |
| GET | `/api/models/{model_id}` | 35 | 200×34, 403×1 |
| GET | `/api/models/{model_id}/chain-payload` | 5 | 200×5 |
| GET | `/api/models/{model_id}/crypto` | 2 | 200×2 |
| POST | `/api/models/{model_id}/crypto/encrypt` | 4 | 200×2, 409×2 |
| POST | `/api/models/{model_id}/crypto/hash` | 5 | 200×2, 409×3 |
| POST | `/api/models/{model_id}/crypto/merkle` | 4 | 200×2, 409×2 |
| POST | `/api/models/{model_id}/crypto/sign` | 4 | 200×2, 401×1, 409×1 |
| POST | `/api/models/{model_id}/deploy` | 11 | 200×9, 403×1, 409×1 |
| GET | `/api/models/{model_id}/evaluation` | 5 | 200×1, 401×1, 403×1, 404×1, 409×1 |
| POST | `/api/models/{model_id}/license` | 5 | 200×3, 409×1, 422×1 |
| GET | `/api/models/{model_id}/merkle/proof` | 5 | 200×5 |
| POST | `/api/models/{model_id}/merkle/verify-chunk` | 8 | 200×6, 422×2 |
| GET | `/api/models/{model_id}/onchain` | 5 | 200×4, 404×1 |
| POST | `/api/models/{model_id}/predict` | 19 | 200×12, 403×1, 409×3, 422×3 |
| POST | `/api/models/{model_id}/protect` | 8 | 200×4, 403×2, 409×2 |
| POST | `/api/models/{model_id}/register` | 9 | 200×4, 401×1, 403×2, 409×2 |
| POST | `/api/models/{model_id}/register/confirm` | 5 | 200×2, 400×2, 403×1 |
| GET | `/api/models/{model_id}/schema` | 5 | 200×5 |
| GET | `/api/models/{model_id}/training` | 38 | 200×38 |
| POST | `/api/models/{model_id}/undeploy` | 4 | 200×3, 403×1 |
| POST | `/api/models/{model_id}/verify` | 11 | 200×10, 409×1 |
| GET | `/api/security/logs` | 29 | 200×29 |
| GET | `/api/security/tests` | 2 | 200×2 |
| POST | `/api/security/{model_id}/run-all` | 5 | 200×2, 403×2, 409×1 |
| POST | `/api/security/{model_id}/tests/{test_name}` | 2 | 200×1, 404×1 |
