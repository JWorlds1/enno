"""Tagesbericht (report.html): Empfehlung, Begründung, Kennzahlen, Fahrplan je Stunde in Marktzeit — druck- und mailbar.

Eigenständiges HTML ohne externe Ressourcen; so geht der Plan an Leitwarte oder Direktvermarkter.
"""
from __future__ import annotations

import html
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from ..enno import _clean_reason

LABEL = {"SPOT_FLEX": "Flexibel am Spotmarkt fahren", "PTX_PRIORITY": "Günstigen Strom in Wasserstoff umwandeln",
         "REGELENERGIE_RESERVE": "Regelenergie vorhalten"}
DAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _de(v: float, dp: int = 0) -> str:
    return f"{v:,.{dp}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _svg(rec: pd.DataFrame, price_col: str) -> str:
    """Preis (Linie) und BHKW/Elektrolyse (Flächen) über den Tag."""
    w, h, n = 760, 220, len(rec)
    pr = rec[price_col].astype(float)
    lo, hi = min(0.0, pr.min()), max(1.0, pr.max())
    x = lambda i: 40 + i * (w - 60) / max(1, n - 1)  # noqa: E731
    yp = lambda v: 10 + (hi - v) / (hi - lo) * (h - 40)  # noqa: E731
    ym = lambda v: (h - 30) - v * (h - 60)  # noqa: E731  — 0…1 MW
    line = " ".join(f"{x(i):.1f},{yp(v):.1f}" for i, v in enumerate(pr))
    bh = "".join(f'<rect x="{x(i):.1f}" y="{ym(v):.1f}" width="{(w - 60) / n:.2f}" height="{(h - 30) - ym(v):.1f}" fill="#FCC008" opacity=".55"/>'
                 for i, v in enumerate(rec["bhkw_mw"]) if v > 0)
    el = "".join(f'<rect x="{x(i):.1f}" y="{ym(v):.1f}" width="{(w - 60) / n:.2f}" height="{(h - 30) - ym(v):.1f}" fill="#2a6ca3" opacity=".55"/>'
                 for i, v in enumerate(rec["electrolyser_mw"]) if v > 0)
    ticks = "".join(f'<text x="{x(i):.1f}" y="{h - 12}" font-size="10" text-anchor="middle" fill="#666">{rec["time"].iloc[i]}</text>'
                    for i in range(0, n, 16))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Fahrplan und Preis über den Tag">{bh}{el}'
            f'<polyline points="{line}" fill="none" stroke="#1d1d1b" stroke-width="1.6"/>{ticks}'
            f'<text x="4" y="14" font-size="10" fill="#666">{_de(hi)} €</text><text x="4" y="{h - 30}" font-size="10" fill="#666">{_de(lo)} €</text></svg>')


def render(rec: pd.DataFrame, kpi: dict, dec: dict, value: dict, status: dict) -> str:
    day = date.fromisoformat(kpi["target_day"])
    auction = kpi["price_basis"] == "Auktion"
    price_col = "actual_price_eur_mwh" if auction else "pred_price_eur_mwh"
    reserve = "reserve_up_mw" in rec  # Strategie „Regelenergie vorhalten“: freigehaltene Leistung gehört in den Plan
    if not reserve:
        rec = rec.assign(reserve_up_mw=0.0, reserve_down_mw=0.0)
    hourly = rec.assign(hour=rec["slot"] // 4).groupby("hour").agg(
        time=("time", "first"), price=(price_col, "mean"), bhkw=("bhkw_mw", "mean"), el=("electrolyser_mw", "mean"),
        up=("reserve_up_mw", "mean"), down=("reserve_down_mw", "mean"))
    rows = "".join(f"<tr><td>{r.time}</td><td>{_de(r.price, 1)}</td><td>{_de(r.bhkw, 2)}</td><td>{_de(r.el, 2)}</td>"
                   + (f"<td>{_de(r.up, 2)}</td><td>{_de(r.down, 2)}</td>" if reserve else "") + "</tr>"
                   for r in hourly.itertuples())
    res_head = "<th>Reserve ↑ MW</th><th>Reserve ↓ MW</th>" if reserve else ""
    res_txt = (f" · davon Regelleistung {_de(kpi.get('reserve_capacity_eur'))} €" if kpi.get("reserve_capacity_eur") else "")
    expected = "" if auction else " (erwartet laut Prognose)"
    reasons = "".join(f"<li>{html.escape(_clean_reason(r))}</li>" for r in dec.get("rationale", []))
    berlin = ZoneInfo("Europe/Berlin")
    created = datetime.fromisoformat(status["run_at"]).astimezone(berlin).strftime("%d.%m.%Y %H:%M") if status.get("run_at") else "—"
    until = status.get("data_until", {}).get("history.csv")
    until = pd.Timestamp(until).tz_convert(berlin).strftime("%d.%m.%Y %H:%M") if until else "—"
    v = value or {}
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>FLD OS · Tagesbericht {day:%d.%m.%Y}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1d1d1b;margin:0;background:#f5f3f0}}
main{{max-width:860px;margin:0 auto;padding:28px 20px 48px}} h1{{font-size:26px;margin:0}} h2{{font-size:16px;margin:28px 0 8px}}
.eyebrow{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#7a756f}} .hero{{background:#1d1d1b;color:#f5f3f0;border-radius:14px;padding:22px 24px;margin:14px 0}}
.hero b{{color:#FCC008}} .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .k{{background:#fff;border-radius:10px;padding:12px 14px;border:1px solid #e6e2dc}}
.k small{{color:#7a756f;font-size:11px;text-transform:uppercase;letter-spacing:.06em}} .k div{{font-size:20px;font-weight:700}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;font-size:13px}} th,td{{padding:6px 10px;border-bottom:1px solid #eee;text-align:right}}
th:first-child,td:first-child{{text-align:left}} .muted{{color:#7a756f;font-size:12px}} @media print{{body{{background:#fff}}}}
@media (max-width:640px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<div class="eyebrow">FLD OS · Tagesbericht · erstellt {created}</div>
<h1>{DAYS[day.weekday()]}, {day:%d.%m.%Y}</h1>
<div class="hero"><div class="eyebrow" style="color:#bdb7ae">Gebotsplan · {'bewertet zu Auktionspreisen' if auction else 'auf Preisprognose'}</div>
<div style="font-size:22px;font-weight:700;margin:4px 0">{html.escape(LABEL.get(dec.get('strategy', ''), dec.get('strategy', '')))}</div>
<div>Mehrerlös gegenüber Dauerbetrieb{expected}: <b>{'+' if kpi['expected_uplift_eur'] >= 0 else ''}{_de(kpi['expected_uplift_eur'])} €</b>{res_txt} · BHKW {_de(kpi['bhkw_runtime_h'], 1)} h, Elektrolyse {_de(kpi['electrolyser_runtime_h'], 1)} h</div></div>
<div class="kpis">
<div class="k"><small>Erlös</small><div>{_de(kpi['expected_revenue_eur'])} €</div><span class="muted">Dauerbetrieb {_de(kpi['flat_baseline_eur'])} €</span></div>
<div class="k"><small>Strompreis</small><div>{_de(kpi['pred_price_min'])}–{_de(kpi['pred_price_max'])}</div><span class="muted">€/MWh</span></div>
<div class="k"><small>Mehrwert pro Jahr</small><div>≈ {_de(round(v.get('per_year_eur', 0), -3))} €</div><span class="muted">je MW, {v.get('days', 0)} Tage nachgerechnet</span></div>
<div class="k"><small>Treffsicherheit</small><div>{_de(v.get('capture_pct') or 0, 1)} %</div><span class="muted">vom möglichen Mehrerlös</span></div>
</div>
<h2>Fahrplan über den Tag</h2>{_svg(rec, price_col)}
<p class="muted">Linie: Strompreis · gelb: BHKW (MW) · blau: Elektrolyse (MW) · Uhrzeiten in Marktzeit (Berlin)</p>
<h2>Begründung</h2><ul>{reasons}</ul>
<h2>Fahrplan je Stunde</h2><table><thead><tr><th>Stunde</th><th>Preis €/MWh</th><th>BHKW MW</th><th>Elektrolyse MW</th>{res_head}</tr></thead><tbody>{rows}</tbody></table>
<p class="muted">Viertelstündlicher Fahrplan als CSV in FLD OS (Fahrplan → Herunterladen). Prognosefehler (MAE, 12 Monate rollierend):
{_de(kpi.get('forecast_mae_eur_mwh') or 0, 1)} €/MWh. Marktdaten bis {until} Uhr.</p>
</main></body></html>"""
