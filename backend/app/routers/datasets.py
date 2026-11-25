import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import config, ml
from ..db import get_db
from ..deps import current_user

router = APIRouter()
SAMPLES_DIR = config.ROOT / "datasets"
SAMPLES = {
    "digits": "Handwritten digits (8x8 pixels, 10 classes, 1797 rows)",
    "iris": "Iris flowers (4 features, 3 classes, 150 rows)",
    "wine": "Wine cultivars (13 features, 3 classes, 178 rows)",
    "breast_cancer": "Breast cancer diagnosis (30 features, 2 classes, 569 rows)",
    "cifar10_subset": "CIFAR-10 subset (run datasets/prepare_cifar10.py first)",
}


def _public(d):
    out = {k: v for k, v in d.items() if k != "path"}
    out["id"] = out.pop("_id")
    return out


def _register_dataset(user, name, filename, path: Path, source, target):
    sha = hashlib.sha3_256(path.read_bytes()).hexdigest()
    report = ml.analyze_csv(str(path), target)
    ds = {"_id": "ds_" + uuid.uuid4().hex[:10], "owner_id": user["_id"], "owner_name": user["username"], "name": name,
          "filename": filename, "path": str(path), "size_bytes": path.stat().st_size, "sha3": sha, "source": source,
          "created_at": ml.now_iso(), "validation": report}
    get_db().datasets.insert_one(ds)
    return ds


@router.get("/datasets/samples")
def list_samples(user=Depends(current_user)):
    return [{"name": n, "description": d, "available": (SAMPLES_DIR / f"{n}.csv").exists()} for n, d in SAMPLES.items()]


@router.post("/datasets/samples/{name}/use", status_code=201)
def use_sample(name: str, user=Depends(current_user)):
    if name not in SAMPLES: raise HTTPException(404, "unknown sample dataset")
    src = SAMPLES_DIR / f"{name}.csv"
    if not src.exists(): raise HTTPException(404, f"{name}.csv is not available - see datasets/README.md")
    dst_dir = config.STORAGE_DIR / "datasets"; dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{uuid.uuid4().hex[:8]}_{name}.csv"
    shutil.copyfile(src, dst)
    return _public(_register_dataset(user, name, f"{name}.csv", dst, "bundled sample", None))


@router.post("/datasets/upload", status_code=201)
async def upload_dataset(file: UploadFile = File(...), name: str = Form(""), target_column: str = Form(""),
                         user=Depends(current_user)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "only .csv files are supported")
    dst_dir = config.STORAGE_DIR / "datasets"; dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    limit, size = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    with open(dst, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                f.close(); dst.unlink(missing_ok=True)
                raise HTTPException(413, f"file larger than {config.MAX_UPLOAD_MB} MB")
            f.write(chunk)
    ds = _register_dataset(user, name.strip() or Path(file.filename).stem, file.filename, dst, "upload", target_column.strip() or None)
    return _public(ds)


@router.get("/datasets")
def list_datasets(user=Depends(current_user)):
    return [_public(d) for d in get_db().datasets.find({"owner_id": user["_id"]}, sort=[("created_at", -1)])]


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, user=Depends(current_user)):
    d = get_db().datasets.find_one({"_id": dataset_id, "owner_id": user["_id"]})
    if not d: raise HTTPException(404, "dataset not found")
    return _public(d)
