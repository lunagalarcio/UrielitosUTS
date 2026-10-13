"""Limpieza del catálogo sísmico SGC (1993-2018 y 2018-hoy) -> catálogo unificado Santander."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.utils.helpers import get_logger, norm_name_space, norm_text
from src.utils.validation import validate

log = get_logger(__name__)

# Columnas canónicas de salida
COLS = ["fecha", "lat", "lon", "prof_km", "mag", "depto", "mpio_raw", "fuente"]


def _clean_1993_2018(path: str | None = None) -> pd.DataFrame:
    """Lee y normaliza el catálogo SGC 1993-2018."""
    df = pd.read_csv(path or config.SGC_1993_2018, sep=None, engine="python")
    rename = {
        "FECHA": "fecha",
        "LATITUD (grados)": "lat",
        "LONGITUD (grados)": "lon",
        "PROFUNDIDAD (Km)": "prof_km",
        "DEPARTAMENTO": "depto",
        "MUNICIPIO": "mpio_raw",
    }
    df = df.rename(columns=rename)
    # Magnitud: preferir Mw, si no Ml
    mag_mw = pd.to_numeric(df.get("MAGNITUD Mw"), errors="coerce")
    mag_ml = pd.to_numeric(df.get("MAGNITUD Ml"), errors="coerce")
    df["mag"] = mag_mw.fillna(mag_ml)
    if "HORA_UTC" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["HORA_UTC"].astype(str), errors="coerce")
    else:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    for c in ["lat", "lon", "prof_km"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["depto"] = df["depto"].map(norm_name_space)
    df["mpio_raw"] = df["mpio_raw"].map(norm_text)
    df["fuente"] = "SGC_1993_2018"
    return df[[c for c in COLS if c in df.columns]].copy()


def _split_region(region: str) -> tuple[str, str]:
    """'Los Santos - Santander, Colombia' -> (LOS_SANTOS, SANTANDER)."""
    if not region or not isinstance(region, str):
        return "", ""
    head = region.split(",")[0]
    parts = [p.strip() for p in head.split("-")]
    if len(parts) >= 2:
        return norm_text(parts[0]), norm_name_space(parts[1])
    return norm_text(head), ""


def _clean_2018_hoy(path: str | None = None) -> pd.DataFrame:
    """Lee y normaliza el catálogo SGC 2018-hoy."""
    df = pd.read_csv(path or config.SGC_2018_HOY, sep=None, engine="python")
    df = df.rename(columns={"fecha_hora_utc": "fecha", "lat": "lat", "lon": "lon",
                             "prof_km": "prof_km", "mag": "mag"})
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    for c in ["lat", "lon", "prof_km", "mag"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    parsed = df.get("region", pd.Series([""] * len(df))).map(_split_region)
    df["mpio_raw"] = [p[0] for p in parsed]
    df["depto"] = [p[1] for p in parsed]
    df["fuente"] = "SGC_2018_HOY"
    return df[[c for c in COLS]].copy()


def _asignar_mpio_espacial(sismos: pd.DataFrame, divipola: pd.DataFrame) -> pd.DataFrame:
    """Reasigna municipio por cercanía haversiana cuando el nombre no matchea DIVIPOLA.

    Solo actúa sobre filas cuyo mpio no existe en DIVIPOLA Santander o está vacío,
    usando coordenadas del centroide municipal. Vectorizado con numpy.
    """
    ref = divipola.dropna(subset=["latitud", "longitud"]).copy()
    valid = set(ref["nom_norm"].tolist())
    mask = ~sismos["mpio_raw"].isin(valid) | sismos["mpio_raw"].eq("")
    if not mask.any() or ref.empty:
        return sismos
    log.info("Reasignación espacial de %d eventos sin match nominal", int(mask.sum()))
    rlat = np.radians(ref["latitud"].to_numpy())
    rlon = np.radians(ref["longitud"].to_numpy())
    qlat = np.radians(sismos.loc[mask, "lat"].to_numpy())
    qlon = np.radians(sismos.loc[mask, "lon"].to_numpy())
    # Haversine por bloques para no explotar memoria
    names = ref["nom_norm"].to_numpy()
    best_idx = np.zeros(mask.sum(), dtype=int)
    best_dist = np.full(mask.sum(), np.inf)
    block = 5000
    R = 6371.0
    q = np.stack([qlat, qlon], axis=1)
    for i in range(0, len(ref), block):
        blat, blon = rlat[i:i + block], rlon[i:i + block]
        dlat = q[:, 0, None] - blat[None, :]
        dlon = q[:, 1, None] - blon[None, :]
        a = np.sin(dlat / 2) ** 2 + np.cos(q[:, 0, None]) * np.cos(blat[None, :]) * np.sin(dlon / 2) ** 2
        dist = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        j = dist.argmin(axis=1)
        dmin = dist[np.arange(len(q)), j]
        upd = dmin < best_dist
        best_dist[upd] = dmin[upd]
        best_idx[upd] = j[upd] + i
    sismos.loc[mask, "mpio_raw"] = names[best_idx]
    sismos.loc[mask, "mpio_espacial"] = True
    return sismos


def clean_sgc(divipola_santander: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pipeline completo SGC: une, limpia, filtra Santander y deduplica.

    Args:
        divipola_santander: DataFrame DIVIPOLA filtrado a Santander (para join espacial).

    Returns:
        Catálogo unificado con columnas fecha, lat, lon, prof_km, mag, depto, mpio, fuente.
    """
    try:
        a = _clean_1993_2018()
        b = _clean_2018_hoy()
    except FileNotFoundError as exc:
        log.error("Archivo SGC no encontrado: %s", exc)
        raise
    sismos = pd.concat([a, b], ignore_index=True)
    sismos["mpio_espacial"] = False
    # Limpieza de rangos físicos
    n0 = len(sismos)
    sismos = sismos.dropna(subset=["fecha", "lat", "lon", "mag"])
    sismos = sismos[(sismos["mag"] >= 0) & (sismos["mag"] <= 9)]
    sismos = sismos[(sismos["lat"] >= 4) & (sismos["lat"] <= 10)
                    & (sismos["lon"] >= -76) & (sismos["lon"] <= -71)]
    sismos["prof_km"] = sismos["prof_km"].clip(0, 700)
    # Santander: por depto declarado O por bounding box del dpto (5.7-8.2, -74.6--72.4)
    in_box = (sismos["lat"].between(5.4, 8.4)) & (sismos["lon"].between(-74.9, -72.2))
    sismos = sismos[(sismos["depto"] == config.DEPTO_SANTANDER) | (in_box & sismos["depto"].eq(""))].copy()
    # Fallback: si el filtro deja muy poco, usar solo bounding box
    if len(sismos) < 10_000:
        log.warning("Filtro Santander dejó %d filas; usando bounding box amplio", len(sismos))
        full = pd.concat([a, b], ignore_index=True)
        full["mpio_espacial"] = False
        full = full.dropna(subset=["fecha", "lat", "lon", "mag"])
        sismos = full[(full["lat"].between(5.4, 8.4)) & (full["lon"].between(-74.9, -72.2))].copy()
        sismos["prof_km"] = sismos["prof_km"].clip(0, 700)
    if divipola_santander is not None and len(divipola_santander):
        sismos["mpio_raw"] = sismos["mpio_raw"].fillna("")
        sismos = _asignar_mpio_espacial(sismos, divipola_santander)
    sismos = sismos.rename(columns={"mpio_raw": "mpio"})
    # Deduplicación: mismo minuto + misma posición redondeada + misma mag
    sismos["dedup_key"] = (
        sismos["fecha"].dt.strftime("%Y%m%d%H%M") + sismos["lat"].round(3).astype(str)
        + sismos["lon"].round(3).astype(str) + sismos["mag"].round(1).astype(str)
    )
    sismos = sismos.sort_values("fecha").drop_duplicates("dedup_key").drop(columns="dedup_key")
    validate(sismos, "sismos_limpios", required=["fecha", "lat", "lon", "mag", "mpio"],
             numeric_ranges={"mag": (0, 9), "prof_km": (0, 700)})
    log.info("SGC: %d -> %d eventos (Santander + área de influencia)", n0, len(sismos))
    return sismos.reset_index(drop=True)
