"""Tageskette FLD OS — ein Befehl: Daten holen → Prognose → Backtest → Empfehlung → Entscheidung → DB.

    PYTHONPATH=.:engine .venv/bin/python -m fldos.pipeline            # alles
    … -m fldos.pipeline --skip-fetch                                   # nur rechnen (Daten wie vorhanden)
    … -m fldos.pipeline --no-seed                                      # nicht in die DB schreiben

Ziel ist immer der morgige Liefertag nach Marktzeit (Europe/Berlin). ENTSO-E nur mit ENTSOE_TOKEN.
Schreibt nach FLD_DATA_DIR; pipeline_status.json hält fest, was wann mit welchem Stand gerechnet wurde.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import config

from .. import alarm
from ..settings import DATA_DIR, TENANT_ID
from . import fetch, model, plan, report

TZ = ZoneInfo("Europe/Berlin")


def _step(name: str, fn, status: dict, hard: bool = True):
    t = time.time()
    print(f"▶ {name} …", flush=True)
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001 — weiche Schritte protokollieren und weiterlaufen
        status["steps"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        print(f"  ✗ {name}: {e}", flush=True)
        if hard:
            traceback.print_exc()
            raise SystemExit(f"{name}: {type(e).__name__}: {e}"[:300])  # Text → Exit 1, run() meldet ihn
        return None
    status["steps"][name] = {"ok": True, "seconds": round(time.time() - t, 1),
                             **({"rows": out} if isinstance(out, int) else {})}
    print(f"  ✓ {name} ({time.time() - t:.0f}s)", flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fldos.pipeline")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--no-seed", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    a = ap.parse_args(argv)
    d: Path = a.data_dir
    # Ein Lauf zur Zeit (launchd + demo.sh): zwei Läufe schrieben dieselben Dateien und Zeilen (Review M-06)
    lock = open(d / ".tageskette.lock", "w")  # noqa: SIM115 — bleibt bis Prozessende offen
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Tageskette läuft bereits — dieser Aufruf endet ohne Änderung.", flush=True)
        return 2
    now = datetime.now(TZ)
    target = now.date() + timedelta(days=1)
    status: dict = {"run_at": now.isoformat(timespec="seconds"), "target_day": str(target), "steps": {}}

    if not a.skip_fetch:
        _step("Netz erreichbar", _wait_net, status)
        _step("Preise + Erzeugung (Energy-Charts/SMARD)", lambda: fetch.history(d, target), status)
        _step("Wetterprognosen (Open-Meteo)", lambda: fetch.weather(d, target), status)
        _step("Netzbetreiber-Prognosen (ENTSO-E)", lambda: fetch.entsoe(d, target, fetch.entsoe_token()), status, hard=False)
        _step("Gas, CO₂, Öl (TTF/EEX/Brent)", lambda: fetch.external(d), status, hard=False)
        _step("Terminkurve Gas + Öl (12 Monate)", lambda: fetch.forward_curve(d), status, hard=False)
        _step("Regelenergie (regelleistung.net)", lambda: fetch.regelenergie(d, 90), status, hard=False)

    frame, wx = _step("Merkmale", lambda: model.frame(d, until_day=target), status)
    walk = _step("Prognose messen (rollierend, 12 Monate)", lambda: model.walk_forward(frame, wx, 12, until_day=target), status)
    day = _step(f"Prognose für {target}", lambda: model.predict_day(frame, wx, walk, target), status)
    if day is None or day.empty:
        print(f"  ✗ keine Merkmale für {target} (Wetterprognose fehlt?)", flush=True)
        return 1

    cols = {"actual": "actual", "pred_A": "pred_A", "pred_B": "pred_B", "q10": "P10", "q90": "P90"}
    both = pd.concat([walk.pred, day])
    fc = both[list(cols)].rename(columns=cols).rename_axis("utc").reset_index()
    fc["utc"] = fc["utc"].map(lambda t: t.isoformat())
    qcols = [f"q{int(q * 100):02d}" for q in model.QS]
    qt = both[["actual", *qcols]].rename_axis("utc").reset_index()
    qt["utc"] = qt["utc"].map(lambda t: t.isoformat())

    # Die Anlage des Mandanten (Anlagendaten-Seite), nicht die Modellanlage — Review H-04
    plant, status["plant_override"] = _step("Anlagendaten des Mandanten", lambda: _plant(a.no_seed), status)
    bt, summary = _step("Backtest (Plan auf Prognose, Abrechnung auf Ist)", lambda: plan.backtest(walk.pred, plant), status)

    info = {"name": "Lernmodell mit Wetterprognosen, kalibriert", "mae": walk.metrics["mae"]["calibrated"]}
    rec, kpi = _step("Empfehlung", lambda: plan.recommend(day, info, plant), status)

    sigma = float((walk.pred["actual"] - walk.pred["pred_B"]).std())
    reg = pd.read_csv(d / "regelenergie.csv")
    ext = pd.read_csv(d / "external_market.csv")
    dec, rec, kpi = _step("Tagesentscheidung (Spot vs. Regelenergie)", lambda: plan.decide(rec, kpi, reg, ext, sigma, plant), status)

    status["model"] = walk.metrics
    status["backtest"] = {k: round(v, 1) if isinstance(v, float) else v for k, v in summary.items()}
    status["data_until"] = _data_until(d)
    value = {"days": summary["days"], "per_year_eur": summary["per_year_eur"], "capture_pct": summary["capture_pct"]}
    # Alles erst jetzt schreiben (Sekunden statt ~10 min Fenster, in dem Dateien und DB nicht zusammenpassten)
    fetch._write(fc, d / "forecasts.csv")
    fetch._write(qt, d / "quantiles.csv")
    fetch._write(bt, d / "backtest_results.csv")
    fetch._write(rec, d / "recommendation.csv")
    _write_text(d / "recommendation.json", json.dumps(kpi, indent=2, ensure_ascii=False))
    _write_text(d / "decision.json", json.dumps(dec, indent=2, ensure_ascii=False))
    _write_text(d / "reports" / f"{TENANT_ID}.html", report.render(rec, kpi, dec, value, status))
    if not a.no_seed:
        from .. import seed
        status["seed"] = _step("Datenbank aktualisieren", lambda: asyncio.run(seed.seed()), status)
    _write_text(d / "pipeline_status.json", json.dumps(status, indent=2, ensure_ascii=False, default=str))

    print(f"\nEmpfehlung {kpi['target_day']} ({kpi['price_basis']}): {dec['strategy']}, "
          f"Mehrerlös {kpi['expected_uplift_eur']:.0f} € ggü. Dauerbetrieb")
    print(f"Backtest {summary['days']} Tage: {summary['per_year_eur']:,.0f} €/Jahr je MW, "
          f"+{summary['pct_vs_flat']:.1f} %, Treffsicherheit {summary['capture_pct']:.1f} %")
    return 0


def _wait_net() -> None:
    if waited := fetch.wait_for_network():
        print(f"  … {waited} s auf Netz gewartet", flush=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)  # atomar wie fetch._write


def _plant(offline: bool) -> tuple[config.PlantConfig, dict]:
    """Anlagenwerte des Mandanten aus der DB (wie die API: Modellwerte, überschrieben mit FLD-Werten).
    Ohne DB (--no-seed) oder ohne Eintrag: Modellanlage — steht dann in pipeline_status.json."""
    if offline:
        return config.PLANT, {}
    from ..settings import DATABASE_URL
    from ..storage import make_repository

    async def load() -> dict:
        try:
            return await make_repository(DATABASE_URL, TENANT_ID).get_plant_config() or {}
        finally:  # Verbindungen gehören zu dieser Event-Loop; der Seed läuft später in einer neuen
            from ..db import get_engine
            await get_engine(DATABASE_URL).dispose()
    override = asyncio.run(load())
    return config.PLANT.with_overrides(override), override


def _data_until(d: Path) -> dict:
    out = {}
    for f, col in (("history.csv", "utc"), ("wetter.csv", "utc"), ("entsoe_forecasts.csv", "utc"),
                   ("external_market.csv", "date"), ("regelenergie.csv", "date")):
        p = d / f
        if p.exists():
            out[f] = str(pd.read_csv(p, usecols=[col])[col].max())
    return out


def run(argv: list[str] | None = None) -> int:
    """main() mit Alarm: jeder Abbruch wird sofort gemeldet; Exit 0 (fertig) und 2 (läuft schon) nicht."""
    try:
        rc = main(argv)
    except SystemExit as e:
        if e.code in (None, 0, 2):  # 2 auch argparse-Fehler: Aufruf falsch, kein Lauf
            raise
        reason = e.code if isinstance(e.code, str) else f"Abbruch mit Code {e.code}"
        print(f"✗ {reason}", file=sys.stderr, flush=True)
        alarm.pipeline_failed(reason)
        return 1
    except Exception as e:  # noqa: BLE001 — unerwarteter Fehler: melden, dann wie bisher mit Spur enden
        alarm.pipeline_failed(f"{type(e).__name__}: {e}"[:300])
        raise
    if rc == 1:
        alarm.pipeline_failed("keine Prognose für morgen (Wetterprognose fehlt?)")
    return rc


if __name__ == "__main__":
    sys.exit(run())
