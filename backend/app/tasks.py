"""
tasks.py - Asynchronous task tracking engine for ML lifecycle operations.
Maintains task state, execution history, timestamped logs, and resource metrics.
"""
import copy
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import get_db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_task(task_type: str, model_id: str, name: str, user_id: Optional[str] = None) -> dict:
    db = get_db()
    task_id = f"tsk_{datetime.now(timezone.utc):%Y%m%d%H%M%S}_{secrets.token_hex(4)}"
    task = {
        "_id": task_id,
        "id": task_id,
        "type": task_type,
        "model_id": model_id,
        "name": name,
        "user_id": user_id,
        "status": "queued",
        "progress": 0.0,
        "stage": "queued",
        "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Task {task_id} initialized ({task_type})"],
        "history": [],
        "resource_usage": {"elapsed_sec": 0.0, "cpu_time_sec": 0.0, "memory_mb": 0.0},
        "result": None,
        "error": None,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    db.tasks.insert_one(task)
    return task


def start_task(task_id: str, stage: str = "running", msg: Optional[str] = None) -> None:
    db = get_db()
    logs_to_add = [f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"] if msg else []
    t = db.tasks.find_one({"_id": task_id})
    current_logs = t.get("logs", []) if t else []
    current_logs.extend(logs_to_add)
    db.tasks.update_one(
        {"_id": task_id},
        {"$set": {
            "status": "running",
            "stage": stage,
            "started_at": now_iso(),
            "logs": current_logs[-300:]
        }}
    )


def update_task(
    task_id: str,
    progress: float,
    stage: str,
    msg: Optional[str] = None,
    metric: Optional[Dict[str, Any]] = None,
    resource: Optional[Dict[str, Any]] = None
) -> None:
    db = get_db()
    t = db.tasks.find_one({"_id": task_id})
    if not t:
        return
    logs = t.get("logs", [])
    if msg:
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    history = t.get("history", [])
    if metric:
        history.append(metric)

    upd: Dict[str, Any] = {
        "status": "running",
        "progress": round(min(100.0, max(0.0, progress)), 1),
        "stage": stage,
        "logs": logs[-300:],
        "history": history,
    }
    if resource:
        upd["resource_usage"] = resource
    db.tasks.update_one({"_id": task_id}, {"$set": upd})


def complete_task(task_id: str, result: Optional[Dict[str, Any]] = None, msg: Optional[str] = None) -> None:
    db = get_db()
    t = db.tasks.find_one({"_id": task_id})
    logs = t.get("logs", []) if t else []
    if msg:
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task completed successfully")
    db.tasks.update_one(
        {"_id": task_id},
        {"$set": {
            "status": "completed",
            "progress": 100.0,
            "stage": "completed",
            "result": result or {},
            "finished_at": now_iso(),
            "logs": logs[-300:]
        }}
    )


def fail_task(task_id: str, error: str) -> None:
    db = get_db()
    t = db.tasks.find_one({"_id": task_id})
    logs = t.get("logs", []) if t else []
    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {error}")
    db.tasks.update_one(
        {"_id": task_id},
        {"$set": {
            "status": "failed",
            "stage": "failed",
            "error": str(error)[:500],
            "finished_at": now_iso(),
            "logs": logs[-300:]
        }}
    )


def get_task(task_id: str) -> Optional[dict]:
    db = get_db()
    t = db.tasks.find_one({"_id": task_id})
    if not t:
        return None
    out = copy.deepcopy(t)
    out["id"] = out.get("_id")
    return out


def get_model_tasks(model_id: str) -> List[dict]:
    db = get_db()
    tasks = db.tasks.find({"model_id": model_id}, sort=[("created_at", -1)])
    out = []
    for t in tasks:
        item = copy.deepcopy(t)
        item["id"] = item.get("_id")
        out.append(item)
    return out
