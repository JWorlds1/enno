FROM python:3.12-slim
WORKDIR /app
# libgomp1: vom CBC-Solver (PuLP) benötigt
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY engine ./engine
COPY fldos ./fldos
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:/app/engine FLD_DATA_DIR=/data
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn fldos.api:app --host 0.0.0.0 --port 8000"]
