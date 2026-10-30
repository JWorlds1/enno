"""Verfassung §9: Enno-Verläufe sind mandantengetrennt — auch wenn sich zwei Deployments eine DB teilen.

Mandant B kennt (rät) die Sitzungs-ID von A: er darf den Verlauf nicht lesen und nicht hineinschreiben.
"""
import asyncio

from sqlalchemy import delete

from fldos import models as M
from fldos.db import get_engine
from fldos.storage import MemoryRepository, PostgresRepository


async def _probe(a, b) -> tuple[int, list, int, list]:
    cs = await a.get_or_create_chat_session(None)
    await a.save_chat_message(cs.id, "user", "geheim von A")
    seen_by_b = [m.content for m in await b.chat_history(cs.id)]
    b_cs = await b.get_or_create_chat_session(cs.id)  # B schickt A's ID mit
    await b.save_chat_message(b_cs.id, "user", "von B")
    seen_by_a = [m.content for m in await a.chat_history(cs.id)]
    return cs.id, seen_by_b, b_cs.id, seen_by_a


def _check(_sid, seen_by_b, _b_sid, seen_by_a):
    assert seen_by_b == []
    assert seen_by_a == ["geheim von A"]  # B's Nachricht landet nie in A's Sitzung


def test_memory_repository_isolates_chat():
    _check(*asyncio.run(_probe(MemoryRepository("mandant-a"), MemoryRepository("mandant-b"))))


def test_postgres_repository_isolates_chat():
    tenants = ("pytest-mandant-a", "pytest-mandant-b")

    async def go():
        try:
            return await _probe(PostgresRepository(tenant_id=tenants[0]), PostgresRepository(tenant_id=tenants[1]))
        finally:
            async with get_engine().begin() as c:
                for t in (M.ChatMessage, M.ChatSession):
                    await c.execute(delete(t).where(t.tenant_id.in_(tenants)))
            await get_engine().dispose()

    _check(*asyncio.run(go()))
