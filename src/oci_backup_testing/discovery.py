from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .oci_clients import OciClients
from .tags import matches_tag


class DiscoveryError(RuntimeError):
    """Raised when OCI resources cannot be selected without guessing."""


@dataclass(frozen=True)
class VolumeGroupPlan:
    source_compartment_id: str
    source_volume_group_id: str
    source_display_name: str
    availability_domain: str
    latest_backup_id: str
    latest_backup_display_name: str
    latest_backup_time_created: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_compartment_id": self.source_compartment_id,
            "source_volume_group_id": self.source_volume_group_id,
            "source_display_name": self.source_display_name,
            "availability_domain": self.availability_domain,
            "latest_backup_id": self.latest_backup_id,
            "latest_backup_display_name": self.latest_backup_display_name,
            "latest_backup_time_created": self.latest_backup_time_created,
        }


def _all_results(clients: OciClients, func: Any, *args: Any, **kwargs: Any) -> list[Any]:
    return clients.oci.pagination.list_call_get_all_results(func, *args, **kwargs).data


def _time_string(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _resource_label(resource: Any) -> str:
    display_name = getattr(resource, "display_name", None) or "<no display name>"
    return f"{display_name} ({getattr(resource, 'id', '<no id>')})"


def discover_volume_group_plans(clients: OciClients, config: AppConfig) -> list[VolumeGroupPlan]:
    volume_groups = _all_results(
        clients,
        clients.block.list_volume_groups,
        config.source_compartment_id,
        lifecycle_state="AVAILABLE",
    )
    tagged_groups = [group for group in volume_groups if matches_tag(group, config.tag)]

    if not tagged_groups:
        raise DiscoveryError(
            f"No AVAILABLE volume groups found with {config.tag.describe()} "
            f"in source compartment {config.source_compartment_id}"
        )

    plans: list[VolumeGroupPlan] = []
    groups_without_backups: list[str] = []

    for group in sorted(tagged_groups, key=lambda item: getattr(item, "display_name", "") or ""):
        backups = _all_results(
            clients,
            clients.block.list_volume_group_backups,
            config.source_compartment_id,
            volume_group_id=group.id,
            sort_by="TIMECREATED",
            sort_order="DESC",
        )
        available_backups = [
            backup
            for backup in backups
            if str(getattr(backup, "lifecycle_state", "")).upper() == "AVAILABLE"
        ]
        if not available_backups:
            groups_without_backups.append(_resource_label(group))
            continue

        latest = max(
            available_backups,
            key=lambda backup: getattr(backup, "time_created", None),
        )
        plans.append(
            VolumeGroupPlan(
                source_compartment_id=config.source_compartment_id,
                source_volume_group_id=group.id,
                source_display_name=getattr(group, "display_name", "") or group.id,
                availability_domain=group.availability_domain,
                latest_backup_id=latest.id,
                latest_backup_display_name=getattr(latest, "display_name", "") or latest.id,
                latest_backup_time_created=_time_string(getattr(latest, "time_created", None)),
            )
        )

    if groups_without_backups:
        joined = "\n".join(f"  - {item}" for item in groups_without_backups)
        raise DiscoveryError(
            "The following tagged volume groups do not have an AVAILABLE volume group backup:\n"
            f"{joined}"
        )

    return plans


def filter_volume_group_plans(
    plans: list[VolumeGroupPlan],
    volume_group_id: str | None,
) -> list[VolumeGroupPlan]:
    if volume_group_id is None:
        return plans

    selector = volume_group_id.strip()
    if not selector:
        raise DiscoveryError("--volume-group-id must not be empty")

    if not selector.startswith("ocid1.volumegroup."):
        raise DiscoveryError(
            f"--volume-group-id must be a source volume group OCID, got {selector!r}"
        )

    matches = [plan for plan in plans if plan.source_volume_group_id == selector]
    if matches:
        return matches

    available = "\n".join(
        f"  - {plan.source_display_name} ({plan.source_volume_group_id})"
        for plan in plans
    )
    raise DiscoveryError(
        f"No tagged volume group matched --volume-group-id {selector!r}.\n"
        f"Available tagged volume groups:\n{available}"
    )


def find_tagged_vcn(clients: OciClients, config: AppConfig) -> Any:
    if config.network.vcn_id:
        return clients.virtual_network.get_vcn(config.network.vcn_id).data

    compartment_id = config.network.vcn_compartment_id or config.target_compartment_id
    vcns = _all_results(
        clients,
        clients.virtual_network.list_vcns,
        compartment_id,
        lifecycle_state="AVAILABLE",
    )
    tagged_vcns = [vcn for vcn in vcns if matches_tag(vcn, config.tag)]

    if len(tagged_vcns) == 1:
        return tagged_vcns[0]
    if not tagged_vcns:
        raise DiscoveryError(
            f"No AVAILABLE VCN found with {config.tag.describe()} in compartment {compartment_id}. "
            "Set network.vcn_id if the VCN should be selected explicitly."
        )

    labels = "\n".join(f"  - {_resource_label(vcn)}" for vcn in tagged_vcns)
    raise DiscoveryError(
        "Multiple tagged VCNs found, so the subnet cannot be selected safely. "
        f"Set network.vcn_id explicitly.\n{labels}"
    )


def find_subnet_for_ad(clients: OciClients, config: AppConfig, availability_domain: str) -> Any:
    mapped_subnet_id = config.network.subnet_id_by_availability_domain.get(availability_domain)
    if mapped_subnet_id:
        subnet = clients.virtual_network.get_subnet(mapped_subnet_id).data
        _validate_subnet_ad(subnet, availability_domain)
        return subnet

    if config.network.subnet_id:
        subnet = clients.virtual_network.get_subnet(config.network.subnet_id).data
        _validate_subnet_ad(subnet, availability_domain)
        return subnet

    vcn = find_tagged_vcn(clients, config)
    compartment_id = config.network.subnet_compartment_id or config.target_compartment_id
    subnets = _all_results(
        clients,
        clients.virtual_network.list_subnets,
        compartment_id,
        vcn_id=vcn.id,
        lifecycle_state="AVAILABLE",
    )
    candidates = [
        subnet
        for subnet in subnets
        if getattr(subnet, "availability_domain", None) in {None, availability_domain}
    ]

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DiscoveryError(
            f"No AVAILABLE subnet in VCN {vcn.id} can be used for {availability_domain}. "
            "Set network.subnet_id or network.subnet_id_by_availability_domain."
        )

    labels = "\n".join(f"  - {_resource_label(subnet)}" for subnet in candidates)
    raise DiscoveryError(
        f"Multiple subnets in VCN {vcn.id} can be used for {availability_domain}. "
        "Set network.subnet_id or network.subnet_id_by_availability_domain.\n"
        f"{labels}"
    )


def _validate_subnet_ad(subnet: Any, availability_domain: str) -> None:
    subnet_ad = getattr(subnet, "availability_domain", None)
    if subnet_ad is not None and subnet_ad != availability_domain:
        raise DiscoveryError(
            f"Subnet {subnet.id} is in {subnet_ad}, but the restored boot volume is in "
            f"{availability_domain}. Use a regional subnet or provide an AD-specific subnet map."
        )
