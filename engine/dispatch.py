"""Der eine Rechenkern: BHKW + Gasspeicher (+ Elektrolyse, + Plasma-Pyrolyse) auf einem Preisvektor.

Alle Varianten (Fahrplan, What-if, Plasma, Co-Optimierung, CVaR, Pareto, MPC) bauen hierauf und fügen
nur ihren Zusatz hinzu (Reserve-Blöcke, CO₂-Zielfunktion, Szenarien, Horizont). Anlagenwerte kommen
ausschließlich aus `PlantConfig` — dadurch wirken importierte FLD-Anlagendaten überall.

Variablennamen und Reihenfolge der Bedingungen sind Teil des Interfaces: PuLP sortiert Variablen
nach Namen, CBC rechnet in dieser Reihenfolge. Gleiche Namen ⇒ identische Fahrpläne wie vor dem Umbau
(abgesichert durch tests/test_engine_golden.py).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pulp

from config import PLANT, PlantConfig

NAMES = {"p": "p", "on": "on", "su": "su", "sd": "sd", "lvl": "l", "px": "x", "gp": "g"}


@dataclass
class Plant:
    """Die Entscheidungsvariablen einer Anlage über den Horizont (Länge = len(prices))."""
    p: list                 # BHKW-Leistung MW_el
    on: list                # BHKW an/aus (binär oder fest vorgegeben)
    su: list                # Starts
    lvl: list               # Gasspeicher MWh_gas (Länge n+1)
    px: list                # Elektrolyse MW_el
    gp: list = field(default_factory=list)  # Gas → Pyrolyse MWh_gas/h
    sd: list = field(default_factory=list)  # Stopps (nur mit Min-up/down)


def add_plant(
    m: pulp.LpProblem,
    plant: PlantConfig,
    n: int,
    *,
    pfx: str = "",
    names: dict[str, str] | None = None,
    on: Sequence | None = None,
    s0: float | None = None,
    end: str = "ge_start",
    gas_budget: bool = True,
    electro: bool = True,
    pyro: bool | None = None,
    startup: bool = True,
    min_updown: bool = False,
    heat_mustrun: bool = False,
    before_start: Callable[[Plant], None] | None = None,
    per_slot: Callable[[Plant, int], None] | None = None,
) -> Plant:
    """Legt Variablen und Physik der Anlage in `m` an und gibt sie zurück.

    pyro: None = keine Pyrolyse-Variable; False = Variable angelegt, aber auf 0 fixiert; True = frei.
    electro=False fixiert die Elektrolyse auf 0 (Variable bleibt — gleiche Spalten wie vor dem Umbau).
    on: fest vorgegebener oder geteilter Einsatz (z. B. erste Stufe der Stochastik); dann ohne Starts.
    end: "ge_start" (Speicher am Ende ≥ Anfang) | "eq_start"/"eq_s0" (zyklisch) | "floor" (≥ 40 % voll).
    """
    nm = {**NAMES, **(names or {})}
    dt, smax, gin = plant.dt_h, plant.storage_max_mwh, plant.gas_in_per_slot_mwh
    P = plant.p_bhkw_mw

    p = [pulp.LpVariable(f"{pfx}{nm['p']}{t}", 0, P) for t in range(n)]
    own_on = on is None
    if own_on:
        on = [pulp.LpVariable(f"{pfx}{nm['on']}{t}", cat="Binary") for t in range(n)]
    su = [pulp.LpVariable(f"{pfx}{nm['su']}{t}", 0, 1) for t in range(n)] if (own_on and startup) else []
    sd = [pulp.LpVariable(f"{pfx}{nm['sd']}{t}", 0, 1) for t in range(n)] if (own_on and min_updown) else []
    lvl = [pulp.LpVariable(f"{pfx}{nm['lvl']}{t}", 0, smax) for t in range(n + 1)]
    px = [pulp.LpVariable(f"{pfx}{nm['px']}{t}", 0, plant.p_el_mw) for t in range(n)]
    gp = [pulp.LpVariable(f"{pfx}{nm['gp']}{t}", 0, plant.pyro_max_gas_mwh) for t in range(n)] if pyro is not None else []
    v = Plant(p=p, on=list(on), su=su, lvl=lvl, px=px, gp=gp, sd=sd)

    if not electro:
        for t in range(n):
            m += px[t] == 0
    if pyro is False:
        for t in range(n):
            m += gp[t] == 0
    if before_start:
        before_start(v)
    m += lvl[0] == (smax * 0.5 if s0 is None else s0)

    for t in range(n):
        m += p[t] <= P * v.on[t]
        m += p[t] >= plant.min_load * P * v.on[t]
        if per_slot:
            per_slot(v, t)
        draw = (p[t] / plant.eta_el) * dt + (gp[t] * dt if gp else 0)
        m += lvl[t + 1] == lvl[t] + gin - draw
        if su and t > 0:
            if min_updown:
                m += su[t] - sd[t] == v.on[t] - v.on[t - 1]
            else:
                m += su[t] >= v.on[t] - v.on[t - 1]
        if min_updown:
            if t >= plant.min_up_slots - 1:
                m += pulp.lpSum(su[k] for k in range(t - plant.min_up_slots + 1, t + 1)) <= v.on[t]
            if t >= plant.min_down_slots - 1:
                m += pulp.lpSum(sd[k] for k in range(t - plant.min_down_slots + 1, t + 1)) <= 1 - v.on[t]

    if end == "ge_start":
        m += lvl[n] >= lvl[0]
    elif end == "eq_start":
        m += lvl[n] == lvl[0]
    elif end == "eq_s0":
        m += lvl[n] == (smax * 0.5 if s0 is None else s0)
    elif end == "floor":
        m += lvl[n] >= smax * 0.4
    else:
        raise ValueError(f"end={end!r}")
    if heat_mustrun:
        m += pulp.lpSum(v.on[t] for t in range(n)) >= plant.heat_min_runtime_slots
    if gas_budget:
        m += pulp.lpSum((p[t] / plant.eta_el + (gp[t] if gp else 0)) * dt for t in range(n)) == plant.gas_budget_mwh
    return v


def flat_baseline(prices: Sequence[float], plant: PlantConfig = PLANT) -> float:
    """Dauerbetrieb: das Tagesgas gleichmäßig verstromt (ohne Gaskosten)."""
    pf = plant.gas_budget_mwh * plant.eta_el / (plant.slots_per_day * plant.dt_h)
    return sum(pf * a * plant.dt_h + pf * plant.heat_credit_eur_mwh * plant.dt_h for a in prices)


def carbon_rev_per_gas(plant: PlantConfig, carbon_eur_t: float) -> float:
    """€ je MWh_gas aus dem festen Kohlenstoff der Pyrolyse (als CO₂-Äquivalent gutgeschrieben)."""
    return plant.carbon_t_per_gas * (44 / 12) * carbon_eur_t
