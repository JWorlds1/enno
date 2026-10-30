"""Fahrplan-Export: Marktzeit, deutsches Zahlenformat, je Viertelstunde eine Zeile."""
import asyncio
from datetime import date, datetime, timezone

from httpx import ASGITransport, AsyncClient

from fldos import api
from fldos.storage import MemoryRepository


def test_fahrplan_csv_in_market_time():
    repo = MemoryRepository("csv-test")
    rows = [{"slot": i, "ts": datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc).replace(minute=0) if i == 0
             else datetime(2026, 10, 10, 22, 15, tzinfo=timezone.utc), "pred_price": 101.5, "bhkw_mw": 1.0,
             "electrolyser_mw": 0.0, "pyro_mw": None, "reserve_up_mw": None if i == 0 else 0.4,
             "reserve_down_mw": None if i == 0 else 0.2} for i in range(2)]
    asyncio.run(repo.save_run(date(2026, 10, 11), "schedule", {}, rows))
    api.app.dependency_overrides[api.get_repository] = lambda: repo
    try:
        async def go():
            async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as c:
                return await c.get("/api/v1/recommendation.csv")
        r = asyncio.run(go())
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="fahrplan_2026-10-11.csv"' in r.headers["content-disposition"]
    lines = r.text.strip().split("\n")
    assert lines[0] == "zeit_berlin;zeit_utc;preis_eur_mwh;bhkw_mw;elektrolyse_mw;reserve_hoch_mw;reserve_runter_mw"
    assert lines[1] == "2026-10-11 00:00;2026-10-10T22:00Z;101,500;1,000;0,000;0,000;0,000"  # 22:00 UTC = 00:00 Berlin (MESZ)
    assert lines[2].endswith(";0,400;0,200")  # H-05: vorgehaltene Reserve geht an die Leitwarte
