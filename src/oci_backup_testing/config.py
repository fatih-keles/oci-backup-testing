from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the run configuration is incomplete or unsafe."""


def _as_dict(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be an object")
    return value


def _as_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list")
    return value


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string or null")
    return value.strip()


def _required_str(value: Any, name: str) -> str:
    result = _optional_str(value, name)
    if result is None:
        raise ConfigError(f"{name} is required")
    return result


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    result = _int(value, name)
    if result < 1:
        raise ConfigError(f"{name} must be a positive integer or null")
    return result


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "config_file"
    config_file: str = "~/.oci/config"
    profile: str = "DEFAULT"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthConfig":
        mode = data.get("mode", "config_file")
        if mode not in {"config_file", "instance_principal", "resource_principal"}:
            raise ConfigError(
                "auth.mode must be one of config_file, instance_principal, resource_principal"
            )
        return cls(
            mode=mode,
            config_file=str(data.get("config_file", "~/.oci/config")),
            profile=str(data.get("profile", "DEFAULT")),
        )


@dataclass(frozen=True)
class TagSelector:
    kind: str
    key: str
    value: str | None = None
    namespace: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TagSelector":
        kind = data.get("kind", "freeform")
        if kind not in {"freeform", "defined"}:
            raise ConfigError("tag.kind must be freeform or defined")

        key = _required_str(data.get("key", "OCI-Backup-Testing"), "tag.key")
        value = _optional_str(data.get("value"), "tag.value")
        namespace = _optional_str(data.get("namespace"), "tag.namespace")

        if kind == "defined" and namespace is None:
            raise ConfigError("tag.namespace is required when tag.kind is defined")
        if kind == "freeform" and namespace is not None:
            raise ConfigError("tag.namespace is only valid when tag.kind is defined")

        return cls(kind=kind, key=key, value=value, namespace=namespace)

    def describe(self) -> str:
        if self.kind == "defined":
            base = f"defined tag {self.namespace}.{self.key}"
        else:
            base = f"freeform tag {self.key}"
        if self.value is None:
            return f"{base} exists"
        return f"{base} == {self.value}"


@dataclass(frozen=True)
class NetworkConfig:
    vcn_compartment_id: str | None = None
    subnet_compartment_id: str | None = None
    vcn_id: str | None = None
    subnet_id: str | None = None
    subnet_id_by_availability_domain: dict[str, str] = field(default_factory=dict)
    assign_public_ip: bool = False
    nsg_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NetworkConfig":
        subnet_map = _as_dict(
            data.get("subnet_id_by_availability_domain", {}),
            "network.subnet_id_by_availability_domain",
        )
        for ad, subnet_id in subnet_map.items():
            _required_str(ad, "network.subnet_id_by_availability_domain key")
            _required_str(subnet_id, f"network.subnet_id_by_availability_domain[{ad}]")

        nsg_ids = [
            _required_str(value, "network.nsg_ids[]")
            for value in _as_list(data.get("nsg_ids", []), "network.nsg_ids")
        ]

        return cls(
            vcn_compartment_id=_optional_str(
                data.get("vcn_compartment_id"), "network.vcn_compartment_id"
            ),
            subnet_compartment_id=_optional_str(
                data.get("subnet_compartment_id"), "network.subnet_compartment_id"
            ),
            vcn_id=_optional_str(data.get("vcn_id"), "network.vcn_id"),
            subnet_id=_optional_str(data.get("subnet_id"), "network.subnet_id"),
            subnet_id_by_availability_domain=dict(subnet_map),
            assign_public_ip=bool(data.get("assign_public_ip", False)),
            nsg_ids=nsg_ids,
        )


@dataclass(frozen=True)
class RestoreConfig:
    display_name_prefix: str = "oci-restore-test"
    wait_seconds: int = 7200
    wait_interval_seconds: int = 30
    freeform_tags: dict[str, str] = field(default_factory=dict)
    defined_tags: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RestoreConfig":
        freeform_tags = _as_dict(data.get("freeform_tags", {}), "restore.freeform_tags")
        defined_tags = _as_dict(data.get("defined_tags", {}), "restore.defined_tags")
        return cls(
            display_name_prefix=str(data.get("display_name_prefix", "oci-restore-test")),
            wait_seconds=_int(data.get("wait_seconds", 7200), "restore.wait_seconds"),
            wait_interval_seconds=_int(
                data.get("wait_interval_seconds", 30),
                "restore.wait_interval_seconds",
            ),
            freeform_tags={str(k): str(v) for k, v in freeform_tags.items()},
            defined_tags=dict(defined_tags),
        )


@dataclass(frozen=True)
class ComputeConfig:
    shape: str = "VM.Standard.E4.Flex"
    ocpus: float = 2.0
    memory_in_gbs: float = 8.0
    display_name_prefix: str = "oci-restore-test"
    hostname_prefix: str = "ocitest"
    metadata: dict[str, str] = field(default_factory=dict)
    ssh_public_key_path: str | None = None
    attachment_type: str = "paravirtualized"
    pv_encryption_in_transit: bool | None = None
    preserve_boot_volume_on_terminate: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComputeConfig":
        attachment_type = str(data.get("attachment_type", "paravirtualized"))
        if attachment_type not in {"paravirtualized", "iscsi"}:
            raise ConfigError("compute.attachment_type must be paravirtualized or iscsi")

        metadata = _as_dict(data.get("metadata", {}), "compute.metadata")
        pv_value = data.get("pv_encryption_in_transit")
        if pv_value is not None and not isinstance(pv_value, bool):
            raise ConfigError("compute.pv_encryption_in_transit must be true, false, or null")

        return cls(
            shape=str(data.get("shape", "VM.Standard.E4.Flex")),
            ocpus=_float(data.get("ocpus", 2.0), "compute.ocpus"),
            memory_in_gbs=_float(data.get("memory_in_gbs", 8.0), "compute.memory_in_gbs"),
            display_name_prefix=str(data.get("display_name_prefix", "oci-restore-test")),
            hostname_prefix=str(data.get("hostname_prefix", "ocitest")),
            metadata={str(k): str(v) for k, v in metadata.items()},
            ssh_public_key_path=_optional_str(
                data.get("ssh_public_key_path"), "compute.ssh_public_key_path"
            ),
            attachment_type=attachment_type,
            pv_encryption_in_transit=pv_value,
            preserve_boot_volume_on_terminate=bool(
                data.get("preserve_boot_volume_on_terminate", True)
            ),
        )


@dataclass(frozen=True)
class StateRetentionConfig:
    max_executions: int | None = 500
    max_age_days: int | None = 30
    prune_only_cleaned: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateRetentionConfig":
        return cls(
            max_executions=_optional_positive_int(
                data.get("max_executions", 500),
                "state_retention.max_executions",
            ),
            max_age_days=_optional_positive_int(
                data.get("max_age_days", 30),
                "state_retention.max_age_days",
            ),
            prune_only_cleaned=bool(data.get("prune_only_cleaned", True)),
        )


@dataclass(frozen=True)
class ReportConfig:
    enabled: bool = False
    bucket_name: str | None = None
    namespace: str | None = None
    object_name_prefix: str = "oci-backup-testing/reports"
    title: str = "Backup Restore Validation Report"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportConfig":
        enabled = bool(data.get("enabled", False))
        bucket_name = _optional_str(data.get("bucket_name"), "report.bucket_name")
        namespace = _optional_str(data.get("namespace"), "report.namespace")
        object_name_prefix = str(
            data.get("object_name_prefix", "oci-backup-testing/reports")
        ).strip("/")
        title = str(data.get("title", "Backup Restore Validation Report")).strip()

        if enabled and bucket_name is None:
            raise ConfigError("report.bucket_name is required when report.enabled is true")
        if enabled and bucket_name and "replace-me" in bucket_name:
            raise ConfigError("report.bucket_name still contains the example placeholder")
        if not title:
            raise ConfigError("report.title must not be empty")

        return cls(
            enabled=enabled,
            bucket_name=bucket_name,
            namespace=namespace,
            object_name_prefix=object_name_prefix,
            title=title,
        )


@dataclass(frozen=True)
class CleanupConfig:
    terminate_instances: bool = True
    delete_restored_volume_group: bool = True
    delete_restored_volumes: bool = True
    wait_seconds: int = 3600
    wait_interval_seconds: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CleanupConfig":
        return cls(
            terminate_instances=bool(data.get("terminate_instances", True)),
            delete_restored_volume_group=bool(data.get("delete_restored_volume_group", True)),
            delete_restored_volumes=bool(data.get("delete_restored_volumes", True)),
            wait_seconds=_int(data.get("wait_seconds", 3600), "cleanup.wait_seconds"),
            wait_interval_seconds=_int(
                data.get("wait_interval_seconds", 20),
                "cleanup.wait_interval_seconds",
            ),
        )


@dataclass(frozen=True)
class AppConfig:
    source_compartment_id: str
    target_compartment_id: str
    state_file: str
    queue_file: str
    state_retention: StateRetentionConfig
    auth: AuthConfig
    tag: TagSelector
    network: NetworkConfig
    restore: RestoreConfig
    compute: ComputeConfig
    report: ReportConfig
    cleanup: CleanupConfig

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        legacy_compartment_id = _optional_str(data.get("compartment_id"), "compartment_id")
        source_compartment_id = (
            _optional_str(data.get("source_compartment_id"), "source_compartment_id")
            or legacy_compartment_id
        )
        target_compartment_id = (
            _optional_str(data.get("target_compartment_id"), "target_compartment_id")
            or legacy_compartment_id
        )

        if source_compartment_id is None:
            raise ConfigError(
                "source_compartment_id is required. For old single-compartment configs, "
                "compartment_id is still accepted."
            )
        if target_compartment_id is None:
            raise ConfigError(
                "target_compartment_id is required. For old single-compartment configs, "
                "compartment_id is still accepted."
            )
        if "replace-me" in source_compartment_id:
            raise ConfigError("source_compartment_id still contains the example placeholder")
        if "replace-me" in target_compartment_id:
            raise ConfigError("target_compartment_id still contains the example placeholder")

        return cls(
            source_compartment_id=source_compartment_id,
            target_compartment_id=target_compartment_id,
            state_file=str(data.get("state_file", ".oci-restore-state.json")),
            queue_file=str(data.get("queue_file", ".oci-report-queue.json")),
            state_retention=StateRetentionConfig.from_dict(
                _as_dict(data.get("state_retention", {}), "state_retention")
            ),
            auth=AuthConfig.from_dict(_as_dict(data.get("auth", {}), "auth")),
            tag=TagSelector.from_dict(_as_dict(data.get("tag", {}), "tag")),
            network=NetworkConfig.from_dict(_as_dict(data.get("network", {}), "network")),
            restore=RestoreConfig.from_dict(_as_dict(data.get("restore", {}), "restore")),
            compute=ComputeConfig.from_dict(_as_dict(data.get("compute", {}), "compute")),
            report=ReportConfig.from_dict(_as_dict(data.get("report", {}), "report")),
            cleanup=CleanupConfig.from_dict(_as_dict(data.get("cleanup", {}), "cleanup")),
        )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ConfigError("config file must contain a JSON object")
    return AppConfig.from_dict(data)
