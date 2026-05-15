from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import AppConfig
from .oci_clients import OciClients
from .restore import short_ocid, timestamp_suffix, wait_for_lifecycle


class ComputePhaseError(RuntimeError):
    """Raised when a restored volume group cannot be converted into a test VM."""


@dataclass(frozen=True)
class RestoredVolumes:
    boot_volume: Any
    block_volumes: list[Any]


def classify_restored_volumes(clients: OciClients, restored_volume_group: Any) -> RestoredVolumes:
    volume_ids = list(getattr(restored_volume_group, "volume_ids", None) or [])
    if not volume_ids:
        raise ComputePhaseError(
            f"Restored volume group {restored_volume_group.id} has no volume_ids"
        )

    boot_volume_ids = [volume_id for volume_id in volume_ids if _is_boot_volume_ocid(volume_id)]
    block_volume_ids = [volume_id for volume_id in volume_ids if _is_block_volume_ocid(volume_id)]
    unknown_ids = [
        volume_id
        for volume_id in volume_ids
        if volume_id not in set(boot_volume_ids + block_volume_ids)
    ]

    for volume_id in unknown_ids:
        if _looks_like_boot_volume(clients, volume_id):
            boot_volume_ids.append(volume_id)
        elif _looks_like_block_volume(clients, volume_id):
            block_volume_ids.append(volume_id)
        else:
            raise ComputePhaseError(
                f"Cannot classify volume {volume_id} from restored volume group "
                f"{restored_volume_group.id}"
            )

    if len(boot_volume_ids) != 1:
        raise ComputePhaseError(
            f"Restored volume group {restored_volume_group.id} contains "
            f"{len(boot_volume_ids)} boot volumes. This workflow needs exactly one boot volume "
            "per source VM. Split the source grouping or add explicit mapping logic."
        )

    boot_volume = clients.block.get_boot_volume(boot_volume_ids[0]).data
    block_volumes = [clients.block.get_volume(volume_id).data for volume_id in block_volume_ids]
    return RestoredVolumes(boot_volume=boot_volume, block_volumes=block_volumes)


def launch_test_instance(
    clients: OciClients,
    config: AppConfig,
    restored_volume_group: Any,
    restored_volumes: RestoredVolumes,
    subnet: Any,
    ordinal: int,
    dry_run: bool = False,
) -> Any:
    if dry_run:
        return None

    created = create_test_instance(
        clients,
        config,
        restored_volume_group,
        restored_volumes,
        subnet,
        ordinal,
        dry_run=dry_run,
    )
    if created is None:
        return None
    return wait_for_test_instance(clients, config, created.id)


def create_test_instance(
    clients: OciClients,
    config: AppConfig,
    restored_volume_group: Any,
    restored_volumes: RestoredVolumes,
    subnet: Any,
    ordinal: int,
    dry_run: bool = False,
) -> Any:
    if dry_run:
        return None

    metadata = dict(config.compute.metadata)
    if config.compute.ssh_public_key_path:
        metadata["ssh_authorized_keys"] = Path(
            config.compute.ssh_public_key_path
        ).expanduser().read_text(encoding="utf-8").strip()

    hostname_label = _hostname_label(
        config.compute.hostname_prefix,
        short_ocid(restored_volume_group.id),
    )
    create_vnic_details = clients.oci.core.models.CreateVnicDetails(
        subnet_id=subnet.id,
        assign_public_ip=config.network.assign_public_ip,
        nsg_ids=config.network.nsg_ids or None,
        hostname_label=hostname_label,
    )
    launch_details = clients.oci.core.models.LaunchInstanceDetails(
        availability_domain=restored_volumes.boot_volume.availability_domain,
        compartment_id=config.target_compartment_id,
        display_name=(
            f"{config.compute.display_name_prefix}-"
            f"{short_ocid(restored_volume_group.id)}-"
            f"{timestamp_suffix()}"
        ),
        shape=config.compute.shape,
        shape_config=clients.oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=config.compute.ocpus,
            memory_in_gbs=config.compute.memory_in_gbs,
        ),
        source_details=clients.oci.core.models.InstanceSourceViaBootVolumeDetails(
            boot_volume_id=restored_volumes.boot_volume.id
        ),
        create_vnic_details=create_vnic_details,
        metadata=metadata or None,
        freeform_tags={
            "CreatedBy": "oci-backup-testing",
            "RestoredVolumeGroupId": restored_volume_group.id,
        },
    )
    created = clients.compute.launch_instance(
        launch_details,
        opc_retry_token=f"launch-{uuid4()}",
    ).data
    return created


def wait_for_test_instance(clients: OciClients, config: AppConfig, instance_id: str) -> Any:
    return wait_for_lifecycle(
        clients,
        clients.compute,
        clients.compute.get_instance(instance_id),
        "RUNNING",
        config.restore.wait_seconds,
        config.restore.wait_interval_seconds,
    ).data


def attach_block_volumes(
    clients: OciClients,
    config: AppConfig,
    instance: Any,
    block_volumes: list[Any],
    dry_run: bool = False,
) -> list[Any]:
    attachments = []
    for volume in block_volumes:
        if dry_run:
            continue
        details = _attachment_details(clients, config, instance.id, volume.id)
        created = clients.compute.attach_volume(
            details,
            opc_retry_token=f"attach-{uuid4()}",
        ).data
        attachment = wait_for_lifecycle(
            clients,
            clients.compute,
            clients.compute.get_volume_attachment(created.id),
            "ATTACHED",
            config.restore.wait_seconds,
            config.restore.wait_interval_seconds,
        ).data
        attachments.append(attachment)
    return attachments


def _attachment_details(
    clients: OciClients,
    config: AppConfig,
    instance_id: str,
    volume_id: str,
) -> Any:
    common = {
        "instance_id": instance_id,
        "volume_id": volume_id,
        "display_name": f"oci-test-attach-{short_ocid(volume_id)}",
    }
    if config.compute.attachment_type == "iscsi":
        return clients.oci.core.models.AttachIScsiVolumeDetails(**common)

    if config.compute.pv_encryption_in_transit is not None:
        common["is_pv_encryption_in_transit_enabled"] = (
            config.compute.pv_encryption_in_transit
        )
    return clients.oci.core.models.AttachParavirtualizedVolumeDetails(**common)


def _hostname_label(prefix: str, suffix: int | str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9-]", "-", prefix).strip("-").lower()
    if not cleaned:
        cleaned = "ocitest"
    cleaned_suffix = re.sub(r"[^a-zA-Z0-9-]", "-", str(suffix)).strip("-").lower()
    if not cleaned_suffix:
        cleaned_suffix = "1"
    max_prefix = max(1, 15 - len(cleaned_suffix) - 1)
    label = f"{cleaned[:max_prefix].strip('-')}-{cleaned_suffix}"
    return label[:15].strip("-") or f"oci-{cleaned_suffix}"


def _is_boot_volume_ocid(value: str) -> bool:
    return value.startswith("ocid1.bootvolume.")


def _is_block_volume_ocid(value: str) -> bool:
    return value.startswith("ocid1.volume.")


def _looks_like_boot_volume(clients: OciClients, volume_id: str) -> bool:
    try:
        clients.block.get_boot_volume(volume_id)
        return True
    except Exception:
        return False


def _looks_like_block_volume(clients: OciClients, volume_id: str) -> bool:
    try:
        clients.block.get_volume(volume_id)
        return True
    except Exception:
        return False
