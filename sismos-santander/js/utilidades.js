// =============================================================
// utilidades.js — funciones pequeñas que usan todos los módulos
// =============================================================

// Generador de números aleatorios con semilla (mulberry32).
// Con la misma semilla siempre salen los mismos números, así los
// resultados se pueden repetir y verificar.
function crearAleatorio(semilla) {
  let a = semilla >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Mezcla un arreglo (Fisher-Yates) usando el generador con semilla
function mezclar(arreglo, aleatorio) {
  const copia = arreglo.slice();
  for (let i = copia.length - 1; i > 0; i--) {
    const j = Math.floor(aleatorio() * (i + 1));
    const tmp = copia[i];
    copia[i] = copia[j];
    copia[j] = tmp;
  }
  return copia;
}

// Quita tildes, pasa a minúscula y limpia espacios: "Jordán " -> "jordan"
function normalizarTexto(texto) {
  return String(texto == null ? "" : texto)
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/\s+/g, " ").trim();
}

// Convierte "6,862" o "6.862" o 6.862 a número. Si no se puede, devuelve NaN
function aNumero(valor) {
  if (typeof valor === "number") return valor;
  if (valor == null) return NaN;
  let texto = String(valor).trim();
  if (texto === "") return NaN;
  if (texto.indexOf(".") === -1) texto = texto.replace(",", ".");
  const n = Number(texto);
  return isFinite(n) ? n : NaN;
}

function media(lista) {
  if (lista.length === 0) return NaN;
  let suma = 0;
  for (const v of lista) suma += v;
  return suma / lista.length;
}

function desviacion(lista) {
  if (lista.length < 2) return 0;
  const m = media(lista);
  let suma = 0;
  for (const v of lista) suma += (v - m) * (v - m);
  return Math.sqrt(suma / (lista.length - 1));
}

// Cuantil con interpolación lineal (p entre 0 y 1)
function cuantil(lista, p) {
  const ordenada = lista.filter(v => !isNaN(v)).sort((a, b) => a - b);
  if (ordenada.length === 0) return NaN;
  const pos = (ordenada.length - 1) * p;
  const abajo = Math.floor(pos);
  const arriba = Math.ceil(pos);
  return ordenada[abajo] + (ordenada[arriba] - ordenada[abajo]) * (pos - abajo);
}

function mediana(lista) {
  return cuantil(lista, 0.5);
}

// Distancia en km entre dos puntos (fórmula de haversine)
function distanciaKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// Redondeo para mostrar
function redondear(valor, decimales) {
  if (valor == null || isNaN(valor)) return "—";
  const f = Math.pow(10, decimales);
  return Math.round(valor * f) / f;
}

// Pone en mayúscula la primera letra de cada palabra: "LOS SANTOS" -> "Los Santos"
function tipoTitulo(texto) {
  return String(texto).toLowerCase().replace(/(^|\s)\S/g, l => l.toUpperCase());
}

// Lee un CSV sencillo (con comillas opcionales) y devuelve una lista de filas
function parsearCsv(texto) {
  const filas = [];
  for (const linea of texto.replace(/\r/g, "").split("\n")) {
    if (linea.trim() === "") continue;
    const celdas = [];
    let actual = "", entreComillas = false;
    for (const c of linea) {
      if (c === '"') entreComillas = !entreComillas;
      else if (c === "," && !entreComillas) { celdas.push(actual); actual = ""; }
      else actual += c;
    }
    celdas.push(actual);
    filas.push(celdas.map(x => x.trim()));
  }
  return filas;
}
