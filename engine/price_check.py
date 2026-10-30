#!/usr/bin/env python3
"""
Preisprüfung: die Formeln des Preisrechners gegen öffentliche Referenzpunkte (Datum, Quelle, Link).

Regel (vereinbart 17.10.2026):
  - vergleichbare Referenz (gleiches Produkt): Abweichung ≤ 15 % → „geprüft“; sonst „nachjustiert“ mit dem
    Median-Faktor Referenz/Formel, der dann auf den Formelwert angewendet wird;
  - nur andersartige Referenz (grüner statt grauer H₂): „plausibel (grau unter grün)“ oder „unplausibel“;
  - ohne Marktdaten am Referenztag: „nicht geprüft“ (kein erfundener Abgleich).
Referenzen sind Momentaufnahmen aus frei zugänglichen Veröffentlichungen; sie ersetzen keinen Vertragspreis.
"""
import statistics

import pandas as pd

import value_prices as vp

TOLERANCE = 0.15

REFS: list[dict] = [
    {"path": "black", "date": "2026-02-15", "value": 1.66, "unit": "USD/kg", "comparable": True,
     "source": "IMARC, Industrieruß Europa, Feb. 2026", "url": "https://www.imarcgroup.com/carbon-black-pricing-report"},
    {"path": "black", "date": "2026-07-15", "value": 1.51, "unit": "USD/kg", "comparable": True,
     "source": "Business Analytiq, Industrieruß Europa, Juli 2026",
     "url": "https://businessanalytiq.com/procurementanalytics/index/carbon-black-price-index/"},
    {"path": "black", "date": "2025-11-15", "value": 1.00, "unit": "USD/kg", "comparable": False,
     "note": "Importpreis aus China (CFR Deutschland), andere Qualität — nur zur Einordnung",
     "source": "Intratec, Nov. 2025", "url": "https://www.intratec.us/chemical-markets/carbon-black-price"},
    {"path": "cdr", "date": "2026-03-15", "value": 130.14, "unit": "EUR/tCO2", "comparable": True,
     "source": "CORC-Biochar-Index (Puro.earth/Nasdaq), März 2026", "url": "https://puro.earth/carbon-removal-index-price"},
    {"path": "h2", "date": "2025-08-15", "value": 5.34, "unit": "EUR/kg", "comparable": False,
     "note": "grüner H₂ (Kostenindex) — Obergrenze für grauen H₂", "source": "E-Bridge Hydex Green, Aug. 2025",
     "url": "https://www.energate-messenger.com/news/255340/marginal-costs-of-green-hydrogen-almost-unchanged"},
    {"path": "h2", "date": "2025-08-18", "value": 7.83, "unit": "EUR/kg", "comparable": False,
     "note": "grüner H₂ (PPA-basiert, Deutschland) — Obergrenze für grauen H₂", "source": "S&P Platts, Aug. 2025",
     "url": "https://www.spglobal.com/energy/en/pricing-benchmarks/our-methodology/subscriber-notes/081925-platts-corrects-european-renewable-ppa-derived-hydrogen-assessments-for-aug-18"},
]


def _row_at(ext: pd.DataFrame, day: str) -> dict | None:
    """Marktdaten am Referenztag (sonst der letzte Handelstag davor), vorwärts gefüllt."""
    e = ext.assign(date=pd.to_datetime(ext["date"])).sort_values("date").ffill()
    e = e[e["date"] <= pd.Timestamp(day)]
    return None if e.empty else e.iloc[-1].to_dict()


def _formula(path: str, row: dict) -> float | None:
    if path == "h2":
        ttf, eua = vp._num(row.get("ttf_eur_mwh")), vp._num(row.get("eua_eur_t"))
        return vp.h2_grey(ttf, eua) if ttf is not None and eua is not None else None
    if path == "black":
        return vp.carbon_black(row.get("brent_usd_bbl"), row.get("eurusd"))
    if path == "cdr":
        return vp.carbon_cdr()
    return None


def _ref_eur_kg(ref: dict, row: dict) -> float | None:
    if ref["unit"] == "EUR/kg":
        return ref["value"]
    if ref["unit"] == "EUR/tCO2":
        return ref["value"] * vp.CO2_PER_C / 1000
    if ref["unit"] == "USD/kg":
        fx = vp._num(row.get("eurusd"))
        return ref["value"] / fx if fx else None
    return None


def validate(ext: pd.DataFrame) -> dict:
    """→ je Weg (h2, co2, cdr, black): Status, Faktor (1 = Formel unverändert) und die einzelnen Referenzen."""
    out: dict = {"co2": {"status": "Marktpreis (EUA)", "factor": 1.0, "refs": []}}
    for path in ("h2", "cdr", "black"):
        refs = []
        for ref in (r for r in REFS if r["path"] == path):
            row = _row_at(ext, ref["date"])
            f = _formula(path, row) if row else None
            v = _ref_eur_kg(ref, row) if row else None
            refs.append({"date": ref["date"], "source": ref["source"], "url": ref["url"], "comparable": ref["comparable"],
                         "note": ref.get("note"), "ref_eur_kg": v, "formula_eur_kg": f,
                         "deviation_pct": 100 * (f / v - 1) if f is not None and v else None})
        comp = [r for r in refs if r["comparable"] and r["deviation_pct"] is not None]
        other = [r for r in refs if not r["comparable"] and r["deviation_pct"] is not None]
        factor, status = 1.0, "nicht geprüft"
        if comp:
            if max(abs(r["deviation_pct"]) for r in comp) <= 100 * TOLERANCE:
                status = "geprüft"
            else:
                factor = statistics.median(r["ref_eur_kg"] / r["formula_eur_kg"] for r in comp)
                status = "nachjustiert"
        elif other and path == "h2":
            status = "plausibel (grau unter grün)" if all(r["formula_eur_kg"] < r["ref_eur_kg"] for r in other) else "unplausibel"
        out[path] = {"status": status, "factor": factor, "refs": refs}
    return out


def factors(check: dict) -> dict[str, float]:
    """Faktoren für value_prices.prices(…, factors=…): nur nachjustierte Wege."""
    return {k: v["factor"] for k, v in check.items() if v["status"] == "nachjustiert"}
