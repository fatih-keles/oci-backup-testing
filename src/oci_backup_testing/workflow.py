from __future__ import annotations

import sys
from typing import Any
from uuid import uuid4

from .compute import (
    attach_block_volumes,
    classify_restored_volumes,
    create_test_instance,
    wait_for_test_instance,
)
from .config import AppConfig
from .discovery import (
    VolumeGroupPlan,
    discover_volume_group_plans,
    filter_volume_group_plans,
    find_subnet_for_ad,
)
from .oci_clients import OciClients
from .restore import (
    create_restored_volume_group,
    restored_volume_group_display_name,
    wait_for_restored_volume_group,
)
from .queue import save_queue, upsert_queue_execution
from .state import save_state, upsert_execution, utc_now
from .validation import validate_execution


def discover(clients: OciClients, config: AppConfig) -> list[VolumeGroupPlan]:
    return discover_volume_group_plans(clients, config)


def run(
    clients: OciClients,
    config: AppConfig,
    state: dict[str, Any],
    dry_run: bool = False,
    limit: int | None = None,
    volume_group_id: str | None = None,
    queue: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    plans = discover_volume_group_plans(clients, config)
    plans = filter_volume_group_plans(plans, volume_group_id)
    if limit is not None:
        plans = plans[:limit]

    results: list[dict[str, Any]] = []
    for ordinal, plan in enumerate(plans, start=1):
        _progress(f"[{ordinal}/{len(plans)}] Planning {plan.source_display_name}")
        execution = {
            "run_id": str(uuid4()),
            "created_at": utc_now(),
            "phase": "planned",
            **plan.as_dict(),
            "target_compartment_id": config.target_compartment_id,
            "restored_volume_group_id": None,
            "restored_volume_group_display_name": None,
            "boot_volume_id": None,
            "boot_volume_display_name": None,
            "boot_volume_size_in_gbs": None,
            "block_volume_ids": [],
            "block_volume_display_names": [],
            "block_volume_sizes_in_gbs": [],
            "instance_id": None,
            "instance_display_name": None,
            "volume_attachment_ids": [],
            "validation": None,
        }

        if dry_run:
            subnet = find_subnet_for_ad(clients, config, plan.availability_domain)
            execution["phase"] = "dry_run"
            execution["planned_subnet_id"] = subnet.id
            execution["planned_subnet_display_name"] = getattr(subnet, "display_name", None)
            execution["planned_shape"] = config.compute.shape
            execution["planned_ocpus"] = config.compute.ocpus
            execution["planned_memory_in_gbs"] = config.compute.memory_in_gbs
            execution["planned_restored_volume_group_display_name_pattern"] = (
                restored_volume_group_display_name(
                    config.restore.display_name_prefix,
                    plan.source_display_name,
                    plan.source_volume_group_id,
                    "YYYYMMDDHHMMSS",
                )
            )
            execution["planned_actions"] = [
                "restore_latest_volume_group_backup",
                "wait_for_restored_volume_group_available",
                "launch_instance_from_restored_boot_volume",
                "attach_restored_block_volumes",
                "validate_control_plane_states",
            ]
            results.append(execution)
            continue

        _checkpoint(config, state, queue, execution)

        _progress(f"[{ordinal}/{len(plans)}] Requesting restore for {plan.source_display_name}")
        created_group = create_restored_volume_group(clients, config, plan)
        execution.update(
            {
                "phase": "restore_requested",
                "restored_volume_group_id": created_group.id,
                "restored_volume_group_display_name": getattr(
                    created_group, "display_name", None
                ),
            }
        )
        _checkpoint(config, state, queue, execution)

        _progress(
            f"[{ordinal}/{len(plans)}] Waiting for restored volume group "
            f"{created_group.id} to become AVAILABLE"
        )
        restored_group = wait_for_restored_volume_group(clients, config, created_group.id)
        execution["phase"] = "restored"
        _checkpoint(config, state, queue, execution)

        _progress(f"[{ordinal}/{len(plans)}] Classifying restored volumes")
        restored_volumes = classify_restored_volumes(clients, restored_group)
        execution.update(
            {
                "phase": "volumes_classified",
                "boot_volume_id": restored_volumes.boot_volume.id,
                "boot_volume_display_name": getattr(
                    restored_volumes.boot_volume, "display_name", None
                ),
                "boot_volume_size_in_gbs": getattr(
                    restored_volumes.boot_volume, "size_in_gbs", None
                ),
                "block_volume_ids": [volume.id for volume in restored_volumes.block_volumes],
                "block_volume_display_names": [
                    getattr(volume, "display_name", None)
                    for volume in restored_volumes.block_volumes
                ],
                "block_volume_sizes_in_gbs": [
                    getattr(volume, "size_in_gbs", None)
                    for volume in restored_volumes.block_volumes
                ],
            }
        )
        _checkpoint(config, state, queue, execution)

        _progress(f"[{ordinal}/{len(plans)}] Selecting isolated subnet")
        subnet = find_subnet_for_ad(
            clients,
            config,
            restored_volumes.boot_volume.availability_domain,
        )
        _progress(f"[{ordinal}/{len(plans)}] Requesting test instance launch")
        created_instance = create_test_instance(
            clients,
            config,
            restored_group,
            restored_volumes,
            subnet,
            ordinal,
        )
        execution.update(
            {
                "phase": "instance_launch_requested",
                "subnet_id": subnet.id,
                "instance_id": created_instance.id,
                "instance_display_name": getattr(created_instance, "display_name", None),
            }
        )
        _checkpoint(config, state, queue, execution)

        _progress(
            f"[{ordinal}/{len(plans)}] Waiting for test instance "
            f"{getattr(created_instance, 'display_name', created_instance.id)} "
            f"({created_instance.id}) to become RUNNING"
        )
        instance = wait_for_test_instance(clients, config, created_instance.id)
        execution.update(
            {
                "phase": "instance_running",
                "instance_display_name": getattr(instance, "display_name", None)
                or execution.get("instance_display_name"),
            }
        )
        _checkpoint(config, state, queue, execution)

        _progress(f"[{ordinal}/{len(plans)}] Attaching restored block volumes")
        attachments = attach_block_volumes(
            clients,
            config,
            instance,
            restored_volumes.block_volumes,
        )
        execution.update(
            {
                "phase": "volumes_attached",
                "volume_attachment_ids": [attachment.id for attachment in attachments],
            }
        )
        _checkpoint(config, state, queue, execution)

        _progress(f"[{ordinal}/{len(plans)}] Running validation")
        execution.update(
            {
                "phase": "validated",
                "validation": validate_execution(clients, execution),
            }
        )
        _checkpoint(config, state, queue, execution)
        results.append(execution)
        _progress(f"[{ordinal}/{len(plans)}] Completed {plan.source_display_name}")

    return results


def _checkpoint(
    config: AppConfig,
    state: dict[str, Any],
    queue: dict[str, Any] | None,
    execution: dict[str, Any],
) -> None:
    upsert_execution(state, execution)
    save_state(config.state_file, state)
    if queue is not None:
        upsert_queue_execution(queue, execution)
        save_queue(config.queue_file, queue)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
