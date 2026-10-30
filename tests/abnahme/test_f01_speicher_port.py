"""F01 Speicher-Port: Persistenz hinter einer Naht mit zwei Adaptern (Postgres, Speicher)."""
import asyncio
from datetime import date

from fldos.storage import MemoryRepository, PostgresRepository, make_repository

PORT = {
    "latest_run", "dispatch_for_run", "forecasts_for_run", "decision_for_run", "backtest", "fundamentals",
    "regelenergie", "save_run", "save_whatif", "prices_latest", "upsert_prices", "upsert_fundamentals",
    "upsert_regelenergie", "get_or_create_chat_session", "save_chat_message", "chat_history",
    "get_plant_config", "set_plant_config",
}


def test_beide_adapter_erfuellen_denselben_port():
    for cls in (MemoryRepository, PostgresRepository):
        fehlt = {n for n in PORT if not callable(getattr(cls, n, None))}
        assert not fehlt, (cls.__name__, sorted(fehlt))


def test_auswahl_per_url_ohne_verbindungsaufbau():
    assert isinstance(make_repository("memory://"), MemoryRepository)
    assert isinstance(make_repository("postgresql+asyncpg://niemand@127.0.0.1:1/keine"), PostgresRepository)


def test_speicher_roundtrip():
    async def go():
        r = MemoryRepository()
        run = await r.save_run(
            target_day=date(2099, 1, 1), algo="abnahme", kpis={"expected_revenue_eur": 42.0},
            dispatch_rows=[
                {"slot": 0, "ts": None, "pred_price": 50.0, "bhkw_mw": 1.0, "electrolyser_mw": 0.0, "pyro_mw": None},
                {"slot": 1, "ts": None, "pred_price": 60.0, "bhkw_mw": 0.5, "electrolyser_mw": 0.1, "pyro_mw": None},
            ],
        )
        got = await r.latest_run(algo="abnahme")
        assert got is not None and got.id == run.id and got.kpis["expected_revenue_eur"] == 42.0
        assert [x.pred_price for x in await r.dispatch_for_run(run.id)] == [50.0, 60.0]
        assert await r.latest_run(algo="gibt-es-nicht") is None
        assert await r.prices_latest() == []
        assert await r.get_plant_config() is None
        await r.set_plant_config({"eta_el": 0.36})
        await r.set_plant_config({"eta_el": 0.40})
        assert await r.get_plant_config() == {"eta_el": 0.40}
    asyncio.run(go())


def test_mandanten_bleiben_getrennt():
    """Verfassung §9: kein übergreifender Zugriff, auch nicht im Speicher-Adapter."""
    async def go():
        a, b = MemoryRepository(tenant_id="mandant-a"), MemoryRepository(tenant_id="mandant-b")
        await a.set_plant_config({"eta_el": 0.36})
        assert await b.get_plant_config() is None
        await a.save_run(target_day=date(2099, 1, 2), algo="abnahme", kpis={}, dispatch_rows=[])
        assert await b.latest_run(algo="abnahme") is None
    asyncio.run(go())
