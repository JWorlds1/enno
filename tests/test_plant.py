"""Anlagendaten wirken: importierte Werte verändern Engine, API und Enno — und nur gültige Anlagen werden angenommen."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import whatif
from config import PLANT
from fldos import enno
from fldos.api import app
from fldos.db import engine
from fldos.storage import PostgresRepository

PRICES = [60 + 40 * ((t % 32) / 32) for t in range(96)]  # synthetischer Tag, ohne Datenbasis lauffähig


def test_with_overrides_types_and_unknown_keys():
    p = PLANT.with_overrides({"eta_el": 0.38, "min_up_slots": 6.0})
    assert p.eta_el == 0.38 and p.min_up_slots == 6 and isinstance(p.min_up_slots, int)
    assert PLANT.with_overrides({}) is PLANT and PLANT.with_overrides(None) is PLANT
    with pytest.raises(KeyError):
        PLANT.with_overrides({"gibt_es_nicht": 1})


def test_engine_uses_the_given_plant():
    base = whatif.solve_day(PRICES, plant=PLANT)
    weaker = whatif.solve_day(PRICES, plant=PLANT.with_overrides({"eta_el": 0.36}))
    bigger = whatif.solve_day(PRICES, plant=PLANT.with_overrides({"p_bhkw_mw": 1.5}))
    assert base["status"] == weaker["status"] == bigger["status"] == "Optimal"
    # schlechterer Wirkungsgrad: mehr Gas je MWh_el → anderer Gasbedarf, anderes Ergebnis
    assert weaker["net_eur"] != pytest.approx(base["net_eur"], abs=1)
    assert max(bigger["bhkw"]) > PLANT.p_bhkw_mw  # größere Anlage wird auch genutzt


def test_api_plant_override_flows_into_live_results_and_reset_restores():
    asyncio.run(_api())


async def _api() -> None:
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.put("/api/v1/plant-config", json={"params": {}})
            body = {"gas": 70, "h2": 100, "co2": 79, "mode": "electro"}  # = Enno ohne Technik-Angabe (Anlage mit Elektrolyseur)
            w0 = await c.post("/api/v1/whatif", json=body)
            if w0.status_code == 404:
                pytest.skip("keine Preisbasis in der DB")
            s0 = (await c.get("/api/v1/sensitivity")).json()

            put = await c.put("/api/v1/plant-config", json={"params": {"eta_el": 0.36, "start_cost_eur": 120}})
            assert put.status_code == 200 and put.json()["applied_to_optimizer"] is True
            w1 = (await c.post("/api/v1/whatif", json=body)).json()
            s1 = (await c.get("/api/v1/sensitivity")).json()
            assert w1["net_eur"] != pytest.approx(w0.json()["net_eur"], abs=1)
            assert s1["base_net"] != pytest.approx(s0["base_net"], abs=1)

            s = PostgresRepository()  # Enno rechnet mit derselben Anlage
            a = await enno.basis_chat(s, "Rechne mit Gaspreis 70")
            assert enno._eur(w1["net_eeg_eur"] if w1.get("net_eeg_eur") is not None else w1["net_eur"]) in a["reply"]  # Seite = Enno

            await c.put("/api/v1/plant-config", json={"params": {}})
            w2 = (await c.post("/api/v1/whatif", json=body)).json()
            assert w2["net_eur"] == pytest.approx(w0.json()["net_eur"], abs=1e-6)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("params, msg", [
    ({"eta_el": 1.5}, "zwischen 0 und 1"),
    ({"dt_h": 0.5}, "nicht änderbar"),
    ({"min_up_slots": 2.5}, "ganze Zahl"),
    ({"storage_hours": 0}, "größer als 0"),
    ({"full_hours_per_day": 30}, "höchstens 24"),
    ({"heat_min_runtime_slots": 96, "full_hours_per_day": 1}, "kein Fahrplan möglich"),
])
def test_invalid_or_infeasible_plant_is_rejected(params, msg):
    asyncio.run(_reject(params, msg))


async def _reject(params: dict, msg: str) -> None:
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.put("/api/v1/plant-config", json={"params": {}})
            r = await c.put("/api/v1/plant-config", json={"params": params})
            try:
                if msg == "kein Fahrplan möglich" and r.status_code == 200:
                    pytest.skip("keine Preisbasis → kein Probelauf")
                assert r.status_code == 422 and msg in r.json()["detail"], r.text
                assert (await c.get("/api/v1/plant-config")).json()["override"] == {}
            finally:
                await c.put("/api/v1/plant-config", json={"params": {}})
    finally:
        await engine.dispose()
