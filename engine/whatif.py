#!/usr/bin/env python3
"""
Parametrisierter Tages-Optimierer für das What-if-Dashboard.
Re-optimiert einen Tag unter veränderten Annahmen (Gaspreis, H2-Wert,
Kohlenstoff-Gutschrift, PtX-Pfad) — damit die Slider echt re-optimieren.
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant, carbon_rev_per_gas, flat_baseline


def solve_day(prices, gas_cost=70.0, h2_value=100.0, carbon_eur_t=79.0, ptx_mode="plasma", plant: PlantConfig = PLANT,
              on=None):
    """ptx_mode: 'none' | 'electro' | 'plasma'. Returns dispatch + KPIs.
    on: fest vorgegebener BHKW-Einsatz (z. B. aus der Stochastik); dann nur Leistung/PtX re-optimiert."""
    ns, dt = plant.slots_per_day, plant.dt_h
    crev = carbon_rev_per_gas(plant, carbon_eur_t)
    m = pulp.LpProblem("whatif", pulp.LpMaximize)
    v = add_plant(m, plant, ns, electro=ptx_mode == "electro", pyro=ptx_mode == "plasma", on=on)
    rev = 0 if on is None else -plant.start_cost_eur * sum(1 for t in range(1, ns) if on[t] > on[t-1])
    for t in range(ns):
        rev += (v.p[t]*prices[t]*dt + v.p[t]*plant.heat_credit_eur_mwh*dt - (v.su[t] if v.su else 0)*plant.start_cost_eur
                + v.px[t]*(plant.eta_ptx*h2_value - prices[t] - plant.ptx_opex_eur_mwh)*dt
                + v.gp[t]*(plant.eta_pyro_h2*h2_value + crev - plant.plasma_el_per_gas*prices[t])*dt)
    m += rev
    m.solve(pulp.PULP_CBC_CMD(msg=0))

    pv = [pulp.value(v.p[t]) or 0 for t in range(ns)]
    xv = [pulp.value(v.px[t]) or 0 for t in range(ns)]
    gv = [pulp.value(v.gp[t]) or 0 for t in range(ns)]
    return kpis(prices, pv, xv, gv, pulp.value(m.objective), pulp.LpStatus[m.status],
                gas_cost, h2_value, carbon_eur_t, plant)


def kpis(prices, pv, xv, gv, objective, status, gas_cost, h2_value, carbon_eur_t, plant: PlantConfig = PLANT):
    """Fahrplan (BHKW, Elektrolyse, Pyrolyse) + Zielfunktionswert -> KPI-Dict im What-if-Format."""
    ns, dt = plant.slots_per_day, plant.dt_h
    # KPI breakdown
    spot = sum(pv[t]*prices[t]*dt for t in range(ns))
    heat = sum(pv[t]*plant.heat_credit_eur_mwh*dt for t in range(ns))
    h2_mwh = sum(xv)*dt*plant.eta_ptx + sum(gv)*dt*plant.eta_pyro_h2
    h2v = sum(xv[t]*plant.eta_ptx*h2_value*dt for t in range(ns)) + sum(gv[t]*plant.eta_pyro_h2*h2_value*dt for t in range(ns))
    carb_t = sum(gv)*dt*plant.carbon_t_per_gas
    carb = carb_t*(44/12)*carbon_eur_t
    elcost = sum(xv[t]*prices[t]*dt for t in range(ns)) + sum(gv[t]*plant.plasma_el_per_gas*prices[t]*dt for t in range(ns))
    gas_total = gas_cost * plant.gas_budget_mwh
    starts = sum(1 for t in range(1, ns) if pv[t] > 1e-6 and pv[t-1] <= 1e-6)
    net = objective - gas_total
    flat = flat_baseline(prices, plant) - gas_total
    return {
        "bhkw": pv, "electro": xv, "pyro": gv,
        "net_eur": net, "flat_eur": flat, "uplift_eur": net - flat,
        "spot": spot, "heat": heat, "h2_eur": h2v, "carbon_eur": carb,
        "h2_mwh": h2_mwh, "carbon_t": carb_t, "elcost": elcost,
        "gas_cost": gas_total, "starts": starts,
        "bhkw_h": sum(1 for x in pv if x > 1e-6)*dt,
        "status": status,
    }
