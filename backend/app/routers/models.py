"""
routers/models.py - Endpoints for the genuine 6-stage ML lifecycle:
  Stage 1: Model Creation & Upload (/api/models/create, /api/models/upload)
  Stage 2: Model Training (/api/models/{id}/train)
  Stage 3: Model Evaluation (/api/models/{id}/evaluate)
  Stage 4: Model Packaging (/api/models/{id}/package)
  Stage 5: Model Deployment (/api/models/{id}/deploy, /api/models/{id}/predict)
  Task Monitoring: /api/tasks/{task_id}, /api/models/{id}/tasks
"""
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import ml, protection, tasks
from ..db import get_db
from ..deps import current_user, get_model_or_404, owned_model, require_developer
from ..views import model_view

router = APIRouter()


class CreateModelRequest(BaseModel):
    dataset_id: str
    algorithm: str = "random_forest"
    params: dict = {}
    target_column: Optional[str] = None
    test_size: float = 0.2
    random_state: int = 42
    name: Optional[str] = None
    version: str = "1.0.0"


class EvaluateRequest(BaseModel):
    eval_dataset_id: Optional[str] = None


class PackageRequest(BaseModel):
    password: str
    license: Optional[str] = "single-use"


class PredictRequest(BaseModel):
    inputs: Any


@router.get("/ml/algorithms")
def algorithms(user=Depends(current_user)):
    return ml.algorithm_catalog()


# ---------------------------------------------------------------- STAGE 1: CREATE / UPLOAD
@router.post("/models/create", status_code=201)
def create_model(body: CreateModelRequest, user=Depends(require_developer)):
    """Stage 1: Register and validate model architecture and dataset configuration."""
    db = get_db()
    ds = db.datasets.find_one({"_id": body.dataset_id, "owner_id": user["_id"]})
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if body.algorithm not in ml.ALGORITHMS:
        raise HTTPException(422, f"Unknown algorithm; choose from {list(ml.ALGORITHMS)}")
    if not 0.1 <= body.test_size <= 0.5:
        raise HTTPException(422, "test_size must be between 0.1 and 0.5")
    if not body.version.strip() or len(body.version) > 20:
        raise HTTPException(422, "Invalid version string")

    target = body.target_column or ds["validation"].get("target")
    if body.target_column and body.target_column != ds["validation"].get("target"):
        report = ml.analyze_csv(ds["path"], body.target_column)
        ds["validation"] = report
    if not ds["validation"]["valid"]:
        raise HTTPException(422, {"message": "Dataset failed validation", "errors": ds["validation"]["errors"]})

    try:
        params = ml.coerce_params(body.algorithm, body.params)
    except ValueError as e:
        raise HTTPException(422, str(e))

    model_id = f"mdl_{datetime.now(timezone.utc):%Y%m%d}_{secrets.token_hex(4)}"
    name = (body.name or f"{ds['name']}-{body.algorithm}").strip()[:60]
    cfg = {
        "name": name,
        "version": body.version.strip(),
        "algorithm": body.algorithm,
        "params": params,
        "target": target,
        "test_size": body.test_size,
        "random_state": body.random_state
    }

    doc = {
        "_id": model_id,
        "name": name,
        "version": cfg["version"],
        "owner_id": user["_id"],
        "owner_name": user["username"],
        "algorithm": body.algorithm,
        "params": params,
        "dataset_id": ds["_id"],
        "dataset_name": ds["name"],
        "dataset_sha3": ds["sha3"],
        "target": target,
        "test_size": body.test_size,
        "random_state": body.random_state,
        "status": "created",
        "license": "single-use",
        "created_at": ml.now_iso(),
        "training": {
            "status": "pending",
            "progress": 0.0,
            "stage": "ready_to_train",
            "log": [],
            "history": []
        },
        "stages": {
            "creation": {"status": "completed", "at": ml.now_iso()}
        }
    }
    db.models.insert_one(doc)
    return {"id": model_id, "name": name, "version": cfg["version"], "status": "created"}


@router.post("/models/upload", status_code=201)
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    version: str = Form("1.0.0"),
    user=Depends(require_developer)
):
    """Stage 1: Upload and validate an existing pre-trained model file (.joblib / .pkl)."""
    if not file.filename.endswith((".joblib", ".pkl", ".pickle")):
        raise HTTPException(422, "Only .joblib or .pkl model artifacts are supported")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(422, "Model artifact exceeds maximum allowed size (50 MB)")

    model_id = f"mdl_{datetime.now(timezone.utc):%Y%m%d}_{secrets.token_hex(4)}"
    try:
        res = ml.upload_model_artifact(
            model_id=model_id,
            file_bytes=content,
            filename=file.filename,
            name=name.strip()[:60],
            version=version.strip()[:20],
            user=user
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return res


# ---------------------------------------------------------------- STAGE 2: TRAINING
@router.post("/models/{model_id}/train", status_code=202)
def start_model_training(model_id: str, m=Depends(owned_model), user=Depends(require_developer)):
    """Stage 2: Execute asynchronous model training with live epoch logs and metrics."""
    db = get_db()
    ds = db.datasets.find_one({"_id": m.get("dataset_id")})
    if not ds:
        raise HTTPException(404, "Original training dataset is not available")

    cfg = {
        "name": m["name"],
        "version": m["version"],
        "algorithm": m["algorithm"],
        "params": m.get("params", {}),
        "target": m.get("target"),
        "test_size": m.get("test_size", 0.2),
        "random_state": m.get("random_state", 42)
    }

    # Create asynchronous background task
    task = tasks.create_task("training", model_id, f"Train {m['name']} ({m['algorithm']})", user["_id"])
    task_id = task["id"]

    db.models.update_one(
        {"_id": model_id},
        {"$set": {
            "status": "training",
            "training.status": "running",
            "training.progress": 0.0,
            "training.stage": "queued",
            "training.started_at": ml.now_iso(),
            "training.task_id": task_id,
            "stages.training": {"status": "active", "at": ml.now_iso()}
        }}
    )

    ml.start_training(model_id, ds, cfg, task_id)
    return {
        "id": model_id,
        "task_id": task_id,
        "status": "training",
        "message": "Training job dispatched to background worker"
    }


# Backwards compatible alias for training
@router.post("/models/train", status_code=202)
def legacy_train_endpoint(body: CreateModelRequest, user=Depends(require_developer)):
    created = create_model(body, user)
    model_id = created["id"]
    m = get_db().models.find_one({"_id": model_id})
    return start_model_training(model_id, m, user)


# ---------------------------------------------------------------- STAGE 3: EVALUATION
@router.post("/models/{model_id}/evaluate")
def evaluate_model_endpoint(model_id: str, body: Optional[EvaluateRequest] = None, m=Depends(owned_model)):
    """Stage 3: Run comprehensive evaluation of the trained model on test data."""
    if m.get("status") not in ("trained", "evaluated", "packaged", "protected", "deployed", "registered") and not m.get("is_uploaded"):
        raise HTTPException(409, "Model must be trained or uploaded before evaluation can run")
    try:
        report = ml.evaluate_model(model_id, eval_dataset_id=body.eval_dataset_id if body else None)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Evaluation failed: {e}")
    return report


@router.get("/models/{model_id}/evaluation")
def get_evaluation_endpoint(model_id: str, user=Depends(current_user)):
    """Fetch the computed evaluation report."""
    m = get_model_or_404(model_id)
    if m["owner_id"] != user["_id"] and m["status"] != "registered":
        raise HTTPException(403, "Evaluation report is private to the developer until registered")
    ev = m.get("evaluation")
    if not ev and "metrics" in m:
        ev = {
            "model_id": model_id,
            "metrics": m["metrics"],
            "per_class": m.get("per_class", []),
            "confusion_matrix": m.get("confusion_matrix", {"labels": [], "matrix": []})
        }
    if not ev:
        raise HTTPException(404, "Model has not been evaluated yet. Run Stage 3 evaluation first.")
    return ev


# ---------------------------------------------------------------- STAGE 4: PACKAGING
@router.post("/models/{model_id}/package")
def package_model_endpoint(model_id: str, body: PackageRequest, m=Depends(owned_model), user=Depends(require_developer)):
    """Stage 4: Package model weights, generate manifest, Merkle tree, encryption, and X.509 signature."""
    if m.get("status") not in ("trained", "evaluated", "deployed") and not m.get("is_uploaded"):
        raise HTTPException(409, "Model must complete training before packaging")
    try:
        res = protection.package_model(model_id, user, body.password, body.license)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Packaging failed: {e}")
    return res


# ---------------------------------------------------------------- STAGE 5: DEPLOYMENT
@router.post("/models/{model_id}/deploy")
def deploy_model_endpoint(model_id: str, m=Depends(owned_model)):
    """Stage 5: Deploy packaged/trained model to the inference engine."""
    if m.get("training", {}).get("status") != "completed" and not m.get("is_uploaded"):
        raise HTTPException(409, "Training has not completed; cannot deploy")
    try:
        dep = ml.deploy(m)
    except ValueError as e:
        raise HTTPException(409, f"Deployment rejected: {e}")
    except Exception as e:
        raise HTTPException(500, f"Deployment failed: {type(e).__name__}: {str(e)[:150]}")

    upd = {
        "deployment": dep,
        "status": "deployed" if m.get("status") in ("trained", "packaged", "protected") else m.get("status"),
        "stages.deployment": {"status": "completed", "at": ml.now_iso()}
    }
    get_db().models.update_one({"_id": model_id}, {"$set": upd})
    return {"deployment": dep, "status": upd["status"]}


@router.post("/models/{model_id}/undeploy")
def undeploy_model_endpoint(model_id: str, m=Depends(owned_model)):
    """Stage 5: Undeploy model from inference engine."""
    ml.undeploy(model_id)
    get_db().models.update_one(
        {"_id": model_id},
        {"$set": {
            "deployment.status": "undeployed",
            "stages.deployment": {"status": "pending", "at": ml.now_iso()}
        }}
    )
    return {"deployment": {"status": "undeployed"}}


@router.get("/models/{model_id}/schema")
def model_schema_endpoint(model_id: str, m=Depends(owned_model)):
    return {
        "id": m["_id"],
        "name": m["name"],
        "version": m["version"],
        "feature_columns": m.get("feature_columns", []),
        "classes": m.get("classes", []),
        "sample_inputs": m.get("sample_inputs", []),
        "deployment": m.get("deployment"),
        "endpoint": f"/api/models/{model_id}/predict"
    }


@router.post("/models/{model_id}/predict")
def predict_model_endpoint(model_id: str, body: PredictRequest, m=Depends(owned_model)):
    """Stage 5: Live inference prediction with measured latency."""
    if m.get("deployment", {}).get("status") != "deployed":
        raise HTTPException(409, "Model is not currently deployed. Deploy it in Stage 5.")
    try:
        bundle = ml.get_deployed_bundle(m)
        preds, latency_ms = ml.predict_with_bundle(bundle, body.inputs)
    except ValueError as e:
        raise HTTPException(422, str(e))

    get_db().models.update_one({"_id": model_id}, {"$inc": {"deployment.predictions_served": len(preds)}})
    return {
        "model_id": model_id,
        "version": m["version"],
        "predictions": preds,
        "classes": m.get("classes"),
        "latency_ms": latency_ms
    }


# ---------------------------------------------------------------- QUERY & STATUS
@router.get("/models")
def list_models_endpoint(user=Depends(current_user)):
    flt = {"owner_id": user["_id"]} if user["role"] == "developer" else {"status": "registered"}
    return [model_view(m, owner_view=m["owner_id"] == user["_id"]) for m in get_db().models.find(flt, sort=[("created_at", -1)])]


@router.get("/models/{model_id}")
def get_model_endpoint(model_id: str, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if m["owner_id"] != user["_id"] and m["status"] != "registered":
        raise HTTPException(403, "This model is private to its developer until registered")
    return model_view(m, owner_view=m["owner_id"] == user["_id"])


@router.get("/models/{model_id}/training")
def training_status_endpoint(model_id: str, m=Depends(owned_model)):
    t = m.get("training", {})
    return {
        "id": m["_id"],
        "status": m["status"],
        "training": t,
        "metrics": m.get("metrics"),
        "evaluation": m.get("evaluation"),
        "per_class": m.get("per_class"),
        "confusion_matrix": m.get("confusion_matrix"),
        "lifecycle": model_view(m)["lifecycle"]
    }


# ---------------------------------------------------------------- TASK MONITORING
@router.get("/tasks/{task_id}")
def get_task_status_endpoint(task_id: str, user=Depends(current_user)):
    t = tasks.get_task(task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    return t


@router.get("/models/{model_id}/tasks")
def get_model_tasks_endpoint(model_id: str, user=Depends(current_user)):
    m = get_model_or_404(model_id)
    if m["owner_id"] != user["_id"] and m["status"] != "registered":
        raise HTTPException(403, "Access denied")
    return tasks.get_model_tasks(model_id)
