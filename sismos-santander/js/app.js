// =============================================================
// app.js — muestra los resultados del pipeline del equipo
// (Hackathon-uts) en la página: mapa de riesgo, modelo supervisado,
// grupos territoriales, agente de refuerzo, boletines y fuentes.
// Los datos vienen de data/resultados_equipo.js (variable RESULTADOS).
// =============================================================

const R = RESULTADOS;
const $ = id => document.getElementById(id);
const graficas = {};
const mapas = {};
const COLORES_GRUPO = ["#c8102e", "#006b3f", "#ffd100", "#2f6f9f", "#7b5aa6", "#64748b", "#e07b39"];
// Mapeo verificado con data/resultados_equipo.js + clusters_municipio.csv:
// cluster 0 = Grupo 1 (riesgo alto) -> rojo, cluster 1 = Grupo 2 (bajo) -> verde, cluster 2 = Grupo 3 (medio) -> amarillo.
// Se usa colorGrupo() (por nombre, no por id) para que no se rompa si el clustering reasigna ids.
function colorGrupo(mOrNombre, clusterId) {
  const n = String(typeof mOrNombre === "string" ? mOrNombre : (mOrNombre && mOrNombre.cluster_nombre) || mOrNombre || "").toLowerCase();
  if (n.includes("alto")) return "#c8102e";
  if (n.includes("bajo")) return "#006b3f";
  if (n.includes("medio")) return "#ffd100";
  const c = Number(typeof mOrNombre === "object" && mOrNombre !== null && mOrNombre.cluster !== undefined ? mOrNombre.cluster : clusterId) || 0;
  return COLORES_GRUPO[c % COLORES_GRUPO.length];
}
const NIVELES = { bajo: "Bajo", medio: "Medio", alto: "Alto" };

const estado = {
  K: 10,
  evacuacion: {},
  porCodigo: {},
  santander: [],
  fechaFin: null
};

// ---------- Preparación de los datos ----------
R.municipios.forEach((m, i) => {
  m.indice = i;
  m.nombreBonito = nombreMunicipio(m);
  estado.porCodigo[m.cod] = m;
});
estado.santander = R.municipios.filter(m => m.santander);
estado.fechaFin = new Date(R.eventos[R.eventos.length - 1][0] * 60000);
const PRIORIDAD = {};
R.priorizacion_2026.forEach(p => { PRIORIDAD[p.cod_mpio] = p; });

// Nombre con mayúsculas y tildes como en la cartografía (los datos del equipo vienen en mayúsculas)
function nombreMunicipio(m) {
  if (typeof GEO_MUNICIPIOS !== "undefined") {
    const f = GEO_MUNICIPIOS.features.find(x => x.properties.codigo_dane === m.cod);
    if (f) return f.properties.municipio;
  }
  return tipoTitulo(m.nombre);
}
function nombreVariable(clave) {
  const d = R.diccionario.find(x => x.variable === clave);
  return d ? d.descripcion : clave;
}
function eventosDe(cod) {
  const i = estado.porCodigo[cod].indice;
  return R.eventos.filter(e => e[5] === i);
}

// ---------- Ayudas de interfaz ----------
function mostrarMensaje(texto, tipo) {
  const m = $("mensaje");
  m.className = "mensaje " + (tipo || "info");
  m.innerHTML = texto;
}
function cifra(valor, rotulo, clase) {
  return '<div class="cifra ' + (clase || "") + '"><div class="valor">' + valor + '</div><div class="rotulo">' + rotulo + "</div></div>";
}
function pct(v) { return redondear(v * 100, 1) + " %"; }
function etiquetaNivel(n) { const t = NIVELES[n] || n; return '<span class="nivel ' + t + '">' + t + "</span>"; }
function colorVariable(nombre) { return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim(); }
function colorNivel(n) { return colorVariable({ bajo: "--bajo", medio: "--medio", alto: "--alto" }[n]); }

function dibujarGrafica(id, configuracion) {
  if (graficas[id]) graficas[id].destroy();
  graficas[id] = new Chart($(id), configuracion);
}
function aplicarColoresGraficas() {
  if (!window.Chart) return;
  Chart.defaults.color = colorVariable("--suave");
  Chart.defaults.borderColor = colorVariable("--linea");
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
}

// Mapa con imagen satelital (por defecto), mapa de calles y capa de fallas activas
function crearMapa(id) {
  $(id).classList.remove("oculto");
  if (mapas[id]) {
    const borrar = [];
    mapas[id].eachLayer(c => {
      const fijo = c.options && c.options.fijo;
      if (!fijo && !(c instanceof L.TileLayer) && !(c instanceof L.LayerGroup && !(c instanceof L.FeatureGroup))) borrar.push(c);
    });
    borrar.forEach(c => mapas[id].removeLayer(c));
    return mapas[id];
  }
  const mapa = L.map(id, { maxZoom: 19 }).setView([6.9, -73.3], 8);
  const satelite = L.tileLayer(URL_SATELITE, { maxZoom: 19, attribution: "Imágenes © Esri, Maxar, Earthstar Geographics" });
  const nombres = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Nombres © Esri" });
  const calles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, subdomains: "abc", attribution: "© OpenStreetMap" });
  const base = L.layerGroup([satelite, nombres]).addTo(mapa);
  const fallas = L.layerGroup();
  if (typeof FALLAS_ACTIVAS !== "undefined") {
    for (const f of FALLAS_ACTIVAS.features) {
      for (const linea of f.geometry.coordinates) {
        L.polyline(linea.map(c => [c[1], c[0]]), { color: "#ff7a00", weight: 2, dashArray: "6 4", fijo: true })
          .bindTooltip("Falla activa: " + f.properties.nombre).addTo(fallas);
      }
    }
    fallas.addTo(mapa);
  }
  L.control.layers({ "Satélite": base, "Mapa de calles": calles }, { "Fallas activas": fallas }, { collapsed: window.innerWidth <= 860 }).addTo(mapa);
  mapa.on("baselayerchange", () => setTimeout(() => mapa.invalidateSize(), 100));
  mapas[id] = mapa;
  return mapa;
}

// Polígono de un municipio de Santander (cartografía IGAC/DANE incluida)
function poligono(cod) {
  if (typeof GEO_MUNICIPIOS === "undefined") return null;
  return GEO_MUNICIPIOS.features.find(f => f.properties.codigo_dane === cod) || null;
}

function conectarBotonBoletin(mapa) {
  mapa.off("popupopen").on("popupopen", ev => {
    const b = ev.popup.getElement().querySelector("[data-boletin-mapa]");
    if (b) b.onclick = () => generarPdfMunicipio(b.dataset.boletinMapa);
  });
}

// ---------- Navegación, menú y tema ----------
function irASeccion(tab) {
  const boton = document.querySelector('#pestanas button[data-tab="' + tab + '"]');
  document.querySelectorAll("#pestanas button").forEach(b => b.classList.remove("activa"));
  boton.classList.add("activa");
  document.querySelectorAll(".tab").forEach(t => t.classList.add("oculto"));
  $("tab-" + tab).classList.remove("oculto");
  $("tituloSeccion").textContent = boton.dataset.titulo;
  $("app").classList.remove("menu-abierto");
  for (const k in mapas) setTimeout(() => mapas[k].invalidateSize(), 50);
}
document.querySelectorAll("#pestanas button").forEach(b => b.addEventListener("click", () => irASeccion(b.dataset.tab)));

$("botonMenu").addEventListener("click", () => {
  if (window.innerWidth <= 860) $("app").classList.toggle("menu-abierto");
  else $("app").classList.toggle("menu-cerrado");
  setTimeout(() => { for (const k in mapas) mapas[k].invalidateSize(); }, 300);
});
$("velo").addEventListener("click", () => $("app").classList.remove("menu-abierto"));

$("botonTema").addEventListener("click", () => {
  const nuevo = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nuevo;
  try { localStorage.setItem("tema", nuevo); } catch (e) { /* sin almacenamiento */ }
  aplicarColoresGraficas();
  mostrarTodo();
});

$("kPriorizar").addEventListener("input", () => {
  estado.K = Number($("kPriorizar").value);
  $("kValor").textContent = "K = " + estado.K;
  mostrarPanorama(); mostrarPriorizacion(); listarBoletines();
});

$("archivoEvacuacion").addEventListener("change", async () => {
  const archivo = $("archivoEvacuacion").files[0];
  if (!archivo) return;
  estado.evacuacion = leerEvacuacion(await archivo.text());
  mostrarMensaje("Puntos de encuentro cargados para " + Object.keys(estado.evacuacion).length + " municipios. Ya salen en sus boletines.");
  listarBoletines();
});

// =============================================================
// MAPA DE RIESGO
// =============================================================
function mostrarPanorama() {
  const pred = R.prediccion_2026;
  const conteo = { bajo: 0, medio: 0, alto: 0 };
  estado.santander.forEach(m => { if (pred[m.cod]) conteo[pred[m.cod].pred]++; });
  const sismos2025 = estado.santander.reduce((s, m) => s + (R.serie_n_m25[m.cod][2025] || 0), 0);
  const ms = R.metricas_supervisado;
  const rl = R.metricas_rl.test;

  $("panoramaCifras").innerHTML = '<div class="cifras">' +
    cifra(conteo.alto, "municipios con actividad alta prevista para 2026 (5 o más sismos M ≥ 2,0)", "alerta") +
    cifra(estado.K, "municipios priorizados por el agente RL", "precaucion") +
    cifra(sismos2025.toLocaleString("es-CO"), "sismos M ≥ 2,0 en Santander en 2025", "ok") +
    cifra(redondear(ms.test.f1_macro, 2), "F1-macro del modelo en prueba (azar: " + redondear(ms.lineas_base_test.azar.f1_macro, 2) + ")") +
    cifra(pct(rl.agente_rl.pct_oraculo), "del impacto óptimo que captura el agente (azar: " + pct(rl.azar.pct_oraculo) + ")") +
    "</div>";

  const mapa = crearMapa("mapaPanorama");
  const capas = {};
  const oscuro = document.documentElement.dataset.theme === "dark";
  const grupo = [];
  for (const m of estado.santander) {
    const f = poligono(m.cod);
    if (!f) continue;
    const p = pred[m.cod], pr = PRIORIDAD[m.cod];
    const priorizado = pr && pr.rango <= estado.K;
    const capa = L.geoJSON(f, {
      style: {
        color: priorizado ? (oscuro ? "#ffffff" : "#111827") : "#ffffff",
        weight: priorizado ? 3 : 0.8,
        fillColor: p ? colorNivel(p.pred) : colorVariable("--sin-datos"),
        fillOpacity: 0.6
      }
    }).addTo(mapa);
    capa.bindPopup(() => popupMunicipio(m));
    capa.bindTooltip(m.nombreBonito, { sticky: true });
    capas[m.cod] = capa;
    grupo.push(capa);
  }
  if (grupo.length && !mapa._ajustado) { mapa.fitBounds(L.featureGroup(grupo).getBounds(), { padding: [10, 10] }); mapa._ajustado = true; }
  conectarBotonBoletin(mapa);

  const lista = R.priorizacion_2026.slice(0, estado.K);
  $("listaRiesgo").className = "";
  $("listaRiesgo").innerHTML = lista.map(p => {
    const m = estado.porCodigo[p.cod_mpio];
    const nivel = pred[p.cod_mpio] ? pred[p.cod_mpio].pred : "";
    return '<div class="item-riesgo" data-cod="' + p.cod_mpio + '"><span class="puesto">#' + p.rango + "</span><div><b>" + m.nombreBonito +
      "</b><small>Confianza " + p.confianza + " · " + (p.poblacion_total || 0).toLocaleString("es-CO") + " hab. · " + p.n_m25_2025 + " sismos M ≥ 2,0 en 2025</small></div>" +
      etiquetaNivel(nivel) + "</div>";
  }).join("") + "<p class='nota'>Mueve K en Priorización para ver más o menos municipios.</p>";
  document.querySelectorAll(".item-riesgo").forEach(el => {
    el.onclick = () => {
      const capa = capas[el.dataset.cod];
      if (capa) { mapa.fitBounds(capa.getBounds(), { maxZoom: 11 }); capa.openPopup(); }
    };
  });
  setTimeout(() => mapa.invalidateSize(), 50);
}

function popupMunicipio(m) {
  const p = R.prediccion_2026[m.cod], pr = PRIORIDAD[m.cod], f = R.fila_2025[m.cod];
  return "<b>" + m.nombreBonito + "</b><br>Nivel previsto 2026: " + (p ? etiquetaNivel(p.pred) + " (P alto " + pct(p.p_alto) + ")" : "sin dato") +
    "<br>Prioridad: #" + (pr ? pr.rango : "—") + (pr && pr.rango <= estado.K ? " (priorizado)" : "") +
    "<br>Grupo: " + m.cluster_nombre +
    "<br>Sismos M ≥ 2,0 en 2025: " + (R.serie_n_m25[m.cod][2025] || 0) +
    "<br>Población (DANE 2020): " + (f && f.poblacion_total ? f.poblacion_total.toLocaleString("es-CO") : "—") +
    (m.santander ? "<br><button data-boletin-mapa='" + m.cod + "'>Descargar boletín</button>" : "");
}

// =============================================================
// MODELO SUPERVISADO
// =============================================================
function mostrarSupervisado() {
  const ms = R.metricas_supervisado, t = ms.test, b = ms.bootstrap_f1_test;
  let html = '<div class="cifras">' +
    cifra(redondear(t.f1_macro, 3), "F1-macro en prueba (25 %)<br>IC 95 %: " + redondear(b.p2_5, 3) + " – " + redondear(b.p97_5, 3), "ok") +
    cifra(pct(t.balanced_accuracy), "exactitud balanceada") +
    cifra(pct(t.recall_alto), "de los casos de actividad alta detectados (recall alto)", "alerta") +
    cifra(redondear(ms.lineas_base_test.azar.f1_macro, 3), "F1 del azar<br>(predecir al azar según las clases)") +
    cifra(redondear(ms.lineas_base_test.mayoritaria.f1_macro, 3), "F1 de la clase mayoritaria") +
    "</div>";
  html += "<p>Modelo elegido: <b>" + ms.modelo_elegido + "</b> (split estratificado 75/25, validación cruzada a 5 folds: F1-macro " + redondear(ms.val.f1_macro, 3) + "), escogido por F1-macro entre los algoritmos candidatos (Random Forest, Gradient Boosting, HistGradientBoosting y Regresión Logística; XGBoost/LightGBM si están instalados).</p>";

  html += "<h3>Definición de los niveles</h3><table><tr><th>Nivel</th><th>Índice de riesgo (50 % actividad + 30 % exposición + 20 % vulnerabilidad)</th><th class='num'>% en entrenamiento</th><th class='num'>% en prueba</th></tr>" +
    [["bajo", "tercil inferior"], ["medio", "tercil medio"], ["alto", "tercil superior"]].map(([n, r]) => "<tr><td>" + etiquetaNivel(n) + "</td><td>" + r + "</td><td class='num'>" +
      pct(ms.distribucion_clases.train[n]) + "</td><td class='num'>" + pct(ms.distribucion_clases.test[n]) + "</td></tr>").join("") + "</table>";

  html += '<h3>Prueba el modelo: entrada → resultado</h3><div class="dos-columnas"><div><label>Municipio <select id="selMunicipio">' +
    R.municipios.slice().sort((a, b) => (b.santander - a.santander) || a.nombreBonito.localeCompare(b.nombreBonito))
      .map(m => "<option value='" + m.cod + "'>" + m.nombreBonito + (m.santander ? "" : " (" + tipoTitulo(m.dpto) + ")") + "</option>").join("") +
    "</select></label><p class='nota'>Entrada: las variables del municipio en 2025. Resultado: el nivel previsto para 2026.</p><div id='entradaSup'></div></div>" +
    "<div><div id='resultadoSup'></div><div class='grafica' style='height:220px;margin-top:12px'><canvas id='grafSerie'></canvas></div></div></div>";

  html += '<div class="dos-columnas"><div><h3>Matriz de confusión en prueba (filas = real)</h3><table class="matriz"><tr><th></th><th>Bajo</th><th>Medio</th><th>Alto</th></tr>' +
    t.matriz_confusion.map((f, i) => "<tr><th>" + ["Bajo", "Medio", "Alto"][i] + "</th>" + f.map((v, j) => "<td class='" + (i === j ? "diag" : "") + "'>" + v + "</td>").join("") + "</tr>").join("") +
    "</table><h3>Métricas por clase</h3><table><tr><th>Clase</th><th class='num'>Precisión</th><th class='num'>Recall</th><th class='num'>F1</th><th class='num'>Casos</th></tr>" +
    ["bajo", "medio", "alto"].map(n => { const r = t.reporte[n]; return "<tr><td>" + etiquetaNivel(n) + "</td><td class='num'>" + pct(r.precision) + "</td><td class='num'>" + pct(r.recall) + "</td><td class='num'>" + pct(r["f1-score"]) + "</td><td class='num'>" + r.support + "</td></tr>"; }).join("") +
    "</table></div><div><h3>Importancia de variables (permutación en prueba)</h3><div class='grafica' style='height:380px'><canvas id='grafImportancia'></canvas></div></div></div>";

  $("basicoContenido").className = "";
  $("basicoContenido").innerHTML = html;

  const imp = Object.entries(ms.importancias).sort((a, b) => b[1] - a[1]).slice(0, 10);
  dibujarGrafica("grafImportancia", {
    type: "bar",
    data: { labels: imp.map(x => x[0]), datasets: [{ data: imp.map(x => x[1]), backgroundColor: "#006b3f" }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => nombreVariable(c[0].label) } } } }
  });
  $("selMunicipio").value = "68418";
  $("selMunicipio").onchange = mostrarPrediccion;
  mostrarPrediccion();
}

function mostrarPrediccion() {
  const cod = $("selMunicipio").value;
  const m = estado.porCodigo[cod], f = R.fila_2025[cod], p = R.prediccion_2026[cod];
  const claves = ["n_m25", "n_m25_prom_3a", "mag_max", "mag_max_historica", "prof_media_km", "pct_superficial", "dist_nido_km", "b_value"];
  $("entradaSup").innerHTML = "<table>" + claves.map(c => "<tr><td>" + nombreVariable(c) + "</td><td class='num'>" + redondear(f[c], 2) + "</td></tr>").join("") + "</table>";
  $("resultadoSup").innerHTML = '<div class="resultado"><div>Nivel previsto para 2026</div><div class="grande">' + etiquetaNivel(p.pred) + " " + m.nombreBonito + "</div>" +
    ["bajo", "medio", "alto"].map(n => "<div>" + NIVELES[n] + " " + pct(p["p_" + n]) + '</div><div class="barra"><div style="width:' + (p["p_" + n] * 100) + "%;background:" + colorNivel(n) + '"></div></div>').join("") + "</div>";
  const serie = R.serie_n_m25[cod];
  dibujarGrafica("grafSerie", {
    type: "bar",
    data: { labels: R.anios, datasets: [{ label: "Sismos M ≥ 2,0 por año", data: R.anios.map(a => serie[a] || 0), backgroundColor: "#c8102e" }] },
    options: { maintainAspectRatio: false }
  });
}

// =============================================================
// GRUPOS TERRITORIALES
// =============================================================
function mostrarGrupos() {
  const n = R.metricas_no_supervisado;
  const nombres = [...new Set(R.municipios.map(m => m.cluster + "|" + m.cluster_nombre))].sort().map(x => x.split("|"));
  let html = '<div class="cifras">' +
    cifra(n.k_elegido, "grupos (clustering " + (n.metodo || "aglomerativo") + ")") +
    cifra(redondear(n.silueta_final, 3), "coeficiente de silueta") +
    cifra(R.municipios.length, "municipios de Santander comparados") +
    cifra(n.dbscan_fuentes.length, "fuentes sísmicas detectadas con DBSCAN") + "</div>";
  html += '<div class="dos-columnas"><div><h3>Elección de k</h3><div class="grafica"><canvas id="grafK"></canvas></div></div>' +
    '<div><h3>Municipios en el plano PCA</h3><div class="grafica"><canvas id="grafPCA"></canvas></div></div></div>';
  html += "<h3>Perfil de cada grupo (promedios)</h3><div class='tabla-scroll'><table><tr><th>Grupo</th><th class='num'>Municipios</th><th class='num'>Sismos/año</th><th class='num'>Prof. media</th><th class='num'>% superficial</th><th class='num'>% intermedio</th><th class='num'>Valor b</th></tr>" +
    nombres.map(([c, nom]) => {
      const ce = n.centroides[nom] || {};
      const cuantos = R.municipios.filter(m => String(m.cluster) === c).length;
      return "<tr><td><span style='color:" + colorGrupo(nom, c) + "'>●</span> " + nom + "</td><td class='num'>" + cuantos + "</td><td class='num'>" + redondear(ce.tasa_m25_anual, 2) +
        "</td><td class='num'>" + redondear(ce.prof_media_km, 0) + " km</td><td class='num'>" + pct(ce.pct_superficial || 0) + "</td><td class='num'>" + pct(ce.pct_intermedio || 0) + "</td><td class='num'>" + redondear(ce.b_value, 2) + "</td></tr>";
    }).join("") + "</table></div>";
  const dptos = Object.keys(n.comparacion_territorial);
  html += "<h3>Municipios por grupo (Santander)</h3><div class='tabla-scroll'><table><tr><th>Departamento</th>" + nombres.map(([c, nom]) => "<th class='num'>" + nom + "</th>").join("") + "</tr>" +
    dptos.map(d => "<tr" + (d === "SANTANDER" ? " style='font-weight:700'" : "") + "><td>" + tipoTitulo(d) + "</td>" + nombres.map(([c, nom]) => "<td class='num'>" + (n.comparacion_territorial[d][nom] || 0) + "</td>").join("") + "</tr>").join("") + "</table></div>";
  html += '<div class="dos-columnas"><div><h3>Variables que definen los grupos</h3><div class="grafica"><canvas id="grafImpGrupos"></canvas></div></div>' +
    "<div><h3>Fuentes sísmicas (DBSCAN sobre epicentros M ≥ 3)</h3><table><tr><th>Fuente</th><th class='num'>Sismos</th><th class='num'>Lat</th><th class='num'>Lon</th><th class='num'>Prof. media</th><th class='num'>M máx</th></tr>" +
    n.dbscan_fuentes.map(f => "<tr><td>" + f.fuente + (f.fuente === 1 ? " (Nido de Bucaramanga)" : "") + "</td><td class='num'>" + f.n.toLocaleString("es-CO") + "</td><td class='num'>" + redondear(f.lat, 2) + "</td><td class='num'>" + redondear(f.lon, 2) + "</td><td class='num'>" + redondear(f.prof_media_km, 0) + " km</td><td class='num'>" + f.mag_max + "</td></tr>").join("") +
    "</table></div></div><h3>Mapa de grupos</h3><p class='nota'>Puntos: cabeceras de los 87 municipios. Polígonos: municipios de Santander, del color de su grupo.</p>";
  $("medioContenido").className = "";
  $("medioContenido").innerHTML = html;

  dibujarGrafica("grafK", {
    type: "line",
    data: { labels: n.seleccion_k.map(x => "k=" + x.k), datasets: [
      { label: "Silueta (más alto es mejor)", data: n.seleccion_k.map(x => x.silueta), borderColor: "#006b3f" },
      { label: "Davies-Bouldin (más bajo es mejor)", data: n.seleccion_k.map(x => x.davies_bouldin), borderColor: "#c8102e" }] },
    options: { maintainAspectRatio: false }
  });
  dibujarGrafica("grafPCA", {
    type: "scatter",
    data: { datasets: nombres.map(([c, nom]) => ({ label: nom, backgroundColor: colorGrupo(nom, c),
      data: R.municipios.filter(m => String(m.cluster) === c).map(m => ({ x: m.pca1, y: m.pca2, nombre: m.nombreBonito })) })) },
    options: { maintainAspectRatio: false, plugins: { tooltip: { callbacks: { label: c => c.raw.nombre } } }, scales: { x: { title: { display: true, text: "PCA 1" } }, y: { title: { display: true, text: "PCA 2" } } } }
  });
  const imp = Object.entries(n.importancia_variables).sort((a, b) => b[1] - a[1]).filter(x => x[1] > 0);
  dibujarGrafica("grafImpGrupos", {
    type: "bar",
    data: { labels: imp.map(x => x[0]), datasets: [{ data: imp.map(x => x[1]), backgroundColor: "#2f6f9f" }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });

  const mapa = crearMapa("mapaGrupos");
  for (const m of R.municipios) {
    const f = m.santander ? poligono(m.cod) : null;
    if (f) L.geoJSON(f, { style: { color: "#fff", weight: 0.6, fillColor: colorGrupo(m), fillOpacity: 0.45 } }).addTo(mapa).bindTooltip(m.nombreBonito + " · " + m.cluster_nombre);
    L.circleMarker([m.lat, m.lon], { radius: 5, color: "#fff", weight: 1, fillColor: colorGrupo(m), fillOpacity: 1 })
      .addTo(mapa).bindPopup("<b>" + m.nombreBonito + "</b> (" + tipoTitulo(m.dpto) + ")<br>" + m.cluster_nombre + "<br>" + redondear(m.tasa_m25_anual, 2) + " sismos M ≥ 2,0 por año");
  }
  setTimeout(() => mapa.invalidateSize(), 50);
}

// =============================================================
// PRIORIZACIÓN (agente RL)
// =============================================================
function mostrarPriorizacion() {
  const rl = R.metricas_rl, t = rl.test, cfg = rl.config;
  const aTr = cfg.anios_train, aTe = cfg.anios_test;
  let html = "<h3>Cómo está planteado el agente</h3><table>" +
    "<tr><th>Entorno</th><td>" + cfg.entorno + ". Un episodio recorre los 87 municipios en orden aleatorio hasta completar el ranking.</td></tr>" +
    "<tr><th>Estado</th><td>Las 35 variables del municipio (sismicidad, profundidad, temporalidad, población DANE y emergencias UNGRD) estandarizadas, más el avance del episodio.</td></tr>" +
    "<tr><th>Acción</th><td>Priorizar o no priorizar el municipio actual.</td></tr>" +
    "<tr><th>Recompensa</th><td>" + cfg.recompensa + ", con r = índice de riesgo. Premia priorizar municipios de alto riesgo y castiga priorizar los de bajo riesgo.</td></tr>" +
    "<tr><th>Algoritmos</th><td>Compiten <b>PPO</b> (gradiente de política con baseline y clipping, red 37→64→1) y <b>DQN</b> (MLP que estima Q(s,0)/Q(s,1) con replay buffer); " + cfg.epocas + " episodios cada uno. Ganador: <b>" + cfg.algoritmo + "</b> (PPO " + (cfg.recompensas_medias ? cfg.recompensas_medias.PPO : "?") + " vs DQN " + (cfg.recompensas_medias ? cfg.recompensas_medias.DQN : "?") + " de recompensa media).</td></tr></table>";

  const estrategias = [["agente_rl", "Agente RL"], ["indice_pesos_iguales", "Índice de pesos iguales"], ["mayor_poblacion", "Mayor población"],
    ["mayor_actividad_pasada", "Mayor actividad pasada"], ["ranking_supervisado", "Ranking supervisado"], ["azar", "Azar"]];
  html += "<h3>Evaluación transversal (87 municipios, K = " + cfg.k + ")</h3><p class='nota'>Óptimo (" + cfg.oraculo + "). % del óptimo = impacto capturado frente al mejor top-K posible; precisión@K = coincidencia con ese top-K.</p>" + '<div class="cifras">' +
    cifra(pct(t.agente_rl.pct_oraculo), "del impacto óptimo capturado por el agente (± " + redondear(t.agente_rl.std_semillas, 3) + " de recompensa entre semillas)", "ok") +
    cifra(pct(t.agente_rl.precision_at_k), "de sus K elegidos estaban en el top-K real") +
    cifra(pct(t.indice_pesos_iguales.pct_oraculo), "índice de pesos iguales (mejor línea base)") +
    cifra(pct(t.azar.pct_oraculo), "elegir al azar") + "</div>";
  html += '<div class="dos-columnas"><div><h3>Comparación con las líneas base</h3><div class="grafica"><canvas id="grafLineas"></canvas></div></div>' +
    '<div><h3>Curva de aprendizaje (promedio de las semillas)</h3><div class="grafica"><canvas id="grafCurva"></canvas></div></div></div>';
  html += '<h3>Qué pesa en el puntaje: asociación variable–puntaje RL</h3><p class="nota">Correlación absoluta entre cada variable y el puntaje del agente: mientras más alta, más distingue a los municipios priorizados. No son pesos internos de la red, sino una lectura interpretable del ranking.</p><div class="grafica" style="height:360px"><canvas id="grafPesos"></canvas></div>';
  html += "<h3>Priorización para 2026</h3><p class='nota'>Los K priorizados tienen borde grueso; el color indica la confianza (en cuántas semillas quedó en el top-K): rojo alta, amarillo media, gris baja.</p>";
  $("avanzadoContenido").className = "";
  $("avanzadoContenido").innerHTML = html;

  dibujarGrafica("grafLineas", {
    type: "bar",
    data: { labels: estrategias.map(e => e[1]), datasets: [
      { label: "% del óptimo", data: estrategias.map(e => t[e[0]].pct_oraculo * 100), backgroundColor: estrategias.map(e => e[0] === "agente_rl" ? "#c8102e" : "#94a3b8") },
      { label: "Precisión@K (%)", data: estrategias.map(e => t[e[0]].precision_at_k * 100), backgroundColor: estrategias.map(e => e[0] === "agente_rl" ? "#ffd100" : "#cbd5e1") }] },
    options: { maintainAspectRatio: false, scales: { y: { min: 0, max: 100 } } }
  });
  const curva = R.curva_rl;
  dibujarGrafica("grafCurva", {
    type: "line",
    data: { labels: curva.map(c => c.epoca), datasets: [
      { label: "Recompensa en entrenamiento", data: curva.map(c => c.recompensa), borderColor: "#006b3f", pointRadius: 0, yAxisID: "y" },
      { label: "% del óptimo en validación", data: curva.map(c => c.pct_oraculo_val === null ? null : c.pct_oraculo_val * 100), borderColor: "#c8102e", pointRadius: 2, spanGaps: true, yAxisID: "y1" }] },
    options: { maintainAspectRatio: false, scales: { y1: { position: "right", min: 0, max: 100, grid: { display: false } } } }
  });
  const pesos = Object.entries(rl.pesos_politica).sort((a, b) => b[1].media - a[1].media);
  dibujarGrafica("grafPesos", {
    type: "bar",
    data: { labels: pesos.map(p => p[0]), datasets: [
      { label: "Peso medio", data: pesos.map(p => p[1].media), backgroundColor: pesos.map(p => p[1].media >= 0 ? "#006b3f" : "#c8102e") },
      { label: "Desviación entre semillas", data: pesos.map(p => p[1].std), backgroundColor: "#cbd5e1" }] },
    options: { indexAxis: "y", maintainAspectRatio: false }
  });

  const mapa = crearMapa("mapaPrioridad");
  const colConf = { alta: "#c8102e", media: "#ffd100", baja: "#94a3b8" };
  for (const p of R.priorizacion_2026) {
    const f = poligono(p.cod_mpio);
    const dentro = p.rango <= estado.K;
    if (f) L.geoJSON(f, { style: { color: dentro ? "#111827" : "#fff", weight: dentro ? 3 : 0.6, fillColor: dentro ? colConf[p.confianza] : "#e2e8f0", fillOpacity: dentro ? 0.65 : 0.25 } })
      .addTo(mapa).bindPopup(() => popupMunicipio(estado.porCodigo[p.cod_mpio]));
  }
  conectarBotonBoletin(mapa);

  $("avanzadoTablas").innerHTML = "<h3>Ranking completo</h3><div class='tabla-scroll'><table><tr><th>#</th><th>Municipio</th><th class='num'>Puntaje</th><th>Confianza</th><th class='num'>Amenaza</th><th class='num'>Exposición</th><th class='num'>Vulnerabilidad</th><th class='num'>P(alto) 2026</th><th>Grupo</th><th class='num'>Sismos 2025</th></tr>" +
    R.priorizacion_2026.map(p => "<tr" + (p.rango <= estado.K ? " style='background:var(--acento-suave)'" : "") + "><td>" + p.rango + "</td><td>" + estado.porCodigo[p.cod_mpio].nombreBonito +
      "</td><td class='num'>" + redondear(p.puntaje, 2) + "</td><td>" + p.confianza + " (" + pct(p.prob_top_k) + ")</td><td class='num'>" + redondear(p.contrib_amenaza, 2) + "</td><td class='num'>" + redondear(p.contrib_exposicion, 2) +
      "</td><td class='num'>" + redondear(p.contrib_vulnerabilidad, 2) + "</td><td class='num'>" + pct(p.p_alto) + "</td><td>" + p.cluster_nombre + "</td><td class='num'>" + p.n_m25_2025 + "</td></tr>").join("") + "</table></div>" +
    "<p><button id='descargarRanking'>Descargar priorización (CSV)</button></p>" +
    "<h3>Supuestos, limitaciones y extensiones</h3><ul>" +
    "<li><b>No predice sismos:</b> estima niveles de riesgo relativo con el historial y prioriza preparación; no anuncia cuándo ni dónde ocurrirá un sismo.</li>" +
    "<li>Las etiquetas Bajo/Medio/Alto son terciles del índice de riesgo construido por el equipo (50 % actividad + 30 % exposición + 20 % vulnerabilidad), no daños observados.</li>" +
    "<li>El catálogo SGC unificado cubre 1993–hoy; para mapas y boletines se usan eventos M ≥ 2,0 asignados al municipio DIVIPOLA más cercano (nombre o distancia haversiana).</li>" +
    "<li>La población es la proyección DANE 2020–2035 y las emergencias UNGRD cubren 2019–2025; se usan como foto fija del municipio.</li>" +
    "<li>Extensiones: amenaza de la NSR-10 por municipio, vulnerabilidad estructural y actualización automática del catálogo.</li></ul>";
  $("descargarRanking").onclick = () => {
    let csv = "rango,cod_mpio,municipio,puntaje,confianza,prob_top_k,contrib_amenaza,contrib_exposicion,contrib_vulnerabilidad,p_alto,grupo,poblacion,n_m25_2025\n";
    for (const p of R.priorizacion_2026) csv += [p.rango, p.cod_mpio, '"' + estado.porCodigo[p.cod_mpio].nombreBonito + '"', p.puntaje, p.confianza, p.prob_top_k, p.contrib_amenaza, p.contrib_exposicion, p.contrib_vulnerabilidad, p.p_alto, '"' + p.cluster_nombre + '"', p.poblacion_total, p.n_m25_2025].join(",") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = "priorizacion_2026.csv"; a.click();
  };
  setTimeout(() => mapa.invalidateSize(), 50);
}

// =============================================================
// ACTIVIDAD SÍSMICA (agregados directos del catálogo, sin modelos)
// =============================================================
function mostrarActividad() {
  const porAnio = {}, magBins = {}, profBins = {};
  let magMax = 0, sup = 0;
  for (const e of R.eventos) {
    const anio = new Date(e[0] * 60000).getUTCFullYear();
    porAnio[anio] = (porAnio[anio] || 0) + 1;
    const bM = e[4] >= 6 ? "≥ 6,0" : (Math.floor((e[4] - 2) / 0.5) * 0.5 + 2).toFixed(1) + "–" + (Math.floor((e[4] - 2) / 0.5) * 0.5 + 2.5).toFixed(1);
    magBins[bM] = (magBins[bM] || 0) + 1;
    const bP = e[3] < 50 ? "< 50" : (e[3] < 100 ? "50–100" : (e[3] < 150 ? "100–150" : "≥ 150"));
    profBins[bP] = (profBins[bP] || 0) + 1;
    if (e[4] > magMax) magMax = e[4];
    if (e[3] < 50) sup++;
  }
  const aniosOrd = Object.keys(porAnio).map(Number).sort((a, b) => a - b);
  const topAnio = aniosOrd.reduce((a, b) => porAnio[b] > porAnio[a] ? b : a, aniosOrd[0]);
  const top15 = R.municipios.slice().sort((a, b) => b.cantidad_total_sismos - a.cantidad_total_sismos).slice(0, 15);
  $("actividadContenido").className = "";
  $("actividadContenido").innerHTML = '<div class="cifras">' +
    cifra(R.eventos.length.toLocaleString("es-CO"), "sismos M ≥ " + String(R.umbral_magnitud).replace(".", ",") + " asignados (" + R.anios[0] + "–" + R.anios[R.anios.length - 1] + ")") +
    cifra(topAnio + " (" + porAnio[topAnio].toLocaleString("es-CO") + ")", "año con más sismos") +
    cifra(magMax, "magnitud máxima instrumental", "alerta") +
    cifra(redondear(sup / R.eventos.length * 100, 1) + " %", "sismos superficiales (< 50 km)") + "</div>" +
    '<div class="dos-columnas"><div><h3>Sismos por año</h3><div class="grafica"><canvas id="grafAnual"></canvas></div></div>' +
    '<div><h3>Top 15 municipios por sismos acumulados</h3><div class="grafica"><canvas id="grafTopMun"></canvas></div></div></div>' +
    '<div class="dos-columnas"><div><h3>Distribución de magnitudes</h3><div class="grafica"><canvas id="grafMag"></canvas></div></div>' +
    '<div><h3>Distribución de profundidades (km)</h3><div class="grafica"><canvas id="grafProf"></canvas></div></div></div>';
  dibujarGrafica("grafAnual", { type: "bar",
    data: { labels: aniosOrd, datasets: [{ data: aniosOrd.map(a => porAnio[a]), backgroundColor: "#c8102e" }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  dibujarGrafica("grafTopMun", { type: "bar",
    data: { labels: top15.map(m => m.nombreBonito), datasets: [{ data: top15.map(m => m.cantidad_total_sismos), backgroundColor: "#2f6f9f" }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  dibujarGrafica("grafMag", { type: "bar",
    data: { labels: Object.keys(magBins), datasets: [{ data: Object.values(magBins), backgroundColor: "#006b3f" }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  const ordenP = ["< 50", "50–100", "100–150", "≥ 150"];
  dibujarGrafica("grafProf", { type: "bar",
    data: { labels: ordenP, datasets: [{ data: ordenP.map(b => profBins[b] || 0), backgroundColor: "#7b5aa6" }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } } });
}

// =============================================================
// FUENTES Y VARIABLES
// =============================================================
function mostrarDatos() {
  const s = R.fuentes.sgc, o = R.fuentes.otras;
  const filas = [
    ["SGC · Catálogo de la Red Sismológica Nacional (1993–2018)", s.consultas["1993-2018"], s.fecha_descarga_utc, s.eventos_1993_2018.toLocaleString("es-CO") + " sismos"],
    ["SGC · Catálogo SeisComP (2018–hoy)", s.consultas["2018-hoy"], s.fecha_descarga_utc, s.eventos_2018_hoy.toLocaleString("es-CO") + " sismos"]
  ];
  const nombres = { "dane_divipola.csv": "DANE · DIVIPOLA (códigos y cabeceras)", "ungrd_emergencias_2019_2024.csv": "UNGRD · Emergencias 2019–2024",
    "ungrd_emergencias_2025.csv": "UNGRD · Emergencias 2025", "dane_proyeccion_poblacion_municipal_2020_2035.xlsx": "DANE · Proyecciones de población municipal 2020–2035" };
  for (const k in o) filas.push([nombres[k] || k, o[k].url, o[k].fecha_descarga_utc, o[k].filas ? o[k].filas.toLocaleString("es-CO") + " filas" : ""]);
  filas.push(["IGAC/DANE · Límites municipales (santiblanko/colombia.geojson)", "https://github.com/santiblanko/colombia.geojson", "", "87 municipios"]);
  filas.push(["GEM Global Active Faults (Active Tectonics of the Andes, SARA)", "https://github.com/GEMScienceTools/gem-global-active-faults", "", "fallas activas"]);
  $("fuentesContenido").className = "";
  $("fuentesContenido").innerHTML = "<p class='nota'>Filtro del catálogo: caja de " + s.filtros.latitudStart + "° a " + s.filtros.latitudEnd + "° de latitud y " + s.filtros.longitudStart + "° a " + s.filtros.longitudEnd + "° de longitud (Santander y vecinos), periodo " + s.filtros.periodo + ".</p>" +
    "<div class='tabla-scroll'><table><tr><th>Fuente</th><th>Consulta</th><th>Descarga (UTC)</th><th class='num'>Tamaño</th></tr>" +
    filas.map(f => "<tr><td>" + f[0] + "</td><td><a href='" + f[1] + "' target='_blank' rel='noopener'>" + f[1].replace(/^https?:\/\//, "").slice(0, 60) + "</a></td><td>" + (f[2] || "").replace("T", " ").slice(0, 16) + "</td><td class='num'>" + f[3] + "</td></tr>").join("") + "</table></div>";

  const roles = {};
  R.diccionario.forEach(d => { roles[d.rol] = (roles[d.rol] || 0) + 1; });
  const entradas = R.diccionario.filter(d => !["llave", "objetivo", "auxiliar_futuro"].includes(d.rol)).length;
  const pasos = ["Catálogos SGC<br><small>1993–2018 y 2018–hoy</small>", "Limpieza<br><small>duplicados y rangos físicos</small>", "Municipio<br><small>código DIVIPOLA (+ cercanía espacial)</small>",
    "Cruce DANE y UNGRD<br><small>por código DIVIPOLA</small>", "Dataset maestro<br><small>" + R.municipios.length + " municipios × " + R.anios.length + " años (" + R.anios[0] + "–" + R.anios[R.anios.length - 1] + ")</small>", "Supervisado<br><small>riesgo Bajo/Medio/Alto</small>",
    "Aglomerativo<br><small>grupos territoriales</small>", "Agente RL<br><small>priorización (PPO vs DQN)</small>", "Página y boletines"];
  $("variablesContenido").className = "";
  $("variablesContenido").innerHTML = '<div class="cifras">' +
    cifra(R.municipios.length + " × " + R.anios.length, "celdas municipio-año del dataset (" + (R.municipios.length * R.anios.length).toLocaleString("es-CO") + ")") + cifra(entradas, "variables de entrada justificadas") +
    cifra(roles.sup || 0, "variables del modelo supervisado") + cifra(R.eventos_info.n.toLocaleString("es-CO"), "sismos de Santander M ≥ " + String(R.eventos_info.mag_min).replace(".", ",") + " en mapas y boletines") + "</div>" +
    "<h3>Flujo de datos</h3><div class='flujo'>" + pasos.map(x => "<div class='paso'>" + x + "</div>").join("<div class='flecha'>→</div>") + "</div>" +
    "<h3>Diccionario de datos</h3><div class='tabla-scroll' style='max-height:600px'><table><tr><th>Variable</th><th>Fuente</th><th>Rol</th><th>Descripción</th><th>Justificación</th></tr>" +
    R.diccionario.map(d => "<tr><td><code>" + d.variable + "</code></td><td>" + d.fuente + "</td><td>" + d.rol + "</td><td>" + d.descripcion + "</td><td>" + d.justificacion + "</td></tr>").join("") + "</table></div>" +
    "<p class='nota'>Resultados exportados del pipeline Urielitos-main el " + R.generado_utc + " UTC con scripts/exportar_frontend.py.</p>";
}

// =============================================================
function mostrarTodo() {
  mostrarPanorama();
  mostrarActividad();
  mostrarSupervisado();
  mostrarGrupos();
  mostrarPriorizacion();
  mostrarBoletines();
  mostrarDatos();
}

aplicarColoresGraficas();
$("etiquetaDatos").textContent = R.eventos_info.n.toLocaleString("es-CO") + " sismos · " + estado.santander.length + " municipios";
$("fuenteMini").textContent = "Catálogo SGC hasta " + estado.fechaFin.toISOString().slice(0, 10);
mostrarMensaje("Datos oficiales del SGC, DANE y UNGRD procesados por el equipo (" + R.anios[0] + "–" + R.anios[R.anios.length - 1] + "). Último sismo del catálogo: " + estado.fechaFin.toISOString().slice(0, 10) + ".");
mostrarTodo();
