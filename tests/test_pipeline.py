"""Tageskette: Prognose ohne Blick in die Zukunft, Plan auf Auktionspreisen sobald bekannt, Marktzeit."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from fldos.pipeline import model, plan


def _write_synthetic(d, days: int = 75) -> date:
    """Preis = Tagesprofil + Wind-Effekt + Rauschen; Wetter stündlich. → letzter Liefertag (Berlin)."""
    rng = np.random.default_rng(1)
    utc = pd.date_range("2026-03-02 23:00", periods=96 * days, freq="15min", tz="UTC")
    wind = 8 + 6 * np.sin(np.arange(len(utc)) / 300)
    hour = utc.tz_convert("Europe/Berlin").hour
    price = 80 + 30 * np.sin((hour - 6) / 24 * 2 * np.pi) - 3 * wind + rng.normal(0, 5, len(utc))
    pd.DataFrame({"utc": utc.map(lambda t: t.isoformat()), "unix": utc.map(lambda t: int(t.timestamp())),
                  "da_price_eur_mwh": price}).to_csv(d / "history.csv", index=False)
    hourly = utc[::4]
    w = {"utc": hourly}
    for k in model_points("wind"):
        w[k] = wind[::4]
    for k in model_points("sun"):
        w[k] = np.clip(np.sin((hourly.hour - 6) / 12 * np.pi), 0, None) * 600
        w["temp_" + k[4:]] = 10.0
    pd.DataFrame(w).to_csv(d / "wetter.csv", index=False)
    loc = pd.Series(utc.tz_convert("Europe/Berlin").date)
    sizes = loc.value_counts()
    return max(day for day, n in sizes.items() if n == 96)  # letzter vollständiger Liefertag


def model_points(kind: str) -> list[str]:
    from fldos.pipeline import fetch
    return [f"{kind}_{k}" for k in (fetch.WIND_PTS if kind == "wind" else fetch.SUN_PTS)]


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("daten")
    last = _write_synthetic(d)
    frame, wx = model.frame(d)
    walk = model.walk_forward(frame, wx, months=1, until_day=last)
    return d, frame, wx, walk, last


def test_market_day_is_berlin_and_complete(data):
    _, frame, _, _, last = data
    day = frame[frame["day"] == last]
    assert len(day) == 96
    assert day.index[0].tz_convert("Europe/Berlin").strftime("%H:%M") == "00:00"


def test_forecast_never_sees_prices_of_the_target_day(data, tmp_path):
    d, frame, wx, walk, last = data
    a = model.predict_day(frame, wx, walk, last)
    # Auktionsergebnis des Zieltags in der Quelle ändern und alle Merkmale neu bauen
    h = pd.read_csv(d / "history.csv")
    on_day = pd.to_datetime(h["utc"], utc=True).dt.tz_convert("Europe/Berlin").dt.date == last
    h.loc[on_day, "da_price_eur_mwh"] += 500
    h.to_csv(tmp_path / "history.csv", index=False)
    (tmp_path / "wetter.csv").write_bytes((d / "wetter.csv").read_bytes())
    shocked, _ = model.frame(tmp_path)
    b = model.predict_day(shocked, wx, walk, last)
    assert np.allclose(a["pred_B"], b["pred_B"]) and np.allclose(a["pred_A"], b["pred_A"])
    assert (b["actual"] - a["actual"]).round().eq(500).all()  # Ist-Preis wird mitgeführt, nicht genutzt


def test_quantiles_never_cross(data):
    _, _, _, walk, _ = data
    q = walk.pred.dropna(subset=["q05", "q95"])
    cols = ["q05", "q10", "q25", "q50", "q75", "q90", "q95"]
    assert len(q) and (q[cols].diff(axis=1).iloc[:, 1:] >= -1e-9).all().all()


def test_plan_handles_daylight_saving_day(data):
    """25.10.: 100 Viertelstunden — die Empfehlung rechnet mit allen, statt abzustürzen."""
    _, frame, wx, walk, last = data
    day = model.predict_day(frame, wx, walk, last)
    long = pd.concat([day, day.iloc[:4]])  # wie ein 25-Stunden-Tag
    rec, kpi = plan.recommend(long, {"name": "t", "mae": 1.0})
    assert len(rec) == 100 and kpi["status"] == "Optimal"


def test_plan_uses_auction_prices_when_known(data):
    _, frame, wx, walk, last = data
    day = model.predict_day(frame, wx, walk, last)
    _, known = plan.recommend(day, {"name": "t", "mae": 1.0})
    assert known["price_basis"] == "Auktion" and "upper_bound_uplift_eur" in known
    _, unknown = plan.recommend(day.assign(actual=np.nan), {"name": "t", "mae": 1.0})
    assert unknown["price_basis"] == "Prognose"
    assert known["upper_bound_uplift_eur"] >= known["expected_uplift_eur"] - 0.5  # Obergrenze ≥ Gebotsplan zu Ist-Preisen
    rec_k, _ = plan.recommend(day, {"name": "t", "mae": 1.0})
    rec_u, _ = plan.recommend(day.assign(actual=np.nan), {"name": "t", "mae": 1.0})
    assert (rec_k["bhkw_mw"] == rec_u["bhkw_mw"]).all()  # Plan hängt nie von den Auktionspreisen ab (Gebot vor 12:00)


def test_forecast_before_auction_when_target_day_has_no_prices(tmp_path):
    """Morgens vor der Auktion: die Historie endet am Vortag — die Prognose für morgen muss trotzdem 96 Werte liefern."""
    last = _write_synthetic(tmp_path)
    h = pd.read_csv(tmp_path / "history.csv")
    day = pd.to_datetime(h["utc"], utc=True).dt.tz_convert("Europe/Berlin").dt.date
    h[day < last].to_csv(tmp_path / "history.csv", index=False)  # Auktion für `last` noch nicht gelaufen
    frame, wx = model.frame(tmp_path, until_day=last)
    walk = model.walk_forward(frame, wx, months=1, until_day=last)
    pred = model.predict_day(frame, wx, walk, last)
    assert len(pred) == 96 and pred["actual"].isna().all() and pred["pred_B"].notna().all()
    _, kpi = plan.recommend(pred, {"name": "t", "mae": 1.0})
    assert kpi["price_basis"] == "Prognose"


def _markets(afrr: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = pd.date_range("2026-04-01", periods=30).strftime("%Y-%m-%d")
    reg = pd.DataFrame({"date": days, "aFRR_pos_eur_mw_h": afrr, "aFRR_neg_eur_mw_h": afrr, "FCR_eur_mw_h": afrr})
    ext = pd.DataFrame({"date": days, "ttf_eur_mwh": 35.0, "eua_eur_t": 75.0})
    return reg, ext


def test_reserve_strategy_ships_reserve_in_the_schedule(data):
    """H-05: „Regelenergie vorhalten“ → der Fahrplan hält die Leistung frei, Kachel = Mehrerlös inkl. Reserve."""
    _, frame, wx, walk, last = data
    day = model.predict_day(frame, wx, walk, last)
    rec, kpi = plan.recommend(day, {"name": "t", "mae": 1.0})
    reg, ext = _markets(200.0)  # Reserve sehr teuer → muss sich lohnen
    dec, rec2, kpi2 = plan.decide(rec, kpi, reg, ext, 10.0)
    assert dec["strategy"] == "REGELENERGIE_RESERVE"
    assert (rec2["reserve_up_mw"] + rec2["reserve_down_mw"]).sum() > 0
    assert (rec2["bhkw_mw"] + rec2["reserve_up_mw"] <= 1.0 + 1e-6).all()  # Reserve nach oben passt in die Leistung
    assert kpi2["expected_uplift_eur"] == round(dec["expected_uplift_eur"], 0)
    assert kpi2["reserve_capacity_eur"] > 0
    cheap, rec3, kpi3 = plan.decide(rec, kpi, *_markets(0.0), 10.0)
    assert cheap["strategy"] != "REGELENERGIE_RESERVE" and rec3 is rec and kpi3 is kpi  # ohne Reserve: Plan unverändert


def test_decision_is_made_before_the_auction(data):
    """Reserve-Auktion D-1 morgens, Spot-Gebot bis 12:00 → Entscheidung und Fahrplan hängen nie von Auktionspreisen ab."""
    _, frame, wx, walk, last = data
    day = model.predict_day(frame, wx, walk, last)
    reg, ext = _markets(200.0)
    known = plan.decide(*plan.recommend(day, {"name": "t", "mae": 1.0}), reg, ext, 10.0)
    unknown = plan.decide(*plan.recommend(day.assign(actual=np.nan), {"name": "t", "mae": 1.0}), reg, ext, 10.0)
    assert known[0]["strategy"] == unknown[0]["strategy"]
    assert (known[1]["bhkw_mw"] == unknown[1]["bhkw_mw"]).all()


def test_backtest_keeps_the_uplift_expected_before_the_auction(data):
    """H-06: je Tag der Mehrerlös, den die Prognose erwarten ließ (vorab bekannt) — Grundlage der EEG-Tagesauswahl."""
    _, _, _, walk, _ = data
    bt, _ = plan.backtest(walk.pred)
    assert "exp_fc" in bt and bt["exp_fc"].notna().all()


def test_regelenergie_keeps_newly_fetched_days(tmp_path, monkeypatch):
    """Inkrementell geholte Tage dürfen nicht verloren gehen.

    Ursache des Fehlers (16.10.): neue Zeilen haben die abgeleitete Spalte aFRR_eur_mw_h noch nicht, dropna() lief vor
    deren Berechnung und warf genau die neuen Tage weg — die Regelenergiepreise blieben auf dem 08.10. stehen."""
    from datetime import timedelta

    from fldos.pipeline import fetch

    today = date.today()
    old_day, new_day = (today - timedelta(days=3)).isoformat(), (today - timedelta(days=2)).isoformat()
    pd.DataFrame({"date": [old_day], "aFRR_eur_mw_h": [10.0], "FCR_eur_mw_h": [20.0],
                  "aFRR_pos_eur_mw_h": [11.0], "aFRR_neg_eur_mw_h": [9.0]}).to_csv(tmp_path / "regelenergie.csv", index=False)
    fake = {new_day: {"date": new_day, "aFRR_pos_eur_mw_h": 14.0, "aFRR_neg_eur_mw_h": 8.0, "FCR_eur_mw_h": 18.0}}
    monkeypatch.setattr(fetch, "_regel_day", lambda d: fake.get(d))

    assert fetch.regelenergie(tmp_path, days=5) == 1
    out = pd.read_csv(tmp_path / "regelenergie.csv").set_index("date")
    assert list(out.index) == [old_day, new_day]
    assert out.loc[new_day, "aFRR_eur_mw_h"] == pytest.approx(11.0)  # Mittel aus pos/neg


def _yahoo(closes: dict[str, float]) -> dict:
    ts = [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in closes]
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": list(closes.values())}]}}]}}


def test_external_holt_oel_und_wechselkurs_fuer_den_preisrechner(tmp_path, monkeypatch):
    import urllib.error

    from fldos.pipeline import fetch

    data = {"TTF%3DF": {"2026-10-15": 86.0, "2026-10-16": 86.4}, "BZ%3DF": {"2026-10-15": 109.0, "2026-10-16": 109.9},
            "EURUSD%3DX": {"2026-10-16": 1.124}}
    monkeypatch.setattr(fetch, "_json", lambda url, params=None: _yahoo(next(v for k, v in data.items() if k in url)))
    monkeypatch.setattr(fetch, "_get", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("eex", 404, "x", None, None)))
    fetch.external(tmp_path)
    out = pd.read_csv(tmp_path / "external_market.csv").set_index("date")
    assert out.loc["2026-10-16", "brent_usd_bbl"] == 109.9
    assert out.loc["2026-10-16", "eurusd"] == 1.124
    assert out.loc["2026-10-16", "ttf_eur_mwh"] == 86.4


def test_external_ohne_oeldaten_bleibt_gas_erhalten(tmp_path, monkeypatch):
    import urllib.error

    from fldos.pipeline import fetch

    def fake(url, params=None):
        if "TTF" in url:
            return _yahoo({"2026-10-16": 86.4})
        raise urllib.error.URLError("nodename nor servname provided")  # Öl/Wechselkurs nicht erreichbar

    monkeypatch.setattr(fetch, "_json", fake)
    monkeypatch.setattr(fetch, "_get", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("eex", 404, "x", None, None)))
    fetch.external(tmp_path)
    out = pd.read_csv(tmp_path / "external_market.csv")
    assert out["ttf_eur_mwh"].tolist() == [86.4]
    assert out["brent_usd_bbl"].isna().all() and out["eurusd"].isna().all()  # keine Schätzung, Preisrechner zeigt „keine Daten“


def test_tageskette_wartet_auf_netz_nach_dem_aufwachen():
    """17.10. 09:38: Lauf startete in einem 10-s-Wartungs-Aufwachen ohne WLAN → DNS-Fehler → Abbruch. Jetzt: warten."""
    import socket

    from fldos.pipeline import fetch

    clock = {"t": 0.0}
    calls = []

    def resolve(host, port):
        calls.append(host)
        if len(calls) < 3:
            raise socket.gaierror(8, "nodename nor servname provided, or not known")

    def sleep(s):
        clock["t"] += s

    waited = fetch.wait_for_network(resolve=resolve, sleep=sleep, now=lambda: clock["t"], step_s=30)
    assert waited == 60 and len(calls) == 3


def test_tageskette_gibt_nach_frist_ohne_netz_auf():
    import socket

    from fldos.pipeline import fetch

    clock = {"t": 0.0}

    def resolve(host, port):
        raise socket.gaierror(8, "nodename nor servname provided, or not known")

    def sleep(s):
        clock["t"] += s

    with pytest.raises(ConnectionError, match="kein Netz"):
        fetch.wait_for_network(resolve=resolve, sleep=sleep, now=lambda: clock["t"], max_wait_s=300, step_s=30)
    assert clock["t"] == 300


def test_terminkurve_gas_und_oel_je_monat(tmp_path, monkeypatch):
    from datetime import date as _date

    from fldos.pipeline import fetch

    seen = []

    def fake(url, params=None):
        seen.append(url)
        if "TTFX26" in url:
            return _yahoo({"2026-10-16": 87.55})
        if "BZX26" in url or "BZZ26" in url:
            return _yahoo({"2026-10-16": 109.86})
        raise urllib.error.HTTPError(url, 404, "No data found", None, None)  # Monat nicht gelistet → überspringen

    import urllib.error
    monkeypatch.setattr(fetch, "_json", fake)
    n = fetch.forward_curve(tmp_path, today=_date(2026, 10, 17), months=3)
    out = pd.read_csv(tmp_path / "forward_curve.csv")
    assert out["month"].tolist() == ["2026-11", "2026-12", "2027-01"]  # ab dem nächsten Liefermonat
    assert out.loc[0, "ttf_eur_mwh"] == 87.55 and pd.isna(out.loc[1, "ttf_eur_mwh"])
    assert out.loc[1, "brent_usd_bbl"] == 109.86
    assert n == 3 and any("TTFF27.NYM" in u for u in seen) and any("BZF27.NYM" in u for u in seen)
