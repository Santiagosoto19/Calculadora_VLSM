"""Modelos de dominio, excepciones y utilidades de formato.

Toda la lógica de presentación (Excel, CLI, Streamlit) consume estos
dataclasses inmutables para no acoplarse al motor de cálculo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping


class VLSMError(ValueError):
    """Error de validación o de capacidad en el cálculo de subredes."""


class InvalidNetworkError(VLSMError):
    """CIDR mal formado, host bits inválidos o protocolo incorrecto."""


class InsufficientAddressSpaceError(VLSMError):
    """El bloque base no alcanza para cubrir todas las solicitudes."""


class SubnetCollisionError(VLSMError):
    """Dos o más subredes asignadas se solapan o se salen del padre."""


def format_large_int(value: int) -> str:
    """Formatea enteros grandes con separador de miles o notación científica."""
    if value < 0:
        return str(value)
    if value >= 10**15:
        return f"{value:.6e}".replace("+0", "+").replace("+", "")
    return f"{value:,}".replace(",", ".")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@dataclass(frozen=True, slots=True)
class HostRequest:
    """Solicitud nominada de hosts (IPv4) o dispositivos (IPv6)."""

    name: str
    hosts: int
    original_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip())
        if not self.name:
            raise InvalidNetworkError("El nombre de la subred no puede estar vacío.")
        if self.hosts < 1:
            raise InvalidNetworkError(
                f"La subred '{self.name}' requiere al menos 1 host/dispositivo."
            )


@dataclass(frozen=True, slots=True)
class CalculationStep:
    """Paso trazable de la memoria de cálculo."""

    index: int
    title: str
    formula: str
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paso": self.index,
            "titulo": self.title,
            "formula": self.formula,
            "entradas": dict(self.inputs),
            "salidas": dict(self.outputs),
            "notas": self.notes,
        }

    def to_row(self) -> dict[str, Any]:
        def _fmt(mapping: Mapping[str, Any]) -> str:
            parts = [f"{k}={v}" for k, v in mapping.items()]
            return "; ".join(parts)

        return {
            "Paso": self.index,
            "Título": self.title,
            "Fórmula / regla": self.formula,
            "Entradas": _fmt(self.inputs),
            "Salidas": _fmt(self.outputs),
            "Notas": self.notes,
        }


@dataclass(frozen=True, slots=True)
class IPv4Subnet:
    name: str
    requested_hosts: int
    assigned_usable: int
    network: str
    netmask: str
    netmask_binary: str
    cidr: str
    prefixlen: int
    first_usable: str
    last_usable: str
    broadcast: str
    wildcard: str
    block_size: int
    host_bits: int
    bits_borrowed: int
    jump_decimal: int
    jump_hex: str
    waste_hosts: int
    efficiency_pct: float
    waste_pct: float
    allocation_order: int

    def to_row(self) -> dict[str, Any]:
        return {
            "Orden": self.allocation_order,
            "Nombre": self.name,
            "Hosts solicitados": self.requested_hosts,
            "Hosts asignados (útiles)": self.assigned_usable,
            "Red": self.network,
            "Máscara decimal": self.netmask,
            "Máscara binaria": self.netmask_binary,
            "CIDR": self.cidr,
            "Prefijo": self.prefixlen,
            "Primera IP útil": self.first_usable,
            "Última IP útil": self.last_usable,
            "Broadcast": self.broadcast,
            "Wildcard": self.wildcard,
            "Tamaño de bloque": self.block_size,
            "Bits de host": self.host_bits,
            "Bits prestados": self.bits_borrowed,
            "Salto decimal": self.jump_decimal,
            "Salto hexadecimal": self.jump_hex,
            "Desperdicio (hosts)": self.waste_hosts,
            "Eficiencia %": round(self.efficiency_pct, 2),
            "Desperdicio %": round(self.waste_pct, 2),
        }


@dataclass(frozen=True, slots=True)
class IPv6Subnet:
    name: str
    prefix_cidr: str
    compressed: str
    expanded: str
    prefixlen: int
    first_assignable: str
    last_assignable: str
    router_anycast: str
    first_assignable_expanded: str
    last_assignable_expanded: str
    router_anycast_expanded: str
    total_addresses: int
    requested_devices: int
    interface_bits: int
    bits_borrowed: int
    jump_decimal: int
    jump_hex: str
    waste_addresses: int
    efficiency_pct: float
    waste_pct: float
    extra_prefix_bits: int
    allocation_order: int

    def to_row(self) -> dict[str, Any]:
        return {
            "Orden": self.allocation_order,
            "Nombre": self.name,
            "Dispositivos solicitados": self.requested_devices,
            "Prefijo CIDR": self.prefix_cidr,
            "Comprimido": self.compressed,
            "Expandido": self.expanded,
            "Prefijo": self.prefixlen,
            "Primera asignable": self.first_assignable,
            "Última asignable": self.last_assignable,
            "Anycast de router/subred": self.router_anycast,
            "Primera (expandida)": self.first_assignable_expanded,
            "Última (expandida)": self.last_assignable_expanded,
            "Anycast (expandida)": self.router_anycast_expanded,
            "Direcciones totales": format_large_int(self.total_addresses),
            "Bits de interfaz": self.interface_bits,
            "Bits prestados": self.bits_borrowed,
            "Salto decimal": format_large_int(self.jump_decimal),
            "Salto hexadecimal": self.jump_hex,
            "Desperdicio (dir.)": format_large_int(self.waste_addresses),
            "Eficiencia %": round(self.efficiency_pct, 4),
            "Desperdicio %": round(self.waste_pct, 4),
            "Bits extra de prefijo": self.extra_prefix_bits,
        }


@dataclass(slots=True)
class VLSMResult:
    protocol: Literal["IPv4"] = "IPv4"
    base_cidr: str = ""
    base_network: str = ""
    base_prefix: int = 0
    total_addresses: int = 0
    used_addresses: int = 0
    leftover_addresses: int = 0
    leftover_cidrs: list[str] = field(default_factory=list)
    requested_hosts_total: int = 0
    assigned_usable_total: int = 0
    subnet_count: int = 0
    host_efficiency_pct: float = 0.0
    space_efficiency_pct: float = 0.0
    waste_pct: float = 0.0
    subnets: list[IPv4Subnet] = field(default_factory=list)
    steps: list[CalculationStep] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)
    notes: list[str] = field(default_factory=list)

    def summary_metrics(self) -> list[tuple[str, str, str]]:
        leftover = ", ".join(self.leftover_cidrs) if self.leftover_cidrs else "Ninguno"
        return [
            ("IP / bloque base", self.base_cidr, "CIDR de entrada"),
            ("Subredes asignadas", str(self.subnet_count), "Bloques VLSM"),
            ("Hosts solicitados", f"{self.requested_hosts_total:,}".replace(",", "."), "Suma de requerimientos"),
            ("Hosts útiles asignados", f"{self.assigned_usable_total:,}".replace(",", "."), "Sin red ni broadcast"),
            ("Eficiencia de hosts", f"{self.host_efficiency_pct:.2f} %", "Solicitados / útiles"),
            ("Uso del bloque", f"{self.space_efficiency_pct:.2f} %", "Direcciones ocupadas"),
            ("Espacio sobrante", f"{self.leftover_addresses:,}".replace(",", "."), leftover),
            ("Desperdicio global", f"{self.waste_pct:.2f} %", "Útiles no demandados"),
        ]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["leftover_cidrs"] = list(self.leftover_cidrs)
        payload["subnets"] = [s.to_row() for s in self.subnets]
        payload["steps"] = [s.to_dict() for s in self.steps]
        return payload


@dataclass(slots=True)
class IPv6Result:
    protocol: Literal["IPv6"] = "IPv6"
    mode: Literal["fixed", "hosts"] = "fixed"
    base_cidr: str = ""
    base_compressed: str = ""
    base_expanded: str = ""
    base_prefix: int = 0
    target_prefix: int | None = None
    total_addresses: int = 0
    used_addresses: int = 0
    leftover_addresses: int = 0
    leftover_cidrs: list[str] = field(default_factory=list)
    requested_devices_total: int = 0
    subnet_count: int = 0
    child_capacity: int = 0
    truncated: bool = False
    host_efficiency_pct: float = 0.0
    space_efficiency_pct: float = 0.0
    waste_pct: float = 0.0
    subnets: list[IPv6Subnet] = field(default_factory=list)
    steps: list[CalculationStep] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)
    notes: list[str] = field(default_factory=list)

    def summary_metrics(self) -> list[tuple[str, str, str]]:
        leftover = ", ".join(self.leftover_cidrs[:8])
        if len(self.leftover_cidrs) > 8:
            leftover += f" … (+{len(self.leftover_cidrs) - 8})"
        if not leftover:
            leftover = "Ninguno"
        mode_label = (
            f"Prefijo fijo /{self.target_prefix}"
            if self.mode == "fixed"
            else "Por requerimiento de dispositivos"
        )
        return [
            ("Prefijo base", self.base_cidr, self.base_expanded),
            ("Modo de subdivisión", mode_label, self.mode),
            ("Subredes generadas", str(self.subnet_count), f"Capacidad hija: {format_large_int(self.child_capacity)}"),
            ("Dispositivos solicitados", format_large_int(self.requested_devices_total), "Suma de requerimientos"),
            ("Direcciones usadas", format_large_int(self.used_addresses), "Suma de bloques hijos"),
            ("Uso del bloque", f"{self.space_efficiency_pct:.4f} %", "Ocupación del prefijo padre"),
            ("Espacio sobrante", format_large_int(self.leftover_addresses), leftover),
            ("Eficiencia vs dispositivos", f"{self.host_efficiency_pct:.4f} %", "En IPv6 suele ser baja a propósito"),
        ]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["total_addresses"] = str(self.total_addresses)
        payload["used_addresses"] = str(self.used_addresses)
        payload["leftover_addresses"] = str(self.leftover_addresses)
        payload["child_capacity"] = str(self.child_capacity)
        payload["subnets"] = [s.to_row() for s in self.subnets]
        payload["steps"] = [s.to_dict() for s in self.steps]
        return payload


@dataclass(slots=True)
class VLSMGroup:
    """Un edificio / sede con su contenedor y el VLSM interno."""

    name: str
    container: IPv4Subnet
    result: VLSMResult


@dataclass(slots=True)
class MultiVLSMResult:
    """Varios VLSM apilados sobre un mismo bloque padre (una hoja Excel)."""

    protocol: Literal["IPv4"] = "IPv4"
    base_cidr: str = ""
    base_network: str = ""
    base_prefix: int = 0
    total_addresses: int = 0
    used_addresses: int = 0
    leftover_addresses: int = 0
    leftover_cidrs: list[str] = field(default_factory=list)
    requested_hosts_total: int = 0
    assigned_usable_total: int = 0
    subnet_count: int = 0
    host_efficiency_pct: float = 0.0
    space_efficiency_pct: float = 0.0
    waste_pct: float = 0.0
    groups: list[VLSMGroup] = field(default_factory=list)
    containers: list[IPv4Subnet] = field(default_factory=list)
    steps: list[CalculationStep] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)
    notes: list[str] = field(default_factory=list)
    group_prefix: int | None = None

    @property
    def subnets(self) -> list[IPv4Subnet]:
        rows: list[IPv4Subnet] = []
        for group in self.groups:
            rows.extend(group.result.subnets)
        return rows

    def summary_metrics(self) -> list[tuple[str, str, str]]:
        leftover = ", ".join(self.leftover_cidrs) if self.leftover_cidrs else "Ninguno"
        return [
            ("IP / bloque base", self.base_cidr, "CIDR de entrada"),
            ("Grupos / edificios", str(len(self.groups)), "Contenedores en la hoja"),
            ("Subredes internas", str(self.subnet_count), "Suma de VLSM por grupo"),
            ("Hosts solicitados", f"{self.requested_hosts_total:,}".replace(",", "."), "Todos los grupos"),
            ("Hosts útiles asignados", f"{self.assigned_usable_total:,}".replace(",", "."), "Sin red ni broadcast"),
            ("Uso del bloque", f"{self.space_efficiency_pct:.2f} %", "Contenedores sobre el padre"),
            ("Espacio sobrante", f"{self.leftover_addresses:,}".replace(",", "."), leftover),
            ("Eficiencia de hosts", f"{self.host_efficiency_pct:.2f} %", "Solicitados / útiles"),
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "base_cidr": self.base_cidr,
            "groups": [
                {
                    "name": group.name,
                    "container": group.container.to_row(),
                    "subnets": [item.to_row() for item in group.result.subnets],
                }
                for group in self.groups
            ],
            "leftover_cidrs": list(self.leftover_cidrs),
            "steps": [step.to_dict() for step in self.steps],
            "generated_at": self.generated_at,
            "notes": list(self.notes),
        }


ExportResult = VLSMResult | IPv6Result | MultiVLSMResult
