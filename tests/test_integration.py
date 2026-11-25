"""
End-to-end integration tests. They talk to a LIVE backend (real MongoDB or the file fallback, real Hardhat
chain) over HTTP, and independently re-verify results by reading the chain / database / storage directly.

Run (services must be running):   pytest tests/test_integration.py -v
Order matters: later tests use the models created by earlier ones.
"""
import base64, hashlib, io, json, os, secrets, sys
from pathlib import Path

import joblib, pytest
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crypto import identity as idn, keystore, keywrap, crypto_core as cc, merkle as mk   # noqa: E402

SUF = secrets.token_hex(3)
DEV, DEV2, BUY, BUY2 = f"alice_{SUF}", f"dave_{SUF}", f"bob_{SUF}", f"carol_{SUF}"
PW = "S3cure-pass-phrase"
from backend.app import config as _cfg   # loads the same .env the server uses
STORAGE = _cfg.STORAGE_DIR
FIELDS = ["modelId", "version", "creator", "originalHash", "encryptedHash", "merkleRoot", "metadataHash",
          "signature", "creatorPubKey", "licenseTerms", "registeredAt", "registeredBlock", "revoked", "exists"]


def get_db():
    """The same database the server uses; refreshed so the file-backed fallback shows the server's latest writes."""
    from backend.app.db import get_db as _g
    return _g().refresh()


def chain_record(model_id):
    """Independent chain read straight from the contract (bypasses the backend completely)."""
    dep = json.loads((ROOT / "blockchain" / "deployment.json").read_text())
    abi = json.loads((ROOT / "blockchain" / "artifacts-custom" / "ModelRegistry.json").read_text())["abi"]
    w3 = Web3(Web3.HTTPProvider(dep["rpcUrl"]))
    c = w3.eth.contract(address=dep["address"], abi=abi)
    return w3, c, dict(zip(FIELDS, c.functions.getRecord(model_id).call()))


def sha3(b): return hashlib.sha3_256(b).hexdigest()


def tok(api, u, p=PW): return api.post("/auth/login", json={"username": u, "password": p}).json()["token"]


# ============================================================ 1. platform health
def test_01_health_reports_real_dependencies(api):
    h = api.get("/health").json()
    assert h["status"] == "ok" and h["chain"]["connected"] is True and h["chain"]["chainId"] == 31337
    expect = os.environ.get("EXPECT_DB")
    if expect: assert h["database"]["mode"] == expect, h["database"]
    assert h["ca"]["initialised"]
    print("\n   database:", h["database"]["mode"], "| chain block", h["chain"]["blockNumber"])


# ============================================================ 2. auth, roles, certificates
def test_02_registration_login_roles(api, S):
    for u, role in [(DEV, "developer"), (DEV2, "developer"), (BUY, "buyer"), (BUY2, "buyer")]:
        r = api.post("/auth/register", json={"username": u, "password": PW, "role": role})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["certificate"]["role"] == role and body["certificate"]["issuer"].startswith("CN=Marketplace Local Root CA")
        assert bool(body.get("wallet_address")) == (role == "developer")
        assert "password" not in json.dumps(body) and "private" not in json.dumps(body).lower()
    assert api.post("/auth/register", json={"username": DEV, "password": PW, "role": "developer"}).status_code == 409
    assert api.post("/auth/register", json={"username": "x" + SUF, "password": "short", "role": "buyer"}).status_code == 400
    assert api.post("/auth/register", json={"username": "bad name!", "password": PW, "role": "buyer"}).status_code == 400
    assert api.post("/auth/register", json={"username": "z" + SUF, "password": PW, "role": "admin"}).status_code == 400
    assert api.post("/auth/login", json={"username": DEV, "password": "wrong-password"}).status_code == 401
    S["dev"], S["dev2"], S["buy"], S["buy2"] = tok(api, DEV), tok(api, DEV2), tok(api, BUY), tok(api, BUY2)
    assert api.get("/auth/me").status_code == 401                                      # no token
    assert api.get("/auth/me", "garbage").status_code == 401                           # bad token
    me = api.get("/auth/me", S["dev"]).json()
    assert me["certificate_status"]["valid"] and me["wallet_authorized"] is True and me["wallet_balance_eth"] > 0
    S["dev_wallet"] = me["wallet_address"]
    # role enforcement
    assert api.post("/models/train", S["buy"], json={"dataset_id": "x"}).status_code == 403
    assert api.post("/datasets/samples/iris/use", S["buy"]).status_code == 201         # buyers may use datasets
    assert api.get("/marketplace/incoming", S["buy"]).status_code == 403


def test_02b_logout_invalidates_the_session_server_side(api, S):
    t = tok(api, DEV)
    assert api.get("/auth/me", t).status_code == 200
    assert api.post("/auth/logout", t).json() == {"ok": True}
    assert api.get("/auth/me", t).status_code == 401                    # the token is dead on the server, not just forgotten by the browser
    assert api.post("/auth/logout", t).status_code == 401
    assert api.get("/auth/me", S["dev"]).status_code == 200             # other sessions of the same user are unaffected


def test_03_x509_certificates(api, S):
    ca = api.get("/ca/certificate").json()
    me = api.get("/auth/me", S["dev"]).json()
    pem = None
    pem = get_db().users.find_one({"username": DEV})["cert_pem"]
    ok = api.post("/certificates/validate", S["dev"], json={"cert_pem": pem}).json()
    assert ok["valid"] and all(c["ok"] for c in ok["checks"]) and ok["certificate"]["commonName"] == DEV
    # a certificate from a rogue CA must be rejected
    rk, rca = idn.create_self_signed_ca("Rogue CA")
    _, pub = idn.generate_ec_keypair()
    rogue = idn.cert_to_pem(idn.issue_developer_cert(rk, rca, pub, DEV, role="developer")).decode()
    bad = api.post("/certificates/validate", S["dev"], json={"cert_pem": rogue}).json()
    assert not bad["valid"] and "CA signature on certificate" in bad["reason"]
    junk = api.post("/certificates/validate", S["dev"], json={"cert_pem": "not a cert"}).json()
    assert junk["valid"] is False


# ============================================================ 3. datasets + training
def test_04_dataset_validation_rejects_bad_data(api, S):
    cases = {
        "too_few_rows.csv": "a,b,y\n1,2,x\n3,4,y\n",
        "one_class.csv": "a,b,y\n" + "\n".join(f"{i},{i*2},same" for i in range(60)),
        "single_sample_class.csv": "a,b,y\n" + "\n".join(f"{i},{i%7},{'A' if i<59 else 'B'}" for i in range(60)),
        "one_column.csv": "y\n" + "\n".join("a" for _ in range(60)),
        "continuous_target.csv": "a,b,y\n" + "\n".join(f"{i},{i%5},{i*1.37}" for i in range(80)),
    }
    for name, content in cases.items():
        r = api.post("/datasets/upload", S["dev"], files={"file": (name, content, "text/csv")})
        assert r.status_code == 201, r.text
        v = r.json()["validation"]
        assert v["valid"] is False and v["errors"], f"{name} was wrongly accepted: {v}"
        t = api.post("/models/train", S["dev"], json={"dataset_id": r.json()["id"], "algorithm": "random_forest"})
        assert t.status_code == 422, f"{name}: training on an invalid dataset must be refused"
    assert api.post("/datasets/upload", S["dev"], files={"file": ("x.txt", "hello", "text/plain")}).status_code == 422
    r = api.post("/datasets/upload", S["dev"], files={"file": ("garbage.csv", b"\x00\x01\x02\xff" * 50, "text/csv")})
    assert r.json()["validation"]["valid"] is False


def test_05_upload_real_dataset(api, S):
    content = (ROOT / "datasets" / "digits.csv").read_bytes()
    r = api.post("/datasets/upload", S["dev"], files={"file": ("digits.csv", content, "text/csv")}, data={"name": "digits-upload", "target_column": "digit"})
    assert r.status_code == 201
    d = r.json()
    assert d["validation"]["valid"] and d["validation"]["n_rows"] == 1797 and len(d["validation"]["classes"]) == 10
    assert d["sha3"] == sha3(content) and d["source"] == "upload"
    S["digits_ds"] = d["id"]
    assert api.get(f"/datasets/{d['id']}", S["dev2"]).status_code == 404                # other developers cannot see it
    iris = api.post("/datasets/samples/iris/use", S["dev"]).json()
    assert iris["validation"]["valid"]; S["iris_ds"] = iris["id"]


def test_06_every_algorithm_really_trains(api, S, helpers):
    algs = {a["id"] for a in api.get("/ml/algorithms", S["dev"]).json()}
    assert algs == {"random_forest", "gradient_boosting", "mlp_neural_net", "logistic_regression", "svm_rbf", "knn", "decision_tree"}
    S["iris_models"] = {}
    for alg in sorted(algs):
        r = api.post("/models/train", S["dev"], json={"dataset_id": S["iris_ds"], "algorithm": alg, "name": f"iris-{alg}"})
        assert r.status_code == 202, r.text
        mid = r.json()["id"]
        s = helpers.wait_trained(api, S["dev"], mid)
        assert s["training"]["status"] == "completed", (alg, s["training"].get("error"))
        m = s["metrics"]
        assert m["accuracy"] >= 0.85, (alg, m)
        cm = s["confusion_matrix"]["matrix"]
        assert sum(map(sum, cm)) == s["training"]["n_test"] == 30                         # confusion matrix covers exactly the held-out set
        assert {"precision_macro", "recall_macro", "f1_macro", "f1_weighted"} <= m.keys()
        assert len(s["per_class"]) == 3 and all(p["support"] == 10 for p in s["per_class"])
        art = STORAGE / "models" / mid / "model.joblib"
        assert sha3(art.read_bytes()) == s["training"]["artifact_sha3"]                   # recorded hash == real file
        S["iris_models"][alg] = mid
    mlp = api.get(f"/models/{S['iris_models']['mlp_neural_net']}/training", S["dev"]).json()["training"]
    assert len(mlp["history"]) == 40 and mlp["history"][-1]["loss"] < mlp["history"][0]["loss"]  # real epoch-by-epoch learning curve


def test_07_training_input_validation(api, S):
    base = {"dataset_id": S["digits_ds"]}
    assert api.post("/models/train", S["dev"], json={**base, "algorithm": "deep_magic"}).status_code == 422
    assert api.post("/models/train", S["dev"], json={**base, "algorithm": "random_forest", "params": {"n_estimators": 100000}}).status_code == 422
    assert api.post("/models/train", S["dev"], json={**base, "algorithm": "random_forest", "test_size": 0.9}).status_code == 422
    assert api.post("/models/train", S["dev"], json={**base, "algorithm": "mlp_neural_net", "params": {"hidden_layers": "abc"}}).status_code in (202,)  # accepted, then fails cleanly
    assert api.post("/models/train", S["dev2"], json=base).status_code == 404                  # other developer's dataset
    assert api.post("/models/train", S["dev"], json={"dataset_id": "nope"}).status_code == 404


def test_08_train_main_models_on_uploaded_digits(api, S, helpers):
    r = api.post("/models/train", S["dev"], json={"dataset_id": S["digits_ds"], "algorithm": "random_forest", "params": {"n_estimators": 60}, "name": "digits-rf", "version": "1.2.0"})
    S["A"] = r.json()["id"]
    assert r.json()["version"] == "1.2.0"
    # progress is observable while training runs
    s = helpers.wait_trained(api, S["dev"], S["A"])
    assert s["training"]["status"] == "completed" and s["training"]["progress"] == 100
    assert s["metrics"]["accuracy"] >= 0.95 and s["training"]["n_train"] == 1437 and s["training"]["n_test"] == 360
    assert len(s["training"]["history"]) >= 5 and "out-of-bag" in " ".join(s["training"]["log"])
    assert sum(map(sum, s["confusion_matrix"]["matrix"])) == 360 and len(s["confusion_matrix"]["labels"]) == 10
    r = api.post("/models/train", S["dev"], json={"dataset_id": S["digits_ds"], "algorithm": "mlp_neural_net", "params": {"epochs": 20}, "name": "digits-mlp"})
    S["B"] = r.json()["id"]
    assert helpers.wait_trained(api, S["dev"], S["B"])["training"]["status"] == "completed"
    assert S["A"] != S["B"] and S["A"].startswith("mdl_")
    # a model that failed to train is reported honestly
    bad = api.post("/models/train", S["dev"], json={"dataset_id": S["digits_ds"], "algorithm": "mlp_neural_net", "params": {"hidden_layers": "abc"}}).json()["id"]
    S["bad"] = bad
    sb = helpers.wait_trained(api, S["dev"], bad)
    assert sb["training"]["status"] == "failed" and sb["status"] == "training_failed" and sb["training"]["error"]
    assert api.post(f"/models/{bad}/deploy", S["dev"]).status_code == 409


def test_08b_evaluation_endpoint(api, S):
    A = S["A"]
    ev = api.get(f"/models/{A}/evaluation", S["dev"]).json()
    tr = api.get(f"/models/{A}/training", S["dev"]).json()
    assert ev["metrics"] == tr["metrics"] and ev["per_class"] == tr["per_class"] and ev["confusion_matrix"] == tr["confusion_matrix"]
    assert ev["split"] == {"test_size": 0.2, "random_state": 42, "n_train": 1437, "n_test": 360, "stratified": True}
    assert ev["algorithm"] == "random_forest" and ev["params"]["n_estimators"] == 60 and ev["dataset"]["target"] == "digit"
    assert sum(map(sum, ev["confusion_matrix"]["matrix"])) == 360
    assert api.get(f"/models/{A}/evaluation", S["dev2"]).status_code == 403            # private until registered
    assert api.get(f"/models/{A}/evaluation", None).status_code == 401
    assert api.get(f"/models/{S['bad']}/evaluation", S["dev"]).status_code == 409      # failed training -> nothing to evaluate
    assert api.get("/models/nope/evaluation", S["dev"]).status_code == 404


# ============================================================ 4. deployment + inference
def test_09_deploy_and_predict(api, S):
    A = S["A"]
    assert api.post(f"/models/{A}/predict", S["dev"], json={"inputs": [[0] * 64]}).status_code == 409   # not deployed yet
    assert api.post(f"/models/{A}/deploy", S["dev2"]).status_code == 403
    d = api.post(f"/models/{A}/deploy", S["dev"]).json()
    tr = api.get(f"/models/{A}/training", S["dev"]).json()["training"]
    assert d["status"] == "deployed" and d["deployment"]["artifact_sha3"] == tr["artifact_sha3"] and d["deployment"]["matches_training_artifact"]
    sch = api.get(f"/models/{A}/schema", S["dev"]).json()
    assert len(sch["feature_columns"]) == 61                         # 64 pixels minus 3 constant columns dropped by validation
    correct = 0
    for smp in sch["sample_inputs"]:
        p = api.post(f"/models/{A}/predict", S["dev"], json={"inputs": [smp["inputs"]]}).json()["predictions"][0]
        assert abs(sum(p["probabilities"].values()) - 1) < 0.01
        correct += p["prediction"] == smp["true_label"]
    assert correct >= 4
    S["A_sample"] = sch["sample_inputs"][0]
    S["A_pred"] = api.post(f"/models/{A}/predict", S["dev"], json={"inputs": [S["A_sample"]["inputs"]]}).json()["predictions"][0]["prediction"]
    # batch + list-of-lists input
    rows = [s["inputs"] for s in sch["sample_inputs"][:3]]
    assert len(api.post(f"/models/{A}/predict", S["dev"], json={"inputs": rows}).json()["predictions"]) == 3
    # invalid inputs
    assert api.post(f"/models/{A}/predict", S["dev"], json={"inputs": [[1, 2, 3]]}).status_code == 422
    assert api.post(f"/models/{A}/predict", S["dev"], json={"inputs": [{"nope": 1}]}).status_code == 422
    assert api.post(f"/models/{A}/predict", S["dev"], json={"inputs": []}).status_code == 422
    assert api.post(f"/models/{A}/predict", S["dev2"], json={"inputs": rows}).status_code == 403
    assert api.get(f"/models/{A}/training", S["dev"]).json()["status"] == "deployed"
    assert api.get(f"/models/{A}", S["dev"]).json()["deployment"]["predictions_served"] >= 7
    assert api.post(f"/models/{S['B']}/deploy", S["dev"]).status_code == 200


# ============================================================ 5. cryptographic protection
def test_10_protection_order_and_failure_handling(api, S):
    A, iris = S["A"], S["iris_models"]["random_forest"]
    # ordering: a model that is trained but NOT deployed cannot be protected
    assert api.post(f"/models/{iris}/crypto/hash", S["dev"]).status_code == 409
    assert api.post(f"/models/{iris}/protect", S["dev"], json={"password": PW}).status_code == 409
    # steps cannot be skipped
    assert api.post(f"/models/{A}/crypto/encrypt", S["dev"]).status_code == 409
    assert api.post(f"/models/{A}/crypto/merkle", S["dev"]).status_code == 409
    assert api.post(f"/models/{A}/crypto/sign", S["dev"], json={"password": PW}).status_code == 409
    # blockchain registration refused before protection
    assert api.post(f"/models/{A}/register", S["dev"], json={"password": PW}).status_code == 409
    assert api.post(f"/models/{A}/license", S["dev"], json={"license": "free-for-all"}).status_code == 422
    assert api.post(f"/models/{A}/license", S["dev"], json={"license": "single-use"}).status_code == 200
    h = api.post(f"/models/{A}/crypto/hash", S["dev"]).json()
    assert h["equals_training_hash"] and h["equals_deployed_hash"] and len(h["original_sha3"]) == 64
    e = api.post(f"/models/{A}/crypto/encrypt", S["dev"]).json()
    assert e["cipher"] == "AES-256-GCM" and e["key_bits"] == 256 and e["auth_tag_bytes"] == 16 and len(e["nonce_hex"]) == 24
    assert api.post(f"/models/{A}/crypto/hash", S["dev"]).status_code == 409            # cannot re-hash after encrypting
    enc_file = STORAGE / "models" / A / "model.enc"
    blob = enc_file.read_bytes()
    assert blob.startswith(b"AIMKTGCM") and sha3(blob) == e["encrypted_sha3"] and e["encrypted_bytes"] == len(blob) == e["plaintext_bytes"] + 16 + 21
    assert (STORAGE / "models" / A / "model.joblib").exists()                            # plaintext still present until signed
    m = api.post(f"/models/{A}/crypto/merkle", S["dev"]).json()
    assert m["chunk_count"] == -(-len(blob) // m["chunk_size"]) and len(m["root"]) == 64
    # signing with the WRONG password must fail and leave the model unprotected
    assert api.post(f"/models/{A}/crypto/sign", S["dev"], json={"password": "wrong-password"}).status_code == 401
    assert api.get(f"/models/{A}", S["dev"]).json()["status"] == "deployed"
    s = api.post(f"/models/{A}/crypto/sign", S["dev"], json={"password": PW}).json()
    assert s["certificate_valid"] and all(c["ok"] for c in s["certificate_checks"]) and s["plaintext_artifact_securely_deleted"]
    assert s["canonical_metadata"]["original"]["sha3"] == h["original_sha3"] and s["canonical_metadata"]["encrypted"]["sha3"] == e["encrypted_sha3"]
    assert s["canonical_metadata"]["merkle"]["root"] == m["root"]
    assert not (STORAGE / "models" / A / "model.joblib").exists() and enc_file.exists()   # only ciphertext at rest now
    assert api.get(f"/models/{A}", S["dev"]).json()["status"] == "protected"
    # signature is verifiable independently by anyone holding the certificate
    u = get_db().users.find_one({"username": DEV}); cert = idn.load_cert_pem(u["cert_pem"])
    doc = get_db().models.find_one({"_id": A})["crypto"]
    assert idn.verify_signature(cert.public_key(), bytes.fromhex(doc["signature_hex"]), doc["metadata_json"].encode())
    assert sha3(doc["metadata_json"].encode()) == s["metadata_sha3"]
    # immutability after signing
    for ep in ("crypto/hash", "crypto/encrypt", "crypto/merkle"):
        assert api.post(f"/models/{A}/{ep}", S["dev"], json={}).status_code == 409
    assert api.post(f"/models/{A}/license", S["dev"], json={"license": "unlimited"}).status_code == 409
    S["A_sha"], S["A_enc_sha"], S["A_root"], S["A_meta_sha"] = h["original_sha3"], e["encrypted_sha3"], m["root"], s["metadata_sha3"]


def test_11_protect_all_for_model_B_with_approval_license(api, S):
    B = S["B"]
    assert api.post(f"/models/{B}/license", S["dev"], json={"license": "approval-required"}).status_code == 200
    r = api.post(f"/models/{B}/protect", S["dev"], json={"password": PW})
    assert r.status_code == 200 and [x["step"] for x in r.json()["steps"]] == ["hash", "encrypt", "merkle", "sign"]
    assert api.post(f"/models/{B}/protect", S["dev"], json={"password": PW}).status_code == 409   # already protected
    assert api.post(f"/models/{B}/protect", S["dev2"], json={"password": PW}).status_code == 403   # not the owner
    assert api.post(f"/models/{B}/protect", S["buy"], json={"password": PW}).status_code == 403


def test_12_no_secrets_at_rest_and_owner_ecc_decryption(api, S):
    """Independent audit: scan the database + storage for secrets, then decrypt with the developer's OWN key."""
    db = get_db()
    dump = json.dumps({c: db._cols[c].find({}) for c in ("users", "models", "grants", "sessions", "downloads", "datasets")}, default=str)
    master = _cfg.MASTER_PASSPHRASE
    assert "PRIVATE KEY" not in dump, "an unencrypted private key is stored in the database"
    assert master not in dump and PW not in dump
    assert "_demoKeyHex" not in dump
    for p in (STORAGE / "ca").iterdir():
        txt = p.read_bytes()
        assert b"PRIVATE KEY" not in txt and master.encode() not in txt, p
    # developer recovers the content key with THEIR OWN P-256 key (no marketplace escrow involved)
    u = db.users.find_one({"username": DEV}); m = db.models.find_one({"_id": S["A"]})
    priv = idn.load_private_key_pem(keystore.decrypt_private_key(u["ec_private_enc"], PW))
    ck = keywrap.ecies_unwrap(priv, m["crypto"]["owner_wrap"])
    assert len(ck) == 32 and ck.hex() not in dump and base64.b64encode(ck).decode() not in dump   # key itself is stored nowhere
    for p in (STORAGE / "models" / S["A"]).iterdir():
        assert ck not in p.read_bytes()
    nonce, ct = bytes.fromhex(m["crypto"]["nonce_hex"]), (STORAGE / "models" / S["A"] / "model.enc").read_bytes()[21:]
    plain = cc.decrypt(ct, ck, nonce, f"{S['A']}|{m['version']}|{m['crypto']['original_sha3']}".encode())
    assert sha3(plain) == S["A_sha"]
    bundle = joblib.load(io.BytesIO(plain)); assert bundle["model_id"] == S["A"] and bundle["algorithm"] == "random_forest"
    # another developer's key cannot unwrap it
    u2 = db.users.find_one({"username": DEV2})
    priv2 = idn.load_private_key_pem(keystore.decrypt_private_key(u2["ec_private_enc"], PW))
    with pytest.raises(Exception): keywrap.ecies_unwrap(priv2, m["crypto"]["owner_wrap"])
    # wrong password cannot open the key store
    with pytest.raises(ValueError): keystore.decrypt_private_key(u["ec_private_enc"], "wrong")


# ============================================================ 6. blockchain registration
def test_13_registration_on_real_chain(api, S):
    A = S["A"]
    assert api.post(f"/models/{A}/register", S["dev"], json={"password": "wrong-password"}).status_code == 401
    assert api.post(f"/models/{A}/register", S["dev2"], json={"password": PW}).status_code == 403   # not the owner
    assert api.post(f"/models/{A}/register", S["buy"], json={"password": PW}).status_code == 403
    r = api.post(f"/models/{A}/register", S["dev"], json={"password": PW})
    assert r.status_code == 200, r.text
    bc = r.json()["blockchain"]
    w3, c, rec = chain_record(A)
    receipt = w3.eth.get_transaction_receipt(bc["tx_hash"])                                  # independent: the tx really exists
    assert receipt.status == 1 and receipt.blockNumber == bc["block_number"] and receipt["to"].lower() == c.address.lower()
    assert receipt["from"] == S["dev_wallet"] == rec["creator"]                                # msg.sender = developer wallet
    assert "0x" + rec["originalHash"].hex() == "0x" + S["A_sha"] and "0x" + rec["encryptedHash"].hex() == "0x" + S["A_enc_sha"]
    assert rec["merkleRoot"].hex() == S["A_root"] and rec["metadataHash"].hex() == S["A_meta_sha"]
    assert rec["modelId"] == A and rec["version"] == "1.2.0" and rec["licenseTerms"] == "single-use" and not rec["revoked"]
    assert rec["registeredBlock"] == bc["block_number"] and rec["registeredAt"] == bc["block_timestamp"] > 0
    ev = c.events.ModelRegistered().process_receipt(receipt)
    assert len(ev) == 1 and ev[0]["args"]["modelId"] == A
    assert api.get(f"/models/{A}", S["dev"]).json()["status"] == "registered"
    S["A_tx"] = bc["tx_hash"]
    # duplicate registration -> rejected (DB state guard + contract)
    d = api.post(f"/models/{A}/register", S["dev"], json={"password": PW})
    assert d.status_code == 409
    # on-chain endpoint == direct contract read
    oc = api.get(f"/models/{A}/onchain", S["buy"]).json()
    assert oc["record"]["creator"] == rec["creator"] and oc["record"]["merkleRoot"] == "0x" + rec["merkleRoot"].hex()
    assert oc["transaction"]["tx_hash"] == bc["tx_hash"]
    assert api.get("/models/nonexistent/onchain", S["buy"]).status_code in (404,)
    st = api.get("/chain/status").json(); assert st["modelCount"] >= 1 and st["blockNumber"] >= bc["block_number"]
    # register B too
    rb = api.post(f"/models/{S['B']}/register", S["dev"], json={"password": PW}); assert rb.status_code == 200
    S["B_tx"] = rb.json()["blockchain"]["tx_hash"]


def test_14_metamask_style_registration_path(api, S, helpers):
    """Developer sends the transaction from their OWN wallet (as MetaMask would) and the backend confirms it."""
    from eth_account import Account
    r = api.post("/models/train", S["dev2"], json={"dataset_id": api.post("/datasets/samples/wine/use", S["dev2"]).json()["id"], "algorithm": "logistic_regression", "name": "wine-lr"})
    mid = r.json()["id"]; helpers.wait_trained(api, S["dev2"], mid)
    assert api.post(f"/models/{mid}/deploy", S["dev2"]).status_code == 200
    assert api.post(f"/models/{mid}/protect", S["dev2"], json={"password": PW}).status_code == 200
    payload = api.get(f"/models/{mid}/chain-payload", S["dev2"]).json()
    assert payload["modelId"] == mid and payload["originalHash"].startswith("0x") and len(payload["signature"]) > 10
    ext = Account.create()                                                                     # an "external wallet" (MetaMask stand-in)
    assert api.post("/me/wallets/link", S["dev2"], json={"address": "0x123"}).status_code == 422
    link = api.post("/me/wallets/link", S["dev2"], json={"address": ext.address}).json()
    assert link["authorized_on_chain"] and link["balance_eth"] > 0
    dep = json.loads((ROOT / "blockchain" / "deployment.json").read_text())
    abi = json.loads((ROOT / "blockchain" / "artifacts-custom" / "ModelRegistry.json").read_text())["abi"]
    w3 = Web3(Web3.HTTPProvider(dep["rpcUrl"])); c = w3.eth.contract(address=dep["address"], abi=abi)
    tup = (payload["modelId"], payload["version"], bytes.fromhex(payload["originalHash"][2:]), bytes.fromhex(payload["encryptedHash"][2:]),
           bytes.fromhex(payload["merkleRoot"][2:]), bytes.fromhex(payload["metadataHash"][2:]), bytes.fromhex(payload["signature"][2:]),
           bytes.fromhex(payload["creatorPubKey"][2:]), payload["licenseTerms"])
    tx = c.functions.registerModel(tup).build_transaction({"from": ext.address, "nonce": w3.eth.get_transaction_count(ext.address), "chainId": 31337})
    txh = w3.eth.send_raw_transaction(ext.sign_transaction(tx).raw_transaction).hex()
    txh = txh if txh.startswith("0x") else "0x" + txh
    w3.eth.wait_for_transaction_receipt(txh)
    assert api.post(f"/models/{mid}/register/confirm", S["dev"], json={"tx_hash": txh}).status_code in (403, 404)  # not the owner
    assert api.post(f"/models/{mid}/register/confirm", S["dev2"], json={"tx_hash": "0x" + "00" * 32}).status_code == 400  # unknown tx
    assert api.post(f"/models/{mid}/register/confirm", S["dev2"], json={"tx_hash": S["A_tx"]}).status_code == 400          # tx registered another model
    ok = api.post(f"/models/{mid}/register/confirm", S["dev2"], json={"tx_hash": txh})
    assert ok.status_code == 200, ok.text
    assert ok.json()["blockchain"]["creator"] == ext.address and ok.json()["blockchain"]["registered_via"].startswith("MetaMask")
    S["C"] = mid


# ============================================================ 7. verification
def test_15_verification_against_blockchain(api, S):
    for mid in (S["A"], S["B"]):
        v = api.post(f"/models/{mid}/verify", S["buy"]).json()                                 # anyone can verify publicly
        assert v["status"] == "PASS" and v["summary"] == {"passed": 8, "failed": 0, "skipped": 0}, v
        assert [c["id"] for c in v["checks"]] == ["certificate", "chain_record", "ownership", "encrypted_hash", "merkle_root", "metadata_hash", "signature", "signature_onchain"]
    assert api.post(f"/models/{S['iris_models']['knn']}/verify", S["dev"]).status_code == 409   # not registered


def test_16_merkle_chunk_proofs(api, S):
    A = S["A"]
    n = api.get(f"/models/{A}/crypto", S["buy"]).json()["crypto"]["merkle"]["chunk_count"]
    assert n >= 30
    for i in sorted({0, 1, n // 2, n - 2, n - 1}):
        v = api.post(f"/models/{A}/merkle/verify-chunk", S["buy"], json={"index": i}).json()
        assert v["status"] == "PASS" and v["valid_against_onchain_root"] and v["valid_against_stored_root"], v
        assert v["on_chain_root"] == S["A_root"] and 1 <= len(v["proof"]) <= (n - 1).bit_length()   # path length <= ceil(log2 n)
        p = api.get(f"/models/{A}/merkle/proof?index={i}", S["buy"]).json()
        assert p["leaf_hash"] == v["leaf_hash"] == v["computed_leaf_hash"]
    assert api.post(f"/models/{A}/merkle/verify-chunk", S["buy"], json={"index": n}).status_code == 422
    assert api.post(f"/models/{A}/merkle/verify-chunk", S["buy"], json={"index": -1}).status_code == 422
    # independently recompute one proof from the raw file
    blob = (STORAGE / "models" / A / "model.enc").read_bytes(); cs = 16384
    leaves = [bytes.fromhex(x) for x in get_db().models.find_one({"_id": A})["crypto"]["merkle"]["leaves"]]
    assert mk.leaf_hash(blob[3 * cs:4 * cs]) == leaves[3] and mk.root_from_leaves(leaves) == S["A_root"]


# ============================================================ 8. secure distribution
def test_17_marketplace_listing(api, S):
    ms = {m["id"]: m for m in api.get("/marketplace/models", S["buy"]).json()}
    assert {S["A"], S["B"], S["C"]} <= ms.keys() and S["iris_models"]["knn"] not in ms        # only registered models are listed
    a = ms[S["A"]]
    assert a["developer"]["username"] == DEV and a["developer"]["certificate_fingerprint"] and a["license"] == "single-use"
    assert a["blockchain"]["tx_hash"] == S["A_tx"] and a["blockchain"]["block_number"] > 0 and a["metrics"]["accuracy"] >= 0.95
    d = api.get(f"/marketplace/models/{S['A']}", S["buy"]).json()
    assert d["my_access"] is None and d["is_owner"] is False and d["license_terms"]["max_downloads"] == 1
    assert api.get(f"/marketplace/models/{S['iris_models']['knn']}", S["buy"]).status_code == 404
    assert api.get(f"/models/{S['iris_models']['knn']}", S["buy"]).status_code == 403          # private until registered
    assert len(api.get("/marketplace/licenses", S["buy"]).json()) == 3


def test_17b_encrypted_artifact_is_public_ciphertext_only(api, S):
    A = S["A"]
    r = api.get(f"/marketplace/models/{A}/encrypted", S["buy2"])                          # any signed-in user, no grant needed
    assert r.status_code == 200 and r.content.startswith(b"AIMKTGCM") and r.headers["content-disposition"].endswith(f"{A}_1.2.0.enc\"")
    _, _, rec = chain_record(A)
    assert sha3(r.content) == rec["encryptedHash"].hex() == r.headers["x-encrypted-sha3-256"] == S["A_enc_sha"]   # anyone can check it against the chain
    assert r.content == (STORAGE / "models" / A / "model.enc").read_bytes()
    nonce, ct = r.content[9:21], r.content[21:]
    with pytest.raises(Exception): cc.decrypt(ct, cc.generate_key(), nonce, b"")             # useless without the content key
    assert b"RandomForest" not in r.content and b"sklearn" not in r.content                  # no plaintext structure leaks
    assert api.get(f"/marketplace/models/{A}/encrypted", None).status_code == 401
    assert api.get(f"/marketplace/models/{S['iris_models']['knn']}/encrypted", S["buy"]).status_code == 404   # unregistered


def test_18_single_use_license_distribution(api, S):
    A, buy = S["A"], S["buy"]
    # unauthorised: no request -> DENIED, and NO key / token is released
    r = api.post(f"/marketplace/models/{A}/access", buy, json={"password": PW})
    assert r.status_code == 403 and "download_token" not in r.text and r.json()["steps"][-1]["status"] == "DENIED"
    assert api.post(f"/marketplace/models/{A}/access", None, json={"password": PW}).status_code == 401
    assert api.post(f"/marketplace/models/{A}/access-request", S["dev"], json={}).status_code == 400   # developer cannot "buy" own model
    g = api.post(f"/marketplace/models/{A}/access-request", buy, json={"note": "research"}).json()
    assert g["status"] == "approved" and g["license"] == "single-use" and g["max_downloads"] == 1
    assert api.post(f"/marketplace/models/{A}/access-request", buy, json={}).json()["id"] == g["id"]   # idempotent
    # wrong password: cannot unlock the buyer's private key -> no key exchange, not counted as a download
    r = api.post(f"/marketplace/models/{A}/access", buy, json={"password": "wrong-password"})
    assert r.status_code == 401 and "download_token" not in r.text
    # authorised
    r = api.post(f"/marketplace/models/{A}/access", buy, json={"password": PW})
    assert r.status_code == 200, r.text
    j = r.json()
    names = [s["step"] for s in j["steps"]]
    assert names == ["access_grant", "buyer_certificate", "developer_certificate", "retrieve_encrypted", "blockchain_record", "integrity_verification",
                     "key_exchange", "decrypt", "plaintext_hash", "release"] and all(s["status"] == "PASS" for s in j["steps"])
    kx = next(s for s in j["steps"] if s["step"] == "key_exchange")["key_exchange"]
    assert kx["scheme"].startswith("ECDH-P256+HKDF") and "content_key" not in json.dumps(j)
    f = api.get(f"/downloads/{j['download_token']}", buy)
    assert f.status_code == 200 and f.headers["content-disposition"].endswith(f"{A}_1.2.0.joblib\"")
    _, _, rec = chain_record(A)
    assert "0x" + sha3(f.content) == "0x" + rec["originalHash"].hex() == j["plaintext_sha3"]        # distributed bytes == on-chain original hash
    import pandas as pd
    bundle = joblib.load(io.BytesIO(f.content))
    dist_pred = str(bundle["pipeline"].predict(pd.DataFrame([S["A_sample"]["inputs"]])[bundle["feature_columns"]])[0])
    assert dist_pred == S["A_pred"]                                                              # distributed model == deployed model
    # inference through the distributed copy
    ip = api.post(f"/downloads/{j['download_token']}/predict", buy, json={"inputs": [S["A_sample"]["inputs"]]}).json()
    assert ip["predictions"][0]["prediction"] == S["A_pred"] and "hash-verified" in ip["artifact"]
    # tokens are bound to the buyer
    assert api.get(f"/downloads/{j['download_token']}", S["buy2"]).status_code == 404
    assert api.get(f"/downloads/{j['download_token']}", None).status_code == 401
    # single-use license is now exhausted
    r = api.post(f"/marketplace/models/{A}/access", buy, json={"password": PW})
    assert r.status_code == 403 and "exhausted" in r.json()["detail"] and "download_token" not in r.text
    # another buyer who never requested access gets nothing either
    r = api.post(f"/marketplace/models/{A}/access", S["buy2"], json={"password": PW})
    assert r.status_code == 403 and "download_token" not in r.text


def test_19_approval_required_license_flow(api, S):
    B, buy, buy2, dev, dev2 = S["B"], S["buy"], S["buy2"], S["dev"], S["dev2"]
    g = api.post(f"/marketplace/models/{B}/access-request", buy, json={"note": "please"}).json()
    assert g["status"] == "pending" and g["max_downloads"] == 3
    r = api.post(f"/marketplace/models/{B}/access", buy, json={"password": PW})
    assert r.status_code == 403 and "pending" in r.json()["detail"] and "download_token" not in r.text
    inc = api.get("/marketplace/incoming", dev).json()
    assert any(x["id"] == g["id"] for x in inc) and not any(x["id"] == g["id"] for x in api.get("/marketplace/incoming", dev2).json())
    assert api.post(f"/marketplace/requests/{g['id']}/decision", dev2, json={"approve": True}).status_code == 404    # not the owner
    assert api.post(f"/marketplace/requests/{g['id']}/decision", buy, json={"approve": True}).status_code == 403      # buyers cannot approve
    assert api.post(f"/marketplace/requests/{g['id']}/decision", dev, json={"approve": True}).json()["status"] == "approved"
    assert api.post(f"/marketplace/requests/{g['id']}/decision", dev, json={"approve": False}).status_code == 409     # already decided
    r = api.post(f"/marketplace/models/{B}/access", buy, json={"password": PW}); assert r.status_code == 200
    S["B_tok"] = r.json()["download_token"]
    for _ in range(2):
        assert api.post(f"/marketplace/models/{B}/access", buy, json={"password": PW}).status_code == 200            # up to 3 downloads
    assert api.post(f"/marketplace/models/{B}/access", buy, json={"password": PW}).status_code == 403
    # a denied request
    g2 = api.post(f"/marketplace/models/{B}/access-request", buy2, json={}).json()
    assert api.post(f"/marketplace/requests/{g2['id']}/decision", dev, json={"approve": False}).json()["status"] == "denied"
    r = api.post(f"/marketplace/models/{B}/access", buy2, json={"password": PW})
    assert r.status_code == 403 and "denied" in r.json()["detail"] and "download_token" not in r.text


def test_20_tampered_stored_file_blocks_distribution(api, S):
    """An attacker modifies the stored encrypted model on disk: distribution must refuse to release it."""
    C, dev2, buy2 = S["C"], S["dev2"], S["buy2"]
    g = api.post(f"/marketplace/models/{C}/access-request", buy2, json={})
    assert g.status_code == 201 and g.json()["status"] == "approved"
    # model C has the default license (single-use): request as buy2, then tamper before downloading
    path = STORAGE / "models" / C / "model.enc"; orig = path.read_bytes()
    try:
        bad = bytearray(orig); bad[len(bad) // 3] ^= 0x01; path.write_bytes(bytes(bad))
        r = api.post(f"/marketplace/models/{C}/access", buy2, json={"password": PW})
        assert r.status_code == 409 and "download_token" not in r.text
        steps = {s["step"]: s for s in r.json()["steps"]}
        assert steps["integrity_verification"]["status"] == "FAIL" and "encrypted_hash" in r.json()["detail"] and "merkle_root" in r.json()["detail"]
        assert "key_exchange" not in steps                                                       # key exchange never even started
        assert api.post(f"/models/{C}/verify", buy2).json()["status"] == "FAIL"
    finally:
        path.write_bytes(orig)
    assert api.post(f"/models/{C}/verify", buy2).json()["status"] == "PASS"                      # restored
    assert api.post(f"/marketplace/models/{C}/access", buy2, json={"password": PW}).status_code == 200


def test_21_tamper_security_suite(api, S):
    A = S["A"]
    assert api.post(f"/security/{A}/run-all", S["buy"], json={"password": PW}).status_code == 403
    assert api.post(f"/security/{A}/run-all", S["dev2"], json={"password": PW}).status_code == 403
    assert api.post(f"/security/{A}/tests/not_a_test", S["dev"], json={}).status_code == 404
    assert api.post(f"/security/{S['iris_models']['knn']}/run-all", S["dev"], json={"password": PW}).status_code == 409   # not registered
    r = api.post(f"/security/{A}/run-all", S["dev"], json={"password": PW}); assert r.status_code == 200, r.text
    res = {x["test"]: x for x in r.json()["results"]}
    assert r.json()["all_matched"] and r.json()["matched"] == 6
    assert (res["normal"]["actual"], res["file_tamper"]["actual"], res["signature_tamper"]["actual"],
            res["unauthorized_ownership"]["actual"], res["duplicate"]["actual"], res["unauthorized_download"]["actual"]) == \
           ("PASS", "FAIL", "FAIL", "REJECTED", "REJECTED", "DENIED")
    ft = res["file_tamper"]["details"]
    assert ft["restored"] and {"encrypted_hash", "merkle_root", "decrypt"} <= set(ft["failed_checks"]) and "InvalidTag" in ft["gcm_decrypt_attempt"]
    sg = res["signature_tamper"]["details"]
    assert "signature" in sg["case_a"]["failed_checks"] and {"metadata_hash", "signature"} <= set(sg["case_b"]["failed_checks"])
    oa = res["unauthorized_ownership"]["details"]["attempts"]
    assert [a["contract_message"] for a in oa] == ["Not an authorized developer", "Not the model owner", "Not the model owner"] and oa[0]["failed_tx_hash"]
    w3 = Web3(Web3.HTTPProvider(json.loads((ROOT / "blockchain" / "deployment.json").read_text())["rpcUrl"]))
    rc = w3.eth.get_transaction_receipt(oa[0]["failed_tx_hash"]); assert rc.status == 0         # the rejected tx really exists on-chain as FAILED
    dp = res["duplicate"]["details"]
    assert dp["contract_message"] == "Model already registered" and dp["database_duplicate_check"].startswith("rejected")
    assert w3.eth.get_transaction_receipt(dp["failed_tx_hash"]).status == 0
    ud = res["unauthorized_download"]["details"]["attempts"]
    assert len(ud) == 3 and all(a["outcome"] == "DENIED" and a["key_released"] is False for a in ud)
    # the model survives the tests intact
    assert api.post(f"/models/{A}/verify", S["dev"]).json()["status"] == "PASS"
    assert [u for u in get_db().users.find({}) if u["username"].startswith("tmp_")] == []         # throwaway test accounts were cleaned up
    assert [g for g in get_db().grants.find({}) if g["buyer_name"].startswith("tmp_")] == []
    assert api.post(f"/security/{A}/tests/normal", S["dev"], json={}).json()["actual"] == "PASS"


def test_22_logs_and_dashboard(api, S):
    st = api.get("/dashboard/stats", S["dev"]).json()
    mine = api.get("/models", S["dev"]).json()                                      # derive the expected numbers independently
    assert st["models_total"] == len(mine)
    assert st["models_trained"] == sum(m["training"]["status"] == "completed" for m in mine) >= 9
    assert st["models_deployed"] == sum(m.get("deployment", {}).get("status") == "deployed" for m in mine) >= 2
    assert st["models_protected"] == sum(m["status"] in ("protected", "registered") for m in mine) >= 2
    assert st["models_registered"] == sum(m["status"] == "registered" for m in mine) >= 2
    assert st["tamper_tests_run"] >= 7 and st["tamper_tests_as_expected"] == st["tamper_tests_run"]
    assert st["verifications_passed"] >= 4 and st["verifications_failed"] >= 1      # the tampered-file distribution attempt FAILED verification
    assert st["access_denied"] >= 3 and st["chain"]["connected"]
    logs = api.get(f"/security/logs?model_id={S['A']}", S["dev"]).json()
    assert {"verification", "tamper_test", "distribution"} <= {l["kind"] for l in logs}
    assert any(l["status"] == "PASS" for l in logs)
    assert any(l["status"] == "FAIL" for l in api.get(f"/security/logs?model_id={S['C']}", S["dev2"]).json())
    bst = api.get("/dashboard/stats", S["buy"]).json()
    assert bst["models_registered"] == len(api.get("/marketplace/models", S["buy"]).json()) >= 3


def test_22b_undeploy_and_redeploy_from_encrypted_store(api, S):
    B, dev, dev2 = S["B"], S["dev"], S["dev2"]
    row = api.get(f"/models/{B}/schema", dev).json()["sample_inputs"][0]["inputs"]
    assert api.get(f"/models/{B}", dev).json()["deployment"]["status"] == "deployed"
    assert api.post(f"/models/{B}/predict", dev, json={"inputs": [row]}).status_code == 200
    assert api.post(f"/models/{B}/undeploy", dev2).status_code == 403                       # only the owner
    assert api.post(f"/models/{B}/undeploy", dev).json()["deployment"]["status"] == "undeployed"
    assert api.get(f"/models/{B}", dev).json()["deployment"]["status"] == "undeployed"
    assert api.post(f"/models/{B}/predict", dev, json={"inputs": [row]}).status_code == 409   # no longer served
    # B is protected: its plaintext was deleted, so redeploying must decrypt the stored ciphertext and verify the hash
    assert not (STORAGE / "models" / B / "model.joblib").exists()
    d = api.post(f"/models/{B}/deploy", dev).json()
    tr = api.get(f"/models/{B}/training", dev).json()["training"]
    assert d["deployment"]["status"] == "deployed" and d["deployment"]["artifact_sha3"] == tr["artifact_sha3"] and d["status"] == "registered"
    assert api.post(f"/models/{B}/predict", dev, json={"inputs": [row]}).status_code == 200
    assert not (STORAGE / "models" / B / "model.joblib").exists()                            # still no plaintext at rest
    assert api.post(f"/models/{S['iris_models']['knn']}/undeploy", dev).status_code == 200  # idempotent for never-deployed models


def test_22c_remaining_read_endpoints(api, S):
    cfg = api.get("/chain/config").json()
    dep = json.loads((ROOT / "blockchain" / "deployment.json").read_text())
    assert cfg["address"] == dep["address"] and cfg["chainId"] == 31337 and any(x.get("name") == "registerModel" for x in cfg["abi"])
    samples = {s["name"]: s for s in api.get("/datasets/samples", S["dev"]).json()}
    assert all(samples[n]["available"] for n in ("digits", "iris", "wine", "breast_cancer")) and "cifar10_subset" in samples
    mine = api.get("/datasets", S["dev"]).json()
    assert any(d["id"] == S["digits_ds"] for d in mine) and all("path" not in d for d in mine)        # server file paths are never exposed
    assert S["digits_ds"] not in {d["id"] for d in api.get("/datasets", S["dev2"]).json()}            # datasets are per-user
    tests = api.get("/security/tests", S["dev"]).json()
    assert {t["id"]: t["expected"] for t in tests} == {"normal": "PASS", "file_tamper": "FAIL", "signature_tamper": "FAIL",
        "unauthorized_ownership": "REJECTED", "duplicate": "REJECTED", "unauthorized_download": "DENIED"}
    reqs = api.get("/marketplace/my-requests", S["buy"]).json()
    assert any(g["model_id"] == S["A"] for g in reqs) and all(g["buyer"] == BUY for g in reqs)
    assert not any(g["buyer"] == BUY for g in api.get("/marketplace/my-requests", S["buy2"]).json())


def test_23_save_state_for_restart_test(api, S):
    out = ROOT / "tests" / "results"; out.mkdir(parents=True, exist_ok=True)
    json.dump({"A": S["A"], "A_pred": S["A_pred"], "A_sample": S["A_sample"], "A_root": S["A_root"], "A_tx": S["A_tx"],
               "dev_token": S["dev"], "dev_user": DEV, "buy_user": BUY}, open(out / ".state.json", "w"))
