"""Serialización de resultados a CSV, JSON y Markdown (consumo local)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pandas as pd

from core.models import ExportResult, MultiVLSMResult


def result_to_dataframe(result: ExportResult) -> pd.DataFrame:
    if isinstance(result, MultiVLSMResult):
        rows = []
        for group in result.groups:
            for item in group.result.subnets:
                row = item.to_row()
                row["Grupo"] = group.name
                rows.append(row)
        return pd.DataFrame(rows)
    rows = [item.to_row() for item in result.subnets]
    return pd.DataFrame(rows)


def steps_to_dataframe(result: ExportResult) -> pd.DataFrame:
    return pd.DataFrame([step.to_row() for step in result.steps])


def to_csv(result: ExportResult) -> str:
    buffer = StringIO()
    result_to_dataframe(result).to_csv(buffer, index=False)
    buffer.write("\n\n# Memoria de cálculo\n")
    steps_to_dataframe(result).to_csv(buffer, index=False)
    return buffer.getvalue()


def to_json(result: ExportResult) -> str:
    payload: dict[str, Any] = result.to_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def to_markdown(result: ExportResult) -> str:
    lines: list[str] = [
        f"# Plan de direccionamiento {result.protocol}",
        "",
        f"- **Bloque base:** `{result.base_cidr}`",
        f"- **Generado:** {result.generated_at}",
        f"- **Subredes:** {result.subnet_count}",
        "",
        "## Resumen",
        "",
        "| Métrica | Valor | Detalle |",
        "| --- | --- | --- |",
    ]
    for label, value, hint in result.summary_metrics():
        lines.append(f"| {label} | {value} | {hint} |")

    lines += ["", "## Subredes asignadas", ""]
    frame = result_to_dataframe(result)
    if frame.empty:
        lines.append("_Sin subredes._")
    else:
        lines.append(_markdown_table(frame))

    lines += ["", "## Memoria de cálculo", ""]
    steps = steps_to_dataframe(result)
    if not steps.empty:
        lines.append(_markdown_table(steps))

    if result.notes:
        lines += ["", "## Notas", ""]
        lines.extend(f"- {note}" for note in result.notes)

    leftover = result.leftover_cidrs
    lines += ["", "## Espacio sobrante", ""]
    if leftover:
        lines.extend(f"- `{cidr}`" for cidr in leftover)
    else:
        lines.append("- Ninguno")
    lines.append("")
    return "\n".join(lines)


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(col) for col in frame.columns]
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for _, row in frame.iterrows():
        cells = [_escape_cell(row[col]) for col in frame.columns]
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body])


def _escape_cell(value: Any) -> str:
    text = "—" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")
