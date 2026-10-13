"""Utilidades transversales: logging, IO y normalización de texto."""
from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


def get_logger(name: str = "sismo_santander", level: int = logging.INFO) -> logging.Logger:
    """Crea (o reutiliza) un logger con formato uniforme."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


log = get_logger()


def norm_text(value: Any) -> str:
    """Normaliza texto: sin tildes, mayúsculas, espacios colapsados.

    Ej: 'Santa Helena del Opón' -> 'SANTA HELENA DEL OPON'
    """
    if value is None:
        return ""
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return ""
    except Exception:
        pass
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # El catálogo SGC usa guion bajo como separador
    text = text.replace(" ", "_")
    return text


def norm_name_space(value: Any) -> str:
    """Igual que norm_text pero con espacios (para DIVIPOLA/UNGRD)."""
    return norm_text(value).replace("_", " ")


def pad_divipola(value: Any, length: int = 5) -> str:
    """Normaliza un código DIVIPOLA a string de `length` dígitos."""
    if value is None:
        return ""
    s = str(value).strip().replace(".0", "")
    s = re.sub(r"\D", "", s)
    if not s:
        return ""
    return s.zfill(length)[-length:] if len(s) > length else s.zfill(length)


def save_json(payload: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
