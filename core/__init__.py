"""Calculadora VLSM Dual-Stack (IPv4 / IPv6) — núcleo de cálculo local."""

from __future__ import annotations

from core.models import (
    CalculationStep,
    HostRequest,
    IPv6Result,
    IPv6Subnet,
    MultiVLSMResult,
    VLSMError,
    VLSMGroup,
    VLSMResult,
)
from core.subnet_v6 import calculate_ipv6
from core.vlsm_v4 import calculate_vlsm_grouped, calculate_vlsm_v4

__version__ = "1.0.0"
__all__ = [
    "CalculationStep",
    "HostRequest",
    "IPv6Result",
    "IPv6Subnet",
    "VLSMError",
    "MultiVLSMResult",
    "VLSMGroup",
    "VLSMResult",
    "calculate_ipv6",
    "calculate_vlsm_grouped",
    "calculate_vlsm_v4",
    "__version__",
]
