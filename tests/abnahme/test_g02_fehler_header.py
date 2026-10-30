"""G02 (Review M1) Das Fehlermodell behält die Header der Ausnahme, z. B. Allow bei 405 (RFC 9110 §15.5.6)."""
from tests.abnahme._client import assert_problem, call


def test_405_traegt_allow():
    r = call("POST", "/api/v1/health")
    assert_problem(r, 405)
    assert "GET" in r.headers.get("allow", ""), dict(r.headers)


def test_404_bleibt_problem_json():
    assert_problem(call("GET", "/api/v1/gibt-es-nicht"), 404)
