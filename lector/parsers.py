"""Extracción de serial, contador y fecha según el modelo de impresora.

Cada modelo tiene su propio extractor porque el reporte de configuración
o de estadísticas cambia de un fabricante a otro:

- Lexmark: "Total cómputo caras impresas" (total de la sección Total > Mono)
- HP:      "Ciclos del motor"
- OKI:     "Total mono" (Impres.Total)
- Ricoh:   "Contador total"

Cuando la etiqueta del serial no se lee bien por OCR, se usa un patrón de
respaldo basado en el formato del serial de cada fabricante. Esos valores se
marcan para revisión (respaldo=True).
"""

import re
from dataclasses import dataclass
from datetime import datetime


class LecturaError(Exception):
    """El PDF no pudo leerse (modelo desconocido o datos faltantes)."""


MESES = {
    "jan": 1, "ene": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "ago": 8, "sep": 9, "oct": 10, "nov": 11,
    "dec": 12, "dic": 12,
}

# Zona relativa (x0, y0, x1, y1) de la página 1 donde suele estar la nota manuscrita.
# Calibrada con los 4 ejemplos; ajustar si cambia el formato de escaneo.
NOTA_RECORTE = {
    "Ricoh SP 4510DN": (0.38, 0.02, 0.68, 0.075),
    "Lexmark MX511de": (0.72, 0.00, 0.99, 0.07),
    "HP LaserJet MFP E52645": (0.40, 0.02, 0.62, 0.09),
}

SERIE = r"([A-Z0-9]{6,20})"
UMBRAL_CONFIANZA = 80.0


@dataclass
class Lectura:
    modelo: str
    serial: str
    contador: int
    fecha: datetime | None
    confianza_serial: float | None  # None si no se pudo verificar en el OCR
    respaldo: bool = False          # serial obtenido con patrón de respaldo


def _numero(texto: str) -> int:
    return int(re.sub(r"\D", "", texto))


def _fecha(anio: str, mes: int, dia: int, hora: str = "00:00:00", ampm: str | None = None):
    try:
        formato = "%Y-%m-%d %I:%M:%S %p" if ampm else "%Y-%m-%d %H:%M:%S"
        texto = f"{anio}-{mes:02d}-{dia:02d} {hora} {ampm or ''}".strip()
        return datetime.strptime(texto, formato)
    except ValueError:
        return None


def _fecha_con_mes_texto(match):
    if not match or match.group(1)[:3].lower() not in MESES:
        return None
    return _fecha(match.group(3), MESES[match.group(1)[:3].lower()], int(match.group(2)),
                  match.group(4), match.group(5).upper())


def _serial(texto: str, patron_etiqueta: str, patron_respaldo: str | None):
    """Devuelve (serial, usó_respaldo). Busca primero por etiqueta y luego por formato."""
    m = re.search(patron_etiqueta, texto, re.I)
    if m:
        return m.group(1).upper(), False
    if patron_respaldo:
        m = re.search(patron_respaldo, texto)
        if m:
            return m.group(1).upper(), True
    return None, False


def _ricoh(t: str):
    serial, respaldo = _serial(
        t,
        r"(?:ID|1D|lD|I[dD])\s*m\S{1,6}\s+" + SERIE,
        r"\b(T578[A-Z0-9]{6,8})\b",
    )
    contador = re.search(r"Contador\s+total[ \t]+(\d[\d.,]*)", t, re.I)
    fecha = re.search(
        r"(\w{3})\.?\s*(\d{1,2}),?\s*(\d{4})\s+(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)", t, re.I
    )
    return serial, _numero(contador.group(1)) if contador else None, _fecha_con_mes_texto(fecha), respaldo


def _lexmark(t: str):
    # El serial de la impresora está bajo el encabezado "Impresora" (no el de cartuchos).
    serial, respaldo = None, False
    encabezado = re.search(r"^[ \t]*Impresora[ \t]*$", t, re.M)
    if encabezado:
        bloque = t[encabezado.end(): encabezado.end() + 400]
        serial, respaldo = _serial(bloque, r"N\S{1,2}mero\s+de\s+serie[ \t]+" + SERIE, None)
    if not serial:
        m = re.search(r"\b(70[0-9A-Z]{11})\b", t)
        if m:
            serial, respaldo = m.group(1), True

    contador = None
    seccion = re.search(r"C\S{1,2}mputo\s+caras\s+impresas", t, re.I)
    if seccion:
        m = re.search(r"Total[ \t:.]*\n\s*Mono[ \t]+(\d[\d.,]*)", t[seccion.end():], re.I)
        contador = _numero(m.group(1)) if m else None

    fecha = re.search(r"Fecha\s+de\s+impresi\S{1,2}n\s+(\d{4})-(\d{2})-(\d{2})", t, re.I)
    f = _fecha(fecha.group(1), int(fecha.group(2)), int(fecha.group(3))) if fecha else None
    return serial, contador, f, respaldo


def _hp(t: str):
    serial, respaldo = _serial(
        t,
        r"N\S{1,2}mero\s+de\s+serie\s+del\s+producto\S*\s*" + SERIE,
        r"\b((?:MXB|BRB)[A-Z0-9]{6,8})\b",
    )
    contador = re.search(r"Ciclos\s+del\s+motor\S{0,2}\s*:?\s*(\d[\d.,]*)", t, re.I)
    fecha = re.search(r"(\w{3})/(\d{2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)", t, re.I)
    return serial, _numero(contador.group(1)) if contador else None, _fecha_con_mes_texto(fecha), respaldo


def _oki(t: str):
    serial, respaldo = _serial(
        t,
        r"N\S{1,2}mero\s+de\s+serie\s+Impresora:?\s*" + SERIE,
        r"\b(AK[0-9A-Z]{8})\b",
    )
    contador = re.search(r"Impres\.\s*Total[ \t]+(\d[\d.,]*)", t, re.I) or re.search(
        r"Mono\s*:\s*(\d{4,})", t, re.I
    )
    fecha = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", t)
    f = None
    if fecha:
        try:
            f = datetime.strptime(f"{fecha.group(3)}-{fecha.group(1)}-{fecha.group(2)} {fecha.group(4)}",
                                  "%Y-%m-%d %H:%M")
        except ValueError:
            f = None
    return serial, _numero(contador.group(1)) if contador else None, f, respaldo


MODELOS = [
    ("Ricoh SP 4510DN", r"R\W?[il1]\W?C\W?OH|Contador\s+total", _ricoh),
    ("Lexmark MX511de", r"Lexmark|L[e3]xm[a@]rk|Estad\S{1,2}sticas\s+dispositivo", _lexmark),
    ("HP LaserJet MFP E52645", r"HP\s*Laser\s*Jet|LaserJet|Ciclos\s+del\s+motor", _hp),
    ("OKI ES5112", r"\bOKI\b|ES\s?5112|Infor\.?\s*uso\s+impresora|Impres\.\s*Total", _oki),
]


def confianza_serial(serial: str, palabras: list[tuple[str, float]]) -> float | None:
    valores = [conf for texto, conf in palabras if texto.upper() == serial]
    return min(valores) if valores else None


def leer(texto: str, palabras: list[tuple[str, float]]) -> Lectura:
    for modelo, patron, extractor in MODELOS:
        if re.search(patron, texto, re.I):
            serial, contador, fecha, respaldo = extractor(texto)
            if not serial:
                raise LecturaError(f"{modelo}: no se encontró el número de serie")
            if contador is None:
                raise LecturaError(f"{modelo}: no se encontró el contador")
            return Lectura(
                modelo=modelo,
                serial=serial,
                contador=contador,
                fecha=fecha,
                confianza_serial=confianza_serial(serial, palabras),
                respaldo=respaldo,
            )
    raise LecturaError("modelo de impresora no reconocido")
