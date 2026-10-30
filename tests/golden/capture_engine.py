"""Hält die Ergebnisse aller Engine-Modelle mit Standard-Anlage fest (Eingaben + Ausgaben).

Einmal VOR dem Umbau laufen lassen: python tests/golden/capture_engine.py
Der Test test_engine_golden.py rechnet mit denselben Eingaben nach und vergleicht.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_forecast as bf
import coopt_milp
import mpc
import pareto_milp
import plasma_milp
import scenarios
import stochastic_cvar
import whatif
from config import ROOT

OUT = Path(__file__).with_name("engine_baseline.json")
R = 6  # Nachkommastellen


def r(x):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r(v) for v in x]
    return None if x is None else round(float(x), R)


def main() -> None:
    fc = pd.read_csv(ROOT / "forecasts.csv", parse_dates=["utc"])
    fc["day"] = fc["utc"].dt.date
    days = [d for d, g in fc.groupby("day") if len(g) == bf.NS][-3:]
    g = fc.set_index("day")
    hist = pd.read_csv(ROOT / "history.csv", usecols=["utc", "ren_share_load_pct"], parse_dates=["utc"])
    hist["day"] = hist["utc"].dt.date
    h = hist.set_index("day")
    pool = scenarios.residual_pool(fc["actual"], fc["pred_B"])

    cases = []
    for d in days:
        pred, act = g.loc[d, "pred_B"].tolist(), g.loc[d, "actual"].tolist()
        inten = (pareto_milp.INT_MAX * (1 - h.loc[d, "ren_share_load_pct"].clip(0, 100) / 100)).tolist()
        c = {"day": str(d), "pred": r(pred), "actual": r(act), "inten": r(inten)}

        c["whatif"] = {mode: {k: r(v) for k, v in whatif.solve_day(act, 85.0, 120.0, 90.0, mode).items() if k != "status"}
                       for mode in ("none", "electro", "plasma")}
        pv, xv, st = bf.schedule(pred)
        c["schedule"] = {"p": r(pv), "x": r(xv), "status": st, "settle": r(bf.settle(pv, xv, act)), "flat": r(bf.flat(act))}
        c["plasma"] = {mode: r(plasma_milp.solve(act, mode)) for mode in ("power", "electro", "pyro")}
        c["coopt"] = {str(res): r(coopt_milp.optimise(act, 18.7, 20.5, allow_reserve=res)[:3]) for res in (False, True)}
        _, c_lo, _ = pareto_milp.solve(act, inten, 80.0)
        c_hi = pareto_milp.solve_co2max(act, inten, 80.0)
        c["pareto"] = {"free": r(pareto_milp.solve(act, inten, 80.0)[:2]),
                       "floor": r(pareto_milp.solve(act, inten, 80.0, co2_floor=(c_lo + c_hi) / 2)[:2]),
                       "co2max": r(c_hi)}
        scen = scenarios.make_scenarios(pred, pool, 4, block=8)
        c["scen"] = r([list(s) for s in scen])
        rp, on_rp, cv0 = stochastic_cvar.solve(scen, lam=0.0)
        ep5, on5, cv5 = stochastic_cvar.solve(scen, lam=0.5)
        on_ev = stochastic_cvar.solve([np.asarray(pred)], lam=0.0)[1]
        eev = stochastic_cvar.solve(scen, lam=0.0, fixed_on=on_ev)[0]
        ws = stochastic_cvar.solve(scen, lam=0.0, ws=True)[0]
        c["cvar"] = {"rp": r(rp), "cv0": r(cv0), "on_rp": on_rp, "ep5": r(ep5), "cv5": r(cv5), "on5": on5,
                     "on_ev": on_ev, "eev": r(eev), "ws": r(ws)}
        cases.append(c)

    # MPC über die 3 Tage (Zustand getragen) + tagesisoliert
    two = sum((g.loc[d, "pred_B"].tolist() for d in days[:2]), [])
    pv, xv, lv = mpc.optimise(two, bf.S_MAX * 0.5, cyclic=False)
    pv1, xv1, lv1 = mpc.optimise(g.loc[days[0], "pred_B"].tolist(), bf.S_MAX * 0.5, cyclic=True)
    mpc_case = {"pred2": r(two), "p": r(pv), "x": r(xv), "lvl": r(lv), "p1": r(pv1), "x1": r(xv1), "lvl1": r(lv1),
                "settle": r(mpc.settle(pv[:bf.NS], xv[:bf.NS], g.loc[days[0], "actual"].tolist()))}

    OUT.write_text(json.dumps({"cases": cases, "mpc": mpc_case}))
    print(f"geschrieben: {OUT} ({OUT.stat().st_size // 1024} KB, {len(cases)} Tage)")


if __name__ == "__main__":
    main()
