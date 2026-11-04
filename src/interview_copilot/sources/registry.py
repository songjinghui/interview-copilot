"""Installed source ports, gated independently by evidence and connection state.

This registry contains installed code, not credentials or durable user settings.
The composition root supplies persisted configuration when assembling descriptors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ..jobs.model import Capability, CapabilityStatus
from .base import SourceError

PORTS = frozenset({"search_jobs", "read_job", "read_feedback"})


@dataclass(frozen=True)
class RegisteredCapability:
    evidence: Capability
    stage: str = "external_sample"
    enabled: bool = True

    def __post_init__(self):
        if self.stage not in {"external_sample", "local_script", "product"}:
            raise ValueError("Unknown evidence stage")
        if not isinstance(self.evidence, Capability) or type(self.enabled) is not bool:
            raise ValueError("Invalid capability declaration")


@dataclass(frozen=True)
class SourceDescriptor:
    key: str
    display_name: str
    adapter_version: str
    capabilities: Mapping[str, RegisteredCapability]
    enabled: bool = False
    connection_state: str = "unconfigured"
    config_schema: Mapping = field(default_factory=dict)
    url_matchers: tuple[str, ...] = ()

    def __post_init__(self):
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.key, self.display_name, self.adapter_version)
        ):
            raise ValueError("Source identity must be explicit")
        if set(self.capabilities) - PORTS:
            raise ValueError("Only read capabilities may be registered")
        if any(
            not isinstance(c, RegisteredCapability) for c in self.capabilities.values()
        ):
            raise ValueError("Capabilities need independent evidence")
        if type(self.enabled) is not bool or self.connection_state not in {
            "unconfigured",
            "ready",
            "auth_required",
            "error",
            "disabled",
        }:
            raise ValueError("Invalid source state")
        object.__setattr__(
            self, "capabilities", MappingProxyType(dict(self.capabilities))
        )
        object.__setattr__(
            self, "config_schema", MappingProxyType(dict(self.config_schema))
        )


class SourceRegistry:
    def __init__(self):
        self._sources: dict[str, tuple[SourceDescriptor, dict]] = {}

    def register(self, descriptor: SourceDescriptor, **ports) -> None:
        if descriptor.key in self._sources:
            raise ValueError("Source key is already installed")
        if set(ports) - PORTS or set(ports) - set(descriptor.capabilities):
            raise ValueError("Undeclared or unsupported port")
        for name, port in ports.items():
            if not callable(getattr(port, name, None)):
                raise ValueError(f"Port does not implement {name}")
        for name, capability in descriptor.capabilities.items():
            if (
                capability.evidence.status is CapabilityStatus.VERIFIED
                and name not in ports
            ):
                raise ValueError("Verified capability needs an installed port")
        self._sources[descriptor.key] = (descriptor, dict(ports))

    def require(self, source_key: str, capability: str):
        if source_key not in self._sources:
            raise SourceError("not_found", "Source is not installed")
        descriptor, ports = self._sources[source_key]
        declaration = descriptor.capabilities.get(capability)
        if (
            declaration is None
            or declaration.evidence.status is CapabilityStatus.UNSUPPORTED
        ):
            raise SourceError("unsupported", "Source does not support this capability")
        if (
            not descriptor.enabled
            or not declaration.enabled
            or descriptor.connection_state == "disabled"
        ):
            raise SourceError("disabled", "This capability is disabled")
        if descriptor.connection_state != "ready":
            raise SourceError(
                descriptor.connection_state, "Source connection is not ready"
            )
        if (
            declaration.evidence.status is not CapabilityStatus.VERIFIED
            or declaration.stage != "product"
            or capability not in ports
        ):
            raise SourceError(
                "capability_not_verified",
                "This capability has not been verified in the product",
            )
        return ports[capability]

    def for_capability(self, capability: str) -> list[SourceDescriptor]:
        result = []
        for key, (descriptor, _) in self._sources.items():
            try:
                self.require(key, capability)
            except SourceError:
                continue
            result.append(descriptor)
        return result
