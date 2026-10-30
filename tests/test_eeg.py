"""EEG-Erlöse: Marktprämie (AW − MW, nie negativ), § 51 negative Preise, § 39m Jahresmenge, § 50a Flexzuschlag."""
from dataclasses import replace

import pandas as pd
import pytest

from config import PLANT
from fldos import eeg

P = replace(PLANT, aw_eur_mwh=231.2, eeg_share=0.10, flex_eur_kw_a=0.0)


def test_premium_capped_at_annual_share_per_day():
    e = eeg.day([1.0] * 96, [100.0] * 96, P, marktwert=100.0)  # 24 MWh erzeugt, Deckel 0,1 × 1 MW × 24 h = 2,4 MWh
    assert e["praemie_mwh"] == pytest.approx(2.4)
    assert e["eeg_premium_eur"] == pytest.approx(2.4 * 131.2)


def test_no_premium_at_negative_prices():
    e = eeg.day([0.5] * 96, [-5.0] * 96, P, marktwert=80.0)
    assert e["eeg_premium_eur"] == 0.0
    part = eeg.day([0.5] * 96, [-5.0] * 92 + [50.0] * 4, P, marktwert=80.0)  # nur 4 Slots positiv → 0,5 MWh
    assert part["praemie_mwh"] == pytest.approx(0.5)


def test_premium_never_negative_and_flex_per_day():
    assert eeg.day([1.0] * 96, [300.0] * 96, P, marktwert=300.0)["eeg_premium_eur"] == 0.0  # MW > AW → 0
    flex = eeg.day([0.0] * 96, [50.0] * 96, replace(P, flex_eur_kw_a=100.0), marktwert=50.0)["flex_eur"]
    assert flex == pytest.approx(100 * 1000 / 365)  # 1 MW × 100 €/kW·a


def test_monthly_market_value_in_market_time(tmp_path):
    utc = pd.date_range("2026-09-30 22:00", periods=4, freq="15min", tz="UTC")  # = 01.10. 00:00 Berlin
    pd.DataFrame({"utc": [t.isoformat() for t in utc], "da_price_eur_mwh": [10, 20, 30, 40]}).to_csv(tmp_path / "h.csv", index=False)
    assert eeg.monthly_market_value(tmp_path / "h.csv", pd.Timestamp("2026-10-15").date()) == 25.0
    assert eeg.monthly_market_value(tmp_path / "h.csv", pd.Timestamp("2026-09-15").date()) is None


def test_net_incl_eeg_is_the_one_netto():
    # eine Netto-Definition für Was-wäre-wenn, Sensitivität und Enno: Spot/Wärme/PtX − Gas + Marktprämie + Flexzuschlag
    r = {"net_eur": -600.0, "bhkw": [1.0] * 96}
    e = eeg.day(r["bhkw"], [100.0] * 96, P, marktwert=100.0)
    assert eeg.net_incl_eeg(r, [100.0] * 96, P, 100.0) == pytest.approx(-600.0 + e["eeg_premium_eur"] + e["flex_eur"])
    assert eeg.net_incl_eeg(r, [100.0] * 96, P, None) == -600.0  # Monatsmarktwert unbekannt → ohne EEG


def test_eeg_budget_picks_days_by_forecast_not_hindsight():
    """H-06: ausgewählt wird nach dem vorab erwarteten Mehrerlös, gezählt der erzielte — nie nach dem Ergebnis sortiert."""
    import asyncio
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient

    from fldos import api

    rows = [SimpleNamespace(exp_fc=300.0, up_fc=50.0), SimpleNamespace(exp_fc=100.0, up_fc=400.0),
            SimpleNamespace(exp_fc=200.0, up_fc=150.0)]

    class Repo:
        async def backtest(self):
            return rows

    api.app.dependency_overrides[api.get_repository] = lambda: Repo()
    try:
        async def go():
            async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as c:
                return (await c.get("/api/v1/eeg-budget?annual_hours=16&daily_hours=8")).json()
        e = asyncio.run(go())
    finally:
        api.app.dependency_overrides.clear()
    assert e["ranking"] == "prognose" and e["affordable_days"] == 2
    assert e["value_at_budget"] == 200.0  # Tage mit Erwartung 300 und 200 → erzielt 50 + 150 (nicht 400 + 150)


def test_validation_messages_are_german():
    """N-03: 422-Meldungen erscheinen in der Oberfläche — auf Deutsch, mit Feldname."""
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from fldos import api

    async def go():
        async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as c:
            return (await c.get("/api/v1/eeg-budget?annual_hours=-80")).json()["detail"]
    assert asyncio.run(go()) == "annual_hours: mindestens 0"
