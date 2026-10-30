#!/usr/bin/env python3
"""
M5 — rolling-horizon MPC (receding horizon) with storage state carried across
day boundaries.

Critical comparison, both planned on the FORECAST and settled on ACTUAL prices
(so the only difference is horizon + state continuity, not forecast skill):
  - daily-independent : 1-day horizon, cyclic storage (end = start)  [the naive op]
  - MPC               : H-day horizon, storage carried forward, commit day 1 only

MPC value = inter-day gas arbitrage + multi-day foresight. It is BOUNDED by the
storage size (here ~1 day of gas), so we expect a modest but positive gain —
reported honestly rather than inflated.
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant


def optimise(prices, s0, cyclic, plant: PlantConfig = PLANT):
    """Plan over len(prices) slots from initial storage s0.
    cyclic=True forces end storage == s0 (daily-independent baseline);
    else terminal floor prevents myopic draining (MPC)."""
    L, dt = len(prices), plant.dt_h
    m = pulp.LpProblem("h", pulp.LpMaximize)
    v = add_plant(m, plant, L, s0=s0, end="eq_s0" if cyclic else "floor", gas_budget=False)
    obj = 0
    for t in range(L):
        obj += (v.p[t] * prices[t] * dt + v.p[t] * plant.heat_credit_eur_mwh * dt
                + v.px[t] * (plant.eta_ptx * plant.h2_value_eur_mwh - prices[t] - plant.ptx_opex_eur_mwh) * dt
                - v.su[t] * plant.start_cost_eur)
    m += obj
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    pv = [pulp.value(v.p[t]) or 0 for t in range(L)]
    xv = [pulp.value(v.px[t]) or 0 for t in range(L)]
    return pv, xv, [pulp.value(v.lvl[t]) for t in range(L + 1)]


def settle(pv, xv, actual, plant: PlantConfig = PLANT):
    dt = plant.dt_h
    starts = sum(1 for t in range(1, len(pv)) if pv[t] > 1e-6 and pv[t-1] <= 1e-6)
    r = sum(pv[t]*actual[t]*dt + pv[t]*plant.heat_credit_eur_mwh*dt for t in range(len(pv))) - starts*plant.start_cost_eur
    r += sum(xv[t]*(plant.eta_ptx*plant.h2_value_eur_mwh - actual[t] - plant.ptx_opex_eur_mwh)*dt for t in range(len(pv)))
    return r
