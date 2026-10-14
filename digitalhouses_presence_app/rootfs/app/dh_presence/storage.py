"""Atomically persist confirmed presence. Corrupted files fail explicitly."""
import json
import os
import tempfile
from pathlib import Path


def load(path: str) -> dict:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema_version": 1, "residents": []}
    data = json.loads(content)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or not isinstance(data.get("residents"), list):
        raise ValueError("Corrupt Presence state; refusing automatic reset")
    for item in data["residents"]:
        if not isinstance(item, dict) or not isinstance(item.get("user_id"), str) or item.get("confirmed") not in ("home", "not_home", "unavailable"):
            raise ValueError("Corrupt persisted resident")
    return data


def save(path: str, data: dict):
    if data.get("schema_version") != 1 or not isinstance(data.get("residents"), list):
        raise ValueError("Invalid persistent state")
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".presence-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        dirfd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
