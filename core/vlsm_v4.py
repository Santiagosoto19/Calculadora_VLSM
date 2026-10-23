"""Motor VLSM clásico para IPv4.

Algoritmo:
1. Validar el CIDR base (dirección de red estricta).
2. Ordenar solicitudes de hosts de mayor a menor.
3. Para cada solicitud, calcular la potencia de 2 mínima que cubra
   hosts + 2 (dirección de red y broadcast).
4. Alinear el puntero de asignación al tamaño de bloque.
5. Verificar capacidad, contención en el padre y ausencia de colisiones.
6. Registrar cada decisión en la memoria de cálculo.
"""

from __future__ import annotations

import ipaddress
import math
from ipaddress import IPv4Address, IPv4Network

from core.models import (
    CalculationStep,
    HostRequest,
    InsufficientAddressSpaceError,
    InvalidNetworkError,
    IPv4Subnet,
    SubnetCollisionError,
    VLSMResult,
)


def parse_ipv4_network(cidr: str, *, strict: bool = True) -> IPv4Network:
    """Parsea un bloque IPv4 en notación CIDR."""
    raw = (cidr or "").strip()
    if not raw:
        raise InvalidNetworkError("Debe indicar un bloque IPv4 en notación CIDR (ej. 192.168.1.0/24).")
    try:
        network = ipaddress.ip_network(raw, strict=strict)
    except ValueError as exc:
        hint = ""
        try:
            relaxed = ipaddress.ip_network(raw, strict=False)
            if isinstance(relaxed, IPv4Network):
                hint = f" ¿Quiso decir {relaxed.with_prefixlen}?"
        except ValueError:
            hint = ""
        raise InvalidNetworkError(f"CIDR IPv4 inválido '{raw}': {exc}.{hint}") from exc
    if not isinstance(network, IPv4Network):
        raise InvalidNetworkError(f"'{raw}' no es un prefijo IPv4.")
    return network


def required_block(usable_hosts: int) -> tuple[int, int, int]:
    """Devuelve (tamaño de bloque, bits de host, prefijo) para N hosts útiles.

    Se reserva siempre red + broadcast, según VLSM de libro de texto:
    needed = hosts + 2, bloque = 2^ceil(log2(needed)).
    """
    if usable_hosts < 1:
        raise InvalidNetworkError("El número de hosts debe ser un entero ≥ 1.")
    needed = usable_hosts + 2
    host_bits = math.ceil(math.log2(needed))
    if host_bits > 32:
        raise InsufficientAddressSpaceError(
            f"Se requieren {needed} direcciones, por encima del espacio IPv4 (2^32)."
        )
    block_size = 1 << host_bits
    prefixlen = 32 - host_bits
    return block_size, host_bits, prefixlen


def _wildcard_dotted(prefixlen: int) -> str:
    wildcard_int = (1 << (32 - prefixlen)) - 1 if prefixlen < 32 else 0
    return str(IPv4Address(wildcard_int))


def _mask_binary(netmask: IPv4Address) -> str:
    packed = int(netmask)
    octets = [(packed >> shift) & 0xFF for shift in (24, 16, 8, 0)]
    return ".".join(f"{octet:08b}" for octet in octets)


def _align_up(value: int, block: int) -> int:
    remainder = value % block
    if remainder == 0:
        return value
    return value + (block - remainder)


def _leftover_ranges(parent: IPv4Network, assigned: list[IPv4Network]) -> list[IPv4Network]:
    leftovers: list[IPv4Network] = []
    cursor = int(parent.network_address)
    end = int(parent.broadcast_address)
    for child in sorted(assigned, key=lambda net: int(net.network_address)):
        start = int(child.network_address)
        if cursor < start:
            leftovers.extend(
                ipaddress.summarize_address_range(IPv4Address(cursor), IPv4Address(start - 1))
            )
        cursor = int(child.broadcast_address) + 1
    if cursor <= end:
        leftovers.extend(
            ipaddress.summarize_address_range(IPv4Address(cursor), IPv4Address(end))
        )
    return leftovers


def _assert_no_collisions(parent: IPv4Network, children: list[IPv4Network]) -> None:
    for index, left in enumerate(children):
        if not left.subnet_of(parent):
            raise SubnetCollisionError(
                f"La subred {left.with_prefixlen} no está contenida en {parent.with_prefixlen}."
            )
        for right in children[index + 1 :]:
            if left.overlaps(right):
                raise SubnetCollisionError(
                    f"Colisión detectada entre {left.with_prefixlen} y {right.with_prefixlen}."
                )


def _usable_endpoints(network: IPv4Network) -> tuple[str, str, str]:
    """Primera útil, última útil y broadcast."""
    if network.prefixlen >= 31:
        hosts = list(network.hosts()) if network.prefixlen == 31 else [network.network_address]
        first = str(hosts[0]) if hosts else str(network.network_address)
        last = str(hosts[-1]) if hosts else str(network.network_address)
        return first, last, str(network.broadcast_address)
    return (
        str(network.network_address + 1),
        str(network.broadcast_address - 1),
        str(network.broadcast_address),
    )


def calculate_vlsm_v4(
    base_cidr: str,
    requests: list[HostRequest] | list[tuple[str, int]],
    *,
    strict: bool = True,
    sort_largest_first: bool = True,
) -> VLSMResult:
    """Calcula el plan VLSM IPv4 y su memoria de cálculo."""
    parent = parse_ipv4_network(base_cidr, strict=strict)
    normalized = _normalize_requests(requests)
    steps: list[CalculationStep] = []

    steps.append(
        CalculationStep(
            index=1,
            title="Validación del bloque base IPv4",
            formula="IPv4Network(cidr, strict=True)",
            inputs={"cidr": base_cidr.strip()},
            outputs={
                "red": str(parent.network_address),
                "máscara": str(parent.netmask),
                "prefijo": parent.prefixlen,
                "broadcast": str(parent.broadcast_address),
                "capacidad": parent.num_addresses,
            },
            notes="La dirección indicada debe coincidir con la dirección de red del prefijo.",
        )
    )

    names = [item.name for item in normalized]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise InvalidNetworkError(f"Nombres de subred duplicados: {', '.join(duplicates)}.")

    if sort_largest_first:
        ordered = sorted(normalized, key=lambda item: (-item.hosts, item.original_index, item.name))
        order_note = "Asignar primero los bloques grandes evita fragmentación y simplifica la alineación."
    else:
        ordered = list(normalized)
        order_note = "Se respeta el orden de la tabla (modo laboratorio)."
    steps.append(
        CalculationStep(
            index=2,
            title="Ordenamiento de solicitudes",
            formula="sorted(hosts desc)" if sort_largest_first else "orden de entrada",
            inputs={"orden_original": [f"{item.name}:{item.hosts}" for item in normalized]},
            outputs={"orden_asignación": [f"{item.name}:{item.hosts}" for item in ordered]},
            notes=order_note,
        )
    )

    preview_blocks = [required_block(item.hosts)[0] for item in ordered]
    total_needed = sum(preview_blocks)
    steps.append(
        CalculationStep(
            index=3,
            title="Comprobación de capacidad del bloque padre",
            formula="Σ 2^ceil(log2(hosts_i + 2)) ≤ 2^(32-prefijo_padre)",
            inputs={
                "bloques_estimados": preview_blocks,
                "suma_bloques": total_needed,
                "capacidad_padre": parent.num_addresses,
            },
            outputs={"cabe_sin_alineación": total_needed <= parent.num_addresses},
            notes="La alineación a potencia de 2 puede consumir huecos extra; se valida de nuevo al asignar.",
        )
    )
    if total_needed > parent.num_addresses:
        raise InsufficientAddressSpaceError(
            f"El bloque {parent.with_prefixlen} tiene {parent.num_addresses} direcciones, "
            f"pero las solicitudes requieren {total_needed} (hosts+red+broadcast, redondeados a potencia de 2)."
        )

    cursor = int(parent.network_address)
    parent_end = int(parent.broadcast_address)
    assigned_networks: list[IPv4Network] = []
    subnets: list[IPv4Subnet] = []

    for order, request in enumerate(ordered, start=1):
        block_size, host_bits, prefixlen = required_block(request.hosts)
        aligned = _align_up(cursor, block_size)
        gap = aligned - cursor
        last_addr = aligned + block_size - 1
        if last_addr > parent_end:
            remaining = parent_end - cursor + 1 if cursor <= parent_end else 0
            raise InsufficientAddressSpaceError(
                f"No hay espacio para '{request.name}' ({request.hosts} hosts → /{prefixlen}, "
                f"bloque {block_size}) a partir de {IPv4Address(cursor)}. "
                f"Quedan {max(remaining, 0)} direcciones libres en {parent.with_prefixlen}."
            )

        child = IPv4Network((aligned, prefixlen))
        first_usable, last_usable, broadcast = _usable_endpoints(child)
        assigned_usable = child.num_addresses - 2 if child.prefixlen <= 30 else child.num_addresses
        waste = max(assigned_usable - request.hosts, 0)
        efficiency = (request.hosts / assigned_usable * 100.0) if assigned_usable else 0.0
        bits_borrowed = prefixlen - parent.prefixlen
        if bits_borrowed < 0:
            raise InsufficientAddressSpaceError(
                f"'{request.name}' exige /{prefixlen}, más amplio que el padre /{parent.prefixlen}."
            )

        subnet = IPv4Subnet(
            name=request.name,
            requested_hosts=request.hosts,
            assigned_usable=assigned_usable,
            network=str(child.network_address),
            netmask=str(child.netmask),
            netmask_binary=_mask_binary(child.netmask),
            cidr=child.with_prefixlen,
            prefixlen=prefixlen,
            first_usable=first_usable,
            last_usable=last_usable,
            broadcast=broadcast,
            wildcard=_wildcard_dotted(prefixlen),
            block_size=block_size,
            host_bits=host_bits,
            bits_borrowed=bits_borrowed,
            jump_decimal=block_size,
            jump_hex=hex(block_size),
            waste_hosts=waste,
            efficiency_pct=efficiency,
            waste_pct=100.0 - efficiency,
            allocation_order=order,
        )
        subnets.append(subnet)
        assigned_networks.append(child)

        steps.append(
            CalculationStep(
                index=3 + order,
                title=f"Asignación {order}: {request.name}",
                formula="needed=H+2; host_bits=ceil(log2(needed)); bloque=2^host_bits; prefijo=32-host_bits",
                inputs={
                    "hosts_solicitados": request.hosts,
                    "needed": request.hosts + 2,
                    "puntero_previo": str(IPv4Address(cursor)),
                    "alineación": gap,
                },
                outputs={
                    "host_bits": host_bits,
                    "bloque": block_size,
                    "prefijo": f"/{prefixlen}",
                    "máscara": str(child.netmask),
                    "máscara_binaria": subnet.netmask_binary,
                    "red": child.with_prefixlen,
                    "primera_útil": first_usable,
                    "última_útil": last_usable,
                    "broadcast": broadcast,
                    "wildcard": subnet.wildcard,
                    "salto_dec": block_size,
                    "salto_hex": hex(block_size),
                    "eficiencia_%": round(efficiency, 2),
                },
                notes=(
                    f"Se toman prestados {bits_borrowed} bits de la porción de host del /{parent.prefixlen}. "
                    + (f"Hueco de alineación: {gap} direcciones." if gap else "Sin hueco de alineación.")
                ),
            )
        )
        cursor = aligned + block_size

    _assert_no_collisions(parent, assigned_networks)

    leftovers = _leftover_ranges(parent, assigned_networks)
    used = sum(net.num_addresses for net in assigned_networks)
    leftover_count = parent.num_addresses - used
    requested_total = sum(item.hosts for item in ordered)
    assigned_usable_total = sum(item.assigned_usable for item in subnets)
    host_eff = (requested_total / assigned_usable_total * 100.0) if assigned_usable_total else 0.0
    space_eff = (used / parent.num_addresses * 100.0) if parent.num_addresses else 0.0

    steps.append(
        CalculationStep(
            index=4 + len(subnets),
            title="Auditoría de colisiones y espacio residual",
            formula="¬overlaps(i,j) ∧ subnet_of(padre) ; leftover = summarize_address_range",
            inputs={"subredes": [net.with_prefixlen for net in assigned_networks]},
            outputs={
                "colisiones": "ninguna",
                "direcciones_usadas": used,
                "direcciones_libres": leftover_count,
                "rangos_libres": [net.with_prefixlen for net in leftovers],
            },
            notes="Los rangos libres quedan disponibles para crecimiento futuro o enlaces adicionales.",
        )
    )

    notes = [
        "Las IPs de red y broadcast no se asignan a hosts (excepto /31 y /32, no usados en este modo +2).",
        "La eficiencia de hosts compara solicitados contra útiles del bloque; el uso del bloque incluye red y broadcast.",
    ]
    if leftovers:
        notes.append("Espacio sobrante: " + ", ".join(net.with_prefixlen for net in leftovers) + ".")

    return VLSMResult(
        base_cidr=parent.with_prefixlen,
        base_network=str(parent.network_address),
        base_prefix=parent.prefixlen,
        total_addresses=parent.num_addresses,
        used_addresses=used,
        leftover_addresses=leftover_count,
        leftover_cidrs=[net.with_prefixlen for net in leftovers],
        requested_hosts_total=requested_total,
        assigned_usable_total=assigned_usable_total,
        subnet_count=len(subnets),
        host_efficiency_pct=host_eff,
        space_efficiency_pct=space_eff,
        waste_pct=100.0 - host_eff,
        subnets=subnets,
        steps=steps,
        notes=notes,
    )


def _normalize_requests(
    requests: list[HostRequest] | list[tuple[str, int]],
) -> list[HostRequest]:
    if not requests:
        raise InvalidNetworkError("Debe indicar al menos una subred con su número de hosts.")
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


def calculate_vlsm_grouped(
    base_cidr: str,
    groups: list[tuple[str, list[HostRequest] | list[tuple[str, int]]]],
    *,
    group_prefix: int | None = None,
    sort_largest_first: bool = True,
    strict: bool = True,
) -> "MultiVLSMResult":
    """Parte el bloque padre en contenedores y aplica VLSM dentro de cada grupo."""
    from core.models import MultiVLSMResult, VLSMGroup

    if not groups:
        raise InvalidNetworkError("Debe indicar al menos un grupo (edificio, sede o VLAN).")
    names = [name.strip() for name, _ in groups]
    if any(not name for name in names):
        raise InvalidNetworkError("El nombre de un grupo no puede estar vacío.")
    if len(names) != len(set(names)):
        raise InvalidNetworkError("Hay nombres de grupo duplicados.")

    parent = parse_ipv4_network(base_cidr, strict=strict)
    prepared: list[tuple[str, list[HostRequest], int]] = []
    for name, raw_requests in groups:
        requests = _normalize_requests(raw_requests)
        if group_prefix is not None:
            if not (parent.prefixlen < group_prefix <= 30):
                raise InvalidNetworkError(
                    f"El prefijo de grupo /{group_prefix} debe ser mayor que /{parent.prefixlen} y ≤ /30."
                )
            container_prefix = group_prefix
        else:
            probe = calculate_vlsm_v4("10.0.0.0/8", requests, sort_largest_first=sort_largest_first)
            used = max(probe.used_addresses, 4)
            host_bits = max(2, math.ceil(math.log2(used)))
            container_prefix = 32 - host_bits
            if container_prefix < parent.prefixlen:
                raise InsufficientAddressSpaceError(
                    f"El grupo '{name}' necesita /{container_prefix}, más amplio que {parent.with_prefixlen}."
                )
        prepared.append((name.strip(), requests, container_prefix))

    container_hosts = [
        HostRequest(name=name, hosts=(1 << (32 - prefix)) - 2, original_index=index)
        for index, (name, _, prefix) in enumerate(prepared)
    ]
    containers_plan = calculate_vlsm_v4(
        parent.with_prefixlen,
        container_hosts,
        strict=strict,
        sort_largest_first=group_prefix is None,
    )
    by_name = {item.name: item for item in containers_plan.subnets}

    built: list[VLSMGroup] = []
    all_steps = list(containers_plan.steps)
    for name, requests, _prefix in prepared:
        container = by_name[name]
        inner = calculate_vlsm_v4(
            container.cidr,
            requests,
            strict=True,
            sort_largest_first=sort_largest_first,
        )
        all_steps.extend(inner.steps)
        built.append(VLSMGroup(name=name, container=container, result=inner))

    requested_total = sum(group.result.requested_hosts_total for group in built)
    assigned_usable = sum(group.result.assigned_usable_total for group in built)
    used = containers_plan.used_addresses
    host_eff = (requested_total / assigned_usable * 100.0) if assigned_usable else 0.0
    notes = [
        f"{len(built)} grupos en {parent.with_prefixlen}.",
        "Cada grupo ocupa un contenedor; dentro se aplica VLSM.",
    ]
    if group_prefix is not None:
        notes.append(f"Contenedores de tamaño fijo /{group_prefix}.")
    if not sort_largest_first:
        notes.append("Orden interno: el de la tabla (laboratorio).")

    return MultiVLSMResult(
        base_cidr=parent.with_prefixlen,
        base_network=str(parent.network_address),
        base_prefix=parent.prefixlen,
        total_addresses=parent.num_addresses,
        used_addresses=used,
        leftover_addresses=containers_plan.leftover_addresses,
        leftover_cidrs=list(containers_plan.leftover_cidrs),
        requested_hosts_total=requested_total,
        assigned_usable_total=assigned_usable,
        subnet_count=sum(group.result.subnet_count for group in built),
        host_efficiency_pct=host_eff,
        space_efficiency_pct=containers_plan.space_efficiency_pct,
        waste_pct=100.0 - host_eff,
        groups=built,
        containers=list(containers_plan.subnets),
        steps=all_steps,
        notes=notes,
        group_prefix=group_prefix,
    )
