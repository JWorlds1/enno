"""G05 (Review M6) Der OpenAPI-Vertrag beschreibt die Fehler so, wie sie kommen: problem+json, /ready mit 503."""
from tests.abnahme._client import app, call


def _antworten(pfad, methode):
    return app.openapi()["paths"][pfad][methode]["responses"]


def test_422_ist_problem_json():
    r = _antworten("/api/v1/whatif", "post")
    assert "422" in r, list(r)
    assert list(r["422"]["content"]) == ["application/problem+json"], r["422"]
    assert call("POST", "/api/v1/whatif", json={"gas": "abc"}).headers["content-type"].startswith("application/problem+json")


def test_ready_dokumentiert_503():
    r = _antworten("/api/v1/ready", "get")
    assert "503" in r and "application/problem+json" in r["503"].get("content", {}), r
