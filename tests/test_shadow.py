"""Schattenbetrieb: CSV-Import in Marktzeit, fairer Vergleich bei gleicher Energiemenge."""
import pandas as pd
import pytest

from fldos import shadow


def test_parse_csv_berlin_time_kw_and_decimal_comma():
    rows = shadow.parse_csv("zeit;leistung_kw\n2026-10-11 00:00;1000\n2026-10-11 00:05;500\n2026-10-11 00:15;250,5\n")
    assert rows[0]["ts"].isoformat() == "2026-10-10T22:00:00+00:00"  # 00:00 Berlin (MESZ) = 22:00 UTC
    assert rows[0]["p_mw"] == pytest.approx(0.75)  # Mittel 1000/500 kW je Viertelstunde
    assert rows[1]["p_mw"] == pytest.approx(0.2505)
    mw = shadow.parse_csv("zeit,leistung_mw\n2026-10-11T00:00:00+02:00,0.8\n")
    assert mw[0]["p_mw"] == pytest.approx(0.8)
    assert shadow.parse_csv("") == []


def test_parse_csv_across_dst_change_with_offsets():
    # Leitwarten-CSV über den 25.10.: Offsets +02:00 und +01:00 gemischt (vorher 500 „Mixed timezones“)
    rows = shadow.parse_csv("zeit;leistung_kw\n2026-10-25T01:45:00+02:00;500\n2026-10-25T02:15:00+02:00;600\n"
                            "2026-10-25T02:15:00+01:00;700\n2026-10-25T03:00:00+01:00;800\n")
    assert [r["ts"].isoformat() for r in rows] == ["2026-10-24T23:45:00+00:00", "2026-10-25T00:15:00+00:00",
                                                   "2026-10-25T01:15:00+00:00", "2026-10-25T02:00:00+00:00"]
    assert [r["p_mw"] for r in rows] == pytest.approx([0.5, 0.6, 0.7, 0.8])


def test_parse_csv_local_time_across_dst_change():
    # reine Lokalzeit: doppelte Stunde 02:00–02:59 der Reihe nach (erst Sommer-, dann Winterzeit), nichts verloren
    rows = shadow.parse_csv("zeit;leistung_kw\n2026-10-25 01:45;100\n2026-10-25 02:00;200\n2026-10-25 02:45;300\n"
                            "2026-10-25 02:00;400\n2026-10-25 02:45;500\n2026-10-25 03:00;600\n")
    assert [r["ts"].isoformat()[11:16] for r in rows] == ["23:45", "00:00", "00:45", "01:00", "01:45", "02:00"]
    assert [r["p_mw"] for r in rows] == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])


def test_evaluate_fair_comparison_same_energy():
    idx = pd.date_range("2026-10-10 22:00", periods=4, freq="15min", tz="UTC")
    prices = pd.Series([200.0, 200.0, 50.0, 50.0], index=idx)
    plan = pd.Series([1.0, 1.0, 0.0, 0.0], index=idx)          # teuerste Stunden
    measured = pd.Series([0.5, 0.5, 0.5, 0.5], index=idx)      # gleiche Energie, gleichmäßig
    out = shadow.evaluate({"2026-10-11": plan}, measured, prices)
    d = out["days"][0]
    assert d["energy_rec_mwh"] == d["energy_meas_mwh"] == 0.5
    assert d["price_rec_eur_mwh"] == 200.0 and d["price_meas_eur_mwh"] == 125.0
    assert d["extra_same_energy_eur"] == 38.0  # (200 − 125) × 0,5 MWh = 37,5 → gerundet
    assert out["summary"]["days"] == 1


def test_evaluate_skips_days_without_enough_measurements():
    idx = pd.date_range("2026-10-10 22:00", periods=10, freq="15min", tz="UTC")
    plan, prices = pd.Series(1.0, index=idx), pd.Series(100.0, index=idx)
    measured = pd.Series([1.0] * 8, index=idx[:8])  # 80 % < 90 %
    assert shadow.evaluate({"2026-10-11": plan}, measured, prices)["summary"]["days"] == 0


def test_api_upload_and_compare(monkeypatch):
    import asyncio
    from datetime import date, datetime, timezone

    from httpx import ASGITransport, AsyncClient

    from fldos import api
    from fldos.storage import MemoryRepository

    repo = MemoryRepository("schatten-test")
    idx = pd.date_range("2026-10-10 22:00", periods=96, freq="15min", tz="UTC")
    plan = [{"slot": i, "ts": t.to_pydatetime(), "pred_price": 0.0, "bhkw_mw": 1.0 if i >= 64 else 0.0,
             "electrolyser_mw": 0.0, "pyro_mw": None} for i, t in enumerate(idx)]
    asyncio.run(repo.save_run(date(2026, 10, 11), "schedule", {}, plan))
    prices = pd.Series([50.0] * 64 + [200.0] * 32, index=idx)  # abends teuer
    monkeypatch.setattr(api, "_prices_utc", lambda: prices)
    monkeypatch.setattr(api, "HISTORY_PATH", type("P", (), {"exists": lambda self: True})())
    api.app.dependency_overrides[api.get_repository] = lambda: repo
    csv = "zeit;leistung_kw\n" + "\n".join(f"{t.tz_convert('Europe/Berlin'):%Y-%m-%d %H:%M};333,333" for t in idx)
    try:
        async def go():
            async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as c:
                up = await c.post("/api/v1/measurements", json={"csv": csv})
                bad = await c.post("/api/v1/measurements", json={"csv": "kaputt"})
                return up, bad, await c.get("/api/v1/shadow")
        up, bad, sh = asyncio.run(go())
    finally:
        api.app.dependency_overrides.clear()
    assert up.status_code == 200 and up.json()["rows"] == 96
    assert bad.status_code == 422
    d = sh.json()["days"][0]
    assert d["energy_rec_mwh"] == 8.0 and d["energy_meas_mwh"] == pytest.approx(8.0, abs=0.01)  # gleiche Energie
    assert d["price_rec_eur_mwh"] == 200.0 and d["price_meas_eur_mwh"] == 100.0  # gleichmäßig: (64×50+32×200)/96
    assert d["extra_same_energy_eur"] == pytest.approx(800, abs=2)  # (200−100) × 8 MWh
