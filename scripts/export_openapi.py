"""Schreibt den API-Vertrag nach docs/openapi.json (app.openapi(), ohne Postgres).

Aufruf aus dem Repo-Root: PYTHONPATH=.:engine .venv/bin/python scripts/export_openapi.py
"""
import json
import os
from pathlib import Path

os.environ["FLD_DATABASE_URL"] = "memory://"
os.environ["FLD_WARMUP"] = "0"

from fldos.api import app  # noqa: E402

ZIEL = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
ZIEL.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
print(f"geschrieben: {ZIEL}")
