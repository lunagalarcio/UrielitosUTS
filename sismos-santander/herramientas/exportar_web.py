"""
DEPRECADO — script legacy del repo Hackathon-uts (176 municipios, reports/, dataset_santander.csv).
No usar en UrielitosUTS-main. Usar en su lugar: scripts/exportar_frontend.py
  $env:PYTHONPATH="<repo>"; python scripts/exportar_frontend.py [--mag-min 2.0]
Este archivo se conserva solo como referencia histórica.
---
Exporta los resultados del pipeline del equipo (repositorio Hackathon-uts) a un
archivo JavaScript que la página web lee sin servidor: data/resultados_equipo.js

Uso:
    python herramientas/exportar_web.py RUTA_AL_REPO_Hackathon-uts

Lee (sin modificarlos):
  data/processed/*.csv, reports/*.json, reports/curva_aprendizaje_rl.csv,
  docs/diccionario_datos.csv, data/raw/metadata_*.json,
  data/raw/sgc_1993_2018.csv, data/raw/sgc_2018_hoy.csv, data/raw/dane_divipola.csv
"""
import csv, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(sys.argv[1])
SALIDA = Path(__file__).resolve().parents[1] / "data" / "resultados_equipo.js"
MAG_MIN_EVENTOS = 2.0          # sismos que se guardan para mapas y boletines
RMS_MAX, ERR_PROF_MAX = 2.0, 50.0  # mismo criterio de atípico del equipo
BOX = dict(lat_min=5.7, lat_max=8.2, lon_min=-74.6, lon_max=-72.4)


def leer_csv(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        v = float(str(x).replace(",", "."))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def redondear(v, d=4):
    return None if v is None else round(v, d)


# ---------- Municipios (176 dentro de la caja) y clusters ----------
clusters = leer_csv(REPO / "data/processed/clusters_municipios.csv")
municipios = []
for c in clusters:
    fila = {"cod": c["cod_mpio"], "nombre": c["nom_mpio"], "dpto": c["dpto"], "santander": c["es_santander"] == "1",
            "lat": num(c["lat"]), "lon": num(c["lon"]), "cluster": int(c["cluster"]), "cluster_nombre": c["cluster_nombre"],
            "pca1": redondear(num(c["pca1"])), "pca2": redondear(num(c["pca2"]))}
    for k in ["tasa_m25_anual", "tasa_m30_anual", "tasa_m35_anual", "mag_max", "mag_media", "b_value", "prof_media_km",
              "pct_superficial", "pct_intermedio", "log_energia_anual", "fraccion_anios_activos"]:
        fila[k] = redondear(num(c[k]))
    municipios.append(fila)
cod_a_indice = {m["cod"]: i for i, m in enumerate(municipios)}

# ---------- Tabla única: fila 2025 de cada municipio y serie de n_m25 ----------
dataset = leer_csv(REPO / "data/processed/dataset_santander.csv")
columnas_dataset = list(dataset[0].keys())
ultima = {}
serie = {}
for r in dataset:
    serie.setdefault(r["cod_mpio"], {})[int(r["anio"])] = int(float(r["n_m25"]))
    if r["anio"] == "2025":
        ultima[r["cod_mpio"]] = {k: (num(v) if k not in ("cod_mpio", "nom_mpio", "dpto", "nivel_actividad_t1") else v) for k, v in r.items()}
anios = sorted({int(r["anio"]) for r in dataset})

# ---------- Predicciones del modelo supervisado (walk-forward) ----------
predicciones = {}
historico = {}
for r in leer_csv(REPO / "data/processed/predicciones_supervisado.csv"):
    if r["anio"] == "2025":   # fila 2025 → nivel previsto para 2026
        predicciones[r["cod_mpio"]] = {"p_bajo": redondear(num(r["p_bajo"])), "p_medio": redondear(num(r["p_medio"])),
                                       "p_alto": redondear(num(r["p_alto"])), "pred": r["pred"]}
    historico.setdefault(r["cod_mpio"], []).append([int(r["anio"]) + 1, r["pred"], r["y_true"]])

# ---------- Priorización 2026 del agente RL ----------
priorizacion = []
for r in leer_csv(REPO / "data/processed/priorizacion_2026.csv"):
    priorizacion.append({k: (num(v) if k not in ("cod_mpio", "nom_mpio", "confianza", "cluster_nombre") else v) for k, v in r.items()})

# ---------- Métricas ----------
met_sup = json.load(open(REPO / "reports/metricas_supervisado.json", encoding="utf-8"))
met_nosup = json.load(open(REPO / "reports/metricas_no_supervisado.json", encoding="utf-8"))
met_rl = json.load(open(REPO / "reports/metricas_rl.json", encoding="utf-8"))

# Curva de aprendizaje: promedio entre semillas por época
curva = {}
for r in leer_csv(REPO / "reports/curva_aprendizaje_rl.csv"):
    e = int(r["epoca"])
    c = curva.setdefault(e, {"rec": [], "val": []})
    if num(r["recompensa_train"]) is not None: c["rec"].append(num(r["recompensa_train"]))
    if num(r["pct_oraculo_val"]) is not None: c["val"].append(num(r["pct_oraculo_val"]))
curva_media = [{"epoca": e, "recompensa": redondear(sum(v["rec"]) / len(v["rec"])) if v["rec"] else None,
                "pct_oraculo_val": redondear(sum(v["val"]) / len(v["val"])) if v["val"] else None} for e, v in sorted(curva.items())]

diccionario = leer_csv(REPO / "docs/diccionario_datos.csv")
meta_sgc = json.load(open(REPO / "data/raw/metadata_descarga_sgc.json", encoding="utf-8"))
meta_otras = json.load(open(REPO / "data/raw/metadata_fuentes_complementarias.json", encoding="utf-8"))

# ---------- Sismos (para mapas y boletines) ----------
# Mismas reglas del equipo: sin atípicos, municipio = cabecera más cercana (de las 176 de la caja)
cabeceras = [(m["lat"], m["lon"], m["cod"]) for m in municipios]


def distancia_km(a, b, c, d):
    r = math.pi / 180
    h = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


# rejilla simple para acelerar la búsqueda de la cabecera más cercana
rejilla = {}
for la, lo, cod in cabeceras:
    rejilla.setdefault((int(la * 4), int(lo * 4)), []).append((la, lo, cod))


def cabecera_cercana(la, lo):
    mejor, md = None, 1e9
    ci, cj = int(la * 4), int(lo * 4)
    for di in (-2, -1, 0, 1, 2):
        for dj in (-2, -1, 0, 1, 2):
            for a, b, cod in rejilla.get((ci + di, cj + dj), []):
                d = distancia_km(la, lo, a, b)
                if d < md: md, mejor = d, cod
    if mejor is None:
        for a, b, cod in cabeceras:
            d = distancia_km(la, lo, a, b)
            if d < md: md, mejor = d, cod
    return mejor


eventos = []
conteo = {"leidos": 0, "atipicos": 0, "fuera_caja": 0, "bajo_mag": 0, "duplicados": 0}
vistos = set()


def agregar(fecha, la, lo, prof, mag, rms, errp):
    conteo["leidos"] += 1
    if None in (la, lo, prof, mag) or fecha is None: return
    if (rms is not None and rms > RMS_MAX) or (errp is not None and errp > ERR_PROF_MAX):
        conteo["atipicos"] += 1; return
    if not (BOX["lat_min"] <= la <= BOX["lat_max"] and BOX["lon_min"] <= lo <= BOX["lon_max"]):
        conteo["fuera_caja"] += 1; return
    if mag < MAG_MIN_EVENTOS:
        conteo["bajo_mag"] += 1; return
    clave = (fecha, la, lo, prof, mag)
    if clave in vistos:
        conteo["duplicados"] += 1; return
    vistos.add(clave)
    cod = cabecera_cercana(la, lo)
    if not cod.startswith("68"): return          # solo municipios de Santander para los boletines
    minutos = int(fecha.timestamp() // 60)
    eventos.append([minutos, round(la, 3), round(lo, 3), round(prof, 1), round(mag, 1), cod_a_indice[cod]])


def fecha_de(texto):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


for r in leer_csv(REPO / "data/raw/sgc_1993_2018.csv"):
    hora = (r.get("HORA_UTC") or "00:00:00").strip()
    agregar(fecha_de(f"{r['FECHA'].strip()} {hora}"), num(r["LATITUD (grados)"]), num(r["LONGITUD (grados)"]),
            num(r["PROFUNDIDAD (Km)"]), num(r["MAGNITUD Ml"]), num(r["RMS (Seg)"]), num(r["ERROR PROFUNDIDAD (Km)"]))
for r in leer_csv(REPO / "data/raw/sgc_2018_hoy.csv"):
    agregar(fecha_de(r["fecha_hora_utc"]), num(r["lat"]), num(r["lon"]), num(r["prof_km"]), num(r["mag"]),
            num(r["rms_s"]), num(r["err_prof_km"]))
eventos.sort()

resultado = {
    "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    "repositorio": "github.com/JuanCastellanos1/Hackathon-uts",
    "fuentes": {"sgc": meta_sgc, "otras": meta_otras},
    "anios": anios,
    "municipios": municipios,
    "fila_2025": ultima,
    "columnas_dataset": columnas_dataset,
    "serie_n_m25": serie,
    "prediccion_2026": predicciones,
    "historico_predicciones": historico,
    "priorizacion_2026": priorizacion,
    "metricas_supervisado": met_sup,
    "metricas_no_supervisado": met_nosup,
    "metricas_rl": {k: v for k, v in met_rl.items() if k != "curva_aprendizaje"},
    "curva_rl": curva_media,
    "diccionario": diccionario,
    "eventos_info": {"mag_min": MAG_MIN_EVENTOS, "conteo": conteo, "n": len(eventos),
                     "formato": "[minutos desde 1970 UTC, lat, lon, prof_km, mag, índice de municipio]"},
    "eventos": eventos,
}
texto = ("// Resultados del pipeline del equipo (Hackathon-uts), exportados con herramientas/exportar_web.py.\n"
         "// No editar a mano: volver a correr el script si cambian los resultados.\n"
         "var RESULTADOS = " + json.dumps(resultado, ensure_ascii=False, separators=(",", ":")) + ";\n")
SALIDA.write_text(texto, encoding="utf-8")
print(f"[exportar_web] {SALIDA} · {len(texto)/1e6:.1f} MB · {len(eventos)} sismos de Santander M≥{MAG_MIN_EVENTOS} · {conteo}")
