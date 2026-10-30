"""Alarm: meldet, wenn die Tageskette scheitert oder bis zur Gebotsfrist kein Plan für morgen da ist.

    PYTHONPATH=.:engine .venv/bin/python -m fldos.alarm      # Wächter (launchd alle 15 min): prüft den Stand

Zwei Wege zum Alarm:
  - Die Tageskette meldet selbst, sobald ein Pflichtschritt scheitert (pipeline/__main__.py) — sofort.
  - Der Wächter sieht nach, ob bis zur Gebotsfrist (11:30, Auktion um 12:00) ein Plan für morgen da ist — er
    fängt auch den Lauf, der nie startete (Rechner aus/Schlaf). Solange der Rechner aus ist, kann niemand melden.
Gemeldet wird ins Log (immer), als Mac-Hinweis und per Telegram, wenn TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID gesetzt
sind — nur an einen privaten Chat (positive ID), nie an eine Gruppe. Dieselbe Meldung höchstens einmal am Tag.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .settings import DATA_DIR

TZ = ZoneInfo("Europe/Berlin")
DEADLINE = time(11, 30)  # Plan für morgen muss stehen, bevor um 12:00 die Auktion schließt
LOG = Path.home() / "Library" / "Logs" / "fld-os" / "alarm.log"


def problems(status: dict | None, now: datetime, running: bool = False) -> list[str]:
    """Was am Stand nicht stimmt (leer = alles gut). Vor der Gebotsfrist gibt es nichts zu melden: der Lauf darf
    bis dahin auf Netz warten und rechnen; scheitert er, meldet er sich selbst."""
    if now.time() < DEADLINE:
        return []
    tomorrow = now.date() + timedelta(days=1)
    if status is None:
        return [f"Kein Plan für {tomorrow}: die Tageskette hat noch nie einen Stand geschrieben."]
    if status.get("target_day") != str(tomorrow):
        if running:
            return [f"Kein Plan für {tomorrow} bis {DEADLINE:%H:%M}: die Tageskette läuft noch — Gebote vor der Auktion "
                    f"um 12:00 in Gefahr."]
        return [f"Kein Plan für {tomorrow} bis {DEADLINE:%H:%M}: letzter Lauf {status.get('run_at', '?')} für "
                f"{status.get('target_day', '?')}. Lauf gescheitert oder nie gestartet (Rechner aus/Schlaf?). "
                f"Log: ~/Library/Logs/fld-os/tageskette.log"]
    bad = [f"{k}: {v.get('error', '?')}" for k, v in (status.get("steps") or {}).items() if not v.get("ok")]
    return [f"Plan für {tomorrow} steht, aber mit altem Stand bei: " + "; ".join(bad)] if bad else []


def notify(text: str, env: dict | None = None, *, post=None, mac=None, log: Path | None = None) -> list[str]:
    """Meldung auf allen verfügbaren Wegen; → die Wege, über die sie rausging. Scheitert nie (Alarm ist best effort)."""
    env = os.environ if env is None else env
    log = log or LOG
    used = []
    stamp = datetime.now(TZ).isoformat(timespec="seconds")
    tok, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "").strip()
    note = ""
    if tok and chat:
        if not chat.isdigit():  # negative ID = Gruppe → nie (Vorgabe: Alarme nur privat)
            note = " [Telegram verweigert: Chat-ID ist keine private Chat-ID]"
        else:
            try:
                (post or _post)(f"https://api.telegram.org/bot{tok}/sendMessage",
                                {"chat_id": chat, "text": f"FLD OS\n{text}"})
                used.append("telegram")
            except Exception as e:  # noqa: BLE001
                note = f" [Telegram fehlgeschlagen: {type(e).__name__}]"  # ohne Token im Text
    try:
        (mac or _mac)(text)
        used.append("mac")
    except Exception:  # noqa: BLE001 — z. B. kein osascript (Server)
        pass
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(f"{stamp} [{','.join(used) or 'nur log'}] {text}{note}\n")
        used.append("log")
    except OSError:
        pass
    return used


def _post(url: str, data: dict) -> None:
    urllib.request.urlopen(url, urllib.parse.urlencode(data).encode(), timeout=10).read()


def _mac(text: str) -> None:
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{esc}" with title "FLD OS" sound name "Basso"'],
                   check=True, timeout=10, capture_output=True)


def pipeline_failed(reason: str) -> list[str]:
    """Aufruf aus der Tageskette, wenn sie abbricht — jede Panne wird gemeldet (keine Tagessperre)."""
    return notify(f"Tageskette gescheitert: {reason}. Log: ~/Library/Logs/fld-os/tageskette.log")


def _running(d: Path) -> bool:
    """Hält gerade eine Tageskette die Sperre? (gleiche Sperrdatei wie pipeline/__main__.py)"""
    p = d / ".tageskette.lock"
    if not p.exists():
        return False
    with p.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def check(d: Path, now: datetime | None = None, env: dict | None = None, **kw) -> list[str]:
    """Wächter: Stand prüfen, neue Probleme melden (je Text einmal am Tag); → die gemeldeten Probleme."""
    now = now or datetime.now(TZ)
    sp = d / "pipeline_status.json"
    status = json.loads(sp.read_text()) if sp.exists() else None
    state_p = d / ".alarm_state.json"
    try:
        state = json.loads(state_p.read_text())
    except (OSError, ValueError):
        state = {}
    today = str(now.date())
    sent = []
    for text in problems(status, now, _running(d)):
        if state.get(text) == today:
            continue
        notify(text, env, **kw)
        state[text] = today
        sent.append(text)
    state = {k: v for k, v in state.items() if v == today}  # gestern Gemeldetes darf heute wieder melden
    state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return sent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fldos.alarm")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    a = ap.parse_args(argv)
    for text in check(a.data_dir):
        print(f"gemeldet: {text}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
