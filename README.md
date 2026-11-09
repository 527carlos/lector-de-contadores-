# Lector de contadores

Aplicación web que recibe un `.zip` con PDFs de reportes de impresoras (escaneados) y devuelve:

- `contadores.txt`: tabla separada por tabulaciones con `serial`, `contador`, `modelo`, `archivo_original` y `nota_manuscrita`.
- `errores.txt`: archivos no procesados, duplicados descartados y registros a revisar.
- `pdfs_renombrados/`: cada PDF copiado como `SERIAL.pdf`.
- `comparacion.txt` (opcional): si se sube un listado de seriales en `.xlsx`, compara ese listado con los seriales de los PDF. Estados: `coincide`, `posible coincidencia` (difieren solo en O/0 o I/1, típico del OCR), `solo en Excel (sin PDF)` y `solo en PDF (no está en Excel)`.

El listado de seriales se toma de la primera hoja: la columna titulada "Serial", "Serie" o "Número de serie"; si no hay encabezado reconocible, la primera columna (omitiendo la primera fila).

## Modelos soportados

| Modelo | Serial | Contador |
|---|---|---|
| Lexmark MX511de | Número de serie (sección Impresora) | Total cómputo caras impresas (Total > Mono) |
| HP LaserJet MFP E52645 | Número de serie del producto | Ciclos del motor |
| OKI ES5112 | Número de serie Impresora | Total mono (Impres.Total) |
| Ricoh SP 4510DN | ID máquina | Contador total |

Reglas:

- Si un serial aparece en varios PDFs se conserva el de fecha de impresión más reciente; los demás van a `errores.txt`.
- Si el OCR no está seguro del serial (confianza < 80%) o no leyó la nota manuscrita, el registro aparece con `REVISAR` en `errores.txt`.

## Ejecutar en local

Requiere Tesseract (con idioma español) y poppler:

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-spa poppler-utils

pip install -r requirements-dev.txt
python app.py          # http://localhost:5000
pytest                 # pruebas de los parsers
```

## Despliegue en Render

El repositorio incluye `Dockerfile` y `render.yaml`. En Render: *New → Blueprint* (o *New → Web Service* con runtime Docker) apuntando a este repositorio. El health check es `/healthz`.

## Limitaciones

- La nota manuscrita se lee con Tesseract, que reconoce la letra a mano solo parcialmente. Revisa esa columna.
- Las zonas de recorte de la nota están calibradas con los 4 ejemplos (`lector/parsers.py`, `NOTA_RECORTE`).
