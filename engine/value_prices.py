#!/usr/bin/env python3
"""
Preisrechner: fairer Wert für Wasserstoff und festen Kohlenstoff aus frei verfügbaren Marktdaten.

Für H₂ und festen Kohlenstoff gibt es keinen Börsenpreis je Viertelstunde wie beim Strom. Gerechnet wird nach dem
Ersatzkostenprinzip — „was müsste der Käufer sonst bezahlen?“ — mit Daten, die die Tageskette schon holt:
  - H₂:   grauer Wasserstoff aus Erdgas (Dampfreformierung) = Gas (TTF) + CO₂-Kosten (EUA) + Anlagenkosten
  - C:    als CO₂-Wert (EUA), als CO₂-Entnahme-Zertifikat (CORC-Index) oder als Industrieruß (Ölpreis Brent)
Die Faktoren sind Literatur-Richtwerte; sie gelten bis FLD Vertrags- oder Angebotspreise einträgt (Was-wäre-wenn,
Splitter: eigener Preis). Fehlen Öl- oder Wechselkursdaten, gibt es keinen Rußwert statt einer Schätzung.
"""
import math

GAS_KWH_PER_KG_H2 = 46.0     # Erdgas je kg grauem H₂ (Reformer inkl. Prozesswärme, Hu)
CO2_KG_PER_KG_H2 = 9.0       # CO₂ je kg grauem H₂
H2_FIXED_EUR_KG = 0.40       # Kapital- und Betriebskosten Reformer je kg
CO2_PER_C = 44 / 12          # kg CO₂ je kg gebundenem Kohlenstoff
CDR_EUR_T_CO2 = 130.0        # Puro.earth/Nasdaq CORC-Biochar-Index (März 2026: 130,14 €/t) — von Hand gepflegt
CDR_AS_OF = "2026-03"
OIL_T_PER_T_C = 1.7          # t Rußöl je t Industrieruß (Furnace-Verfahren)
BBL_PER_T = 7.33             # Barrel je Tonne Rohöl
FEED_SHARE_OF_BRENT = 0.75   # Rußöl (Schweröl-Rückstand) handelt unter Brent
BLACK_PROCESS_EUR_T = 400.0  # Herstellkosten je t Ruß ohne Rohstoff


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _de(v: float | None, dp: int = 2) -> str:
    """Zahl für die Anzeige in deutscher Schreibweise; fehlender Wert = „—“ (nie „None“)."""
    return "—" if v is None else f"{v:,.{dp}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def h2_grey(ttf_eur_mwh: float, eua_eur_t: float) -> float:
    """€/kg H₂, den ein Käufer heute für grauen Wasserstoff zahlen müsste."""
    return GAS_KWH_PER_KG_H2 / 1000 * ttf_eur_mwh + CO2_KG_PER_KG_H2 / 1000 * eua_eur_t + H2_FIXED_EUR_KG


def carbon_co2(eua_eur_t: float) -> float:
    """€/kg C, wenn jedes kg Kohlenstoff mit dem EU-CO₂-Preis bewertet wird (untere Grenze)."""
    return CO2_PER_C * eua_eur_t / 1000


def carbon_cdr() -> float:
    """€/kg C als CO₂-Entnahme-Zertifikat zum CORC-Indexpreis."""
    return CO2_PER_C * CDR_EUR_T_CO2 / 1000


def carbon_black(brent_usd_bbl: float | None, eurusd: float | None) -> float | None:
    """€/kg C als Industrieruß: Rußöl (aus Brent) + Herstellung. None ohne gültige Öl-/Wechselkursdaten."""
    brent, fx = _num(brent_usd_bbl), _num(eurusd)
    if brent is None or fx is None or brent <= 0 or fx <= 0:
        return None
    feed_eur_t = OIL_T_PER_T_C * BBL_PER_T * brent / fx * FEED_SHARE_OF_BRENT
    return (feed_eur_t + BLACK_PROCESS_EUR_T) / 1000


def prices(row: dict, factors: dict[str, float] | None = None) -> dict:
    """Alle Werte aus einer Zeile von external_market.csv, je mit Formel und Quelle (für die Anzeige).
    `factors`: Nachjustierung je Weg aus der Preisprüfung (price_check), z. B. {"black": 1.12}."""
    ttf, eua = _num(row.get("ttf_eur_mwh")), _num(row.get("eua_eur_t"))
    brent, fx = _num(row.get("brent_usd_bbl")), _num(row.get("eurusd"))
    h2 = h2_grey(ttf, eua) if ttf is not None and eua is not None else None
    out = {
        "as_of": str(row.get("date")),
        "h2": {"eur_kg": h2, "source": "Gas TTF (Yahoo) + CO₂ EUA (EEX)",
               "formula": f"{GAS_KWH_PER_KG_H2:.0f} kWh Gas × {_de(ttf)} €/MWh + {CO2_KG_PER_KG_H2:.0f} kg CO₂ × {_de(eua)} €/t "
                          f"+ {_de(H2_FIXED_EUR_KG)} € Anlagenkosten",
               "inputs": {"ttf_eur_mwh": ttf, "eua_eur_t": eua}},
        "carbon": {
            "co2": {"eur_kg": carbon_co2(eua) if eua is not None else None, "source": "CO₂ EUA (EEX)",
                    "formula": f"3,67 kg CO₂ je kg C × {_de(eua)} €/t", "inputs": {"eua_eur_t": eua}},
            "cdr": {"eur_kg": carbon_cdr(), "source": f"CORC-Biochar-Index (Puro.earth/Nasdaq, {CDR_AS_OF})",
                    "formula": f"3,67 kg CO₂ je kg C × {_de(CDR_EUR_T_CO2, 0)} €/t", "inputs": {"cdr_eur_t": CDR_EUR_T_CO2}},
            "black": {"eur_kg": carbon_black(brent, fx), "source": "Öl Brent + EUR/USD (Yahoo)",
                      "formula": f"{_de(OIL_T_PER_T_C, 1)} t Rußöl × {_de(BBL_PER_T)} bbl/t × {_de(brent)} $/bbl ÷ {_de(fx, 4)} $/€ × "
                                 f"{_de(FEED_SHARE_OF_BRENT)} + {_de(BLACK_PROCESS_EUR_T, 0)} € Herstellung je t",
                      "inputs": {"brent_usd_bbl": brent, "eurusd": fx}},
        },
    }
    for path, k in (factors or {}).items():
        item = out["h2"] if path == "h2" else out["carbon"].get(path)
        if item and item["eur_kg"] is not None and k != 1.0:
            item["eur_kg"] *= k
            item["formula"] += f" × {_de(k)} (nachjustiert an Referenzpreisen)"
    return out


def curve(rows: list[dict], eua_eur_t: float | None, eurusd: float | None, plant=None) -> list[dict]:
    """Preiskurve je Liefermonat: dieselben Formeln auf die Terminpreise (Gas, Öl); CO₂ und EUR/USD bleiben auf dem
    heutigen Wert (keine freien Monatskontrakte). Dazu die Splitter-Schwelle je Kohlenstoff-Verwertung."""
    import splitter
    from config import PLANT
    plant = plant or PLANT
    eua, fx = _num(eua_eur_t), _num(eurusd)
    cols = {c: _interior([_num(r.get(c)) for r in rows]) for c in ("ttf_eur_mwh", "brent_usd_bbl")}
    out = []
    for i, r in enumerate(rows):
        ttf, brent = cols["ttf_eur_mwh"][i][0], cols["brent_usd_bbl"][i][0]
        h2 = h2_grey(ttf, eua) if ttf is not None and eua is not None else None
        carbon = {"co2": carbon_co2(eua) if eua is not None else None, "cdr": carbon_cdr(),
                  "black": carbon_black(brent, fx)}
        out.append({"month": str(r["month"]), "ttf_eur_mwh": ttf, "brent_usd_bbl": brent, "h2": h2, "carbon": carbon,
                    "interpolated": [c for c in cols if cols[c][i][1]],
                    "threshold": {k: splitter.threshold(h2, v, plant) if h2 is not None and v is not None else None
                                  for k, v in carbon.items()}})
    return out


def _interior(vals: list[float | None]) -> list[tuple[float | None, bool]]:
    """Lücken ZWISCHEN zwei bekannten Monaten linear füllen (→ Wert, interpoliert?); Ränder bleiben leer."""
    known = [i for i, v in enumerate(vals) if v is not None]
    out: list[tuple[float | None, bool]] = [(v, False) for v in vals]
    for a, b in zip(known, known[1:]):
        for i in range(a + 1, b):
            out[i] = (vals[a] + (vals[b] - vals[a]) * (i - a) / (b - a), True)
    return out
