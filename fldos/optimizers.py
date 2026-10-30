"""Pluggable-Optimierer-Registry — die Naht, an der MA-Algorithmen einrasten.

Gleiche API (`fn(prices, **params) -> dict`), austauschbare Implementierung. Heute produktiv:
`whatif` (plasma-bewusst, parametrisiert), `schedule`, `stochastic`, `cvar`, `coopt`. `pareto` und `mpc`
sind reservierte Namen — Module existieren im Repo, werden
inkrementell angebunden; bis dahin klar erkennbar 501 statt stiller Falschantwort.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import backtest_forecast as bf
import coopt_milp
import numpy as np
import stochastic_cvar
import whatif
from scenarios import make_scenarios
from config import PLANT, PlantConfig

ALGOS: tuple[str, ...] = ("whatif", "schedule", "stochastic", "cvar", "coopt", "pareto", "mpc")


def _whatif(prices: list[float], gas: float = 70.0, h2: float = 100.0,
           co2: float = 79.0, mode: str = "plasma", plant: PlantConfig = PLANT) -> dict:
    return whatif.solve_day(prices, gas_cost=gas, h2_value=h2, carbon_eur_t=co2, ptx_mode=mode, plant=plant)


def _schedule(prices: list[float], gas: float = 70.0, plant: PlantConfig = PLANT, **_ignored) -> dict:
    """Deterministische Baseline (MILP ohne Plasma, feste Annahmen). Ökonomie konsistent zu
    backtest_forecast.settle/flat und zu _whatif — Netto inkl. Gaskosten, damit beide Optimierer
    direkt vergleichbar sind (Mehrerlös bleibt gas-unabhängig). Slider (außer Gas fürs Netto)
    wirken hier nicht (Referenzplan mit festen Annahmen)."""
    ns, dt = plant.slots_per_day, plant.dt_h
    pv, xv, status = bf.schedule(prices, plant)
    gas_total = gas * plant.gas_budget_mwh
    net = bf.settle(pv, xv, prices, plant) - gas_total
    fl = bf.flat(prices, plant) - gas_total
    spot = sum(pv[t] * prices[t] * dt for t in range(ns))
    heat = sum(pv[t] * plant.heat_credit_eur_mwh * dt for t in range(ns))
    h2_mwh = sum(xv) * dt * plant.eta_ptx
    h2_eur = sum(xv[t] * plant.eta_ptx * plant.h2_value_eur_mwh * dt for t in range(ns))
    elcost = sum(xv[t] * prices[t] * dt + xv[t] * plant.ptx_opex_eur_mwh * dt for t in range(ns))
    starts = sum(1 for t in range(1, ns) if pv[t] > 1e-6 and pv[t - 1] <= 1e-6)
    return {
        "bhkw": pv, "electro": xv, "pyro": [0.0] * ns,
        "net_eur": net, "flat_eur": fl, "uplift_eur": net - fl,
        "spot": spot, "heat": heat, "h2_eur": h2_eur, "carbon_eur": 0.0,
        "h2_mwh": h2_mwh, "carbon_t": 0.0, "elcost": elcost, "gas_cost": gas_total,
        "starts": starts, "bhkw_h": sum(1 for v in pv if v > 1e-6) * dt, "status": status,
    }


def residuen(prices: list[float]) -> np.ndarray:
    """Abweichung vom gleitenden 1-h-Mittel (4 Viertelstunden), gleich lang wie prices.
    Rand: letzter Wert wird fortgesetzt (mode='edge') — 'same' hätte dort mit Nullen aufgefüllt
    und Scheinabweichungen von ~Preis/4 erzeugt."""
    p = np.asarray(prices, dtype=float)
    return p - np.convolve(np.pad(p, (2, 1), mode="edge"), np.ones(4) / 4, "valid")


def _stochastic(prices: list[float], gas: float = 70.0, h2: float = 100.0, co2: float = 79.0,
                mode: str = "plasma", plant: PlantConfig = PLANT, lam: float = 0.0, n_scen: int = 8) -> dict:
    """Zweistufig stochastisch: Einsatz (on/off) einmal gegen Szenarien, danach Fahrplan auf den echten Preisen.
    lam = Gewicht des CVaR (0 = risikoneutral). Szenarien: Block-Bootstrap der Abweichung vom 1-h-Mittel des
    Tages (ohne Historie die einzige Residuenquelle) — bei glatten Preisen entsprechend schmal."""
    plant = replace(plant, h2_value_eur_mwh=h2)  # die Engine liest den H2-Wert aus der Anlage
    p = np.asarray(prices, dtype=float)
    scen = make_scenarios(p, residuen(p), n_scen)
    _, on, _ = stochastic_cvar.solve(scen, lam, plant=plant)
    return whatif.solve_day(prices, gas_cost=gas, h2_value=h2, carbon_eur_t=co2, ptx_mode=mode, plant=plant, on=on)


def _cvar(prices: list[float], lam: float = 0.5, **params) -> dict:
    return _stochastic(prices, lam=lam, **params)


def _coopt(prices: list[float], gas: float = 70.0, h2: float = 100.0, co2: float = 79.0, mode: str = "plasma",
           plant: PlantConfig = PLANT, afrr: float = 15.0, fcr: float = 18.0) -> dict:
    """Spot + Regelenergie + PtX gemeinsam. afrr/fcr = Kapazitätspreise €/MW·h (Default ≈ Datenmittel);
    das Modell kennt nur Elektrolyse, keine Pyrolyse — Elektrolyse läuft daher nur bei
    mode='electro', sonst aus (nie ein Elektrolyse-Fahrplan zu einem anderen Modus). net_eur enthält die
    Kapazitätserlöse (`capacity_eur`, `reserve_mw` zusätzlich)."""
    plant = replace(plant, h2_value_eur_mwh=h2)
    obj, cap, mw, status, pv, xv, _res = coopt_milp.optimise(prices, afrr, fcr, plant=plant, detail=True, electro=mode == "electro")
    r = whatif.kpis(prices, pv, xv, [0.0] * plant.slots_per_day, obj, status, gas, h2, co2, plant)
    return {**r, "capacity_eur": cap, "reserve_mw": mw}


# Produktiv verdrahtet: whatif (plasma-bewusst), schedule (deterministische Baseline), stochastic/cvar/coopt.
# pareto/mpc brauchen andere Eingaben (CO₂-Intensität bzw. Rolling-Horizont) → bewusst 501.
REGISTRY: dict[str, Callable[..., dict]] = {
    "whatif": _whatif, "schedule": _schedule, "stochastic": _stochastic, "cvar": _cvar, "coopt": _coopt,
}


def run_algo(algo: str, prices: list[float], **params) -> dict:
    if algo not in ALGOS:
        raise ValueError(f"unknown algo {algo!r}; known: {ALGOS}")
    fn = REGISTRY.get(algo)
    if fn is None:
        raise NotImplementedError(f"algo {algo!r} not yet wired")
    plant = params.pop("plant", PLANT)
    if len(prices) != plant.slots_per_day:  # Zeitumstellung: 92/100 Viertelstunden → Anlage mit genau so vielen Slots
        plant = replace(plant, slots_per_day=len(prices))
    return fn(prices, plant=plant, **params)
