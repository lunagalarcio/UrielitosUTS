"""Pipeline end-to-end: limpieza -> features -> riesgo -> RL -> analítica."""
from __future__ import annotations

import argparse
import traceback

from src.evaluation.analytics import build_analytics
from src.evaluation.plots import plot_confusion_matrix
from src.features.build_features import build_features
from src.preprocessing.build_master import build_master
from src.training.clustering import run_clustering
from src.training.label_risk import label_risk
from src.training.train_classifier import train_classifier
from rl.train_rl import train_rl
from src.utils.helpers import get_logger

log = get_logger("pipeline")


def main(episodes: int = 120) -> None:
    log.info("=== FASE 1: procesamiento ===")
    sismos, master, _ = build_master()
    log.info("=== FASE 2: features ===")
    feat = build_features(sismos, master)
    log.info("=== FASE 3: clasificación ===")
    labels = label_risk(feat)
    metrics = train_classifier(feat, labels)
    log.info("=== FASE 3b: clustering no supervisado ===")
    cluster_metrics = run_clustering(feat, labels)
    log.info("Clustering: %s silhouette=%.3f", cluster_metrics["mejor_modelo"], cluster_metrics["silhouette"])
    try:
        plot_confusion_matrix()
    except Exception as exc:
        log.warning("No se pudo graficar matriz: %s", exc)
    log.info("=== FASE 4: RL (%d episodios) ===", episodes)
    rl_meta = train_rl(feat, episodes=episodes)
    log.info("=== FASE 5: analítica ===")
    payload = build_analytics()
    log.info("PIPELINE OK | mejor_modelo=%s F1=%.3f | RL=%s | top1_riesgo=%s",
             metrics["mejor_modelo"], metrics["f1_macro"],
             rl_meta["ganador"], payload["top10_riesgo"][0]["municipio"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline riesgo sísmico Santander")
    parser.add_argument("--episodes", type=int, default=120)
    args = parser.parse_args()
    try:
        main(episodes=args.episodes)
    except Exception:
        log.error("Pipeline falló:\n%s", traceback.format_exc())
        raise
