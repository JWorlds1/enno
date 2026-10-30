"""Preisrechner (fairer Wert H₂/Kohlenstoff aus freien Marktdaten) und Splitter (Gas → Strom oder → H₂ + C je Viertelstunde).

FLD-Verhältnis aus derselben Gasmenge (Meeting 17.10.2026): 250 kWh Strom ODER 5,6 kg H₂ + 19 kg C."""
import asyncio
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient

import splitter
import value_prices as vp
from config import PLANT


# ── Preisrechner ────────────────────────────────────────────────────────────
def test_h2_grauer_wasserstoff_aus_gas_und_co2():
    # 46 kWh Gas × 86,43 €/MWh + 9 kg CO₂ × 85,50 €/t + 0,40 € Anlagenkosten
    assert vp.h2_grey(86.43, 85.50) == pytest.approx(0.046 * 86.43 + 0.009 * 85.50 + 0.40)
    assert vp.h2_grey(86.43, 85.50) == pytest.approx(5.145, abs=0.001)


def test_kohlenstoff_als_co2_wert_und_als_entnahme_zertifikat():
    assert vp.carbon_co2(85.50) == pytest.approx(44 / 12 * 85.50 / 1000)  # ≈ 0,31 €/kg C
    assert vp.carbon_cdr() == pytest.approx(44 / 12 * vp.CDR_EUR_T_CO2 / 1000)


def test_kohlenstoff_als_russ_aus_oelpreis():
    v = vp.carbon_black(109.86, 1.1244)
    expect = (vp.OIL_T_PER_T_C * vp.BBL_PER_T * 109.86 / 1.1244 * vp.FEED_SHARE_OF_BRENT + vp.BLACK_PROCESS_EUR_T) / 1000
    assert v == pytest.approx(expect)
    assert 1.0 < v < 2.0  # Plausibilität: Marktberichte nennen ~1,5 $/kg


@pytest.mark.parametrize("brent, fx", [(None, 1.12), (110.0, None), (float("nan"), 1.12), (110.0, 0.0)])
def test_russ_ohne_oeldaten_ist_keine_schaetzung(brent, fx):
    assert vp.carbon_black(brent, fx) is None  # Abbruchkriterium: lieber „keine Daten“ als ein erfundener Wert


def test_preise_aus_marktzeile():
    row = {"date": "2026-10-16", "ttf_eur_mwh": 86.43, "eua_eur_t": 85.50, "brent_usd_bbl": 109.86, "eurusd": 1.1244}
    p = vp.prices(row)
    assert p["as_of"] == "2026-10-16"
    assert p["h2"]["eur_kg"] == pytest.approx(vp.h2_grey(86.43, 85.50))
    assert set(p["carbon"]) == {"co2", "cdr", "black"}
    assert p["carbon"]["black"]["eur_kg"] == pytest.approx(vp.carbon_black(109.86, 1.1244))
    assert all(v["formula"] and v["source"] for v in [p["h2"], *p["carbon"].values()])
    old = vp.prices({"date": "2026-10-16", "ttf_eur_mwh": 86.43, "eua_eur_t": 85.50})  # Datei ohne Öl-Spalten
    assert old["carbon"]["black"]["eur_kg"] is None


# ── Splitter ────────────────────────────────────────────────────────────────
def test_schwelle_aus_fld_verhaeltnis():
    # 0,25 MWh × p = 5,6 kg × H₂ + 19 kg × C  →  p* = 22,4·H₂ + 76·C
    assert splitter.threshold(5.0, 1.0, PLANT) == pytest.approx(22.4 * 5.0 + 76 * 1.0)
    assert splitter.threshold(3.0, 0.29, PLANT) == pytest.approx(89.24)  # 22,4·3 + 76·0,29


def test_je_viertelstunde_der_hoehere_erloes():
    p = [50.0, 100.0, 200.0, 300.0] + [80.0] * 92
    s = splitter.split_day(p, h2=5.0, c=0.29, plant=PLANT)  # Schwelle ≈ 134 €/MWh
    assert s["route"][:4] == ["plasma", "plasma", "strom", "strom"]
    assert s["strom_slots"] == 2
    plasma = 5.6 * 5.0 + 19 * 0.29
    assert s["revenue"]["nur_plasma"] == pytest.approx(96 * plasma)
    assert s["revenue"]["nur_strom"] == pytest.approx(0.25 * sum(p))
    assert s["revenue"]["splitter"] == pytest.approx(0.25 * (200 + 300) + 94 * plasma)
    assert s["revenue"]["splitter"] >= max(s["revenue"]["nur_strom"], s["revenue"]["nur_plasma"])
    assert s["uplift_vs_best"] == pytest.approx(s["revenue"]["splitter"] - max(s["revenue"]["nur_strom"], s["revenue"]["nur_plasma"]))


def test_preis_genau_auf_der_schwelle_geht_in_strom():
    thr = splitter.threshold(5.0, 1.0, PLANT)
    assert splitter.split_day([thr] * 96, 5.0, 1.0, PLANT)["route"] == ["strom"] * 96


def test_stromzeiten_als_bloecke_in_marktzeit():
    times = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]
    p = [300.0 if 68 <= i < 80 else 50.0 for i in range(96)]  # 17:00–20:00 teuer
    s = splitter.split_day(p, 5.0, 0.29, PLANT, times=times)
    assert s["blocks"] == ["17:00–20:00"]
    assert splitter.split_day([300.0] * 96, 5.0, 0.29, PLANT, times=times)["blocks"] == ["00:00–24:00"]
    assert splitter.split_day([10.0] * 96, 5.0, 0.29, PLANT, times=times)["blocks"] == []


def test_verhaeltnis_kommt_aus_den_anlagendaten():
    plant = replace(PLANT, split_el_kwh=500.0, split_h2_kg=5.6, split_c_kg=19.0)
    assert splitter.threshold(5.0, 1.0, plant) == pytest.approx((5.6 * 5 + 19) / 0.5)


def test_zeitumstellung_92_und_100_viertelstunden():
    for n in (92, 100):
        s = splitter.split_day([100.0] * n, 5.0, 0.29, PLANT)
        assert len(s["route"]) == n


# ── API ─────────────────────────────────────────────────────────────────────
def test_api_preisrechner_und_splitter():
    asyncio.run(_api())


async def _api() -> None:
    from fldos.api import app
    from fldos.db import engine
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            vpr = await c.get("/api/v1/value-prices")
            assert vpr.status_code in (200, 404)
            if vpr.status_code != 200:
                return
            v = vpr.json()
            assert v["h2"]["eur_kg"] > 0 and v["carbon"]["co2"]["eur_kg"] > 0
            ok = {"geprüft", "nachjustiert", "plausibel (grau unter grün)", "unplausibel", "nicht geprüft", "Marktpreis (EUA)"}
            assert all(it["check"]["status"] in ok for it in [v["h2"], *v["carbon"].values()])
            assert v["carbon"]["cdr"]["check"]["status"] == "geprüft"

            r = await c.get("/api/v1/splitter?carbon=co2")
            assert r.status_code in (200, 404)
            if r.status_code != 200:
                return
            d = r.json()
            n = len(d["slots"])
            assert n in (92, 96, 100)
            assert d["h2_eur_kg"] == pytest.approx(v["h2"]["eur_kg"]) and d["c_eur_kg"] == pytest.approx(v["carbon"]["co2"]["eur_kg"])
            assert d["threshold_eur_mwh"] == pytest.approx((d["ratio"]["h2_kg"] * d["h2_eur_kg"] + d["ratio"]["c_kg"] * d["c_eur_kg"]) / (d["ratio"]["el_kwh"] / 1000))
            assert d["strom_slots"] == sum(1 for s in d["slots"] if s["route"] == "strom")
            assert d["price_basis"] in ("Prognose", "Auktion")
            assert d["margin_eur_mwh"] == 0 if d["price_basis"] == "Auktion" else d["margin_eur_mwh"] > 0
            # API == Engine mit denselben Parametern (Abstand, Mindestlaufzeit der Anlage)
            px = [s["price"] for s in d["slots"]]
            plant = replace(PLANT, split_el_kwh=d["ratio"]["el_kwh"], split_h2_kg=d["ratio"]["h2_kg"], split_c_kg=d["ratio"]["c_kg"],
                            split_plasma_kwh=d["ratio"]["plasma_kwh"])
            eng = splitter.split_day(px, d["h2_eur_kg"], d["c_eur_kg"], plant, margin=d["margin_eur_mwh"], min_run=d["min_run_slots"],
                                     block=d["block_slots"] or None)
            assert (d["block_slots"] > 0) == (d["price_basis"] == "Auktion")  # nach der Auktion entscheidet der Block
            assert [s["route"] for s in d["slots"]] == eng["route"] and d["switches"] == eng["switches"]
            assert d["unsure_slots"] == sum(1 for s in d["slots"] if not s["sure"])

            own = (await c.get("/api/v1/splitter?carbon=co2&h2=7&c=1.5")).json()  # eigene Preise (Workshop)
            assert own["h2_eur_kg"] == 7 and own["c_eur_kg"] == 1.5
            csv = await c.get("/api/v1/splitter-bids.csv?carbon=co2")
            assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
            lines = csv.text.strip().split("\n")
            assert lines[0].startswith("liefertag;von;bis;menge_mw;mindestpreis_eur_mwh") and len(lines) - 1 == -(-n // 4)
            assert lines[1].split(";")[4] == f"{d['threshold_eur_mwh']:.2f}".replace(".", ",")
            assert (await c.get("/api/v1/splitter?carbon=gold")).status_code == 422
            assert (await c.get("/api/v1/splitter?h2=-1")).status_code == 422
    finally:
        await engine.dispose()


# ── Eigenstrom, Sicherheitsabstand, Mindestlaufzeit ─────────────────────────
def test_eigenstrom_des_plasmas_senkt_die_schwelle():
    # 0,25·p ≥ Plasma-Wert − 0,143·p  →  p* = Plasma-Wert / (0,25 + 0,143)
    plant = replace(PLANT, split_plasma_kwh=143.0)
    assert splitter.threshold(5.0, 0.29, plant) == pytest.approx((5.6 * 5 + 19 * 0.29) / 0.393)
    assert PLANT.split_plasma_kwh == 0.0  # FLD 17.10.: autark, Strombedarf im Verhältnis enthalten
    p = [100.0] * 96
    s = splitter.split_day(p, 5.0, 0.29, plant)
    assert s["revenue"]["nur_plasma"] == pytest.approx(96 * (5.6 * 5 + 19 * 0.29 - 0.143 * 100))


def test_sicherheitsabstand_verhindert_hin_und_her():
    thr = splitter.threshold(5.0, 0.29, PLANT)  # ≈ 134
    zigzag = [thr + 5, thr - 5] * 48  # knapp um die Schwelle
    no_margin = splitter.split_day(zigzag, 5.0, 0.29, PLANT, min_run=1)
    with_margin = splitter.split_day(zigzag, 5.0, 0.29, PLANT, margin=20.0, min_run=1)
    assert no_margin["switches"] == 95
    assert with_margin["switches"] == 0  # bleibt beim ersten Weg, bis der Preis die Schwelle ± 20 klar kreuzt
    clear = [thr + 50] * 8 + [thr - 50] * 88
    assert splitter.split_day(clear, 5.0, 0.29, PLANT, margin=20.0, min_run=1)["switches"] == 1


def test_bhkw_laeuft_mindestens_eine_stunde():
    thr = splitter.threshold(5.0, 0.29, PLANT)
    p = [thr - 50] * 40 + [thr + 50] * 2 + [thr - 50] * 30 + [thr + 50] * 24  # 30-min-Zacken + 6-h-Block
    s = splitter.split_day(p, 5.0, 0.29, PLANT, min_run=PLANT.min_up_slots)  # 4 Viertelstunden = 1 h
    assert s["route"][40:42] == ["plasma", "plasma"]  # Zacke fällt weg
    assert s["route"][72:] == ["strom"] * 24
    assert s["strom_slots"] == 24


def test_unsichere_viertelstunden_aus_dem_prognoseband():
    thr = splitter.threshold(5.0, 0.29, PLANT)
    p = [thr + 30] * 96
    p10 = [thr + 10] * 48 + [thr - 10] * 48  # zweite Hälfte: Band reicht unter die Schwelle
    p90 = [thr + 50] * 96
    s = splitter.split_day(p, 5.0, 0.29, PLANT, p10=p10, p90=p90)
    assert s["sure"] == [True] * 48 + [False] * 48
    assert s["unsure_slots"] == 48


# ── Splitter im Optimierer (Gasspeicher, festes Tagesgas, Mindestlast, Starts, Mindestlaufzeit, Wärme) ─────
def _day(peak: float = 260.0, base: float = 60.0) -> list[float]:
    return [peak if 17 * 4 <= t < 21 * 4 else base for t in range(96)]


def test_milp_ohne_wert_fuer_h2_und_c_kein_plasma():
    import splitter_milp
    r = splitter_milp.solve(_day(), h2=0.0, c=0.0, plant=PLANT)
    assert r["status"] == "Optimal" and sum(r["plasma_gas_mw"]) == pytest.approx(0, abs=1e-6)
    assert r["revenue"]["splitter"] == pytest.approx(r["revenue"]["nur_strom"], abs=0.5)


def test_milp_haelt_anlagengrenzen_und_ist_nie_schlechter_als_nur_strom():
    import splitter_milp
    r = splitter_milp.solve(_day(), h2=5.0, c=0.5, plant=PLANT)
    assert r["status"] == "Optimal"
    gas = sum((p / PLANT.eta_el + g) * PLANT.dt_h for p, g in zip(r["bhkw_mw"], r["plasma_gas_mw"]))
    assert gas == pytest.approx(PLANT.gas_budget_mwh, rel=1e-6)          # festes Tagesgas
    assert max(r["plasma_gas_mw"]) <= PLANT.pyro_max_gas_mwh + 1e-6       # Plasma-Kapazität
    assert all(p == pytest.approx(0, abs=1e-6) or p >= PLANT.min_load * PLANT.p_bhkw_mw - 1e-6 for p in r["bhkw_mw"])
    assert all(0 - 1e-6 <= s <= PLANT.storage_max_mwh + 1e-6 for s in r["storage_mwh"])
    assert sum(1 for p in r["bhkw_mw"] if p > 1e-6) >= PLANT.heat_min_runtime_slots  # Wärme-Mindestlauf
    assert r["revenue"]["splitter"] >= r["revenue"]["nur_strom"] - 1e-6
    assert sum(r["plasma_gas_mw"]) > 0  # günstige Stunden gehen ins Plasma, wenn H₂ + C dort mehr bringen


def test_milp_laufzeit_ein_tag_unter_drei_sekunden():
    import time

    import splitter_milp
    t = time.perf_counter()
    splitter_milp.solve(_day(), h2=5.0, c=0.5, plant=PLANT)
    assert time.perf_counter() - t < 3.0


# ── Nachrechnung: Plan auf der damaligen Prognose, Abrechnung auf Ist ───────
def _write_days(tmp_path, n_days: int = 3):
    import pandas as pd
    idx = pd.date_range("2026-03-02", periods=96 * n_days, freq="15min", tz="Europe/Berlin").tz_convert("UTC")
    hour = idx.tz_convert("Europe/Berlin").hour
    actual = [250.0 if 18 <= h < 21 else 50.0 for h in hour]       # teurer Abend, billiger Rest
    pred = [240.0 if 18 <= h < 21 else 60.0 for h in hour]          # Prognose trifft die Form
    pd.DataFrame({"utc": idx, "actual": actual, "pred_A": pred, "pred_B": pred, "P10": [p - 30 for p in pred],
                  "P90": [p + 30 for p in pred]}).to_csv(tmp_path / "forecasts.csv", index=False)
    pd.DataFrame({"date": ["2026-03-01"], "ttf_eur_mwh": [40.0], "eua_eur_t": [70.0],
                  "brent_usd_bbl": [80.0], "eurusd": [1.1]}).to_csv(tmp_path / "external_market.csv", index=False)


def test_jahresrechnung_zaehlt_umschaltungen_und_bhkw_zeiten(tmp_path, monkeypatch):
    from fldos import analytics
    _write_days(tmp_path)
    monkeypatch.setattr(analytics, "FORECASTS", tmp_path / "forecasts.csv")
    monkeypatch.setattr(analytics, "EXTERNAL", tmp_path / "external_market.csv")
    r = analytics.splitter_year("co2", milp_days=2, margin=20.0, plant=PLANT)
    h2 = vp.h2_grey(40.0, 70.0)
    thr = splitter.threshold(h2, vp.carbon_co2(70.0), PLANT)
    assert 60 < thr < 240  # Abend → Strom, Rest → Plasma
    assert r["days"] == 3 and r["skipped"] == 0
    assert r["switches_per_day"] == 2.0 and r["switches_per_year"] == pytest.approx(2.0 * 365)
    assert r["bhkw_share_pct"] == pytest.approx(100 * 12 / 96)
    assert r["hourly_bhkw_pct"][19] == 100 and r["hourly_bhkw_pct"][12] == 0 and len(r["hourly_bhkw_pct"]) == 24
    assert r["correct_pct"] == 100.0 and r["avg_run_h"] == 3.0 and r["short_runs_per_year"] == 0
    day_plasma = 96 * (5.6 * h2 + 19 * vp.carbon_co2(70.0) - 0)
    day_split = 12 * 0.25 * 250 + 84 * (5.6 * h2 + 19 * vp.carbon_co2(70.0))
    assert r["per_year"]["splitter"] == pytest.approx(day_split * 365, rel=1e-6)
    assert r["per_year"]["nur_plasma"] == pytest.approx(day_plasma * 365, rel=1e-6)
    assert r["milp"]["days"] == 2 and r["milp"]["uplift_eur_per_day"] >= -1e-6
    assert [m["month"] for m in r["monthly"]] == ["2026-03"]


# ── Gebote mit Mindestpreis: die Börse schaltet auf den echten Preisen ─────
def test_gebote_je_stunde_mit_schwelle_als_mindestpreis():
    thr = splitter.threshold(5.0, 0.29, PLANT)
    times = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]
    fc = [thr + 40 if 18 <= i // 4 < 21 else thr - 40 for i in range(96)]
    b = splitter.bids(fc, 5.0, 0.29, PLANT, times=times)
    assert len(b) == 24 and b[0]["from"] == "00:00" and b[0]["to"] == "01:00" and b[23]["to"] == "24:00"
    assert all(x["limit_eur_mwh"] == pytest.approx(thr) and x["mw"] == PLANT.p_bhkw_mw for x in b)
    assert [x["expected"] for x in b].count(True) == 3 and b[19]["expected"] is True  # Prognose: 18–21 Uhr angenommen


def test_nach_der_auktion_entscheidet_der_stundenblock():
    thr = splitter.threshold(5.0, 0.29, PLANT)
    act = [thr - 40] * 96
    act[40:44] = [thr + 100, thr - 20, thr - 20, thr - 20]  # Ø des Blocks 10–11 Uhr = thr + 10 → angenommen
    act[44] = thr + 300  # einzelne Spitze, Ø des Blocks 11–12 Uhr = thr + 45 → angenommen
    s = splitter.split_day(act, 5.0, 0.29, PLANT, block=4)
    assert s["route"][40:48] == ["strom"] * 8 and s["strom_slots"] == 8
    assert s["switches"] == 2


def test_jahresrechnung_mit_gebotsweg(tmp_path, monkeypatch):
    from fldos import analytics
    _write_days(tmp_path)
    monkeypatch.setattr(analytics, "FORECASTS", tmp_path / "forecasts.csv")
    monkeypatch.setattr(analytics, "EXTERNAL", tmp_path / "external_market.csv")
    r = analytics.splitter_year("co2", milp_days=0, margin=20.0, plant=PLANT)
    assert r["bids"]["per_year"] == pytest.approx(r["per_year"]["ideal"])  # Abend-Block 18–21 Uhr = Ideal
    assert r["bids"]["capture_pct"] == 100.0 and r["bids"]["switches_per_year"] == pytest.approx(2 * 365)


def test_formeln_in_deutscher_schreibweise_ohne_none():
    p = vp.prices({"date": "2026-10-16", "ttf_eur_mwh": 86.43, "eua_eur_t": 85.5})
    assert "86,43 €/MWh" in p["h2"]["formula"] and "85,50 €/t" in p["h2"]["formula"]
    assert "None" not in p["carbon"]["black"]["formula"] and "— $/bbl" in p["carbon"]["black"]["formula"]


def test_preiskurve_rechnet_je_monat_mit_terminpreisen():
    curve = [{"month": "2026-11", "ttf_eur_mwh": 87.55, "brent_usd_bbl": 109.86},
             {"month": "2026-12", "ttf_eur_mwh": None, "brent_usd_bbl": 106.82}]
    out = vp.curve(curve, eua_eur_t=85.5, eurusd=1.1244)
    assert out[0]["h2"] == pytest.approx(vp.h2_grey(87.55, 85.5))
    assert out[0]["carbon"]["black"] == pytest.approx(vp.carbon_black(109.86, 1.1244))
    assert out[0]["carbon"]["co2"] == pytest.approx(vp.carbon_co2(85.5)) and out[0]["carbon"]["cdr"] == pytest.approx(vp.carbon_cdr())
    assert out[1]["h2"] is None  # ohne Gas-Terminpreis kein H₂-Wert für den Monat
    assert out[0]["threshold"]["co2"] == pytest.approx(splitter.threshold(out[0]["h2"], out[0]["carbon"]["co2"], PLANT))


def test_preiskurve_fuellt_nur_innere_luecken_und_kennzeichnet_sie():
    rows = [{"month": "2027-01", "ttf_eur_mwh": 87.0, "brent_usd_bbl": None},
            {"month": "2027-02", "ttf_eur_mwh": None, "brent_usd_bbl": 100.0},
            {"month": "2027-03", "ttf_eur_mwh": None, "brent_usd_bbl": 98.0},
            {"month": "2027-04", "ttf_eur_mwh": 69.0, "brent_usd_bbl": None}]
    out = vp.curve(rows, eua_eur_t=85.5, eurusd=1.12)
    assert out[1]["ttf_eur_mwh"] == pytest.approx(81.0) and out[2]["ttf_eur_mwh"] == pytest.approx(75.0)
    assert out[1]["interpolated"] == ["ttf_eur_mwh"] and out[0]["interpolated"] == []
    assert out[0]["brent_usd_bbl"] is None and out[3]["brent_usd_bbl"] is None  # Ränder: keine Verlängerung


def test_api_preiskurve():
    asyncio.run(_curve())


async def _curve() -> None:
    from fldos.api import app
    from fldos.db import engine
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/api/v1/value-curve")
            assert r.status_code in (200, 404)
            if r.status_code == 200:
                d = r.json()
                assert 1 <= len(d["months"]) <= 12
                for m in d["months"]:
                    if m["h2"] is not None and m["threshold"]["co2"] is not None:
                        assert m["threshold"]["co2"] > 0
    finally:
        await engine.dispose()


# ── Preisprüfung gegen öffentliche Referenzpunkte ───────────────────────────
def _ext(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def test_pruefung_russ_innerhalb_15_prozent_gilt_als_geprueft(monkeypatch):
    import price_check
    monkeypatch.setattr(price_check, "REFS", [
        {"path": "black", "date": "2026-02-15", "value": 1.66, "unit": "USD/kg", "comparable": True, "source": "A", "url": "u"},
        {"path": "black", "date": "2026-07-15", "value": 1.51, "unit": "USD/kg", "comparable": True, "source": "B", "url": "u"}])
    ext = _ext([{"date": "2026-02-13", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0, "brent_usd_bbl": 80.0, "eurusd": 1.10},
                {"date": "2026-07-14", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0, "brent_usd_bbl": 75.0, "eurusd": 1.15}])
    r = price_check.validate(ext)["black"]
    f1, f2 = vp.carbon_black(80.0, 1.10), vp.carbon_black(75.0, 1.15)
    devs = [f1 / (1.66 / 1.10) - 1, f2 / (1.51 / 1.15) - 1]
    assert [x["deviation_pct"] for x in r["refs"]] == pytest.approx([100 * d for d in devs])
    assert r["status"] == ("geprüft" if max(abs(d) for d in devs) <= 0.15 else "nachjustiert")


def test_pruefung_justiert_mit_median_faktor_nach(monkeypatch):
    import price_check
    monkeypatch.setattr(price_check, "REFS", [
        {"path": "black", "date": "2026-02-15", "value": 3.00, "unit": "USD/kg", "comparable": True, "source": "A", "url": "u"}])
    ext = _ext([{"date": "2026-02-15", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0, "brent_usd_bbl": 80.0, "eurusd": 1.0}])
    r = price_check.validate(ext)["black"]
    k = 3.00 / vp.carbon_black(80.0, 1.0)
    assert r["status"] == "nachjustiert" and r["factor"] == pytest.approx(k)
    p = vp.prices({"date": "2026-02-15", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0, "brent_usd_bbl": 80.0, "eurusd": 1.0},
                  factors={"black": k})
    assert p["carbon"]["black"]["eur_kg"] == pytest.approx(3.00) and "nachjustiert" in p["carbon"]["black"]["formula"]


def test_pruefung_ohne_oeldaten_ist_nicht_geprueft(monkeypatch):
    import price_check
    ext = _ext([{"date": "2026-02-15", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0}])
    r = price_check.validate(ext)
    assert r["black"]["status"] == "nicht geprüft" and r["black"]["factor"] == 1.0


def test_pruefung_grauer_wasserstoff_nur_plausibilitaet(monkeypatch):
    import price_check
    monkeypatch.setattr(price_check, "REFS", [
        {"path": "h2", "date": "2025-08-15", "value": 5.34, "unit": "EUR/kg", "comparable": False, "note": "grün", "source": "H", "url": "u"}])
    ext = _ext([{"date": "2025-08-15", "ttf_eur_mwh": 35.0, "eua_eur_t": 70.0}])
    r = price_check.validate(ext)["h2"]
    assert vp.h2_grey(35.0, 70.0) < 5.34
    assert r["status"] == "plausibel (grau unter grün)" and r["factor"] == 1.0


def test_pruefung_zertifikat_und_co2():
    import price_check
    ext = _ext([{"date": "2026-03-15", "ttf_eur_mwh": 40.0, "eua_eur_t": 70.0}])
    r = price_check.validate(ext)
    assert r["cdr"]["status"] == "geprüft" and abs(r["cdr"]["refs"][0]["deviation_pct"]) < 1
    assert r["co2"]["status"] == "Marktpreis (EUA)"


# ── Tagesnachweis: jeder ausgegebene Plan, abgerechnet auf den echten Börsenpreisen ─────
def _proof_inputs(tmp_path):
    """Drei Liefertage: 02.03. mit Plan + Ist, 03.03. ohne Plan, 04.03. mit Plan, aber noch ohne Ist."""
    import pandas as pd
    from datetime import date, datetime, timezone
    pd.DataFrame({"date": ["2026-03-01"], "ttf_eur_mwh": [40.0], "eua_eur_t": [70.0], "brent_usd_bbl": [80.0],
                  "eurusd": [1.1]}).to_csv(tmp_path / "external_market.csv", index=False)
    def day(d):
        return pd.date_range(f"{d} 00:00", periods=96, freq="15min", tz="Europe/Berlin").tz_convert("UTC")
    act = pd.Series([250.0 if 18 <= t.tz_convert("Europe/Berlin").hour < 21 else 50.0 for t in day("2026-03-02")],
                    index=day("2026-03-02"))
    pred = [240.0 if 18 <= t.tz_convert("Europe/Berlin").hour < 21 else 60.0 for t in day("2026-03-02")]
    def run(d, issued, basis="Prognose", mae=20.0, p=pred):
        return {"day": date.fromisoformat(d), "issued": datetime.fromisoformat(issued).replace(tzinfo=timezone.utc),
                "basis": basis, "mae": mae, "ts": list(day(d)), "pred": p, "p10": [x - 30 for x in p], "p90": [x + 30 for x in p]}
    runs = [run("2026-03-02", "2026-03-01T08:30"),
            run("2026-03-02", "2026-03-01T13:00", basis="Auktion", mae=20.0, p=act.tolist()),  # später: zählt nicht
            run("2026-03-04", "2026-03-03T08:30")]
    return runs, act, pred


def test_nachweis_rechnet_den_zuerst_ausgegebenen_plan_auf_ist_ab(tmp_path, monkeypatch):
    from fldos import analytics
    runs, act, pred = _proof_inputs(tmp_path)
    monkeypatch.setattr(analytics, "EXTERNAL", tmp_path / "external_market.csv")
    r = analytics.splitter_proof(runs, act, "co2", plant=PLANT)
    rows = {x["day"]: x for x in r["days"]}
    assert list(rows) == ["2026-03-02", "2026-03-03", "2026-03-04"]  # Lücken bleiben sichtbar
    assert rows["2026-03-03"]["status"] == "kein Plan ausgegeben"
    assert rows["2026-03-04"]["status"] == "Ist-Preise fehlen noch"
    d = rows["2026-03-02"]
    assert d["status"] == "abgerechnet" and d["basis"] == "Prognose" and d["issued"].startswith("2026-03-01T08:30")
    h2, c = vp.h2_grey(40.0, 70.0), vp.carbon_co2(70.0)
    plan = splitter.split_day(pred, h2, c, PLANT, margin=20.0, min_run=PLANT.min_up_slots,
                              p10=[x - 30 for x in pred], p90=[x + 30 for x in pred], settle=act.tolist())
    ideal = splitter.split_day(act.tolist(), h2, c, PLANT, min_run=PLANT.min_up_slots)
    bid = splitter.split_day(act.tolist(), h2, c, PLANT, block=max(4, PLANT.min_up_slots))
    assert d["revenue"]["plan"] == pytest.approx(plan["revenue"]["splitter"], abs=0.01)
    assert d["revenue"]["nur_strom"] == pytest.approx(plan["revenue"]["nur_strom"], abs=0.01)
    assert d["revenue"]["nur_plasma"] == pytest.approx(plan["revenue"]["nur_plasma"], abs=0.01)
    assert d["revenue"]["ideal"] == pytest.approx(ideal["revenue"]["splitter"], abs=0.01)
    assert d["revenue"]["gebote"] == pytest.approx(bid["revenue"]["splitter"], abs=0.01)
    best = max(plan["revenue"]["nur_strom"], plan["revenue"]["nur_plasma"])
    assert d["plus_vs_best_eur"] == pytest.approx(plan["revenue"]["splitter"] - best, abs=0.01)
    assert d["capture_pct"] == pytest.approx(100 * plan["revenue"]["splitter"] / ideal["revenue"]["splitter"], abs=0.1)
    assert d["correct_pct"] == 100.0 and d["switches"] == 2
    s = r["summary"]
    assert s["settled_days"] == 1 and s["missing_days"] == 1 and s["pending_days"] == 1
    assert s["streak_days"] == 0  # der 03.03. ohne Plan unterbricht die Serie; der offene 04.03. zählt erst abgerechnet
    assert s["plus_vs_best_eur"] == pytest.approx(d["plus_vs_best_eur"], abs=0.01)


def test_nachweis_folge_zaehlt_nur_lueckenlose_tage(tmp_path, monkeypatch):
    import pandas as pd
    from fldos import analytics
    runs, act, pred = _proof_inputs(tmp_path)
    monkeypatch.setattr(analytics, "EXTERNAL", tmp_path / "external_market.csv")
    nxt = [dict(runs[0], day=runs[0]["day"] + pd.Timedelta(days=i).to_pytimedelta(),
                ts=[t + pd.Timedelta(days=i) for t in runs[0]["ts"]]) for i in (1, 2)]
    prices = pd.concat([act, *[pd.Series(act.values, index=act.index + pd.Timedelta(days=i)) for i in (1, 2)]])
    r = analytics.splitter_proof([runs[0], *nxt], prices, "co2", plant=PLANT)
    assert [x["status"] for x in r["days"]] == ["abgerechnet"] * 3 and r["summary"]["streak_days"] == 3


def test_api_tagesnachweis():
    asyncio.run(_api_proof())


async def _api_proof() -> None:
    from fldos.api import app
    from fldos.db import engine
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/api/v1/splitter-proof?carbon=gold")).status_code == 422  # Endpoint existiert
            r = await c.get("/api/v1/splitter-proof?carbon=co2")
            assert r.status_code in (200, 404)
            if r.status_code != 200:
                return
            d = r.json()
            st = {"abgerechnet", "kein Plan ausgegeben", "zu spät ausgegeben", "Ist-Preise fehlen noch", "keine Marktdaten"}
            assert d["days"] and all(x["status"] in st for x in d["days"])
            days = [x["day"] for x in d["days"]]
            assert days == sorted(days) and len(set(days)) == len(days)
            s = d["summary"]
            assert s["settled_days"] == sum(x["status"] == "abgerechnet" for x in d["days"])
            assert 0 <= s["streak_days"] <= s["settled_days"]
    finally:
        await engine.dispose()


def test_nachweis_plan_am_liefertag_selbst_ist_zu_spaet(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from fldos import analytics
    runs, act, pred = _proof_inputs(tmp_path)
    monkeypatch.setattr(analytics, "EXTERNAL", tmp_path / "external_market.csv")
    late = dict(runs[0], issued=datetime(2026, 3, 2, 13, 0, tzinfo=timezone.utc))  # 14:00 Marktzeit am Liefertag
    r = analytics.splitter_proof([late], act, "co2", plant=PLANT)
    d = r["days"][0]
    assert d["status"] == "zu spät ausgegeben" and d.get("revenue") is None
    assert r["summary"]["settled_days"] == 0 and r["summary"]["late_days"] == 1 and r["summary"]["streak_days"] == 0
    assert r["summary"]["forecast_days"] == 0
