from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "executions": [],
    }


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path).expanduser()
    if not state_path.exists():
        return empty_state()
    with state_path.open("r", encoding="utf-8") as stream:
        state = json.load(stream)
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported state file schema in {state_path}")
    state.setdefault("executions", [])
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path).expanduser()
    state["updated_at"] = utc_now()
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
        stream.write("\n")
    tmp_path.replace(state_path)


def upsert_execution(state: dict[str, Any], execution: dict[str, Any]) -> None:
    run_id = execution["run_id"]
    executions = state.setdefault("executions", [])
    for index, existing in enumerate(executions):
        if existing.get("run_id") == run_id:
            executions[index] = execution
            return
    executions.append(execution)


def mark_execution_cleaned(
    state: dict[str, Any],
    cleanup_result: dict[str, Any],
    cleanup_status: str = "cleaned",
) -> bool:
    run_id = cleanup_result.get("run_id")
    if not run_id:
        return False
    for execution in state.setdefault("executions", []):
        if execution.get("run_id") == run_id:
            execution["cleanup"] = cleanup_result
            execution["cleanup_status"] = cleanup_status
            execution["cleaned_at"] = utc_now()
            return True
    return False


def prune_state(
    state: dict[str, Any],
    *,
    max_executions: int | None,
    max_age_days: int | None,
    prune_only_cleaned: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    executions = list(state.setdefault("executions", []))
    now = now or datetime.now(timezone.utc)
    pruned_indices: set[int] = set()
    prune_reasons: dict[int, list[str]] = {}

    if max_age_days is not None:
        cutoff = now - timedelta(days=max_age_days)
        for index, execution in enumerate(executions):
            if not _can_prune(execution, prune_only_cleaned):
                continue
            timestamp = _prune_timestamp(execution)
            if timestamp is not None and timestamp < cutoff:
                pruned_indices.add(index)
                prune_reasons.setdefault(index, []).append("max_age_days")

    if max_executions is not None:
        remaining_indices = [
            index for index in range(len(executions)) if index not in pruned_indices
        ]
        excess = len(remaining_indices) - max_executions
        if excess > 0:
            candidates = [
                index
                for index in remaining_indices
                if _can_prune(executions[index], prune_only_cleaned)
            ]
            oldest = datetime.min.replace(tzinfo=timezone.utc)
            candidates.sort(
                key=lambda index: _prune_timestamp(executions[index]) or oldest
            )
            for index in candidates[:excess]:
                pruned_indices.add(index)
                prune_reasons.setdefault(index, []).append("max_executions")

    pruned = [
        _pruned_execution_summary(executions[index], prune_reasons.get(index, []))
        for index in sorted(pruned_indices)
    ]
    state["executions"] = [
        execution
        for index, execution in enumerate(executions)
        if index not in pruned_indices
    ]

    after_count = len(state["executions"])
    protected_count = sum(
        1
        for execution in state["executions"]
        if not _can_prune(execution, prune_only_cleaned)
    )

    return {
        "before_count": len(executions),
        "after_count": after_count,
        "pruned_count": len(pruned),
        "protected_count": protected_count,
        "retention": {
            "max_executions": max_executions,
            "max_age_days": max_age_days,
            "prune_only_cleaned": prune_only_cleaned,
        },
        "retention_limit_met": max_executions is None or after_count <= max_executions,
        "pruned": pruned,
    }


def _can_prune(execution: dict[str, Any], prune_only_cleaned: bool) -> bool:
    if not prune_only_cleaned:
        return True
    return execution.get("cleanup_status") == "cleaned" and bool(
        execution.get("cleaned_at")
    )


def _prune_timestamp(execution: dict[str, Any]) -> datetime | None:
    return _parse_datetime(execution.get("cleaned_at")) or _parse_datetime(
        execution.get("created_at")
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _pruned_execution_summary(
    execution: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "run_id": execution.get("run_id"),
        "source_display_name": execution.get("source_display_name"),
        "phase": execution.get("phase"),
        "created_at": execution.get("created_at"),
        "cleaned_at": execution.get("cleaned_at"),
        "reasons": reasons,
    }
