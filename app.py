import threading
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from lector.comparar import ExcelError, leer_seriales_excel
from lector.procesar import procesar_zip

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB

# Trabajos en segundo plano: id -> estado. Vive en memoria del proceso del servidor.
TRABAJOS: dict[str, dict] = {}
CANDADO = threading.Lock()


def _actualizar(trabajo_id: str, **campos) -> None:
    with CANDADO:
        TRABAJOS[trabajo_id].update(campos)


def _ejecutar(trabajo_id: str, zip_path: Path, excel_path: Path | None, carpeta: Path) -> None:
    def progreso(hechos: int, total: int) -> None:
        _actualizar(trabajo_id, hechos=hechos, total=total)

    try:
        datos = procesar_zip(zip_path, carpeta / "trabajo", excel_path, progreso)
        resultado = carpeta / "resultado.zip"
        resultado.write_bytes(datos)
        _actualizar(trabajo_id, estado="listo", archivo=str(resultado))
    except zipfile.BadZipFile:
        _actualizar(trabajo_id, estado="error", error="El archivo no es un .zip válido.")
    except ExcelError as e:
        _actualizar(trabajo_id, estado="error", error=f"Listado de seriales: {e}.")
    except Exception as e:
        _actualizar(trabajo_id, estado="error", error=f"Error inesperado: {type(e).__name__}: {e}")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return "ok"


@app.post("/procesar")
def procesar():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename or not archivo.filename.lower().endswith(".zip"):
        return jsonify(error="Sube un archivo .zip con los PDFs."), 400

    excel = request.files.get("excel")
    tiene_excel = excel is not None and bool(excel.filename)
    if tiene_excel and not excel.filename.lower().endswith(".xlsx"):
        return jsonify(error="El listado de seriales debe ser un .xlsx."), 400

    carpeta = Path(tempfile.mkdtemp(prefix="lector-"))
    zip_path = carpeta / "entrada.zip"
    archivo.save(zip_path)
    excel_path = None
    if tiene_excel:
        excel_path = carpeta / "listado.xlsx"
        excel.save(excel_path)
        try:
            leer_seriales_excel(excel_path)  # validación rápida antes de procesar
        except ExcelError as e:
            return jsonify(error=f"Listado de seriales: {e}."), 400

    trabajo_id = uuid.uuid4().hex
    with CANDADO:
        TRABAJOS[trabajo_id] = {"estado": "procesando", "hechos": 0, "total": 0}
    threading.Thread(
        target=_ejecutar, args=(trabajo_id, zip_path, excel_path, carpeta), daemon=True
    ).start()
    return jsonify(id=trabajo_id), 202


@app.get("/estado/<trabajo_id>")
def estado(trabajo_id: str):
    with CANDADO:
        trabajo = TRABAJOS.get(trabajo_id)
        if trabajo is None:
            abort(404)
        return jsonify({k: v for k, v in trabajo.items() if k != "archivo"})


@app.get("/descargar/<trabajo_id>")
def descargar(trabajo_id: str):
    with CANDADO:
        trabajo = TRABAJOS.get(trabajo_id)
    if trabajo is None or trabajo.get("estado") != "listo":
        abort(404)
    return send_file(
        trabajo["archivo"],
        mimetype="application/zip",
        as_attachment=True,
        download_name="resultado_contadores.zip",
    )


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
