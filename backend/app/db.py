"""
db.py - persistence layer.

PRIMARY:   MongoDB (pymongo). Collections: users, datasets, models, grants, downloads,
           sessions, verification_logs.
FALLBACK:  an explicitly-flagged, FILE-BACKED development store (JSON files under
           storage/devdb/). It is persistent across restarts - NOT an in-memory dict - and
           implements the small subset of the pymongo API this application uses. It exists
           only so the project can be run on a machine without MongoDB. The active backend is
           always reported by GET /api/health ("database": {"mode": "mongodb"|"file-fallback"}).

DB_MODE=auto  -> use MongoDB if reachable, otherwise fall back (with a loud warning)
DB_MODE=mongo -> require MongoDB (refuse to start without it)
DB_MODE=file  -> force the file-backed development store

LIMITATION of the fallback: it is a SINGLE-PROCESS store (run one backend worker, no `--workers N`). Another
process that opens the same files (e.g. a test) must call get_db().refresh() to see the server's latest writes.
"""
import copy
import json
import os
import threading
from pathlib import Path

from pymongo.errors import DuplicateKeyError

from . import config

COLLECTIONS = ["users", "datasets", "models", "grants", "downloads", "sessions", "verification_logs", "tasks"]
UNIQUE_INDEXES = {"users": ["username"]}


# ====================================================================== file-backed store
def _get(doc, dotted):
    cur = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _match(doc, flt):
    for key, cond in (flt or {}).items():
        val, found = _get(doc, key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and not (found and val in arg): return False
                if op == "$nin" and (found and val in arg): return False
                if op == "$ne" and (found and val == arg): return False
                if op == "$exists" and (found != bool(arg)): return False
                if op == "$gt" and not (found and val is not None and val > arg): return False
                if op == "$gte" and not (found and val is not None and val >= arg): return False
                if op == "$lt" and not (found and val is not None and val < arg): return False
                if op == "$lte" and not (found and val is not None and val <= arg): return False
        elif not (found and val == cond):
            return False
    return True


def _apply_update(doc, update):
    for op, fields in update.items():
        for key, arg in fields.items():
            parts = key.split(".")
            cur = doc
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            last = parts[-1]
            if op == "$set": cur[last] = copy.deepcopy(arg)
            elif op == "$unset": cur.pop(last, None)
            elif op == "$inc": cur[last] = cur.get(last, 0) + arg
            elif op == "$push": cur.setdefault(last, []).append(copy.deepcopy(arg))
            else: raise NotImplementedError(op)


class FileCollection:
    def __init__(self, name, directory: Path, unique=()):
        self.name, self.unique = name, list(unique)
        self.path = directory / f"{name}.json"
        self._lock = threading.RLock()
        self._docs = {}
        if self.path.exists():
            self._docs = {d["_id"]: d for d in json.loads(self.path.read_text(encoding="utf-8"))}

    def reload(self):
        """Re-read the JSON file (only needed by OTHER processes that inspect the dev DB, e.g. tests)."""
        with self._lock:
            self._docs = {d["_id"]: d for d in json.loads(self.path.read_text(encoding="utf-8"))} if self.path.exists() else {}

    def _flush(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self._docs.values()), default=str), encoding="utf-8")
        os.replace(tmp, self.path)

    def insert_one(self, doc):
        with self._lock:
            if doc["_id"] in self._docs:
                raise DuplicateKeyError(f"duplicate _id in {self.name}")
            for u in self.unique:
                if any(d.get(u) == doc.get(u) for d in self._docs.values()):
                    raise DuplicateKeyError(f"duplicate {u} in {self.name}")
            self._docs[doc["_id"]] = copy.deepcopy(doc)
            self._flush()

    def find_one(self, flt=None, sort=None):
        if sort:
            found = self.find(flt, sort=sort, limit=1)
            return found[0] if found else None
        with self._lock:
            for d in self._docs.values():
                if _match(d, flt):
                    return copy.deepcopy(d)
        return None

    def find(self, flt=None, sort=None, limit=0):
        with self._lock:
            out = [copy.deepcopy(d) for d in self._docs.values() if _match(d, flt)]
        for key, direction in reversed(sort or []):
            out.sort(key=lambda d: (_get(d, key)[0] is None, _get(d, key)[0]), reverse=(direction < 0))
        return out[:limit] if limit else out

    def update_one(self, flt, update):
        with self._lock:
            for d in self._docs.values():
                if _match(d, flt):
                    _apply_update(d, update)
                    self._flush()
                    return 1
        return 0

    def delete_one(self, flt):
        with self._lock:
            for k, d in list(self._docs.items()):
                if _match(d, flt):
                    del self._docs[k]; self._flush(); return 1
        return 0

    def delete_many(self, flt):
        with self._lock:
            keys = [k for k, d in self._docs.items() if _match(d, flt)]
            for k in keys: del self._docs[k]
            if keys: self._flush()
            return len(keys)

    def count_documents(self, flt=None):
        with self._lock:
            return sum(1 for d in self._docs.values() if _match(d, flt))



class MongoCollection:
    """
    Thin adapter over a pymongo Collection so that BOTH backends share one contract:
    find() returns a plain list (pymongo returns a lazy cursor: not truthy-testable, not len()-able,
    single-pass). Everything else is delegated unchanged.
    """
    def __init__(self, collection):
        self._c = collection

    def find(self, flt=None, sort=None, limit=0):
        cur = self._c.find(flt or {})
        if sort:
            cur = cur.sort(sort)
        if limit:
            cur = cur.limit(limit)
        return list(cur)

    def __getattr__(self, name):
        return getattr(self._c, name)


# ====================================================================== connection
class Database:
    def __init__(self):
        self.mode = None              # "mongodb" | "file-fallback"
        self.detail = ""
        self.error = None
        self._cols = {}

    def __getattr__(self, name):
        if name in COLLECTIONS:
            return self._cols[name]
        raise AttributeError(name)

    def refresh(self):
        """Reload file-backed collections from disk (no-op for MongoDB)."""
        for c in self._cols.values():
            if isinstance(c, FileCollection):          # NOT hasattr(): pymongo Collections answer to ANY attribute name
                c.reload()
        return self

    def status(self):
        return {"mode": self.mode, "detail": self.detail, "fallback": self.mode != "mongodb",
                "error": self.error}


_db = None
_lock = threading.Lock()


def get_db() -> Database:
    global _db
    with _lock:
        if _db is None:
            _db = _connect()
        return _db


def _connect() -> Database:
    db = Database()
    if config.DB_MODE in ("auto", "mongo"):
        try:
            from pymongo import MongoClient
            client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            mdb = client[config.MONGODB_DB]
            for name in COLLECTIONS:
                db._cols[name] = MongoCollection(mdb[name])
                for field in UNIQUE_INDEXES.get(name, []):
                    mdb[name].create_index(field, unique=True)
            mdb["models"].create_index("owner_id")
            mdb["verification_logs"].create_index("at")
            db.mode, db.detail = "mongodb", f"{config.MONGODB_URI}/{config.MONGODB_DB}"
            print(f"[db] connected to MongoDB {db.detail}")
            return db
        except Exception as e:
            db.error = str(e)[:200]
            if config.DB_MODE == "mongo":
                raise RuntimeError(f"DB_MODE=mongo but MongoDB is unreachable at {config.MONGODB_URI}: {e}")
            print(f"[db] WARNING: MongoDB unreachable ({db.error}). Using FILE-BACKED DEVELOPMENT FALLBACK "
                  f"in {config.STORAGE_DIR / 'devdb'}. Install/start MongoDB for production use.")
    directory = config.STORAGE_DIR / "devdb"
    directory.mkdir(parents=True, exist_ok=True)
    for name in COLLECTIONS:
        db._cols[name] = FileCollection(name, directory, UNIQUE_INDEXES.get(name, []))
    db.mode, db.detail = "file-fallback", str(directory)
    return db


def reset_for_tests():
    global _db
    _db = None
