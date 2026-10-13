# 🌋 Plataforma de Riesgo Sísmico — Santander (Colombia)

Clasificación del riesgo sísmico municipal y priorización inteligente con **Aprendizaje por Refuerzo**,
construida con datos oficiales: **SGC** (catálogo de sismicidad), **DANE** (DIVIPOLA + proyecciones de población)
y **UNGRD** (emergencias).

## Arquitectura

```text
project/
├─ data/raw/            # fuentes oficiales (ya descargadas)
├─ data/processed/      # dataset maestro, features, rankings, métricas
├─ models/              # clasificador + agente RL + metadatos
├─ rl/                  # entorno Gymnasium + agentes PPO/DQN
├─ src/
│  ├─ preprocessing/    # limpieza SGC, DIVIPOLA, población, emergencias, master
│  ├─ features/         # 30+ variables + índices de exposición/vulnerabilidad/riesgo
│  ├─ training/         # etiquetado + selección automática (RF/XGB/LGBM/GB)
│  ├─ evaluation/       # analítica, insights, gráficas
│  └─ utils/            # logging, validación, normalización
├─ dashboard/           # (reservado; app principal en app.py)
├─ scripts/run_pipeline.py
├─ app.py               # dashboard Streamlit (6 páginas)
└─ requirements.txt
```

## Uso

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py --episodes 120
streamlit run app.py
```

> El pipeline funciona solo con `pandas + numpy + scikit-learn`. `xgboost`, `lightgbm`,
> `gymnasium`, `stable-baselines3` y `torch` son opcionales: si están instalados se usan,
> si no, el sistema usa `GradientBoosting`/`HistGradientBoosting` y agentes RL propios (numpy).

## Fases

1. **Procesamiento**: unificación SGC 1993-2018 + 2018-hoy, join espacial por cercanía haversiana
   cuando el nombre no matchea DIVIPOLA, llave maestra = código DIVIPOLA.
2. **Features**: 30+ variables (sismicidad, profundidad, temporalidad, exposición, emergencias)
   + `indice_exposicion`, `indice_vulnerabilidad`, `indice_riesgo`.
3. **Clasificación**: Bajo/Medio/Alto por terciles del índice; selección automática del mejor
   (RF, XGBoost, LightGBM, GradientBoosting); guarda accuracy/precision/recall/F1 + matriz.
4. **RL**: entorno Gymnasium (priorizar/no priorizar, recompensa ∝ riesgo+exposición+emergencias);
   compiten PPO-style y DQN; ranking 0-100 por municipio.
5. **Analítica**: Top-10 riesgo, Top-10 RL, estadísticas e insights automáticos.
6. **Dashboard**: Streamlit con Inicio, Análisis Sísmico, Riesgo, RL, Mapas (Folium) e Insights.
