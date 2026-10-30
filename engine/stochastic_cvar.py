#!/usr/bin/env python3
"""
M3b — mean-CVaR two-stage stochastic UC with SHAPE-aware scenarios.

Closes the VSS~0 finding from stochastic_milp.py:
  - scenarios now carry intraday shape uncertainty (block-bootstrap residuals)
    -> the commitment decision is genuinely uncertain -> VSS > 0
  - risk aversion via CVaR (Rockafellar-Uryasev): objective
        (1-lambda) * E[profit]  +  lambda * CVaR_alpha[profit]
    traces an efficient frontier E[profit] vs. downside risk, and shows the
    schedule hedge against low-price tails (cost of robustness).
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant

ALPHA = 0.20   # CVaR tail (worst 20% of scenarios)


def recourse(m, pfx, on, price, plant: PlantConfig = PLANT):
    """Zweite Stufe je Szenario: Leistung/Speicher/Elektrolyse bei geteiltem Einsatz `on`."""
    dt = plant.dt_h
    v = add_plant(m, plant, plant.slots_per_day, pfx=pfx, on=on)
    rev = 0
    for t in range(plant.slots_per_day):
        rev += (v.p[t] * price[t] * dt + v.p[t] * plant.heat_credit_eur_mwh * dt
                + v.px[t] * (plant.eta_ptx * plant.h2_value_eur_mwh - price[t] - plant.ptx_opex_eur_mwh) * dt)
    return rev


def solve(scen, lam, fixed_on=None, ws=False, plant: PlantConfig = PLANT):
    """mean-CVaR two-stage. fixed_on: evaluate a given commitment (EEV).
    ws=True: per-scenario full info commitment (WS / EVPI)."""
    ns, start_c = plant.slots_per_day, plant.start_cost_eur
    S = len(scen)
    pi = 1.0 / S
    if ws:
        z = 0.0
        for price in scen:
            m = pulp.LpProblem("ws", pulp.LpMaximize)
            on = [pulp.LpVariable(f"o{t}", cat="Binary") for t in range(ns)]
            su = [pulp.LpVariable(f"u{t}", 0, 1) for t in range(ns)]
            for t in range(1, ns):
                m += su[t] >= on[t] - on[t - 1]
            m += recourse(m, "w", on, price, plant) - pulp.lpSum(su[t] * start_c for t in range(ns))
            m.solve(pulp.PULP_CBC_CMD(msg=0))
            z += pi * pulp.value(m.objective)
        return z, None

    m = pulp.LpProblem("rp", pulp.LpMaximize)
    if fixed_on is None:
        on = [pulp.LpVariable(f"on{t}", cat="Binary") for t in range(ns)]
        su = [pulp.LpVariable(f"su{t}", 0, 1) for t in range(ns)]
        for t in range(1, ns):
            m += su[t] >= on[t] - on[t - 1]
        start_cost = pulp.lpSum(su[t] * start_c for t in range(ns))
    else:
        on = [float(x) for x in fixed_on]
        start_cost = sum(1 for t in range(1, ns) if fixed_on[t] > fixed_on[t - 1]) * start_c

    profit = []
    for s, price in enumerate(scen):
        profit.append(recourse(m, f"s{s}_", on, price, plant) - start_cost)
    exp = pulp.lpSum(pi * profit[s] for s in range(S))

    # Rockafellar-Uryasev CVaR of profit (maximise the lower tail)
    eta = pulp.LpVariable("eta")
    zc = [pulp.LpVariable(f"z{s}", 0) for s in range(S)]
    for s in range(S):
        m += zc[s] >= eta - profit[s]
    cvar = eta - (1.0 / ALPHA) * pulp.lpSum(pi * zc[s] for s in range(S))

    m += (1 - lam) * exp + lam * cvar
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    onv = ([int(round(pulp.value(on[t]))) for t in range(ns)]
           if fixed_on is None else fixed_on)
    ep = sum(pi * (pulp.value(profit[s])) for s in range(S))
    pr = sorted(pulp.value(profit[s]) for s in range(S))
    k = max(1, int(ALPHA * S))
    cv = sum(pr[:k]) / k                      # realised CVaR (mean of worst alpha)
    return ep, onv, cv
