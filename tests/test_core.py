"""
Core invariant tests for the FLD optimisation stack.
Self-contained tests use synthetic inputs; data-dependent tests skip if the
generated CSVs are absent (so CI without data still passes the logic tests).
"""
import os
import numpy as np
import pytest

import config
import backtest_forecast as bf
import scenarios
import coopt_milp


# ---- config consistency (single source of truth vs legacy constants) -----
def test_config_matches_module_constants():
    c = config.PLANT
    assert c.p_bhkw_mw == bf.P_BHKW
    assert c.eta_el == bf.ETA_EL
    assert c.min_load == bf.MINLOAD
    assert c.heat_min_runtime_slots == bf.HEAT_MINRUN
    assert abs(c.gas_budget_mwh - bf.G_DAY) < 1e-9
    assert abs(c.storage_max_mwh - bf.S_MAX) < 1e-9


# ---- scenario generation -------------------------------------------------
def test_scenarios_shape_and_centered():
    point = list(np.linspace(50, 150, bf.NS))
    pool = np.random.default_rng(0).normal(0, 20, 5000)
    scen = scenarios.make_scenarios(point, pool, n_scen=15, block=8, seed=1)
    assert len(scen) == 15
    assert all(len(s) == bf.NS for s in scen)
    # residuals are centered -> scenario mean tracks the point path closely
    mean_path = np.mean(scen, axis=0)
    assert abs(np.mean(mean_path - np.array(point))) < 10


# ---- MILP schedule invariants -------------------------------------------
def test_schedule_feasible_and_constrained():
    rng = np.random.default_rng(2)
    price = list(50 + 60 * np.sin(np.linspace(0, 6.28, bf.NS)) + rng.normal(0, 10, bf.NS))
    pv, xv, status = bf.schedule(price)
    assert status == "Optimal"
    assert max(pv) <= bf.P_BHKW + 1e-6                       # capacity
    running = sum(1 for v in pv if v > 1e-6)
    assert running >= bf.HEAT_MINRUN                         # heat must-run
    gas = sum(v / bf.ETA_EL * bf.DT for v in pv)
    assert abs(gas - bf.G_DAY) < 1e-3                        # daily gas budget


def test_minload_respected():
    price = [80.0] * bf.NS
    pv, _, _ = bf.schedule(price)
    for v in pv:
        assert v == 0 or v >= bf.MINLOAD * bf.P_BHKW - 1e-6  # off or >= min-load


# ---- co-optimisation dominance ------------------------------------------
def test_coopt_never_worse_than_spot_only():
    rng = np.random.default_rng(3)
    price = list(70 + 50 * np.sin(np.linspace(0, 6.28, bf.NS)) + rng.normal(0, 8, bf.NS))
    spot, _, _, _ = coopt_milp.optimise(price, 18.0, 20.0, allow_reserve=False)
    co, _, _, st = coopt_milp.optimise(price, 18.0, 20.0, allow_reserve=True)
    assert st == "Optimal"
    assert co >= spot - 1e-3        # adding a revenue stream cannot reduce optimum


# ---- conformal coverage property (toy) ----------------------------------
def test_conformal_widening_increases_coverage():
    rng = np.random.default_rng(4)
    y = rng.normal(0, 1, 2000)
    lo, hi = -0.5 * np.ones_like(y), 0.5 * np.ones_like(y)   # too-narrow interval
    base = np.mean((y >= lo) & (y <= hi))
    q = 1.0
    wide = np.mean((y >= lo - q) & (y <= hi + q))
    assert wide > base                                       # widening raises coverage


# ---- data schema (skip if not generated) --------------------------------
@pytest.mark.skipif(not os.path.exists(config.PATHS.external),
                    reason="external_market.csv not generated")
def test_external_market_schema():
    import pandas as pd
    df = pd.read_csv(config.PATHS.external)
    assert {"date", "ttf_eur_mwh", "eua_eur_t"} <= set(df.columns)
    assert (df["eua_eur_t"].dropna() > 0).all()
