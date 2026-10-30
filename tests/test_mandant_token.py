"""Mandant pro Anfrage (Verfassung §9): mit Anmeldung entscheidet allein der Claim `tenant` im Token.

Zwei Mandanten in EINER Instanz und EINER DB: Anlagendaten und Enno-Verläufe von A sind für B unsichtbar.
"""
import asyncio

import jwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from fldos import api
from fldos import models as M
from fldos.db import get_engine

SECRET = "test-secret-mandant"
A, B = "pytest-mandant-a", "pytest-mandant-b"


def auth(tenant: str | None) -> dict:
    claims = {"sub": "u1"} if tenant is None else {"sub": "u1", "tenant": tenant}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


def two_tenants(monkeypatch):
    monkeypatch.setattr(api, "REQUIRE_AUTH", True)
    monkeypatch.setattr(api, "JWT_SECRET", SECRET)
    monkeypatch.setattr(api, "TENANTS", frozenset({A, B}))


def run(go):
    async def wrapped():
        try:
            async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as c:
                return await go(c)
        finally:
            async with get_engine().begin() as conn:
                for t in (M.ChatMessage, M.ChatSession, M.PlantConfigRow):
                    await conn.execute(delete(t).where(t.tenant_id.in_((A, B))))
            await get_engine().dispose()
    return asyncio.run(wrapped())


def test_token_decides_tenant(monkeypatch):
    two_tenants(monkeypatch)

    async def go(c):
        assert (await c.get("/api/v1/plant-config")).status_code == 401
        assert (await c.get("/api/v1/plant-config", headers=auth(None))).status_code == 403
        assert (await c.get("/api/v1/plant-config", headers=auth("fremd"))).status_code == 403
        assert (await c.get("/api/v1/plant-config", headers=auth(A))).status_code == 200
        assert (await c.get("/api/v1/ready")).status_code == 200  # Bereitschaft braucht keinen Mandanten
    run(go)


def test_plant_config_and_chat_isolated_per_request(monkeypatch):
    two_tenants(monkeypatch)

    async def go(c):
        r = await c.put("/api/v1/plant-config", json={"params": {"start_cost_eur": 99}}, headers=auth(A))
        assert r.status_code == 200, r.text
        assert (await c.get("/api/v1/plant-config", headers=auth(A))).json()["override"] == {"start_cost_eur": 99}
        assert (await c.get("/api/v1/plant-config", headers=auth(B))).json()["override"] == {}

        sid = (await c.post("/api/v1/chat", json={"message": "geheim von A", "history": []}, headers=auth(A))).json()["session_id"]
        assert (await c.get(f"/api/v1/chat/{sid}/history", headers=auth(B))).json() == []
        b = (await c.post("/api/v1/chat", json={"message": "von B", "history": [], "session_id": sid}, headers=auth(B))).json()
        assert b["session_id"] != sid
        hist = (await c.get(f"/api/v1/chat/{sid}/history", headers=auth(A))).json()
        assert [h["content"] for h in hist if h["role"] == "user"] == ["geheim von A"]
    run(go)
