import io
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from lector.parsers import LecturaError, confianza_serial, leer
from lector.procesar import deduplicar, extraer_pdfs, Registro

RICOH = """Referencia del sistema
ID máquina T578H805864 de
Contador total 51065
Oct. 27,2026 01:15:55PM
"""

LEXMARK = """Estadísticas dispositivo (Página 1)
Impresora
Fecha instal. 2014-10-17
Número de serie 701545HH0MD7R
Cómputo caras impresas
Imprimir
Mono 120499
Total : 120499
Copia
Mono 66
Total 66

Total
Mono 120565
Total . 120565
Caras impresas en negro
Unidad imagen
Número de serie CAB1924540DE
Fecha de impresión 2026-10-27
"""

HP = """Página configuración HP LaserJet MFP E52645
Número de serie del producto: MXBCS9C0LD
Ciclos del motor*: 65359
Oct/27/2026 12:04:54 PM
"""

OKI = """Infor. uso impresora ES5112
Numero de serie Impresora:AK97001630 10/27/2026 08:59'08*
Impres.Total 123495
Mono:123495
"""


@pytest.mark.parametrize(
    "texto, modelo, serial, contador",
    [
        (RICOH, "Ricoh SP 4510DN", "T578H805864", 51065),
        (LEXMARK, "Lexmark MX511de", "701545HH0MD7R", 120565),
        (HP, "HP LaserJet MFP E52645", "MXBCS9C0LD", 65359),
        (OKI, "OKI ES5112", "AK97001630", 123495),
    ],
)
def test_extrae_modelo_serial_y_contador(texto, modelo, serial, contador):
    lectura = leer(texto, [])
    assert lectura.modelo == modelo
    assert lectura.serial == serial
    assert lectura.contador == contador


def test_fechas_de_impresion():
    assert leer(RICOH, []).fecha == datetime(2026, 10, 27, 13, 15, 55)
    assert leer(LEXMARK, []).fecha == datetime(2026, 10, 27)
    assert leer(HP, []).fecha == datetime(2026, 10, 27, 12, 4, 54)
    assert leer(OKI, []).fecha == datetime(2026, 10, 27, 8, 59)


def test_modelo_desconocido():
    with pytest.raises(LecturaError, match="no reconocido"):
        leer("texto cualquiera sin datos", [])


def test_serial_no_encontrado():
    with pytest.raises(LecturaError, match="serie"):
        leer("Ciclos del motor*: 100\nHP LaserJet", [])


def test_confianza_del_serial():
    palabras = [("MXBCS9C0LD", 62.0), ("otra", 95.0), ("MXBCS9C0LD", 70.0)]
    assert confianza_serial("MXBCS9C0LD", palabras) == 62.0
    assert confianza_serial("NOEXISTE", palabras) is None


def _registro(archivo, serial, fecha):
    return Registro(archivo, Path(archivo), "OKI ES5112", serial, 1, fecha, 99.0, "")


def test_duplicados_conserva_el_mas_reciente():
    a = _registro("a.pdf", "ABC123456", datetime(2026, 10, 1))
    b = _registro("b.pdf", "ABC123456", datetime(2026, 10, 27))
    c = _registro("c.pdf", "XYZ987654", None)
    conservados, descartados = deduplicar([a, b, c])
    assert {r.archivo for r in conservados} == {"b.pdf", "c.pdf"}
    assert [(d.archivo, g.archivo) for d, g in descartados] == [("a.pdf", "b.pdf")]


def test_zip_ignora_rutas_peligrosas_y_no_pdf(tmp_path):
    zip_path = tmp_path / "entrada.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("carpeta/impresora1.pdf", b"%PDF-1.4 fake")
        zf.writestr("../evil.pdf", b"x")
        zf.writestr("notas.txt", b"hola")
        zf.writestr("__MACOSX/._impresora1.pdf", b"x")
    errores = []
    pdfs = extraer_pdfs(zip_path, tmp_path / "out", errores)
    assert [nombre for nombre, _ in pdfs] == ["impresora1.pdf"]
    assert any("ruta sospechosa" in e for e in errores)
    assert any("no es PDF" in e for e in errores)


def test_ricoh_sin_etiqueta_usa_respaldo_por_formato():
    texto = "Referencia del sistema\nXX Mg T578H602639 de\nContador total 12345\n"
    lectura = leer(texto, [])
    assert lectura.serial == "T578H602639"
    assert lectura.contador == 12345
    assert lectura.respaldo is True


def test_hp_serie_con_formato_brb_usa_respaldo():
    texto = "HP LaserJet MFP E52645\nBRBSQD61CN\nCiclos del motor*: 500\n"
    lectura = leer(texto, [])
    assert lectura.serial == "BRBSQD61CN"
    assert lectura.respaldo is True


def test_oki_contador_de_respaldo_mono():
    texto = "OKI ES5112\nNumero de serie Impresora:AK97001459\nMono:123495\n"
    lectura = leer(texto, [])
    assert lectura.serial == "AK97001459"
    assert lectura.contador == 123495
    assert lectura.respaldo is False


def test_lexmark_serie_con_etiqueta_mal_leida_usa_respaldo():
    texto = (
        "Estadísticas dispositivo\nImpresora\nFecha instal. 2014\nNxmero de sene 70157GHH1GY5L\n"
        "Cómputo caras impresas\nTotal\nMono 1000\n"
    )
    lectura = leer(texto, [])
    assert lectura.serial == "70157GHH1GY5L"
    assert lectura.contador == 1000
    assert lectura.respaldo is True
