"""Vergleichstest: Der Umbau der Engine darf mit Standard-Anlage kein Ergebnis verändern.

Eingaben und erwartete Ausgaben stehen in golden/engine_baseline.json (erzeugt mit dem Code VOR dem Umbau).
Verglichen werden Zielwerte UND Fahrpläne — ein anderer Fahrplan bei gleichem Zielwert würde den
Backtest (Planung auf Prognose, Abrechnung auf Ist) verschieben.
"""
import json
from pathlib import Path

import numpy as np
import pytest

import backtest_forecast as bf
import coopt_milp
import mpc
import pareto_milp
import plasma_milp
import stochastic_cvar
import whatif

G = json.loads((Path(__file__).parent / "golden" / "engine_baseline.json").read_text())
CASES = G["cases"]
TOL = 1e-4


def close(a, b):
    np.testing.assert_allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), atol=TOL, rtol=1e-7)


@pytest.mark.parametrize("c", CASES, ids=[c["day"] for c in CASES])
def test_whatif_and_plasma(c):
    for mode, exp in c["whatif"].items():
        got = whatif.solve_day(c["actual"], 85.0, 120.0, 90.0, mode)
        for k, v in exp.items():
            close(got[k], v)
    for mode, exp in c["plasma"].items():
        close(plasma_milp.solve(c["actual"], mode), exp)


@pytest.mark.parametrize("c", CASES, ids=[c["day"] for c in CASES])
def test_schedule_backtest(c):
    pv, xv, st = bf.schedule(c["pred"])
    assert st == c["schedule"]["status"]
    close(pv, c["schedule"]["p"])
    close(xv, c["schedule"]["x"])
    close(bf.settle(pv, xv, c["actual"]), c["schedule"]["settle"])
    close(bf.flat(c["actual"]), c["schedule"]["flat"])


@pytest.mark.parametrize("c", CASES, ids=[c["day"] for c in CASES])
def test_coopt_and_pareto(c):
    for res in (False, True):
        close(coopt_milp.optimise(c["actual"], 18.7, 20.5, allow_reserve=res)[:3], c["coopt"][str(res)])
    close(pareto_milp.solve(c["actual"], c["inten"], 80.0)[:2], c["pareto"]["free"])
    close(pareto_milp.solve_co2max(c["actual"], c["inten"], 80.0), c["pareto"]["co2max"])
    _, c_lo, _ = pareto_milp.solve(c["actual"], c["inten"], 80.0)
    floor = (c_lo + c["pareto"]["co2max"]) / 2
    close(pareto_milp.solve(c["actual"], c["inten"], 80.0, co2_floor=floor)[:2], c["pareto"]["floor"])


@pytest.mark.parametrize("c", CASES, ids=[c["day"] for c in CASES])
def test_cvar(c):
    scen = [np.asarray(s) for s in c["scen"]]
    e = c["cvar"]
    rp, on_rp, cv0 = stochastic_cvar.solve(scen, lam=0.0)
    close([rp, cv0], [e["rp"], e["cv0"]])
    assert on_rp == e["on_rp"]
    ep5, on5, cv5 = stochastic_cvar.solve(scen, lam=0.5)
    close([ep5, cv5], [e["ep5"], e["cv5"]])
    assert on5 == e["on5"]
    assert stochastic_cvar.solve([np.asarray(c["pred"])], lam=0.0)[1] == e["on_ev"]
    close(stochastic_cvar.solve(scen, lam=0.0, fixed_on=e["on_ev"])[0], e["eev"])
    close(stochastic_cvar.solve(scen, lam=0.0, ws=True)[0], e["ws"])


def test_mpc():
    m = G["mpc"]
    pv, xv, lv = mpc.optimise(m["pred2"], bf.S_MAX * 0.5, cyclic=False)
    close(pv, m["p"]); close(xv, m["x"]); close(lv, m["lvl"])
    pv1, xv1, lv1 = mpc.optimise(m["pred2"][:bf.NS], bf.S_MAX * 0.5, cyclic=True)
    close(pv1, m["p1"]); close(xv1, m["x1"]); close(lv1, m["lvl1"])
    close(mpc.settle(pv[:bf.NS], xv[:bf.NS], CASES[0]["actual"]), m["settle"])
