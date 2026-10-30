"""F07 Was-wäre-wenn bietet CVaR/Stochastisch/Co-Opt an — die Registry muss sie auch rechnen (heute 501)."""
import math

import pytest

from fldos import optimizers as opt

# Ein Tag in Viertelstunden: Tal nachts, Spitze abends — wie die Bestands-Tests, aber unabhängig von ihnen.
PRICES = [60 + 40 * math.sin((i - 30) / 96 * 2 * math.pi) for i in range(96)]


@pytest.mark.parametrize("algo", ["stochastic", "cvar", "coopt"])
def test_optimierer_ist_angebunden(algo):
    r = opt.run_algo(algo, PRICES, gas=70, h2=100, co2=79, mode="plasma")
    assert isinstance(r["net_eur"], float) and math.isfinite(r["net_eur"])
    assert len(r["bhkw"]) == len(r["electro"]) == len(r["pyro"]) == 96
    assert r["status"]


def test_unbekannter_name_bleibt_fehler():
    with pytest.raises(ValueError):
        opt.run_algo("gibt-es-nicht", PRICES)
