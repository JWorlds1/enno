#!/usr/bin/env bash
# FLD OS Backend lokal starten (Homebrew-Postgres 14 + pgvector).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/usr/local/opt/postgresql@14/bin:$PATH"
export FLD_DATABASE_URL="${FLD_DATABASE_URL:-postgresql+asyncpg://qed97@localhost:5432/fld_os}"
export PYTHONPATH=.:engine
exec .venv/bin/uvicorn fldos.api:app --host 127.0.0.1 --port "${FLD_PORT:-8031}"
