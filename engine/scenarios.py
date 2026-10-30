#!/usr/bin/env python3
"""
Shape-aware price scenario generation via moving-block bootstrap of forecast
residuals. Unlike comonotone quantile scenarios (level-only), this perturbs the
intraday SHAPE -> different hours expensive in different scenarios -> genuine
commitment uncertainty -> non-trivial VSS.
"""
import numpy as np


def residual_pool(actual, pred):
    r = np.asarray(actual) - np.asarray(pred)
    return r[np.isfinite(r)]


def make_scenarios(point_path, pool, n_scen, block=8, seed=42):
    """point_path: length-96 forecast; pool: 1D residual array.
    Returns list of n_scen price paths (point + block-bootstrapped residuals)."""
    rng = np.random.default_rng(seed)
    pool = pool - pool.mean()             # center -> scenarios unbiased around point
    T = len(point_path)
    scen = []
    for _ in range(n_scen):
        res = np.empty(T)
        i = 0
        while i < T:
            start = rng.integers(0, len(pool) - block)
            chunk = pool[start:start + block]
            res[i:i + len(chunk)] = chunk[:T - i]
            i += block
        scen.append(np.asarray(point_path) + res)
    return scen
