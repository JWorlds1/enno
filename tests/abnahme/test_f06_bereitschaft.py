"""F06 Lebendigkeit vs. Bereitschaft: /health fragt nie die DB, /ready schon — und meldet 503, statt zu hängen."""
import os
import subprocess
import sys
import time

from tests.abnahme._client import call

SKRIPT = """
import asyncio, json, httpx
from fldos.api import app
async def go():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a") as c:
        r = await c.get("/api/v1/ready")
        print(json.dumps({"status": r.status_code, "ct": r.headers.get("content-type", "")}))
asyncio.run(go())
"""


def test_bereit_mit_speicher():
    r = call("GET", "/api/v1/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready", "db": "memory"}


def test_nicht_bereit_ohne_erreichbare_db_aber_lebendig():
    env = {**os.environ, "FLD_DATABASE_URL": "postgresql+asyncpg://niemand@127.0.0.1:1/keine", "FLD_WARMUP": "0"}
    t0 = time.monotonic()
    out = subprocess.run([sys.executable, "-c", SKRIPT], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    r = __import__("json").loads(out.stdout.strip().splitlines()[-1])
    assert r["status"] == 503 and r["ct"].startswith("application/problem+json"), r
    assert time.monotonic() - t0 < 30
