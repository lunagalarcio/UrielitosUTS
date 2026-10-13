"""Gráficas de evaluación (matriz de confusión) para el dashboard."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src import config
from src.utils.helpers import get_logger, load_json

log = get_logger(__name__)


def plot_confusion_matrix(save_path: str | None = None) -> str:
    """Renderiza la matriz de confusión guardada en metricas_clasificacion.json."""
    metrics = load_json(config.METRICS_JSON)
    cm = np.array(metrics["matriz_confusion"]["matrix"])
    labels = metrics["matriz_confusion"]["labels"]
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, cmap="Reds")
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Real")
    ax.set_title(f"Matriz de confusión — {metrics['mejor_modelo']}")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, cm[i, j], ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black", fontweight="bold")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    out = save_path or str(config.DATA_PROC / "matriz_confusion.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    log.info("Matriz de confusión guardada en %s", out)
    return out
