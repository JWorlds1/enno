"""Invarianten der Analyse-Module (klein gehalten: wenige Tage/Szenarien, echte Daten).

Überspringt ohne Datenbasis; die API-Tests für /plant-config brauchen die migrierte DB.
"""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from fldos import analytics as A
from fldos.api import app
from fldos.db import engine

needs_data = pytest.mark.skipif(not A.FORECASTS.exists(), reason="keine Datenbasis in FLD_DATA_DIR")
EPS = 1e-6


@needs_data
def test_forecast_band_aci_beats_raw_coverage():
    r = A.forecast_band(show_days=1)
    cov = r["coverage"]
    assert abs(cov["aci"] - r["target"]) < abs(cov["raw"] - r["target"])
    assert len(r["series"]) == 96
    assert all(p["ts"].endswith("Z") for p in r["series"])  # UTC ausdrücklich, sonst liest der Browser Lokalzeit


@needs_data
def test_revenue_stack_coopt_dominates_spot_only():
    r = A.revenue_stack(n_days=2)
    for row in r["rows"]:
        assert row["coopt"] >= row["spot_only"] - 0.5          # Reserve ist optional -> nie schlechter
        assert abs(row["energy"] + row["capacity"] - row["coopt"]) < 0.5


@needs_data
def test_plasma_modes_never_worse_than_power_only():
    r = A.plasma_compare(n_days=2)
    for row in r["rows"]:
        assert row["electro"] >= row["power"] - 0.5
        assert row["pyro"] >= row["power"] - 0.5


@needs_data
def test_sensitivity_gas_price_lowers_net():
    g, days = A._forecast_days()
    prices = g.loc[days[-1], "pred_B"].tolist()
    r = A.sensitivity(prices)
    gas = next(b for b in r["bars"] if b["param"] == "gas")
    assert gas["high_net"] < gas["low_net"]
    assert [b["swing"] for b in r["bars"]] == sorted((b["swing"] for b in r["bars"]), reverse=True)
    with_eeg = A.sensitivity(prices, marktwert=90.0)  # Netto inkl. EEG wie Was-wäre-wenn und Enno
    assert with_eeg["with_eeg"] is True and r["with_eeg"] is False
    assert with_eeg["base_net"] > r["base_net"]  # Marktprämie (231,2 − 90) kommt hinzu


@needs_data
def test_pareto_front_trades_profit_for_co2():
    r = A.pareto(points=4)
    front = r["front"]
    assert len(front) >= 2
    for a, b in zip(front, front[1:]):
        assert b["co2_t"] >= a["co2_t"] - EPS
        assert b["profit"] <= a["profit"] + 0.5


@needs_data
def test_mpc_shapes():
    r = A.mpc_state(n_days=2)
    assert len(r["days"]) == len(r["base_eur"]) == len(r["mpc_eur"]) == 2
    assert len(r["level_mpc"]) == 2 * 96
    assert all(0 - EPS <= v <= r["s_max"] + 0.01 for v in r["level_mpc"])


@needs_data
def test_risk_value_ordering():
    r = A.risk(n_scen=4, lambdas=(0.0, 0.9))
    assert r["ws"] >= r["rp"] - 0.5 >= r["eev"] - 1.0         # WS ≥ RP ≥ EEV
    f0, f9 = r["frontier"]
    assert f9["cvar"] >= f0["cvar"] - 0.5                      # Risikoaversion hebt den Tail


def test_plant_config_validation_roundtrip():
    asyncio.run(_plant_config())


async def _plant_config() -> None:
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            bad = await c.put("/api/v1/plant-config", json={"params": {"unbekannt": 1}})
            assert bad.status_code == 422
            neg = await c.put("/api/v1/plant-config", json={"params": {"eta_el": -0.1}})
            assert neg.status_code == 422
            ok = await c.put("/api/v1/plant-config", json={"params": {"eta_el": 0.40}})
            assert ok.status_code == 200
            d = ok.json()
            assert d["diff"]["eta_el"] == {"default": 0.42, "plant": 0.40}
            reset = await c.put("/api/v1/plant-config", json={"params": {}})
            assert reset.json()["diff"] == {}

            # Endpoint-Ebene: Preisvektor (list) im Cache-Schlüssel darf nicht crashen, 2. Aufruf aus Cache
            sens = await c.get("/api/v1/sensitivity?gas=80&mode=electro")
            assert sens.status_code in (200, 404)
            if sens.status_code == 200:
                assert len(sens.json()["bars"]) == 3
                again = await c.get("/api/v1/sensitivity?gas=80&mode=electro")
                assert again.json() == sens.json()
                # H-03: ein Netto im System — Sensitivität (Basis) == Was-wäre-wenn (Netto inkl. EEG) bei gleichen Annahmen
                same = (await c.get("/api/v1/sensitivity?gas=121&h2=100&co2=79&mode=electro")).json()
                wi = (await c.post("/api/v1/whatif", json={"gas": 121, "h2": 100, "co2": 79, "mode": "electro", "algo": "whatif"})).json()
                assert same["base_net"] == pytest.approx(wi.get("net_eeg_eur") or wi["net_eur"], abs=0.1)
                assert same["with_eeg"] == ("net_eeg_eur" in wi and wi["net_eeg_eur"] is not None)
            bad_mode = await c.get("/api/v1/sensitivity?mode=kohle")
            assert bad_mode.status_code == 422
    finally:
        await engine.dispose()
