# SPEC — Plataforma de Riesgo Sísmico Santander

Versión: 1.0 | Fecha: 2026-10-13 | Estado: implementado (`app.py`, `scripts/run_pipeline.py`)

## 1. Objetivo

Clasificar el riesgo sísmico de los 87 municipios de Santander (cód. DANE 68) en `Bajo/Medio/Alto` y generar un ranking operativo de priorización con RL para gestión del riesgo.

Fuentes oficiales obligatorias: **SGC** (2 catálogos), **DANE** (DIVIPOLA + proyección 2020-2035), **UNGRD** (emergencias 2019-2024 + 2025).

## 2. Alcance

Incluye: limpieza, join espacial haversiano, 32 features, 3 índices, clasificador supervisado, clustering contraste, entorno RL + PPO/DQN, analítica, dashboard Streamlit de 6 páginas responsive.

No incluye: predicción de sismos en tiempo real, PGA/GMF, análisis estructural edificio por edificio.

## 3. Arquitectura

`data/raw → src/preprocessing → data/processed/sismos_limpios.csv + municipios_master.csv → src/features → features_municipio.csv → src/training/label_risk (terciles) → train_classifier / clustering → rl/train_rl → src/evaluation/analytics+plots → app.py`

Llave maestra: `cod_mpio` DIVIPOLA (string, ej. `68418`). `RANDOM_STATE=42` global (`src/config.py`).

## 4. Datos

### 4.1 Raw (`src/config.py:14-20`)

| Archivo | Contenido esperado |
|---|---|
| `sgc_1993_2018.csv` | 111.908 eventos bbox Santander |
| `sgc_2018_hoy.csv` | 110.177 eventos SeisComP |
| `dane_divipola.csv` | 87 municipios, `cod_mpio, municipio, lat, lon` |
| `dane_proyeccion...xlsx` | población actual + 2035 |
| `ungrd_emergencias_2019_2024.csv` + `...2025.csv` | 38.869 registros nacionales → filtrar Santander |

### 4.2 Processed — contratos

`features_municipio.csv`: `cod_mpio, municipio, cantidad_total_sismos, magnitud_{promedio,maxima,minima,std}, pct_mag>4, pct_mag>5, energia_sismica_acum, profundidad_{...}, pct_superficiales, frecuencia_anual, sismos_{10a,5a,2a}, tendencia, crecimiento_frec, poblacion_{actual,proyectada}, crecimiento_pob, log_poblacion, emergencias_{totales,sismicas,por_anio}, fallecidos, heridos, personas_afectadas, lat_mpio, lon_mpio, idx_actividad, indice_{exposicion,vulnerabilidad,riesgo}`.

`riesgo_labels.csv`: `cod_mpio, municipio, indice_riesgo, riesgo ∈ {Bajo,Medio,Alto}` (29/29/29).

`ranking_rl.csv`: `cod_mpio, municipio, indice_riesgo, score_rl, score_rl_100 [0-100], puesto [1-87]`.

`metricas_clasificacion.json`, `metricas_clustering.json`, `analitica.json`, `curva_rl.csv`, `matriz_confusion.png`.

## 5. Features e índices

32 variables primarias (ver lista en `models/risk_classifier_meta.json:features`). Índices compuestos `[0-1]`:

* `indice_exposicion` = f(población, log_pob, crecimiento)
* `indice_vulnerabilidad` = f(emergencias, fallecidos, heridos, afectados)
* `indice_riesgo` = f(idx_actividad, exposición, vulnerabilidad) → única fuente de etiqueta.

Regla anti-fuga: `LEAK_COLS = {idx_actividad, indice_exposicion, indice_vulnerabilidad, indice_riesgo}` nunca entran al `X` del clasificador/clustering.

## 6. Modelos

### 6.1 Clasificador `src/training/train_classifier.py`

* Candidatos: `RandomForest(300, balanced) | GradientBoosting | HistGradientBoosting | LogisticRegression(balanced, 2000 it) | XGBoost(300, d6, lr0.05) | LightGBM(300, lr0.05)` — últimos dos solo si instalados. Todos en `Pipeline(StandardScaler, clf)`.
* Split: `train_test_split(0.25, stratify, seed 42)` + `StratifiedKFold(5)` en train.
* Selección: mayor `F1-macro CV`. Reporte test: `accuracy, precision_macro, recall_macro, f1_macro, confusion_matrix`.
* Actual: ganador `XGBoost F1-CV 0.6812, Acc 0.9091, F1 0.9079`. Matriz `[[7,0,0],[1,6,0],[0,1,7]]`.
* Artefactos: `models/risk_classifier.pkl {pipeline, features, classes}`, `risk_classifier_meta.json`, `data/processed/predicciones_riesgo.csv {cod, riesgo, riesgo_pred, proba_alto}`.
* Criterio aceptación: `F1-macro test ≥ 0.75`, sin confusión Bajo↔Alto.

### 6.2 Clustering `src/training/clustering.py`

* `log1p` en cols skew>1.5 + `StandardScaler`. Candidatos `KMeans k=3,4,5,6 | Aglomerativo k=3 | DBSCAN eps 0.8,1.2,1.6 (min_samples 3)`.
* Selección: mayor `silhouette`. Mapeo clúster→nivel por `indice_riesgo` medio. PCA-2D para plot.
* Actual: `Aglomerativo_k3 silhouette 0.1999, ARI 0.4085, acuerdo 64.4%`.

### 6.3 RL `rl/env_sismo.py`, `rl/agents.py`, `rl/train_rl.py`

* Env `SismoPrioridadEnv(gym.Env)`: episodio = 87 pasos orden aleatorio. `obs = Xn[i] + [frac,1-frac]`, `Box(-10,10)`, `Discrete(2)`.
* Recompensa: `R(1)=2r-1+0.5·e·r`, `R(0)=0.3(1-r)-0.7r`.
* Agentes propios: `PolicyGradientAgent(obs_dim, lr0.05, h64)` REINFORCE+baseline+clip; `DQNAgent` con `MLPRegressor(64,32,tanh,max_iter1,warm_start)` + buffer 5000, `gamma 0.95`, `batch 64`, `eps 1.0→0.05`. Opcional SB3 `PPO/DQN MlpPolicy 8000 steps`.
* Entrenamiento: `episodes=120` (`--episodes` CLI). Evaluación: media 10 episodios deterministas. Ganador = max.
* Actual: `DQN 9.857 > PPO 9.135`.
* Ranking: `score = Q1-Q0 (propio) o predict() (SB3)` → normalizado `0-100` → `puesto`. **Limitación conocida:** con SB3 el score es binario `0/1` → 33 empates en 100.0; para desempate usar `Q1-Q0` continuo.
* Artefactos: `models/rl_agent.pkl`, `models/rl_{ppo,dqn}_sb3.zip`, `models/rl_meta.json`.

## 7. Dashboard `app.py` — 6 páginas

`Inicio | Análisis Sísmico | Riesgo | Aprendizaje por Refuerzo | Mapas | Insights`. `layout="wide"`, todo Plotly con `use_container_width=True`, Folium centro `[6.9,-73.3] zoom 8`, `CircleMarker radio=4+10*riesgo`, colores `Alto red / Medio orange / Bajo green`.

### 7.1 Spec responsive (obligatorio)

* CSS en `app.py:18-37`: `.block-container max 1200px`, `img/iframe width 100%`, tablas con scroll-x.
* Breakpoints: `≤768px` columnas 45% (2 por fila), títulos `h1 1.4rem`; `≤480px` 1 columna.
* Imágenes README/docs con `style="width:100%;height:auto;border-radius:12px"`.
* Aceptación: sin scroll horizontal en 360px, mapa visible, tablas con scroll interno.

## 8. Pipeline

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py --episodes 120
streamlit run app.py
```

Mínimo: `pandas+numpy+scikit-learn`. Opcionales con fallback: `xgboost, lightgbm, gymnasium, stable-baselines3, torch, folium, plotly`.

## 9. Riesgos

* Dataset pequeño (n=87) → varianza CV alta; mitigado con stratify + F1-macro.
* Outlier Los Santos (104k sismos) → mitigado con log1p en clustering, pero domina `indice_riesgo`.
* Ranking RL binario actual → documentado en §6.3, fix propuesto.

## 10. Definiciones (glosario)

* `r` = indice_riesgo, `e` = indice_exposicion. `score_rl_100` = prioridad operativa 0-100 (≠ probabilidad). `proba_alto` = P(clase Alto) del clasificador.
