#!/usr/bin/env python3
"""
M4 — co-optimisation of Spot energy <-> Regelenergie capacity <-> PtX.

The plant's MW are a shared resource: every MW sold on the spot is a MW that
cannot be reserved as balancing capacity (aFRR/FCR) and vice versa. This MILP
allocates the BHKW capacity jointly across all three value streams, respecting
reserve headroom, and quantifies the uplift over a spot-only schedule — exactly
the gap the decision agent flagged (Regelenergie > Spot on some days).

Reserve products are 4h blocks (as on regelleistung.net): reserved MW is
constant within each block. Capacity payments use the observed clearing prices.
"""
import pulp

from config import PLANT, PlantConfig
from dispatch import add_plant

BLOCK = 16          # 4h = 16 quarter-hours
NBLOCK = 6          # sechs 4-h-Produkte je Liefertag (Marktzeit)


def block_of(t, ns):
    """Reserveblock des Slots t. Die Zeitumstellung (02:00/03:00) liegt im ersten Block 00–04 Uhr:
    am 29.03. hat er 12, am 25.10. 20 Viertelstunden (ns = 92 bzw. 100), alle anderen 16."""
    shift = ns - 96
    return 0 if t < BLOCK + shift else (t - shift) // BLOCK


def optimise(price, afrr, fcr, allow_reserve=True, plant: PlantConfig = PLANT, detail=False, electro=True, afrr_neg=None):
    # afrr = Preis aFRR positiv, afrr_neg = negativ ((EUR/MW)/h); ohne afrr_neg gilt für beide Richtungen afrr.
    afrr_neg = afrr if afrr_neg is None else afrr_neg
    ns, dt, P = plant.slots_per_day, plant.dt_h, plant.p_bhkw_mw
    nblock = NBLOCK
    hours = [sum(1 for t in range(ns) if block_of(t, ns) == b) * dt for b in range(nblock)]  # 4 h, am Umstellungstag 3/5 h
    m = pulp.LpProblem("coopt", pulp.LpMaximize)
    # per-block reserve products (constant within a 4h block)
    rp = [pulp.LpVariable(f"rp{b}", 0, P) for b in range(nblock)]   # aFRR up
    rn = [pulp.LpVariable(f"rn{b}", 0, P) for b in range(nblock)]   # aFRR down
    rf = [pulp.LpVariable(f"rf{b}", 0, P) for b in range(nblock)]   # FCR (symmetric)

    def no_reserve(_v):
        if not allow_reserve:
            for b in range(nblock):
                m.addConstraint(rp[b] == 0); m.addConstraint(rn[b] == 0); m.addConstraint(rf[b] == 0)

    def headroom(v, t):
        # reserve headroom: up (aFRR+ , FCR) above dispatch; down below to min-load
        b = block_of(t, ns)
        m.addConstraint(v.p[t] + rp[b] + rf[b] <= P * v.on[t])
        m.addConstraint(rn[b] + rf[b] <= v.p[t] - plant.min_load * P * v.on[t])

    v = add_plant(m, plant, ns, before_start=no_reserve, per_slot=headroom, electro=electro)
    rev = 0
    for t in range(ns):
        rev += (v.p[t] * price[t] * dt + v.p[t] * plant.heat_credit_eur_mwh * dt
                + v.px[t] * (plant.eta_ptx * plant.h2_value_eur_mwh - price[t] - plant.ptx_opex_eur_mwh) * dt)
    # capacity revenue: (EUR/MW)/h * Stunden je Block
    cap = pulp.lpSum((rp[b] * afrr + rn[b] * afrr_neg + rf[b] * fcr) * hours[b] for b in range(nblock))
    rev += cap - pulp.lpSum(v.su[t] * plant.start_cost_eur for t in range(ns))
    m += rev
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    cap_eur = sum((pulp.value(rp[b]) * afrr + pulp.value(rn[b]) * afrr_neg + pulp.value(rf[b]) * fcr) * hours[b]
                  for b in range(nblock))
    mw_res = sum(pulp.value(rp[b]) + pulp.value(rn[b]) + pulp.value(rf[b])
                 for b in range(nblock)) / nblock
    out = (pulp.value(m.objective), cap_eur, mw_res, pulp.LpStatus[m.status])
    if detail:   # zusätzlich der Fahrplan: BHKW- und Elektrolyse-Leistung je Slot + vorgehaltene Reserve je Slot
        val = lambda x: pulp.value(x) or 0.0  # noqa: E731
        reserve = [{"up_mw": val(rp[block_of(t, ns)]) + val(rf[block_of(t, ns)]),     # aFRR+ und FCR: Leistung nach oben frei
                    "down_mw": val(rn[block_of(t, ns)]) + val(rf[block_of(t, ns)])}   # aFRR− und FCR: nach unten
                   for t in range(ns)]
        out += ([val(v.p[t]) for t in range(ns)], [val(v.px[t]) for t in range(ns)], reserve)
    return out
