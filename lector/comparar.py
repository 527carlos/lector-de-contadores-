"""Comparación entre el listado de seriales (Excel) y los seriales leídos de los PDF."""

import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook


class ExcelError(ValueError):
    """El Excel de seriales no se pudo leer."""


ENCABEZADOS_SERIE = ("serial", "serie", "numerodeserie", "numeroserie", "nserie")


def _sin_acentos(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normal if not unicodedata.combining(c))


def _celda_a_serial(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip().upper()


def leer_seriales_excel(ruta: Path) -> list[str]:
    """Lee la primera hoja de un .xlsx.

    Usa la columna cuyo encabezado sea "Serial" / "Serie" / "Número de serie".
    Si no hay encabezado reconocible, usa la primera columna y omite la primera fila.
    """
    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except Exception as e:
        raise ExcelError("no se pudo abrir el archivo; debe ser un .xlsx válido") from e

    try:
        filas = list(libro.worksheets[0].iter_rows(values_only=True))
    finally:
        libro.close()

    if not filas:
        raise ExcelError("el Excel está vacío")

    columna = 0
    inicio = 1
    for i, celda in enumerate(filas[0]):
        if isinstance(celda, str):
            clave = re.sub(r"[^a-z]", "", _sin_acentos(celda).lower())
            if any(clave == e or (e in clave and "serie" in e) for e in ENCABEZADOS_SERIE):
                columna = i
                break
    else:
        inicio = 1  # sin encabezado reconocible: se asume que la primera fila es encabezado

    seriales: list[str] = []
    vistos: set[str] = set()
    for fila in filas[inicio:]:
        valor = _celda_a_serial(fila[columna] if columna < len(fila) else None)
        if valor and valor not in vistos:
            vistos.add(valor)
            seriales.append(valor)
    if not seriales:
        raise ExcelError("no se encontraron seriales en el Excel")
    return seriales


def _clave(serial: str) -> str:
    """Forma comparable: O se trata como 0 e I como 1 (confusiones típicas del OCR)."""
    return serial.upper().translate(str.maketrans({"O": "0", "I": "1"}))


def comparar(excel: list[str], pdf: list[str]) -> list[tuple[str, str, str]]:
    """Devuelve filas (serial, estado, detalle)."""
    pdf_unicos = sorted(set(pdf))
    pdf_set = set(pdf_unicos)
    excel_set = set(excel)

    pdf_por_clave: dict[str, list[str]] = {}
    for p in pdf_unicos:
        pdf_por_clave.setdefault(_clave(p), []).append(p)
    excel_claves = {_clave(s) for s in excel_set}

    filas: list[tuple[str, str, str]] = []
    for s in excel:
        if s in pdf_set:
            filas.append((s, "coincide", ""))
        elif _clave(s) in pdf_por_clave:
            posibles = ", ".join(pdf_por_clave[_clave(s)])
            filas.append((s, "posible coincidencia (revisar O/0, I/1)", f"PDF: {posibles}"))
        else:
            filas.append((s, "solo en Excel (sin PDF)", ""))

    for p in pdf_unicos:
        if p in excel_set or _clave(p) in excel_claves:
            continue
        filas.append((p, "solo en PDF (no está en Excel)", ""))
    return filas
