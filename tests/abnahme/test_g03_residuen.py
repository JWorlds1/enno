"""G03 (Review M4) Die Szenarien von stochastic/cvar kommen aus echten Abweichungen, nicht aus Randartefakten.

Vertrag: `optimizers.residuen(prices)` liefert die Abweichung vom gleitenden 1-h-Mittel, gleich lang wie prices,
und _stochastic nutzt genau diese Funktion.
"""
import inspect
import math

from fldos import optimizers as opt

GLATT = [60 + 40 * math.sin((i - 30) / 96 * 2 * math.pi) for i in range(96)]


def test_glatte_kurve_hat_kleine_residuen_auch_am_rand():
    r = list(opt.residuen(GLATT))
    assert len(r) == 96
    innen = max(abs(x) for x in r[4:-4])
    assert max(abs(x) for x in r) <= 3 * max(innen, 0.5), (r[:3], r[-3:], innen)


def test_stochastic_nutzt_die_residuen():
    assert "residuen(" in inspect.getsource(opt._stochastic)


def test_sprung_bleibt_sichtbar():
    p = [50.0] * 48 + [150.0] * 48
    assert max(abs(x) for x in opt.residuen(p)) > 20  # Positivkontrolle: echte Abweichung wird nicht weggeglättet
