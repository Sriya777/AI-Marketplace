# Test report

Generated: 2026-11-17T13:00:39Z  
Python 3.12.3 · Node v22.23.4 · scikit-learn 1.9.1 · web3 8.0.0 · FastAPI 0.162.5 · cryptography 50.0.2  
Database under test: **file-fallback**  ·  Chain: Hardhat chain 31337 contract 0x5FbDB2315678afecb367f032d93F642f64180aa3

| Suite | Result | Summary |
|---|---|---|
| Cryptography unit tests (+CIFAR conversion) | PASS | 28 passed in 2.80s  |
| Smart contract tests (live chain) | PASS | 17/17 contract tests passed |
| Integration tests (API + MongoDB/fallback + blockchain) | PASS | 28 passed in 14.22s  |
| Persistence across restart (encrypted-artifact reload) | PASS | 1 passed in 0.22s  |
| Endpoint coverage (every API operation exercised) | PASS | endpoint coverage: 55/55 |

Raw outputs: `tests/results/*.txt`. Browser screenshots: `tests/results/screenshots/` (if the browser test was run).
