#!/usr/bin/env python3
"""
Splitter im Optimierer: dasselbe Tagesgas wird über 96 Viertelstunden auf BHKW (Strom + Wärme) und Plasma-Pyrolyse
(H₂ + fester Kohlenstoff) verteilt — mit Gasspeicher, festem Tagesgas, Mindestlast, Startkosten, Mindestlauf- und
-stillstandszeit und Wärme-Mindestlauf (dispatch.add_plant). Der Plasma-Erlös je MWh Gas kommt aus FLDs Verhältnis:
eine Gaseinheit = so viel Gas, wie das BHKW für split_el_kwh Strom braucht (÷ eta_el).

Vergleich: dieselbe Anlage ohne Plasma („nur Strom“, optimal gefahren). „Nur Plasma“ gibt es hier nicht: die
Pyrolyse-Kapazität (pyro_max_gas_mwh) reicht nicht für das ganze Tagesgas.
"""
import pulp

from config import PlantConfig
from dispatch import add_plant


def plasma_value_per_gas(h2: float, c: float, plant: PlantConfig) -> tuple[float, float]:
    """→ (€ aus H₂ + C je MWh Gas, MWh Plasma-Strom je MWh Gas)."""
    unit = plant.split_el_kwh / 1000 / plant.eta_el  # MWh Gas je Gaseinheit
    return (plant.split_h2_kg * h2 + plant.split_c_kg * c) / unit, plant.split_plasma_kwh / 1000 / unit


def _solve(prices: list[float], h2: float, c: float, plant: PlantConfig, pyro: bool) -> dict:
    ns, dt = len(prices), plant.dt_h
    val, pel = plasma_value_per_gas(h2, c, plant)
    m = pulp.LpProblem("splitter", pulp.LpMaximize)
    v = add_plant(m, plant, ns, electro=False, pyro=pyro, startup=True, min_updown=True, heat_mustrun=True)
    rev = pulp.lpSum(v.p[t] * (prices[t] + plant.heat_credit_eur_mwh) * dt - v.su[t] * plant.start_cost_eur
                     for t in range(ns))
    if pyro:
        rev += pulp.lpSum(v.gp[t] * (val - pel * prices[t]) * dt for t in range(ns))
    m += rev
    m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20))
    pv = [max(0.0, pulp.value(v.p[t]) or 0.0) for t in range(ns)]
    gv = [max(0.0, pulp.value(v.gp[t]) or 0.0) for t in range(ns)] if pyro else [0.0] * ns
    return {"status": pulp.LpStatus[m.status], "objective": pulp.value(m.objective) or 0.0, "bhkw_mw": pv,
            "plasma_gas_mw": gv, "storage_mwh": [pulp.value(x) or 0.0 for x in v.lvl],
            "starts": sum(1 for t in range(ns) if pv[t] > 1e-6 and (t == 0 or pv[t - 1] <= 1e-6))}


def solve(prices: list[float], h2: float, c: float, plant: PlantConfig) -> dict:
    """Tagesplan BHKW/Plasma je Viertelstunde + Erlös gegenüber „nur Strom“ (beide optimal, gleiche Anlage)."""
    if len(prices) != plant.slots_per_day:  # Zeitumstellung: 92/100 Viertelstunden
        from dataclasses import replace
        plant = replace(plant, slots_per_day=len(prices))
    both = _solve(prices, h2, c, plant, pyro=True)
    power = _solve(prices, h2, c, plant, pyro=False)
    val, _ = plasma_value_per_gas(h2, c, plant)
    gas_plasma = sum(both["plasma_gas_mw"]) * plant.dt_h
    unit = plant.split_el_kwh / 1000 / plant.eta_el
    return {**both, "status": both["status"] if power["status"] == "Optimal" else power["status"],
            "revenue": {"splitter": both["objective"], "nur_strom": power["objective"]},
            "uplift_eur": both["objective"] - power["objective"],
            "plasma_gas_mwh": gas_plasma, "h2_kg": gas_plasma / unit * plant.split_h2_kg,
            "c_kg": gas_plasma / unit * plant.split_c_kg, "plasma_eur_per_mwh_gas": val,
            "bhkw_h": sum(1 for p in both["bhkw_mw"] if p > 1e-6) * plant.dt_h}


def settle(plan: dict, actual: list[float], h2: float, c: float, plant: PlantConfig, pyro: bool = True) -> float:
    """Erlös eines (auf der Prognose geplanten) Fahrplans zu den Ist-Preisen — wie der Backtest des Fahrplans."""
    val, pel = plasma_value_per_gas(h2, c, plant)
    dt = plant.dt_h
    rev = sum(p * (a + plant.heat_credit_eur_mwh) * dt for p, a in zip(plan["bhkw_mw"], actual))
    rev -= plan["starts"] * plant.start_cost_eur
    if pyro:
        rev += sum(g * (val - pel * a) * dt for g, a in zip(plan["plasma_gas_mw"], actual))
    return rev
