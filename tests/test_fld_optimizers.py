"""Unit-Tests der pluggable-Optimierer-Registry (pur, keine DB)."""
import pytest

import fldos.optimizers as opt

PRICES = [50.0 + (i % 24) for i in range(96)]


def test_whatif_algo_runs_and_returns_dispatch():
    r = opt.run_algo("whatif", PRICES, gas=70, h2=100, co2=79, mode="plasma")
    assert r["status"] == "Optimal"
    for k in ("net_eur", "uplift_eur", "bhkw", "electro", "pyro", "bhkw_h", "starts"):
        assert k in r
    assert len(r["bhkw"]) == 96


def test_schedule_algo_returns_full_comparable_dict():
    r = opt.run_algo("schedule", PRICES)
    assert r["status"] == "Optimal"
    for k in ("net_eur", "flat_eur", "uplift_eur", "bhkw", "electro", "pyro", "bhkw_h", "starts", "spot", "heat"):
        assert k in r
    assert len(r["bhkw"]) == 96 and len(r["pyro"]) == 96
    assert all(v == 0.0 for v in r["pyro"])  # Baseline hat kein Plasma


def test_schedule_and_whatif_same_shape():
    s = opt.run_algo("schedule", PRICES)
    w = opt.run_algo("whatif", PRICES, gas=70, h2=100, co2=79, mode="plasma")
    assert set(s.keys()) == set(w.keys())  # vergleichbar über dieselbe API
    assert len(s["bhkw"]) == len(w["bhkw"]) == 96


def test_cdr_sensitivity_sweep():
    from fldos.api import _compute_cdr
    d = _compute_cdr(PRICES, 70.0, 100.0)
    assert len(d["rows"]) == 9  # 80..240 in 20er-Schritten
    for k in ("co2", "plasma_net", "electro_net", "plasma_carbon_t", "plasma_h2_mwh", "plasma_pyro", "plasma_uplift"):
        assert k in d["rows"][0]
    # höherer CDR-Preis → mind. nicht weniger Kohlenstoff-Ausbeute (mehr Pyrolyse-Anreiz)
    assert d["rows"][-1]["plasma_carbon_t"] >= d["rows"][0]["plasma_carbon_t"]
    assert d["break_even_co2"] is None or isinstance(d["break_even_co2"], int)


def test_unknown_algo_raises_valueerror():
    with pytest.raises(ValueError):
        opt.run_algo("does-not-exist", PRICES)


def test_reserved_but_unwired_algo_raises_notimplemented():
    with pytest.raises(NotImplementedError):
        opt.run_algo("mpc", PRICES)


@pytest.mark.parametrize("n", [92, 100])  # Zeitumstellung: 29.03. hat 92, 25.10. hat 100 Viertelstunden
@pytest.mark.parametrize("algo", ["whatif", "schedule", "coopt"])
def test_dst_days_keep_every_slot(algo, n):
    r = opt.run_algo(algo, [50.0 + (i % 24) for i in range(n)], gas=70, h2=100, co2=79, mode="electro")
    assert len(r["bhkw"]) == n


def test_memory_adapter_keeps_dst_price_vector():
    """M-09: Speicher und Postgres liefern an Umstellungstagen beide alle 100 Preise (vorher Speicher: keine)."""
    import asyncio
    from datetime import date

    from fldos.storage import MemoryRepository

    repo = MemoryRepository("dst-test")
    rows = [{"slot": i, "ts": None, "pred_price": 50.0 + i, "bhkw_mw": 0.0, "electrolyser_mw": 0.0, "pyro_mw": None}
            for i in range(100)]
    asyncio.run(repo.save_run(date(2026, 10, 25), "schedule", {}, rows))
    assert len(asyncio.run(repo.prices_latest())) == 100
