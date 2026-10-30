"""G04 (Review M5) coopt widerspricht nie dem gewählten PtX-Pfad: ohne Elektrolyse-Modus keine Elektrolyse."""
import math

import pytest

from fldos import optimizers as opt

PRICES = [60 + 40 * math.sin((i - 30) / 96 * 2 * math.pi) for i in range(96)]


@pytest.mark.parametrize("mode", ["none", "plasma"])
def test_kein_electro_ausser_im_electro_modus(mode):
    try:
        r = opt.run_algo("coopt", PRICES, gas=70, h2=100, co2=79, mode=mode)
    except ValueError:
        return  # ablehnen ist erlaubt (→ 400), still falsch rechnen nicht
    assert sum(r["electro"]) == 0, (mode, sum(r["electro"]))


def test_electro_modus_rechnet_weiter():
    r = opt.run_algo("coopt", PRICES, gas=70, h2=100, co2=79, mode="electro")
    assert math.isfinite(r["net_eur"]) and len(r["electro"]) == 96
