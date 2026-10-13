"""Validación y reporte de calidad de datos."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.utils.helpers import get_logger

log = get_logger(__name__)


@dataclass
class ValidationReport:
    """Reporte de validación de un DataFrame."""

    name: str
    n_rows: int = 0
    n_cols: int = 0
    null_pct: dict[str, float] = field(default_factory=dict)
    dup_rows: int = 0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dataset": self.name,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "dup_rows": self.dup_rows,
            "null_pct": {k: round(v, 2) for k, v in self.null_pct.items() if v > 0},
            "issues": self.issues,
        }


def validate(
    df: pd.DataFrame,
    name: str,
    required: list[str] | None = None,
    numeric_ranges: dict[str, tuple[float, float]] | None = None,
) -> ValidationReport:
    """Valida nulos, duplicados, columnas requeridas y rangos numéricos."""
    rep = ValidationReport(name=name, n_rows=int(len(df)), n_cols=int(df.shape[1]))
    if len(df):
        rep.null_pct = (df.isna().mean() * 100).to_dict()
        rep.dup_rows = int(df.duplicated().sum())
    else:
        rep.issues.append("DataFrame vacío")
    for col in required or []:
        if col not in df.columns:
            rep.issues.append(f"Falta columna requerida: {col}")
        elif df[col].isna().mean() > 0.5:
            rep.issues.append(f"Columna {col} con >50% nulos ({df[col].isna().mean():.1%})")
    for col, (lo, hi) in (numeric_ranges or {}).items():
        if col in df.columns:
            bad = ((df[col] < lo) | (df[col] > hi)).sum()
            if bad:
                rep.issues.append(f"{col}: {bad} valores fuera de [{lo}, {hi}]")
    if rep.dup_rows:
        rep.issues.append(f"{rep.dup_rows} filas duplicadas exactas")
    log.info("%s: %d filas x %d cols | %d issues", name, rep.n_rows, rep.n_cols, len(rep.issues))
    for issue in rep.issues:
        log.warning("  - %s: %s", name, issue)
    return rep
