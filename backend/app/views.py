"""Shapes database documents into API responses: strips secrets/internal fields and derives the 6-stage lifecycle."""
import copy

from .db import get_db

STAGE_ORDER = [
    ("creation", "Model Upload / Creation"),
    ("training", "Model Training"),
    ("evaluation", "Model Evaluation"),
    ("packaging", "Model Packaging"),
    ("deployment", "Model Deployment"),
    ("registration", "Blockchain Registration"),
]


def lifecycle(m: dict) -> list:
    cr = m.get("crypto") or {}
    tr = m.get("training", {})
    ev = m.get("evaluation") or m.get("metrics")
    dep = m.get("deployment", {})
    st_val = m.get("status", "")

    def st(done, failed=False, active=False):
        return "failed" if failed else ("completed" if done else ("active" if active else "pending"))

    s = {
        "creation": st(True),
        "training": st(
            tr.get("status") == "completed" or bool(m.get("is_uploaded")),
            tr.get("status") == "failed",
            tr.get("status") in ("queued", "running")
        ),
        "evaluation": st(bool(ev)),
        "packaging": st(
            bool(cr.get("signature_hex")) or st_val in ("packaged", "protected", "registered"),
            m.get("stages", {}).get("packaging", {}).get("status") == "failed",
            m.get("stages", {}).get("packaging", {}).get("status") == "running"
        ),
        "deployment": st(dep.get("status") == "deployed"),
        "registration": st(
            st_val == "registered",
            m.get("stages", {}).get("register", {}).get("status") == "failed" and st_val != "registered"
        ),
    }
    return [{"id": k, "label": lbl, "status": s[k]} for k, lbl in STAGE_ORDER]


def model_view(m: dict, owner_view: bool = True) -> dict:
    out = copy.deepcopy(m)
    out["id"] = out.pop("_id")
    cr = out.get("crypto")
    if cr:
        cr.pop("escrow_wrap", None)
        cr.pop("owner_wrap", None)
        if cr.get("merkle"):
            cr["merkle"]["leaves_count"] = len(cr["merkle"].pop("leaves", []))
    if not owner_view:
        out.pop("training", None)
        out.pop("sample_inputs", None)
    out["lifecycle"] = lifecycle(m)
    return out


def marketplace_view(m: dict) -> dict:
    db = get_db()
    owner = db.users.find_one({"_id": m["owner_id"]}) or {}
    from crypto import identity as idn
    cert = idn.cert_summary(idn.load_cert_pem(owner["cert_pem"])) if owner.get("cert_pem") else {}
    cr, bc = m.get("crypto", {}), m.get("blockchain", {})
    metrics = m.get("metrics", {})
    return {
        "id": m["_id"],
        "name": m["name"],
        "version": m["version"],
        "algorithm": m["algorithm"],
        "license": m["license"],
        "developer": {
            "username": m["owner_name"],
            "certificate_subject": cert.get("subject"),
            "certificate_fingerprint": cert.get("fingerprintSha3_256"),
            "wallet": bc.get("creator")
        },
        "metrics": {
            "accuracy": metrics.get("accuracy", 0.0),
            "precision_macro": metrics.get("precision_macro", 0.0),
            "recall_macro": metrics.get("recall_macro", 0.0),
            "f1_macro": metrics.get("f1_macro", 0.0)
        },
        "n_classes": len(m.get("classes", [])),
        "n_features": len(m.get("feature_columns", [])),
        "dataset_name": m.get("dataset_name"),
        "size_bytes": cr.get("original_bytes"),
        "original_sha3": cr.get("original_sha3"),
        "merkle_root": cr.get("merkle", {}).get("root"),
        "blockchain": {
            k: bc.get(k) for k in ("tx_hash", "block_number", "block_timestamp", "contract_address", "chain_id", "creator")
        },
        "created_at": m["created_at"]
    }
