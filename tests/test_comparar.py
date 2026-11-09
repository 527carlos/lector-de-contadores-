from pathlib import Path

import pytest
from openpyxl import Workbook

from lector.comparar import ExcelError, comparar, leer_seriales_excel


def _xlsx(tmp_path: Path, filas, nombre="listado.xlsx") -> Path:
    libro = Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    ruta = tmp_path / nombre
    libro.save(ruta)
    return ruta


def test_lee_columna_con_encabezado_serial(tmp_path):
    ruta = _xlsx(tmp_path, [["Torre", "Número de serie"], ["T7", "ab12cd34"], ["T7", " ZZ99YY88 "], ["T7", None]])
    assert leer_seriales_excel(ruta) == ["AB12CD34", "ZZ99YY88"]


def test_sin_encabezado_usa_primera_columna_y_omite_primera_fila(tmp_path):
    ruta = _xlsx(tmp_path, [["encabezado"], ["AK97001630"], ["MXBCS9C0LD"], ["AK97001630"]])
    assert leer_seriales_excel(ruta) == ["AK97001630", "MXBCS9C0LD"]


def test_excel_vacio_falla(tmp_path):
    ruta = _xlsx(tmp_path, [["Serial"]])
    with pytest.raises(ExcelError, match="no se encontraron seriales"):
        leer_seriales_excel(ruta)


def test_archivo_no_excel_falla(tmp_path):
    ruta = tmp_path / "falso.xlsx"
    ruta.write_text("esto no es un excel")
    with pytest.raises(ExcelError, match="xlsx"):
        leer_seriales_excel(ruta)


def test_comparacion_completa():
    excel = ["T578H805864", "AK97001630", "701545HH0MD7R", "SOLOEXCEL1"]
    pdf = ["T578H805864", "AK97001630", "701545HHOMD7R", "SOLOPDF0002"]
    filas = {s: (estado, detalle) for s, estado, detalle in comparar(excel, pdf)}
    assert filas["T578H805864"] == ("coincide", "")
    assert filas["AK97001630"] == ("coincide", "")
    assert filas["701545HH0MD7R"][0].startswith("posible coincidencia")
    assert filas["701545HH0MD7R"][1] == "PDF: 701545HHOMD7R"
    assert filas["SOLOEXCEL1"][0] == "solo en Excel (sin PDF)"
    assert filas["SOLOPDF0002"][0] == "solo en PDF (no está en Excel)"
    # El serial de PDF con posible coincidencia no se repite como "solo en PDF".
    assert "701545HHOMD7R" not in filas


def test_comparacion_sin_coincidencias():
    filas = comparar(["AAA111BBB"], ["CCC222DDD"])
    assert sorted(estado for _, estado, _ in filas) == [
        "solo en Excel (sin PDF)",
        "solo en PDF (no está en Excel)",
    ]
