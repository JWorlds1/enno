#!/usr/bin/env python3
"""
Splitter: je Viertelstunde geht das Gas in den Weg mit dem höheren Erlös — Strom (BHKW) oder H₂ + fester Kohlenstoff
(Plasma-Pyrolyse). Grundlage ist FLDs Verhältnis aus derselben Gasmenge (Anlagendaten split_*): standardmäßig
250 kWh Strom ODER 5,6 kg H₂ + 19 kg Kohlenstoff; braucht das Plasma Strom, der nicht schon im Verhältnis steckt,
zählt er zum Marktpreis (split_plasma_kwh, Standard 0 = FLD-Angabe „autark“).

Strom lohnt, sobald  Strompreis ≥ Schwelle = (kg H₂ × H₂-Preis + kg C × C-Preis) / (MWh Strom + MWh Plasma-Strom).

Betrieb statt Rechenübung:
  - Sicherheitsabstand (margin): auf der Prognose wird nur umgeschaltet, wenn der Preis die Schwelle um mehr als den
    Prognosefehler kreuzt — sonst bleibt der bisherige Weg (kein Hin und Her bei knappen Viertelstunden).
  - Mindestlaufzeit (min_run): kürzere Strom-Läufe gehen ins Plasma (keine Zacken unter 1 h).
  - Prognoseband (p10/p90): eine Viertelstunde ist sicher, wenn das ganze Band auf einer Seite der Schwelle liegt.
Ohne Gasspeicher und Wärme — die rechnet die Optimierer-Variante (splitter_milp).
"""
from config import PlantConfig


def threshold(h2: float, c: float, plant: PlantConfig) -> float:
    """Strompreis in €/MWh, ab dem Strom mehr bringt als H₂ + Kohlenstoff."""
    return (plant.split_h2_kg * h2 + plant.split_c_kg * c) / ((plant.split_el_kwh + plant.split_plasma_kwh) / 1000)


def _blocks(route: list[str], times: list[str]) -> list[str]:
    out, start = [], None
    for i, r in enumerate(route):
        if r == "strom" and start is None:
            start = times[i]
        if r != "strom" and start is not None:
            out.append(f"{start}–{times[i]}")
            start = None
    if start is not None:
        out.append(f"{start}–24:00")
    return out


def _hysteresis(prices: list[float], thr: float, margin: float) -> list[bool]:
    out: list[bool] = []
    for p in prices:
        prev = out[-1] if out else None
        if prev is None:
            s = p >= thr
        elif p >= thr + margin:
            s = True
        elif p < thr - margin:
            s = False
        else:
            s = prev
        out.append(s)
    return out


def _min_run(strom: list[bool], k: int) -> list[bool]:
    s, i = list(strom), 0
    while i < len(s):
        if s[i]:
            j = i
            while j < len(s) and s[j]:
                j += 1
            if j - i < k:
                s[i:j] = [False] * (j - i)
            i = j
        else:
            i += 1
    return s


def _block_accept(prices: list[float], thr: float, block: int) -> list[bool]:
    """Wie die Börse ein Blockgebot mit Mindestpreis abrechnet: ganzer Block, wenn sein Ø-Preis ≥ Schwelle."""
    out: list[bool] = []
    for i in range(0, len(prices), block):
        chunk = prices[i:i + block]
        out += [sum(chunk) / len(chunk) >= thr] * len(chunk)
    return out


def bids(prices: list[float], h2: float, c: float, plant: PlantConfig, times: list[str], block: int = 4) -> list[dict]:
    """Gebotsvorschlag für die Day-Ahead-Auktion: je Block die BHKW-Leistung mit der Schwelle als Mindestpreis.
    `expected`: würde der Block bei den übergebenen (Prognose-)Preisen angenommen?"""
    thr = threshold(h2, c, plant)
    acc = _block_accept(prices, thr, block)
    out = []
    for i in range(0, len(prices), block):
        j = min(i + block, len(prices))
        out.append({"from": times[i], "to": times[j] if j < len(times) else "24:00", "mw": plant.p_bhkw_mw,
                    "limit_eur_mwh": thr, "forecast_eur_mwh": sum(prices[i:j]) / (j - i), "expected": acc[i]})
    return out


def split_day(prices: list[float], h2: float, c: float, plant: PlantConfig, times: list[str] | None = None,
              margin: float = 0.0, min_run: int = 1, p10: list[float] | None = None,
              p90: list[float] | None = None, settle: list[float] | None = None, block: int | None = None) -> dict:
    """Weg je Viertelstunde, Strom-Zeitblöcke und Erlös je Gaseinheit: Splitter vs. nur Strom vs. nur Plasma.
    `settle`: Preise für die Abrechnung (z. B. Ist), sonst die Planpreise.
    `block`: Ergebnis der Blockgebote (Ø-Preis je Block ≥ Schwelle) statt Viertelstunden-Regel — nach der Auktion."""
    thr = threshold(h2, c, plant)
    el, pel = plant.split_el_kwh / 1000, plant.split_plasma_kwh / 1000
    product = plant.split_h2_kg * h2 + plant.split_c_kg * c
    strom = _block_accept(prices, thr, block) if block else _min_run(_hysteresis(prices, thr, margin), min_run)
    route = ["strom" if s else "plasma" for s in strom]
    px = settle if settle is not None else prices
    power = [el * p for p in px]
    plasma = [product - pel * p for p in px]
    rev = {"splitter": sum(pw if s else pl for pw, pl, s in zip(power, plasma, strom)),
           "nur_strom": sum(power), "nur_plasma": sum(plasma)}
    sure = ([lo >= thr or hi < thr for lo, hi in zip(p10, p90)] if p10 is not None and p90 is not None
            else [True] * len(prices))
    return {"threshold": thr, "route": route, "strom_slots": sum(strom), "revenue": rev,
            "uplift_vs_best": rev["splitter"] - max(rev["nur_strom"], rev["nur_plasma"]),
            "switches": sum(1 for a, b in zip(strom, strom[1:]) if a != b),
            "sure": sure, "unsure_slots": sure.count(False),
            "blocks": _blocks(route, times) if times else []}
