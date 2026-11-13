"""Flujo completo: ZIP con PDFs -> contadores.txt + errores.txt + PDFs renombrados por serial."""

import csv
import io
import os
import re
import shutil
import subprocess
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from .comparar import comparar, leer_seriales_excel
from .ocr import ocr_nota, ocr_pdf
from .parsers import NOTA_RECORTE, UMBRAL_CONFIANZA, LecturaError, leer


@dataclass
class Registro:
    archivo: str          # nombre original dentro del ZIP
    ruta: Path            # copia extraída del PDF
    modelo: str
    serial: str
    contador: int
    fecha: datetime | None
    confianza: float | None
    nota: str
    respaldo: bool = False


def extraer_pdfs(zip_path: Path, destino: Path, errores: list[str]) -> list[tuple[str, Path]]:
    """Extrae solo PDFs, evitando rutas peligrosas. Lo demás se reporta en errores."""
    destino.mkdir(parents=True, exist_ok=True)
    pdfs: list[tuple[str, Path]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for i, info in enumerate(zf.infolist()):
            if info.is_dir():
                continue
            ruta_zip = PurePosixPath(info.filename)
            if "__MACOSX" in ruta_zip.parts or ruta_zip.name.startswith("._"):
                continue
            if ruta_zip.is_absolute() or ".." in ruta_zip.parts:
                errores.append(f"{info.filename}: ruta sospechosa, ignorado")
                continue
            if ruta_zip.suffix.lower() != ".pdf":
                errores.append(f"{info.filename}: no es PDF, ignorado")
                continue
            ruta = destino / f"{i:05d}.pdf"
            with zf.open(info) as origen, open(ruta, "wb") as copia:
                shutil.copyfileobj(origen, copia)
            pdfs.append((ruta_zip.name, ruta))
    pdfs.sort(key=lambda par: par[0])
    return pdfs


def procesar_pdf(ruta: Path, nombre: str, directorio: Path) -> Registro:
    directorio.mkdir(parents=True, exist_ok=True)
    resultado = ocr_pdf(ruta, directorio)
    (directorio / "ocr.txt").write_text(resultado.texto, encoding="utf-8")  # para diagnóstico
    lectura = leer(resultado.texto, resultado.palabras)
    nota = ""
    recorte = NOTA_RECORTE.get(lectura.modelo)
    if recorte:
        nota = ocr_nota(resultado.primera_pagina, recorte, directorio)
    return Registro(
        archivo=nombre,
        ruta=ruta,
        modelo=lectura.modelo,
        serial=lectura.serial,
        contador=lectura.contador,
        fecha=lectura.fecha,
        confianza=lectura.confianza_serial,
        nota=nota,
        respaldo=lectura.respaldo,
    )


def deduplicar(registros: list[Registro]) -> tuple[list[Registro], list[tuple[Registro, Registro]]]:
    """Por serial conserva el registro con fecha más reciente.

    Devuelve (conservados, [(descartado, conservado), ...]).
    """
    grupos: dict[str, list[Registro]] = {}
    for r in registros:
        grupos.setdefault(r.serial, []).append(r)

    conservados: list[Registro] = []
    descartados: list[tuple[Registro, Registro]] = []
    for grupo in grupos.values():
        grupo.sort(key=lambda r: (r.fecha or datetime.min, r.archivo))
        ganador = grupo[-1]
        conservados.append(ganador)
        descartados.extend((r, ganador) for r in grupo[:-1])
    return conservados, descartados


def _texto_tsv(valor: str) -> str:
    return " ".join(str(valor).replace("\t", " ").split())


def _contadores_tsv(conservados: list[Registro]) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar="\\")
    escritor.writerow(["serial", "contador", "modelo", "archivo_original", "nota_manuscrita"])
    for r in sorted(conservados, key=lambda r: (r.modelo, r.serial)):
        escritor.writerow([r.serial, r.contador, r.modelo, _texto_tsv(r.archivo), _texto_tsv(r.nota)])
    # UTF-8 con BOM para que Excel en español muestre bien los acentos.
    return "﻿" + salida.getvalue()


def _procesar_seguro(tarea: tuple[Path, str, Path]):
    """Versión de procesar_pdf que nunca lanza excepciones (para ejecutar en otro proceso)."""
    ruta, nombre, directorio = tarea
    try:
        return procesar_pdf(ruta, nombre, directorio), None
    except LecturaError as e:
        return None, f"{nombre}: {e}"
    except subprocess.CalledProcessError as e:
        return None, f"{nombre}: falló el OCR o la conversión del PDF ({e.cmd[0]})"
    except Exception as e:  # un PDF dañado no debe detener el lote
        return None, f"{nombre}: error inesperado ({type(e).__name__}: {e})"


def procesar_zip(
    zip_path: Path,
    trabajo: Path,
    excel_path: Path | None = None,
    progreso: Optional[Callable[[int, int], None]] = None,
) -> bytes:
    trabajo.mkdir(parents=True, exist_ok=True)
    # Se valida el Excel antes del OCR para no esperar en vano si está mal.
    seriales_excel = leer_seriales_excel(excel_path) if excel_path else None
    errores: list[str] = []
    pdfs = extraer_pdfs(zip_path, trabajo / "entrada", errores)

    # Cada tesseract usa un hilo; con varios procesos en paralelo se evita saturar la CPU.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    tareas = [(ruta, nombre, trabajo / f"ocr_{n:05d}") for n, (nombre, ruta) in enumerate(pdfs)]
    diagnostico = trabajo / "diagnostico"
    diagnostico.mkdir(parents=True, exist_ok=True)
    registros: list[Registro] = []
    if progreso:
        progreso(0, len(tareas))
    if tareas:
        workers = max(1, min(len(tareas), os.cpu_count() or 1))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for hechos, (registro, error) in enumerate(pool.map(_procesar_seguro, tareas), start=1):
                if registro is not None:
                    registros.append(registro)
                else:
                    indice = hechos - 1
                    errores.append(error)
                    # Guarda el texto OCR para revisar por qué no se leyó el archivo.
                    origen = tareas[indice][2] / "ocr.txt"
                    if origen.exists():
                        shutil.copyfile(origen, diagnostico / f"{tareas[indice][1]}.txt")
                if progreso:
                    progreso(hechos, len(tareas))

    conservados, descartados = deduplicar(registros)
    for descartado, ganador in descartados:
        errores.append(
            f"{descartado.archivo}: serial {descartado.serial} duplicado; descartado "
            f"(se conservó {ganador.archivo}, fecha {ganador.fecha or 'desconocida'})"
        )
    for r in conservados:
        if r.confianza is None or r.confianza < UMBRAL_CONFIANZA:
            conf = "no verificable" if r.confianza is None else f"{r.confianza:.0f}%"
            errores.append(f"REVISAR {r.archivo}: serial {r.serial} con confianza OCR baja ({conf})")
        if re.search(r"[OI]", r.serial):
            errores.append(f"REVISAR {r.archivo}: serial {r.serial} contiene O o I; verificar si es 0 o 1")
        if r.respaldo:
            errores.append(f"REVISAR {r.archivo}: serial {r.serial} tomado por formato, no por etiqueta; verificar")
        if NOTA_RECORTE.get(r.modelo) and not r.nota:
            errores.append(f"REVISAR {r.archivo}: nota manuscrita no legible")

    salida = trabajo / "salida"
    (salida / "pdfs_renombrados").mkdir(parents=True, exist_ok=True)
    for r in conservados:
        shutil.copyfile(r.ruta, salida / "pdfs_renombrados" / f"{r.serial}.pdf")

    contadores = _contadores_tsv(conservados)
    texto_errores = "\n".join(errores) if errores else "Sin errores."
    (salida / "contadores.txt").write_text(contadores, encoding="utf-8")
    (salida / "errores.txt").write_text(texto_errores + "\n", encoding="utf-8")

    archivos = ["contadores.txt", "errores.txt"]
    if seriales_excel is not None:
        filas = comparar(seriales_excel, [r.serial for r in conservados])
        lineas = ["serial\testado\tdetalle"] + [f"{s}\t{e}\t{d}" for s, e, d in filas]
        (salida / "comparacion.txt").write_text("﻿" + "\n".join(lineas) + "\n", encoding="utf-8")
        archivos.append("comparacion.txt")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre in archivos:
            zf.write(salida / nombre, nombre)
        for txt in sorted(diagnostico.glob("*.txt")):
            zf.write(txt, f"diagnostico/{txt.name}")
        for pdf in sorted((salida / "pdfs_renombrados").glob("*.pdf")):
            zf.write(pdf, f"pdfs_renombrados/{pdf.name}")
    return buffer.getvalue()
