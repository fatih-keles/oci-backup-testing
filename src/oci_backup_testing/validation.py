from __future__ import annotations

from typing import Any

from .oci_clients import OciClients


def validate_execution(
    clients: OciClients,
    execution: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    restored_volume_group_id = execution.get("restored_volume_group_id")
    if restored_volume_group_id:
        volume_group = clients.block.get_volume_group(restored_volume_group_id).data
        checks.append(
            {
                "name": "restored_volume_group_available",
                "resource_id": restored_volume_group_id,
                "state": getattr(volume_group, "lifecycle_state", None),
                "passed": getattr(volume_group, "lifecycle_state", None) == "AVAILABLE",
            }
        )

    instance_id = execution.get("instance_id")
    if instance_id:
        instance = clients.compute.get_instance(instance_id).data
        checks.append(
            {
                "name": "instance_running",
                "resource_id": instance_id,
                "state": getattr(instance, "lifecycle_state", None),
                "passed": getattr(instance, "lifecycle_state", None) == "RUNNING",
            }
        )

    for attachment_id in execution.get("volume_attachment_ids", []):
        attachment = clients.compute.get_volume_attachment(attachment_id).data
        checks.append(
            {
                "name": "block_volume_attached",
                "resource_id": attachment_id,
                "state": getattr(attachment, "lifecycle_state", None),
                "passed": getattr(attachment, "lifecycle_state", None) == "ATTACHED",
            }
        )

    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
