"""Extracción de serial, contador y fecha según el modelo de impresora.

Cada modelo tiene su propio extractor porque el reporte de configuración
o de estadísticas cambia de un fabricante a otro:

- Lexmark: "Total cómputo caras impresas" (total de la sección Total > Mono)
- HP:      "Ciclos del motor"
- OKI:     "Total mono" (Impres.Total)
- Ricoh:   "Contador total"
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


def _numero(texto: str) -> int:
    return int(re.sub(r"\D", "", texto))


def _fecha(anio: str, mes: int, dia: int, hora: str = "00:00:00", ampm: str | None = None):
    try:
        formato = "%Y-%m-%d %I:%M:%S %p" if ampm else "%Y-%m-%d %H:%M:%S"
        texto = f"{anio}-{mes:02d}-{dia:02d} {hora} {ampm or ''}".strip()
        return datetime.strptime(texto, formato)
    except ValueError:
        return None


def _ricoh(t: str):
    serial = re.search(r"(?:ID|1D|lD)\s*m[aá]quina\s+" + SERIE, t, re.I)
    contador = re.search(r"Contador\s+total[ \t]+(\d[\d.,]*)", t, re.I)
    fecha = re.search(
        r"(\w{3})\.?\s*(\d{1,2}),?\s*(\d{4})\s+(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)", t, re.I
    )
    f = None
    if fecha and fecha.group(1)[:3].lower() in MESES:
        f = _fecha(fecha.group(3), MESES[fecha.group(1)[:3].lower()], int(fecha.group(2)),
                   fecha.group(4), fecha.group(5).upper())
    return (
        serial.group(1).upper() if serial else None,
        _numero(contador.group(1)) if contador else None,
        f,
    )


def _lexmark(t: str):
    # El serial de la impresora está bajo el encabezado "Impresora" (no el de cartuchos).
    serial = None
    encabezado = re.search(r"^[ \t]*Impresora[ \t]*$", t, re.M)
    if encabezado:
        bloque = t[encabezado.end(): encabezado.end() + 400]
        m = re.search(r"N[úu]mero\s+de\s+serie[ \t]+" + SERIE, bloque, re.I)
        serial = m.group(1).upper() if m else None

    contador = None
    seccion = re.search(r"C[oó]mputo\s+caras\s+impresas", t, re.I)
    if seccion:
        m = re.search(r"Total[ \t:.]*\n\s*Mono[ \t]+(\d[\d.,]*)", t[seccion.end():], re.I)
        contador = _numero(m.group(1)) if m else None

    fecha = re.search(r"Fecha\s+de\s+impresi[oó]n\s+(\d{4})-(\d{2})-(\d{2})", t, re.I)
    f = _fecha(fecha.group(1), int(fecha.group(2)), int(fecha.group(3))) if fecha else None
    return serial, contador, f


def _hp(t: str):
    serial = re.search(r"N[úu]mero\s+de\s+serie\s+del\s+producto:\s*" + SERIE, t, re.I)
    contador = re.search(r"Ciclos\s+del\s+motor\*?:\s*(\d[\d.,]*)", t, re.I)
    fecha = re.search(r"(\w{3})/(\d{2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)", t, re.I)
    f = None
    if fecha and fecha.group(1)[:3].lower() in MESES:
        f = _fecha(fecha.group(3), MESES[fecha.group(1)[:3].lower()], int(fecha.group(2)),
                   fecha.group(4), fecha.group(5).upper())
    return (
        serial.group(1).upper() if serial else None,
        _numero(contador.group(1)) if contador else None,
        f,
    )


def _oki(t: str):
    serial = re.search(r"N[úu]mero\s+de\s+serie\s+Impresora:?\s*" + SERIE, t, re.I)
    contador = re.search(r"Impres\.\s*Total[ \t]+(\d[\d.,]*)", t, re.I)
    fecha = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", t)
    f = None
    if fecha:
        try:
            f = datetime.strptime(f"{fecha.group(3)}-{fecha.group(1)}-{fecha.group(2)} {fecha.group(4)}",
                                  "%Y-%m-%d %H:%M")
        except ValueError:
            f = None
    return (
        serial.group(1).upper() if serial else None,
        _numero(contador.group(1)) if contador else None,
        f,
    )


MODELOS = [
    ("Ricoh SP 4510DN", r"RICOH|Contador\s+total", _ricoh),
    ("Lexmark MX511de", r"Lexmark|Estad[ií]sticas\s+dispositivo", _lexmark),
    ("HP LaserJet MFP E52645", r"HP\s+LaserJet|Ciclos\s+del\s+motor", _hp),
    ("OKI ES5112", r"\bOKI\b|Infor\.?\s*uso\s+impresora|Impres\.\s*Total", _oki),
]


def confianza_serial(serial: str, palabras: list[tuple[str, float]]) -> float | None:
    valores = [conf for texto, conf in palabras if texto.upper() == serial]
    return min(valores) if valores else None


def leer(texto: str, palabras: list[tuple[str, float]]) -> Lectura:
    for modelo, patron, extractor in MODELOS:
        if re.search(patron, texto, re.I):
            serial, contador, fecha = extractor(texto)
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
            )
    raise LecturaError("modelo de impresora no reconocido")
