"""Unit-Tests der JWT-Verifikation (HS256) — flag-gated Auth für /fld-api."""
import jwt

from fldos import api


def test_valid_token_roundtrip(monkeypatch):
    secret = "test-secret-123"
    monkeypatch.setattr(api, "JWT_SECRET", secret)
    good = "Bearer " + jwt.encode({"sub": "u1", "tenant": "fld-energy"}, secret, algorithm="HS256")
    assert api._token_valid(good) is True


def test_invalid_tokens_rejected(monkeypatch):
    monkeypatch.setattr(api, "JWT_SECRET", "test-secret-123")
    assert api._token_valid(None) is False
    assert api._token_valid("Basic abc") is False
    assert api._token_valid("Bearer garbage.token.xxx") is False
    wrong = "Bearer " + jwt.encode({"sub": "u1"}, "other-secret", algorithm="HS256")
    assert api._token_valid(wrong) is False
