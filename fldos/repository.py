"""Repository-Layer: typisierte DB-Zugriffe zwischen Engine und API.

Die reine Rechen-Engine (backtest_forecast, whatif, …) kennt keine DB — sie bekommt/liefert
Python-Arrays. Hier werden Ergebnisse persistiert und für die API gelesen.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import models as M


# ── Reads (API) ──────────────────────────────────────────────────────────────
async def latest_run(session: AsyncSession, algo: str | None = None, *, tenant: str) -> M.Run | None:
    q = select(M.Run).where(M.Run.tenant_id == tenant).order_by(M.Run.created_at.desc())
    if algo:
        q = q.where(M.Run.algo == algo)
    return (await session.execute(q.limit(1))).scalar_one_or_none()


async def dispatch_for_run(session: AsyncSession, run_id: int, *, tenant: str) -> list[M.Dispatch]:
    q = select(M.Dispatch).where(M.Dispatch.tenant_id == tenant, M.Dispatch.run_id == run_id).order_by(M.Dispatch.slot)
    return list((await session.execute(q)).scalars())


async def forecasts_for_run(session: AsyncSession, run_id: int, *, tenant: str) -> list[M.Forecast]:
    q = select(M.Forecast).where(M.Forecast.tenant_id == tenant, M.Forecast.run_id == run_id).order_by(M.Forecast.ts)
    return list((await session.execute(q)).scalars())


async def decision_for_run(session: AsyncSession, run_id: int, *, tenant: str) -> M.Decision | None:
    q = select(M.Decision).where(M.Decision.tenant_id == tenant, M.Decision.run_id == run_id).order_by(M.Decision.id.desc())
    return (await session.execute(q.limit(1))).scalar_one_or_none()


async def backtest(session: AsyncSession, algo: str | None = None, *, tenant: str) -> list[M.BacktestResult]:
    q = select(M.BacktestResult).where(M.BacktestResult.tenant_id == tenant).order_by(M.BacktestResult.day)
    if algo:
        q = q.where(M.BacktestResult.algo == algo)
    return list((await session.execute(q)).scalars())


async def fundamentals(session: AsyncSession, limit: int = 400, *, tenant: str) -> list[M.MarketFundamental]:
    q = (
        select(M.MarketFundamental)
        .where(M.MarketFundamental.tenant_id == tenant)
        .order_by(M.MarketFundamental.day.desc())
        .limit(limit)
    )
    return list((await session.execute(q)).scalars())


async def regelenergie(session: AsyncSession, *, tenant: str) -> list[M.RegelenergiePrice]:
    q = select(M.RegelenergiePrice).where(M.RegelenergiePrice.tenant_id == tenant).order_by(
        M.RegelenergiePrice.day
    )
    return list((await session.execute(q)).scalars())


# ── Writes (Pipeline / Adapter) ──────────────────────────────────────────────
async def save_run(
    session: AsyncSession,
    target_day: date,
    algo: str,
    kpis: dict,
    dispatch_rows: list[dict],
    forecast_rows: list[dict] | None = None,
    decision: dict | None = None,
    *,
    tenant: str,
) -> M.Run:
    """Ein kompletter Lauf: Run + Dispatch (+ optional Forecasts + Decision) in einer Transaktion."""
    run = M.Run(tenant_id=tenant, target_day=target_day, algo=algo, status="ok", kpis=kpis)
    session.add(run)
    await session.flush()  # run.id
    session.add_all([M.Dispatch(tenant_id=tenant, run_id=run.id, **r) for r in dispatch_rows])
    if forecast_rows:
        session.add_all([M.Forecast(tenant_id=tenant, run_id=run.id, **r) for r in forecast_rows])
    if decision:
        session.add(M.Decision(tenant_id=tenant, run_id=run.id, **decision))
    await session.commit()
    return run


async def save_whatif(session: AsyncSession, params: dict, result: dict, *, tenant: str) -> None:
    session.add(M.WhatifRun(tenant_id=tenant, params=params, result=result))
    await session.commit()


async def prices_latest(session: AsyncSession, *, tenant: str) -> list[float]:
    """Preisvektor des jüngsten Laufs (96 Slots, an Umstellungstagen 92/100) — Basis für /whatif."""
    run = await latest_run(session, tenant=tenant)
    if not run:
        return []
    rows = await dispatch_for_run(session, run.id, tenant=tenant)
    return [r.pred_price or 0.0 for r in rows]


async def upsert_prices(session: AsyncSession, rows: list[dict], *, tenant: str) -> int:
    """rows: [{ts, price_eur_mwh, source}]. Idempotent per (tenant_id, ts, source)."""
    if not rows:
        return 0
    stmt = pg_insert(M.MarketPrice).values([{**r, "tenant_id": tenant} for r in rows])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_prices", set_={"price_eur_mwh": stmt.excluded.price_eur_mwh}
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def upsert_fundamentals(session: AsyncSession, rows: list[dict], *, tenant: str) -> int:
    if not rows:
        return 0
    stmt = pg_insert(M.MarketFundamental).values([{**r, "tenant_id": tenant} for r in rows])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_fundamentals",
        set_={"ttf_gas_eur_mwh": stmt.excluded.ttf_gas_eur_mwh, "eua_co2_eur_t": stmt.excluded.eua_co2_eur_t},
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def upsert_regelenergie(session: AsyncSession, rows: list[dict], *, tenant: str) -> int:
    if not rows:
        return 0
    stmt = pg_insert(M.RegelenergiePrice).values([{**r, "tenant_id": tenant} for r in rows])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_regelenergie", set_={"price_eur_mw_h": stmt.excluded.price_eur_mw_h}
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


# ── Plant-Config ─────────────────────────────────────────────────────────────
# ── Enno-Chat-Persistenz ─────────────────────────────────────────────────────
async def get_or_create_chat_session(
    session: AsyncSession, session_id: int | None = None, agent_id: str = "enno", *, tenant: str
) -> M.ChatSession:
    if session_id:
        cs = await session.get(M.ChatSession, session_id)
        if cs and cs.tenant_id == tenant:  # fremde ID → eigene neue Sitzung, nie die fremde
            return cs
    cs = M.ChatSession(tenant_id=tenant, agent_id=agent_id)
    session.add(cs)
    await session.flush()  # cs.id
    return cs


async def save_chat_message(
    session: AsyncSession, session_id: int, role: str, content: str, tool_calls: list | None = None, *, tenant: str
) -> None:
    session.add(M.ChatMessage(
        tenant_id=tenant, session_id=session_id, role=role, content=content,
        tool_calls={"calls": tool_calls} if tool_calls else None,
    ))


async def chat_history(session: AsyncSession, session_id: int, *, tenant: str) -> list[M.ChatMessage]:
    q = select(M.ChatMessage).where(M.ChatMessage.tenant_id == tenant, M.ChatMessage.session_id == session_id).order_by(M.ChatMessage.id)
    return list((await session.execute(q)).scalars())


async def get_plant_config(session: AsyncSession, *, tenant: str) -> dict | None:
    row = await session.get(M.PlantConfigRow, tenant)
    return row.params if row else None


async def set_plant_config(session: AsyncSession, params: dict, *, tenant: str) -> None:
    stmt = pg_insert(M.PlantConfigRow).values(tenant_id=tenant, params=params)
    stmt = stmt.on_conflict_do_update(index_elements=["tenant_id"], set_={"params": params})
    await session.execute(stmt)
    await session.commit()


# ── Schattenbetrieb ──────────────────────────────────────────────────────────
async def upsert_measurements(session: AsyncSession, rows: list[dict], *, tenant: str) -> int:
    """rows: [{ts, p_mw}] — gemessene Einspeisung; idempotent je (tenant_id, ts)."""
    if not rows:
        return 0
    stmt = pg_insert(M.PlantMeasurement).values([{**r, "tenant_id": tenant} for r in rows])
    stmt = stmt.on_conflict_do_update(constraint="uq_plant_measurements", set_={"p_mw": stmt.excluded.p_mw})
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def measurements(session: AsyncSession, start: datetime, end: datetime, *, tenant: str) -> list[M.PlantMeasurement]:
    q = (select(M.PlantMeasurement)
         .where(M.PlantMeasurement.tenant_id == tenant, M.PlantMeasurement.ts >= start, M.PlantMeasurement.ts < end)
         .order_by(M.PlantMeasurement.ts))
    return list((await session.execute(q)).scalars())


async def runs_since(session: AsyncSession, since: date, *, tenant: str) -> list[M.Run]:
    """Alle Läufe ab Liefertag `since` (Historie der Empfehlungen), älteste zuerst."""
    q = (select(M.Run).where(M.Run.tenant_id == tenant, M.Run.target_day >= since)
         .order_by(M.Run.target_day, M.Run.created_at))
    return list((await session.execute(q)).scalars())


async def memory_count(session: AsyncSession, *, tenant: str) -> int:
    return int((await session.execute(
        select(func.count()).select_from(M.AgentMemory).where(M.AgentMemory.tenant_id == tenant)
    )).scalar_one())
