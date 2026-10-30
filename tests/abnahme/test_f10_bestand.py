"""F10 Nichts Bestehendes bricht: alle Bestands-Tests, die vor dem Lauf ohne Postgres grün waren, sind es noch.
Gemessen mit unerreichbarer Postgres-URL — genauso wird hier geprüft."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bestand_gruen():
    ids = [l.strip() for l in (Path(__file__).parent / "bestand.txt").read_text().splitlines() if l.strip()]
    assert len(ids) == 37
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:warnings", *ids],
                         cwd=ROOT, env={**os.environ, "FLD_DATABASE_URL": "postgresql+asyncpg://niemand@127.0.0.1:1/keine"}, capture_output=True, text=True, timeout=1500)
    assert out.returncode == 0, out.stdout[-4000:]
