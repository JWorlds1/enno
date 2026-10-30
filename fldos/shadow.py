"""Schattenbetrieb: Empfehlung von FLD OS gegen die tatsächlich gefahrene Anlage, Euro für Euro.

Fairer Vergleich: Fährt die Anlage mehr/weniger Energie als empfohlen, verzerrt der reine Erlösvergleich. Kennzahl daher
„Mehrerlös bei gleicher Energiemenge“ = (Ø-Preis der Empfehlung − Ø-Preis des Betriebs) × gefahrene Energie.
Erlös = Spot-Erlös (Day-Ahead, Marktzeit); Wärme/EEG sind für dieselbe Energiemenge gleich und kürzen sich.
"""
from __future__ import annotations

import io

import pandas as pd

TZ = "Europe/Berlin"
MIN_COVERAGE = 0.9  # Tag zählt erst, wenn ≥ 90 % der Viertelstunden gemessen sind


def parse_csv(text: str) -> list[dict]:
    """CSV `zeit;leistung` → [{ts (UTC), p_mw}] je Viertelstunde (Mittelwert, falls feiner aufgelöst).

    Zeit: ISO mit Offset oder ohne Offset = Marktzeit Berlin. Leistung in kW, außer die Kopfzeile nennt MW.
    Trenner ; , oder Tab; Dezimalkomma bei Semikolon."""
    t = text.strip()
    if not t:
        return []
    first = t.splitlines()[0]
    sep = ";" if ";" in first else "\t" if "\t" in first else ","
    has_header = not first.split(sep)[0].strip()[:1].isdigit()
    try:
        df = pd.read_csv(io.StringIO(t), sep=sep, header=0 if has_header else None, decimal="," if sep == ";" else ".",
                         usecols=[0, 1], names=None if has_header else ["zeit", "leistung"])
    except (ValueError, pd.errors.ParserError):
        return []  # keine zwei Spalten / kaputte Datei → Aufrufer meldet „nicht erkannt“
    unit_mw = has_header and "mw" in str(df.columns[1]).lower()
    df.columns = ["zeit", "leistung"]
    zeit = df["zeit"].astype(str).str.strip()
    if zeit.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$").any():
        # mit Offset: über die Zeitumstellung stehen +02:00 und +01:00 gemischt → direkt nach UTC
        ts = pd.to_datetime(zeit, utc=True, errors="coerce", format="mixed")
    else:
        # Marktzeit ohne Offset: die doppelte Stunde im Oktober aus der Reihenfolge auflösen (erst Sommer-, dann Winterzeit)
        local = pd.to_datetime(zeit, errors="coerce", format="mixed")
        try:
            ts = local.dt.tz_localize(TZ, ambiguous="infer", nonexistent="NaT")
        except (ValueError, TypeError):  # Reihenfolge nicht eindeutig → doppelte Stunde verwerfen statt raten
            ts = local.dt.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
    df = df.assign(ts=ts.dt.tz_convert("UTC"), p=pd.to_numeric(df["leistung"], errors="coerce")).dropna(subset=["ts", "p"])
    if df.empty:
        return []
    s = df.set_index("ts")["p"].resample("15min").mean().dropna() / (1.0 if unit_mw else 1000.0)
    return [{"ts": t.to_pydatetime(), "p_mw": float(v)} for t, v in s.items()]


def evaluate(plans: dict, measured: pd.Series, prices: pd.Series, dt: float = 0.25) -> dict:
    """plans: {Liefertag: Series bhkw_mw (UTC-Index)}; measured/prices: Series mit UTC-Viertelstunden-Index."""
    days = []
    for day, plan in sorted(plans.items()):
        pr = prices.reindex(plan.index)
        me = measured.reindex(plan.index)
        if pr.isna().any() or me.notna().mean() < MIN_COVERAGE:
            continue  # Preise oder Messdaten fehlen → Tag nicht vergleichbar
        me = me.fillna(0.0)
        e_rec, e_me = float(plan.sum() * dt), float(me.sum() * dt)
        r_rec, r_me = float((plan * pr).sum() * dt), float((me * pr).sum() * dt)
        p_rec = r_rec / e_rec if e_rec > 0 else 0.0
        p_me = r_me / e_me if e_me > 0 else 0.0
        days.append({"day": str(day), "energy_rec_mwh": round(e_rec, 2), "energy_meas_mwh": round(e_me, 2),
                     "revenue_rec_eur": round(r_rec, 0), "revenue_meas_eur": round(r_me, 0),
                     "price_rec_eur_mwh": round(p_rec, 1), "price_meas_eur_mwh": round(p_me, 1),
                     "extra_same_energy_eur": round((p_rec - p_me) * e_me, 0)})
    total = sum(d["extra_same_energy_eur"] for d in days)
    return {"days": days, "summary": {"days": len(days), "extra_same_energy_eur": round(total, 0),
                                      "per_day_eur": round(total / len(days), 0) if days else None}}
