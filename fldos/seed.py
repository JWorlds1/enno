"""Seed: lädt die Ausgaben der Tageskette (CSV/JSON in FLD_DATA_DIR) in die DB — letzter Schritt von `-m fldos.pipeline`.

Markt-/Regelenergiedaten per Upsert, Backtest ersetzt, je Aufruf ein neuer Lauf (Historie der Empfehlungen).
Aufruf:  FLD_DATABASE_URL=... python -m fldos.seed
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

from . import memory
from . import models as M
from . import repository as repo
from .db import SessionLocal
from .settings import DATA_DIR as ROOT, TENANT_ID


def _read_json(name: str) -> dict:
    p = ROOT / name
    return json.loads(p.read_text()) if p.exists() else {}


def _combine_ts(day: date, t: str) -> datetime | None:
    try:
        return pd.to_datetime(f"{day} {t}").to_pydatetime()
    except Exception:
        return None


async def seed() -> dict:
    counts: dict[str, int] = {}
    async with SessionLocal() as s:
        # ── Markt-Fundamentaldaten ──
        f = ROOT / "external_market.csv"
        if f.exists():
            df = pd.read_csv(f)
            rows = [
                {"day": pd.to_datetime(r["date"]).date(),
                 "ttf_gas_eur_mwh": float(r["ttf_eur_mwh"]) if pd.notna(r["ttf_eur_mwh"]) else None,
                 "eua_co2_eur_t": float(r["eua_eur_t"]) if pd.notna(r["eua_eur_t"]) else None,
                 "source": "seed"}
                for _, r in df.iterrows()
            ]
            counts["market"] = await repo.upsert_fundamentals(s, rows, tenant=TENANT_ID)

        # ── Regelenergie (aFRR + FCR je Tag) ──
        f = ROOT / "regelenergie.csv"
        if f.exists():
            df = pd.read_csv(f)
            rows = []
            for _, r in df.iterrows():
                d = pd.to_datetime(r["date"]).date()
                # aFRR je Richtung: das Mittel aus + und − erzielt niemand (Review N-05)
                rows.append({"day": d, "product": "afrr_pos", "price_eur_mw_h": float(r["aFRR_pos_eur_mw_h"])})
                rows.append({"day": d, "product": "afrr_neg", "price_eur_mw_h": float(r["aFRR_neg_eur_mw_h"])})
                rows.append({"day": d, "product": "fcr", "price_eur_mw_h": float(r["FCR_eur_mw_h"])})
            counts["regelenergie"] = await repo.upsert_regelenergie(s, rows, tenant=TENANT_ID)

        # ── Backtest: ersetzen in EINER Transaktion (DELETE + INSERT), sonst ist er zwischendurch leer (/value 404) ──
        # Nur den eigenen Mandanten anfassen (§9). Läufe/Empfehlungen bleiben als Historie, Was-wäre-wenn-Szenarien auch.
        f = ROOT / "backtest_results.csv"
        if f.exists():
            await s.execute(text("DELETE FROM backtest_results WHERE tenant_id = :t"), {"t": TENANT_ID})
            df = pd.read_csv(f)
            base = date(2025, 1, 1)
            objs = []
            for i, r in df.iterrows():
                try:
                    d = pd.to_datetime(r["day"]).date()
                except Exception:
                    d = base + timedelta(days=int(i))
                objs.append(M.BacktestResult(
                    tenant_id=TENANT_ID, day=d, algo="schedule",
                    flat=float(r["flat"]), perfect=float(r["perfect"]), forecast=float(r["forecast"]),
                    up_fc=float(r["up_fc"]), up_pf=float(r["up_pf"]), ok=bool(r["ok"]),
                    exp_fc=float(r["exp_fc"]) if "exp_fc" in r and pd.notna(r["exp_fc"]) else None,
                ))
            s.add_all(objs)
            await s.commit()
            counts["backtest"] = len(objs)

        # ── Der Lauf: Empfehlung + Dispatch + Prognose + Decision ──
        kpis = _read_json("recommendation.json")
        target_day = (
            pd.to_datetime(kpis["target_day"]).date() if kpis.get("target_day")
            else date.today() + timedelta(days=1)
        )
        dispatch_rows: list[dict] = []
        f = ROOT / "recommendation.csv"
        if f.exists():
            df = pd.read_csv(f)
            for _, r in df.iterrows():
                dispatch_rows.append({
                    "slot": int(r["slot"]),
                    "ts": pd.to_datetime(r["utc"]).to_pydatetime() if "utc" in r else _combine_ts(target_day, str(r["time"])),
                    # Preisbasis des Plans: Auktionspreis, wenn der Fahrplan darauf gerechnet wurde, sonst Prognose
                    "pred_price": float(r["actual_price_eur_mwh"] if kpis.get("price_basis") == "Auktion"
                                        else r["pred_price_eur_mwh"]),
                    "bhkw_mw": float(r["bhkw_mw"]),
                    "electrolyser_mw": float(r["electrolyser_mw"]),
                    "pyro_mw": None,
                    **{c: float(r[c]) if c in r and pd.notna(r[c]) else None for c in ("reserve_up_mw", "reserve_down_mw")},
                })

        forecast_rows: list[dict] = []
        f = ROOT / "forecasts.csv"
        if f.exists():
            df = pd.read_csv(f)
            # genau der Liefertag (Marktzeit) — tail(96) schnitt an Umstellungstagen (92/100 Slots) falsch
            df = df[pd.to_datetime(df["utc"], utc=True).dt.tz_convert("Europe/Berlin").dt.date == target_day]
            for _, r in df.iterrows():
                forecast_rows.append({
                    "ts": pd.to_datetime(r["utc"]).to_pydatetime(),
                    "actual": None if pd.isna(r["actual"]) else float(r["actual"]),
                    "pred_a": None if pd.isna(r["pred_A"]) else float(r["pred_A"]),
                    "pred_b": None if pd.isna(r["pred_B"]) else float(r["pred_B"]),
                    "p10": None if pd.isna(r["P10"]) else float(r["P10"]),
                    "p90": None if pd.isna(r["P90"]) else float(r["P90"]),
                })

        dj = _read_json("decision.json")
        decision = {
            "strategy": str(dj.get("strategy", "n/a")),
            "scores": dj.get("strategy_scores") or dj.get("scores"),
            "guardrails": dj.get("guardrails"),
            "rationale": dj.get("rationale"),
        } if dj else None

        if dispatch_rows:
            run = await repo.save_run(
                s, target_day=target_day, algo="schedule", kpis=kpis,
                dispatch_rows=dispatch_rows, forecast_rows=forecast_rows, decision=decision,
                tenant=TENANT_ID,
            )
            counts["run_id"] = run.id
            counts["dispatch"] = len(dispatch_rows)
            counts["forecast"] = len(forecast_rows)
            # Enno-Langzeitgedächtnis: Tages-Empfehlung als Erinnerung ablegen (best-effort).
            try:
                summary = (f"Empfehlung {target_day}: erwarteter Erlös {kpis.get('expected_revenue_eur')}€, "
                           f"Mehrerlös {kpis.get('expected_uplift_eur')}€, BHKW-Laufzeit {kpis.get('bhkw_runtime_h')}h, "
                           f"Strategie {decision['strategy'] if decision else 'n/a'}.")
                await memory.remember(s, "recommendation", summary, {"target_day": str(target_day)}, tenant=TENANT_ID)
                counts["memory"] = 1
            except Exception:
                counts["memory"] = 0
    return counts


if __name__ == "__main__":
    print("seed:", asyncio.run(seed()))
