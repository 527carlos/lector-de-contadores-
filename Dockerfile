FROM python:3.12-slim

# Tesseract (con español) para OCR y poppler para convertir PDF a imágenes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 600 app:app"]
