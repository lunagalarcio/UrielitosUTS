"""Clustering no supervisado de municipios (KMeans / Aglomerativo / DBSCAN).

Selecciona automáticamente la mejor configuración por silhouette score,
perfila cada clúster y lo mapea a niveles Bajo/Medio/Alto (por indice_riesgo
medio) para contrastar con la clasificación supervisada.
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src import config
from src.utils.helpers import get_logger, save_json

log = get_logger(__name__)

# Columnas que definen la etiqueta supervisada: se excluyen igual que en el clasificador
LEAK_COLS = {"idx_actividad", "indice_exposicion", "indice_vulnerabilidad", "indice_riesgo"}
RISK_ORDER = {"Bajo": 0, "Medio": 1, "Alto": 2}


def _X_primary(feat: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cols = [c for c in feat.columns if c not in ("cod_mpio", "municipio") and c not in LEAK_COLS]
    return feat[cols].fillna(0).to_numpy(dtype=float), cols


def _silhouette(Xs: np.ndarray, labels: np.ndarray) -> float:
    n_cl = len(set(labels)) - (1 if -1 in labels else 0)
    if n_cl < 2 or n_cl >= len(Xs):
        return -1.0
    mask = labels != -1
    if mask.sum() < n_cl + 1:
        return -1.0
    try:
        return float(silhouette_score(Xs[mask], labels[mask]))
    except Exception:
        return -1.0


def run_clustering(feat: pd.DataFrame | None = None, labels: pd.DataFrame | None = None) -> dict:
    """Entrena candidatos, elige el mejor por silhouette y guarda artefactos.

    Returns:
        Diccionario con el ganador, silhouette, comparación y perfiles.
    """
    feat = feat if feat is not None else pd.read_csv(config.FEATURES)
    labels = labels if labels is not None else (pd.read_csv(config.LABELS) if config.LABELS.exists() else None)
    X, feature_names = _X_primary(feat)
    # Los conteos sísmicos son hiper-asimétricos (Los Santos = 104k vs mediana 255):
    # log-transformar las variables con skew alto para que el clustering no
    # colapse en "outliers vs resto".
    X = X.copy()
    skew = pd.DataFrame(X, columns=feature_names).skew()
    log_cols = [c for c in feature_names if skew[c] > 1.5 and (feat[c] >= 0).all()]
    for c in log_cols:
        X[:, feature_names.index(c)] = np.log1p(feat[c].fillna(0).to_numpy(dtype=float))
    log.info("Clustering: %d vars log-transformadas (skew>1.5)", len(log_cols))
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    candidates: dict[str, np.ndarray] = {}
    # k>=3: con k=2 el óptimo aísla solo los outliers extremos (Los Santos,
    # Zapatoca) y no aporta segmentación operativa; se exigen >=3 grupos.
    for k in (3, 4, 5, 6):
        candidates[f"KMeans_k{k}"] = KMeans(n_clusters=k, n_init=10,
                                            random_state=config.RANDOM_STATE).fit_predict(Xs)
    candidates["Aglomerativo_k3"] = AgglomerativeClustering(n_clusters=3).fit_predict(Xs)
    for eps in (0.8, 1.2, 1.6):
        candidates[f"DBSCAN_eps{eps}"] = DBSCAN(eps=eps, min_samples=3).fit_predict(Xs)

    scores = {name: round(_silhouette(Xs, lab), 4) for name, lab in candidates.items()}
    best_name = max(scores, key=scores.get)
    best_labels = np.asarray(candidates[best_name])
    log.info("Clustering: %s", {k: v for k, v in scores.items()})
    log.info("Ganador no supervisado: %s (silhouette=%.3f)", best_name, scores[best_name])

    # PCA 2D para visualización
    pca = PCA(n_components=2, random_state=config.RANDOM_STATE)
    XY = pca.fit_transform(Xs)

    # Mapeo clúster -> nivel de riesgo por indice_riesgo medio
    cluster_riesgo: dict[int, str] = {}
    order = feat.set_index("cod_mpio")["indice_riesgo"] if "indice_riesgo" in feat.columns else None
    tmp = pd.DataFrame({"cod_mpio": feat["cod_mpio"].to_numpy(), "cluster": best_labels})
    if order is not None:
        tmp["indice_riesgo"] = tmp["cod_mpio"].map(order)
        means = tmp.groupby("cluster")["indice_riesgo"].mean().sort_values()
        levels = ["Bajo", "Medio", "Alto"]
        for rank, cl in enumerate(means.index):
            cluster_riesgo[int(cl)] = levels[min(rank * len(levels) // max(len(means), 1), len(levels) - 1)]

    out = pd.DataFrame({"cod_mpio": feat["cod_mpio"], "municipio": feat["municipio"],
                        "cluster": best_labels,
                        "cluster_riesgo": [cluster_riesgo.get(int(c), "?") for c in best_labels],
                        "pca1": XY[:, 0], "pca2": XY[:, 1]})
    out.to_csv(config.DATA_PROC / "clusters_municipio.csv", index=False)

    # Perfiles: top variables por desviación de la media global
    profiles = {}
    for cl in sorted(out["cluster"].unique().tolist()):
        sub = feat[out["cluster"].to_numpy() == cl][feature_names]
        z = ((sub.mean() - feat[feature_names].mean()) / (feat[feature_names].std() + 1e-9)).sort_values(ascending=False)
        profiles[str(int(cl))] = {
            "n_municipios": int((out["cluster"] == cl).sum()),
            "nivel_asociado": cluster_riesgo.get(int(cl), "?"),
            "rasgos_distintivos": [f"{i} (z={v:.2f})" for i, v in z.head(5).items()],
            "municipios": out[out["cluster"] == cl].nlargest(5, "pca1")["municipio"].tolist(),
        }

    metrics: dict = {
        "mejor_modelo": best_name,
        "silhouette": scores[best_name],
        "comparacion_silhouette": scores,
        "n_clusters": int(len(set(best_labels)) - (1 if -1 in best_labels else 0)),
        "ruido_dbscan": int((best_labels == -1).sum()),
        "varianza_pca2d": round(float(sum(pca.explained_variance_ratio_)), 4),
        "perfiles": profiles,
    }
    if labels is not None and "indice_riesgo" in feat.columns:
        y_true = labels.set_index("cod_mpio").loc[feat["cod_mpio"], "riesgo"].map(RISK_ORDER).to_numpy()
        metrics["ari_vs_supervisado"] = round(float(adjusted_rand_score(y_true, best_labels)), 4)
        agree = (out["cluster_riesgo"].map(RISK_ORDER).to_numpy() == y_true).mean()
        metrics["acuerdo_nivel_vs_supervisado"] = round(float(agree), 4)
        log.info("ARI vs supervisado=%.3f | acuerdo de nivel=%.1f%%", metrics["ari_vs_supervisado"], agree * 100)

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"scaler": scaler, "modelo": best_name, "features": feature_names, "pca": pca},
                config.MODELS_DIR / "cluster_model.pkl")
    save_json(metrics, config.DATA_PROC / "metricas_clustering.json")
    return metrics
