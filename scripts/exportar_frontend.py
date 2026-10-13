"""Exporta los resultados de NUESTRO pipeline a sismos-santander/data/resultados_equipo.js.

El frontend (index.html + js/) lee sin servidor la variable RESULTADOS, por lo que
no se necesita API: este script materializa modelos y variables del backend en un JS.

Uso:
    $env:PYTHONPATH="<repo>"
    py -3.11 scripts/exportar_frontend.py [--mag-min 2.0]

Lee: data/processed/*, models/*, data/raw/metadata_*.json
Escribe: sismos-santander/data/resultados_equipo.js
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"
SALIDA = ROOT / "sismos-santander" / "data" / "resultados_equipo.js"

NIDO = (6.80, -73.15)  # Nido Sísmico de Bucaramanga (referencia)
K_ORACULO = 10
RANDOM_STATE = 42

LEAK_COLS = {"idx_actividad", "indice_exposicion", "indice_vulnerabilidad", "indice_riesgo"}
NIVELES = ["Bajo", "Medio", "Alto"]


def r4(v, d: int = 4):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), d)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = math.pi / 180
    h = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(max(0.0, min(1.0, h))))


def b_value_mle(mags: np.ndarray, mc: float) -> float | None:
    m = mags[mags >= mc]
    if len(m) < 10 or m.mean() <= mc:
        return None
    return float(math.log10(math.e) / (m.mean() - mc))


def main(mag_min: float = 2.0) -> None:
    feat = pd.read_csv(PROC / "features_municipio.csv")
    labels = pd.read_csv(PROC / "riesgo_labels.csv")
    ranking = pd.read_csv(PROC / "ranking_rl.csv")
    clusters = pd.read_csv(PROC / "clusters_municipio.csv")
    sismos = pd.read_csv(PROC / "sismos_limpios.csv", parse_dates=["fecha"])
    master = pd.read_csv(PROC / "municipios_master.csv")
    met_clf = json.loads((PROC / "metricas_clasificacion.json").read_text(encoding="utf-8"))
    met_clu = json.loads((PROC / "metricas_clustering.json").read_text(encoding="utf-8"))
    met_rl = json.loads((MODELS / "rl_meta.json").read_text(encoding="utf-8"))
    curva = pd.read_csv(PROC / "curva_rl.csv") if (PROC / "curva_rl.csv").exists() else pd.DataFrame()
    meta_sgc = json.loads((ROOT / "data" / "raw" / "metadata_descarga_sgc.json").read_text(encoding="utf-8"))
    meta_otras = json.loads((ROOT / "data" / "raw" / "metadata_fuentes_complementarias.json").read_text(encoding="utf-8"))
    bundle = joblib.load(MODELS / "risk_classifier.pkl")
    pipe, feat_cols, classes = bundle["pipeline"], bundle["features"], list(bundle["classes"])
    _predecir = pipe.predict

    def _pred_nombres(X):
        return np.array(NIVELES)[np.asarray(_predecir(X), dtype=int)]

    pipe.predict = _pred_nombres  # el pipeline entrena con 0/1/2; aquí siempre nombres
    # Códigos DIVIPOLA como string: el frontend compara con `===` contra el GeoJSON
    for _df in (feat, labels, ranking, clusters, master):
        if "cod_mpio" in _df.columns:
            _df["cod_mpio"] = _df["cod_mpio"].astype(str)

    sismos["fecha"] = pd.to_datetime(sismos["fecha"], errors="coerce")
    sismos = sismos.dropna(subset=["fecha"])
    sismos["anio"] = sismos["fecha"].dt.year
    anios = sorted(int(a) for a in sismos["anio"].unique())
    span = max(len(anios), 1)
    by_name = feat.set_index("municipio")
    cod_of = dict(zip(master["municipio"], master["cod_mpio"]))
    latlon = {m: (by_name.at[m, "lat_mpio"], by_name.at[m, "lon_mpio"]) for m in feat["municipio"]}
    g = sismos.groupby("mpio")

    # ---------- Serie anual + perfil sísmico por municipio ----------
    serie: dict[str, dict[int, int]] = {}
    perfil: dict[str, dict] = {}
    for _, row in feat.iterrows():
        name, code = row["municipio"], row["cod_mpio"]
        ev = g.get_group(name) if name in g.groups else sismos.iloc[0:0]
        counts = ev.groupby("anio").size().to_dict()
        serie[code] = {int(a): int(counts.get(a, 0)) for a in anios}
        mags = ev["mag"].to_numpy() if len(ev) else np.array([])
        prof = ev["prof_km"].to_numpy() if len(ev) else np.array([])
        perfil[code] = {
            "tasa_m25_anual": len(ev) / span,
            "tasa_m30_anual": float((mags >= 3.0).sum()) / span if len(ev) else 0.0,
            "tasa_m35_anual": float((mags >= 3.5).sum()) / span if len(ev) else 0.0,
            "mag_max": float(mags.max()) if len(ev) else 0.0,
            "mag_media": float(mags.mean()) if len(ev) else 0.0,
            "b_value": b_value_mle(mags, mc=2.0),
            "prof_media_km": float(prof.mean()) if len(ev) else 0.0,
            "pct_superficial": float((prof < 50).mean()) if len(ev) else 0.0,
            "pct_intermedio": float(((prof >= 50) & (prof < 150)).mean()) if len(ev) else 0.0,
            "log_energia_anual": float(math.log10(max(row["energia_sismica_acum"] / span, 1e-9))),
            "fraccion_anios_activos": float((pd.Series(counts) > 0).mean()) if counts else 0.0,
            "n_2025": int(counts.get(2025, 0)),
            "n_prom_3a": float(np.mean([counts.get(a, 0) for a in (2022, 2023, 2024)])),
            "mag_max_2025": float(ev[ev["anio"] == 2025]["mag"].max()) if (ev["anio"] == 2025).any() else 0.0,
            "mag_max_hist": float(mags.max()) if len(ev) else 0.0,
        }

    # ---------- Municipios ----------
    perfiles_clu = met_clu.get("perfiles", {})
    nombre_cluster = {int(k): f"Grupo {int(k) + 1} (riesgo {v.get('nivel_asociado', '?').lower()})"
                      for k, v in perfiles_clu.items()}
    clu_idx = dict(zip(clusters["cod_mpio"], clusters["cluster"]))
    pca_idx = {c: (p1, p2) for c, p1, p2 in zip(clusters["cod_mpio"], clusters["pca1"], clusters["pca2"])}
    municipios = []
    for _, row in feat.iterrows():
        code = row["cod_mpio"]
        cl = int(clu_idx.get(code, 0))
        p = perfil[code]
        p1, p2 = pca_idx.get(code, (0.0, 0.0))
        municipios.append({
            "cod": code, "nombre": row["municipio"], "dpto": "SANTANDER", "santander": True,
            "lat": r4(row["lat_mpio"]), "lon": r4(row["lon_mpio"]),
            "cluster": cl, "cluster_nombre": nombre_cluster.get(cl, f"Grupo {cl + 1}"),
            "pca1": r4(p1), "pca2": r4(p2),
            "tasa_m25_anual": r4(p["tasa_m25_anual"]), "tasa_m30_anual": r4(p["tasa_m30_anual"]),
            "tasa_m35_anual": r4(p["tasa_m35_anual"]), "mag_max": r4(p["mag_max"]),
            "mag_media": r4(p["mag_media"]), "b_value": r4(p["b_value"]),
            "prof_media_km": r4(p["prof_media_km"]), "pct_superficial": r4(p["pct_superficial"]),
            "pct_intermedio": r4(p["pct_intermedio"]), "log_energia_anual": r4(p["log_energia_anual"]),
            "fraccion_anios_activos": r4(p["fraccion_anios_activos"]),
            "cantidad_total_sismos": int(row["cantidad_total_sismos"]),
            "indice_riesgo": r4(row["indice_riesgo"]),
            "poblacion_total": int(row["poblacion_actual"]),
        })
    cod_a_indice = {m["cod"]: i for i, m in enumerate(municipios)}

    # ---------- fila_2025 ----------
    fila_2025 = {}
    for _, row in feat.iterrows():
        code = row["cod_mpio"]
        p = perfil[code]
        la, lo = latlon[row["municipio"]]
        fila_2025[code] = {
            "poblacion_total": int(row["poblacion_actual"]),
            "emergencias_prom_anual": r4(row["emergencias_totales"] / 7.0),
            "fallecidos_total": int(row["fallecidos"]), "heridos_total": int(row["heridos"]),
            "personas_afectadas": int(row["personas_afectadas"]),
            "n_m25": p["n_2025"], "n_m25_prom_3a": r4(p["n_prom_3a"]),
            "mag_max": r4(p["mag_max_2025"]), "mag_max_historica": r4(p["mag_max_hist"]),
            "prof_media_km": r4(p["prof_media_km"]), "pct_superficial": r4(p["pct_superficial"]),
            "dist_nido_km": r4(haversine_km(la, lo, *NIDO)) if la and lo else None,
            "b_value": r4(p["b_value"]),
        }

    # ---------- Predicción supervisada (probas reales del modelo guardado) ----------
    X = feat[feat_cols].fillna(0).to_numpy()
    proba = pipe.predict_proba(X)
    order = [classes.index(n) for n in NIVELES]
    pred_idx = proba.argmax(axis=1)
    inv_pred = {v: k for k, v in {"bajo": 0, "medio": 1, "alto": 2}.items()}
    prediccion_2026, historico = {}, {}
    riesgo_true = dict(zip(labels["cod_mpio"], labels["riesgo"]))
    for i, (_, row) in enumerate(feat.iterrows()):
        code = row["cod_mpio"]
        prediccion_2026[code] = {
            "p_bajo": r4(proba[i, order[0]]), "p_medio": r4(proba[i, order[1]]),
            "p_alto": r4(proba[i, order[2]]),
            "pred": NIVELES[pred_idx[i]].lower(),
        }
        historico[code] = [[2026, NIVELES[pred_idx[i]].lower(), str(riesgo_true.get(code, "?")).lower()]]

    # ---------- Métricas supervisado (mismo split que el entrenamiento) ----------
    from sklearn.metrics import balanced_accuracy_score, classification_report, f1_score
    from sklearn.model_selection import train_test_split

    y = labels.set_index("cod_mpio").loc[feat["cod_mpio"], "riesgo"].to_numpy()
    X_tr, X_te, y_tr, y_te, idx_tr, idx_te = train_test_split(
        X, y, np.arange(len(feat)), test_size=0.25, stratify=y, random_state=RANDOM_STATE)
    y_pred = pipe.predict(X_te)
    rep = classification_report(y_te, y_pred, labels=NIVELES, output_dict=True, zero_division=0)
    bal_acc = float(balanced_accuracy_score(y_te, y_pred))
    rec_alto = float(rep["Alto"]["recall"])
    rng = np.random.default_rng(RANDOM_STATE)
    # bootstrap: remuestrear pares (y_true, y_pred) del test
    boots = [float(f1_score(y_te[b], y_pred[b], average="macro"))
             for b in (rng.choice(len(y_te), len(y_te), replace=True) for _ in range(300))]
    maj = max(set(y_tr.tolist()), key=y_tr.tolist().count)
    f1_maj = float(f1_score(y_te, [maj] * len(y_te), average="macro", zero_division=0))
    f1_azar = float(np.mean([f1_score(y_te, rng.choice(np.unique(y_tr), len(y_te)), average="macro")
                             for _ in range(50)]))
    dist = lambda arr: {n.lower(): r4(float((arr == n).mean())) for n in NIVELES}
    metricas_supervisado = {
        "modelo_elegido": met_clf["mejor_modelo"],
        "params": {"test_size": 0.25, "cv_folds": 5, "random_state": RANDOM_STATE,
                   "split": "estratificado 75/25", "etiquetas": "terciles del indice_riesgo"},
        "val": {"f1_macro": met_clf["f1_macro_cv"]},
        "test": {"f1_macro": met_clf["f1_macro"], "balanced_accuracy": r4(bal_acc),
                 "recall_alto": r4(rec_alto),
                 "matriz_confusion": met_clf["matriz_confusion"]["matrix"],
                 "reporte": {n.lower(): {"precision": r4(rep[n]["precision"]), "recall": r4(rep[n]["recall"]),
                                         "f1-score": r4(rep[n]["f1-score"]), "support": int(rep[n]["support"])}
                             for n in NIVELES}},
        "lineas_base_test": {"azar": {"f1_macro": r4(f1_azar)}, "mayoritaria": {"f1_macro": r4(f1_maj)}},
        "bootstrap_f1_test": {"p2_5": r4(float(np.quantile(boots, 0.025))),
                              "p97_5": r4(float(np.quantile(boots, 0.975)))},
        "distribucion_clases": {"train": dist(y_tr), "test": dist(y_te)},
        "importancias": {d["feature"]: d["importancia"] for d in met_clf.get("top_importancias", [])},
        "comparacion_modelos_f1_cv": met_clf.get("comparacion_modelos_f1_cv", {}),
    }

    # ---------- Clustering ----------
    scaler_cols = feat_cols
    Xs = feat[scaler_cols].fillna(0).to_numpy(dtype=float)
    skew = pd.DataFrame(Xs, columns=scaler_cols).skew()
    for c in [c for c in scaler_cols if skew[c] > 1.5 and (feat[c] >= 0).all()]:
        Xs[:, scaler_cols.index(c)] = np.log1p(feat[c].fillna(0).to_numpy(dtype=float))
    from sklearn.cluster import KMeans
    from sklearn.feature_selection import f_classif
    from sklearn.metrics import davies_bouldin_score, silhouette_score
    from sklearn.preprocessing import StandardScaler

    Xs = StandardScaler().fit_transform(Xs)
    seleccion_k = []
    for k in (3, 4, 5, 6):
        lab = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit_predict(Xs)
        seleccion_k.append({"k": k, "silueta": r4(silhouette_score(Xs, lab)),
                            "davies_bouldin": r4(davies_bouldin_score(Xs, lab))})
    clu_lab = clusters.set_index("cod_mpio").loc[feat["cod_mpio"], "cluster"].to_numpy()
    F, _ = f_classif(Xs, clu_lab)
    importancia = {c: r4(float(v)) for c, v in sorted(zip(scaler_cols, F), key=lambda t: -t[1]) if np.isfinite(v)}
    centroides = {}
    for cl in sorted(set(clu_lab.tolist())):
        sub = feat[clu_lab == cl]
        centroides[nombre_cluster.get(int(cl), str(cl))] = {
            "tasa_m25_anual": r4(sub["frecuencia_sismica_anual"].mean()),
            "prof_media_km": r4(sub["profundidad_promedio"].mean()),
            "pct_superficial": r4(sub["pct_sismos_superficiales"].mean()),
            "pct_intermedio": r4((((sub["profundidad_promedio"] >= 50) & (sub["profundidad_promedio"] < 150))).mean()),
            "b_value": None}
    comp_terr = {"SANTANDER": {}}
    for cl in sorted(set(clu_lab.tolist())):
        comp_terr["SANTANDER"][nombre_cluster.get(int(cl), str(cl))] = int((clu_lab == cl).sum())

    # DBSCAN sobre epicentros M>=3 para fuentes sísmicas
    from sklearn.cluster import DBSCAN

    ev3 = sismos[(sismos["mag"] >= 3.0)].dropna(subset=["lat", "lon", "prof_km"])
    fuentes = []
    if len(ev3) >= 50:
        Xr = np.radians(ev3[["lat", "lon"]].to_numpy())
        db = DBSCAN(eps=12 / 6371.0, min_samples=25, metric="haversine").fit(Xr)
        ev3 = ev3.copy()
        ev3["fu"] = db.labels_
        grupos = [l for l in sorted(set(db.labels_)) if l != -1]
        info = []
        for l in grupos:
            q = ev3[ev3["fu"] == l]
            info.append({"n": int(len(q)), "lat": float(q["lat"].mean()), "lon": float(q["lon"].mean()),
                         "prof_media_km": r4(q["prof_km"].mean()), "mag_max": r4(q["mag"].max()),
                         "d_nido": haversine_km(float(q["lat"].mean()), float(q["lon"].mean()), *NIDO)})
        info.sort(key=lambda d: d["d_nido"])  # fuente 1 = más cercana al Nido
        for i, d in enumerate(info[:12], start=1):
            d.pop("d_nido")
            fuentes.append({"fuente": i, **d})
    metricas_no_supervisado = {
        "metodo": met_clu["mejor_modelo"], "k_elegido": met_clu["n_clusters"],
        "silueta_final": met_clu["silhouette"], "seleccion_k": seleccion_k,
        "centroides": centroides, "comparacion_territorial": comp_terr,
        "dbscan_fuentes": fuentes, "importancia_variables": importancia,
        "ari_vs_supervisado": met_clu.get("ari_vs_supervisado"),
    }

    # ---------- RL: oráculo top-K por indice_riesgo + líneas base ----------
    riesgo = feat.set_index("cod_mpio")["indice_riesgo"]
    rank = ranking.set_index("cod_mpio")
    oracle = set(riesgo.nlargest(K_ORACULO).index)
    impact = lambda codes: float(riesgo.loc[list(codes)].sum())

    def strat(codes):
        top = list(codes)[:K_ORACULO]
        return {"pct_oraculo": r4(impact(top) / impact(oracle)),
                "precision_at_k": r4(len(set(top) & oracle) / K_ORACULO)}

    proba_alto = {code: prediccion_2026[code]["p_alto"] or 0.0 for code in feat["cod_mpio"]}
    amenaza = feat.set_index("cod_mpio")["idx_actividad"]
    expo = feat.set_index("cod_mpio")["indice_exposicion"]
    vuln = feat.set_index("cod_mpio")["indice_vulnerabilidad"]
    mixto = ((amenaza - amenaza.min()) / (amenaza.max() - amenaza.min() + 1e-9)
             + (expo - expo.min()) / (expo.max() - expo.min() + 1e-9)
             + (vuln - vuln.min()) / (vuln.max() - vuln.min() + 1e-9)) / 3
    azares = []
    for s in range(20):
        perm = feat["cod_mpio"].sample(frac=1, random_state=1000 + s).tolist()
        azares.append(strat(perm)["pct_oraculo"])
    test_rl = {
        "agente_rl": {**strat(rank.sort_values("puesto").index), "std_semillas": 0.0},
        "indice_pesos_iguales": strat(mixto.sort_values(ascending=False).index),
        "mayor_poblacion": strat(feat.sort_values("poblacion_actual", ascending=False)["cod_mpio"]),
        "mayor_actividad_pasada": strat(feat.sort_values("cantidad_total_sismos", ascending=False)["cod_mpio"]),
        "ranking_supervisado": strat(sorted(proba_alto, key=proba_alto.get, reverse=True)),
        "azar": {"pct_oraculo": r4(float(np.mean(azares))), "precision_at_k": r4(K_ORACULO / len(feat)),
                 "std_semillas": r4(float(np.std(azares)))},
    }
    score = rank["score_rl_100"]
    pesos = {}
    for c in feat_cols:
        v = feat[c].to_numpy(dtype=float)
        pesos[c] = r4(abs(float(np.corrcoef(v, score.loc[feat["cod_mpio"]])[0, 1]))
                      if v.std() > 0 else 0.0)
    curva_list = []
    if len(curva):
        w = curva[curva["algoritmo"] == met_rl["ganador"].lower()]
        w = w if len(w) else curva[curva["algoritmo"] == curva["algoritmo"].iloc[0]]
        for _, r in w.iterrows():
            curva_list.append({"epoca": int(r["epoca"]), "recompensa": r4(r["recompensa"]),
                               "pct_oraculo_val": None})
    metricas_rl = {
        "test": test_rl,
        "config": {"k": K_ORACULO, "algoritmo": met_rl["ganador"],
                   "recompensas_medias": met_rl.get("recompensas_medias"),
                   "epocas": met_rl.get("episodios"), "semillas": 1, "lr": "0.05 (PPO) / MLP (DQN)",
                   "entorno": "episodio recorre 87 municipios; estado=35 vars; acciones={priorizar, no priorizar}",
                   "recompensa": "R(a=1)=2r-1+0.5·exposicion·r; R(a=0)=0.3(1-r)-0.7r, r=indice_riesgo",
                   "oraculo": f"top-{K_ORACULO} por indice_riesgo (impacto=suma de r)",
                   "anios_train": [anios[0], anios[-1]], "anios_test": [anios[0], anios[-1]]},
        "pesos_politica": {c: {"media": v or 0.0, "std": 0.0} for c, v in
                           sorted(pesos.items(), key=lambda t: -(t[1] or 0))[:20]},
    }

    # ---------- Priorización 2026 ----------
    conf_q = rank["score_rl_100"].quantile([1 / 3, 2 / 3])
    fidx = feat.set_index("cod_mpio")
    priorizacion = []
    for code, r in rank.iterrows():
        s = float(r["score_rl_100"])
        priorizacion.append({
            "cod_mpio": code, "rango": int(r["puesto"]), "puntaje": r4(s),
            "confianza": "alta" if s >= conf_q.iloc[1] else ("media" if s >= conf_q.iloc[0] else "baja"),
            "prob_top_k": r4(s / 100.0),
            "contrib_amenaza": None,
            "contrib_exposicion": None, "contrib_vulnerabilidad": None,
            "p_alto": prediccion_2026[code]["p_alto"],
            "cluster_nombre": next(m["cluster_nombre"] for m in municipios if m["cod"] == code),
            "poblacion_total": int(fidx.at[code, "poblacion_actual"]),
            "n_m25_2025": perfil[code]["n_2025"],
        })
    for p in priorizacion:
        c = p["cod_mpio"]
        p["contrib_amenaza"] = r4(fidx.at[c, "idx_actividad"])
        p["contrib_exposicion"] = r4(fidx.at[c, "indice_exposicion"])
        p["contrib_vulnerabilidad"] = r4(fidx.at[c, "indice_vulnerabilidad"])

    # ---------- Diccionario ----------
    DESC = {
        "cantidad_total_sismos": ("conteo total de sismos asignados al municipio en el catálogo SGC unificado", "Más eventos = mayor actividad sísmica instrumental"),
        "magnitud_promedio": ("magnitud media de los eventos del municipio", "Resume el tamaño típico de la sismicidad local"),
        "magnitud_maxima": ("mayor magnitud registrada en el municipio", "Indica el peor caso instrumental observado"),
        "magnitud_minima": ("menor magnitud registrada", "Refleja la completitud del catálogo en la zona"),
        "magnitud_std": ("desviación estándar de la magnitud", "Variabilidad del tamaño de los eventos"),
        "pct_sismos_mag_mayor_4": ("fracción de sismos con magnitud ≥ 4.0", "Eventos moderados con potencial de daño"),
        "pct_sismos_mag_mayor_5": ("fracción de sismos con magnitud ≥ 5.0", "Eventos fuertes, raros y relevantes"),
        "energia_sismica_acum": ("suma de 10^(1.5·M): energía sísmica acumulada", "Pondera los sismos grandes sobre los pequeños"),
        "profundidad_promedio": ("profundidad media en km", "Distingue sismicidad del Nido (profunda) de la cortical"),
        "profundidad_maxima": ("profundidad máxima en km", "Alcance del slab bajo el municipio"),
        "profundidad_minima": ("profundidad mínima en km", "Cercanía de eventos a la superficie"),
        "profundidad_std": ("desviación estándar de la profundidad", "Mezcla de fuentes profundas y superficiales"),
        "pct_sismos_superficiales": ("fracción de sismos con profundidad < 50 km", "Los superficiales amenazan más la infraestructura"),
        "frecuencia_sismica_anual": ("sismos por año en el periodo del catálogo", "Tasa base de actividad"),
        "sismos_ultimos_10_anios": ("eventos en los últimos 10 años", "Actividad reciente de mediano plazo"),
        "sismos_ultimos_5_anios": ("eventos en los últimos 5 años", "Actividad reciente de corto plazo"),
        "sismos_ultimos_2_anios": ("eventos en los últimos 2 años", "Actividad inmediata"),
        "tendencia_sismica": ("pendiente lineal de la serie anual (mínimos cuadrados)", "Detecta aumento o caída sostenida"),
        "crecimiento_frecuencia_sismica": ("cambio relativo entre el último y el primer lustro", "Aceleración reciente de la actividad"),
        "poblacion_actual": ("población DANE del año de referencia", "Personas expuestas hoy"),
        "poblacion_proyectada": ("población DANE proyectada a 2035", "Exposición futura"),
        "crecimiento_poblacional": ("cambio relativo de población en el periodo", "Presión sobre suelo e infraestructura"),
        "log_poblacion": ("logaritmo de la población", "Comprime la escala entre capital y ruralidad"),
        "emergencias_totales": ("emergencias UNGRD 2019–2025 en el municipio", "Historial de desastres (toda causa)"),
        "emergencias_sismicas": ("emergencias UNGRD de origen sísmico", "Daño sísmico observado"),
        "emergencias_por_anio": ("emergencias por año", "Tasa de recurrencia de desastres"),
        "fallecidos": ("fallecidos acumulados en emergencias", "Severidad humana histórica"),
        "heridos": ("heridos acumulados en emergencias", "Severidad humana histórica"),
        "personas_afectadas": ("personas afectadas acumuladas", "Magnitud del impacto social"),
        "lat_mpio": ("latitud de la cabecera (DIVIPOLA)", "Posición para mapas y distancias"),
        "lon_mpio": ("longitud de la cabecera (DIVIPOLA)", "Posición para mapas y distancias"),
        "idx_actividad": ("subíndice de actividad sísmica 0–1", "Componente de amenaza del índice de riesgo"),
        "indice_exposicion": ("subíndice de exposición 0–1", "Población y afectación pasada"),
        "indice_vulnerabilidad": ("subíndice de vulnerabilidad 0–1", "Emergencias, superficialidad y crecimiento"),
        "indice_riesgo": ("índice compuesto 0–1 (50% actividad + 30% exposición + 20% vulnerabilidad)", "Define las etiquetas Bajo/Medio/Alto por terciles"),
    }
    diccionario = [{"variable": c, "fuente": "SGC" if c in feat_cols[:19] else ("DANE" if "pobla" in c or c in ("lat_mpio", "lon_mpio", "log_poblacion", "crecimiento_poblacional") else ("UNGRD" if c in ("emergencias_totales", "emergencias_sismicas", "emergencias_por_anio", "fallecidos", "heridos", "personas_afectadas") else "SGC+DANE+UNGRD")),
                    "rol": "sup" if c in feat_cols else "compuesto",
                    "descripcion": DESC.get(c, ("", ""))[0], "justificacion": DESC.get(c, ("", ""))[1]}
                   for c in feat_cols + ["idx_actividad", "indice_exposicion", "indice_vulnerabilidad", "indice_riesgo"]]

    # ---------- Eventos compactos M>=mag_min ----------
    ev = sismos[sismos["mag"] >= mag_min].dropna(subset=["lat", "lon", "prof_km", "mag"])
    nom_a_indice = {m["nombre"]: i for i, m in enumerate(municipios)}
    eventos, sin_mapa = [], 0
    for _, e in ev.iterrows():
        key = str(e["mpio"]).replace("_", " ")
        if key not in nom_a_indice:
            sin_mapa += 1
            continue
        minutos = int(pd.Timestamp(e["fecha"]).tz_localize("UTC").timestamp() // 60)
        eventos.append([minutos, round(float(e["lat"]), 3), round(float(e["lon"]), 3),
                        round(float(e["prof_km"]), 1), round(float(e["mag"]), 1), nom_a_indice[key]])
    eventos.sort()

    resultado = {
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "repositorio": "Urielitos-main",
        "pipeline": "src+rl de este repo (terciles del indice_riesgo; split 75/25; PPO vs DQN)",
        "umbral_magnitud": mag_min,
        "fuentes": {"sgc": meta_sgc, "otras": meta_otras},
        "anios": anios,
        "municipios": municipios,
        "fila_2025": fila_2025,
        "columnas_dataset": feat_cols,
        "serie_n_m25": serie,
        "prediccion_2026": prediccion_2026,
        "historico_predicciones": historico,
        "priorizacion_2026": priorizacion,
        "metricas_supervisado": metricas_supervisado,
        "metricas_no_supervisado": metricas_no_supervisado,
        "metricas_rl": metricas_rl,
        "curva_rl": curva_list,
        "diccionario": diccionario,
        "eventos_info": {"mag_min": mag_min, "n": len(eventos), "sin_mapa": sin_mapa,
                         "formato": "[minutos desde 1970 UTC, lat, lon, prof_km, mag, índice de municipio]"},
        "eventos": eventos,
    }
    texto = ("// Resultados del pipeline Urielitos-main, exportados con scripts/exportar_frontend.py.\n"
             "// No editar a mano: volver a correr el script si cambian los resultados.\n"
             "var RESULTADOS = " + json.dumps(resultado, ensure_ascii=False, separators=(",", ":")) + ";\n")
    SALIDA.write_text(texto, encoding="utf-8")
    print(f"[exportar_frontend] {SALIDA} · {len(texto) / 1e6:.1f} MB · {len(eventos)} eventos M>={mag_min} "
          f"· {len(municipios)} municipios · fuentes DBSCAN: {len(fuentes)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mag-min", type=float, default=2.0)
    args = ap.parse_args()
    main(mag_min=args.mag_min)
