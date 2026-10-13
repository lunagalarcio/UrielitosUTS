"""Feature Engineering municipal (>=25 variables)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.utils.helpers import get_logger

log = get_logger(__name__)

FEATURE_COLS: list[str] = []  # se llena en build_features()


def _slope(y: np.ndarray) -> float:
    """Pendiente de tendencia lineal (mínimos cuadrados)."""
    y = np.asarray(y, dtype=float)
    if len(y) < 2 or np.all(y == y[0]):
        return 0.0
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0])


def build_features(sismos: pd.DataFrame | None = None, master: pd.DataFrame | None = None) -> pd.DataFrame:
    """Genera la matriz de features por municipio y la guarda en data/processed.

    Incluye sismicidad, temporalidad, exposición poblacional, vulnerabilidad
    e índices compuestos. Mínimo 25 variables.
    """
    sismos = sismos if sismos is not None else pd.read_csv(config.SISMOS_CLEAN, parse_dates=["fecha"])
    master = master if master is not None else pd.read_csv(config.MUNICIPIOS_MASTER)
    sismos["fecha"] = pd.to_datetime(sismos["fecha"], errors="coerce")
    sismos = sismos.dropna(subset=["fecha"]).copy()
    sismos["anio"] = sismos["fecha"].dt.year
    now = int(sismos["anio"].max())
    anios_span = max(int(sismos["anio"].max() - sismos["anio"].min() + 1), 1)

    rows: list[dict] = []
    grouped = sismos.groupby("mpio")
    for _, m in master.iterrows():
        name, code = m["municipio"], m["cod_mpio"]
        g = grouped.get_group(name) if name in grouped.groups else sismos.iloc[0:0]
        n = len(g)
        mag = g["mag"].to_numpy() if n else np.array([0.0])
        prof = g["prof_km"].to_numpy() if n else np.array([0.0])
        counts_year = g.groupby("anio").size()
        last10 = g[g["anio"] >= now - 10]
        last5 = g[g["anio"] >= now - 5]
        last2 = g[g["anio"] >= now - 2]
        yearly = np.array([counts_year.get(y, 0) for y in range(now - 9, now + 1)], dtype=float)
        first_half = yearly[:5].sum()
        crecimiento = ((yearly[5:].sum() - first_half) / first_half) if first_half > 0 else float(yearly[5:].sum() > 0)
        energia = float(np.sum(10.0 ** (1.5 * np.clip(mag, 0, 9))) if n else 0.0)
        pob = float(m.get("poblacion_actual", 0) or 0)
        pob_fut = float(m.get("poblacion_proyectada", pob) or pob)
        em_tot = float(m.get("emergencias_totales", 0) or 0)
        em_sis = float(m.get("emergencias_sismicas", 0) or 0)
        fallec = float(m.get("fallecidos", 0) or 0)
        her = float(m.get("heridos", 0) or 0)
        pers = float(m.get("personas_afectadas", 0) or 0)
        row = {
            "cod_mpio": code, "municipio": name,
            # --- sismicidad básica (8)
            "cantidad_total_sismos": n,
            "magnitud_promedio": float(mag.mean()) if n else 0.0,
            "magnitud_maxima": float(mag.max()) if n else 0.0,
            "magnitud_minima": float(mag.min()) if n else 0.0,
            "magnitud_std": float(mag.std()) if n > 1 else 0.0,
            "pct_sismos_mag_mayor_4": float((mag >= 4.0).mean()) if n else 0.0,
            "pct_sismos_mag_mayor_5": float((mag >= 5.0).mean()) if n else 0.0,
            "energia_sismica_acum": energia,
            # --- profundidad (5)
            "profundidad_promedio": float(prof.mean()) if n else 0.0,
            "profundidad_maxima": float(prof.max()) if n else 0.0,
            "profundidad_minima": float(prof.min()) if n else 0.0,
            "profundidad_std": float(prof.std()) if n > 1 else 0.0,
            "pct_sismos_superficiales": float((prof < 50).mean()) if n else 0.0,
            # --- temporalidad (6)
            "frecuencia_sismica_anual": n / anios_span,
            "sismos_ultimos_10_anios": int(len(last10)),
            "sismos_ultimos_5_anios": int(len(last5)),
            "sismos_ultimos_2_anios": int(len(last2)),
            "tendencia_sismica": _slope(yearly),
            "crecimiento_frecuencia_sismica": float(np.clip(crecimiento, -5, 5)),
            # --- exposición / población (4)
            "poblacion_actual": pob,
            "poblacion_proyectada": pob_fut,
            "crecimiento_poblacional": float(m.get("crecimiento_poblacional", 0) or 0),
            "log_poblacion": float(np.log1p(pob)),
            # --- emergencias / vulnerabilidad (6)
            "emergencias_totales": em_tot,
            "emergencias_sismicas": em_sis,
            "emergencias_por_anio": em_tot / 7.0,
            "fallecidos": fallec,
            "heridos": her,
            "personas_afectadas": pers,
            # --- geo (2)
            "lat_mpio": float(m.get("lat_mpio", 0) or 0),
            "lon_mpio": float(m.get("lon_mpio", 0) or 0),
        }
        rows.append(row)

    feat = pd.DataFrame(rows)
    # --- Índices compuestos (normalizados 0-1 con min-max robusto)
    def _mm(s: pd.Series) -> pd.Series:
        lo, hi = s.quantile(0.02), s.quantile(0.98)
        if hi <= lo:
            return pd.Series(0.0, index=s.index)
        return ((s.clip(lo, hi) - lo) / (hi - lo)).fillna(0)

    feat["idx_actividad"] = (0.45 * _mm(np.log1p(feat["cantidad_total_sismos"]))
                             + 0.25 * _mm(feat["magnitud_maxima"])
                             + 0.15 * _mm(np.log1p(feat["sismos_ultimos_5_anios"]))
                             + 0.15 * _mm(feat["pct_sismos_mag_mayor_4"]))
    feat["indice_exposicion"] = (0.6 * _mm(feat["log_poblacion"])
                                 + 0.25 * _mm(np.log1p(feat["personas_afectadas"]))
                                 + 0.15 * _mm(np.log1p(feat["poblacion_proyectada"]))).clip(0, 1)
    feat["indice_vulnerabilidad"] = (0.4 * _mm(np.log1p(feat["emergencias_totales"]))
                                     + 0.25 * _mm(feat["pct_sismos_superficiales"])
                                     + 0.2 * _mm(np.log1p(feat["fallecidos"] + feat["heridos"]))
                                     + 0.15 * _mm(feat["crecimiento_poblacional"].clip(0))).clip(0, 1)
    feat["indice_riesgo"] = (0.5 * feat["idx_actividad"]
                             + 0.3 * feat["indice_exposicion"]
                             + 0.2 * feat["indice_vulnerabilidad"]).clip(0, 1)
    global FEATURE_COLS
    FEATURE_COLS = [c for c in feat.columns if c not in ("cod_mpio", "municipio")]
    feat.to_csv(config.FEATURES, index=False)
    log.info("Features: %d municipios x %d variables", len(feat), len(FEATURE_COLS))
    return feat


def load_features() -> tuple[pd.DataFrame, list[str]]:
    """Carga la matriz de features y la lista de columnas numéricas."""
    feat = pd.read_csv(config.FEATURES)
    cols = [c for c in feat.columns if c not in ("cod_mpio", "municipio")]
    return feat, cols
