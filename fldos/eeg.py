"""EEG-Erlöse eines Tagesfahrplans (Rechtsstand EEG 2023, 10/2026): gleitende Marktprämie + Flexibilitätszuschlag.

- Marktprämie MP = AW − MW, nie negativ (Anlage 1 Nr. 3.1.2); MW = Monatsmittel des Spotpreises (Anlage 1 Nr. 3.2).
- Keine Prämie in Zeiträumen mit negativem Spotpreis (§ 51).
- Biomethan aus der Ausschreibung: Prämie nur für eine Jahresmenge von 10 % der installierten Leistung (§ 39m Abs. 2)
  → je Tag im Jahresmittel `eeg_share × Leistung × 24 h`. ponytail: Tagesmittel; wann im Jahr die Menge am meisten
  bringt, rechnet die Seite EEG-Jahresbudget.
- Flexibilitätszuschlag § 50a: Euro je kW und Jahr, als Tagesanteil.
Die Prämie hängt nicht von der Uhrzeit ab (außer negativen Preisen) — sie ändert das Netto, kaum den Fahrplan.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from config import PlantConfig


def day(bhkw_mw: Sequence[float], prices: Sequence[float], plant: PlantConfig, marktwert: float) -> dict:
    gen_pos = sum(p * plant.dt_h for p, pr in zip(bhkw_mw, prices) if pr >= 0)  # § 51
    cap = plant.eeg_share * plant.p_bhkw_mw * 24  # § 39m: Jahresmenge, je Tag im Mittel
    eligible = min(gen_pos, cap)
    mp = max(0.0, plant.aw_eur_mwh - marktwert)
    return {"marktwert_eur_mwh": round(marktwert, 2), "praemie_eur_mwh": round(mp, 2),
            "praemie_mwh": round(eligible, 3), "eeg_premium_eur": eligible * mp,
            "flex_eur": plant.flex_eur_kw_a * plant.p_bhkw_mw * 1000 / 365}


def net_incl_eeg(result: dict, prices: Sequence[float], plant: PlantConfig, marktwert: float | None) -> float:
    """Das eine Netto im System (Was-wäre-wenn, Sensitivität, Enno): Optimierer-Netto (nach Gas) + Marktprämie +
    Flexzuschlag. Ohne veröffentlichten Monatsmarktwert bleibt es beim Netto ohne EEG."""
    if marktwert is None:
        return result["net_eur"]
    e = day(result["bhkw"], prices, plant, marktwert)
    return result["net_eur"] + e["eeg_premium_eur"] + e["flex_eur"]


def monthly_market_value(history_csv, d: date) -> float | None:
    """Monatsmittel des Day-Ahead-Preises (Marktzeit) im Monat von `d`, soweit veröffentlicht."""
    h = pd.read_csv(history_csv, usecols=["utc", "da_price_eur_mwh"], parse_dates=["utc"]).dropna()
    loc = h["utc"].dt.tz_convert("Europe/Berlin")
    m = h[(loc.dt.year == d.year) & (loc.dt.month == d.month)]["da_price_eur_mwh"]
    return float(m.mean()) if len(m) else None
