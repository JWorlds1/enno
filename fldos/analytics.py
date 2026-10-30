"""Analyse-Module der Plattform — bindet die Engine an: Risiko (mean-CVaR), Pareto Erlös↔CO₂,
Erlös-Stapel (Co-Optimierung), Plasma vs. Elektrolyse, Prognoseband (CQR/ACI), MPC-Speicher,
Sensitivität (Tornado).

Reine, synchrone Funktionen über den Daten in DATA_DIR. Die API ruft sie per to_thread und
cached nach (Parameter, Datei-mtime).
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

import backtest_forecast as bf
import coopt_milp
import mpc
import pareto_milp
import plasma_milp
import scenarios
import stochastic_cvar
import whatif
from config import PLANT, PlantConfig

from . import eeg
from .settings import DATA_DIR

FORECASTS = DATA_DIR / "forecasts.csv"
HISTORY = DATA_DIR / "history.csv"
QUANTILES = DATA_DIR / "quantiles.csv"
REGEL = DATA_DIR / "regelenergie.csv"
EXTERNAL = DATA_DIR / "external_market.csv"

# Defaults an EINER Stelle: Endpoints, Warm-up und Enno müssen denselben Cache-Schlüssel treffen.
DEF_BAND_DAYS, DEF_STACK_DAYS, DEF_PLASMA_DAYS, DEF_MPC_DAYS = 7, 7, 10, 14

_memo: dict = {}
_memo_locks: dict = {}
_memo_locks_guard = threading.Lock()


def cached(name: str, fn, *args, key_extra=None, **kwargs):
    """Ergebnis-Cache je (Analyse, Parameter inkl. Anlage, Daten-mtime) — die MILP-Läufe dauern Sekunden.

    Aufrufer übergeben die Anlage immer als plant=… (auch die Standard-Anlage), damit Warm-up,
    Endpoints und Enno denselben Schlüssel treffen."""
    mtime = max((p.stat().st_mtime for p in DATA_DIR.glob("*.csv")), default=0.0)
    key = (name, tuple(tuple(a) if isinstance(a, list) else a for a in args), tuple(sorted(kwargs.items())), key_extra, mtime)
    # Je Schlüssel ein Lock: Warm-up und erste Anfrage rechnen dieselbe Analyse nicht doppelt.
    with _memo_locks_guard:
        lock = _memo_locks.setdefault(key, threading.Lock())
    with lock:
        if key not in _memo:
            _memo[key] = fn(*args, **kwargs)
    return _memo[key]


def _forecast_days() -> tuple[pd.DataFrame, list]:
    """Prognose-/Ist-Preise je Liefertag (Marktzeit Europe/Berlin), nur vollständige 96-Slot-Tage mit Ist-Preisen."""
    fc = pd.read_csv(FORECASTS, parse_dates=["utc"])
    fc["day"] = fc["utc"].dt.tz_convert("Europe/Berlin").dt.date
    days = [d for d, g in fc.groupby("day") if len(g) == bf.NS and g[["actual", "pred_B"]].notna().all().all()]
    return fc.set_index("day"), days


def _r(x: float, dp: int = 1) -> float:
    return round(float(x), dp)


# ── Risiko: mean-CVaR-Effizienzfront + Wert der Stochastik ──────────────────
def risk(n_scen: int = 12, lambdas: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 0.95), plant: PlantConfig = PLANT) -> dict:
    g, days = _forecast_days()
    d = days[-1]
    point = g.loc[d, "pred_B"].tolist()
    pool = scenarios.residual_pool(g["actual"], g["pred_B"])
    scen = scenarios.make_scenarios(point, pool, n_scen, block=8)
    def solve(scen, **kw):
        return stochastic_cvar.solve(scen, plant=plant, **kw)
    rp = solve(scen, lam=0.0)[0]
    on_ev = solve([np.asarray(point)], lam=0.0)[1]
    eev = solve(scen, lam=0.0, fixed_on=on_ev)[0]
    ws = solve(scen, lam=0.0, ws=True)[0]
    frontier = []
    for lam in lambdas:
        ep, onv, cv = solve(scen, lam=lam)
        frontier.append({"lam": lam, "expected": _r(ep), "cvar": _r(cv), "bhkw_h": _r(sum(onv) * plant.dt_h, 2)})
    return {
        "day": str(d), "scenarios": n_scen, "alpha": stochastic_cvar.ALPHA,
        "rp": _r(rp), "eev": _r(eev), "ws": _r(ws), "vss": _r(rp - eev), "evpi": _r(ws - rp),
        "frontier": frontier,
    }


# ── Mehrwert: was der Prognose-Fahrplan im Backtest gegenüber Dauerbetrieb gebracht hat ──────────
def value_summary(rows) -> dict | None:
    """Aus Backtest-Zeilen (flat, up_fc, up_pf, day): Mehrerlös gesamt, je Tag, je Jahr, in % und Treffsicherheit.

    Eine Quelle für Cockpit und Enno. Fahrplan auf der Prognose geplant, zu Ist-Preisen abgerechnet."""
    ok = [r for r in rows if r.flat is not None and r.up_fc is not None and r.up_pf is not None]
    if not ok:
        return None
    n = len(ok)
    up, flat, pf = sum(r.up_fc for r in ok), sum(r.flat for r in ok), sum(r.up_pf for r in ok)
    return {"days": n, "from_day": min(r.day for r in ok), "to_day": max(r.day for r in ok),
            "uplift_eur": _r(up, 0), "per_day_eur": _r(up / n, 0), "per_year_eur": _r(up / n * 365, 0),
            "pct_vs_flat": _r(up / flat * 100) if flat else None, "capture_pct": _r(up / pf * 100) if pf > 0 else None}


# ── Pareto: Erlös ↔ CO₂-Einsparung (ε-constraint) ───────────────────────────
def pareto(points: int = 6, plant: PlantConfig = PLANT) -> dict:
    g, days = _forecast_days()
    hist = pd.read_csv(HISTORY, usecols=["utc", "ren_share_load_pct"], parse_dates=["utc"])
    hist["day"] = hist["utc"].dt.tz_convert("Europe/Berlin").dt.date
    hcount = hist.dropna(subset=["ren_share_load_pct"]).groupby("day").size()
    d = next(dd for dd in reversed(days) if hcount.get(dd, 0) == bf.NS)
    price = g.loc[d, "actual"].tolist()
    share = hist.set_index("day").loc[d, "ren_share_load_pct"].clip(0, 100)
    inten = (plant.grid_co2_max_t_mwh * (1 - share / 100)).tolist()
    ext = pd.read_csv(EXTERNAL).dropna()
    gas_cost = float(ext.iloc[-1]["ttf_eur_mwh"]) + plant.bio_premium_eur_mwh
    eua = float(ext.iloc[-1]["eua_eur_t"])

    _, c_lo, _ = pareto_milp.solve(price, inten, gas_cost, plant=plant)
    c_hi = pareto_milp.solve_co2max(price, inten, gas_cost, plant=plant)
    front = []
    for floor in np.linspace(c_lo, c_hi, points):
        pr, co, st = pareto_milp.solve(price, inten, gas_cost, co2_floor=float(floor), plant=plant)
        if st == "Optimal":
            front.append({"co2_t": _r(co, 3), "profit": _r(pr)})
    slope = None
    if len(front) >= 2 and front[-1]["co2_t"] > front[0]["co2_t"]:
        slope = _r((front[0]["profit"] - front[-1]["profit"]) / (front[-1]["co2_t"] - front[0]["co2_t"]))
    return {"day": str(d), "gas_cost": _r(gas_cost), "eua": _r(eua), "front": front,
            "slope_eur_t": slope, "cheaper_than_eua": slope is not None and slope < eua}


# ── Erlös-Stapel: Spot/Wärme/PtX vs. Regelenergie (Co-Optimierung) ──────────
def revenue_stack(n_days: int = 7, plant: PlantConfig = PLANT) -> dict:
    g, days = _forecast_days()
    reg = pd.read_csv(REGEL).sort_values("date").tail(30)  # Preisniveau der letzten 30 Tage, wie die Tagesentscheidung
    fcr = float(reg.FCR_eur_mw_h.mean())
    if "aFRR_pos_eur_mw_h" in reg:  # pay-as-bid, mengengewichtet, positiv/negativ getrennt
        afrr, afrr_neg = float(reg.aFRR_pos_eur_mw_h.mean()), float(reg.aFRR_neg_eur_mw_h.mean())
    else:
        afrr = afrr_neg = float(reg.aFRR_eur_mw_h.mean())
    rows = []
    for d in days[-n_days:]:
        pr = g.loc[d, "actual"].tolist()
        so = coopt_milp.optimise(pr, afrr, fcr, allow_reserve=False, plant=plant, afrr_neg=afrr_neg)[0]
        co, cap, mw, _ = coopt_milp.optimise(pr, afrr, fcr, allow_reserve=True, plant=plant, afrr_neg=afrr_neg)
        # co = Energie-Erlös (nach Umdisponieren) + Kapazitätserlös
        rows.append({"day": str(d), "spot_only": _r(so), "coopt": _r(co), "energy": _r(co - cap),
                     "capacity": _r(cap), "uplift": _r(co - so), "reserve_mw": _r(mw, 2)})
    n = len(rows) or 1
    avg_up = sum(r["uplift"] for r in rows) / n
    return {"afrr": _r(afrr), "afrr_neg": _r(afrr_neg), "fcr": _r(fcr), "rows": rows,
            "avg_uplift": _r(avg_up), "uplift_per_mw_year": _r(avg_up * 365, 0)}


# ── Plasma-Pyrolyse vs. Elektrolyse vs. nur Strom ───────────────────────────
def plasma_compare(n_days: int = 10, plant: PlantConfig = PLANT) -> dict:
    g, days = _forecast_days()
    rows = []
    for d in days[-n_days:]:
        pr = g.loc[d, "actual"].tolist()
        res = {mode: plasma_milp.solve(pr, mode, plant=plant) for mode in ("power", "electro", "pyro")}
        _, gas_pyro, h2, carbon = res["pyro"]
        rows.append({"day": str(d), "power": _r(res["power"][0]), "electro": _r(res["electro"][0]),
                     "pyro": _r(res["pyro"][0]), "gas_pyro_mwh": _r(gas_pyro, 2),
                     "h2_mwh": _r(h2, 2), "carbon_t": _r(carbon, 3)})
    n = len(rows) or 1
    avg = {k: _r(sum(r[k] for r in rows) / n) for k in ("power", "electro", "pyro")}
    return {"rows": rows, "avg": avg,
            "uplift_electro": _r(avg["electro"] - avg["power"]), "uplift_pyro": _r(avg["pyro"] - avg["power"]),
            "carbon_credit_eur_t": plasma_milp.CARBON_CREDIT_EUR_T}


# ── Splitter über 12 Monate: Plan auf der damaligen Prognose, Abrechnung auf Ist ─────────────
def _split_settle(fc: list[float], act: list[float], band: tuple, h2: float, c: float, plant: PlantConfig,
                  margin: float, block: int | None = None) -> tuple[dict, dict, dict]:
    """Ein Liefertag: Plan auf der Prognose (Sicherheitsabstand, Mindestlaufzeit, Band — oder nach der Auktion der
    Stundenblock), abgerechnet auf Ist; dazu das Bestmögliche (Ist vorher bekannt) und die Blockgebote (Börse auf Ist)."""
    import splitter
    blk = max(4, plant.min_up_slots)
    plan = (splitter.split_day(fc, h2, c, plant, block=blk, settle=act) if block else
            splitter.split_day(fc, h2, c, plant, margin=margin, min_run=plant.min_up_slots, p10=band[0], p90=band[1],
                               settle=act))
    ideal = splitter.split_day(act, h2, c, plant, min_run=plant.min_up_slots)
    bid = splitter.split_day(act, h2, c, plant, block=blk)
    return plan, ideal, bid


def _value_prices_by_day(days) -> tuple[pd.DataFrame, dict]:
    """H₂-/C-Werte je Tag aus external_market.csv (letzter Handelstag davor, vorwärts gefüllt) + Nachjustierfaktoren."""
    import price_check
    raw = pd.read_csv(EXTERNAL)
    fac = price_check.factors(price_check.validate(raw))  # wie /value-prices: nachjustierte Wege
    ext = raw.assign(date=pd.to_datetime(raw["date"]).dt.date)
    ext = ext.drop_duplicates("date").set_index("date").sort_index()
    return ext.reindex(sorted(set(ext.index) | set(days))).ffill(), fac


def splitter_year(carbon: str = "co2", milp_days: int = 14, margin: float = 0.0, plant: PlantConfig = PLANT) -> dict:
    """Wie oft schaltet der Splitter um, wann läuft das BHKW, was bringt es — je Tag H₂-/C-Wert aus den Marktdaten
    dieses Tages (Preisrechner), Plan mit Sicherheitsabstand `margin` und BHKW-Mindestlaufzeit, Abrechnung auf Ist.
    Euro je Gaseinheit und Viertelstunde, hochgerechnet aufs Jahr (= 1 MW BHKW im Dauerbetrieb).
    Zusätzlich die Optimierer-Variante (Gasspeicher, Tagesgas, Starts, Wärme) für die letzten `milp_days` Tage."""
    import splitter_milp
    import value_prices
    g, days = _forecast_days()
    ext, fac = _value_prices_by_day(days)
    rev = {"splitter": 0.0, "nur_strom": 0.0, "nur_plasma": 0.0, "ideal": 0.0}
    sw = strom = correct = unsure = slots = 0
    bid_rev, bid_sw, bid_ok = 0.0, 0, 0
    runs: list[int] = []
    hour_on, hour_n = np.zeros(24), np.zeros(24)
    months: dict[str, dict] = {}
    used, skipped, milp_rows = [], 0, []
    for d in days:
        pr = value_prices.prices({"date": d, **ext.loc[d].to_dict()}, factors=fac)
        h2, c = pr["h2"]["eur_kg"], pr["carbon"][carbon]["eur_kg"]
        if h2 is None or c is None:
            skipped += 1
            continue
        day = g.loc[d]
        fc, act = day["pred_B"].tolist(), day["actual"].tolist()
        band = (day["P10"].tolist(), day["P90"].tolist()) if {"P10", "P90"} <= set(day.columns) else (None, None)
        plan, ideal, bid = _split_settle(fc, act, band, h2, c, plant, margin)
        on = [r == "strom" for r in plan["route"]]
        for k in ("splitter", "nur_strom", "nur_plasma"):
            rev[k] += plan["revenue"][k]
        rev["ideal"] += ideal["revenue"]["splitter"]
        bid_rev += bid["revenue"]["splitter"]
        bid_sw += bid["switches"]
        bid_ok += sum(a == b for a, b in zip(bid["route"], ideal["route"]))
        sw += plan["switches"]
        strom += sum(on)
        slots += len(on)
        unsure += plan["unsure_slots"]
        correct += sum(a == b for a, b in zip(plan["route"], ideal["route"]))
        i = 0
        while i < len(on):
            if on[i]:
                j = i
                while j < len(on) and on[j]:
                    j += 1
                runs.append(j - i)
                i = j
            else:
                i += 1
        hrs = pd.DatetimeIndex(day["utc"]).tz_convert("Europe/Berlin").hour
        np.add.at(hour_on, hrs, on)
        np.add.at(hour_n, hrs, 1)
        mo = months.setdefault(str(d)[:7], {"on": 0, "n": 0, "uplift": 0.0})
        mo["on"] += sum(on)
        mo["n"] += len(on)
        mo["uplift"] += plan["revenue"]["splitter"] - max(plan["revenue"]["nur_strom"], plan["revenue"]["nur_plasma"])
        used.append((d, fc, act, h2, c))
    n = len(used)
    if not n:
        raise FileNotFoundError(EXTERNAL)  # keine Tage mit Marktdaten → 404 wie fehlende Datenbasis
    yr = 365 / n
    for d, fc, act, h2, c in used[-milp_days:] if milp_days else []:
        both = splitter_milp._solve(fc, h2, c, plant, pyro=True)
        power = splitter_milp._solve(fc, h2, c, plant, pyro=False)
        milp_rows.append({"day": str(d), "splitter": splitter_milp.settle(both, act, h2, c, plant),
                          "nur_strom": splitter_milp.settle(power, act, h2, c, plant, pyro=False),
                          "plasma_gas_mwh": sum(both["plasma_gas_mw"]) * plant.dt_h, "starts": both["starts"]})
    best = max(rev["nur_strom"], rev["nur_plasma"])
    mn = len(milp_rows) or 1
    return {
        "carbon": carbon, "days": n, "skipped": skipped, "from": str(used[0][0]), "to": str(used[-1][0]),
        "margin_eur_mwh": _r(margin), "min_run_h": plant.min_up_slots * plant.dt_h,
        "per_year": {k: _r(v * yr, 0) for k, v in rev.items()},
        "uplift_vs_best_pct": _r(100 * (rev["splitter"] - best) / best) if best else 0.0,
        "capture_pct": _r(100 * rev["splitter"] / rev["ideal"]) if rev["ideal"] else 0.0,
        "switches_per_year": _r(sw * yr, 0), "switches_per_day": _r(sw / n, 2),
        "bhkw_share_pct": _r(100 * strom / slots), "bhkw_runs_per_year": _r(len(runs) * yr, 0),
        "avg_run_h": _r(np.mean(runs) * plant.dt_h if runs else 0.0, 2),
        "short_runs_per_year": _r(sum(1 for r in runs if r < plant.min_up_slots) * yr, 0),
        "correct_pct": _r(100 * correct / slots), "unsure_pct": _r(100 * unsure / slots),
        "hourly_bhkw_pct": [_r(100 * a / b) if b else 0.0 for a, b in zip(hour_on, hour_n)],
        "monthly": [{"month": k, "bhkw_pct": _r(100 * v["on"] / v["n"]), "uplift_eur": _r(v["uplift"], 0)}
                    for k, v in sorted(months.items())],
        "bids": {"per_year": _r(bid_rev * yr, 0), "capture_pct": _r(100 * bid_rev / rev["ideal"]) if rev["ideal"] else 0.0,
                 "switches_per_year": _r(bid_sw * yr, 0), "correct_pct": _r(100 * bid_ok / slots)},
        "milp": {"days": len(milp_rows),
                 "uplift_eur_per_day": _r(sum(r["splitter"] - r["nur_strom"] for r in milp_rows) / mn),
                 "plasma_gas_mwh_per_day": _r(sum(r["plasma_gas_mwh"] for r in milp_rows) / mn, 2),
                 "starts_per_day": _r(sum(r["starts"] for r in milp_rows) / mn, 2),
                 "rows": [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()} for r in milp_rows]},
    }


# ── Tagesnachweis: jeder ausgegebene Plan, abgerechnet auf den echten Börsenpreisen ─────
PROOF_STATUS = ("abgerechnet", "kein Plan ausgegeben", "zu spät ausgegeben", "Ist-Preise fehlen noch", "keine Marktdaten")


def splitter_proof(runs: list[dict], prices: pd.Series, carbon: str = "co2", plant: PlantConfig = PLANT) -> dict:
    """Je Liefertag der ZUERST ausgegebene Plan (der, nach dem geboten wurde — spätere Läufe nach der Auktion sind
    Rückschau), abgerechnet auf Ist: Splitter-Plan vs. nur Strom vs. nur Plasma vs. Bestmögliches vs. Blockgebote.
    Kein Backtest: die Prognose stammt aus dem Lauf, so wie sie damals ausgegeben wurde (Datenbank).
    `runs`: {day, issued, basis, mae, ts, pred, p10, p90}; `prices`: Day-Ahead-Ist je UTC-Viertelstunde.
    Tage ohne Plan bleiben als Lücke stehen — der Nachweis zeigt auch, wann das System nichts geliefert hat.
    Ein Plan, der erst am Liefertag (Marktzeit) rausging, ist kein Day-Ahead-Plan: „zu spät ausgegeben“."""
    import value_prices
    first: dict = {}
    for r in sorted(runs, key=lambda r: r["issued"]):
        first.setdefault(r["day"], r)
    if not first:
        return {"carbon": carbon, "days": [], "summary": _proof_summary([])}
    issued_days = [r["issued"].date() for r in first.values()]
    ext, fac = _value_prices_by_day(issued_days)
    out = []
    day = min(first)
    while day <= max(first):
        r = first.get(day)
        row: dict = {"day": str(day), "status": "kein Plan ausgegeben", "issued": None, "basis": None}
        if r is not None:
            row.update(issued=r["issued"].isoformat(timespec="minutes"), basis=r["basis"])
            act = prices.reindex(pd.DatetimeIndex(r["ts"]).tz_convert("UTC")).tolist()
            pr = value_prices.prices({"date": r["issued"].date(), **ext.loc[r["issued"].date()].to_dict()}, factors=fac)
            h2, c = pr["h2"]["eur_kg"], pr["carbon"][carbon]["eur_kg"]
            if pd.Timestamp(r["issued"]).tz_convert("Europe/Berlin").date() >= day:
                row["status"] = "zu spät ausgegeben"
            elif any(pd.isna(a) for a in act):
                row["status"] = "Ist-Preise fehlen noch"
            elif h2 is None or c is None:
                row["status"] = "keine Marktdaten"
            else:
                auction = r["basis"] == "Auktion"
                band = (None, None) if auction else (r["p10"], r["p90"])
                plan, ideal, bid = _split_settle(r["pred"], act, band, h2, c, plant, 0.0 if auction else r["mae"],
                                                 block=auction or None)
                rv = plan["revenue"]
                best = max(rv["nur_strom"], rv["nur_plasma"])
                row.update(status="abgerechnet", h2_eur_kg=_r(h2, 2), c_eur_kg=_r(c, 3), threshold_eur_mwh=_r(plan["threshold"]),
                           revenue={"plan": _r(rv["splitter"], 2), "nur_strom": _r(rv["nur_strom"], 2),
                                    "nur_plasma": _r(rv["nur_plasma"], 2), "ideal": _r(ideal["revenue"]["splitter"], 2),
                                    "gebote": _r(bid["revenue"]["splitter"], 2)},
                           plus_vs_best_eur=_r(rv["splitter"] - best, 2),
                           capture_pct=_r(100 * rv["splitter"] / ideal["revenue"]["splitter"]) if ideal["revenue"]["splitter"] else 0.0,
                           switches=plan["switches"], strom_slots=plan["strom_slots"],
                           correct_pct=_r(100 * sum(a == b for a, b in zip(plan["route"], ideal["route"])) / len(act)))
        out.append(row)
        day += pd.Timedelta(days=1).to_pytimedelta()
    return {"carbon": carbon, "days": out, "summary": _proof_summary(out)}


def _proof_summary(rows: list[dict]) -> dict:
    done = [r for r in rows if r["status"] == "abgerechnet"]
    streak = 0
    for r in reversed([r for r in rows if r["status"] != "Ist-Preise fehlen noch"]):  # offen ≠ Lücke
        if r["status"] != "abgerechnet":
            break
        streak += 1
    ideal = sum(r["revenue"]["ideal"] for r in done)
    return {"settled_days": len(done), "missing_days": sum(r["status"] == "kein Plan ausgegeben" for r in rows),
            "pending_days": sum(r["status"] == "Ist-Preise fehlen noch" for r in rows),
            "late_days": sum(r["status"] == "zu spät ausgegeben" for r in rows), "streak_days": streak,
            "forecast_days": sum(r["basis"] == "Prognose" for r in done),  # vor der Auktion geplant = echter Prognosebeweis
            "plus_vs_best_eur": _r(sum(r["plus_vs_best_eur"] for r in done), 2),
            "capture_pct": _r(100 * sum(r["revenue"]["plan"] for r in done) / ideal) if ideal else 0.0,
            "last_settled": done[-1]["day"] if done else None}


# ── Prognoseband: roh vs. CQR (statisch) vs. ACI (adaptiv) ──────────────────
def forecast_band(show_days: int = 7, alpha: float = 0.20, gamma: float = 0.03) -> dict:
    q = pd.read_csv(QUANTILES, parse_dates=["utc"]).dropna(subset=["actual", "q10", "q90"])
    y, lo, hi = q["actual"].to_numpy(), q["q10"].to_numpy(), q["q90"].to_numpy()
    n_cal = int(len(q) * 0.3)
    score = np.maximum(lo - y, y - hi)
    cal = score[:n_cal]
    k = int(np.ceil((n_cal + 1) * (1 - alpha)))
    Q = float(np.sort(cal)[min(k, n_cal) - 1])

    te = slice(n_cal, len(q))
    yt, lt, ht = y[te], lo[te], hi[te]
    cov_raw = float(np.mean((yt >= lt) & (yt <= ht)))
    cov_cqr = float(np.mean((yt >= lt - Q) & (yt <= ht + Q)))
    # ACI (Gibbs & Candès): α_t online aus realisierter Abdeckung nachführen
    hist_scores, a_t = list(cal), alpha
    aci_lo, aci_hi, covered = [], [], []
    for i in range(len(yt)):
        Qt = float(np.quantile(hist_scores[-96 * 30:], min(max(1 - a_t, 0.0), 1.0)))
        l_i, h_i = lt[i] - Qt, ht[i] + Qt
        c = bool(l_i <= yt[i] <= h_i)
        aci_lo.append(l_i); aci_hi.append(h_i); covered.append(c)
        hist_scores.append(max(lt[i] - yt[i], yt[i] - ht[i]))
        a_t = min(0.999, max(0.001, a_t + gamma * (alpha - (0.0 if c else 1.0))))

    m = min(show_days * bf.NS, len(yt))
    # mit „Z“: ohne Zone liest der Browser (new Date) die Zeit als Lokalzeit → Achse um 2 h verschoben
    ts = pd.to_datetime(q["utc"].iloc[n_cal:], utc=True).dt.strftime("%Y-%m-%dT%H:%MZ").tolist()
    roll = pd.Series(covered, dtype=float).rolling(bf.NS, min_periods=1).mean().to_numpy()
    series = [{"ts": ts[i], "actual": _r(yt[i]), "raw_lo": _r(lt[i]), "raw_hi": _r(ht[i]),
               "aci_lo": _r(aci_lo[i]), "aci_hi": _r(aci_hi[i]), "aci_cov_24h": _r(roll[i], 3)}
              for i in range(len(yt) - m, len(yt))]
    return {
        "target": 1 - alpha, "calib_n": n_cal, "test_n": len(yt), "cqr_q": _r(Q, 2),
        "coverage": {"raw": _r(cov_raw, 3), "cqr": _r(cov_cqr, 3), "aci": _r(np.mean(covered), 3)},
        "width": {"raw": _r(np.mean(ht - lt)), "cqr": _r(np.mean(ht - lt + 2 * Q)),
                  "aci": _r(np.mean(np.array(aci_hi) - np.array(aci_lo)))},
        "series": series,
    }


# ── MPC: Speicherzustand über Tage (Rolling Horizon vs. tagesisoliert) ─────
def mpc_state(n_days: int = 14, horizon: int = 2, plant: PlantConfig = PLANT) -> dict:
    g, days = _forecast_days()
    days = days[-(n_days + horizon - 1):]
    run_days = days[:n_days]

    def roll(H: int) -> tuple[list[float], list[float]]:
        ns = plant.slots_per_day
        s, per_day, levels = plant.storage_max_mwh * 0.5, [], []
        for i, d in enumerate(run_days):
            pred = sum((g.loc[dd, "pred_B"].tolist() for dd in days[i:i + H]), [])
            pv, xv, lv = mpc.optimise(pred, s, cyclic=(H == 1), plant=plant)
            per_day.append(mpc.settle(pv[:ns], xv[:ns], g.loc[d, "actual"].tolist(), plant=plant))
            levels.extend(lv[:ns])
            s = lv[ns]
        return per_day, levels

    base, base_lv = roll(1)
    mp, mp_lv = roll(horizon)
    return {
        "horizon": horizon, "s_max": _r(plant.storage_max_mwh, 2),
        "days": [str(d) for d in run_days],
        "base_eur": [_r(v) for v in base], "mpc_eur": [_r(v) for v in mp],
        "total_base": _r(sum(base)), "total_mpc": _r(sum(mp)),
        "uplift_per_mw_year": _r((sum(mp) - sum(base)) / len(run_days) * 365, 0),
        "level_base": [_r(v, 2) for v in base_lv], "level_mpc": [_r(v, 2) for v in mp_lv],
    }


# ── Sensitivität: Tornado über Gas / H₂ / CO₂ ──────────────────────────────
def sensitivity(prices: list[float], gas: float = 70.0, h2: float = 100.0, co2: float = 79.0,
                mode: str = "plasma", delta: float = 0.3, plant: PlantConfig = PLANT,
                marktwert: float | None = None) -> dict:
    """Netto = dasselbe wie Was-wäre-wenn und Enno (eeg.net_incl_eeg): inkl. EEG, sobald der Monatsmarktwert bekannt ist."""
    base = {"gas": gas, "h2": h2, "co2": co2}

    def net(p: dict) -> float:
        r = whatif.solve_day(prices, gas_cost=p["gas"], h2_value=p["h2"], carbon_eur_t=p["co2"], ptx_mode=mode, plant=plant)
        return eeg.net_incl_eeg(r, prices, plant, marktwert)

    base_net = net(base)
    bars = []
    for k, label in (("gas", "Gaspreis"), ("h2", "H₂-Wert"), ("co2", "CO₂-/CDR-Preis")):
        lo = net({**base, k: base[k] * (1 - delta)})
        hi = net({**base, k: base[k] * (1 + delta)})
        bars.append({"param": k, "label": label, "base_value": base[k],
                     "low_value": _r(base[k] * (1 - delta)), "high_value": _r(base[k] * (1 + delta)),
                     "low_net": _r(lo), "high_net": _r(hi), "swing": _r(abs(hi - lo))})
    bars.sort(key=lambda b: b["swing"], reverse=True)
    return {"mode": mode, "delta": delta, "base_net": _r(base_net), "bars": bars, "with_eeg": marktwert is not None}
