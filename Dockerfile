FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install CA certs for outbound TLS (Supabase), and minimal diagnostics
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Default port; Cloud hosts (Render) set PORT
ENV PORT=8000
EXPOSE 8000

# Honor $PORT at runtime. Render sets env vars at run stage (DATABASE_URL, etc.)
CMD ["sh", "-c", "uvicorn app.server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
