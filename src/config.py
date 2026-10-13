"""Configuración central del proyecto de riesgo sísmico Santander."""
from __future__ import annotations

from pathlib import Path

# Raíz del proyecto (carpeta que contiene app.py)
ROOT: Path = Path(__file__).resolve().parent.parent

DATA_RAW: Path = ROOT / "data" / "raw"
DATA_PROC: Path = ROOT / "data" / "processed"
MODELS_DIR: Path = ROOT / "models"
RL_DIR: Path = ROOT / "rl"

# Archivos fuente
SGC_1993_2018: Path = DATA_RAW / "sgc_1993_2018.csv"
SGC_2018_HOY: Path = DATA_RAW / "sgc_2018_hoy.csv"
DIVIPOLA: Path = DATA_RAW / "dane_divipola.csv"
POBLACION_XLSX: Path = DATA_RAW / "dane_proyeccion_poblacion_municipal_2020_2035.xlsx"
EMERG_2019_2024: Path = DATA_RAW / "ungrd_emergencias_2019_2024.csv"
EMERG_2025: Path = DATA_RAW / "ungrd_emergencias_2025.csv"

# Artefactos generados
SISMOS_CLEAN: Path = DATA_PROC / "sismos_limpios.csv"
MUNICIPIOS_MASTER: Path = DATA_PROC / "municipios_master.csv"
FEATURES: Path = DATA_PROC / "features_municipio.csv"
LABELS: Path = DATA_PROC / "riesgo_labels.csv"
RANKING_RL: Path = DATA_PROC / "ranking_rl.csv"
ANALITICA_JSON: Path = DATA_PROC / "analitica.json"
METRICS_JSON: Path = DATA_PROC / "metricas_clasificacion.json"
INSIGHTS_JSON: Path = DATA_PROC / "insights.json"

MODEL_CLF: Path = MODELS_DIR / "risk_classifier.pkl"
MODEL_META: Path = MODELS_DIR / "risk_classifier_meta.json"
RL_MODEL: Path = MODELS_DIR / "rl_agent.pkl"
RL_META: Path = MODELS_DIR / "rl_meta.json"

# Constantes de dominio
COD_DPTO_SANTANDER: str = "68"
DEPTO_SANTANDER: str = "SANTANDER"
ANIO_CORTE: int = 2026
CRS_WGS84: str = "EPSG:4326"

# Municipios del área de influencia del Nido Sísmico de Bucaramanga
# (fuente: literatura SGC; se usa para insights, no para etiquetado)
NIDO_BUCARAMANGA: tuple[str, ...] = (
    "LOS SANTOS",
    "CEPITA",
    "ZAPATOCA",
    "BETULIA",
    "JORDAN",
    "VILLANUEVA",
    "ARATOCA",
    "PIEDECUESTA",
    "GIRON",
    "FLORIDABLANCA",
    "BUCARAMANGA",
)

RISK_LABELS: tuple[str, ...] = ("Bajo", "Medio", "Alto")
RANDOM_STATE: int = 42
