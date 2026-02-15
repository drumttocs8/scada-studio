FROM python:3.12-slim

WORKDIR /app

# System deps for lxml, psycopg, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# When built from repo root (Railway), files are under plugins/
COPY plugins/requirements.txt .

# Install CPU-only PyTorch first (avoids ~4GB of CUDA libs)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY plugins/ .

# Railway injects PORT dynamically; default to 8000 for local dev
ENV PORT=8000
EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
