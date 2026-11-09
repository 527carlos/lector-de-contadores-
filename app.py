import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from flask import Flask, render_template, request, send_file

from lector.procesar import procesar_zip

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB


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
        return render_template("index.html", error="Sube un archivo .zip con los PDFs."), 400

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "entrada.zip"
        archivo.save(zip_path)
        try:
            datos = procesar_zip(zip_path, Path(tmp) / "trabajo")
        except zipfile.BadZipFile:
            return render_template("index.html", error="El archivo no es un .zip válido."), 400

    return send_file(
        BytesIO(datos),
        mimetype="application/zip",
        as_attachment=True,
        download_name="resultado_contadores.zip",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
