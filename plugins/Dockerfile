FROM python:3.12-slim

WORKDIR /app

# System deps for lxml, psycopg, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# When built from repo root (Railway), files are under plugins/
COPY plugins/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY plugins/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
