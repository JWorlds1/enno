"""Integrations-Smoke-Test der FLD-API gegen die lokale DB.

Ein async-Client in EINEM Event-Loop (vermeidet das TestClient-Loop-Problem mit asyncpg).
Benötigt migrierte DB (FLD_DATABASE_URL) + Seed; datenlose Endpoints werden tolerant behandelt.
"""
import asyncio

from httpx import ASGITransport, AsyncClient

from fldos.api import app
from fldos.db import engine


def test_api_smoke():
    asyncio.run(_smoke())


async def _smoke() -> None:
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/api/v1/health")
            assert r.status_code == 200 and r.json() == {"status": "ok"}

            st = await c.get("/api/v1/status")
            assert st.status_code == 200
            sd = st.json()
            assert sd["db"] == "ok" and "stale" in sd and "memories" in sd

            rec = await c.get("/api/v1/recommendation")
            assert rec.status_code in (200, 404)
            if rec.status_code == 200:
                assert len(rec.json()["slots"]) == 96

            bt = await c.get("/api/v1/backtest")
            assert bt.status_code == 200
            assert isinstance(bt.json(), list)

            eeg = await c.get("/api/v1/eeg-budget")
            assert eeg.status_code in (200, 404)
            if eeg.status_code == 200:
                e = eeg.json()
                assert e["affordable_days"] == int(876 / 8)  # 109 Betriebstage
                assert len(e["cum_hours"]) == e["total_days"]
                assert 0 <= e["pct_of_max"] <= 100
                assert e["ranking"] in ("prognose", "nachtraeglich")
                assert (await c.get("/api/v1/eeg-budget?annual_hours=-80")).status_code == 422  # N-01

            wf = await c.post("/api/v1/whatif", json={"gas": 90, "h2": 150, "co2": 100, "mode": "plasma"})
            assert wf.status_code in (200, 404)
            if wf.status_code == 200:
                d = wf.json()
                assert d["status"] == "Optimal"
                assert len(d["bhkw"]) == 96

            # target_day muss ein valides Datum sein (Frische-Sanity)
            if rec.status_code == 200:
                from datetime import date
                date.fromisoformat(rec.json()["target_day"])  # wirft bei ungültig

            figs = await c.get("/api/v1/figures")
            assert figs.status_code == 200
            assert isinstance(figs.json(), list)
            for f in figs.json():
                assert f["name"].endswith(".png") and f["title"]

            hm = await c.get("/api/v1/price-heatmap")
            assert hm.status_code in (200, 404)
            if hm.status_code == 200:
                d = hm.json()
                assert len(d["matrix"]) == 7 and len(d["matrix"][0]) == 24

            # Chat-Persistenz (läuft auch ohne LLM: Session + Turns werden gespeichert)
            ch = await c.post("/api/v1/chat", json={"message": "testfrage", "history": []})
            assert ch.status_code == 200
            sid = ch.json()["session_id"]
            hist = await c.get(f"/api/v1/chat/{sid}/history")
            assert hist.status_code == 200
            h = hist.json()
            assert len(h) >= 2 and h[0]["role"] == "user" and h[0]["content"] == "testfrage"
    finally:
        await engine.dispose()
