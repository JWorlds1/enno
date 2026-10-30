"""Speicher-Port: Persistenz hinter einer Naht mit zwei Adaptern.

PostgresRepository delegiert an die Funktionen in repository.py und verwaltet die Session selbst;
MemoryRepository hält alles im Prozess (Tests, Betrieb ohne Postgres). Beide bieten dieselben
async-Methoden wie repository.py, nur ohne session-Parameter. Erzeugen verbindet nie.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from . import memory
from . import models as M
from . import repository as R
from . import settings
from sqlalchemy import text

from .db import get_sessionmaker


class PostgresRepository:
    kind = "postgres"  # Anzeige in /ready
    db_status = "ok"  # Anzeige in /status

    def __init__(self, url: str | None = None, tenant_id: str | None = None) -> None:
        self._url = url or settings.DATABASE_URL
        self.tenant_id = tenant_id or settings.TENANT_ID

    async def _call(self, fn, *args, **kw):
        async with get_sessionmaker(self._url)() as session:  # Engine entsteht erst hier, geteilt mit fldos.db
            out = await fn(session, *args, tenant=self.tenant_id, **kw)  # §9: jeder Zugriff trägt den Mandanten
            await session.commit()  # repository.py committet nicht überall (Chat-Funktionen)
            return out

    async def latest_run(self, algo: str | None = None) -> M.Run | None:
        return await self._call(R.latest_run, algo)

    async def dispatch_for_run(self, run_id: int) -> list[M.Dispatch]:
        return await self._call(R.dispatch_for_run, run_id)

    async def forecasts_for_run(self, run_id: int) -> list[M.Forecast]:
        return await self._call(R.forecasts_for_run, run_id)

    async def decision_for_run(self, run_id: int) -> M.Decision | None:
        return await self._call(R.decision_for_run, run_id)

    async def backtest(self, algo: str | None = None) -> list[M.BacktestResult]:
        return await self._call(R.backtest, algo)

    async def fundamentals(self, limit: int = 400) -> list[M.MarketFundamental]:
        return await self._call(R.fundamentals, limit)

    async def regelenergie(self) -> list[M.RegelenergiePrice]:
        return await self._call(R.regelenergie)

    async def save_run(
        self,
        target_day: date,
        algo: str,
        kpis: dict,
        dispatch_rows: list[dict],
        forecast_rows: list[dict] | None = None,
        decision: dict | None = None,
    ) -> M.Run:
        return await self._call(R.save_run, target_day, algo, kpis, dispatch_rows, forecast_rows, decision)

    async def save_whatif(self, params: dict, result: dict) -> None:
        await self._call(R.save_whatif, params, result)

    async def prices_latest(self) -> list[float]:
        return await self._call(R.prices_latest)

    async def upsert_prices(self, rows: list[dict]) -> int:
        return await self._call(R.upsert_prices, rows)

    async def upsert_fundamentals(self, rows: list[dict]) -> int:
        return await self._call(R.upsert_fundamentals, rows)

    async def upsert_regelenergie(self, rows: list[dict]) -> int:
        return await self._call(R.upsert_regelenergie, rows)

    async def get_or_create_chat_session(self, session_id: int | None = None, agent_id: str = "enno") -> M.ChatSession:
        return await self._call(R.get_or_create_chat_session, session_id, agent_id)

    async def save_chat_message(
        self, session_id: int, role: str, content: str, tool_calls: list | None = None
    ) -> None:
        await self._call(R.save_chat_message, session_id, role, content, tool_calls)

    async def chat_history(self, session_id: int) -> list[M.ChatMessage]:
        return await self._call(R.chat_history, session_id)

    async def get_plant_config(self) -> dict | None:
        return await self._call(R.get_plant_config)

    async def set_plant_config(self, params: dict) -> None:
        await self._call(R.set_plant_config, params)

    async def upsert_measurements(self, rows: list[dict]) -> int:
        return await self._call(R.upsert_measurements, rows)

    async def measurements(self, start: datetime, end: datetime) -> list[M.PlantMeasurement]:
        return await self._call(R.measurements, start, end)

    async def runs_since(self, since: date) -> list[M.Run]:
        return await self._call(R.runs_since, since)

    async def ping(self) -> None:
        async def select_1(session, *, tenant):
            await session.execute(text("SELECT 1"))
        await self._call(select_1)

    async def memory_count(self) -> int:
        return await self._call(R.memory_count)

    async def search_memory(self, query: str, k: int = 4) -> list[M.AgentMemory]:
        return await self._call(memory.search, query, k)


class MemoryRepository:
    """Eine Instanz = ein Mandant: jede Zeile trägt tenant_id, fremde Instanzen sehen nichts."""

    kind = "memory"
    db_status = "memory"  # Anzeige in /status

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id or settings.TENANT_ID
        self._ids = count(1)
        self._runs: list[M.Run] = []
        self._dispatch: list[M.Dispatch] = []
        self._forecasts: list[M.Forecast] = []
        self._decisions: list[M.Decision] = []
        self._whatifs: list[M.WhatifRun] = []
        self._backtest: list[M.BacktestResult] = []
        self._fundamentals: dict[date, M.MarketFundamental] = {}
        self._regelenergie: dict[tuple[date, str], M.RegelenergiePrice] = {}
        self._prices: dict[tuple[datetime, str], M.MarketPrice] = {}
        self._chat_sessions: dict[int, M.ChatSession] = {}
        self._chat_messages: list[M.ChatMessage] = []
        self._plant_config: dict | None = None
        self._measurements: dict[datetime, M.PlantMeasurement] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def latest_run(self, algo: str | None = None) -> M.Run | None:
        return next((r for r in reversed(self._runs) if algo is None or r.algo == algo), None)

    async def dispatch_for_run(self, run_id: int) -> list[M.Dispatch]:
        return sorted((d for d in self._dispatch if d.run_id == run_id), key=lambda d: d.slot)

    async def forecasts_for_run(self, run_id: int) -> list[M.Forecast]:
        return sorted((f for f in self._forecasts if f.run_id == run_id), key=lambda f: f.ts)

    async def decision_for_run(self, run_id: int) -> M.Decision | None:
        return next((d for d in reversed(self._decisions) if d.run_id == run_id), None)

    async def backtest(self, algo: str | None = None) -> list[M.BacktestResult]:
        return sorted((b for b in self._backtest if algo is None or b.algo == algo), key=lambda b: b.day)

    async def fundamentals(self, limit: int = 400) -> list[M.MarketFundamental]:
        return sorted(self._fundamentals.values(), key=lambda f: f.day, reverse=True)[:limit]

    async def regelenergie(self) -> list[M.RegelenergiePrice]:
        return sorted(self._regelenergie.values(), key=lambda r: r.day)

    async def save_run(
        self,
        target_day: date,
        algo: str,
        kpis: dict,
        dispatch_rows: list[dict],
        forecast_rows: list[dict] | None = None,
        decision: dict | None = None,
    ) -> M.Run:
        tid = self.tenant_id
        run = M.Run(
            id=next(self._ids), tenant_id=tid, target_day=target_day, algo=algo, status="ok", kpis=kpis,
            created_at=self._now(),
        )
        self._runs.append(run)
        self._dispatch += [M.Dispatch(id=next(self._ids), tenant_id=tid, run_id=run.id, **r) for r in dispatch_rows]
        self._forecasts += [
            M.Forecast(id=next(self._ids), tenant_id=tid, run_id=run.id, **r) for r in forecast_rows or []
        ]
        if decision:
            self._decisions.append(
                M.Decision(id=next(self._ids), tenant_id=tid, run_id=run.id, created_at=self._now(), **decision)
            )
        return run

    async def save_whatif(self, params: dict, result: dict) -> None:
        self._whatifs.append(M.WhatifRun(
            id=next(self._ids), tenant_id=self.tenant_id, params=params, result=result, created_at=self._now(),
        ))

    async def prices_latest(self) -> list[float]:
        """Preisvektor des jüngsten Laufs — Basis für /whatif. Wie Postgres: 96 Slots, an Umstellungstagen 92/100.
        Unvollständige Läufe sind keine Preisbasis."""
        run = await self.latest_run()
        if not run:
            return []
        rows = await self.dispatch_for_run(run.id)
        return [d.pred_price or 0.0 for d in rows] if len(rows) in (92, 96, 100) else []

    async def upsert_prices(self, rows: list[dict]) -> int:
        for r in rows:
            key = (r["ts"], r["source"])
            if key in self._prices:
                self._prices[key].price_eur_mwh = r["price_eur_mwh"]
            else:
                self._prices[key] = M.MarketPrice(id=next(self._ids), tenant_id=self.tenant_id, **r)
        return len(rows)

    async def upsert_fundamentals(self, rows: list[dict]) -> int:
        for r in rows:
            cur = self._fundamentals.get(r["day"])
            if cur:
                cur.ttf_gas_eur_mwh, cur.eua_co2_eur_t = r.get("ttf_gas_eur_mwh"), r.get("eua_co2_eur_t")
            else:
                self._fundamentals[r["day"]] = M.MarketFundamental(id=next(self._ids), tenant_id=self.tenant_id, **r)
        return len(rows)

    async def upsert_regelenergie(self, rows: list[dict]) -> int:
        for r in rows:
            key = (r["day"], r["product"])
            if key in self._regelenergie:
                self._regelenergie[key].price_eur_mw_h = r["price_eur_mw_h"]
            else:
                self._regelenergie[key] = M.RegelenergiePrice(id=next(self._ids), tenant_id=self.tenant_id, **r)
        return len(rows)

    async def get_or_create_chat_session(self, session_id: int | None = None, agent_id: str = "enno") -> M.ChatSession:
        if session_id and session_id in self._chat_sessions:
            return self._chat_sessions[session_id]
        cs = M.ChatSession(id=next(self._ids), tenant_id=self.tenant_id, agent_id=agent_id, created_at=self._now())
        self._chat_sessions[cs.id] = cs
        return cs

    async def save_chat_message(
        self, session_id: int, role: str, content: str, tool_calls: list | None = None
    ) -> None:
        self._chat_messages.append(M.ChatMessage(
            id=next(self._ids), tenant_id=self.tenant_id, session_id=session_id, role=role, content=content,
            tool_calls={"calls": tool_calls} if tool_calls else None, created_at=self._now(),
        ))

    async def chat_history(self, session_id: int) -> list[M.ChatMessage]:
        return [m for m in self._chat_messages if m.session_id == session_id]

    async def get_plant_config(self) -> dict | None:
        return self._plant_config

    async def set_plant_config(self, params: dict) -> None:
        self._plant_config = params

    async def upsert_measurements(self, rows: list[dict]) -> int:
        for r in rows:
            self._measurements[r["ts"]] = M.PlantMeasurement(tenant_id=self.tenant_id, ts=r["ts"], p_mw=r["p_mw"])
        return len(rows)

    async def measurements(self, start: datetime, end: datetime) -> list[M.PlantMeasurement]:
        return [m for ts, m in sorted(self._measurements.items()) if start <= ts < end]

    async def runs_since(self, since: date) -> list[M.Run]:
        return sorted((r for r in self._runs if r.target_day >= since), key=lambda r: (r.target_day, r.created_at))

    async def ping(self) -> None:
        pass  # im Prozess: immer erreichbar

    async def memory_count(self) -> int:
        return 0  # Langzeitgedächtnis braucht pgvector; hier degradiert es wie memory.search ohne Embedding

    async def search_memory(self, query: str, k: int = 4) -> list[M.AgentMemory]:
        return []


Repository = PostgresRepository | MemoryRepository


def make_repository(url: str, tenant_id: str | None = None) -> Repository:
    """memory:// → Speicher, sonst Postgres. Verbindet nicht beim Erzeugen."""
    return MemoryRepository(tenant_id) if url.startswith("memory://") else PostgresRepository(url, tenant_id)
