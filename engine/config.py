#!/usr/bin/env python3
"""
Central typed configuration for the FLD optimisation stack.
Single source of truth for plant parameters and data paths; a consistency test
(tests/test_core.py) guards against drift vs. the legacy module constants.
"""
import os
from dataclasses import dataclass, replace
from pathlib import Path

# Daten liegen außerhalb des Codes (gitignored) — per FLD_DATA_DIR umlenkbar.
ROOT = Path(os.environ.get("FLD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


@dataclass(frozen=True)
class PlantConfig:
    # BHKW
    p_bhkw_mw: float = 1.0          # installed electrical power
    eta_el: float = 0.42            # electrical efficiency (gas -> el)
    min_load: float = 0.50          # min load fraction when running
    start_cost_eur: float = 50.0    # EUR per start
    full_hours_per_day: float = 8.0 # gas budget = full-power hours/day
    storage_hours: float = 8.0      # gas buffer in full-power-hours
    heat_min_runtime_slots: int = 16  # >=4h must-run (heat baseload)
    heat_credit_eur_mwh: float = 15.0
    min_up_slots: int = 4           # min. Laufzeit nach Start (4 × 15 min)
    min_down_slots: int = 4         # min. Stillstand nach Stopp
    # electrolyser / PtX
    p_el_mw: float = 0.5
    eta_ptx: float = 0.62
    h2_value_eur_mwh: float = 100.0
    ptx_opex_eur_mwh: float = 8.0
    # Plasma-Pyrolyse (CH4 -> C + 2 H2), Gas aus demselben Speicher wie das BHKW
    eta_pyro_h2: float = 0.60           # MWh_H2 je MWh_gas
    plasma_el_per_gas: float = 0.24     # MWh_el je MWh_gas
    carbon_t_per_gas: float = 0.054     # t fester Kohlenstoff je MWh_gas
    pyro_max_gas_mwh: float = 0.5       # max. MWh_gas je Slot in die Pyrolyse
    # Splitter: FLD-Verhältnis aus DERSELBEN Gasmenge (Angabe FLD, 17.10.2026): Strom ODER H₂ + fester Kohlenstoff
    split_el_kwh: float = 250.0
    split_h2_kg: float = 5.6
    split_c_kg: float = 19.0
    split_plasma_kwh: float = 0.0       # Netzstrom fürs Plasma je Gaseinheit; 0 = autark, im Verhältnis enthalten
    # market / emissions
    bio_premium_eur_mwh: float = 40.0   # biomethane premium over fossil TTF
    grid_co2_max_t_mwh: float = 0.70    # intensity at zero renewable share
    # EEG 2023 (Stand 10/2026) — je Anlage verschieden, Standard = Biomethan-Ausschreibung
    aw_eur_mwh: float = 231.2           # anzulegender Wert; Ø-Zuschlag Biomethan-Ausschreibung 01.09.2026 (BNetzA)
    eeg_share: float = 0.10             # Anteil inst. Leistung mit Prämie als Jahresmenge (§ 39m Abs. 2; Biogas § 39i: ~0,45)
    flex_eur_kw_a: float = 0.0          # Flexibilitätszuschlag § 50a: 100 €/kW·a, falls Anspruch besteht (für Biomethan zu klären)
    # time grid
    dt_h: float = 0.25
    slots_per_day: int = 96

    @property
    def gas_budget_mwh(self) -> float:
        return self.p_bhkw_mw * self.full_hours_per_day / self.eta_el

    @property
    def storage_max_mwh(self) -> float:
        return self.p_bhkw_mw * self.storage_hours / self.eta_el

    @property
    def gas_in_per_slot_mwh(self) -> float:
        return self.gas_budget_mwh / self.slots_per_day

    def with_overrides(self, overrides: dict | None) -> "PlantConfig":
        """Neue Anlage mit importierten Werten; unbekannte Schlüssel sind ein Fehler, keine stille Ignoranz."""
        if not overrides:
            return self
        unknown = set(overrides) - set(self.__dataclass_fields__)
        if unknown:
            raise KeyError(f"unbekannte Anlagenparameter: {sorted(unknown)}")
        typed = {k: type(getattr(self, k))(v) for k, v in overrides.items()}
        return replace(self, **typed)


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    history: Path = ROOT / "history.csv"
    forecasts: Path = ROOT / "forecasts.csv"
    external: Path = ROOT / "external_market.csv"
    regelenergie: Path = ROOT / "regelenergie.csv"
    quantiles: Path = ROOT / "quantiles.csv"


PLANT = PlantConfig()
PATHS = Paths()
