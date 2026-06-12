FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema (timezonefinder / numpy / pvlib usan wheels precompilados,
# pero dejamos build-essential por si algún paquete necesita compilar)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces sirve la app en el puerto 7860
ENV PORT=7860
EXPOSE 7860

# gunicorn sirve el objeto WSGI expuesto en app.py (server = app.server)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120", "app:server"]
