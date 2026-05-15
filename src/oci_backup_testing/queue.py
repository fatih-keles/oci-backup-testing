from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state import utc_now


SCHEMA_VERSION = 1


def new_queue() -> dict[str, Any]:
    now = utc_now()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": f"{stamp}-{uuid4().hex[:8]}",
        "created_at": now,
        "updated_at": now,
        "executions": [],
    }


def init_queue(path: str | Path) -> dict[str, Any]:
    queue = new_queue()
    save_queue(path, queue)
    return queue


def load_queue(path: str | Path, create_if_missing: bool = False) -> dict[str, Any]:
    queue_path = Path(path).expanduser()
    if not queue_path.exists():
        if create_if_missing:
            return init_queue(queue_path)
        raise FileNotFoundError(f"Queue file does not exist: {queue_path}")

    with queue_path.open("r", encoding="utf-8") as stream:
        queue = json.load(stream)
    if not isinstance(queue, dict) or queue.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported queue file schema in {queue_path}")
    queue.setdefault("executions", [])
    return queue


def save_queue(path: str | Path, queue: dict[str, Any]) -> None:
    queue_path = Path(path).expanduser()
    queue["updated_at"] = utc_now()
    tmp_path = queue_path.with_suffix(queue_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as stream:
        json.dump(queue, stream, indent=2, sort_keys=True)
        stream.write("\n")
    tmp_path.replace(queue_path)


def clear_queue(path: str | Path) -> bool:
    queue_path = Path(path).expanduser()
    if not queue_path.exists():
        return False
    queue_path.unlink()
    return True


def upsert_queue_execution(queue: dict[str, Any], execution: dict[str, Any]) -> None:
    run_id = execution["run_id"]
    executions = queue.setdefault("executions", [])
    for index, existing in enumerate(executions):
        if existing.get("run_id") == run_id:
            executions[index] = dict(execution)
            return
    executions.append(dict(execution))
