"""Dashboard Streamlit — Plataforma de Riesgo Sísmico de Santander."""
from __future__ import annotations

import json
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"

st.set_page_config(page_title="Riesgo Sísmico Santander", page_icon="🌋", layout="wide")


@st.cache_data
def load_csv(name: str) -> pd.DataFrame:
    p = PROC / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data
def load_json(name: str) -> dict:
    p = PROC / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------------- Datos ----------------
feat = load_csv("features_municipio.csv")
labels = load_csv("riesgo_labels.csv")
preds = load_csv("predicciones_riesgo.csv")
ranking = load_csv("ranking_rl.csv")
clusters = load_csv("clusters_municipio.csv")
sismos = load_csv("sismos_limpios.csv")
metricas = load_json("metricas_clasificacion.json")
metricas_clu = load_json("metricas_clustering.json")
analitica = load_json("analitica.json")
rl_meta = load_json("rl_meta.json") if (PROC / "rl_meta.json").exists() else load_json("../models/rl_meta.json")

if "fecha" in sismos.columns:
    sismos["fecha"] = pd.to_datetime(sismos["fecha"], errors="coerce")
    sismos["anio"] = sismos["fecha"].dt.year

base = feat.merge(labels[["cod_mpio", "riesgo"]], on="cod_mpio", how="left") if len(feat) and len(labels) else feat
if len(ranking) and len(base):
    base = base.merge(ranking[["cod_mpio", "score_rl_100", "puesto"]], on="cod_mpio", how="left")

# ---------------- Navegación ----------------
st.sidebar.title("🌋 Riesgo Sísmico Santander")
page = st.sidebar.radio("Navegación", ["Inicio", "Análisis Sísmico", "Riesgo", "Aprendizaje por Refuerzo", "Mapas", "Insights"])
st.sidebar.divider()
st.sidebar.caption("Fuentes oficiales: SGC · DANE (DIVIPOLA + proyecciones) · UNGRD")

if base.empty:
    st.error("No hay datos procesados. Ejecute `python scripts/run_pipeline.py` primero.")
    st.stop()

# ================= INICIO =================
if page == "Inicio":
    st.title("Plataforma de Análisis de Riesgo Sísmico — Santander 🇨🇴")
    st.markdown("Clasificación del riesgo municipal y priorización inteligente con **Aprendizaje por Refuerzo** "
                "a partir de datos oficiales colombianos (SGC, DANE, UNGRD).")
    est = analitica.get("estadisticas", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sismos analizados", f"{est.get('n_sismos', int(feat['cantidad_total_sismos'].sum())):,}")
    c2.metric("Municipios", est.get("n_municipios", len(feat)))
    c3.metric("Magnitud máxima", est.get("magnitud_max_dpto", round(float(feat['magnitud_maxima'].max()), 2)))
    c4.metric("Población expuesta", f"{est.get('poblacion_total', int(feat['poblacion_actual'].sum())):,}")
    st.subheader("Fuentes oficiales utilizadas")
    st.table(pd.DataFrame([
        {"Fuente": "SGC — Catálogo de Sismicidad 1993-2018", "Registros": "111.908 eventos (bbox Santander)"},
        {"Fuente": "SGC — Catálogo 2018-hoy (SeisComP)", "Registros": "110.177 eventos (bbox Santander)"},
        {"Fuente": "DANE — DIVIPOLA", "Registros": "87 municipios de Santander (cód. 68)"},
        {"Fuente": "DANE — Proyección de población 2020-2035", "Registros": "Población actual y 2035 por municipio"},
        {"Fuente": "UNGRD — Emergencias 2019-2024 + 2025", "Registros": "38.869 registros nacionales filtrados a Santander"},
    ]))
    st.subheader("Distribución del riesgo")
    if "riesgo" in base.columns:
        st.bar_chart(base["riesgo"].value_counts())
    if metricas:
        st.info(f"Modelo ganador: **{metricas.get('mejor_modelo')}** · "
                f"Accuracy {metricas.get('accuracy')} · F1-macro {metricas.get('f1_macro')}")

# ================= ANÁLISIS SÍSMICO =================
elif page == "Análisis Sísmico":
    st.title("Análisis Sísmico Instrumental")
    if len(sismos):
        por_anio = sismos.groupby("anio").size().reset_index(name="sismos")
        st.plotly_chart(px.bar(por_anio, x="anio", y="sismos", title="Sismos por año (Santander + área de influencia)"),
                        use_container_width=True)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.histogram(sismos, x="mag", nbins=40, title="Distribución de magnitudes"), use_container_width=True)
        c2.plotly_chart(px.histogram(sismos, x="prof_km", nbins=40, title="Distribución de profundidades (km)"),
                        use_container_width=True)
        sample = sismos.dropna(subset=["lat", "lon"]).sample(min(5000, len(sismos)), random_state=42)
        st.plotly_chart(px.scatter_geo(sample, lat="lat", lon="lon", color="mag", size="mag",
                                        scope="south america", title="Distribución espacial (muestra 5.000 eventos)",
                                        color_continuous_scale="Reds"), use_container_width=True)
    st.subheader("Top 15 municipios por sismicidad")
    top = feat.nlargest(15, "cantidad_total_sismos")[["municipio", "cantidad_total_sismos", "magnitud_maxima"]]
    st.plotly_chart(px.bar(top, x="municipio", y="cantidad_total_sismos", hover_data=["magnitud_maxima"],
                            title="Eventos acumulados por municipio", color="cantidad_total_sismos",
                            color_continuous_scale="Reds"), use_container_width=True)

# ================= RIESGO =================
elif page == "Riesgo":
    st.title("Clasificación de Riesgo Municipal")
    if metricas:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Modelo", metricas.get("mejor_modelo", "-"))
        c2.metric("Accuracy", metricas.get("accuracy", "-"))
        c3.metric("Precision", metricas.get("precision_macro", "-"))
        c4.metric("F1-score", metricas.get("f1_macro", "-"))
        with st.expander("Comparación de algoritmos (F1-macro CV)"):
            comp = metricas.get("comparacion_modelos_f1_cv", {})
            st.bar_chart(pd.Series(comp))
        with st.expander("Importancia de variables"):
            imp = metricas.get("top_importancias", [])
            if imp:
                st.table(pd.DataFrame(imp))
        mp = PROC / "matriz_confusion.png"
        if mp.exists():
            st.image(str(mp), caption="Matriz de confusión (test)")
    if metricas_clu:
        with st.expander(f"Clustering no supervisado — {metricas_clu.get('mejor_modelo')} "
                         f"(silhouette {metricas_clu.get('silhouette')})"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Clústeres", metricas_clu.get("n_clusters", "-"))
            c2.metric("ARI vs supervisado", metricas_clu.get("ari_vs_supervisado", "-"))
            c3.metric("Acuerdo de nivel", metricas_clu.get("acuerdo_nivel_vs_supervisado", "-"))
            if len(clusters):
                st.plotly_chart(px.scatter(clusters, x="pca1", y="pca2", color="cluster",
                                            hover_data=["municipio", "cluster_riesgo"],
                                            title="Municipios en espacio PCA-2D por clúster",
                                            color_continuous_scale="Viridis"), use_container_width=True)
                for cl, prof in metricas_clu.get("perfiles", {}).items():
                    st.markdown(f"**Clúster {cl}** (nivel {prof['nivel_asociado']}, "
                                f"{prof['n_municipios']} municipios): "
                                + "; ".join(prof["rasgos_distintivos"][:3]))
    filtro = st.multiselect("Filtrar por nivel", ["Bajo", "Medio", "Alto"], default=["Bajo", "Medio", "Alto"])
    cols = ["municipio", "riesgo", "indice_riesgo", "cantidad_total_sismos", "magnitud_maxima",
            "poblacion_actual", "emergencias_totales"]
    st.dataframe(base[base["riesgo"].isin(filtro)][[c for c in cols if c in base.columns]]
                 .sort_values("indice_riesgo", ascending=False), use_container_width=True)

# ================= RL =================
elif page == "Aprendizaje por Refuerzo":
    st.title("Priorización con Aprendizaje por Refuerzo 🤖")
    if rl_meta or (ROOT / "models" / "rl_meta.json").exists():
        meta = rl_meta or json.loads((ROOT / "models" / "rl_meta.json").read_text(encoding="utf-8"))
        st.success(f"Agente ganador: **{meta.get('ganador')}** · "
                   f"Recompensas: {meta.get('recompensas_medias')}")
    st.markdown("**Entorno Gymnasium**: estado = features del municipio · acciones = {priorizar, no priorizar} · "
                "recompensa proporcional a actividad sísmica + población expuesta + emergencias históricas.")
    if len(ranking):
        st.subheader("🏆 Ranking de municipios prioritarios")
        st.dataframe(ranking.head(20)[["puesto", "municipio", "score_rl_100", "indice_riesgo"]],
                     use_container_width=True)
        st.plotly_chart(px.bar(ranking.head(15), x="municipio", y="score_rl_100",
                                title="Top 15 priorizados por RL (score 0-100)",
                                color="indice_riesgo", color_continuous_scale="Reds"),
                        use_container_width=True)

# ================= MAPAS =================
elif page == "Mapas":
    st.title("Mapas de Riesgo 🗺️")
    color = {"Alto": "red", "Medio": "orange", "Bajo": "green"}
    m = folium.Map(location=[6.9, -73.3], zoom_start=8, tiles="CartoDB positron")
    for _, r in base.iterrows():
        if not r.get("lat_mpio") or not r.get("lon_mpio"):
            continue
        folium.CircleMarker([r["lat_mpio"], r["lon_mpio"]], radius=4 + 10 * float(r.get("indice_riesgo", 0)),
                             color=color.get(r.get("riesgo", "Medio"), "orange"),
                             fill=True, fill_opacity=0.6,
                             popup=f"{r['municipio']}: {r.get('riesgo')} ({float(r.get('indice_riesgo', 0)):.2f})").add_to(m)
    if len(sismos):
        heat = sismos.dropna(subset=["lat", "lon"]).sample(min(2000, len(sismos)), random_state=7)
        for _, s in heat.iterrows():
            folium.CircleMarker([s["lat"], s["lon"]], radius=1.5, color="darkred",
                                 fill=True, fill_opacity=0.35).add_to(m)
    components.html(m.get_root().render(), height=600)

# ================= INSIGHTS =================
else:
    st.title("Insights Automáticos 💡")
    for i, ins in enumerate(analitica.get("insights", []), 1):
        st.info(f"**{i}.** {ins}")
    st.subheader("Top 10 mayor riesgo")
    st.table(pd.DataFrame(analitica.get("top10_riesgo", [])))
    st.subheader("Top 10 priorizados por RL")
    st.table(pd.DataFrame(analitica.get("top10_rl", [])))
