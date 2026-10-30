#!/usr/bin/env python3
"""
Realistic plant (v2) + forecast-driven backtest — the honest operational result.

v2 vs v1: smaller gas buffer (8h not 24h), min up/down time, heat must-run
baseload, PtX with opex. Three strategies on the FORECAST TEST period:
  1. flat baseline            (no flexibility)
  2. forecast-driven          (schedule on PREDICTED price, settle on ACTUAL)
  3. perfect foresight        (schedule on ACTUAL price = upper bound)

capture rate = forecast-driven uplift / perfect-foresight uplift.
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant, flat_baseline

# Abgeleitete Kurznamen der Standard-Anlage — nur noch Aliase auf PLANT (eine Quelle).
P_BHKW, ETA_EL, MINLOAD = PLANT.p_bhkw_mw, PLANT.eta_el, PLANT.min_load
START_C = PLANT.start_cost_eur
FULLH, S_HOURS = PLANT.full_hours_per_day, PLANT.storage_hours
MINUP, MINDN = PLANT.min_up_slots, PLANT.min_down_slots
HEAT_MINRUN = PLANT.heat_min_runtime_slots
HEAT_CR, GAS_COST = PLANT.heat_credit_eur_mwh, 70.0
PTX_ON, P_EL, ETA_PTX = True, PLANT.p_el_mw, PLANT.eta_ptx
H2_VALUE, PTX_OPEX = PLANT.h2_value_eur_mwh, PLANT.ptx_opex_eur_mwh

DT, NS = PLANT.dt_h, PLANT.slots_per_day
G_DAY = PLANT.gas_budget_mwh
G_IN = PLANT.gas_in_per_slot_mwh
S_MAX = PLANT.storage_max_mwh


def schedule(prices, plant: PlantConfig = PLANT):
    """Fahrplan für einen Tag (Min-up/down, Wärme-Mindestlauf, Elektrolyse). → (p[], px[], Status)"""
    ns, dt = plant.slots_per_day, plant.dt_h
    m = pulp.LpProblem("d", pulp.LpMaximize)
    v = add_plant(m, plant, ns, names={"lvl": "s", "px": "px"}, min_updown=True, heat_mustrun=True)
    rev = 0
    for t in range(ns):
        rev += v.p[t]*prices[t]*dt + v.p[t]*plant.heat_credit_eur_mwh*dt - v.su[t]*plant.start_cost_eur
        rev += (v.px[t]*plant.eta_ptx*plant.h2_value_eur_mwh*dt - v.px[t]*prices[t]*dt
                - v.px[t]*plant.ptx_opex_eur_mwh*dt)
    m += rev
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    pv = [pulp.value(v.p[t]) or 0 for t in range(ns)]
    xv = [pulp.value(v.px[t]) or 0 for t in range(ns)]
    return pv, xv, pulp.LpStatus[m.status]


def settle(pv, xv, actual, plant: PlantConfig = PLANT):
    """Erlös eines festen Fahrplans zu IST-Preisen (Gaskosten kürzen sich im Mehrerlös)."""
    dt = plant.dt_h
    starts = sum(1 for t in range(1, len(pv)) if pv[t] > 1e-6 and pv[t-1] <= 1e-6)
    r = sum(pv[t]*actual[t]*dt + pv[t]*plant.heat_credit_eur_mwh*dt for t in range(len(pv))) - starts*plant.start_cost_eur
    r += sum(xv[t]*plant.eta_ptx*plant.h2_value_eur_mwh*dt - xv[t]*actual[t]*dt - xv[t]*plant.ptx_opex_eur_mwh*dt
             for t in range(len(pv)))
    return r


def flat(actual, plant: PlantConfig = PLANT):
    return flat_baseline(actual, plant)
