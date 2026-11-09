"""OCR de PDFs escaneados usando poppler (pdftoppm) y Tesseract (español)."""

import csv
import io
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

DPI = 300  # 600 dpi no mejoró los seriales y multiplica el tiempo de proceso
IDIOMA = "spa"


@dataclass
class ResultadoOcr:
    texto: str
    palabras: list[tuple[str, float]]  # (texto, confianza 0-100)
    primera_pagina: Path


def _paginas(directorio: Path) -> list[Path]:
    def numero(p: Path) -> int:
        m = re.search(r"(\d+)\.png$", p.name)
        return int(m.group(1)) if m else 0

    return sorted(directorio.glob("pag*.png"), key=numero)


def _tsv_a_lineas(salida_tsv: str) -> tuple[str, list[tuple[str, float]]]:
    """Reconstruye las líneas de texto y la confianza por palabra desde el TSV de Tesseract."""
    lineas: dict[tuple, list[str]] = {}
    palabras: list[tuple[str, float]] = []
    lector = csv.DictReader(io.StringIO(salida_tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for fila in lector:
        texto = (fila.get("text") or "").strip()
        try:
            conf = float(fila.get("conf") or -1)
        except ValueError:
            conf = -1
        if not texto or conf < 0:
            continue
        clave = (fila["page_num"], fila["block_num"], fila["par_num"], fila["line_num"])
        lineas.setdefault(clave, []).append(texto)
        palabras.append((texto, conf))
    texto = "\n".join(" ".join(v) for v in lineas.values())
    return texto, palabras


def _ocr_imagen(imagen: Path) -> tuple[str, list[tuple[str, float]]]:
    salida = subprocess.run(
        ["tesseract", str(imagen), "stdout", "-l", IDIOMA, "--psm", "4", "tsv"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return _tsv_a_lineas(salida)


def ocr_pdf(pdf: Path, directorio: Path) -> ResultadoOcr:
    """Rasteriza todas las páginas del PDF y devuelve el texto OCR combinado."""
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-png", str(pdf), str(directorio / "pag")],
        capture_output=True,
        check=True,
    )
    paginas = _paginas(directorio)
    if not paginas:
        raise RuntimeError("el PDF no contiene páginas legibles")

    textos: list[str] = []
    palabras: list[tuple[str, float]] = []
    for pagina in paginas:
        texto, pal = _ocr_imagen(pagina)
        textos.append(texto)
        palabras.extend(pal)
    return ResultadoOcr("\n".join(textos), palabras, paginas[0])


def ocr_nota(imagen: Path, recorte: tuple[float, float, float, float], directorio: Path) -> str:
    """OCR de la nota manuscrita recortando una zona relativa de la página (mejor esfuerzo)."""
    a, b, c, d = recorte
    im = Image.open(imagen).convert("L")
    w, h = im.size
    zona = im.crop((int(w * a), int(h * b), int(w * c), int(h * d)))
    zona = zona.resize((zona.width * 2, zona.height * 2))
    zona = ImageOps.autocontrast(zona).point(lambda x: 255 if x > 150 else 0)
    ruta = directorio / "nota.png"
    zona.save(ruta)
    salida = subprocess.run(
        ["tesseract", str(ruta), "stdout", "-l", IDIOMA, "--psm", "7"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    limpio = re.sub(r"[^\w\s=.,:-]", " ", salida)
    return " ".join(limpio.split())
