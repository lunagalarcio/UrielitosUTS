// =============================================================
// boletines.js — filtro de municipios y boletín en PDF (jsPDF)
// =============================================================

const AVISO_NO_PREDICE = "ESTE SISTEMA NO PREDICE SISMOS. Hoy ningún método científico puede anunciar cuándo, dónde " +
  "y de qué magnitud ocurrirá un sismo. El nivel de este boletín es una estimación estadística de la actividad " +
  "esperada a partir del historial del catálogo; puede fallar. Es un prototipo académico y no reemplaza la " +
  "información oficial del Servicio Geológico Colombiano (SGC), la UNGRD ni el Consejo Municipal de Gestión del Riesgo.";

// Imágenes satelitales Esri World Imagery (uso libre con atribución)
const URL_SATELITE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

const NO_PUEDE_PREDECIR = [
  "Cuándo ocurrirá un sismo: ni la fecha ni la hora.",
  "Dónde exactamente ocurrirá ni qué magnitud tendrá.",
  "Si en este municipio habrá un sismo que cause daños.",
  "No es un sistema de alerta temprana: no avisa segundos ni minutos antes de un sismo.",
  "No evalúa el estado de las construcciones ni el tipo de suelo, que son lo que más influye en los daños.",
  "Un nivel bajo no significa que no pueda temblar fuerte, y un nivel alto no significa que vaya a ocurrir un terremoto."
];

const LINEAS_EMERGENCIA = [
  "Línea única de emergencias: 123",
  "Bomberos: 119",
  "Cruz Roja Colombiana: 132",
  "Defensa Civil: 144"
];

const RECOMENDACIONES = {
  antes: [
    "Haga un plan familiar de emergencia: dónde se encuentran, a quién llaman y quién recoge a los niños.",
    "Tenga un kit de emergencia: agua, alimentos no perecederos, linterna, radio, botiquín, documentos y medicamentos.",
    "Identifique en su casa, colegio y trabajo las zonas seguras, las salidas y la ruta hacia el punto de encuentro.",
    "Asegure muebles altos, repisas, cilindros de gas y objetos que puedan caer.",
    "Participe en los simulacros y consulte el plan de emergencia de su municipio."
  ],
  durante: [
    "Agáchese, cúbrase y sujétese: protéjase bajo una mesa firme o junto a un muro interior.",
    "Aléjese de ventanas, vidrios, repisas y objetos que puedan caer.",
    "No use ascensores ni corra hacia las escaleras mientras el suelo se mueve.",
    "Si está en la calle, aléjese de edificios, postes, cables, muros y taludes.",
    "Si va conduciendo, deténgase en un lugar seguro, lejos de puentes y laderas."
  ],
  despues: [
    "Revise si usted o alguien cerca está herido y dé primeros auxilios si sabe hacerlo.",
    "Si la edificación tiene daños, evacúe con calma por la ruta señalizada hasta el punto de encuentro.",
    "Cierre las llaves del gas y del agua y baje los tacos de la electricidad si hay daños.",
    "Esté atento a réplicas y a deslizamientos: en las zonas de ladera de Santander un sismo puede desestabilizar taludes.",
    "Use el teléfono solo para emergencias e infórmese por canales oficiales (SGC, UNGRD, alcaldía)."
  ]
};

// CSV de evacuación: municipio,tipo,nombre,lat,lon,descripcion → { codigo: [puntos] }
function leerEvacuacion(textoCsv) {
  const filas = parsearCsv(textoCsv);
  const encabezado = filas[0].map(normalizarTexto);
  const col = nombre => encabezado.findIndex(h => h.startsWith(nombre));
  const cMun = col("municip"), cTipo = col("tipo"), cNombre = col("nombre"), cLat = col("lat"), cLon = col("lon"), cDesc = col("desc");
  const porNombre = {};
  for (const m of estado.santander) porNombre[normalizarTexto(m.nombreBonito)] = m.cod;
  const datos = {};
  for (let i = 1; i < filas.length; i++) {
    const cod = porNombre[normalizarTexto(filas[i][cMun === -1 ? 0 : cMun])];
    if (!cod) continue;
    if (!datos[cod]) datos[cod] = [];
    datos[cod].push({
      tipo: cTipo >= 0 ? filas[i][cTipo] : "Punto de encuentro",
      nombre: cNombre >= 0 ? filas[i][cNombre] : "",
      lat: cLat >= 0 ? aNumero(filas[i][cLat]) : NaN,
      lon: cLon >= 0 ? aNumero(filas[i][cLon]) : NaN,
      descripcion: cDesc >= 0 ? filas[i][cDesc] : ""
    });
  }
  return datos;
}

// Falla activa más cercana a un punto (km), con los datos de FALLAS_ACTIVAS
function fallaMasCercana(lat, lon) {
  if (typeof FALLAS_ACTIVAS === "undefined") return null;
  const kx = 111.32 * Math.cos(lat * Math.PI / 180), ky = 110.574;
  let mejor = { km: Infinity, nombre: "" };
  for (const f of FALLAS_ACTIVAS.features) {
    for (const linea of f.geometry.coordinates) {
      for (let i = 0; i < linea.length - 1; i++) {
        const ax = (linea[i][0] - lon) * kx, ay = (linea[i][1] - lat) * ky;
        const bx = (linea[i + 1][0] - lon) * kx, by = (linea[i + 1][1] - lat) * ky;
        const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
        const t = l2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
        const d = Math.hypot(ax + t * dx, ay + t * dy);
        if (d < mejor.km) mejor = { km: d, nombre: f.properties.nombre };
      }
    }
  }
  return mejor;
}

// Sismo en formato de objeto (los datos vienen compactos como arreglos)
function aSismo(e) { return { fecha: new Date(e[0] * 60000), lat: e[1], lon: e[2], prof: e[3], mag: e[4] }; }

// Reúne todo lo que va en el boletín de un municipio (por código DIVIPOLA)
function datosBoletin(cod) {
  const m = estado.porCodigo[cod];
  const f = R.fila_2025[cod] || {};
  const p = R.prediccion_2026[cod];
  const pr = PRIORIDAD[cod];
  const sismos = eventosDe(cod).map(aSismo);
  const fin = estado.fechaFin.getTime();
  const ultimoAno = sismos.filter(e => fin - e.fecha.getTime() <= 365.25 * 86400000);
  const mayor = sismos.reduce((a, b) => (b.mag > a.mag ? b : a), sismos[0] || null);
  const falla = fallaMasCercana(m.lat, m.lon);
  return {
    cod: cod, municipio: m.nombreBonito,
    poblacion: f.poblacion_total, pctRural: f.pct_rural,
    nivel: p ? p.pred : null, probs: p ? [p.p_bajo, p.p_medio, p.p_alto] : [0, 0, 0],
    n2025: R.serie_n_m25[cod][2025] || 0, prom3: f.n_m25_prom_3a,
    puesto: pr ? pr.rango : null, priorizado: pr ? pr.rango <= estado.K : false, confianza: pr ? pr.confianza : "",
    probTopK: pr ? pr.prob_top_k : 0, contrib: pr ? [pr.contrib_amenaza, pr.contrib_exposicion, pr.contrib_vulnerabilidad] : null,
    grupo: m.cluster_nombre,
    emergencias: f.emergencias_prom_anual, fallecidos: f.fallecidos_total, heridos: f.heridos_total,
    personas: f.personas_afectadas,
    sismos: sismos, sismosAno: ultimoAno, mayor: mayor, ultimo: sismos[sismos.length - 1] || null,
    pctSuperficial: m.pct_superficial, profMedia: m.prof_media_km,
    evacuacion: estado.evacuacion[cod] || [],
    falla: falla ? falla.nombre : "", distFalla: falla ? falla.km : NaN
  };
}

// Mapa satelital del municipio para el PDF: límite del municipio (IGAC, si se cargó),
// epicentros del último año y puntos de encuentro. Se arma uniendo teselas de Esri.
// Si no hay internet o el servidor no lo permite, devuelve null y el boletín sale sin mapa.
async function mapaMunicipio(cod, b) {
  const ancho = 768, alto = 448;
  const feature = poligono(cod);
  const anillos = [];
  if (feature) {
    const g = feature.geometry;
    const pols = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    for (const pol of pols) anillos.push(pol[0]);
  }
  let sismos = b.sismosAno;
  if (sismos.length === 0) sismos = b.sismos.slice(-200);
  const puntos = b.evacuacion.filter(p => !isNaN(p.lat));

  // Caja a mostrar: el límite del municipio o, si no hay, los epicentros y puntos
  let lats = [], lons = [];
  if (anillos.length) anillos.forEach(a => a.forEach(c => { lons.push(c[0]); lats.push(c[1]); }));
  else { sismos.forEach(e => { lats.push(e.lat); lons.push(e.lon); }); }
  puntos.forEach(p => { lats.push(p.lat); lons.push(p.lon); });
  const latMin = Math.min(...lats), latMax = Math.max(...lats), lonMin = Math.min(...lons), lonMax = Math.max(...lons);

  const aPixel = (la, lo, z) => {
    const n = 256 * Math.pow(2, z);
    const sen = Math.sin(la * Math.PI / 180);
    return { x: (lo + 180) / 360 * n, y: (0.5 - Math.log((1 + sen) / (1 - sen)) / (4 * Math.PI)) * n };
  };
  // El zoom más cercano en el que todo cabe
  let z = 13;
  for (; z > 6; z--) {
    const a = aPixel(latMax, lonMin, z), c = aPixel(latMin, lonMax, z);
    if (c.x - a.x < ancho * 0.85 && c.y - a.y < alto * 0.85) break;
  }
  const centro = aPixel((latMin + latMax) / 2, (lonMin + lonMax) / 2, z);
  const x0 = centro.x - ancho / 2, y0 = centro.y - alto / 2;
  const enLienzo = (la, lo) => { const q = aPixel(la, lo, z); return { x: q.x - x0, y: q.y - y0 }; };

  const lienzo = document.createElement("canvas");
  lienzo.width = ancho; lienzo.height = alto;
  const ctx = lienzo.getContext("2d");
  const cargar = url => new Promise((ok, falla) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    const reloj = setTimeout(() => falla(new Error("tiempo")), 8000);
    img.onload = () => { clearTimeout(reloj); ok(img); };
    img.onerror = () => { clearTimeout(reloj); falla(new Error("tesela")); };
    img.src = url;
  });
  try {
    // Dibuja todas las teselas de un servidor; si alguna falla, lanza error
    const dibujarTeselas = async plantilla => {
      const tareas = [];
      for (let tx = Math.floor(x0 / 256); tx <= Math.floor((x0 + ancho) / 256); tx++) {
        for (let ty = Math.floor(y0 / 256); ty <= Math.floor((y0 + alto) / 256); ty++) {
          const url = plantilla.replace("{z}", z).replace("{x}", tx).replace("{y}", ty);
          tareas.push(cargar(url).then(img => ctx.drawImage(img, tx * 256 - x0, ty * 256 - y0)));
        }
      }
      await Promise.all(tareas);
    };
    // Primero la imagen satelital; si no carga, el mapa de calles de OpenStreetMap
    let creditoBase = "Imagen satelital: Esri World Imagery (Esri, Maxar, Earthstar Geographics)";
    try {
      await dibujarTeselas(URL_SATELITE);
      lienzo.toDataURL("image/jpeg");                        // comprueba que la imagen se pueda exportar
    } catch (errorSatelite) {
      ctx.clearRect(0, 0, ancho, alto);
      await dibujarTeselas("https://tile.openstreetmap.org/{z}/{x}/{y}.png");
      creditoBase = "Mapa base: © colaboradores de OpenStreetMap (no cargó la imagen satelital)";
    }

    // Límite del municipio
    if (anillos.length) {
      ctx.strokeStyle = "#ffd54a"; ctx.lineWidth = 3; ctx.fillStyle = "rgba(255,213,74,0.10)";
      for (const a of anillos) {
        ctx.beginPath();
        a.forEach((c, k) => { const q = enLienzo(c[1], c[0]); if (k === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y); });
        ctx.closePath(); ctx.fill(); ctx.stroke();
      }
    }
    // Fallas activas (línea naranja punteada)
    if (typeof FALLAS_ACTIVAS !== "undefined") {
      ctx.strokeStyle = "#ff7a00"; ctx.lineWidth = 2.5; ctx.setLineDash([8, 5]);
      for (const f of FALLAS_ACTIVAS.features) for (const linea of f.geometry.coordinates) {
        ctx.beginPath();
        linea.forEach((c, k) => { const q = enLienzo(c[1], c[0]); if (k === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y); });
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }
    // Epicentros (tamaño según magnitud)
    const escala = sismos.length > 300 ? 0.45 : 1;   // con muchos sismos (Nido) se dibujan más pequeños
    for (const e of sismos) {
      const q = enLienzo(e.lat, e.lon);
      ctx.beginPath(); ctx.arc(q.x, q.y, (2 + Math.max(0, e.mag - 1) * 2.2) * escala, 0, 2 * Math.PI);
      ctx.fillStyle = e.prof < 30 ? "rgba(255,87,51,0.75)" : "rgba(255,160,60,0.55)";
      ctx.strokeStyle = "rgba(255,255,255,0.8)"; ctx.lineWidth = 1;
      ctx.fill(); ctx.stroke();
    }
    // Puntos de encuentro
    puntos.forEach((p, i) => {
      const q = enLienzo(p.lat, p.lon);
      ctx.fillStyle = "#2e9e4f"; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(q.x, q.y, 10, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#ffffff"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.fillText(String(i + 1), q.x, q.y + 4);
    });
    ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fillRect(0, alto - 18, ancho, 18);
    ctx.fillStyle = "#ffffff"; ctx.font = "11px sans-serif"; ctx.textAlign = "left";
    ctx.fillText(creditoBase + (anillos.length ? " · Límite municipal: IGAC/DANE" : ""), 6, alto - 5);
    return { imagen: lienzo.toDataURL("image/jpeg", 0.82), conLimite: anillos.length > 0, nSismos: sismos.length, satelital: creditoBase.startsWith("Imagen satelital") };
  } catch (error) {
    return null;
  }
}

function fechaCorta(fecha) { return fecha.toISOString().slice(0, 10); }

// ---------- Lista filtrable ----------
function mostrarBoletines() {
  const grupos = [...new Set(estado.santander.map(m => m.cluster_nombre))].sort();
  $("filtroGrupo").innerHTML = '<option value="">Todos</option>' + grupos.map(g => "<option>" + g + "</option>").join("");
  ["filtroNivel", "filtroPrioridad", "filtroGrupo"].forEach(id => { $(id).onchange = listarBoletines; });
  $("filtroTexto").oninput = listarBoletines;
  $("botonBoletinDepto").onclick = generarPdfDepartamento;
  listarBoletines();
}

function listarBoletines() {
  const nivel = $("filtroNivel").value.toLowerCase(), prio = $("filtroPrioridad").value, grupo = $("filtroGrupo").value;
  const texto = normalizarTexto($("filtroTexto").value);
  const filas = R.priorizacion_2026.filter(p => {
    const m = estado.porCodigo[p.cod_mpio], pred = R.prediccion_2026[p.cod_mpio];
    if (nivel && (!pred || pred.pred !== nivel)) return false;
    if (prio === "si" && p.rango > estado.K) return false;
    if (grupo && m.cluster_nombre !== grupo) return false;
    if (texto && !normalizarTexto(m.nombreBonito).includes(texto)) return false;
    return true;
  });
  $("boletinesContenido").className = "";
  $("boletinesContenido").innerHTML = "<div class='mensaje aviso'><b>Lo que este sistema no puede predecir:</b><ul>" +
    NO_PUEDE_PREDECIR.map(t => "<li>" + t + "</li>").join("") + "</ul></div><p class='nota'>" + filas.length + " municipios con el filtro actual.</p>" +
    "<div class='tabla-scroll'><table><tr><th>Prioridad</th><th>Municipio</th><th>Nivel 2026</th><th>Grupo</th><th class='num'>Sismos M≥2,0 en 2025</th><th>Evacuación</th><th></th></tr>" +
    filas.map(p => {
      const m = estado.porCodigo[p.cod_mpio], pred = R.prediccion_2026[p.cod_mpio];
      const ev = (estado.evacuacion[p.cod_mpio] || []).length;
      return "<tr><td>#" + p.rango + (p.rango <= estado.K ? " ★" : "") + "</td><td>" + m.nombreBonito + "</td><td>" + (pred ? etiquetaNivel(pred.pred) : "—") +
        "</td><td>" + m.cluster_nombre + "</td><td class='num'>" + p.n_m25_2025 + "</td><td>" + (ev ? ev + " puntos" : "General") +
        "</td><td><button data-boletin='" + p.cod_mpio + "'>Descargar PDF</button></td></tr>";
    }).join("") + "</table></div>";
  document.querySelectorAll("[data-boletin]").forEach(b => { b.onclick = () => generarPdfMunicipio(b.dataset.boletin); });
}

// ---------- Ayudas para escribir el PDF ----------
function crearDocumento() {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "letter" });
  const pdf = { doc: doc, y: 18, margen: 16, ancho: 216 - 32 };
  return pdf;
}
function saltoSiHaceFalta(pdf, alto) {
  if (pdf.y + alto > 265) { pdf.doc.addPage(); pdf.y = 18; }
}
function titulo(pdf, texto, tam) {
  pdf.y += 2;
  saltoSiHaceFalta(pdf, 12);
  pdf.doc.setFont("helvetica", "bold"); pdf.doc.setFontSize(tam || 12); pdf.doc.setTextColor(31, 122, 61);
  pdf.doc.text(texto, pdf.margen, pdf.y); pdf.y += (tam || 12) * 0.5 + 2;
}
function parrafo(pdf, texto, opciones) {
  const op = opciones || {};
  pdf.doc.setFont("helvetica", op.negrita ? "bold" : "normal"); pdf.doc.setFontSize(op.tam || 10);
  pdf.doc.setTextColor(...(op.color || [28, 28, 28]));
  const lineas = pdf.doc.splitTextToSize(texto, pdf.ancho - (op.sangria || 0));
  for (const l of lineas) { saltoSiHaceFalta(pdf, 5); pdf.doc.text(l, pdf.margen + (op.sangria || 0), pdf.y); pdf.y += (op.tam || 10) * 0.45; }
  pdf.y += 1.5;
}
function vinetas(pdf, lista) {
  for (const t of lista) parrafo(pdf, "-  " + t, { sangria: 3 });
}
function recuadro(pdf, texto, colorFondo, colorTexto) {
  pdf.doc.setFont("helvetica", "bold"); pdf.doc.setFontSize(9.5);
  const lineas = pdf.doc.splitTextToSize(texto, pdf.ancho - 8);
  const alto = lineas.length * 4.3 + 6;
  saltoSiHaceFalta(pdf, alto);
  pdf.doc.setFillColor(...colorFondo); pdf.doc.rect(pdf.margen, pdf.y - 4, pdf.ancho, alto, "F");
  pdf.doc.setTextColor(...colorTexto);
  pdf.doc.text(lineas, pdf.margen + 4, pdf.y + 1);
  pdf.y += alto + 3;
}
// Nombre que aparece en el encabezado de los boletines (cámbienlo por el de su equipo)
const NOMBRE_EQUIPO = "Equipo Sismos Santander";

function encabezadoPdf(pdf, subtitulo) {
  const d = pdf.doc;
  d.setFillColor(28, 28, 28); d.rect(0, 0, 216, 30, "F");
  // Franja con los colores de Santander (rojo, verde, amarillo, negro)
  const franja = [[200, 16, 46], [31, 122, 61], [242, 194, 48], [28, 28, 28]];
  franja.forEach((c, i) => { d.setFillColor(...c); d.rect(i * 54, 30, 54, 2.2, "F"); });
  d.setTextColor(255, 255, 255); d.setFont("helvetica", "bold"); d.setFontSize(16);
  d.text("Boletín de actividad sísmica", pdf.margen, 12);
  d.setFont("helvetica", "normal"); d.setFontSize(10);
  d.text(subtitulo + "  ·  Emitido: " + fechaCorta(new Date()), pdf.margen, 19);
  d.setFontSize(8.5); d.setTextColor(216, 208, 199);
  d.text("Elaborado por " + NOMBRE_EQUIPO + " con datos oficiales de: SGC, DANE, UNGRD e IGAC", pdf.margen, 25.5);
  // Sello de documento no oficial
  d.setDrawColor(255, 213, 74); d.setLineWidth(0.6); d.roundedRect(150, 6, 50, 15, 2, 2, "S");
  d.setTextColor(255, 213, 74); d.setFont("helvetica", "bold"); d.setFontSize(8.5);
  d.text("DOCUMENTO ACADÉMICO", 175, 12, { align: "center" });
  d.text("NO OFICIAL", 175, 17, { align: "center" });
  pdf.y = 42;
}
function piePdf(pdf) {
  const d = pdf.doc, n = d.getNumberOfPages();
  for (let i = 1; i <= n; i++) {
    d.setPage(i); d.setFont("helvetica", "normal"); d.setFontSize(7.5); d.setTextColor(120, 110, 100);
    d.text("Sismos Santander · prototipo académico · Catálogo SGC hasta " + fechaCorta(estado.fechaFin), 16, 272);
    d.text("Página " + i + " de " + n, 216 - 16, 272, { align: "right" });
  }
}
const COLOR_NIVEL = { bajo: [31, 122, 61], medio: [217, 165, 28], alto: [200, 16, 46] };

// ---------- Boletín de un municipio ----------
async function generarPdfMunicipio(cod) {
  const b = datosBoletin(cod);
  mostrarMensaje("Generando boletín de " + b.municipio + "...");
  const mapa = await mapaMunicipio(cod, b);
  const imagenMapa = mapa ? mapa.imagen : null;
  const pdf = crearDocumento();
  encabezadoPdf(pdf, b.municipio + ", Santander");

  recuadro(pdf, AVISO_NO_PREDICE, [255, 243, 205], [110, 80, 0]);

  titulo(pdf, b.municipio, 18);
  parrafo(pdf, "Población (DANE, proyección 2020): " + (b.poblacion ? b.poblacion.toLocaleString("es-CO") + " habitantes" : "sin dato") +
    (b.pctRural !== undefined ? " (" + Math.round(b.pctRural * 100) + " % rural)" : "") + "  ·  Catálogo SGC hasta " + fechaCorta(estado.fechaFin), { color: [111, 102, 94] });

  // Nivel previsto
  if (b.nivel) {
    const c = COLOR_NIVEL[b.nivel];
    pdf.doc.setFillColor(...c); pdf.doc.roundedRect(pdf.margen, pdf.y - 4, 60, 10, 2, 2, "F");
    pdf.doc.setTextColor(255, 255, 255); pdf.doc.setFont("helvetica", "bold"); pdf.doc.setFontSize(12);
    pdf.doc.text("Actividad " + b.nivel, pdf.margen + 4, pdf.y + 2.5);
    pdf.doc.setTextColor(28, 28, 28); pdf.doc.setFont("helvetica", "normal"); pdf.doc.setFontSize(10);
    pdf.doc.text("Nivel previsto para 2026 (bajo " + Math.round(b.probs[0] * 100) + " %, medio " +
      Math.round(b.probs[1] * 100) + " %, alto " + Math.round(b.probs[2] * 100) + " %)", pdf.margen + 64, pdf.y + 2.5);
    pdf.y += 12;
  }
  parrafo(pdf, "Bajo/Medio/Alto son los terciles del índice de riesgo del equipo (50 % actividad sísmica + 30 % exposición poblacional + 20 % vulnerabilidad). El nivel ordena municipios entre sí, no dice cuántos sismos habrá ni la probabilidad de un sismo fuerte. " +
    "En la zona del Nido de Bucaramanga un nivel alto refleja sobre todo sismos profundos, que en general se sienten poco.", { tam: 9, color: [111, 102, 94] });

  titulo(pdf, "Lo que este sistema no puede predecir");
  vinetas(pdf, NO_PUEDE_PREDECIR);

  titulo(pdf, "Actividad sísmica");
  const ano = b.sismosAno;
  vinetas(pdf, [
    "Sismos de magnitud 2,0 o más en 2025: " + b.n2025 + (b.prom3 !== undefined ? " (promedio de los 3 años anteriores: " + redondear(b.prom3, 1) + ")" : ""),
    "Sismos de magnitud 2 o más en los últimos 12 meses del catálogo: " + ano.length + (ano.length ? " (magnitud máxima " + Math.max(...ano.map(e => e.mag)) + ", profundidad promedio " + redondear(media(ano.map(e => e.prof)), 0) + " km)" : ""),
    b.ultimo ? "Último sismo registrado: " + fechaCorta(b.ultimo.fecha) + ", magnitud " + b.ultimo.mag + ", profundidad " + redondear(b.ultimo.prof, 0) + " km" : "Sin sismos registrados",
    b.mayor ? "Sismo de mayor magnitud desde 1993: " + fechaCorta(b.mayor.fecha) + ", magnitud " + b.mayor.mag + ", profundidad " + redondear(b.mayor.prof, 0) + " km" : "",
    "Profundidad típica: " + redondear(b.profMedia, 0) + " km; " + Math.round((b.pctSuperficial || 0) * 100) + " % de sismos superficiales (menos de 50 km)",
    "Grupo territorial: " + b.grupo,
    "Falla activa más cercana a la cabecera: " + (b.falla ? b.falla + ", a " + redondear(b.distFalla, 1) + " km" : "sin dato")
  ].filter(Boolean));

  if (imagenMapa) {
    saltoSiHaceFalta(pdf, 125);
    titulo(pdf, (mapa.satelital ? "Mapa satelital de " : "Mapa de ") + b.municipio);
    pdf.doc.addImage(imagenMapa, "JPEG", pdf.margen, pdf.y, pdf.ancho, pdf.ancho * 448 / 768);
    pdf.y += pdf.ancho * 448 / 768 + 3;
    parrafo(pdf, (mapa.conLimite ? "Línea amarilla: límite del municipio. " : "") +
      "Círculos: " + mapa.nSismos + " epicentros del último año (más grandes = mayor magnitud; rojos = superficiales, naranja = profundos). Línea naranja punteada: fallas activas." +
      (b.evacuacion.some(e => !isNaN(e.lat)) ? " Puntos verdes: puntos de encuentro, numerados como en la sección de evacuación." : ""),
      { tam: 8.5, color: [111, 102, 94] });
  }

  titulo(pdf, "Prioridad departamental para 2026");
  if (b.puesto) {
    parrafo(pdf, "Puesto " + b.puesto + " de 87 municipios de Santander" +
      (b.priorizado ? ". Está entre los " + estado.K + " municipios priorizados para acciones de preparación (visitas técnicas, simulacros, revisión de planes)." : ". No está entre los " + estado.K + " priorizados.") +
      " Confianza " + b.confianza + ": quedó en el grupo priorizado en " + Math.round(b.probTopK * 100) + " % de los entrenamientos del agente.");
    if (b.contrib) parrafo(pdf, "Aporte al puntaje: amenaza " + redondear(b.contrib[0], 2) + ", exposición " + redondear(b.contrib[1], 2) + ", vulnerabilidad " + redondear(b.contrib[2], 2) + ".", { tam: 9, color: [111, 102, 94] });
  }
  vinetas(pdf, [
    "Emergencias reportadas a la UNGRD (2019–2025): " + redondear(b.emergencias, 1) + " por año en promedio",
    "Personas afectadas acumuladas: " + (b.personas || 0).toLocaleString("es-CO") + "  ·  Fallecidos: " + (b.fallecidos || 0) + "  ·  Heridos: " + (b.heridos || 0)
  ]);

  titulo(pdf, "Evacuación y puntos de encuentro");
  if (b.evacuacion.length) {
    for (const [i, e] of b.evacuacion.entries()) {
      const coord = isNaN(e.lat) ? "" : " (" + e.lat.toFixed(5) + ", " + e.lon.toFixed(5) + ")";
      parrafo(pdf, (i + 1) + ". " + e.tipo + ": " + e.nombre + coord, { negrita: true });
      if (e.descripcion) parrafo(pdf, e.descripcion, { sangria: 3 });
    }
    parrafo(pdf, "Información de puntos y rutas cargada por el equipo; confírmela con la alcaldía.", { tam: 8.5, color: [111, 102, 94] });
  } else {
    parrafo(pdf, "Este boletín no tiene cargados los puntos de encuentro ni las rutas de " + b.municipio + ". Consulte el plan municipal de gestión del riesgo " +
      "y la estrategia de respuesta en la alcaldía o el Consejo Municipal de Gestión del Riesgo de Desastres (CMGRD).");
    vinetas(pdf, [
      "Evacúe solo cuando pare el movimiento y si la edificación tiene daños, caminando, sin correr y sin devolverse por objetos.",
      "Siga las señales de ruta de evacuación de su edificio, colegio o conjunto hasta el punto de encuentro.",
      "Prefiera espacios abiertos (parques, canchas) lejos de edificios, cables, árboles grandes y taludes.",
      "Evite puentes, laderas y bordes de quebradas por el riesgo de deslizamientos y avenidas torrenciales.",
      "Acuerde con su familia un punto de encuentro fuera de la casa y otro fuera del barrio."
    ]);
  }

  titulo(pdf, "Qué hacer antes de un sismo"); vinetas(pdf, RECOMENDACIONES.antes);
  titulo(pdf, "Qué hacer durante un sismo"); vinetas(pdf, RECOMENDACIONES.durante);
  titulo(pdf, "Qué hacer después de un sismo"); vinetas(pdf, RECOMENDACIONES.despues);

  titulo(pdf, "Líneas de emergencia");
  parrafo(pdf, LINEAS_EMERGENCIA.join("   ·   "), { negrita: true });

  titulo(pdf, "Fuentes y método");
  parrafo(pdf, "Sismos: catálogo unificado de la Red Sismológica Nacional del SGC (1993 a hoy, 208.230 eventos procesados). Población: DANE, proyecciones 2020–2035. Emergencias: UNGRD 2019–2025 (datos.gov.co). " +
    "Límites municipales: cartografía IGAC/DANE. Fallas activas: GEM Global Active Faults. Riesgo Bajo/Medio/Alto por terciles del índice del equipo; " +
    "clasificador supervisado con split 75/25 y clustering aglomerativo; prioridad con agente de aprendizaje por refuerzo (PPO vs DQN). Detalle en el README del proyecto.", { tam: 8.5, color: [111, 102, 94] });

  piePdf(pdf);
  pdf.doc.save("boletin_" + normalizarTexto(b.municipio).replace(/\s+/g, "_") + ".pdf");
  mostrarMensaje("Boletín de " + b.municipio + " descargado." + (imagenMapa ? "" : " No se pudo agregar el mapa (revisa la conexión a internet)."));
}

// ---------- Boletín departamental (resumen) ----------
function generarPdfDepartamento() {
  const pdf = crearDocumento();
  encabezadoPdf(pdf, "Departamento de Santander");
  recuadro(pdf, AVISO_NO_PREDICE, [255, 243, 205], [110, 80, 0]);
  titulo(pdf, "Lo que este sistema no puede predecir");
  vinetas(pdf, NO_PUEDE_PREDECIR);
  const conteo = { alto: 0, medio: 0, bajo: 0 };
  estado.santander.forEach(m => { const p = R.prediccion_2026[m.cod]; if (p) conteo[p.pred]++; });
  const n2025 = estado.santander.reduce((s, m) => s + (R.serie_n_m25[m.cod][2025] || 0), 0);
  titulo(pdf, "Resumen", 14);
  parrafo(pdf, "En 2025 se registraron " + n2025.toLocaleString("es-CO") + " sismos de magnitud 2,0 o más en los 87 municipios de Santander. " +
    "Nivel previsto para 2026: " + conteo.alto + " municipios con actividad alta, " + conteo.medio + " media y " + conteo.bajo + " baja.");
  titulo(pdf, "Municipios priorizados (" + estado.K + ")");
  for (const p of R.priorizacion_2026.filter(x => x.rango <= estado.K)) {
    const pred = R.prediccion_2026[p.cod_mpio];
    parrafo(pdf, "#" + p.rango + "  " + estado.porCodigo[p.cod_mpio].nombreBonito + "  ·  actividad " + (pred ? pred.pred : "—") + "  ·  confianza " + p.confianza +
      "  ·  " + (p.poblacion_total || 0).toLocaleString("es-CO") + " hab.  ·  " + p.n_m25_2025 + " sismos M≥2,0 en 2025");
  }
  titulo(pdf, "Los demás municipios");
  for (const p of R.priorizacion_2026.filter(x => x.rango > estado.K)) {
    const pred = R.prediccion_2026[p.cod_mpio];
    parrafo(pdf, "#" + p.rango + "  " + estado.porCodigo[p.cod_mpio].nombreBonito + "  ·  actividad " + (pred ? pred.pred : "—") + "  ·  " + p.n_m25_2025 + " sismos M≥2,0 en 2025", { tam: 9 });
  }
  titulo(pdf, "Líneas de emergencia");
  parrafo(pdf, LINEAS_EMERGENCIA.join("   ·   "), { negrita: true });
  piePdf(pdf);
  pdf.doc.save("boletin_santander.pdf");
}
