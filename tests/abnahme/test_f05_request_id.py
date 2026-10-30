"""F05 Nachverfolgbarkeit: jede Antwort trägt X-Request-ID; eine mitgeschickte ID wird übernommen."""
from tests.abnahme._client import call


def test_antwort_hat_request_id():
    a = call("GET", "/api/v1/health").headers.get("x-request-id", "")
    b = call("GET", "/api/v1/health").headers.get("x-request-id", "")
    assert len(a) >= 8 and len(b) >= 8 and a != b


def test_mitgeschickte_id_wird_uebernommen():
    r = call("GET", "/api/v1/health", headers={"X-Request-ID": "abnahme-1234"})
    assert r.headers.get("x-request-id") == "abnahme-1234"


def test_auch_fehlerantworten_tragen_die_id():
    r = call("GET", "/api/v1/gibt-es-nicht", headers={"X-Request-ID": "abnahme-404"})
    assert r.status_code == 404 and r.headers.get("x-request-id") == "abnahme-404"
