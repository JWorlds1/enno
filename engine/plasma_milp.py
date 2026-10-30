#!/usr/bin/env python3
"""
FLD-spezifisch: Plasma-Pyrolyse statt Standard-Elektrolyse.

Kerndifferenz zur Elektrolyse (px aus Netzstrom + Wasser):
  Plasma-Pyrolyse spaltet METHAN  ->  fester Kohlenstoff + H2  ("türkiser" H2)
  - Feedstock = Biomethan aus DEMSELBEN Gasspeicher  -> konkurriert mit dem BHKW
  - nur ~25% der Elektrolyse-Strommenge je kg H2
  - zwei Wertströme: H2 + fester Kohlenstoff (CO2-Senke / Produkt, kein CO2-Ausstoß)

Daraus wird eine GAS-ROUTING-Entscheidung je Slot: Gas -> Strom (Preis hoch)
oder Gas -> H2+Kohlenstoff (Preis niedrig). Vergleicht drei Betriebsmodi.
Das Modell ist das What-if-Modell mit Standardannahmen (H₂-Wert der Anlage, CO₂ 79 €/t).
"""
from config import PLANT, PlantConfig
from whatif import solve_day

CARBON_CREDIT_EUR_T = 79.0  # EUR je t CO2-Äquivalent (EUA-Niveau; CDR ggf. höher)
_MODE = {"power": "none", "electro": "electro", "pyro": "plasma"}


def solve(price, mode, plant: PlantConfig = PLANT):
    """mode: 'power' (nur BHKW) | 'electro' (+Netz-Elektrolyse) | 'pyro' (+Plasma-Pyrolyse).
    → (Zielwert ohne Gaskosten, Gas→Pyrolyse MWh, H₂ MWh, Kohlenstoff t)"""
    r = solve_day(price, gas_cost=0.0, h2_value=plant.h2_value_eur_mwh, carbon_eur_t=CARBON_CREDIT_EUR_T,
                  ptx_mode=_MODE[mode], plant=plant)
    gas_pyro = sum(r["pyro"]) * plant.dt_h
    return r["net_eur"], gas_pyro, r["h2_mwh"], r["carbon_t"]
