"""Interfaz web de Slicer, calculadora de subredes IPv4 e IPv6."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from core.excel_exporter import build_workbook, workbook_to_bytes
from core.md_input import LabInput, parse
from core.models import (
    ExportResult,
    HostRequest,
    InsufficientAddressSpaceError,
    IPv4Subnet,
    IPv6Result,
    IPv6Subnet,
    MultiVLSMResult,
    VLSMError,
    VLSMResult,
)
from core.reports import result_to_dataframe, to_csv, to_json, to_markdown
from core.subnet_v6 import calculate_ipv6
from core.vlsm_v4 import calculate_vlsm_grouped, calculate_vlsm_v4

st.set_page_config(
    page_title="Slicer",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS_PATH = Path(__file__).resolve().parent / "assets" / "app.css"
_SIN_RESULTADO = "No hay resultado. Revisa la pestaña Calculadora."
_COLUMNAS_TEXTO = (
    "Red",
    "Máscara decimal",
    "CIDR",
    "Primera IP útil",
    "Última IP útil",
    "Broadcast",
)
_COLUMNAS_NUMERO = ("Hosts asignados (útiles)", "Desperdicio (hosts)")


def _inject_css() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _consumir_toast() -> None:
    """Muestra el aviso pendiente una sola vez y lo retira."""
    texto = st.session_state.pop("_toast", None)
    if texto:
        st.toast(str(texto))


def _marcar_toast(texto: str) -> None:
    """Deja el texto del toast para el arranque del siguiente run."""
    st.session_state["_toast"] = texto


def _reiniciar_formulario() -> None:
    """Vacía el formulario. No borra el .md: si no, se volvería a aplicar."""
    claves = (
        "v4_cidr",
        "v4_layout",
        "v4_input_order",
        "v4_group_count",
        "v4_group_prefix_on",
        "v4_group_prefix",
        "_v4_list_seed",
        "v6_cidr",
        "v6_mode",
        "v6_prefix",
        "v6_count",
        "v6_named",
        "v6_nibble",
        "_v6_names_seed",
        "_v6_hosts_seed",
        "v4_result",
        "v6_result",
    )
    for clave in claves:
        st.session_state.pop(clave, None)
    for indice in range(12):
        st.session_state.pop(f"v4_gname_{indice}", None)
        st.session_state.pop(f"_v4_seed_{indice}", None)
    st.session_state["v4_editor_rev"] = int(st.session_state.get("v4_editor_rev", 0)) + 1
    st.session_state["v6_editor_rev"] = int(st.session_state.get("v6_editor_rev", 0)) + 1
    _marcar_toast("Formulario reiniciado")


def _default_v4_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nombre": ["LAN-Usuarios", "Servidores", "Voz", "IoT", "Enlace-WAN"],
            "Hosts": [100, 50, 25, 12, 2],
        }
    )


def _second_v4_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nombre": ["Piso-2", "Impresoras", "Enlace"],
            "Hosts": [40, 8, 2],
        }
    )


def _blank_v4_table() -> pd.DataFrame:
    return pd.DataFrame({"Nombre": [""], "Hosts": [None]})


def _table_from_pairs(pairs: list[tuple[str, int]]) -> pd.DataFrame:
    return pd.DataFrame({"Nombre": [name for name, _ in pairs], "Hosts": [hosts for _, hosts in pairs]})


def _default_v6_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nombre": ["VLAN-Datos", "VLAN-Voz", "VLAN-IoT", "P2P-Core"],
            "Dispositivos": [500, 80, 40, 2],
        }
    )


def _parse_table(frame: pd.DataFrame, value_col: str) -> list[HostRequest]:
    requests: list[HostRequest] = []
    for index, row in frame.iterrows():
        name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        raw = row.iloc[1] if len(row) > 1 else None
        if not name or name.lower() in {"nan", "none"}:
            continue
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        hosts = int(raw)
        requests.append(HostRequest(name=name, hosts=hosts, original_index=int(index)))
    if not requests:
        raise VLSMError(f"Agregue al menos una fila con nombre y {value_col}.")
    return requests


def _config_editor_v4() -> dict:
    # TextColumn de esta versión no tiene placeholder; el ejemplo va en la ayuda.
    return {
        "Nombre": st.column_config.TextColumn(
            "Nombre de subred",
            required=True,
            help="Ej. LAN-Usuarios",
        ),
        "Hosts": st.column_config.NumberColumn(
            "Hosts necesarios",
            min_value=1,
            step=1,
            required=True,
        ),
    }


def _editor_v4(seed: pd.DataFrame, key: str) -> pd.DataFrame:
    return st.data_editor(
        seed,
        num_rows="dynamic",
        use_container_width=True,
        column_config=_config_editor_v4(),
        key=key,
    )


def _cargar_ejemplo_listado() -> None:
    """Siembra el listado de ejemplo y deja el toast para el siguiente run."""
    st.session_state["_v4_list_seed"] = _default_v4_table()
    st.session_state["v4_editor_rev"] = int(st.session_state.get("v4_editor_rev", 0)) + 1
    _marcar_toast("Ejemplo cargado")


def _cargar_ejemplo_grupos() -> None:
    """Siembra dos grupos de ejemplo. No carga el laboratorio Tendencias."""
    st.session_state["_v4_seed_0"] = _default_v4_table()
    st.session_state["_v4_seed_1"] = _second_v4_table()
    st.session_state["v4_gname_0"] = "Edificio 1"
    st.session_state["v4_gname_1"] = "Edificio 2"
    st.session_state["v4_group_count"] = 2
    st.session_state["v4_editor_rev"] = int(st.session_state.get("v4_editor_rev", 0)) + 1
    for indice in range(2, 12):
        st.session_state.pop(f"v4_gname_{indice}", None)
        st.session_state.pop(f"_v4_seed_{indice}", None)
    _marcar_toast("Ejemplo cargado")


def _banda_eficiencia(pct: float) -> str:
    """Semáforo de eficiencia: más de 85 verde, desde 60 ámbar, si no rojo."""
    if pct > 85:
        return "ok"
    if pct >= 60:
        return "mid"
    return "bad"


def _banda_desperdicio(pct: float) -> str:
    """Semáforo de desperdicio: menos de 15 verde, hasta 40 ámbar, si no rojo."""
    if pct < 15:
        return "ok"
    if pct <= 40:
        return "mid"
    return "bad"


def _clase_metrica(result: ExportResult, etiqueta: str) -> str:
    """Color según el campo numérico. Un desperdicio alto no se pinta de verde."""
    if etiqueta == "Eficiencia de hosts" and isinstance(result, (VLSMResult, MultiVLSMResult)):
        return _banda_eficiencia(result.host_efficiency_pct)
    if etiqueta == "Desperdicio global" and isinstance(result, VLSMResult):
        return _banda_desperdicio(result.waste_pct)
    return ""


def _clase_barra_uso(result: ExportResult) -> str:
    """Semáforo de ocupación. En IPv6 de prefijo fijo la barra queda neutra."""
    if isinstance(result, IPv6Result) and result.mode != "hosts":
        return ""
    return _banda_eficiencia(result.space_efficiency_pct)


def _hero(protocol: str) -> None:
    if protocol == "IPv4":
        variant = "hero--ipv4"
        kicker, title, blurb = (
            "Slicer · IPv4",
            "Subdivisión de redes IPv4",
            "Por defecto las solicitudes se ordenan de mayor a menor. Puedes respetar el orden de la tabla. Cada bloque usa la máscara más pequeña que cubre hosts + 2.",
        )
    else:
        variant = "hero--ipv6"
        kicker, title, blurb = (
            "Slicer · IPv6",
            "Subdivisión y delegación IPv6",
            "Prefijos fijos (/64, /127) o bits de interfaz por dispositivos. Anycast de router = IID todo cero.",
        )
    st.markdown(
        f"""
        <section class="hero {variant}">
          <span class="hero-kicker">{escape(kicker)}</span>
          <h1>{escape(title)}</h1>
          <p>{escape(blurb)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _metrics(result: ExportResult) -> None:
    cards = result.summary_metrics()
    parts = []
    for label, value, hint in cards:
        clase = _clase_metrica(result, label)
        extra = f" {clase}" if clase else ""
        parts.append(
            f"""<article class="metric-card{extra}">
              <span class="metric-label">{escape(label)}</span>
              <strong class="metric-value">{escape(str(value))}</strong>
              <span class="metric-hint">{escape(hint)}</span>
            </article>"""
        )
    st.markdown(f'<div class="metric-grid">{"".join(parts)}</div>', unsafe_allow_html=True)


def _barra_uso(result: ExportResult) -> None:
    """Barra de uso del bloque con el porcentaje del modelo, ancho entre 0 y 100."""
    ancho = max(0.0, min(float(result.space_efficiency_pct), 100.0))
    clase = _clase_barra_uso(result)
    extra = f" {clase}" if clase else ""
    st.markdown(
        (
            '<div class="usage">'
            '<div class="usage-head">'
            '<span class="metric-label">Uso del bloque</span>'
            f'<span class="usage-pct">{result.space_efficiency_pct:.1f}%</span>'
            "</div>"
            f'<div class="usage-track"><i class="usage-fill{extra}" style="width:{ancho:.6f}%"></i></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _subnet_cards_v4(subnets: list[IPv4Subnet], title: str = "Subredes asignadas") -> None:
    parts = []
    for subnet in subnets:
        chip = _banda_eficiencia(subnet.efficiency_pct)
        width = max(0.0, min(subnet.efficiency_pct, 100.0))
        parts.append(
            f"""<article class="subnet-card">
              <div class="subnet-head">
                <h3>{escape(subnet.name)}</h3>
                <span class="chip pfx">/{subnet.prefixlen}</span>
              </div>
              <dl class="kv">
                <div><dt>Red</dt><dd>{escape(subnet.network)}</dd></div>
                <div><dt>Máscara</dt><dd>{escape(subnet.netmask)}</dd></div>
                <div><dt>Primera útil</dt><dd>{escape(subnet.first_usable)}</dd></div>
                <div><dt>Última útil</dt><dd>{escape(subnet.last_usable)}</dd></div>
                <div><dt>Broadcast</dt><dd>{escape(subnet.broadcast)}</dd></div>
                <div><dt>Wildcard</dt><dd>{escape(subnet.wildcard)}</dd></div>
                <div><dt>Hosts</dt><dd>{subnet.requested_hosts} → {subnet.assigned_usable}</dd></div>
                <div><dt>Salto</dt><dd>{subnet.jump_decimal} ({escape(subnet.jump_hex)})</dd></div>
              </dl>
              <div class="eff">
                <span class="chip {chip}">{subnet.efficiency_pct:.1f}% eficiente</span>
                <div class="eff-track"><i class="eff-fill {chip}" style="width:{width:.1f}%"></i></div>
              </div>
            </article>"""
        )
    st.markdown(
        f'<div class="section-title">{escape(title)}</div>'
        f'<div class="subnet-grid">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def _subnet_cards_v6(subnets: list[IPv6Subnet]) -> None:
    parts = []
    for subnet in subnets:
        parts.append(
            f"""<article class="subnet-card">
              <div class="subnet-head">
                <h3>{escape(subnet.name)}</h3>
                <span class="chip pfx">/{subnet.prefixlen}</span>
              </div>
              <dl class="kv">
                <div><dt>CIDR</dt><dd>{escape(subnet.compressed)}</dd></div>
                <div><dt>Anycast</dt><dd>{escape(subnet.router_anycast)}</dd></div>
                <div><dt>Primera</dt><dd>{escape(subnet.first_assignable)}</dd></div>
                <div><dt>Última</dt><dd>{escape(subnet.last_assignable)}</dd></div>
                <div><dt>Expandido</dt><dd>{escape(subnet.expanded)}</dd></div>
                <div><dt>IID bits</dt><dd>{subnet.interface_bits}</dd></div>
              </dl>
            </article>"""
        )
    st.markdown(
        '<div class="section-title">Prefijos delegados</div>'
        f'<div class="subnet-grid">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def _config_tabla(frame: pd.DataFrame) -> dict:
    """Solo columnas que existen, con el tipo real del dataframe."""
    config: dict = {}
    for nombre in _COLUMNAS_TEXTO:
        if nombre in frame.columns:
            config[nombre] = st.column_config.TextColumn(nombre)
    for nombre in _COLUMNAS_NUMERO:
        if nombre not in frame.columns:
            continue
        if pd.api.types.is_numeric_dtype(frame[nombre]):
            config[nombre] = st.column_config.NumberColumn(nombre)
        else:
            config[nombre] = st.column_config.TextColumn(nombre)
    return config


def _tabla_principal(result: ExportResult) -> None:
    frame = result_to_dataframe(result)
    orden = list(frame.columns)
    if "Red" in orden and "CIDR" in orden:
        orden.remove("CIDR")
        orden.insert(orden.index("Red") + 1, "CIDR")
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        column_config=_config_tabla(frame),
        column_order=orden,
    )


def _tarjetas_subred(result: ExportResult) -> None:
    if isinstance(result, MultiVLSMResult):
        for group in result.groups:
            _subnet_cards_v4(group.result.subnets, f"{group.name} · {group.container.cidr}")
        return
    if isinstance(result, IPv6Result):
        _subnet_cards_v6(result.subnets)
        return
    _subnet_cards_v4(result.subnets)


def _memoria(result: ExportResult) -> None:
    with st.expander("Memoria de cálculo", expanded=False):
        st.dataframe(
            pd.DataFrame([step.to_row() for step in result.steps]),
            use_container_width=True,
            hide_index=True,
        )
    if result.notes:
        st.info("  ·  ".join(result.notes))


def _downloads(result: ExportResult, stem: str) -> None:
    xlsx = workbook_to_bytes(build_workbook(result))
    csv_data = to_csv(result)
    json_data = to_json(result)
    md_data = to_markdown(result)
    st.caption("Descarga el reporte en este equipo.")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.download_button(
        "Excel",
        data=xlsx,
        file_name=f"{stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
    col_b.download_button(
        "CSV",
        data=csv_data.encode("utf-8"),
        file_name=f"{stem}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    col_c.download_button(
        "JSON",
        data=json_data.encode("utf-8"),
        file_name=f"{stem}.json",
        mime="application/json",
        use_container_width=True,
    )
    col_d.download_button(
        "Markdown",
        data=md_data.encode("utf-8"),
        file_name=f"{stem}.md",
        mime="text/markdown",
        use_container_width=True,
    )


def _filas_diagrama_v4(result: ExportResult) -> pd.DataFrame:
    filas: list[dict[str, object]] = []
    if isinstance(result, MultiVLSMResult):
        for grupo in result.groups:
            for subred in grupo.result.subnets:
                filas.append(
                    {
                        "Nombre": f"{grupo.name} · {subred.name}",
                        "Tamaño": int(subred.block_size),
                        "Tipo": "Asignado",
                    }
                )
    else:
        for subred in result.subnets:
            filas.append(
                {
                    "Nombre": subred.name,
                    "Tamaño": int(subred.block_size),
                    "Tipo": "Asignado",
                }
            )
    filas.append(
        {
            "Nombre": "Libre",
            "Tamaño": int(result.leftover_addresses),
            "Tipo": "Libre",
        }
    )
    return pd.DataFrame(filas)


def _diagrama_v4(result: ExportResult) -> alt.Chart:
    """Barras horizontales por subred y una fila Libre del bloque padre."""
    frame = _filas_diagrama_v4(result)
    altura = max(160, 28 * len(frame) + 36)
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            y=alt.Y("Nombre:N", sort=None, title=""),
            x=alt.X("Tamaño:Q", title="Tamaño de bloque", stack=None),
            color=alt.Color(
                "Tipo:N",
                scale=alt.Scale(domain=["Asignado", "Libre"], range=["#1B4F8A", "#8F8474"]),
                legend=alt.Legend(title=""),
            ),
            tooltip=[
                alt.Tooltip("Nombre:N", title="Nombre"),
                alt.Tooltip("Tamaño:Q", title="Tamaño"),
            ],
        )
        .properties(height=altura)
        .configure(background="#FFFEFB")
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=False,
            labelColor="#3F3A33",
            titleColor="#5C564C",
            domainColor="#D6D1C7",
            tickColor="#D6D1C7",
            labelFont="IBM Plex Sans",
            titleFont="IBM Plex Sans",
        )
        .configure_legend(labelColor="#3F3A33", labelFont="IBM Plex Sans")
    )


def _diagrama_v6(result: IPv6Result) -> alt.Chart:
    """Una barra de ocupación 0–100. El porcentaje pequeño es el dato real."""
    usado = float(result.space_efficiency_pct)
    libre = max(0.0, 100.0 - usado)
    frame = pd.DataFrame(
        {
            "Bloque": ["Ocupación", "Ocupación"],
            "Tipo": ["Asignado", "Libre"],
            "Porcentaje": [usado, libre],
        }
    )
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            y=alt.Y("Bloque:N", title=""),
            x=alt.X(
                "Porcentaje:Q",
                title="Porcentaje",
                stack="zero",
                scale=alt.Scale(domain=[0, 100]),
            ),
            color=alt.Color(
                "Tipo:N",
                scale=alt.Scale(domain=["Asignado", "Libre"], range=["#0F6E6B", "#8F8474"]),
                legend=alt.Legend(title=""),
            ),
            tooltip=[
                alt.Tooltip("Tipo:N", title="Parte"),
                alt.Tooltip("Porcentaje:Q", title="Porcentaje", format=".4f"),
            ],
        )
        .properties(height=120)
        .configure(background="#FFFEFB")
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=False,
            labelColor="#3F3A33",
            titleColor="#5C564C",
            domainColor="#D6D1C7",
            tickColor="#D6D1C7",
            labelFont="IBM Plex Sans",
            titleFont="IBM Plex Sans",
        )
        .configure_legend(labelColor="#3F3A33", labelFont="IBM Plex Sans")
    )


def _diagrama(result: ExportResult) -> alt.Chart:
    """Elige el diagrama horizontal según el protocolo del resultado."""
    if isinstance(result, IPv6Result):
        return _diagrama_v6(result)
    return _diagrama_v4(result)


def _resolver_calculo(clave: str, accion: Callable[[], ExportResult]) -> ExportResult | None:
    """Corre el motor. La falta de espacio avisa en warning; el resto, en error."""
    try:
        resultado = accion()
    except InsufficientAddressSpaceError as exc:
        st.session_state.pop(clave, None)
        st.warning(str(exc))
        return None
    except (VLSMError, ValueError) as exc:
        st.session_state.pop(clave, None)
        st.error(str(exc))
        return None
    st.session_state[clave] = resultado
    return resultado


def _aviso_sin_resultado() -> None:
    st.caption(_SIN_RESULTADO)


def _apply_lab_spec(lab: LabInput) -> None:
    """Escribe el laboratorio en session_state. No calcula."""
    st.session_state["protocol"] = lab.protocol
    if lab.mode == "listado":
        st.session_state["v4_layout"] = "Un listado"
        st.session_state["v4_cidr"] = lab.cidr
        st.session_state["v4_input_order"] = lab.input_order
        st.session_state["v4_editor_rev"] = int(st.session_state.get("v4_editor_rev", 0)) + 1
        st.session_state["_v4_list_seed"] = _table_from_pairs([(item.name, item.hosts) for item in lab.requests])
        for index in range(12):
            st.session_state.pop(f"v4_gname_{index}", None)
            st.session_state.pop(f"_v4_seed_{index}", None)
        return
    if lab.mode == "grupos":
        st.session_state["v4_layout"] = "Varios grupos (una hoja)"
        st.session_state["v4_cidr"] = lab.cidr
        st.session_state["v4_group_count"] = len(lab.groups)
        st.session_state["v4_group_prefix_on"] = lab.group_prefix is not None
        if lab.group_prefix is not None:
            st.session_state["v4_group_prefix"] = lab.group_prefix
        st.session_state["v4_input_order"] = lab.input_order
        st.session_state["v4_editor_rev"] = int(st.session_state.get("v4_editor_rev", 0)) + 1
        for index, (name, reqs) in enumerate(lab.groups):
            st.session_state[f"v4_gname_{index}"] = name
            st.session_state[f"_v4_seed_{index}"] = _table_from_pairs([(item.name, item.hosts) for item in reqs])
        for index in range(len(lab.groups), 12):
            st.session_state.pop(f"v4_gname_{index}", None)
            st.session_state.pop(f"_v4_seed_{index}", None)
        return
    if lab.mode == "fijo":
        st.session_state["v6_cidr"] = lab.cidr
        st.session_state["v6_mode"] = "Prefijo fijo (Prefix Delegation)"
        if lab.target_prefix is not None:
            st.session_state["v6_prefix"] = lab.target_prefix
        st.session_state["v6_count"] = 8 if lab.count is None else lab.count
        st.session_state["v6_named"] = bool(lab.names)
        st.session_state["v6_editor_rev"] = int(st.session_state.get("v6_editor_rev", 0)) + 1
        if lab.names:
            st.session_state["_v6_names_seed"] = pd.DataFrame(
                {"Nombre": list(lab.names), "Dispositivos": [0] * len(lab.names)}
            )
        else:
            st.session_state.pop("_v6_names_seed", None)
        for index in range(12):
            st.session_state.pop(f"v4_gname_{index}", None)
            st.session_state.pop(f"_v4_seed_{index}", None)
        return
    st.session_state["v6_cidr"] = lab.cidr
    st.session_state["v6_mode"] = "Por requerimiento de dispositivos"
    st.session_state["v6_nibble"] = lab.nibble_align
    st.session_state["v6_editor_rev"] = int(st.session_state.get("v6_editor_rev", 0)) + 1
    st.session_state["_v6_hosts_seed"] = pd.DataFrame(
        {
            "Nombre": [item.name for item in lab.requests],
            "Dispositivos": [item.hosts for item in lab.requests],
        }
    )
    for index in range(12):
        st.session_state.pop(f"v4_gname_{index}", None)
        st.session_state.pop(f"_v4_seed_{index}", None)


def _apply_tendencias() -> None:
    path = Path(__file__).parent / "examples" / "tendencias.md"
    _apply_lab_spec(parse(path.read_text(encoding="utf-8-sig")))
    _marcar_toast("Laboratorio Tendencias cargado")


def _ingest_lab_markdown(uploaded) -> None:
    if uploaded is None:
        return
    raw = uploaded.getvalue()
    size = uploaded.size if getattr(uploaded, "size", None) is not None else len(raw)
    token = (uploaded.name, size, hashlib.sha256(raw).hexdigest())
    if token == st.session_state.get("lab_md_token"):
        return
    try:
        lab = parse(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        st.sidebar.error("El archivo no está en UTF-8.")
        return
    except VLSMError as exc:
        st.sidebar.error(str(exc))
        return
    _apply_lab_spec(lab)
    st.session_state["lab_md_token"] = token
    _marcar_toast("Laboratorio cargado")
    st.rerun()


def _sembrar_v4(indice: int) -> pd.DataFrame:
    seed = st.session_state.pop(f"_v4_seed_{indice}", None)
    if seed is not None:
        return seed
    if indice == 0:
        return _default_v4_table()
    if indice == 1:
        return _second_v4_table()
    return _blank_v4_table()


def render_ipv4() -> None:
    _hero("IPv4")
    st.session_state.setdefault("v4_cidr", "192.168.10.0/24")
    st.session_state.setdefault("v4_editor_rev", 0)
    st.session_state.setdefault("v4_group_count", 2)
    st.session_state.setdefault("v4_group_prefix_on", False)
    st.session_state.setdefault("v4_group_prefix", 23)
    st.session_state.setdefault("v4_input_order", False)

    tab_calc, tab_res, tab_diag, tab_exp = st.tabs(
        ["Calculadora", "Resultados", "Diagrama del bloque", "Exportar"]
    )
    result: ExportResult | None = None
    stem = "slicer-ipv4"

    with tab_calc:
        layout = st.radio(
            "Hoja Excel",
            options=["Un listado", "Varios grupos (una hoja)"],
            horizontal=True,
            key="v4_layout",
            help="Varios grupos apila edificios o sedes en una sola hoja, como el laboratorio Tendencias.",
        )
        if layout.startswith("Varios"):
            cidr = st.text_input("Bloque base CIDR", placeholder="10.0.0.0/16", key="v4_cidr")
            input_order = st.checkbox(
                "Respetar el orden de la tabla (no reordenar de mayor a menor)",
                key="v4_input_order",
                help="Útil en laboratorios donde Administración queda después de los /30.",
            )
            col_a, col_b, col_c = st.columns([1, 1, 1])
            n_groups = int(
                col_a.number_input("Cantidad de grupos", min_value=2, max_value=12, step=1, key="v4_group_count")
            )
            fixed = col_b.checkbox("Prefijo fijo por grupo", key="v4_group_prefix_on")
            group_prefix = None
            if fixed:
                group_prefix = int(
                    col_c.number_input("Prefijo de cada grupo", min_value=8, max_value=30, step=1, key="v4_group_prefix")
                )
            else:
                col_c.caption("El tamaño de cada contenedor se calcula según lo que pida el grupo.")
            btn_lab, btn_ej = st.columns(2)
            btn_lab.button(
                "Cargar laboratorio Tendencias",
                use_container_width=True,
                on_click=_apply_tendencias,
            )
            btn_ej.button(
                "Cargar ejemplo",
                use_container_width=True,
                on_click=_cargar_ejemplo_grupos,
            )
            st.caption("Excel: hoja «VLSM Por EDIFICIO» con una tabla por grupo.")

            groups: list[tuple[str, list[HostRequest]]] = []
            rev = st.session_state.v4_editor_rev
            for index in range(n_groups):
                st.session_state.setdefault(f"v4_gname_{index}", f"Edificio {index + 1}")
                seed = _sembrar_v4(index)
                with st.expander(st.session_state[f"v4_gname_{index}"], expanded=index == 0):
                    name = st.text_input("Nombre del grupo", key=f"v4_gname_{index}")
                    editor = _editor_v4(seed, f"v4_geditor_{index}_{rev}")
                    try:
                        groups.append((name, _parse_table(pd.DataFrame(editor), "hosts")))
                    except VLSMError:
                        continue

            def _calcular_grupos() -> ExportResult:
                if len(groups) < 2:
                    raise VLSMError("Complete al menos dos grupos con nombre y hosts para generar una hoja.")
                return calculate_vlsm_grouped(
                    cidr,
                    groups,
                    group_prefix=group_prefix,
                    sort_largest_first=not input_order,
                )

            result = _resolver_calculo("v4_result", _calcular_grupos)
            stem = "slicer-ipv4-grupos"
        else:
            izquierda, derecha = st.columns([1, 2])
            with izquierda:
                cidr = st.text_input("Bloque base CIDR", placeholder="10.0.0.0/16", key="v4_cidr")
                input_order = st.checkbox(
                    "Respetar el orden de la tabla (no reordenar de mayor a menor)",
                    key="v4_input_order",
                    help="Útil en laboratorios donde Administración queda después de los /30.",
                )
                st.button("Cargar ejemplo", on_click=_cargar_ejemplo_listado, use_container_width=True)
            with derecha:
                rev = st.session_state.v4_editor_rev
                seed = st.session_state.pop("_v4_list_seed", None)
                if seed is None:
                    seed = _default_v4_table()
                editor = _editor_v4(seed, f"v4_editor_{rev}")
            st.caption("El cálculo se actualiza al cambiar el CIDR o la tabla.")

            def _calcular_listado() -> ExportResult:
                requests = _parse_table(pd.DataFrame(editor), "hosts")
                return calculate_vlsm_v4(cidr, requests, sort_largest_first=not input_order)

            result = _resolver_calculo("v4_result", _calcular_listado)
            stem = "slicer-ipv4"

    with tab_res:
        if result is None:
            _aviso_sin_resultado()
        else:
            _metrics(result)
            _barra_uso(result)
            _tabla_principal(result)
            _tarjetas_subred(result)
            _memoria(result)
    with tab_diag:
        if result is None:
            _aviso_sin_resultado()
        else:
            st.altair_chart(_diagrama(result), use_container_width=True)
    with tab_exp:
        if result is None:
            _aviso_sin_resultado()
        else:
            _downloads(result, stem)


def render_ipv6() -> None:
    _hero("IPv6")
    st.session_state.setdefault("v6_cidr", "2001:db8:abcd::/48")
    st.session_state.setdefault("v6_mode", "Prefijo fijo (Prefix Delegation)")
    st.session_state.setdefault("v6_prefix", 64)
    st.session_state.setdefault("v6_count", 8)
    st.session_state.setdefault("v6_named", False)
    st.session_state.setdefault("v6_nibble", False)
    st.session_state.setdefault("v6_editor_rev", 0)

    tab_calc, tab_res, tab_diag, tab_exp = st.tabs(
        ["Calculadora", "Resultados", "Diagrama del bloque", "Exportar"]
    )
    result: ExportResult | None = None

    with tab_calc:
        cidr = st.text_input("Prefijo base CIDR", placeholder="fd12:3456:789a::/56", key="v6_cidr")
        mode_label = st.radio(
            "Modo de subdivisión",
            options=["Prefijo fijo (Prefix Delegation)", "Por requerimiento de dispositivos"],
            horizontal=True,
            key="v6_mode",
        )
        rev = int(st.session_state.v6_editor_rev)
        if mode_label.startswith("Prefijo fijo"):
            col_a, col_b = st.columns(2)
            target_prefix = int(col_a.number_input("Prefijo hijo", min_value=1, max_value=128, step=1, key="v6_prefix"))
            count = int(col_b.number_input("Cantidad a listar", min_value=1, max_value=4096, step=1, key="v6_count"))
            st.caption("Prueba /64 para VLAN o /127 para enlaces p2p.")
            named = st.checkbox("Nombrar subredes (en lugar de Subred-00, Subred-01…)", key="v6_named")
            editor = None
            if named:
                seed = st.session_state.pop("_v6_names_seed", None)
                if seed is None:
                    seed = pd.DataFrame(
                        {"Nombre": [f"VLAN-{i:02d}" for i in range(1, 5)], "Dispositivos": [0, 0, 0, 0]}
                    )
                editor = st.data_editor(
                    seed,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "Nombre": st.column_config.TextColumn(
                            "Nombre",
                            help="Ej. LAN-Usuarios",
                        ),
                    },
                    key=f"v6_fixed_names_{rev}",
                )

            def _calcular_fijo() -> ExportResult:
                names = None
                if editor is not None:
                    frame = pd.DataFrame(editor)
                    names = [str(v).strip() for v in frame.iloc[:, 0].tolist() if str(v).strip() not in {"", "nan"}]
                return calculate_ipv6(
                    cidr,
                    mode="fixed",
                    target_prefix=target_prefix,
                    count=None if names else count,
                    names=names,
                )

            result = _resolver_calculo("v6_result", _calcular_fijo)
        else:
            nibble = st.checkbox("Alinear prefijos a nibble (múltiplo de 4, RFC 5375)", key="v6_nibble")
            seed = st.session_state.pop("_v6_hosts_seed", None)
            if seed is None:
                seed = _default_v6_table()
            editor = st.data_editor(
                seed,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "Nombre": st.column_config.TextColumn(
                        "Nombre del segmento",
                        required=True,
                        help="Ej. LAN-Usuarios",
                    ),
                    "Dispositivos": st.column_config.NumberColumn(
                        "Dispositivos / direcciones",
                        min_value=1,
                        step=1,
                        required=True,
                    ),
                },
                key=f"v6_hosts_editor_{rev}",
            )

            def _calcular_hosts() -> ExportResult:
                requests = _parse_table(pd.DataFrame(editor), "dispositivos")
                return calculate_ipv6(cidr, mode="hosts", requests=requests, nibble_align=nibble)

            result = _resolver_calculo("v6_result", _calcular_hosts)

    with tab_res:
        if result is None:
            _aviso_sin_resultado()
        else:
            _metrics(result)
            _barra_uso(result)
            _tabla_principal(result)
            _tarjetas_subred(result)
            _memoria(result)
    with tab_diag:
        if result is None:
            _aviso_sin_resultado()
        else:
            st.altair_chart(_diagrama(result), use_container_width=True)
    with tab_exp:
        if result is None:
            _aviso_sin_resultado()
        else:
            _downloads(result, "slicer-ipv6")


def main() -> None:
    _consumir_toast()
    _inject_css()
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
              <h2>Slicer</h2>
              <p>Subredes IPv4 e IPv6</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()
        uploaded = st.file_uploader("Laboratorio (.md)", type=["md"], key="lab_md_file")
        _ingest_lab_markdown(uploaded)
        with st.expander("Cómo usarlo"):
            st.markdown(
                "- Carga un laboratorio (.md).\n"
                "- Elige el protocolo.\n"
                "- Llena la tabla.\n"
                "- Revisa Resultados, Diagrama del bloque y Exportar."
            )
        st.session_state.setdefault("protocol", "IPv4")
        protocol = st.radio("Protocolo", options=["IPv4", "IPv6"], key="protocol")
        st.caption("🔒 Los reportes se generan en este equipo")
        st.button("Reiniciar", on_click=_reiniciar_formulario, use_container_width=True)

    if protocol == "IPv4":
        render_ipv4()
    else:
        render_ipv6()


if __name__ == "__main__":
    main()
