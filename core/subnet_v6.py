"""Subdivisión y delegación de prefijos IPv6.

Modos:
- *fixed*: Prefix Delegation de tamaño uniforme (p. ej. /48 → /64).
- *hosts*: VLSM-like por requerimiento de dispositivos; se calculan los
  bits de interfaz como ceil(log2(N)) y se asigna el prefijo más pequeño
  que los cubre (opcionalmente alineado a nibble).

RFC relevantes:
- RFC 4291: Subnet-Router Anycast = identificador de interfaz todo-cero.
- RFC 6164: /127 en enlaces punto a punto.
- RFC 4193: Unique Local Address (fd00::/8).
"""

from __future__ import annotations

import ipaddress
import math
from ipaddress import IPv6Address, IPv6Network
from typing import Literal

from core.models import (
    CalculationStep,
    HostRequest,
    InsufficientAddressSpaceError,
    InvalidNetworkError,
    IPv6Result,
    IPv6Subnet,
    SubnetCollisionError,
)

MAX_LISTED_SUBNETS = 4096


def parse_ipv6_network(cidr: str, *, strict: bool = True) -> IPv6Network:
    raw = (cidr or "").strip()
    if not raw:
        raise InvalidNetworkError(
            "Debe indicar un prefijo IPv6 en notación CIDR (ej. 2001:db8:abcd::/48)."
        )
    try:
        network = ipaddress.ip_network(raw, strict=strict)
    except ValueError as exc:
        hint = ""
        try:
            relaxed = ipaddress.ip_network(raw, strict=False)
            if isinstance(relaxed, IPv6Network):
                hint = f" ¿Quiso decir {relaxed.with_prefixlen}?"
        except ValueError:
            hint = ""
        raise InvalidNetworkError(f"CIDR IPv6 inválido '{raw}': {exc}.{hint}") from exc
    if not isinstance(network, IPv6Network):
        raise InvalidNetworkError(f"'{raw}' no es un prefijo IPv6.")
    return network


def interface_bits_for_devices(devices: int) -> int:
    """Bits de interfaz mínimos para N direcciones asignables."""
    if devices < 1:
        raise InvalidNetworkError("El número de dispositivos debe ser ≥ 1.")
    return max(1, math.ceil(math.log2(devices)))


def prefix_for_devices(devices: int, *, nibble_align: bool = False) -> tuple[int, int]:
    """Devuelve (prefixlen, interface_bits) para N dispositivos."""
    iid_bits = interface_bits_for_devices(devices)
    prefixlen = 128 - iid_bits
    if nibble_align:
        aligned = (prefixlen // 4) * 4
        prefixlen = aligned
        iid_bits = 128 - prefixlen
    return prefixlen, iid_bits


def _align_up(value: int, block: int) -> int:
    remainder = value % block
    if remainder == 0:
        return value
    return value + (block - remainder)


def _assignable_range(network: IPv6Network) -> tuple[IPv6Address, IPv6Address, IPv6Address]:
    """(primera asignable, última asignable, anycast de router/subred)."""
    anycast = network.network_address
    last = network.broadcast_address
    if network.prefixlen >= 127:
        first = anycast
    else:
        first = IPv6Address(int(anycast) + 1)
    return first, last, anycast


def _leftover_ranges(parent: IPv6Network, assigned: list[IPv6Network]) -> list[IPv6Network]:
    leftovers: list[IPv6Network] = []
    cursor = int(parent.network_address)
    end = int(parent.broadcast_address)
    for child in sorted(assigned, key=lambda net: int(net.network_address)):
        start = int(child.network_address)
        if cursor < start:
            leftovers.extend(
                ipaddress.summarize_address_range(IPv6Address(cursor), IPv6Address(start - 1))
            )
        cursor = int(child.broadcast_address) + 1
    if cursor <= end:
        leftovers.extend(
            ipaddress.summarize_address_range(IPv6Address(cursor), IPv6Address(end))
        )
    return leftovers


def _assert_no_collisions(parent: IPv6Network, children: list[IPv6Network]) -> None:
    for index, left in enumerate(children):
        if not left.subnet_of(parent):
            raise SubnetCollisionError(
                f"El prefijo {left.with_prefixlen} no está contenido en {parent.with_prefixlen}."
            )
        for right in children[index + 1 :]:
            if left.overlaps(right):
                raise SubnetCollisionError(
                    f"Colisión IPv6 entre {left.with_prefixlen} y {right.with_prefixlen}."
                )


def _build_subnet(
    name: str,
    child: IPv6Network,
    parent: IPv6Network,
    *,
    requested_devices: int,
    required_prefix: int,
    order: int,
) -> IPv6Subnet:
    first, last, anycast = _assignable_range(child)
    total = child.num_addresses
    waste = max(total - requested_devices, 0) if requested_devices else 0
    if requested_devices and total:
        efficiency = requested_devices / total * 100.0
    elif requested_devices == 0:
        efficiency = 100.0
    else:
        efficiency = 0.0
    extra_bits = max(required_prefix - child.prefixlen, 0)
    return IPv6Subnet(
        name=name,
        prefix_cidr=child.with_prefixlen,
        compressed=child.compressed,
        expanded=f"{child.network_address.exploded}/{child.prefixlen}",
        prefixlen=child.prefixlen,
        first_assignable=str(first.compressed),
        last_assignable=str(last.compressed),
        router_anycast=str(anycast.compressed),
        first_assignable_expanded=first.exploded,
        last_assignable_expanded=last.exploded,
        router_anycast_expanded=anycast.exploded,
        total_addresses=total,
        requested_devices=requested_devices,
        interface_bits=128 - child.prefixlen,
        bits_borrowed=child.prefixlen - parent.prefixlen,
        jump_decimal=total,
        jump_hex=hex(total),
        waste_addresses=waste,
        efficiency_pct=efficiency,
        waste_pct=100.0 - efficiency,
        extra_prefix_bits=extra_bits,
        allocation_order=order,
    )


def calculate_ipv6(
    base_cidr: str,
    *,
    mode: Literal["fixed", "hosts"] = "fixed",
    target_prefix: int | None = None,
    count: int | None = None,
    requests: list[HostRequest] | list[tuple[str, int]] | None = None,
    names: list[str] | None = None,
    nibble_align: bool = False,
    limit: int = MAX_LISTED_SUBNETS,
    strict: bool = True,
) -> IPv6Result:
    """Calcula la subdivisión IPv6 según el modo indicado."""
    parent = parse_ipv6_network(base_cidr, strict=strict)
    if mode == "fixed":
        return _calculate_fixed(
            parent,
            target_prefix=target_prefix,
            count=count,
            names=names,
            requests=requests,
            limit=limit,
        )
    if mode == "hosts":
        if not requests:
            raise InvalidNetworkError(
                "El modo por dispositivos requiere una lista de nombres y cantidades."
            )
        return _calculate_by_hosts(
            parent,
            requests=requests,
            nibble_align=nibble_align,
            limit=limit,
        )
    raise InvalidNetworkError(f"Modo IPv6 desconocido: {mode}")


def _calculate_fixed(
    parent: IPv6Network,
    *,
    target_prefix: int | None,
    count: int | None,
    names: list[str] | None,
    requests: list[HostRequest] | list[tuple[str, int]] | None,
    limit: int,
) -> IPv6Result:
    if target_prefix is None:
        raise InvalidNetworkError("Debe indicar el prefijo hijo (ej. 64, 56 o 127).")
    if not (parent.prefixlen <= target_prefix <= 128):
        raise InvalidNetworkError(
            f"El prefijo hijo /{target_prefix} debe cumplir "
            f"{parent.prefixlen} ≤ p ≤ 128 respecto del padre {parent.with_prefixlen}."
        )

    borrowed = target_prefix - parent.prefixlen
    capacity = 1 << borrowed if borrowed <= 62 else 2**borrowed
    labels = _fixed_labels(count, names, requests, capacity)
    if len(labels) > capacity:
        raise InsufficientAddressSpaceError(
            f"Se pidieron {len(labels)} subredes /{target_prefix}, "
            f"pero {parent.with_prefixlen} solo produce {capacity}."
        )
    if len(labels) > limit:
        labels = labels[:limit]
        truncated = True
    else:
        truncated = False

    steps: list[CalculationStep] = [
        CalculationStep(
            index=1,
            title="Validación del prefijo IPv6 base",
            formula="IPv6Network(cidr, strict=True)",
            inputs={"cidr": parent.with_prefixlen},
            outputs={
                "comprimido": parent.compressed,
                "expandido": parent.network_address.exploded,
                "prefijo": parent.prefixlen,
                "tipo": _scope_label(parent),
                "capacidad": str(parent.num_addresses),
            },
            notes=_scope_note(parent),
        ),
        CalculationStep(
            index=2,
            title="Prefix Delegation de tamaño fijo",
            formula="hijos = 2^(prefijo_hijo - prefijo_padre); salto = 2^(128-prefijo_hijo)",
            inputs={
                "prefijo_hijo": target_prefix,
                "bits_prestados": borrowed,
                "solicitadas": len(labels),
            },
            outputs={
                "capacidad_hijos": str(capacity),
                "salto_dec": str(2 ** (128 - target_prefix)),
                "salto_hex": hex(2 ** (128 - target_prefix)),
            },
            notes="Cada VLAN/enlace recibe el mismo tamaño; el incremento ocurre en los bits delegados.",
        ),
    ]

    generator = parent.subnets(new_prefix=target_prefix)
    assigned: list[IPv6Network] = []
    subnets: list[IPv6Subnet] = []
    jump = 2 ** (128 - target_prefix)

    for order, label in enumerate(labels, start=1):
        child = next(generator)
        requested = 0
        if requests:
            requested = _requested_for_name(requests, label)
        subnet = _build_subnet(
            label,
            child,
            parent,
            requested_devices=requested,
            required_prefix=target_prefix,
            order=order,
        )
        assigned.append(child)
        subnets.append(subnet)
        if order <= 12 or order == len(labels):
            steps.append(
                CalculationStep(
                    index=2 + order,
                    title=f"Delegación {order}: {label}",
                    formula="siguiente = red_actual + 2^(128-p)",
                    inputs={"salto": hex(jump)},
                    outputs={
                        "cidr": child.with_prefixlen,
                        "comprimido": child.compressed,
                        "expandido": child.network_address.exploded,
                        "anycast": subnet.router_anycast,
                        "primera": subnet.first_assignable,
                        "última": subnet.last_assignable,
                    },
                    notes="Anycast de router/subred = identificador de interfaz todo cero (RFC 4291).",
                )
            )

    _assert_no_collisions(parent, assigned)
    leftovers = _leftover_ranges(parent, assigned)
    used = sum(net.num_addresses for net in assigned)
    leftover_count = parent.num_addresses - used
    requested_total = sum(item.requested_devices for item in subnets)
    host_eff = (requested_total / used * 100.0) if requested_total and used else 100.0
    space_eff = (used / parent.num_addresses * 100.0) if parent.num_addresses else 0.0

    listed_leftovers = leftovers[:32]
    notes = [
        f"Modo Prefix Delegation: {len(subnets)} prefijos /{target_prefix} desde {parent.with_prefixlen}.",
        "La primera dirección de cada subred es el Subnet-Router Anycast; el rango asignable comienza en ::1 salvo /127 y /128.",
    ]
    if truncated:
        notes.append(f"Listado truncado a {limit} subredes para no saturar memoria/UI.")
    if borrowed >= 16 and count is None and not names:
        notes.append(
            f"Un /{parent.prefixlen} produce {capacity} redes /{target_prefix}; "
            "use --count o nombres para limitar el listado."
        )

    steps.append(
        CalculationStep(
            index=3 + len(subnets),
            title="Auditoría de colisiones y residuo",
            formula="¬overlaps ; leftover = summarize_address_range IPv6",
            inputs={"generadas": len(assigned)},
            outputs={
                "colisiones": "ninguna",
                "usadas": str(used),
                "libres": str(leftover_count),
                "rangos_libres_muestra": [net.with_prefixlen for net in listed_leftovers],
            },
            notes="Los prefijos no delegados permanecen en el pool del padre.",
        )
    )

    return IPv6Result(
        mode="fixed",
        base_cidr=parent.with_prefixlen,
        base_compressed=parent.compressed,
        base_expanded=f"{parent.network_address.exploded}/{parent.prefixlen}",
        base_prefix=parent.prefixlen,
        target_prefix=target_prefix,
        total_addresses=parent.num_addresses,
        used_addresses=used,
        leftover_addresses=leftover_count,
        leftover_cidrs=[net.with_prefixlen for net in listed_leftovers],
        requested_devices_total=requested_total,
        subnet_count=len(subnets),
        child_capacity=capacity,
        truncated=truncated,
        host_efficiency_pct=host_eff,
        space_efficiency_pct=space_eff,
        waste_pct=100.0 - host_eff if requested_total else 0.0,
        subnets=subnets,
        steps=steps,
        notes=notes,
    )


def _calculate_by_hosts(
    parent: IPv6Network,
    *,
    requests: list[HostRequest] | list[tuple[str, int]],
    nibble_align: bool,
    limit: int,
) -> IPv6Result:
    normalized = _normalize_requests(requests)
    names = [item.name for item in normalized]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise InvalidNetworkError(f"Nombres de subred duplicados: {', '.join(duplicates)}.")

    sized: list[tuple[HostRequest, int, int]] = []
    for item in normalized:
        prefixlen, iid_bits = prefix_for_devices(item.hosts, nibble_align=nibble_align)
        if prefixlen < parent.prefixlen:
            raise InsufficientAddressSpaceError(
                f"'{item.name}' necesita /{prefixlen} ({item.hosts} dispositivos), "
                f"más amplio que el padre {parent.with_prefixlen}."
            )
        sized.append((item, prefixlen, iid_bits))

    ordered = sorted(sized, key=lambda row: (row[1], -row[0].hosts, row[0].original_index))
    steps: list[CalculationStep] = [
        CalculationStep(
            index=1,
            title="Validación del prefijo IPv6 base",
            formula="IPv6Network(cidr, strict=True)",
            inputs={"cidr": parent.with_prefixlen},
            outputs={
                "comprimido": parent.compressed,
                "expandido": parent.network_address.exploded,
                "tipo": _scope_label(parent),
            },
            notes=_scope_note(parent),
        ),
        CalculationStep(
            index=2,
            title="Cálculo de bits de interfaz por segmento",
            formula="iid=ceil(log2(N)); prefijo=128-iid" + (" ; nibble=4*floor(p/4)" if nibble_align else ""),
            inputs={"solicitudes": [f"{item.name}:{item.hosts}" for item, _, _ in sized]},
            outputs={
                "prefijos": [f"{item.name}→/{prefix} (IID {iid} bits)" for item, prefix, iid in sized],
                "nibble_align": nibble_align,
            },
            notes=(
                "IPv6 no reserva broadcast; se dimensiona por direcciones asignables. "
                "SLAAC/EUI-64 exige /64 en LAN aunque N sea pequeño."
            ),
        ),
        CalculationStep(
            index=3,
            title="Ordenamiento por tamaño de bloque (prefijo más corto primero)",
            formula="sorted(key=prefixlen asc, hosts desc)",
            inputs={},
            outputs={"orden": [f"{item.name}:/{prefix}" for item, prefix, _ in ordered]},
            notes="Igual que VLSM IPv4: los bloques grandes se colocan primero para alinear fronteras.",
        ),
    ]

    if len(ordered) > limit:
        ordered = ordered[:limit]
        truncated = True
    else:
        truncated = False

    cursor = int(parent.network_address)
    parent_end = int(parent.broadcast_address)
    assigned: list[IPv6Network] = []
    subnets: list[IPv6Subnet] = []

    for order, (request, prefixlen, iid_bits) in enumerate(ordered, start=1):
        block = 2 ** (128 - prefixlen)
        aligned = _align_up(cursor, block)
        last_addr = aligned + block - 1
        if last_addr > parent_end:
            remaining = parent_end - cursor + 1 if cursor <= parent_end else 0
            raise InsufficientAddressSpaceError(
                f"No hay espacio para '{request.name}' (/{prefixlen}) a partir de "
                f"{IPv6Address(cursor).compressed}. Quedan {remaining} direcciones libres."
            )
        child = IPv6Network((aligned, prefixlen))
        subnet = _build_subnet(
            request.name,
            child,
            parent,
            requested_devices=request.hosts,
            required_prefix=prefixlen if not nibble_align else prefix_for_devices(request.hosts, nibble_align=False)[0],
            order=order,
        )
        assigned.append(child)
        subnets.append(subnet)
        gap = aligned - cursor
        steps.append(
            CalculationStep(
                index=3 + order,
                title=f"Asignación {order}: {request.name}",
                formula="needed=N; iid=ceil(log2(N)); bloque=2^iid",
                inputs={
                    "dispositivos": request.hosts,
                    "iid_bits": iid_bits,
                    "puntero": IPv6Address(cursor).compressed,
                    "alineación": gap,
                },
                outputs={
                    "prefijo": child.with_prefixlen,
                    "comprimido": child.compressed,
                    "expandido": child.network_address.exploded,
                    "anycast": subnet.router_anycast,
                    "rango": f"{subnet.first_assignable} — {subnet.last_assignable}",
                    "salto_hex": hex(block),
                    "eficiencia_%": round(subnet.efficiency_pct, 6),
                },
                notes=(
                    "Anycast de router/subred = :: de la subred. "
                    + ("Alineado a nibble (RFC 5375)." if nibble_align else "Ajuste ceñido, sin forzar nibble.")
                ),
            )
        )
        cursor = aligned + block

    _assert_no_collisions(parent, assigned)
    leftovers = _leftover_ranges(parent, assigned)
    used = sum(net.num_addresses for net in assigned)
    leftover_count = parent.num_addresses - used
    requested_total = sum(item.hosts for item, _, _ in ordered)
    host_eff = (requested_total / used * 100.0) if used else 0.0
    space_eff = (used / parent.num_addresses * 100.0) if parent.num_addresses else 0.0
    listed_leftovers = leftovers[:32]

    steps.append(
        CalculationStep(
            index=4 + len(subnets),
            title="Auditoría de colisiones y residuo",
            formula="¬overlaps ; leftover = summarize_address_range IPv6",
            inputs={"subredes": [net.with_prefixlen for net in assigned]},
            outputs={
                "colisiones": "ninguna",
                "usadas": str(used),
                "libres": str(leftover_count),
                "rangos_libres_muestra": [net.with_prefixlen for net in listed_leftovers],
            },
            notes="Un /64 para decenas de hosts tiene eficiencia numérica ~0 % y es, aun así, la práctica recomendada en LAN.",
        )
    )

    notes = [
        "Dimensionamiento por dispositivos: el prefijo se deriva de los bits de interfaz necesarios.",
        "SLAAC requiere /64; use nibble-align o Prefix Delegation fijo /64 para VLANs de acceso.",
    ]
    if truncated:
        notes.append(f"Listado truncado a {limit} subredes.")

    return IPv6Result(
        mode="hosts",
        base_cidr=parent.with_prefixlen,
        base_compressed=parent.compressed,
        base_expanded=f"{parent.network_address.exploded}/{parent.prefixlen}",
        base_prefix=parent.prefixlen,
        target_prefix=None,
        total_addresses=parent.num_addresses,
        used_addresses=used,
        leftover_addresses=leftover_count,
        leftover_cidrs=[net.with_prefixlen for net in listed_leftovers],
        requested_devices_total=requested_total,
        subnet_count=len(subnets),
        child_capacity=len(subnets),
        truncated=truncated,
        host_efficiency_pct=host_eff,
        space_efficiency_pct=space_eff,
        waste_pct=100.0 - host_eff,
        subnets=subnets,
        steps=steps,
        notes=notes,
    )


def _scope_label(network: IPv6Network) -> str:
    addr = int(network.network_address)
    if network.is_loopback:
        return "Loopback"
    if network.is_multicast:
        return "Multicast"
    if network.is_link_local:
        return "Link-local (fe80::/10) — no enrutable"
    if (addr >> 96) == 0x20010DB8:
        return "Documentación (RFC 3849, 2001:db8::/32)"
    if network.is_private:
        return "ULA (RFC 4193)"
    if network.is_global:
        return "Global Unicast"
    return "IPv6"


def _scope_note(network: IPv6Network) -> str:
    label = _scope_label(network)
    if "ULA" in label:
        return "ULA: enrutable internamente, no en Internet público. Ideal para laboratorios dual-stack."
    if "Documentación" in label:
        return "Prefijo de documentación: válido en ejemplos, filtros y laboratorios; no se anuncia en producción."
    if "Link-local" in label:
        return "fe80::/10 no se debe subdividir para VLAN de campus; use GUA o ULA."
    return "Prefijo aceptado. Verifique que no solape delegaciones ya entregadas por el ISP o el Nibble boundary."


def _fixed_labels(
    count: int | None,
    names: list[str] | None,
    requests: list[HostRequest] | list[tuple[str, int]] | None,
    capacity: int,
) -> list[str]:
    if requests:
        normalized = _normalize_requests(requests)
        return [item.name for item in normalized]
    if names:
        cleaned = [name.strip() for name in names if name.strip()]
        if not cleaned:
            raise InvalidNetworkError("La lista de nombres está vacía.")
        return cleaned
    n = count if count is not None else min(capacity, 8)
    if n < 1:
        raise InvalidNetworkError("El número de subredes debe ser ≥ 1.")
    if n > capacity:
        raise InsufficientAddressSpaceError(
            f"Se solicitaron {n} subredes, pero el padre solo permite {capacity}."
        )
    width = max(2, len(str(n - 1)))
    return [f"Subred-{index:0{width}d}" for index in range(n)]


def _requested_for_name(
    requests: list[HostRequest] | list[tuple[str, int]],
    name: str,
) -> int:
    for item in _normalize_requests(requests):
        if item.name == name:
            return item.hosts
    return 0


def _normalize_requests(
    requests: list[HostRequest] | list[tuple[str, int]],
) -> list[HostRequest]:
    if not requests:
        raise InvalidNetworkError("Debe indicar al menos una subred.")
    normalized: list[HostRequest] = []
    for index, item in enumerate(requests):
        if isinstance(item, HostRequest):
            normalized.append(
                HostRequest(name=item.name, hosts=item.hosts, original_index=item.original_index or index)
            )
        else:
            name, hosts = item
            normalized.append(HostRequest(name=str(name), hosts=int(hosts), original_index=index))
    return normalized
