"""Terminal de Slicer para cálculos VLSM IPv4 e IPv6.

Ejemplos:
    python cli.py ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2 --excel plan.xlsx
    python cli.py ipv4 172.16.128.0/21 --group-prefix 23 --input-order \\
        -g 'Edificio 1=RRHH:66,Ventas:38,Compras:20,Server:4' \\
        -g 'Edificio 2=Operativa:66,Produccion:48,investigacion:10' --excel edificios.xlsx
    python cli.py ipv6 2001:db8:abcd::/48 --prefix 64 --count 8 --json plan.json
    python cli.py ipv6 fd00:1::/56 -s VLAN10:500 -s P2P:2 --nibble-align
"""

from __future__ import annotations

from pathlib import Path

import click

from core.excel_exporter import export_xlsx
from core.md_input import LabInput, parse
from core.models import ExportResult, HostRequest, VLSMError
from core.reports import result_to_dataframe, to_csv, to_json, to_markdown
from core.subnet_v6 import calculate_ipv6
from core.vlsm_v4 import calculate_vlsm_grouped, calculate_vlsm_v4


def _parse_named(values: tuple[str, ...]) -> list[HostRequest]:
    requests: list[HostRequest] = []
    for index, raw in enumerate(values):
        if ":" not in raw:
            raise click.BadParameter("Use el formato Nombre:cantidad (ej. LAN:100).")
        name, _, amount = raw.rpartition(":")
        name = name.strip()
        if not name:
            raise click.BadParameter(f"Nombre vacío en '{raw}'.")
        try:
            hosts = int(amount.strip())
        except ValueError as exc:
            raise click.BadParameter(f"Cantidad inválida en '{raw}'.") from exc
        requests.append(HostRequest(name=name, hosts=hosts, original_index=index))
    return requests


def _parse_group(raw: str) -> tuple[str, list[HostRequest]]:
    if "=" not in raw:
        raise click.BadParameter("Use Grupo=Nombre:hosts,Nombre:hosts (ej. Edificio 1=RRHH:66,Ventas:38).")
    title, _, body = raw.partition("=")
    title = title.strip()
    if not title or not body.strip():
        raise click.BadParameter(f"Grupo inválido: '{raw}'.")
    parts = tuple(item.strip() for item in body.split(",") if item.strip())
    return title, _parse_named(parts)


def _load_lab(path: str) -> LabInput:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise click.ClickException("El archivo no está en UTF-8.") from exc
    return parse(text)


def _emit(result: ExportResult, *, excel: str | None, csv_path: str | None, json_path: str | None, md_path: str | None) -> None:
    frame = result_to_dataframe(result)
    click.secho(f"\n{result.protocol}  {result.base_cidr}", fg="cyan", bold=True)
    click.echo(f"Generado: {result.generated_at}")
    click.echo("")
    for label, value, hint in result.summary_metrics():
        click.echo(f"  {label:28} {value:22}  {hint}")
    click.echo("")
    if not frame.empty:
        click.echo(frame.to_string(index=False))
    click.echo("")
    for note in result.notes:
        click.secho(f"  · {note}", fg="yellow")
    if excel:
        export_xlsx(result, excel)
        click.secho(f"Excel → {excel}", fg="green")
    if csv_path:
        Path(csv_path).write_text(to_csv(result), encoding="utf-8")
        click.secho(f"CSV   → {csv_path}", fg="green")
    if json_path:
        Path(json_path).write_text(to_json(result), encoding="utf-8")
        click.secho(f"JSON  → {json_path}", fg="green")
    if md_path:
        Path(md_path).write_text(to_markdown(result), encoding="utf-8")
        click.secho(f"MD    → {md_path}", fg="green")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version="1.0.0", prog_name="slicer")
def main() -> None:
    """Slicer — subredes IPv4 (VLSM) e IPv6."""


@main.command("ipv4")
@click.argument("network", required=False)
@click.option(
    "-s",
    "--subnet",
    "subnets",
    multiple=True,
    help="Subred en formato Nombre:hosts. Repetible.",
)
@click.option(
    "-g",
    "--group",
    "groups",
    multiple=True,
    help="Grupo en una hoja: 'Edificio 1=RRHH:66,Ventas:38'. Repetible.",
)
@click.option("--group-prefix", type=int, help="Prefijo fijo de cada grupo (ej. 23).")
@click.option("--input-order", is_flag=True, help="No reordenar por tamaño (orden de la tabla).")
@click.option("--excel", type=click.Path(dir_okay=False), help="Ruta del informe .xlsx")
@click.option("--csv", "csv_path", type=click.Path(dir_okay=False), help="Ruta CSV")
@click.option("--json", "json_path", type=click.Path(dir_okay=False), help="Ruta JSON")
@click.option("--md", "md_path", type=click.Path(dir_okay=False), help="Ruta Markdown")
@click.option(
    "--from-md",
    "from_md",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Markdown de entrada del laboratorio. No es el informe --md.",
)
@click.option("--relaxed", is_flag=True, help="Acepta hosts como dirección de red (canoniza el CIDR).")
def ipv4_cmd(
    network: str | None,
    subnets: tuple[str, ...],
    groups: tuple[str, ...],
    group_prefix: int | None,
    input_order: bool,
    excel: str | None,
    csv_path: str | None,
    json_path: str | None,
    md_path: str | None,
    from_md: str | None,
    relaxed: bool,
) -> None:
    """Calcula VLSM IPv4 sobre un CIDR o un laboratorio --from-md."""
    try:
        if from_md:
            if network or subnets or groups or group_prefix is not None or input_order:
                raise click.ClickException(
                    "Con --from-md no indique el CIDR ni -s, -g, --group-prefix o --input-order."
                )
            lab = _load_lab(from_md)
            if lab.protocol != "IPv4":
                raise click.ClickException("Este archivo es IPv6; use el comando ipv6.")
            if lab.mode == "listado":
                result = calculate_vlsm_v4(
                    lab.cidr,
                    list(lab.requests),
                    strict=not relaxed,
                    sort_largest_first=not lab.input_order,
                )
            elif lab.mode == "grupos":
                result = calculate_vlsm_grouped(
                    lab.cidr,
                    [(name, list(reqs)) for name, reqs in lab.groups],
                    group_prefix=lab.group_prefix,
                    sort_largest_first=not lab.input_order,
                    strict=not relaxed,
                )
            else:
                raise click.ClickException(f"El modo '{lab.mode}' no aplica a IPv4.")
        else:
            if not network:
                raise click.ClickException("Indique el CIDR o --from-md ARCHIVO.")
            if groups:
                parsed = [_parse_group(item) for item in groups]
                result = calculate_vlsm_grouped(
                    network,
                    parsed,
                    group_prefix=group_prefix,
                    sort_largest_first=not input_order,
                    strict=not relaxed,
                )
            else:
                if not subnets:
                    raise click.UsageError("Indique -s Nombre:hosts o varios -g 'Grupo=A:10,B:5'.")
                result = calculate_vlsm_v4(
                    network,
                    _parse_named(subnets),
                    strict=not relaxed,
                    sort_largest_first=not input_order,
                )
    except VLSMError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, excel=excel, csv_path=csv_path, json_path=json_path, md_path=md_path)


@main.command("ipv6")
@click.argument("network", required=False)
@click.option(
    "-s",
    "--subnet",
    "subnets",
    multiple=True,
    help="Segmento Nombre:dispositivos. Activa el modo por requerimiento.",
)
@click.option("--prefix", type=int, help="Prefijo hijo fijo (PD), ej. 64 o 127.")
@click.option("--count", type=int, help="Cuántas subredes fijas listar (por defecto 8).")
@click.option("--name", "names", multiple=True, help="Nombre de subred en modo PD fijo. Repetible.")
@click.option("--nibble-align/--no-nibble-align", default=False, help="Alinear a frontera de nibble.")
@click.option("--limit", type=int, default=4096, show_default=True, help="Tope de filas listadas.")
@click.option("--excel", type=click.Path(dir_okay=False), help="Ruta del informe .xlsx")
@click.option("--csv", "csv_path", type=click.Path(dir_okay=False), help="Ruta CSV")
@click.option("--json", "json_path", type=click.Path(dir_okay=False), help="Ruta JSON")
@click.option("--md", "md_path", type=click.Path(dir_okay=False), help="Ruta Markdown")
@click.option(
    "--from-md",
    "from_md",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Markdown de entrada del laboratorio. No es el informe --md.",
)
@click.option("--relaxed", is_flag=True, help="Canoniza el prefijo si no cae en frontera de red.")
def ipv6_cmd(
    network: str | None,
    subnets: tuple[str, ...],
    prefix: int | None,
    count: int | None,
    names: tuple[str, ...],
    nibble_align: bool,
    limit: int,
    excel: str | None,
    csv_path: str | None,
    json_path: str | None,
    md_path: str | None,
    from_md: str | None,
    relaxed: bool,
) -> None:
    """Calcula Prefix Delegation o subnetting IPv6 sobre un CIDR o un laboratorio --from-md."""
    try:
        if from_md:
            if network or subnets or prefix is not None or count is not None or names or nibble_align:
                raise click.ClickException(
                    "Con --from-md no indique el CIDR ni -s, --prefix, --count, --name o --nibble-align."
                )
            lab = _load_lab(from_md)
            if lab.protocol != "IPv6":
                raise click.ClickException("Este archivo es IPv4; use el comando ipv4.")
            if lab.mode == "fijo":
                fixed_names = list(lab.names) or None
                result = calculate_ipv6(
                    lab.cidr,
                    mode="fixed",
                    target_prefix=lab.target_prefix,
                    count=None if fixed_names else lab.count,
                    names=fixed_names,
                    limit=limit,
                    strict=not relaxed,
                )
            elif lab.mode == "dispositivos":
                result = calculate_ipv6(
                    lab.cidr,
                    mode="hosts",
                    requests=list(lab.requests),
                    nibble_align=lab.nibble_align,
                    limit=limit,
                    strict=not relaxed,
                )
            else:
                raise click.ClickException(f"El modo '{lab.mode}' no aplica a IPv6.")
        else:
            if not network:
                raise click.ClickException("Indique el CIDR o --from-md ARCHIVO.")
            if subnets:
                result = calculate_ipv6(
                    network,
                    mode="hosts",
                    requests=_parse_named(subnets),
                    nibble_align=nibble_align,
                    limit=limit,
                    strict=not relaxed,
                )
            else:
                if prefix is None:
                    raise click.UsageError("Indique --prefix para PD fijo o -s Nombre:N para modo por dispositivos.")
                result = calculate_ipv6(
                    network,
                    mode="fixed",
                    target_prefix=prefix,
                    count=count,
                    names=list(names) if names else None,
                    limit=limit,
                    strict=not relaxed,
                )
    except VLSMError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, excel=excel, csv_path=csv_path, json_path=json_path, md_path=md_path)


if __name__ == "__main__":
    main()
