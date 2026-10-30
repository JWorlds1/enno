"""Planung der Tageskette: Backtest, Empfehlung für morgen, Tagesentscheidung Spot vs. Regelenergie.

Backtest: Fahrplan auf der Prognose geplant, zu Ist-Preisen abgerechnet, gegen Dauerbetrieb.
Empfehlung: Sind die Auktionspreise für morgen bekannt (ab ~12:45 Uhr), wird darauf geplant, sonst auf die Prognose.
Entscheidung: Spot allein vs. Spot + Regelenergie aus der Co-Optimierung — beide netto gegen Dauerbetrieb, also
vergleichbar (früher: Brutto-Kapazitätserlös gegen Spot-Mehrerlös).
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

import backtest_forecast as bf
import coopt_milp
from config import PLANT, PlantConfig

RESERVE_MIN_GAIN_EUR = 20.0  # Regelenergie lohnt erst ab diesem Zusatzerlös (Aufwand Präqualifikation/Abruf)


def backtest(pred: pd.DataFrame, plant: PlantConfig = PLANT) -> tuple[pd.DataFrame, dict]:
    """Je vollständigem Liefertag: Dauerbetrieb, perfekte Voraussicht, Plan auf Prognose B (und A zum Vergleich)."""
    rows, up_a = [], 0.0
    for day, g in pred.groupby("day"):
        if len(g) != plant.slots_per_day or g[["actual", "pred_A", "pred_B"]].isna().any().any():
            continue  # Zeitumstellung (92/100 Slots) oder Lücken
        act = g["actual"].tolist()
        flat = bf.flat(act, plant)
        pv, xv, st_pf = bf.schedule(act, plant)
        perfect = bf.settle(pv, xv, act, plant)
        pred = g["pred_B"].tolist()
        pv, xv, st_fc = bf.schedule(pred, plant)
        fc = bf.settle(pv, xv, act, plant)
        exp_fc = bf.settle(pv, xv, pred, plant) - bf.flat(pred, plant)  # vor der Auktion erwartet (nur Prognose)
        pv, xv, _ = bf.schedule(g["pred_A"].tolist(), plant)
        up_a += bf.settle(pv, xv, act, plant) - flat
        rows.append({"day": str(day), "flat": flat, "perfect": perfect, "forecast": fc,
                     "ok": st_pf == "Optimal" and st_fc == "Optimal", "up_pf": perfect - flat, "up_fc": fc - flat,
                     "exp_fc": exp_fc})
    bt = pd.DataFrame(rows)
    n = len(bt)
    s = {"days": n, "flat_eur": float(bt["flat"].sum()), "up_fc_eur": float(bt["up_fc"].sum()),
         "up_pf_eur": float(bt["up_pf"].sum()), "up_fc_model_A_eur": up_a}
    s["per_year_eur"] = s["up_fc_eur"] / n * 365 if n else 0.0
    s["pct_vs_flat"] = s["up_fc_eur"] / s["flat_eur"] * 100 if s["flat_eur"] else 0.0
    s["capture_pct"] = s["up_fc_eur"] / s["up_pf_eur"] * 100 if s["up_pf_eur"] else 0.0
    return bt, s


def recommend(day_pred: pd.DataFrame, model_info: dict, plant: PlantConfig = PLANT) -> tuple[pd.DataFrame, dict]:
    """Fahrplan für den Liefertag = Gebotsplan, immer auf der Prognose B gerechnet (nach 12:00 ist das Gebot abgegeben).

    Sind die Auktionspreise bekannt, wird derselbe Plan zu diesen Preisen BEWERTET (price_basis „Auktion“);
    der Plan mit perfekter Kenntnis der Preise ist nur Obergrenze (upper_bound_uplift_eur), nie die Empfehlung.

    Tage mit Zeitumstellung haben 92/100 Viertelstunden → die Anlage wird mit genau so vielen Slots gerechnet."""
    if len(day_pred) != plant.slots_per_day:
        plant = replace(plant, slots_per_day=len(day_pred))
    auction = bool(day_pred["actual"].notna().all())
    basis = (day_pred["actual"] if auction else day_pred["pred_B"]).tolist()  # Bewertungspreise
    pv, xv, status = bf.schedule(day_pred["pred_B"].tolist(), plant)  # Plan: nur Wissen vor der Auktion
    loc = day_pred.index.tz_convert("Europe/Berlin")
    rec = pd.DataFrame({"slot": range(len(basis)), "time": [t.strftime("%H:%M") for t in loc],
                        "utc": [t.isoformat() for t in day_pred.index],
                        "pred_price_eur_mwh": day_pred["pred_B"].round(1).to_numpy(),
                        "actual_price_eur_mwh": day_pred["actual"].round(2).to_numpy(),
                        "bhkw_mw": [round(v, 3) for v in pv], "electrolyser_mw": [round(v, 3) for v in xv]})
    rev, base = bf.settle(pv, xv, basis, plant), bf.flat(basis, plant)
    dt = plant.dt_h
    kpi = {
        "target_day": str(day_pred["day"].iloc[0]), "status": status,
        "price_basis": "Auktion" if auction else "Prognose",
        "expected_revenue_eur": round(rev, 0), "flat_baseline_eur": round(base, 0),
        "expected_uplift_eur": round(rev - base, 0),
        "bhkw_runtime_h": sum(1 for v in pv if v > 1e-6) * dt,
        "bhkw_starts": sum(1 for t in range(1, len(pv)) if pv[t] > 1e-6 and pv[t - 1] <= 1e-6),
        "electrolyser_runtime_h": sum(1 for v in xv if v > 1e-6) * dt,
        "h2_produced_mwh": round(sum(xv) * plant.eta_ptx * dt, 2),
        "h2_value_eur": round(sum(xv) * plant.eta_ptx * dt * plant.h2_value_eur_mwh, 0),
        "pred_price_min": round(min(basis), 1), "pred_price_max": round(max(basis), 1),
        "model": model_info.get("name", ""), "forecast_mae_eur_mwh": model_info.get("mae"),
    }
    if auction:  # Obergrenze: Plan mit perfekter Kenntnis der Auktionspreise (nicht handelbar, nur Vergleich)
        upv, uxv, _ = bf.schedule(basis, plant)
        kpi["upper_bound_uplift_eur"] = round(bf.settle(upv, uxv, basis, plant) - base, 0)
    return rec, kpi


def decide(rec: pd.DataFrame, kpi: dict, reg: pd.DataFrame, ext: pd.DataFrame, sigma: float,
           plant: PlantConfig = PLANT) -> tuple[dict, pd.DataFrame, dict]:
    """Spot vs. Spot + Regelenergie, beide als Mehrerlös gegen Dauerbetrieb; Regelpreise = Mittel der letzten 30 Tage.

    Entschieden wird vor den Auktionen (Regelleistung D-1 morgens, Spot bis 12:00) → nur auf der Prognose.
    Bei „Regelenergie vorhalten“ wird der Fahrplan der Co-Optimierung zur Empfehlung: BHKW/Elektrolyse plus die
    vorgehaltene Reserve je Viertelstunde (sonst ließe sich die Reserve nicht erbringen). → (Entscheidung, Fahrplan, KPIs)."""
    if len(rec) != plant.slots_per_day:  # Zeitumstellung
        plant = replace(plant, slots_per_day=len(rec))
    auction = kpi["price_basis"] == "Auktion"
    plan_px = rec["pred_price_eur_mwh"].tolist()
    basis = (rec["actual_price_eur_mwh"] if auction else rec["pred_price_eur_mwh"]).tolist()  # nur Bewertung
    r30 = reg.sort_values("date").tail(30)
    a_pos, a_neg, fcr = (float(r30[c].mean()) for c in ("aFRR_pos_eur_mw_h", "aFRR_neg_eur_mw_h", "FCR_eur_mw_h"))
    spot_only = coopt_milp.optimise(plan_px, a_pos, fcr, allow_reserve=False, plant=plant, afrr_neg=a_neg)[0]
    co, cap, mw, st, cpv, cxv, res = coopt_milp.optimise(plan_px, a_pos, fcr, allow_reserve=True, plant=plant,
                                                          afrr_neg=a_neg, detail=True)
    spot_up = float(kpi["expected_uplift_eur"])  # Spot-Plan, bewertet zur Preisbasis (nach der Auktion: Ist)
    spot_fc = bf.settle(rec["bhkw_mw"].tolist(), rec["electrolyser_mw"].tolist(), plan_px, plant) - bf.flat(plan_px, plant)
    gain = co - spot_only  # Zusatz durch Reserve, auf der Prognose — nur das war bei der Entscheidung bekannt
    both = spot_up + gain
    ptx_h = float(kpi["electrolyser_runtime_h"])
    if gain >= RESERVE_MIN_GAIN_EUR:
        strategy = "REGELENERGIE_RESERVE"
    elif ptx_h > 0:
        strategy = "PTX_PRIORITY"
    else:
        strategy = "SPOT_FLEX"
    if strategy == "REGELENERGIE_RESERVE":
        rec, kpi = _with_reserve(rec, kpi, cpv, cxv, res, cap, mw, basis, plant)
        both = float(kpi["expected_uplift_eur"])  # Plan der Co-Optimierung, bewertet wie der Spot-Plan
        ptx_h = float(kpi["electrolyser_runtime_h"])
    last = ext.dropna().iloc[-1]
    guards = {"heat_min_runtime": "ok" if sum(1 for v in rec["bhkw_mw"] if v > 1e-6) >= plant.heat_min_runtime_slots else "VERLETZT",
              "solver_feasible": "ok" if kpi["status"] == "Optimal" and st == "Optimal" else "VERLETZT",
              "capacity_ok": "ok" if rec["bhkw_mw"].max() <= plant.p_bhkw_mw + 1e-6 else "VERLETZT"}
    spread = max(basis) - min(basis)
    fc_txt = f"Prognose ({kpi['model']}, MAE {kpi['forecast_mae_eur_mwh']} EUR/MWh)"
    basis_txt = (f"Gebotsplan auf {fc_txt}, bewertet zu den Auktionspreisen (seit ~12:45 bekannt)" if auction else fc_txt)
    rat = [f"Preisbasis: {basis_txt}.",
           f"Preis-Spread {spread:.1f} EUR/MWh, Prognose-Unsicherheit σ={sigma:.1f} EUR/MWh.",
           f"Entscheidung auf der Prognose: Spot-Flex {spot_fc:.1f} EUR vs. Regelenergie {spot_fc + gain:.1f} EUR "
           f"(Spot + Reserve; aFRR+ {a_pos:.1f}, aFRR− {a_neg:.1f}, FCR {fcr:.1f} (EUR/MW)/h, Mittel 30 Tage).",
           f"Reserve: Ø {mw:.2f} MW vorgehalten, Kapazitätserlös {cap:.0f} EUR, Zusatz ggü. nur Spot {gain:.0f} EUR."]
    rat.append(f"Elektrolyse {ptx_h:.1f} h." if ptx_h > 0 else "Elektrolyse lohnt sich morgen in keiner Viertelstunde.")
    if auction:  # Bewertung erst nach der Auktion, getrennt von der Entscheidung
        rat.append(f"Ergebnis zu Auktionspreisen: {(both if strategy == 'REGELENERGIE_RESERVE' else spot_up):.1f} EUR "
                   f"gegenüber Dauerbetrieb (nur Spot: {spot_up:.1f} EUR).")
    rat.append(f"Gewählt: {strategy}.")
    viol = [k for k, v in guards.items() if v != "ok"]
    rat.append("Guardrails ok." if not viol else f"GUARDRAIL-FLAGS: {viol}")
    return {"target_day": kpi["target_day"], "strategy": strategy, "expected_uplift_eur": round(both if strategy == "REGELENERGIE_RESERVE" else spot_up, 1),
            "risk_sigma_eur": round(sigma, 1),
            "signals": {"price_spread_eur_mwh": round(spread, 1), "spot_uplift_eur": round(spot_up, 1),
                        "reserve_gain_eur": round(gain, 1), "reserve_mw": round(mw, 2), "capacity_eur": round(cap, 1),
                        "afrr_pos_eur_mw_h": round(a_pos, 2), "afrr_neg_eur_mw_h": round(a_neg, 2), "fcr_eur_mw_h": round(fcr, 2),
                        "gas_eur_mwh": float(last["ttf_eur_mwh"]), "co2_eur_t": float(last["eua_eur_t"])},
            "strategy_scores": {"SPOT_FLEX": round(spot_up, 1), "REGELENERGIE_RESERVE": round(both, 1)},
            "guardrails": guards, "rationale": rat}, rec, kpi


def _with_reserve(rec: pd.DataFrame, kpi: dict, pv: list, xv: list, res: list[dict], cap: float, mw: float,
                  basis: list[float], plant: PlantConfig) -> tuple[pd.DataFrame, dict]:
    """Fahrplan mit Reserve: Leistung der Co-Optimierung + vorgehaltene MW je Viertelstunde (für die Leitwarte)."""
    rec = rec.assign(bhkw_mw=[round(v, 3) for v in pv], electrolyser_mw=[round(v, 3) for v in xv],
                     reserve_up_mw=[round(r["up_mw"], 3) for r in res], reserve_down_mw=[round(r["down_mw"], 3) for r in res])
    dt = plant.dt_h
    rev = bf.settle(pv, xv, basis, plant) + cap
    base = bf.flat(basis, plant)
    kpi = {**kpi, "expected_revenue_eur": round(rev, 0), "expected_uplift_eur": round(rev - base, 0),
           "bhkw_runtime_h": sum(1 for v in pv if v > 1e-6) * dt,
           "bhkw_starts": sum(1 for t in range(1, len(pv)) if pv[t] > 1e-6 and pv[t - 1] <= 1e-6),
           "electrolyser_runtime_h": sum(1 for v in xv if v > 1e-6) * dt,
           "h2_produced_mwh": round(sum(xv) * plant.eta_ptx * dt, 2),
           "h2_value_eur": round(sum(xv) * plant.eta_ptx * dt * plant.h2_value_eur_mwh, 0),
           "reserve_capacity_eur": round(cap, 0), "reserve_mw_avg": round(mw, 2)}
    kpi.pop("upper_bound_uplift_eur", None)  # Obergrenze galt dem Spot-Plan
    return rec, kpi
