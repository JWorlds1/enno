"""Abruf der offenen Marktdaten für die Tageskette. Jede Quelle schreibt eine CSV nach data_dir.

Quellen (alle frei, ENTSO-E mit Token):
  Energy-Charts  Day-Ahead-Preis DE-LU (15 min, inkl. morgen nach der Auktion), Erzeugung + Last
  SMARD          Preis-Fallback (Bundesnetzagentur), falls Energy-Charts Lücken hat
  Open-Meteo     Wetterprognosen Wind/Sonne/Temperatur für Wind- und Solarregionen; für die Vergangenheit
                 das Archiv der damals gültigen Vorhersagen → Backtest ohne Blick in die Zukunft
  ENTSO-E        Last- und Wind/Solar-Prognosen der Netzbetreiber (Vergleich; Wind/Solar erst nach der Auktion)
  Yahoo / EEX    Gas (TTF, €/MWh) / CO₂ (EUA-Auktionspreis, €/t)
  regelleistung  aFRR (mengengewichteter Mittelwert angenommener Gebote, pos/neg) und FCR (Abrechnungspreis)
"""
from __future__ import annotations

import http.client
import io
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

UA = {"User-Agent": "fld-os/1.0"}
EC = "https://api.energy-charts.info"
SMARD_IDX = "https://www.smard.de/app/chart_data/4169/DE/index_quarterhour.json"
SMARD_DAT = "https://www.smard.de/app/chart_data/4169/DE/4169_DE_quarterhour_{ts}.json"
OM_FC = "https://api.open-meteo.com/v1/forecast"
OM_HIST = "https://historical-forecast-api.open-meteo.com/v1/forecast"  # erste Stunden jedes Laufs ≈ Ist-Wetter
OM_PREV = "https://previous-runs-api.open-meteo.com/v1/forecast"  # Vorhersage vom Vortag (Lauf ~24 h vorher)
PREV_START = "2024-01-01"  # ab hier Vortagsvorhersagen (Wind ab ~03/2024); davor nur Trainingsdaten
WX_VERSION = 2  # 2 = Vergangenheit mit Vorlaufzeit wie im Betrieb (Review H-01); ältere wetter.csv wird neu geladen
ENTSOE = "https://web-api.tp.entsoe.eu/api"
DE_LU = "10Y1001A1001A82H"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={p1}&period2={p2}&interval=1d"
EEX = "https://public.eex-group.com/eex/eua-auction-report/emission-spot-primary-market-auction-report-{yr}-data.xlsx"
REGEL = ("https://www.regelleistung.net/apps/cpp-publisher/api/v1/download/tenders/anonymousresults"
         "?date={d}&exportFormat=xlsx&market=CAPACITY&productTypes={pt}")

HISTORY_COLS = ["utc", "unix", "da_price_eur_mwh", "load_mw", "residual_load_mw", "solar_mw", "wind_onshore_mw",
                "wind_offshore_mw", "biomass_mw", "ren_share_load_pct", "temp_c", "wind_ms", "solar_kwh_m2", "cloud_pct"]
POWER = {"Solar": "solar_mw", "Wind onshore": "wind_onshore_mw", "Wind offshore": "wind_offshore_mw",
         "Biomass": "biomass_mw", "Load": "load_mw", "Residual load": "residual_load_mw",
         "Renewable share of load": "ren_share_load_pct"}
# Wetterpunkte: wo Deutschlands Wind- und Solarleistung steht (grob nach installierter Leistung gewählt).
WIND_PTS = {"nordsee": (54.5, 6.5), "sh": (54.4, 9.5), "nds": (53.0, 8.2), "bb": (52.6, 13.6), "st": (51.9, 11.6)}
SUN_PTS = {"by": (48.6, 11.5), "bw": (48.6, 9.1), "nrw": (51.5, 7.5), "nds": (52.4, 9.7)}
WX_START = "2023-06-01"


def _get(url: str, params: dict | None = None, tries: int = 4, timeout: int = 60) -> bytes:
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404) or k == tries - 1:
                raise
            time.sleep(5 * (k + 1) if e.code == 429 else 2 * (k + 1))
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, ConnectionError, OSError):
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))
    raise RuntimeError("unreachable")


def wait_for_network(host: str = "api.energy-charts.info", max_wait_s: int = 5400, step_s: int = 30, *,
                     resolve=socket.getaddrinfo, sleep=time.sleep, now=time.time) -> int:
    """Wartet, bis `host` per DNS auflösbar ist; → Wartezeit in s, ConnectionError nach `max_wait_s` (Uhrzeit).

    Ursache 17.10. 09:38: launchd holte den verpassten 09:30-Lauf in einem 10-s-Wartungs-Aufwachen nach (Deckel zu,
    Akku), ohne WLAN → DNS-Fehler, die 4 Versuche von _get (~12 s) überbrückten das nicht. Schläft der Mac beim
    Warten wieder ein, ruht der Prozess und macht beim nächsten Aufwachen weiter — daher Frist nach Uhrzeit."""
    start = now()
    while True:
        try:
            resolve(host, 443)
            return int(now() - start)
        except OSError as e:  # socket.gaierror ist ein OSError
            if now() - start >= max_wait_s:
                raise ConnectionError(f"kein Netz: {host} nach {max_wait_s // 60} min nicht auflösbar ({e})") from e
            sleep(step_s)


def _json(url: str, params: dict | None = None) -> dict:
    return json.loads(_get(url, params))


def _write(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")  # je Prozess eigene Temp-Datei (zwei Läufe überschrieben sich)
    df.to_csv(tmp, index=False)
    tmp.replace(path)  # atomar: die laufende API liest nie eine halbe Datei


# ── Preis + Erzeugung ────────────────────────────────────────────────────────
def history(data_dir: Path, until: date) -> int:
    """history.csv bis einschließlich `until` (UTC-Tag) fortschreiben. → neue Zeilen."""
    path = data_dir / "history.csv"
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=HISTORY_COLS)
    last = int(old["unix"].max()) if len(old) else int(pd.Timestamp(WX_START, tz="UTC").timestamp())
    start = datetime.fromtimestamp(last, timezone.utc).date() - timedelta(days=1)
    rows: dict[int, dict] = {}
    day = start
    while day <= until:
        end = min(day + timedelta(days=14), until + timedelta(days=1))
        s, e = day.isoformat(), end.isoformat()
        price = _json(f"{EC}/price", {"bzn": "DE-LU", "start": s, "end": e})
        for ts, p in zip(price["unix_seconds"], price["price"]):
            rows.setdefault(ts, {})["da_price_eur_mwh"] = p
        power = _json(f"{EC}/public_power", {"country": "de", "start": s, "end": e})
        types = {t["name"]: t["data"] for t in power["production_types"]}
        for i, ts in enumerate(power["unix_seconds"]):
            r = rows.setdefault(ts, {})
            for name, col in POWER.items():
                v = types.get(name)
                r[col] = v[i] if v and i < len(v) else None
        day = end
        time.sleep(0.5)
    new = pd.DataFrame.from_dict(rows, orient="index").rename_axis("unix").reset_index()
    new = new[new["unix"] % 900 == 0]  # nur Viertelstunden-Raster
    new["utc"] = pd.to_datetime(new["unix"], unit="s", utc=True).map(lambda t: t.isoformat())
    _fill_price_from_smard(new)
    merged = (pd.concat([old[~old["unix"].isin(new["unix"])], new.reindex(columns=HISTORY_COLS)])
              .sort_values("unix").reset_index(drop=True))
    _write(merged[HISTORY_COLS], path)
    return int((~new["unix"].isin(old["unix"])).sum())


def _fill_price_from_smard(df: pd.DataFrame) -> None:
    gap = df["da_price_eur_mwh"].isna()
    if not gap.any():
        return
    lo = int(df.loc[gap, "unix"].min()) - 8 * 86400
    pmap: dict[int, float] = {}
    for w in (w for w in _json(SMARD_IDX)["timestamps"] if w / 1000 >= lo):
        for ms, v in _json(SMARD_DAT.format(ts=w))["series"]:
            if v is not None:
                pmap[ms // 1000] = v
    df.loc[gap, "da_price_eur_mwh"] = df.loc[gap, "unix"].map(pmap)


# ── Wetterprognosen (Open-Meteo) ─────────────────────────────────────────────
def weather(data_dir: Path, until: date) -> int:
    """wetter.csv: stündliche Vorhersagen je Region, für jede Stunde mit der Vorlaufzeit wie im Betrieb.

    Vergangenheit = Vorhersage vom Vortag (Previous-Runs-API, „previous_day1“): um 09:30 für morgen liegen 15–38 h
    zwischen Vorhersage und Lieferung — so misst der Backtest, was im Betrieb erreichbar ist. Die Historical-Forecast-API
    setzt dagegen die ersten Stunden jedes Laufs zusammen (≈ Ist-Wetter) und füllt nur Lücken davor (vor 2024: nur
    Training, nie im Prüfjahr). Zukunft = jüngster Lauf der Forecast-API."""
    path = data_dir / "wetter.csv"
    meta = data_dir / "wetter.meta.json"
    fresh = not meta.exists() or json.loads(meta.read_text()).get("version") != WX_VERSION
    old = None if fresh or not path.exists() else pd.read_csv(path, parse_dates=["utc"])
    now = pd.Timestamp.now(tz="UTC").floor("h")
    today = now.date()
    start = (old["utc"].max().date() - timedelta(days=3)) if old is not None and len(old) else date.fromisoformat(WX_START)
    past = []
    y0 = start
    while y0 <= today:
        y1 = min(date(y0.year + 1, 1, 1) - timedelta(days=1), today)
        span = {"start_date": y0.isoformat(), "end_date": y1.isoformat()}
        hist = _om(OM_HIST, {**span, "end_date": min(y1, today - timedelta(days=2)).isoformat()}) if y0 <= today - timedelta(days=2) else None
        prev = _om(OM_PREV, span, suffix="_previous_day1") if y1 >= date.fromisoformat(PREV_START) else None
        if prev is None:
            past.append(hist)
        else:  # Vortagsvorhersage, wo vorhanden; Lücken (z. B. Wind vor 03/2024) aus dem Archiv
            prev = prev.set_index("utc")
            past.append((prev.combine_first(hist.set_index("utc")) if hist is not None else prev).reset_index())
        y0 = y1 + timedelta(days=1)
    fc = _om(OM_FC, {"past_days": 0, "forecast_days": max(2, (until - today).days + 1)})
    past_df = pd.concat(past)
    # vergangene Stunden: Vortagsvorhersage; ab jetzt: jüngster Lauf (das, was der Betrieb um 09:30 sieht)
    new = pd.concat([past_df[past_df["utc"] < now], fc[fc["utc"] >= now]]).drop_duplicates("utc", keep="last")
    new = new.dropna(how="all", subset=[c for c in new.columns if c != "utc"])
    merged = new if old is None else pd.concat([old[~old["utc"].isin(new["utc"])], new])
    merged = merged.sort_values("utc").reset_index(drop=True)
    _write(merged, path)
    meta.write_text(json.dumps({"version": WX_VERSION, "past": "previous_day1 ab " + PREV_START, "future": "forecast"}))
    return len(new)


def _om(url: str, span: dict, suffix: str = "") -> pd.DataFrame:
    pts = [(f"wind_{k}", v) for k, v in WIND_PTS.items()] + [(f"sun_{k}", v) for k, v in SUN_PTS.items()]
    var = ("wind_speed_100m", "shortwave_radiation", "temperature_2m")
    d = _json(url, {"latitude": ",".join(str(p[1][0]) for p in pts), "longitude": ",".join(str(p[1][1]) for p in pts),
                    "hourly": ",".join(v + suffix for v in var), "timezone": "UTC", **span})
    d = d if isinstance(d, list) else [d]
    out = pd.DataFrame({"utc": pd.to_datetime(d[0]["hourly"]["time"], utc=True)})
    for (name, _), loc in zip(pts, d):
        h = loc["hourly"]
        if name.startswith("wind_"):
            out[name] = pd.to_numeric(pd.Series(h["wind_speed_100m" + suffix]), errors="coerce").to_numpy()
        else:
            out[name] = pd.to_numeric(pd.Series(h["shortwave_radiation" + suffix]), errors="coerce").to_numpy()
            out[f"temp_{name[4:]}"] = pd.to_numeric(pd.Series(h["temperature_2m" + suffix]), errors="coerce").to_numpy()
    return out


# ── ENTSO-E (Netzbetreiber-Prognosen) ────────────────────────────────────────
def entsoe(data_dir: Path, until: date, token: str | None) -> int:
    """entsoe_forecasts.csv fortschreiben: Lastprognose A65 + Wind/Solar A69. Ohne Token: übersprungen."""
    if not token:
        return 0
    path = data_dir / "entsoe_forecasts.csv"
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["utc", "unix"])
    start = (pd.to_datetime(old["utc"].max(), utc=True) - pd.Timedelta(days=2)) if len(old) else pd.Timestamp(WX_START, tz="UTC")
    stop = pd.Timestamp(until + timedelta(days=1), tz="UTC")
    rows: dict = {}
    a = start.normalize()
    while a < stop:
        b = min(a + pd.Timedelta(days=31), stop)
        span = {"periodStart": a.strftime("%Y%m%d%H%M"), "periodEnd": b.strftime("%Y%m%d%H%M"), "securityToken": token}
        for ts, _, v in _entsoe_points({"documentType": "A65", "processType": "A01", "outBiddingZone_Domain": DE_LU, **span}):
            rows.setdefault(ts, {})["load_fc_mw"] = v
        for ts, psr, v in _entsoe_points({"documentType": "A69", "processType": "A01", "in_Domain": DE_LU, **span}):
            col = {"B16": "solar_fc_mw", "B18": "wind_off_fc_mw", "B19": "wind_on_fc_mw"}.get(psr)
            if col:
                rows.setdefault(ts, {})[col] = v
        a = b
    if not rows:
        return 0
    new = pd.DataFrame.from_dict(rows, orient="index").rename_axis("ts").reset_index()
    new["unix"] = new["ts"].map(lambda t: int(t.timestamp()))
    new["utc"] = new["ts"].map(lambda t: t.isoformat())
    new = new.drop(columns="ts")
    merged = pd.concat([old[~old["unix"].isin(new["unix"])], new]).sort_values("unix").reset_index(drop=True)
    _write(merged[["utc", "unix", "load_fc_mw", "solar_fc_mw", "wind_on_fc_mw", "wind_off_fc_mw"]], path)
    return len(new)


def _entsoe_points(params: dict):
    try:
        xml = _get(ENTSOE, params, timeout=90)
    except urllib.error.HTTPError as e:
        if e.code == 400:  # keine Daten für das Fenster
            return
        raise
    root = ET.fromstring(xml)
    ns = {"n": root.tag.split("}")[0].strip("{")}
    for ts in root.findall(".//n:TimeSeries", ns):
        psr = ts.find(".//n:MktPSRType/n:psrType", ns)
        for per in ts.findall("n:Period", ns):
            t0 = datetime.fromisoformat(per.find("n:timeInterval/n:start", ns).text.replace("Z", "+00:00"))
            res = per.find("n:resolution", ns).text
            step = 15 if "15" in res else 60 if "60" in res else 30
            for pt in per.findall("n:Point", ns):
                pos = int(pt.find("n:position", ns).text)
                yield t0 + timedelta(minutes=step * (pos - 1)), (psr.text if psr is not None else None), float(pt.find("n:quantity", ns).text)


# ── Gas + CO₂ ────────────────────────────────────────────────────────────────
def _yahoo(ticker: str, p1: int, digits: int = 2) -> dict[date, float]:
    d = _json(YAHOO.format(tk=urllib.parse.quote(ticker), p1=p1, p2=int(time.time())))["chart"]["result"][0]
    return {datetime.fromtimestamp(t, timezone.utc).date(): round(c, digits)
            for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"]) if c is not None}


def external(data_dir: Path) -> int:
    """external_market.csv: TTF (Yahoo, Front-Month) + EUA-Primärauktionspreis (EEX), für den Preisrechner Brent und
    EUR/USD (Yahoo). Täglich, vorwärts gefüllt. Öl/Wechselkurs sind weich: fehlen sie, bleibt die Spalte leer und
    der Preisrechner zeigt für Industrieruß „keine Daten“ statt einer Schätzung."""
    p1 = int(pd.Timestamp(WX_START, tz="UTC").timestamp())
    gas = _yahoo("TTF=F", p1)
    soft: dict[str, dict[date, float]] = {}
    for col, tk, digits in (("brent_usd_bbl", "BZ=F", 2), ("eurusd", "EURUSD=X", 4)):
        try:
            soft[col] = _yahoo(tk, p1, digits)
        except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as e:
            print(f"  ! {tk} nicht verfügbar ({e}) — Industrieruß-Wert bleibt leer", flush=True)
            soft[col] = {}
    co2: dict[date, float] = {}
    for yr in range(int(WX_START[:4]), date.today().year + 1):
        try:
            df = pd.read_excel(io.BytesIO(_get(EEX.format(yr=yr))), header=5)[["Date", "Auction Price €/tCO2"]].dropna()
        except (urllib.error.HTTPError, KeyError, ValueError):
            continue  # Jahresbericht fehlt / Format geändert — Vorjahre bleiben
        co2.update({pd.to_datetime(r.Date).date(): round(float(r[1]), 2) for r in df.itertuples(index=False)})
    days = sorted(set(gas) | set(co2))
    out = pd.DataFrame({"date": [x.isoformat() for x in days],
                        "ttf_eur_mwh": [gas.get(x) for x in days], "eua_eur_t": [co2.get(x) for x in days],
                        **{col: [v.get(x) for x in days] for col, v in soft.items()}}).ffill()
    _write(out, data_dir / "external_market.csv")
    return len(out)


_MONTH_CODES = "FGHJKMNQUVXZ"  # Jan … Dez (Börsen-Kürzel der Liefermonate)


def forward_curve(data_dir: Path, today: date | None = None, months: int = 12, pause: float = 0.2) -> int:
    """forward_curve.csv: Terminpreise je Liefermonat (ab dem nächsten) — Gas TTF und Öl Brent (Yahoo, Kontrakte
    TTF<M><JJ>.NYM / BZ<M><JJ>.NYM), letzter Schlusskurs. Nicht gelistete Monate bleiben leer (keine Schätzung).
    CO₂ und EUR/USD haben keine freien Monatskontrakte: der Preisrechner hält sie auf dem heutigen Wert."""
    today = today or date.today()
    p1 = int(time.time()) - 10 * 86400
    rows = []
    for k in range(1, months + 1):
        y, m = divmod(today.month - 1 + k, 12)
        yy, mm = today.year + y, m + 1
        code = f"{_MONTH_CODES[m]}{yy % 100:02d}"
        row: dict = {"month": f"{yy}-{mm:02d}"}
        for col, tk in (("ttf_eur_mwh", f"TTF{code}.NYM"), ("brent_usd_bbl", f"BZ{code}.NYM")):
            try:
                closes = _yahoo(tk, p1)
                row[col] = closes[max(closes)] if closes else None
            except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError):
                row[col] = None
            time.sleep(pause)
        rows.append(row)
    _write(pd.DataFrame(rows, columns=["month", "ttf_eur_mwh", "brent_usd_bbl"]), data_dir / "forward_curve.csv")
    return len(rows)


# ── Regelenergie ─────────────────────────────────────────────────────────────
def regelenergie(data_dir: Path, days: int = 90) -> int:
    """regelenergie.csv: die letzten `days` veröffentlichten Tage (Veröffentlichung ~2 Tage verzögert), inkrementell.

    aFRR ist pay-as-bid → der realistische Erlös ist der mengengewichtete Mittelwert der angenommenen Gebote
    (nicht das Höchstgebot), getrennt nach positiv/negativ. FCR ist pay-as-cleared → Abrechnungspreis/4 h.
    regelleistung.net braucht ~35 s je Tag → nur fehlende Tage holen, 4 parallel."""
    from concurrent.futures import ThreadPoolExecutor

    path = data_dir / "regelenergie.csv"
    want = [(date.today() - timedelta(days=k)).isoformat() for k in range(2, days + 2)]
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if "aFRR_pos_eur_mw_h" not in old:  # alte Methode (Höchstgebot) → neu rechnen
        old = pd.DataFrame()
    have = set(old["date"]) if len(old) else set()
    with ThreadPoolExecutor(4) as ex:
        new = [r for r in ex.map(_regel_day, [d for d in want if d not in have]) if r]
    out = pd.concat([old, pd.DataFrame(new)]) if new else old
    # abgeleitete Spalte VOR dropna: neue Zeilen haben sie noch nicht und flögen sonst raus (Preise blieben stehen)
    out["aFRR_eur_mw_h"] = (out["aFRR_pos_eur_mw_h"] + out["aFRR_neg_eur_mw_h"]) / 2  # Kompatibilität (Mittel pos/neg)
    out = out[out["date"].isin(want)].dropna().drop_duplicates("date").sort_values("date")
    _write(out[["date", "aFRR_eur_mw_h", "FCR_eur_mw_h", "aFRR_pos_eur_mw_h", "aFRR_neg_eur_mw_h"]], path)
    return len(new)


def _regel_day(d: str) -> dict | None:
    rec: dict = {"date": d}
    try:
        a = pd.read_excel(io.BytesIO(_get(REGEL.format(d=d, pt="aFRR"), timeout=120)))
        a = a[(a["COUNTRY"] == "DE") & (a["ALLOCATED_CAPACITY_[MW]"] > 0)]
        for side in ("POS", "NEG"):
            s = a[a["PRODUCT"].str.startswith(side)]
            w = s["ALLOCATED_CAPACITY_[MW]"]
            rec[f"aFRR_{side.lower()}_eur_mw_h"] = float(np.average(s["CAPACITY_PRICE_[(EUR/MW)/h]"], weights=w)) if w.sum() else None
        f = pd.read_excel(io.BytesIO(_get(REGEL.format(d=d, pt="FCR"), timeout=120)))
        f = f[(f["COUNTRY"] == "DE") & (f["ALLOCATED_CAPACITY_[MW]"] > 0)]
        rec["FCR_eur_mw_h"] = float(f.groupby("PRODUCT")["SETTLEMENTCAPACITY_PRICE_[EUR/MW]"].max().mean() / 4.0)
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return None  # Tag noch nicht veröffentlicht, Verbindung abgebrochen oder Format geändert
    return rec


def entsoe_token() -> str | None:
    return os.environ.get("ENTSOE_TOKEN") or None
