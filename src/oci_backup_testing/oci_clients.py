from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig


@dataclass(frozen=True)
class OciClients:
    oci: Any
    block: Any
    compute: Any
    object_storage: Any
    virtual_network: Any


def build_clients(config: AppConfig) -> OciClients:
    import oci

    signer = None
    client_config: dict[str, Any]

    if config.auth.mode == "config_file":
        client_config = oci.config.from_file(
            str(Path(config.auth.config_file).expanduser()),
            config.auth.profile,
        )
    elif config.auth.mode == "instance_principal":
        client_config = {}
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    elif config.auth.mode == "resource_principal":
        client_config = {}
        signer = oci.auth.signers.get_resource_principals_signer()
    else:
        raise ValueError(f"Unsupported auth mode: {config.auth.mode}")

    kwargs = {
        "retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY,
    }
    if signer is not None:
        kwargs["signer"] = signer

    return OciClients(
        oci=oci,
        block=oci.core.BlockstorageClient(client_config, **kwargs),
        compute=oci.core.ComputeClient(client_config, **kwargs),
        object_storage=oci.object_storage.ObjectStorageClient(client_config, **kwargs),
        virtual_network=oci.core.VirtualNetworkClient(client_config, **kwargs),
    )
