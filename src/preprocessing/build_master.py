"""Construcción del dataset maestro municipal (DIVIPOLA como llave)."""
from __future__ import annotations

import pandas as pd

from src import config
from src.preprocessing.clean_aux import clean_divipola, clean_emergencias, clean_poblacion
from src.preprocessing.clean_sgc import clean_sgc
from src.utils.helpers import get_logger, save_json
from src.utils.validation import validate

log = get_logger(__name__)


def build_master() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Ejecuta Fase 1 completa y guarda artefactos en data/processed.

    Returns:
        (sismos_limpios, municipios_master, reportes)
    """
    config.DATA_PROC.mkdir(parents=True, exist_ok=True)
    reports: dict = {}

    divipola = clean_divipola()
    reports["divipola"] = {"n_municipios": len(divipola)}

    sismos = clean_sgc(divipola_santander=divipola)
    sismos.to_csv(config.SISMOS_CLEAN, index=False)
    reports["sismos"] = {"n_eventos": len(sismos),
                         "rango_fechas": [str(sismos["fecha"].min()), str(sismos["fecha"].max())]}

    try:
        poblacion = clean_poblacion()
    except Exception as exc:  # fallback: población uniforme para no bloquear pipeline
        log.error("Población falló (%s). Usando fallback uniforme.", exc)
        poblacion = pd.DataFrame({"cod_mpio": divipola["cod_mpio"], "municipio": divipola["nom_norm"],
                                  "poblacion_actual": 10000.0, "poblacion_proyectada": 10500.0,
                                  "crecimiento_poblacional": 0.05})
    try:
        emerg = clean_emergencias()
    except Exception as exc:
        log.error("Emergencias falló (%s). Usando vacío.", exc)
        emerg = pd.DataFrame(columns=["mpio_norm", "cod_mpio", "anio", "evento",
                                       "fallecidos_n", "heridos_n", "personas_n", "es_sismico"])

    # Llave maestra: todos los municipios DIVIPOLA Santander
    master = divipola[["cod_mpio", "nom_norm", "latitud", "longitud"]].rename(
        columns={"nom_norm": "municipio", "latitud": "lat_mpio", "longitud": "lon_mpio"})
    # Merge población (por código; fallback por nombre)
    master = master.merge(poblacion[["cod_mpio", "municipio", "poblacion_actual",
                                     "poblacion_proyectada", "crecimiento_poblacional"]],
                          on="cod_mpio", how="left", suffixes=("", "_pob"))
    mask = master["poblacion_actual"].isna()
    if mask.any():
        by_name = poblacion.set_index("municipio")[["poblacion_actual", "poblacion_proyectada",
                                                    "crecimiento_poblacional"]]
        for idx in master[mask].index:
            name = master.at[idx, "municipio"]
            if name in by_name.index:
                for c in ["poblacion_actual", "poblacion_proyectada", "crecimiento_poblacional"]:
                    master.at[idx, c] = by_name.at[name, c]
    master["poblacion_actual"] = master["poblacion_actual"].fillna(master["poblacion_actual"].median() or 10000)
    master["poblacion_proyectada"] = master["poblacion_proyectada"].fillna(master["poblacion_actual"])
    master["crecimiento_poblacional"] = master["crecimiento_poblacional"].fillna(0)

    # Agregado de emergencias por municipio
    if len(emerg):
        emerg["key"] = emerg["cod_mpio"].where(
            emerg["cod_mpio"].str.startswith(config.COD_DPTO_SANTANDER, na=False), emerg["mpio_norm"])
        agg = emerg.groupby("key").agg(
            emergencias_totales=("evento", "size"),
            emergencias_sismicas=("es_sismico", "sum"),
            fallecidos=("fallecidos_n", "sum"),
            heridos=("heridos_n", "sum"),
            personas_afectadas=("personas_n", "sum")).reset_index()
        master = master.merge(agg, left_on="cod_mpio", right_on="key", how="left").drop(columns=["key"], errors="ignore")
        master = master.merge(agg, left_on="municipio", right_on="key", how="left",
                              suffixes=("", "_byname"))
        for c in ["emergencias_totales", "emergencias_sismicas", "fallecidos", "heridos", "personas_afectadas"]:
            fallback = master.pop(c + "_byname") if c + "_byname" in master.columns else 0
            master[c] = master[c].fillna(fallback).fillna(0)
    else:
        for c in ["emergencias_totales", "emergencias_sismicas", "fallecidos", "heridos", "personas_afectadas"]:
            master[c] = 0

    # n_sismos preliminar (conteo directo por nombre normalizado SGC)
    counts = sismos["mpio"].value_counts()
    master["n_sismos_match"] = master["municipio"].map(counts).fillna(0).astype(int)

    validate(master, "municipios_master", required=["cod_mpio", "municipio"])
    master.to_csv(config.MUNICIPIOS_MASTER, index=False)
    reports["master"] = {"n_municipios": len(master)}
    save_json(reports, config.DATA_PROC / "reporte_limpieza.json")
    log.info("Dataset maestro: %d municipios", len(master))
    return sismos, master, reports
