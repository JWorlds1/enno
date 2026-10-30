"""F08 Der API-Vertrag ist ein versioniertes Artefakt: docs/openapi.json == app.openapi(), kein Pfad geht verloren."""
import json
from pathlib import Path

from tests.abnahme._client import app

ROOT = Path(__file__).resolve().parents[2]
PFADE_HEUTE = {
    "/api/v1/health", "/api/v1/status", "/api/v1/recommendation", "/api/v1/decision", "/api/v1/forecast",
    "/api/v1/backtest", "/api/v1/market", "/api/v1/regelenergie", "/api/v1/whatif", "/api/v1/figures",
    "/api/v1/figures/{name}", "/api/v1/chat", "/api/v1/chat/{session_id}/history", "/api/v1/report",
    "/api/v1/price-heatmap", "/api/v1/eeg-budget", "/api/v1/cdr-sensitivity", "/api/v1/risk", "/api/v1/pareto",
    "/api/v1/revenue-stack", "/api/v1/plasma-compare", "/api/v1/forecast-band", "/api/v1/mpc",
    "/api/v1/sensitivity", "/api/v1/plant-config", "/api/v1/ready", "/api/v1/value-prices", "/api/v1/splitter", "/api/v1/splitter-plan", "/api/v1/splitter-year", "/api/v1/splitter-bids.csv", "/api/v1/value-curve", "/api/v1/splitter-proof",
}


def test_vertrag_ist_eingecheckt_und_aktuell():
    datei = ROOT / "docs" / "openapi.json"
    assert datei.is_file(), "docs/openapi.json fehlt"
    assert json.loads(datei.read_text()) == json.loads(json.dumps(app.openapi())), "Vertrag veraltet — neu erzeugen"


def test_kein_pfad_geht_verloren():
    fehlt = PFADE_HEUTE - set(app.openapi()["paths"])
    assert not fehlt, sorted(fehlt)
