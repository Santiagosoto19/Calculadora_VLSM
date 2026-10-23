"""Carga un laboratorio VLSM desde Markdown de texto plano.

Solo admite líneas en blanco, un título ``#``, campos ``- Clave: valor``
antes del primer ``##``, secciones ``##`` y tablas ``| … |``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from core.models import HostRequest, VLSMError

_CANONICAL: dict[str, str] = {
    "protocolo": "Protocolo",
    "base": "Base",
    "modo": "Modo",
    "orden": "Orden",
    "prefijo grupo": "Prefijo grupo",
    "prefijo hijo": "Prefijo hijo",
    "cantidad": "Cantidad",
    "nibble": "Nibble",
}

_APPLIES: dict[str, set[str]] = {
    "listado": {"orden"},
    "grupos": {"orden", "prefijo grupo"},
    "fijo": {"prefijo hijo", "cantidad"},
    "dispositivos": {"nibble"},
}

_MODES = ("listado", "grupos", "fijo", "dispositivos")
_FIELD_RE = re.compile(r"^-\s+([^:]+):\s*(.*)$")
_SECTION_RE = re.compile(r"^##\s+(.+)$")
_SEPARATOR_RE = re.compile(r":?-{3,}:?")


@dataclass(frozen=True, slots=True)
class LabInput:
    protocol: Literal["IPv4", "IPv6"]
    cidr: str
    mode: Literal["listado", "grupos", "fijo", "dispositivos"]
    requests: tuple[HostRequest, ...] = ()
    groups: tuple[tuple[str, tuple[HostRequest, ...]], ...] = ()
    names: tuple[str, ...] = ()
    group_prefix: int | None = None
    input_order: bool = False
    target_prefix: int | None = None
    count: int | None = None
    nibble_align: bool = False


@dataclass
class _Field:
    value: str
    line: int
    raw_key: str


@dataclass
class _Section:
    name: str
    line: int
    header: list[str] | None = None
    header_line: int = 0
    awaiting_separator: bool = False
    rows: list[tuple[int, list[str]]] = field(default_factory=list)


def parse(text: str) -> LabInput:
    """Convierte el Markdown del laboratorio en un :class:`LabInput`."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text.strip():
        _fail(1, "el archivo Markdown está vacío.")

    fields, sections = _scan(text)
    protocol = _protocol(fields)
    cidr = _base(fields)
    mode = _mode(fields, protocol)
    _reject_inapplicable(fields, mode)
    input_order = _input_order(fields)
    group_prefix = _optional_int(fields, "prefijo grupo", "el prefijo de grupo", 8, 30)
    target_prefix = _optional_int(fields, "prefijo hijo", "el prefijo hijo", 1, 128)
    count = _optional_int(fields, "cantidad", "la cantidad", 1, 4096)
    nibble_align = _nibble(fields)

    if mode == "listado":
        return LabInput(
            protocol=protocol,
            cidr=cidr,
            mode="listado",
            requests=_subnet_section(sections, "listado"),
            input_order=input_order,
        )
    if mode == "grupos":
        return LabInput(
            protocol=protocol,
            cidr=cidr,
            mode="grupos",
            groups=_groups(sections),
            group_prefix=group_prefix,
            input_order=input_order,
        )
    if mode == "fijo":
        if target_prefix is None:
            _fail(1, "falta el prefijo hijo (campo Prefijo hijo).")
        names = _fixed_names(sections, count_line=fields["cantidad"].line if "cantidad" in fields else None)
        return LabInput(
            protocol=protocol,
            cidr=cidr,
            mode="fijo",
            names=names,
            target_prefix=target_prefix,
            count=None if names else (8 if count is None else count),
        )
    return LabInput(
        protocol=protocol,
        cidr=cidr,
        mode="dispositivos",
        requests=_subnet_section(sections, "dispositivos"),
        nibble_align=nibble_align,
    )


def _fail(line: int, message: str) -> None:
    raise VLSMError(f"Línea {line}: {message}")


def _norm_key(raw: str) -> str:
    return " ".join(raw.strip().lower().split())


def _scan(text: str) -> tuple[dict[str, _Field], list[_Section]]:
    fields: dict[str, _Field] = {}
    sections: list[_Section] = []
    current: _Section | None = None
    seen_section = False

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("###"):
            _fail(lineno, "no se admiten subtítulos (###).")
        if line.startswith("##"):
            if current is not None and current.awaiting_separator:
                _fail(current.header_line, "la tabla debe incluir la fila separadora '| --- |'.")
            current = _start_section(line, lineno)
            sections.append(current)
            seen_section = True
            continue
        if line.startswith("#"):
            continue
        if line.startswith("-"):
            _read_field(line, lineno, seen_section, fields)
            continue
        if line.startswith("|") and line.endswith("|"):
            if current is None:
                _fail(lineno, "la tabla debe ir dentro de una sección ##.")
            _read_table_row(current, line, lineno)
            continue
        _fail(lineno, "la línea no es un campo, un título (#), una sección (##) ni una fila de tabla.")

    if current is not None and current.awaiting_separator:
        _fail(current.header_line, "la tabla debe incluir la fila separadora '| --- |'.")
    return fields, sections


def _start_section(line: str, lineno: int) -> _Section:
    match = _SECTION_RE.fullmatch(line)
    if match is None:
        _fail(lineno, "la sección debe tener la forma '## Nombre'.")
    name = match.group(1).strip()
    if not name:
        _fail(lineno, "la sección ## necesita un nombre.")
    if "|" in name:
        _fail(lineno, f"el nombre '{name}' no puede contener '|'.")
    return _Section(name=name, line=lineno)


def _read_field(line: str, lineno: int, seen_section: bool, fields: dict[str, _Field]) -> None:
    if not re.match(r"^-\s+", line):
        _fail(lineno, "la línea no es un campo, un título (#), una sección (##) ni una fila de tabla.")
    match = _FIELD_RE.fullmatch(line)
    raw_key = match.group(1).strip() if match else ""
    if seen_section:
        label = raw_key or line
        _fail(lineno, f"el campo '{label}' debe ir antes del primer ##.")
    if match is None or not raw_key:
        _fail(lineno, "el campo debe tener la forma '- Clave: valor'.")
    key = _norm_key(raw_key)
    if key not in _CANONICAL:
        _fail(lineno, f"el campo '{raw_key}' es desconocido.")
    if key in fields:
        _fail(lineno, f"el campo '{_CANONICAL[key]}' está repetido.")
    fields[key] = _Field(value=match.group(2).strip(), line=lineno, raw_key=raw_key)


def _split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_RE.fullmatch(cell.replace(" ", "")) for cell in cells)


def _read_table_row(section: _Section, line: str, lineno: int) -> None:
    cells = _split_cells(line)
    if section.header is None:
        section.header = cells
        section.header_line = lineno
        section.awaiting_separator = True
        return
    if section.awaiting_separator:
        if not _is_separator(cells):
            _fail(lineno, "la segunda fila de la tabla debe ser el separador '| --- |'.")
        if len(cells) != len(section.header):
            _fail(lineno, "la fila separadora no coincide con el encabezado.")
        section.awaiting_separator = False
        return
    section.rows.append((lineno, cells))


def _protocol(fields: dict[str, _Field]) -> Literal["IPv4", "IPv6"]:
    field_ = fields.get("protocolo")
    if field_ is None:
        _fail(1, "falta el protocolo (campo Protocolo: IPv4 o IPv6).")
    token = field_.value.upper()
    if token == "IPV4":
        return "IPv4"
    if token == "IPV6":
        return "IPv6"
    _fail(field_.line, f"el protocolo '{field_.value}' debe ser IPv4 o IPv6.")
    raise AssertionError


def _base(fields: dict[str, _Field]) -> str:
    field_ = fields.get("base")
    if field_ is None:
        _fail(1, "falta el bloque base (campo Base).")
    if "/" not in field_.value:
        _fail(field_.line, f"la base '{field_.value}' debe ser un CIDR (contiene /).")
    return field_.value


def _mode(fields: dict[str, _Field], protocol: str) -> Literal["listado", "grupos", "fijo", "dispositivos"]:
    field_ = fields.get("modo")
    if field_ is None:
        if protocol == "IPv6":
            _fail(1, "falta el modo IPv6 (Modo: fijo o Modo: dispositivos).")
        _fail(1, "falta el modo IPv4 (Modo: listado o Modo: grupos).")
    mode = field_.value.lower()
    if mode not in _MODES:
        _fail(field_.line, f"el modo '{field_.value}' no se reconoce.")
    if protocol == "IPv4" and mode not in {"listado", "grupos"}:
        _fail(field_.line, f"el modo '{mode}' no aplica a {protocol}.")
    if protocol == "IPv6" and mode not in {"fijo", "dispositivos"}:
        _fail(field_.line, f"el modo '{mode}' no aplica a {protocol}.")
    return mode  # type: ignore[return-value]


def _reject_inapplicable(fields: dict[str, _Field], mode: str) -> None:
    allowed = {"protocolo", "base", "modo"} | _APPLIES[mode]
    for key, field_ in fields.items():
        if key not in allowed:
            _fail(field_.line, f"el campo '{_CANONICAL[key]}' no aplica al modo {mode}.")


def _input_order(fields: dict[str, _Field]) -> bool:
    field_ = fields.get("orden")
    if field_ is None:
        return False
    value = field_.value.lower()
    if value == "tabla":
        return True
    if value == "tamaño":
        return False
    _fail(field_.line, f"el orden '{field_.value}' debe ser tabla o tamaño.")
    raise AssertionError


def _optional_int(
    fields: dict[str, _Field],
    key: str,
    noun: str,
    low: int,
    high: int,
) -> int | None:
    field_ = fields.get(key)
    if field_ is None:
        return None
    raw = field_.value
    if not re.fullmatch(r"\d+", raw):
        _fail(field_.line, f"{noun} '{raw}' no es un entero.")
    value = int(raw)
    if value < low or value > high:
        _fail(field_.line, f"{noun} '{raw}' debe estar entre {low} y {high}.")
    return value


def _nibble(fields: dict[str, _Field]) -> bool:
    field_ = fields.get("nibble")
    if field_ is None:
        return False
    value = field_.value.lower()
    if value in {"si", "sí"}:
        return True
    if value == "no":
        return False
    _fail(field_.line, f"el nibble '{field_.value}' debe ser si, sí o no.")
    raise AssertionError


def _header_norm(cells: list[str]) -> list[str]:
    return [" ".join(cell.lower().split()) for cell in cells]


def _expect_header(section: _Section, mode: str) -> None:
    assert section.header is not None
    norm = _header_norm(section.header)
    line = section.header_line
    if mode in {"listado", "grupos"}:
        if norm != ["nombre", "hosts"]:
            _fail(line, "la tabla debe tener las columnas Nombre y Hosts.")
        return
    if mode == "dispositivos":
        if norm not in (["nombre", "hosts"], ["nombre", "dispositivos"]):
            _fail(line, "la tabla debe tener las columnas Nombre y Hosts (o Dispositivos).")
        return
    if norm != ["nombre"]:
        _fail(line, "en modo fijo la tabla solo admite la columna Nombre.")


def _section_requests(section: _Section, mode: str) -> tuple[HostRequest, ...]:
    if section.header is None:
        return ()
    _expect_header(section, mode)
    width = len(section.header)
    requests: list[HostRequest] = []
    for lineno, cells in section.rows:
        if cells and all(not cell.strip() for cell in cells):
            continue
        if len(cells) != width:
            _fail(lineno, f"la fila tiene {len(cells)} columnas y el encabezado tiene {width}.")
        name = cells[0].strip()
        if "|" in name:
            _fail(lineno, f"el nombre '{name}' no puede contener '|'.")
        if not name:
            _fail(lineno, "el nombre de la subred no puede estar vacío.")
        raw_hosts = cells[1].strip()
        if not re.fullmatch(r"\d+", raw_hosts):
            _fail(lineno, f"el valor de hosts '{raw_hosts}' no es un entero.")
        hosts = int(raw_hosts)
        if hosts < 1:
            _fail(lineno, f"la subred '{name}' requiere al menos 1 host/dispositivo.")
        requests.append(HostRequest(name=name, hosts=hosts, original_index=len(requests)))
    return tuple(requests)


def _fail_mix(sections: list[_Section]) -> None:
    sub_lines = [section.line for section in sections if section.name == "Subredes"]
    other_lines = [section.line for section in sections if section.name != "Subredes"]
    if other_lines:
        line = max(min(sub_lines), min(other_lines))
    else:
        line = sub_lines[1]
    _fail(line, "no se puede mezclar el listado (## Subredes) con grupos.")


def _subnet_section(sections: list[_Section], mode: str) -> tuple[HostRequest, ...]:
    if not any(section.name == "Subredes" for section in sections):
        _fail(1, f"el modo {mode} necesita la sección ## Subredes.")
    if len(sections) != 1:
        _fail_mix(sections)
    section = sections[0]
    requests = _section_requests(section, mode)
    if not requests:
        _fail(section.line, "la sección ## Subredes no tiene subredes.")
    return requests


def _groups(sections: list[_Section]) -> tuple[tuple[str, tuple[HostRequest, ...]], ...]:
    has_subredes = any(section.name == "Subredes" for section in sections)
    if has_subredes and len(sections) == 1:
        _fail(
            sections[0].line,
            "el modo grupos necesita un título ## por grupo, no una sola sección ## Subredes.",
        )
    if has_subredes:
        _fail_mix(sections)

    groups: list[tuple[str, tuple[HostRequest, ...]]] = []
    for section in sections:
        requests = _section_requests(section, "grupos")
        if not requests:
            _fail(section.line, f"el grupo '{section.name}' no tiene subredes.")
        groups.append((section.name, requests))
    if not 2 <= len(groups) <= 12:
        if not sections:
            line = 1
        elif len(sections) > 12:
            line = sections[12].line
        else:
            line = sections[0].line
        _fail(line, "el modo grupos admite entre 2 y 12 grupos.")
    return tuple(groups)


def _fixed_names(sections: list[_Section], *, count_line: int | None) -> tuple[str, ...]:
    if not sections:
        return ()
    has_subredes = any(section.name == "Subredes" for section in sections)
    if not has_subredes:
        _fail(sections[0].line, "en modo fijo la única sección válida es ## Subredes.")
    if len(sections) != 1:
        _fail_mix(sections)
    section = sections[0]
    if count_line is not None:
        _fail(
            max(count_line, section.line),
            "en modo fijo use Cantidad o la tabla ## Subredes, no las dos.",
        )
    if section.header is None:
        _fail(section.line, "la sección ## Subredes no tiene nombres.")
    _expect_header(section, "fijo")
    names: list[str] = []
    width = len(section.header)
    for lineno, cells in section.rows:
        if cells and all(not cell.strip() for cell in cells):
            continue
        if len(cells) != width:
            _fail(lineno, f"la fila tiene {len(cells)} columnas y el encabezado tiene {width}.")
        name = cells[0].strip()
        if "|" in name:
            _fail(lineno, f"el nombre '{name}' no puede contener '|'.")
        if not name:
            _fail(lineno, "el nombre de la subred no puede estar vacío.")
        names.append(name)
    if not names:
        _fail(section.line, "la sección ## Subredes no tiene nombres.")
    return tuple(names)
