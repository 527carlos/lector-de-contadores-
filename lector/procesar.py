"""Flujo completo: ZIP con PDFs -> contadores.txt + errores.txt + PDFs renombrados por serial."""

import csv
import io
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

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


def procesar_zip(zip_path: Path, trabajo: Path) -> bytes:
    trabajo.mkdir(parents=True, exist_ok=True)
    errores: list[str] = []
    pdfs = extraer_pdfs(zip_path, trabajo / "entrada", errores)

    registros: list[Registro] = []
    for n, (nombre, ruta) in enumerate(pdfs):
        try:
            registros.append(procesar_pdf(ruta, nombre, trabajo / f"ocr_{n:05d}"))
        except LecturaError as e:
            errores.append(f"{nombre}: {e}")
        except subprocess.CalledProcessError as e:
            errores.append(f"{nombre}: falló el OCR o la conversión del PDF ({e.cmd[0]})")
        except Exception as e:  # un PDF dañado no debe detener el lote
            errores.append(f"{nombre}: error inesperado ({type(e).__name__}: {e})")

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

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(salida / "contadores.txt", "contadores.txt")
        zf.write(salida / "errores.txt", "errores.txt")
        for pdf in sorted((salida / "pdfs_renombrados").glob("*.pdf")):
            zf.write(pdf, f"pdfs_renombrados/{pdf.name}")
    return buffer.getvalue()
