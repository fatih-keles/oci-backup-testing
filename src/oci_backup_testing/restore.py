from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import AppConfig
from .discovery import VolumeGroupPlan
from .oci_clients import OciClients


def short_ocid(ocid: str) -> str:
    return ocid.rsplit(".", 1)[-1][-8:]


def timestamp_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def restored_volume_group_display_name(
    prefix: str,
    source_display_name: str,
    source_volume_group_id: str,
    timestamp: str | None = None,
) -> str:
    source_name = source_display_name.strip() or "source-volume-group"
    suffix = timestamp or timestamp_suffix()
    return f"{prefix}-{source_name}-{short_ocid(source_volume_group_id)}-{suffix}"


def wait_for_lifecycle(
    clients: OciClients,
    service_client: Any,
    get_response: Any,
    expected_state: str,
    max_wait_seconds: int,
    max_interval_seconds: int,
) -> Any:
    expected = expected_state.upper()
    failure_states = _failure_states_for(expected)

    return clients.oci.wait_until(
        service_client,
        get_response,
        evaluate_response=lambda waiter_response: _wait_evaluator(
            waiter_response,
            expected,
            failure_states,
        ),
        max_wait_seconds=max_wait_seconds,
        max_interval_seconds=max_interval_seconds,
    )


def _wait_evaluator(response: Any, expected_state: str, failure_states: set[str]) -> bool:
    state = str(getattr(response.data, "lifecycle_state", "")).upper()
    if state == expected_state:
        return True
    if state in failure_states:
        resource_id = getattr(response.data, "id", "<unknown>")
        details = getattr(response.data, "lifecycle_details", None)
        detail_text = f"; details={details}" if details else ""
        raise RuntimeError(
            f"Resource {resource_id} reached terminal state {state} while waiting "
            f"for {expected_state}{detail_text}"
        )
    return False


def _failure_states_for(expected_state: str) -> set[str]:
    if expected_state == "RUNNING":
        return {"TERMINATING", "TERMINATED", "STOPPING", "STOPPED"}
    if expected_state == "AVAILABLE":
        return {"FAULTY", "TERMINATING", "TERMINATED"}
    if expected_state == "ATTACHED":
        return {"DETACHING", "DETACHED"}
    return {"FAILED", "FAULTY", "TERMINATING", "TERMINATED"}


def restore_latest_backup(
    clients: OciClients,
    config: AppConfig,
    plan: VolumeGroupPlan,
    dry_run: bool = False,
) -> Any:
    created = create_restored_volume_group(clients, config, plan, dry_run=dry_run)
    if created is None:
        return None
    return wait_for_restored_volume_group(clients, config, created.id)


def create_restored_volume_group(
    clients: OciClients,
    config: AppConfig,
    plan: VolumeGroupPlan,
    dry_run: bool = False,
) -> Any:
    if dry_run:
        return None

    display_name = restored_volume_group_display_name(
        config.restore.display_name_prefix,
        plan.source_display_name,
        plan.source_volume_group_id,
    )
    details = clients.oci.core.models.CreateVolumeGroupDetails(
        compartment_id=config.target_compartment_id,
        availability_domain=plan.availability_domain,
        display_name=display_name,
        source_details=clients.oci.core.models.VolumeGroupSourceFromVolumeGroupBackupDetails(
            volume_group_backup_id=plan.latest_backup_id
        ),
        freeform_tags=dict(config.restore.freeform_tags),
        defined_tags=dict(config.restore.defined_tags),
    )
    created = clients.block.create_volume_group(
        details,
        opc_retry_token=f"restore-{uuid4()}",
    ).data
    return created


def wait_for_restored_volume_group(
    clients: OciClients,
    config: AppConfig,
    volume_group_id: str,
) -> Any:
    return wait_for_lifecycle(
        clients,
        clients.block,
        clients.block.get_volume_group(volume_group_id),
        "AVAILABLE",
        config.restore.wait_seconds,
        config.restore.wait_interval_seconds,
    ).data
