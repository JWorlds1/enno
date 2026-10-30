"""F02 Die API läuft über den Speicher-Port — mit memory:// ohne Postgres vollständig startbar."""
from tests.abnahme._client import call


def test_health():
    r = call("GET", "/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_status_meldet_speicher_backend():
    r = call("GET", "/api/v1/status")
    assert r.status_code == 200, r.text
    assert r.json()["db"] == "memory"


def test_anlagendaten_roundtrip():
    assert call("PUT", "/api/v1/plant-config", json={"params": {}}).status_code == 200
    r = call("PUT", "/api/v1/plant-config", json={"params": {"eta_el": 0.36, "start_cost_eur": 120}})
    assert r.status_code == 200, r.text
    got = call("GET", "/api/v1/plant-config").json()
    assert got["override"] == {"eta_el": 0.36, "start_cost_eur": 120}
    assert call("PUT", "/api/v1/plant-config", json={"params": {}}).status_code == 200
    assert call("GET", "/api/v1/plant-config").json()["override"] == {}


def test_whatif_ohne_preisbasis_ist_404():
    r = call("POST", "/api/v1/whatif", json={"algo": "whatif"})
    assert r.status_code == 404, r.text
