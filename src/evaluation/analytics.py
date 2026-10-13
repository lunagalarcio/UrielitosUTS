"""Analítica descriptiva + insights automáticos."""
from __future__ import annotations

import pandas as pd

from src import config
from src.utils.helpers import get_logger, save_json

log = get_logger(__name__)


def build_analytics() -> dict:
    """Genera Top-10 riesgo/RL, estadísticas generales e insights. Guarda JSON."""
    feat = pd.read_csv(config.FEATURES)
    labels = pd.read_csv(config.LABELS) if config.LABELS.exists() else None
    ranking = pd.read_csv(config.RANKING_RL) if config.RANKING_RL.exists() else None
    sismos = pd.read_csv(config.SISMOS_CLEAN, parse_dates=["fecha"]) if config.SISMOS_CLEAN.exists() else None

    top_riesgo = feat.nlargest(10, "indice_riesgo")[["municipio", "indice_riesgo", "cantidad_total_sismos",
                                                     "magnitud_maxima", "poblacion_actual"]].to_dict("records")
    top_rl = (ranking.head(10)[["puesto", "municipio", "score_rl_100", "indice_riesgo"]].to_dict("records")
              if ranking is not None else [])
    stats = {
        "n_municipios": int(len(feat)),
        "n_sismos": int(feat["cantidad_total_sismos"].sum()),
        "magnitud_max_dpto": float(feat["magnitud_maxima"].max()),
        "magnitud_prom_dpto": round(float(sismos["mag"].mean()), 3) if sismos is not None else None,
        "profundidad_prom_dpto": round(float(sismos["prof_km"].mean()), 1) if sismos is not None else None,
        "pct_superficiales": round(float((sismos["prof_km"] < 50).mean() * 100), 1) if sismos is not None else None,
        "poblacion_total": int(feat["poblacion_actual"].sum()),
        "emergencias_totales": int(feat["emergencias_totales"].sum()),
        "distribucion_riesgo": labels["riesgo"].value_counts().to_dict() if labels is not None else {},
    }
    if sismos is not None and len(sismos):
        por_anio = sismos.groupby(sismos["fecha"].dt.year).size()
        stats["anio_mas_activo"] = int(por_anio.idxmax())
        stats["sismos_anio_mas_activo"] = int(por_anio.max())
        stats["sismos_ultimos_5_anios_pct"] = round(
            float((sismos["fecha"].dt.year >= sismos["fecha"].dt.year.max() - 5).mean() * 100), 1)

    insights = generar_insights(feat, sismos, labels)
    payload = {"estadisticas": stats, "top10_riesgo": top_riesgo, "top10_rl": top_rl, "insights": insights}
    save_json(payload, config.ANALITICA_JSON)
    save_json({"insights": insights}, config.INSIGHTS_JSON)
    log.info("Analítica: %d insights generados", len(insights))
    return payload


def generar_insights(feat: pd.DataFrame, sismos: pd.DataFrame | None,
                     labels: pd.DataFrame | None) -> list[str]:
    """Reglas interpretables sobre los datos (sin hardcodear conclusiones)."""
    out: list[str] = []
    total = feat["cantidad_total_sismos"].sum()
    top1 = feat.nlargest(1, "cantidad_total_sismos").iloc[0]
    out.append(f"{top1['municipio'].title()} concentra {top1['cantidad_total_sismos']:,} sismos "
               f"({top1['cantidad_total_sismos'] / max(total, 1):.1%} del total departamental), "
               f"lo que lo ubica como el epicentro instrumental de Santander.")
    # Nido sísmico de Bucaramanga
    nido = feat[feat["municipio"].isin(config.NIDO_BUCARAMANGA)]
    if len(nido):
        prom_nido = nido["frecuencia_sismica_anual"].mean()
        prom_dpto = feat["frecuencia_sismica_anual"].mean()
        ratio = prom_nido / max(prom_dpto, 1e-9)
        out.append(f"Los municipios del área de influencia del Nido Sísmico de Bucaramanga "
                   f"({', '.join(n.title() for n in nido.nlargest(5, 'cantidad_total_sismos')['municipio'])}) "
                   f"presentan una frecuencia sísmica {ratio:.1f}x superior al promedio departamental "
                   f"({prom_nido:.0f} vs {prom_dpto:.0f} sismos/año).")
    # Profundidad
    if sismos is not None and len(sismos):
        sup = (sismos["prof_km"] < 50).mean() * 100
        out.append(f"El {sup:.1f}% de los sismos es superficial (<50 km); estos eventos, aunque menos frecuentes, "
                   f"representan la mayor amenaza para infraestructura por su cercanía a la superficie.")
        fuerte = sismos[sismos["mag"] >= 5.0]
        if len(fuerte):
            out.append(f"Se registran {len(fuerte)} sismos de magnitud ≥5.0 en el periodo; "
                       f"la magnitud máxima instrumental es {sismos['mag'].max():.1f} Ml/Mw.")
    # Riesgo vs población
    alto = feat.nlargest(5, "indice_riesgo")
    out.append(f"Los 5 municipios con mayor índice de riesgo son "
               f"{', '.join(f'{r.municipio.title()} ({r.indice_riesgo:.2f})' for _, r in alto.iterrows())}; "
               f"combinar sismicidad con exposición poblacional cambia el orden frente al conteo de sismos puro.")
    exp = feat.nlargest(3, "personas_afectadas")
    if exp["personas_afectadas"].sum() > 0:
        out.append(f"En vulnerabilidad histórica destacan "
                   f"{', '.join(f'{r.municipio.title()} ({int(r.personas_afectadas):,} personas afectadas)' for _, r in exp.iterrows())}, "
                   f"donde la gestión del riesgo debe priorizar respuesta y recuperación.")
    ten = feat[feat["tendencia_sismica"] > feat["tendencia_sismica"].quantile(0.9)]
    if len(ten):
        out.append(f"{len(ten)} municipios muestran tendencia sísmica creciente en la última década "
                   f"(ej. {', '.join(t.title() for t in ten.nlargest(3, 'tendencia_sismica')['municipio'])}); "
                   f"se recomienda monitoreo instrumental reforzado.")
    if labels is not None:
        d = labels["riesgo"].value_counts().to_dict()
        out.append(f"Clasificación final: {d.get('Alto', 0)} municipios en riesgo Alto, "
                   f"{d.get('Medio', 0)} en Medio y {d.get('Bajo', 0)} en Bajo, "
                   f"sobre {len(labels)} municipios evaluados de Santander.")
    return out
