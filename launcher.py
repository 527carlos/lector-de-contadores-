"""Punto de entrada para el ejecutable de Windows.

Levanta el servidor en 127.0.0.1 y abre el navegador. Cerrar la ventana de consola detiene la app.
"""

import multiprocessing
import threading
import time
import webbrowser

from lector.rutas import configurar_entorno

configurar_entorno()

from app import app  # noqa: E402  (después de configurar el entorno)

PUERTO = 5000


def abrir_navegador() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PUERTO}")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # necesario para el procesamiento en paralelo en Windows
    print("Lector de contadores en ejecución.")
    print(f"Abre http://127.0.0.1:{PUERTO} si el navegador no se abre solo.")
    print("Para detener la app, cierra esta ventana.")
    threading.Thread(target=abrir_navegador, daemon=True).start()
    app.run(host="127.0.0.1", port=PUERTO, threaded=True, use_reloader=False, debug=False)
