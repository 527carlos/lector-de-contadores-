import io
import time
import zipfile

import pytest

import app as lector_app


@pytest.fixture
def cliente(monkeypatch):
    def falso(zip_path, trabajo, excel_path=None, progreso=None):
        for i in range(1, 4):
            if progreso:
                progreso(i, 3)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("contadores.txt", "serial\tcontador\n")
        return buffer.getvalue()

    monkeypatch.setattr(lector_app, "procesar_zip", falso)
    lector_app.app.config["TESTING"] = True
    return lector_app.app.test_client()


def _zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("impresora.pdf", b"%PDF-1.4 fake")
    return buffer.getvalue()


def _esperar(cliente, trabajo_id, limite=10):
    for _ in range(int(limite / 0.05)):
        estado = cliente.get(f"/estado/{trabajo_id}").get_json()
        if estado["estado"] != "procesando":
            return estado
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó")


def test_flujo_completo_subida_progreso_y_descarga(cliente):
    r = cliente.post("/procesar", data={"archivo": (io.BytesIO(_zip_bytes()), "pdfs.zip")},
                     content_type="multipart/form-data")
    assert r.status_code == 202
    trabajo_id = r.get_json()["id"]

    estado = _esperar(cliente, trabajo_id)
    assert estado["estado"] == "listo"
    assert estado["hechos"] == estado["total"] == 3

    descarga = cliente.get(f"/descargar/{trabajo_id}")
    assert descarga.status_code == 200
    assert descarga.mimetype == "application/zip"
    assert "contadores.txt" in zipfile.ZipFile(io.BytesIO(descarga.data)).namelist()


def test_rechaza_archivo_que_no_es_zip(cliente):
    r = cliente.post("/procesar", data={"archivo": (io.BytesIO(b"x"), "datos.rar")},
                     content_type="multipart/form-data")
    assert r.status_code == 400
    assert "zip" in r.get_json()["error"]


def test_rechaza_excel_invalido_antes_de_procesar(cliente):
    r = cliente.post(
        "/procesar",
        data={
            "archivo": (io.BytesIO(_zip_bytes()), "pdfs.zip"),
            "excel": (io.BytesIO(b"no es excel"), "lista.xlsx"),
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "Listado de seriales" in r.get_json()["error"]


def test_trabajo_inexistente_da_404(cliente):
    assert cliente.get("/estado/no-existe").status_code == 404
    assert cliente.get("/descargar/no-existe").status_code == 404
