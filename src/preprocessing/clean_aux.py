"""Limpieza de DIVIPOLA, proyección de población DANE y emergencias UNGRD."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from src import config
from src.utils.helpers import get_logger, norm_name_space, pad_divipola
from src.utils.validation import validate

log = get_logger(__name__)


# ---------------------------------------------------------------- DIVIPOLA
def clean_divipola(path: str | None = None) -> pd.DataFrame:
    """Lee DIVIPOLA, normaliza códigos/coordenadas y filtra Santander (dpto 68)."""
    df = pd.read_csv(path or config.DIVIPOLA, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]
    rename = {"cod_dpto": "cod_dpto", "dpto": "dpto", "cod_mpio": "cod_mpio",
              "nom_mpio": "nom_mpio", "longitud": "longitud", "latitud": "latitud"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["cod_dpto"] = df["cod_dpto"].astype(str).str.extract(r"(\d+)")[0].str.zfill(2)
    df["cod_mpio"] = df["cod_mpio"].astype(str).str.extract(r"(\d+)")[0].apply(pad_divipola)
    # Coordenadas con coma decimal
    for c in ["longitud", "latitud"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["dpto_norm"] = df["dpto"].map(norm_name_space)
    df["nom_norm"] = df["nom_mpio"].map(norm_name_space)
    sant = df[df["cod_dpto"] == config.COD_DPTO_SANTANDER].copy()
    if sant.empty:  # fallback por nombre si el código viene distinto
        sant = df[df["dpto_norm"] == config.DEPTO_SANTANDER].copy()
    validate(sant, "divipola_santander", required=["cod_mpio", "nom_mpio"])
    log.info("DIVIPOLA Santander: %d municipios", len(sant))
    return sant.reset_index(drop=True)


# ---------------------------------------------------------------- POBLACIÓN
def _find_header_row(raw: pd.DataFrame) -> int | None:
    """Busca la fila de encabezado real (contiene DPTO/MUNICIPIO/AÑO)."""
    for i in range(min(15, len(raw))):
        row = " ".join(str(v) for v in raw.iloc[i].tolist()).upper()
        if ("MUNICIPIO" in row or "MPIO" in row) and ("2020" in row or "POBLACI" in row or "AÑO" in row or "ANO" in row):
            return i
    return None


def clean_poblacion(path: str | None = None) -> pd.DataFrame:
    """Parser del Excel DANE 2020-2035 (formato largo: DP/DPNOM/MPIO/DPMP/AÑO/ÁREA/Población).

    Devuelve: cod_mpio, municipio, poblacion_actual (2024), poblacion_proyectada (2035),
    crecimiento_poblacional.
    """
    import unicodedata as _ud

    path = path or config.POBLACION_XLSX
    try:
        raw = pd.read_excel(path, sheet_name=0, header=None, engine="openpyxl")
    except Exception as exc:
        log.error("No se pudo leer Excel de población: %s", exc)
        raise

    def _plain(v: object) -> str:
        s = str(v).strip().upper()
        s = "".join(c for c in _ud.normalize("NFKD", s) if not _ud.combining(c))
        return s

    header_idx = None
    for i in range(min(15, len(raw))):
        cells = [_plain(v) for v in raw.iloc[i].tolist()]
        joined = " ".join(cells)
        if "DPNOM" in joined and "MPIO" in joined and "POBLACI" in joined:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("No se encontró fila de encabezado en el Excel de población DANE")
    header = [_plain(v) for v in raw.iloc[header_idx].tolist()]
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")
    col_dpto = next((c for c in df.columns if "DPNOM" in c), None)
    col_mpio_cod = next((c for c in df.columns if c == "MPIO"), None)
    col_nombre = next((c for c in df.columns if "DPMP" in c), None)
    col_anio = next((c for c in df.columns if c in ("ANO", "AÑO", "A\u00d1O")), None)
    col_area = next((c for c in df.columns if "AREA" in c), None)
    col_pob = next((c for c in df.columns if "POBLACI" in c), None)
    if not all([col_dpto, col_mpio_cod, col_anio, col_pob]):
        raise ValueError(f"Columnas inesperadas en Excel DANE: {list(df.columns)}")
    if col_area:
        df = df[df[col_area].map(_plain).str.contains("TOTAL", na=False)]
    df = df[df[col_dpto].map(_plain).str.strip().eq("SANTANDER")]
    df["_anio"] = pd.to_numeric(df[col_anio], errors="coerce")
    df["_pob"] = pd.to_numeric(df[col_pob], errors="coerce")
    df = df.dropna(subset=["_anio", "_pob"])
    df["cod_mpio"] = df[col_mpio_cod].astype(str).str.extract(r"(\d{2,5})")[0].apply(pad_divipola)
    df["municipio"] = df[col_nombre].map(norm_name_space) if col_nombre else df["cod_mpio"]
    pivot = df.pivot_table(index=["cod_mpio", "municipio"], columns="_anio", values="_pob",
                           aggfunc="sum").reset_index()
    years = sorted([c for c in pivot.columns if isinstance(c, (int, float))])
    if not years:
        raise ValueError("Sin años pivoteados en Excel DANE")
    actual_year = max([int(y) for y in years if int(y) <= config.ANIO_CORTE], default=int(years[0]))
    last_year = int(max(years))
    first_year = int(min(years))
    pivot["poblacion_actual"] = pd.to_numeric(pivot[actual_year], errors="coerce")
    pivot["poblacion_proyectada"] = pd.to_numeric(pivot[last_year], errors="coerce")
    base = pd.to_numeric(pivot[first_year], errors="coerce").replace(0, np.nan)
    pivot["crecimiento_poblacional"] = ((pivot["poblacion_proyectada"] - base) / base).fillna(0).clip(-1, 5)
    pivot["anio_actual_ref"] = actual_year
    out = pivot[["cod_mpio", "municipio", "poblacion_actual", "poblacion_proyectada",
                 "crecimiento_poblacional", "anio_actual_ref"]].copy()
    validate(out, "poblacion_santander", required=["municipio", "poblacion_actual"])
    log.info("Población: %d municipios | actual=%d proy=%d", len(out), actual_year, last_year)
    return out


# ---------------------------------------------------------------- EMERGENCIAS
def _clean_emergencias_one(path: str | Path, divipola_col: str, fecha_col: str = "fecha") -> pd.DataFrame:
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]
    dcol = next((c for c in df.columns if divipola_col in c or "divipola" in c), None)
    df["cod_mpio"] = df[dcol].apply(pad_divipola) if dcol else ""
    dep = next((c for c in df.columns if "departamento" in c or "dpto" in c), None)
    mun = next((c for c in df.columns if "municipio" in c), None)
    df["dpto_norm"] = df[dep].map(norm_name_space) if dep else ""
    df["mpio_norm"] = df[mun].map(norm_name_space) if mun else ""
    df["fecha"] = pd.to_datetime(df.get(fecha_col), errors="coerce")
    df["anio"] = df["fecha"].dt.year
    ev = next((c for c in df.columns if "evento" in c), None)
    df["evento"] = df[ev].astype(str).str.upper().str.strip() if ev else "DESCONOCIDO"
    for c in ["fallecidos", "muertos", "heridos", "desapa", "desaparecidos", "personas", "familias"]:
        col = next((k for k in df.columns if k.startswith(c[:6])), None)
        if col:
            df[col] = pd.to_numeric(df[col].astype(str).str.extract(r"(-?\d+)")[0], errors="coerce").fillna(0)
    df["fallecidos_n"] = pd.to_numeric(df.get("fallecidos", df.get("muertos", 0)), errors="coerce").fillna(0)
    df["heridos_n"] = pd.to_numeric(df.get("heridos", 0), errors="coerce").fillna(0)
    df["personas_n"] = pd.to_numeric(df.get("personas", 0), errors="coerce").fillna(0)
    df["es_sismico"] = df["evento"].str.contains("SISMO|TERREMOTO|MOVIMIENTO TELURICO|TELURICO", na=False)
    return df


def clean_emergencias() -> pd.DataFrame:
    """Une UNGRD 2019-2024 + 2025 y filtra Santander."""
    from pathlib import Path as _P  # noqa: F401  (tipado laxo aceptado)
    a = _clean_emergencias_one(config.EMERG_2019_2024, "divipola")
    b = _clean_emergencias_one(config.EMERG_2025, "codificaci")
    cols = ["fecha", "anio", "dpto_norm", "mpio_norm", "cod_mpio", "evento",
            "fallecidos_n", "heridos_n", "personas_n", "es_sismico"]
    emerg = pd.concat([a[[c for c in cols if c in a.columns]],
                       b[[c for c in cols if c in b.columns]]], ignore_index=True)
    emerg = emerg[(emerg["dpto_norm"] == config.DEPTO_SANTANDER)
                  | emerg["cod_mpio"].str.startswith(config.COD_DPTO_SANTANDER)].copy()
    validate(emerg, "emergencias_santander", required=["fecha", "mpio_norm"])
    log.info("Emergencias Santander: %d registros (%d sísmicos)", len(emerg), int(emerg["es_sismico"].sum()))
    return emerg.reset_index(drop=True)
