"""Entrenamiento y selección automática del mejor clasificador de riesgo."""
from __future__ import annotations

import json
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src import config
from src.utils.helpers import get_logger, save_json

log = get_logger(__name__)
warnings.filterwarnings("ignore")


def _candidate_models() -> dict[str, object]:
    """Modelos candidatos. XGBoost/LightGBM solo si están instalados."""
    models: dict[str, object] = {
        "RandomForest": RandomForestClassifier(n_estimators=300, max_depth=None,
                                               min_samples_leaf=2, class_weight="balanced",
                                               random_state=config.RANDOM_STATE, n_jobs=-1),
        "GradientBoosting": GradientBoostingClassifier(random_state=config.RANDOM_STATE),
        "HistGradientBoosting": __import__("sklearn.ensemble", fromlist=["HistGradientBoostingClassifier"]).HistGradientBoostingClassifier(
            random_state=config.RANDOM_STATE),
        "LogisticRegression": LogisticRegression(max_iter=2000, class_weight="balanced"),
    }
    try:
        from xgboost import XGBClassifier

        models["XGBoost"] = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                          subsample=0.9, colsample_bytree=0.9, eval_metric="mlogloss",
                                          random_state=config.RANDOM_STATE, n_jobs=-1)
    except Exception as exc:
        log.warning("XGBoost no disponible (%s)", exc)
    try:
        from lightgbm import LGBMClassifier

        models["LightGBM"] = LGBMClassifier(n_estimators=300, learning_rate=0.05,
                                            class_weight="balanced", random_state=config.RANDOM_STATE, verbose=-1)
    except Exception as exc:
        log.warning("LightGBM no disponible (%s)", exc)
    return models


def train_classifier(feat: pd.DataFrame | None = None, labels: pd.DataFrame | None = None) -> dict:
    """Entrena candidatos, elige el mejor por F1-macro (CV) y guarda artefactos.

    Returns:
        Diccionario con métricas del mejor modelo y comparación.
    """
    feat = feat if feat is not None else pd.read_csv(config.FEATURES)
    labels = labels if labels is not None else pd.read_csv(config.LABELS)
    df = feat.merge(labels[["cod_mpio", "riesgo"]], on="cod_mpio", how="inner")
    # Evitar fuga de etiqueta: los índices compuestos definen el label; el
    # clasificador debe aprender solo de variables primarias.
    LEAK_COLS = {"idx_actividad", "indice_exposicion", "indice_vulnerabilidad", "indice_riesgo"}
    X = df[[c for c in feat.columns if c not in ("cod_mpio", "municipio") and c not in LEAK_COLS]].fillna(0).to_numpy()
    # XGBoost (y otros boosters) exigen etiquetas enteras 0..K-1: codificar y
    # decodificar en los bordes para no cambiar el contrato (Bajo/Medio/Alto).
    CLASES = list(config.RISK_LABELS)
    a_int = {c: i for i, c in enumerate(CLASES)}
    y = df["riesgo"].map(a_int).to_numpy()
    feature_names = [c for c in feat.columns if c not in ("cod_mpio", "municipio") and c not in LEAK_COLS]

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=config.RANDOM_STATE)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=config.RANDOM_STATE)
    comparison: dict[str, float] = {}
    best_name, best_cv = "", -1.0
    for name, clf in _candidate_models().items():
        pipe = Pipeline([("scaler", StandardScaler()), ("clf", clf)])
        scores = cross_val_score(pipe, X_tr, y_tr, cv=cv, scoring="f1_macro", n_jobs=-1)
        comparison[name] = float(scores.mean())
        log.info("%-18s F1-macro CV=%.4f (±%.4f)", name, scores.mean(), scores.std())
        if scores.mean() > best_cv:
            best_cv, best_name = float(scores.mean()), name

    best_pipe = Pipeline([("scaler", StandardScaler()),
                          ("clf", _candidate_models()[best_name])])
    best_pipe.fit(X_tr, y_tr)
    y_pred = best_pipe.predict(X_te)
    y_te_nombres = [CLASES[i] for i in y_te]
    y_pred_nombres = [CLASES[i] for i in y_pred]
    cm = confusion_matrix(y_te, y_pred, labels=list(range(len(CLASES))))
    metrics = {
        "mejor_modelo": best_name,
        "f1_macro_cv": round(best_cv, 4),
        "accuracy": round(float(accuracy_score(y_te, y_pred)), 4),
        "precision_macro": round(float(precision_score(y_te, y_pred, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_te, y_pred, average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_te, y_pred, average="macro", zero_division=0)), 4),
        "matriz_confusion": {"labels": CLASES, "matrix": cm.tolist()},
        "comparacion_modelos_f1_cv": {k: round(v, 4) for k, v in comparison.items()},
        "n_municipios": int(len(df)),
        "features": feature_names,
    }
    # Importancias (si el estimador las expone)
    try:
        clf = best_pipe.named_steps["clf"]
        if hasattr(clf, "feature_importances_"):
            imp = sorted(zip(feature_names, map(float, clf.feature_importances_)),
                         key=lambda t: t[1], reverse=True)[:15]
            metrics["top_importancias"] = [{"feature": f, "importancia": round(v, 4)} for f, v in imp]
        elif hasattr(clf, "coef_"):
            imp = sorted(zip(feature_names, map(float, np.abs(clf.coef_).mean(axis=0))),
                         key=lambda t: t[1], reverse=True)[:15]
            metrics["top_importancias"] = [{"feature": f, "importancia": round(v, 4)} for f, v in imp]
    except Exception as exc:
        log.warning("No se pudieron extraer importancias: %s", exc)

    # Predicción sobre todos los municipios + guardado (de vuelta a nombres)
    df["riesgo_pred"] = [CLASES[i] for i in best_pipe.predict(X)]
    try:
        df["proba_alto"] = best_pipe.predict_proba(X)[:, CLASES.index("Alto")]
    except Exception:
        df["proba_alto"] = 0.0
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": best_pipe, "features": feature_names,
                 "classes": list(config.RISK_LABELS)}, config.MODEL_CLF)
    save_json(metrics, config.METRICS_JSON)
    save_json(metrics, config.MODEL_META)
    df[["cod_mpio", "municipio", "riesgo", "riesgo_pred", "proba_alto"]].to_csv(
        config.DATA_PROC / "predicciones_riesgo.csv", index=False)
    log.info("Mejor modelo: %s | Acc=%.3f F1=%.3f", best_name, metrics["accuracy"], metrics["f1_macro"])
    return metrics
