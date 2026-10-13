"""Etiquetado de riesgo (Bajo/Medio/Alto) a partir del índice continuo."""
from __future__ import annotations

import pandas as pd

from src import config
from src.utils.helpers import get_logger

log = get_logger(__name__)


def label_risk(feat: pd.DataFrame | None = None) -> pd.DataFrame:
    """Cuantiza `indice_riesgo` en 3 clases balanceadas (terciles).

    Si qcut falla (poca varianza), usa cortes fijos 0.33/0.66.
    """
    feat = feat if feat is not None else pd.read_csv(config.FEATURES)
    try:
        labels = pd.qcut(feat["indice_riesgo"], 3, labels=list(config.RISK_LABELS))
    except ValueError:
        labels = pd.cut(feat["indice_riesgo"], [-0.01, 0.33, 0.66, 1.01], labels=list(config.RISK_LABELS))
    out = feat[["cod_mpio", "municipio", "indice_riesgo"]].copy()
    out["riesgo"] = labels.astype(str)
    out.to_csv(config.LABELS, index=False)
    log.info("Etiquetas: %s", out["riesgo"].value_counts().to_dict())
    return out
