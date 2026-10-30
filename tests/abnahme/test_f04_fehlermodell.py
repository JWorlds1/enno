"""F04 Ein Fehlermodell für die ganze API: RFC 9457 (application/problem+json)."""
from tests.abnahme._client import assert_problem, call


def test_unbekannte_route():
    assert_problem(call("GET", "/api/v1/gibt-es-nicht"), 404)


def test_unbekannte_abbildung():
    assert_problem(call("GET", "/api/v1/figures/gibt-es-nicht"), 404)


def test_validierungsfehler_mit_fachlicher_meldung():
    body = assert_problem(call("PUT", "/api/v1/plant-config", json={"params": {"eta_el": 7}}), 422)
    assert "zwischen 0 und 1" in body["detail"]


def test_schemafehler_im_request():
    assert_problem(call("PUT", "/api/v1/plant-config", json={"falsch": 1}), 422)


def test_fachlicher_404():
    body = assert_problem(call("POST", "/api/v1/whatif", json={"algo": "whatif"}), 404)
    assert "Preisbasis" in body["detail"]  # deutsche Meldung (Review N-03), weiterhin fachlich statt generisch
