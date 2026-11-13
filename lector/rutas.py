"""Rutas de recursos y binarios, tanto en desarrollo como empaquetado con PyInstaller."""

import os
import sys
from pathlib import Path


def directorio_base() -> Path:
    """Carpeta raíz de la app. Dentro del ejecutable apunta a la carpeta de recursos empaquetados."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def configurar_entorno() -> None:
    """Si hay Tesseract y poppler empaquetados, los agrega al PATH.

    En desarrollo no hace nada: se usan los que estén instalados en el sistema.
    """
    base = directorio_base()
    tesseract = base / "tesseract"
    poppler = base / "poppler" / "bin"

    carpetas = [str(c) for c in (tesseract, poppler) if c.is_dir()]
    if carpetas:
        os.environ["PATH"] = os.pathsep.join(carpetas + [os.environ.get("PATH", "")])
    if (tesseract / "tessdata").is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tesseract / "tessdata")
