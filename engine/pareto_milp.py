#!/usr/bin/env python3
"""
M6 — multi-criteria optimisation: Profit vs. CO2 (epsilon-constraint Pareto).

Climate objective uses a per-slot grid carbon intensity derived from the real
renewable share (history.csv): intensity_t = INT_MAX * (1 - ren_share_t/100)
[tCO2/MWh]. The biomethane BHKW (biogenic ~0 direct) DISPLACES grid power of
that intensity; PtX CONSUMES grid power at that intensity. Net CO2 saved =
sum (p_t - px_t) * intensity_t * DT.

Profit uses the real TTF gas price (+ biomethane premium). Sweeping the CO2
floor traces the Pareto front; its slope (EUR per tCO2) compared to the EUA
price (~79 EUR/t) tells whether on-site mitigation is cheaper than buying
allowances — the key techno-economic insight.
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant

INT_MAX = PLANT.grid_co2_max_t_mwh   # tCO2/MWh at zero renewable share (fossil-heavy grid)
BIO_PREMIUM = PLANT.bio_premium_eur_mwh  # EUR/MWh biomethane premium over TTF fossil gas


def solve(price, inten, gas_cost, co2_floor=None, plant: PlantConfig = PLANT):
    ns, dt = plant.slots_per_day, plant.dt_h
    m = pulp.LpProblem("pareto", pulp.LpMaximize)
    v = add_plant(m, plant, ns)
    profit = -pulp.lpSum(v.su[t] * plant.start_cost_eur for t in range(ns)) - gas_cost * plant.gas_budget_mwh
    co2 = 0
    for t in range(ns):
        profit += (v.p[t] * price[t] * dt + v.p[t] * plant.heat_credit_eur_mwh * dt
                   + v.px[t] * (plant.eta_ptx * plant.h2_value_eur_mwh - price[t] - plant.ptx_opex_eur_mwh) * dt)
        co2 += (v.p[t] - v.px[t]) * inten[t] * dt
    co2_var = pulp.LpVariable("co2", lowBound=None)
    m += co2_var == co2
    if co2_floor is not None:
        m += co2_var >= co2_floor
    m += profit
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    return pulp.value(profit), pulp.value(co2_var), pulp.LpStatus[m.status]


def solve_co2max(price, inten, gas_cost, plant: PlantConfig = PLANT):
    """Separate endpoint: maximise CO2 saved (ignores profit)."""
    ns, dt = plant.slots_per_day, plant.dt_h
    m = pulp.LpProblem("co2max", pulp.LpMaximize)
    v = add_plant(m, plant, ns, startup=False)
    m += pulp.lpSum((v.p[t] - v.px[t]) * inten[t] * dt for t in range(ns))
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    return pulp.value(m.objective)
