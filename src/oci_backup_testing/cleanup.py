from __future__ import annotations

import time
from typing import Any, Callable

from .config import AppConfig
from .oci_clients import OciClients


class CleanupError(RuntimeError):
    """Raised when cleanup cannot finish."""


def cleanup_from_state(
    clients: OciClients,
    config: AppConfig,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    for execution in reversed(state.get("executions", [])):
        results.append(cleanup_execution(clients, config, execution))
    return results


def cleanup_execution(
    clients: OciClients,
    config: AppConfig,
    execution: dict[str, Any],
) -> dict[str, Any]:
    actions: list[dict[str, str]] = []

    if config.cleanup.terminate_instances and execution.get("instance_id"):
        _terminate_instance(clients, config, execution["instance_id"], actions)

    for attachment_id in execution.get("volume_attachment_ids", []):
        _detach_volume_attachment(
            clients,
            config,
            attachment_id,
            actions,
        )

    if config.cleanup.delete_restored_volume_group and execution.get("restored_volume_group_id"):
        _delete_resource(
            clients,
            clients.block.get_volume_group,
            clients.block.delete_volume_group,
            execution["restored_volume_group_id"],
            "volume_group",
            config.cleanup.wait_seconds,
            config.cleanup.wait_interval_seconds,
            actions,
        )

    if config.cleanup.delete_restored_volumes:
        for volume_id in execution.get("block_volume_ids", []):
            _delete_resource(
                clients,
                clients.block.get_volume,
                clients.block.delete_volume,
                volume_id,
                "block_volume",
                config.cleanup.wait_seconds,
                config.cleanup.wait_interval_seconds,
                actions,
            )
        if execution.get("boot_volume_id"):
            _delete_resource(
                clients,
                clients.block.get_boot_volume,
                clients.block.delete_boot_volume,
                execution["boot_volume_id"],
                "boot_volume",
                config.cleanup.wait_seconds,
                config.cleanup.wait_interval_seconds,
                actions,
            )

    return {
        "run_id": execution.get("run_id"),
        "actions": actions,
    }


def _terminate_instance(
    clients: OciClients,
    config: AppConfig,
    instance_id: str,
    actions: list[dict[str, str]],
) -> None:
    try:
        instance = clients.compute.get_instance(instance_id).data
    except Exception as exc:
        if _is_not_found(exc):
            actions.append({"resource": instance_id, "action": "terminate_instance", "status": "not_found"})
            return
        raise

    if getattr(instance, "lifecycle_state", None) == "TERMINATED":
        actions.append({"resource": instance_id, "action": "terminate_instance", "status": "already_terminated"})
        return

    clients.compute.terminate_instance(
        instance_id,
        preserve_boot_volume=config.compute.preserve_boot_volume_on_terminate,
    )
    _wait_for_state_or_not_found(
        clients.compute.get_instance,
        instance_id,
        "TERMINATED",
        config.cleanup.wait_seconds,
        config.cleanup.wait_interval_seconds,
    )
    actions.append({"resource": instance_id, "action": "terminate_instance", "status": "terminated"})


def _detach_volume_attachment(
    clients: OciClients,
    config: AppConfig,
    attachment_id: str,
    actions: list[dict[str, str]],
) -> None:
    try:
        attachment = clients.compute.get_volume_attachment(attachment_id).data
    except Exception as exc:
        if _is_not_found(exc):
            actions.append({"resource": attachment_id, "action": "detach_volume", "status": "not_found"})
            return
        raise

    state = str(getattr(attachment, "lifecycle_state", "")).upper()
    if state == "DETACHED":
        actions.append({"resource": attachment_id, "action": "detach_volume", "status": "already_detached"})
        return

    clients.compute.detach_volume(attachment_id)
    _wait_for_state_or_not_found(
        clients.compute.get_volume_attachment,
        attachment_id,
        "DETACHED",
        config.cleanup.wait_seconds,
        config.cleanup.wait_interval_seconds,
    )
    actions.append({"resource": attachment_id, "action": "detach_volume", "status": "detached"})


def _delete_resource(
    clients: OciClients,
    getter: Callable[[str], Any],
    deleter: Callable[[str], Any],
    resource_id: str,
    resource_kind: str,
    wait_seconds: int,
    wait_interval_seconds: int,
    actions: list[dict[str, str]],
) -> None:
    try:
        getter(resource_id)
    except Exception as exc:
        if _is_not_found(exc):
            actions.append({"resource": resource_id, "action": f"delete_{resource_kind}", "status": "not_found"})
            return
        raise

    try:
        deleter(resource_id)
    except Exception as exc:
        if _is_not_found(exc):
            actions.append({"resource": resource_id, "action": f"delete_{resource_kind}", "status": "not_found"})
            return
        raise

    _wait_until_not_found(getter, resource_id, wait_seconds, wait_interval_seconds)
    actions.append({"resource": resource_id, "action": f"delete_{resource_kind}", "status": "deleted"})


def _wait_for_state_or_not_found(
    getter: Callable[[str], Any],
    resource_id: str,
    expected_state: str,
    wait_seconds: int,
    wait_interval_seconds: int,
) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            resource = getter(resource_id).data
        except Exception as exc:
            if _is_not_found(exc):
                return
            raise
        if str(getattr(resource, "lifecycle_state", "")).upper() == expected_state:
            return
        if time.monotonic() >= deadline:
            raise CleanupError(f"Timed out waiting for {resource_id} to reach {expected_state}")
        time.sleep(wait_interval_seconds)


def _wait_until_not_found(
    getter: Callable[[str], Any],
    resource_id: str,
    wait_seconds: int,
    wait_interval_seconds: int,
) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            resource = getter(resource_id).data
        except Exception as exc:
            if _is_not_found(exc):
                return
            raise
        if str(getattr(resource, "lifecycle_state", "")).upper() == "TERMINATED":
            return
        if time.monotonic() >= deadline:
            raise CleanupError(f"Timed out waiting for {resource_id} to be deleted")
        time.sleep(wait_interval_seconds)


def _is_not_found(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 404
