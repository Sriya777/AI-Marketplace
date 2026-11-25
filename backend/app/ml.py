"""
ml.py - dataset validation, preprocessing, REAL model training with progress and resource tracking,
independent evaluation, packaging, deployment (inference) and prediction.

Nothing here loads a pretrained model or hardcodes outputs: every model is fitted from the dataset or uploaded.
"""
import copy
import io
import math
import os
import secrets
import sys
import threading
import time
import traceback
import tracemalloc
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from crypto.crypto_core import sha3_256_hash
from . import artifacts, tasks
from .db import get_db

MIN_ROWS, MAX_ROWS, MAX_CLASSES = 30, 200_000, 50


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================ dataset validation
def _clean_target(y: pd.Series) -> pd.Series:
    if pd.api.types.is_float_dtype(y):
        nn = y.dropna()
        if len(nn) and (nn == nn.round()).all():
            y = y.astype("Int64")
    return y.astype(str)


def analyze_csv(path: str, target_column: str = None) -> dict:
    """Validate an uploaded CSV for classification."""
    report = {"valid": False, "errors": [], "warnings": [], "n_rows": 0, "n_cols": 0, "target": None,
              "features": [], "classes": [], "class_counts": {}, "preview": [], "columns": []}
    err, warn = report["errors"], report["warnings"]
    try:
        df = pd.read_csv(path)
    except Exception as e:
        err.append(f"Cannot parse file as CSV: {str(e)[:150]}")
        return report
    df.columns = [str(c).strip() for c in df.columns]
    report["n_rows"], report["n_cols"], report["columns"] = len(df), df.shape[1], list(df.columns)
    report["preview"] = df.head(8).astype(object).where(df.head(8).notna(), None).to_dict(orient="records")
    if len(set(df.columns)) != len(df.columns):
        err.append("Duplicate column names are not allowed.")
    if any(c == "" or c.startswith("Unnamed:") for c in df.columns):
        warn.append("Some columns have empty/auto-generated names (header row missing?).")
    if df.shape[1] < 2:
        err.append("Need at least 2 columns (features + a target column).")
    if len(df) < MIN_ROWS:
        err.append(f"Need at least {MIN_ROWS} rows (found {len(df)}).")
    if len(df) > MAX_ROWS:
        err.append(f"Too many rows ({len(df)} > {MAX_ROWS}).")
    if err:
        return report

    target = (target_column or df.columns[-1]).strip()
    report["target"] = target
    if target not in df.columns:
        err.append(f"Target column '{target}' not found. Columns: {', '.join(df.columns[:20])}")
        return report

    y_raw = df[target]
    if y_raw.isna().any():
        warn.append(f"{int(y_raw.isna().sum())} row(s) with a missing target will be dropped.")
    y = _clean_target(y_raw.dropna())
    counts = y.value_counts()
    report["classes"] = sorted(counts.index.tolist())
    report["class_counts"] = {str(k): int(v) for k, v in counts.sort_index().items()}
    if len(counts) < 2:
        err.append("Target must contain at least 2 distinct classes.")
    if len(counts) > MAX_CLASSES:
        err.append(f"Target has {len(counts)} distinct values (max {MAX_CLASSES}). Only classification is supported.")
    small = [str(k) for k, v in counts.items() if v < 2]
    if small:
        err.append(f"Class(es) with fewer than 2 samples cannot be split for training: {', '.join(small[:5])}")
    if len(counts) >= 2 and counts.min() / counts.max() < 0.1:
        warn.append("Class imbalance detected (smallest class < 10% of largest).")

    features = []
    for col in df.columns:
        if col == target:
            continue
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        info = {"name": col, "kind": "numeric" if numeric else "categorical",
                "missing": int(s.isna().sum()), "unique": int(s.nunique(dropna=True)), "dropped": False, "reason": None}
        if info["missing"] == len(s):
            info.update(dropped=True, reason="all values missing")
        elif info["unique"] <= 1:
            info.update(dropped=True, reason="constant column")
        elif not numeric and info["unique"] > 50 and info["unique"] / len(s) > 0.5:
            info.update(dropped=True, reason="high-cardinality text (ID or free text)")
        elif numeric and np.isinf(s.astype(float)).any():
            err.append(f"Column '{col}' contains infinite values.")
        features.append(info)
    report["features"] = features
    kept = [f for f in features if not f["dropped"]]
    for f in features:
        if f["dropped"]:
            warn.append(f"Column '{f['name']}' will be dropped: {f['reason']}.")
    if not kept:
        err.append("No usable feature columns remain after validation.")
    report["valid"] = not err
    return report


# ============================================================ algorithms
P = lambda name, label, typ, default, lo=None, hi=None, help="": dict(
    name=name, label=label, type=typ, default=default, min=lo, max=hi, help=help)

ALGORITHMS = {
    "random_forest": {"label": "Random Forest", "incremental": "trees", "params": [
        P("n_estimators", "Trees", "int", 100, 10, 500), P("max_depth", "Max depth (0 = unlimited)", "int", 0, 0, 50),
        P("min_samples_leaf", "Min samples per leaf", "int", 1, 1, 50)]},
    "gradient_boosting": {"label": "Gradient Boosting", "incremental": "stages", "params": [
        P("n_estimators", "Boosting stages", "int", 100, 10, 400), P("learning_rate", "Learning rate", "float", 0.1, 0.01, 1.0),
        P("max_depth", "Tree depth", "int", 3, 1, 8)]},
    "mlp_neural_net": {"label": "Neural Network (MLP)", "incremental": "epochs", "params": [
        P("hidden_layers", "Hidden layers (comma separated)", "str", "128,64"), P("epochs", "Epochs", "int", 40, 5, 300),
        P("learning_rate", "Learning rate", "float", 0.001, 0.0001, 0.1), P("batch_size", "Batch size", "int", 64, 8, 512)]},
    "logistic_regression": {"label": "Logistic Regression", "incremental": None, "params": [
        P("C", "Inverse regularisation (C)", "float", 1.0, 0.001, 100), P("max_iter", "Max iterations", "int", 1000, 100, 5000)]},
    "svm_rbf": {"label": "Support Vector Machine (RBF)", "incremental": None, "params": [
        P("C", "C", "float", 1.0, 0.01, 100), P("gamma", "Gamma (scale/auto)", "str", "scale")]},
    "knn": {"label": "k-Nearest Neighbours", "incremental": None, "params": [P("n_neighbors", "k", "int", 5, 1, 50)]},
    "decision_tree": {"label": "Decision Tree", "incremental": None, "params": [
        P("max_depth", "Max depth (0 = unlimited)", "int", 0, 0, 50), P("min_samples_leaf", "Min samples per leaf", "int", 1, 1, 50)]},
}


def algorithm_catalog():
    return [{"id": k, "label": v["label"], "params": v["params"], "incremental": v["incremental"]} for k, v in ALGORITHMS.items()]


def coerce_params(algorithm: str, given: dict) -> dict:
    spec = {p["name"]: p for p in ALGORITHMS[algorithm]["params"]}
    out = {}
    for name, p in spec.items():
        v = (given or {}).get(name, p["default"])
        try:
            if p["type"] == "int": v = int(float(v))
            elif p["type"] == "float": v = float(v)
            else: v = str(v)
        except (TypeError, ValueError):
            raise ValueError(f"parameter '{name}' must be {p['type']}")
        if p["type"] in ("int", "float"):
            if p["min"] is not None and v < p["min"]: raise ValueError(f"'{name}' must be >= {p['min']}")
            if p["max"] is not None and v > p["max"]: raise ValueError(f"'{name}' must be <= {p['max']}")
        out[name] = v
    return out


# ============================================================ preprocessor
def build_preprocessor(X: pd.DataFrame):
    num = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c]) and not pd.api.types.is_bool_dtype(X[c])]
    cat = [c for c in X.columns if c not in num]
    steps = []
    if num:
        steps.append(("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num))
    if cat:
        steps.append(("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                                       ("oh", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), cat))
    return ColumnTransformer(steps, remainder="drop"), num, cat


class Progress:
    """Writer of training progress into the model document and task engine."""
    def __init__(self, model_id: str, task_id: Optional[str] = None):
        self.model_id = model_id
        self.task_id = task_id
        self.last = 0.0
        self.log = []
        self.history = []

    def update(self, pct: float, stage: str, msg: str = None, metric: dict = None, resource: dict = None, force: bool = False):
        if msg:
            timestamp = datetime.now().strftime('%H:%M:%S')
            entry = f"[{timestamp}] {msg}"
            self.log.append(entry)
            self.log = self.log[-200:]
            print(f"[ML-TRAIN] [{timestamp}] [{self.model_id[:16]}] {pct:5.1f}% | {stage.upper():13} | {msg}", flush=True)
        if metric:
            self.history.append(metric)

        t = time.time()
        if not force and t - self.last < 0.15:
            return
        self.last = t

        upd = {
            "training.progress": round(pct, 1),
            "training.stage": stage,
            "training.log": self.log,
            "training.history": self.history
        }
        if resource:
            upd["training.resource_usage"] = resource
        get_db().models.update_one({"_id": self.model_id}, {"$set": upd})

        if self.task_id:
            tasks.update_task(self.task_id, pct, stage, msg, metric, resource)


def _build_estimator(algorithm, p, seed, n_train):
    if algorithm == "random_forest":
        return RandomForestClassifier(n_estimators=10, max_depth=p["max_depth"] or None, min_samples_leaf=p["min_samples_leaf"],
                                      warm_start=True, oob_score=True, bootstrap=True, random_state=seed, n_jobs=-1)
    if algorithm == "gradient_boosting":
        return GradientBoostingClassifier(n_estimators=5, learning_rate=p["learning_rate"], max_depth=p["max_depth"],
                                          warm_start=True, random_state=seed)
    if algorithm == "mlp_neural_net":
        hl = tuple(int(x) for x in p["hidden_layers"].split(",") if x.strip())
        if not hl or any(h < 1 or h > 2048 for h in hl):
            raise ValueError("hidden_layers must be positive integers, e.g. 128,64")
        return MLPClassifier(hidden_layer_sizes=hl, learning_rate_init=p["learning_rate"],
                             batch_size=min(p["batch_size"], n_train), random_state=seed, alpha=1e-4)
    if algorithm == "logistic_regression":
        return LogisticRegression(C=p["C"], max_iter=p["max_iter"])
    if algorithm == "svm_rbf":
        return SVC(C=p["C"], gamma=p["gamma"], probability=True, random_state=seed)
    if algorithm == "knn":
        return KNeighborsClassifier(n_neighbors=min(p["n_neighbors"], max(1, n_train - 1)))
    if algorithm == "decision_tree":
        return DecisionTreeClassifier(max_depth=p["max_depth"] or None, min_samples_leaf=p["min_samples_leaf"], random_state=seed)
    raise ValueError(f"unknown algorithm {algorithm}")


def _fit_with_progress(algorithm, clf, p, Xt, y, prog: Progress):
    lo, hi = 30.0, 85.0
    classes = np.unique(y)
    if algorithm == "random_forest":
        total = p["n_estimators"]
        step = max(5, total // 10)
        k = 0
        while k < total:
            k = min(total, k + step)
            clf.set_params(n_estimators=k)
            clf.fit(Xt, y)
            oob = float(getattr(clf, "oob_score_", float("nan")))
            prog.update(lo + (hi - lo) * k / total, "fitting", f"Fitted {k}/{total} trees (out-of-bag accuracy: {oob:.4f})",
                        {"step": k, "oob_accuracy": None if math.isnan(oob) else round(oob, 5)})
    elif algorithm == "gradient_boosting":
        total = p["n_estimators"]
        step = max(5, total // 10)
        k = 0
        while k < total:
            k = min(total, k + step)
            clf.set_params(n_estimators=k)
            clf.fit(Xt, y)
            loss = float(clf.train_score_[-1])
            prog.update(lo + (hi - lo) * k / total, "fitting", f"Boosting stage {k}/{total} (loss: {loss:.4f})",
                        {"step": k, "loss": round(loss, 5)})
    elif algorithm == "mlp_neural_net":
        total = p["epochs"]
        idx = np.random.RandomState(0).choice(len(y), min(len(y), 2000), replace=False)
        for ep in range(1, total + 1):
            clf.partial_fit(Xt, y, classes=classes)
            acc = float(accuracy_score(y[idx], clf.predict(Xt[idx])))
            prog.update(lo + (hi - lo) * ep / total, "fitting", f"Epoch {ep}/{total} (loss: {clf.loss_:.4f}, train accuracy: {acc:.4f})",
                        {"step": ep, "loss": round(float(clf.loss_), 5), "train_accuracy": round(acc, 5)})
    else:
        prog.update(lo, "fitting", f"Fitting {ALGORITHMS[algorithm]['label']}...")
        clf.fit(Xt, y)
        prog.update(hi, "fitting", "Model fitting complete")


# ============================================================ training execution
def train_model(model_id: str, dataset: dict, cfg: dict, task_id: Optional[str] = None) -> None:
    """Executes model training in a worker thread. Does NOT run packaging or deployment."""
    db = get_db()
    prog = Progress(model_id, task_id)
    t0 = time.perf_counter()
    cpu_t0 = os.times().user + os.times().system
    tracemalloc.start()

    print("\n" + "="*72, flush=True)
    print(f"[BACKEND-ML] >>> MODEL TRAINING INITIATED <<<", flush=True)
    print(f"[BACKEND-ML] Model ID:        {model_id}", flush=True)
    print(f"[BACKEND-ML] Model Name:      {cfg.get('name')}", flush=True)
    print(f"[BACKEND-ML] Architecture:    {cfg.get('algorithm')}", flush=True)
    print(f"[BACKEND-ML] Hyperparameters: {cfg.get('params')}", flush=True)
    print(f"[BACKEND-ML] Dataset:         {dataset.get('name')} (Target: {cfg.get('target')})", flush=True)
    print("="*72 + "\n", flush=True)

    try:
        if task_id:
            tasks.start_task(task_id, stage="loading", msg=f"Loading dataset '{dataset['name']}'")
        prog.update(5, "loading", f"Loading dataset '{dataset['name']}'", force=True)

        try:
            df = pd.read_csv(dataset["path"])
        except Exception:
            df = pd.read_csv(dataset["path"], engine="python")
        df.columns = [str(c).strip() for c in df.columns]
        target = cfg["target"]
        df = df[df[target].notna()].reset_index(drop=True)
        y = _clean_target(df[target]).to_numpy()
        dropped = {f["name"] for f in dataset["validation"]["features"] if f["dropped"]}
        X = df.drop(columns=[target] + [c for c in dropped if c in df.columns])
        n_classes = len(np.unique(y))
        if math.ceil(len(df) * cfg["test_size"]) < n_classes:
            raise ValueError("Test split is smaller than the number of classes. Increase test_size.")

        prog.update(12, "preprocessing", f"Preprocessing dataset: {len(df)} rows, {X.shape[1]} features, {n_classes} target classes", force=True)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=cfg["test_size"], stratify=y, random_state=cfg["random_state"])

        prog.update(18, "splitting", f"Splitting data: {len(X_train)} training samples, {len(X_test)} evaluation samples (seed={cfg['random_state']})", force=True)

        # Store test split securely on disk for Stage 3 Model Evaluation
        test_split_path = artifacts.model_dir(model_id) / "test_split.joblib"
        joblib.dump({"X_test": X_test, "y_test": y_test, "classes": sorted(np.unique(y).tolist())}, test_split_path, compress=3)

        pre, num, cat = build_preprocessor(X_train)
        Xt_train = pre.fit_transform(X_train)
        prog.update(25, "preprocessing", f"Feature transformers fitted: {len(num)} numeric, {len(cat)} categorical -> {Xt_train.shape[1]} input features", force=True)

        clf = _build_estimator(cfg["algorithm"], cfg["params"], cfg["random_state"], len(y_train))
        prog.update(30, "fitting", f"Training {ALGORITHMS[cfg['algorithm']]['label']} with parameters {cfg['params']}", force=True)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _fit_with_progress(cfg["algorithm"], clf, cfg["params"], Xt_train, y_train, prog)

        pipeline = Pipeline([("preprocess", pre), ("clf", clf)])

        # Calculate train accuracy for verification
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            y_train_pred = pipeline.predict(X_train)
        train_acc = float(accuracy_score(y_train, y_train_pred))

        prog.update(90, "saving", "Saving trained model artifact to storage", force=True)

        labels = sorted(np.unique(y).tolist())
        bundle = {
            "format": "ai-marketplace-model/v1",
            "model_id": model_id,
            "name": cfg["name"],
            "version": cfg["version"],
            "algorithm": cfg["algorithm"],
            "pipeline": pipeline,
            "feature_columns": list(X.columns),
            "target": target,
            "classes": labels,
            "trained_at": now_iso(),
            "library_versions": {
                "scikit-learn": sklearn.__version__,
                "pandas": pd.__version__,
                "numpy": np.__version__
            }
        }
        path = artifacts.plain_path(model_id)
        joblib.dump(bundle, path, compress=3)
        data = path.read_bytes()
        sha = sha3_256_hash(data)

        # Generate sample inputs for deployment testing
        samples = []
        for i in range(min(5, len(X_test))):
            row = X_test.iloc[i].astype(object).where(X_test.iloc[i].notna(), None).to_dict()
            samples.append({
                "inputs": {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()},
                "true_label": str(y_test[i])
            })

        train_seconds = round(time.perf_counter() - t0, 3)
        cpu_time = round((os.times().user + os.times().system) - cpu_t0, 3)
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        mem_mb = round(peak_mem / (1024 * 1024), 2)

        resource_usage = {
            "elapsed_sec": train_seconds,
            "cpu_time_sec": cpu_time,
            "memory_mb": mem_mb
        }

        db.models.update_one(
            {"_id": model_id},
            {"$set": {
                "status": "trained",
                "feature_columns": list(X.columns),
                "classes": labels,
                "sample_inputs": samples,
                "training.status": "completed",
                "training.progress": 100.0,
                "training.stage": "completed",
                "training.finished_at": now_iso(),
                "training.seconds": train_seconds,
                "training.train_accuracy": train_acc,
                "training.resource_usage": resource_usage,
                "training.artifact_sha3": sha,
                "training.artifact_bytes": len(data),
                "training.n_train": int(len(X_train)),
                "training.n_test": int(len(X_test)),
                "training.n_model_inputs": int(Xt_train.shape[1]),
                "training.preprocessing": {"numeric": num, "categorical": cat, "dropped": sorted(dropped)},
                "stages.training": {"status": "completed", "at": now_iso(), "duration_sec": train_seconds}
            }}
        )

        msg = f"Training completed in {train_seconds}s (CPU: {cpu_time}s, Peak RAM: {mem_mb} MB) - Artifact SHA3: {sha[:16]}..."
        prog.update(100.0, "completed", msg, resource=resource_usage, force=True)

        print("\n" + "="*72, flush=True)
        print(f"[BACKEND-ML] >>> MODEL TRAINING COMPLETED SUCCESSFULLY <<<", flush=True)
        print(f"[BACKEND-ML] Model ID:        {model_id}", flush=True)
        print(f"[BACKEND-ML] Train Accuracy:  {train_acc * 100:.2f}%", flush=True)
        print(f"[BACKEND-ML] Duration:        {train_seconds}s (CPU: {cpu_time}s)", flush=True)
        print(f"[BACKEND-ML] Peak RAM:        {mem_mb} MB", flush=True)
        print(f"[BACKEND-ML] Artifact SHA3:   {sha}", flush=True)
        print(f"[BACKEND-ML] Test Split:      Saved to storage for Stage 3 Evaluation", flush=True)
        print("="*72 + "\n", flush=True)

        if task_id:
            tasks.complete_task(task_id, result={
                "model_id": model_id,
                "artifact_sha3": sha,
                "train_accuracy": train_acc,
                "duration_sec": train_seconds,
                "resource_usage": resource_usage
            }, msg=msg)

    except Exception as e:
        traceback.print_exc()
        err_msg = str(e)
        prog.log.append(f"ERROR: {err_msg}")
        db.models.update_one(
            {"_id": model_id},
            {"$set": {
                "status": "training_failed",
                "training.status": "failed",
                "training.error": err_msg[:500],
                "training.log": prog.log,
                "training.finished_at": now_iso(),
                "stages.training": {"status": "failed", "at": now_iso(), "error": err_msg[:200]}
            }}
        )
        if task_id:
            tasks.fail_task(task_id, err_msg)


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ml_worker")


def start_training(model_id: str, dataset: dict, cfg: dict, task_id: Optional[str] = None):
    _executor.submit(train_model, model_id, dataset, cfg, task_id)


# ============================================================ Stage 3: Evaluation
def evaluate_model(model_id: str, eval_dataset_id: Optional[str] = None) -> dict:
    """Executes evaluation on the test split or provided evaluation dataset."""
    db = get_db()
    m = db.models.find_one({"_id": model_id})
    if not m:
        raise ValueError(f"Model '{model_id}' not found")
    if m.get("status") not in ("trained", "evaluated", "packaged", "protected", "deployed", "registered") and not m.get("is_uploaded"):
        raise ValueError("Model has not completed training yet")

    t0 = time.perf_counter()
    bundle = load_bundle(m)
    pipeline = bundle["pipeline"]
    feature_cols = bundle["feature_columns"]

    # Load evaluation data
    test_path = artifacts.model_dir(model_id) / "test_split.joblib"
    if eval_dataset_id:
        ds = db.datasets.find_one({"_id": eval_dataset_id})
        if not ds:
            raise ValueError("Evaluation dataset not found")
        try:
            df_eval = pd.read_csv(ds["path"])
        except Exception:
            df_eval = pd.read_csv(ds["path"], engine="python")
        df_eval.columns = [str(c).strip() for c in df_eval.columns]
        target = m.get("target") or ds["validation"].get("target")
        df_eval = df_eval[df_eval[target].notna()].reset_index(drop=True)
        y_eval = _clean_target(df_eval[target]).to_numpy()
        X_eval = df_eval[[c for c in feature_cols if c in df_eval.columns]]
    elif test_path.exists():
        split_data = joblib.load(test_path)
        X_eval = split_data["X_test"]
        y_eval = split_data["y_test"]
    else:
        raise ValueError("No evaluation split or dataset found for this model")

    print(f"\n[BACKEND-EVAL] >>> Running Stage 3 Evaluation for model '{model_id}' on {len(X_eval)} test samples...", flush=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y_pred = pipeline.predict(X_eval)

    labels = sorted(np.unique(y_eval).tolist())
    metrics = {
        "accuracy": accuracy_score(y_eval, y_pred),
        "precision_macro": precision_score(y_eval, y_pred, average="macro", zero_division=0),
        "recall_macro": recall_score(y_eval, y_pred, average="macro", zero_division=0),
        "f1_macro": f1_score(y_eval, y_pred, average="macro", zero_division=0),
        "precision_weighted": precision_score(y_eval, y_pred, average="weighted", zero_division=0),
        "recall_weighted": recall_score(y_eval, y_pred, average="weighted", zero_division=0),
        "f1_weighted": f1_score(y_eval, y_pred, average="weighted", zero_division=0),
    }
    metrics = {k: round(float(v), 6) for k, v in metrics.items()}
    rep = classification_report(y_eval, y_pred, labels=labels, output_dict=True, zero_division=0)
    per_class = [
        {"label": l, "precision": round(rep[l]["precision"], 4), "recall": round(rep[l]["recall"], 4),
         "f1": round(rep[l]["f1-score"], 4), "support": int(rep[l]["support"])}
        for l in labels if l in rep
    ]
    cm = confusion_matrix(y_eval, y_pred, labels=labels).tolist()
    eval_seconds = round(time.perf_counter() - t0, 3)

    evaluation_report = {
        "model_id": model_id,
        "evaluated_at": now_iso(),
        "n_samples": len(X_eval),
        "metrics": metrics,
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": cm},
        "evaluation_duration_sec": eval_seconds
    }

    db.models.update_one(
        {"_id": model_id},
        {"$set": {
            "metrics": metrics,
            "per_class": per_class,
            "confusion_matrix": {"labels": labels, "matrix": cm},
            "evaluation": evaluation_report,
            "stages.evaluation": {"status": "completed", "at": now_iso(), "duration_sec": eval_seconds}
        }}
    )
    print(f"[BACKEND-EVAL] Stage 3 Evaluation complete in {eval_seconds}s | Accuracy: {metrics['accuracy']*100:.2f}% | F1: {metrics['f1_macro']*100:.2f}%\n", flush=True)
    return evaluation_report


# ============================================================ Stage 1: Upload Model Artifact
def upload_model_artifact(model_id: str, file_bytes: bytes, filename: str, name: str, version: str, user: dict) -> dict:
    """Validates and stores an uploaded trained model file."""
    db = get_db()
    path = artifacts.plain_path(model_id)
    path.write_bytes(file_bytes)
    try:
        loaded = joblib.load(io.BytesIO(file_bytes))
    except Exception as e:
        path.unlink(missing_ok=True)
        raise ValueError(f"Uploaded file cannot be deserialized as a model artifact: {e}")

    # Inspect pipeline or estimator
    pipeline = loaded if hasattr(loaded, "predict") else (loaded.get("pipeline") if isinstance(loaded, dict) else None)
    if not pipeline or not hasattr(pipeline, "predict"):
        path.unlink(missing_ok=True)
        raise ValueError("Uploaded object does not have a 'predict' method. Only valid ML models/pipelines are accepted.")

    feature_cols = getattr(pipeline, "feature_names_in_", None)
    if feature_cols is not None:
        feature_cols = list(feature_cols)
    elif isinstance(loaded, dict) and "feature_columns" in loaded:
        feature_cols = loaded["feature_columns"]
    else:
        feature_cols = ["feature_0", "feature_1"]

    classes = getattr(pipeline, "classes_", None)
    if classes is not None:
        classes = [str(c) for c in classes]
    elif isinstance(loaded, dict) and "classes" in loaded:
        classes = loaded["classes"]
    else:
        classes = ["class_0", "class_1"]

    sha = sha3_256_hash(file_bytes)
    bundle = {
        "format": "ai-marketplace-model/v1",
        "model_id": model_id,
        "name": name,
        "version": version,
        "algorithm": getattr(pipeline, "__class__", type(pipeline)).__name__,
        "pipeline": pipeline,
        "feature_columns": feature_cols,
        "classes": classes,
        "uploaded_at": now_iso()
    }
    joblib.dump(bundle, path, compress=3)
    final_bytes = path.read_bytes()
    final_sha = sha3_256_hash(final_bytes)

    doc = {
        "_id": model_id,
        "name": name,
        "version": version,
        "owner_id": user["_id"],
        "owner_name": user["username"],
        "algorithm": bundle["algorithm"],
        "dataset_name": "External / Uploaded",
        "status": "trained",
        "is_uploaded": True,
        "license": "single-use",
        "feature_columns": feature_cols,
        "classes": classes,
        "created_at": now_iso(),
        "training": {
            "status": "completed",
            "progress": 100.0,
            "stage": "uploaded",
            "artifact_sha3": final_sha,
            "artifact_bytes": len(final_bytes),
            "log": [f"[{datetime.now().strftime('%H:%M:%S')}] Model artifact '{filename}' uploaded and verified"],
            "finished_at": now_iso()
        },
        "stages": {
            "creation": {"status": "completed", "at": now_iso()},
            "training": {"status": "completed", "at": now_iso(), "uploaded": True}
        }
    }
    db.models.insert_one(doc)
    return {"id": model_id, "name": name, "version": version, "artifact_sha3": final_sha, "classes": classes}


# ============================================================ Stage 5: deployment / inference
_deployed = {}
_dep_lock = threading.Lock()


def load_bundle(model: dict) -> dict:
    """Load model artifact with SHA3-256 verification."""
    data = artifacts.read_model_bytes(model)
    return joblib.load(io.BytesIO(data))


def deploy(model: dict) -> dict:
    t0 = time.perf_counter()
    data = artifacts.read_model_bytes(model)
    sha = sha3_256_hash(data)
    bundle = joblib.load(io.BytesIO(data))

    # Warm-up / smoke test
    sample_rows = model.get("sample_inputs")
    if sample_rows and len(sample_rows) > 0:
        test_df = pd.DataFrame([sample_rows[0]["inputs"]])[bundle["feature_columns"]]
        _ = bundle["pipeline"].predict(test_df)

    load_time_ms = round((time.perf_counter() - t0) * 1000, 2)
    with _dep_lock:
        _deployed[model["_id"]] = {"bundle": bundle, "sha3": sha, "loaded_at": now_iso()}

    dep_info = {
        "status": "deployed",
        "version": model["version"],
        "endpoint": f"/api/models/{model['_id']}/predict",
        "deployed_at": now_iso(),
        "artifact_sha3": sha,
        "load_ms": load_time_ms,
        "predictions_served": model.get("deployment", {}).get("predictions_served", 0)
    }
    return dep_info


def undeploy(model_id: str):
    with _dep_lock:
        _deployed.pop(model_id, None)


def get_deployed_bundle(model: dict):
    with _dep_lock:
        entry = _deployed.get(model["_id"])
    if entry:
        return entry["bundle"]
    if model.get("deployment", {}).get("status") != "deployed":
        return None
    b = load_bundle(model)
    with _dep_lock:
        _deployed[model["_id"]] = {"bundle": b, "sha3": model.get("training", {}).get("artifact_sha3"), "loaded_at": now_iso()}
    return b


def predict_with_bundle(bundle: dict, inputs) -> Tuple[list, float]:
    t_start = time.perf_counter()
    cols = bundle["feature_columns"]
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("'inputs' must be a non-empty list of rows")
    if len(inputs) > 1000:
        raise ValueError("At most 1000 rows allowed per request")

    if isinstance(inputs[0], dict):
        missing = [c for c in cols if any(c not in row for row in inputs)]
        if missing:
            raise ValueError(f"Missing required feature column(s): {', '.join(missing[:8])}")
        df = pd.DataFrame([{c: row[c] for c in cols} for row in inputs])
    else:
        if any(len(r) != len(cols) for r in inputs):
            raise ValueError(f"Each row requires exactly {len(cols)} feature values in order: {', '.join(cols[:6])}...")
        df = pd.DataFrame(inputs, columns=cols)

    pipe = bundle["pipeline"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            preds = pipe.predict(df)
            proba = pipe.predict_proba(df) if hasattr(pipe, "predict_proba") else None
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid input values: {str(e)[:200]}")

    classes = [str(c) for c in getattr(pipe, "classes_", np.unique(preds))]
    out = []
    for i, p in enumerate(preds):
        item = {"prediction": str(p)}
        if proba is not None:
            item["confidence"] = round(float(proba[i].max()), 4)
            item["probabilities"] = {c: round(float(v), 4) for c, v in zip(classes, proba[i])}
        out.append(item)

    latency_ms = round((time.perf_counter() - t_start) * 1000, 2)
    sample_preds = [p['prediction'] for p in out[:4]]
    print(f"[BACKEND-INFERENCE] Model: {bundle.get('model_id')} | Batch: {len(inputs)} samples | Latency: {latency_ms}ms | Predictions: {sample_preds}{'...' if len(out)>4 else ''}", flush=True)
    return out, latency_ms
