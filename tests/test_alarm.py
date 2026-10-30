"""Alarm: Tageskette gescheitert oder bis zur Gebotsfrist kein Plan für morgen → Meldung (Log, Mac, Telegram privat)."""
import json
from datetime import datetime

import pytest

from fldos import alarm

TZ = alarm.TZ


def _now(h, m=0, day="2026-10-22"):
    return datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}").replace(tzinfo=TZ)


def _status(target="2026-10-23", steps=None):
    return {"run_at": "2026-10-22T09:30:10+02:00", "target_day": target,
            "steps": steps or {"Preise + Erzeugung (Energy-Charts/SMARD)": {"ok": True}}}


def test_vor_der_gebotsfrist_kein_alarm():
    assert alarm.problems(None, _now(11, 29)) == []
    assert alarm.problems(_status(target="2026-10-22"), _now(9, 0)) == []


def test_plan_fuer_morgen_steht_kein_alarm():
    assert alarm.problems(_status(), _now(11, 30)) == []


def test_nach_der_frist_ohne_plan_fuer_morgen():
    p = alarm.problems(_status(target="2026-10-22"), _now(11, 45))
    assert len(p) == 1 and "Kein Plan für 2026-10-23" in p[0] and "2026-10-22T09:30" in p[0]
    assert "läuft noch" in alarm.problems(_status(target="2026-10-22"), _now(11, 45), running=True)[0]
    assert "noch nie" in alarm.problems(None, _now(12, 0))[0]


def test_weicher_schritt_ausgefallen_wird_gemeldet():
    st = _status(steps={"Netzbetreiber-Prognosen (ENTSO-E)": {"ok": False, "error": "HTTPError: 503"},
                        "Merkmale": {"ok": True}})
    p = alarm.problems(st, _now(12, 0))
    assert len(p) == 1 and "ENTSO-E" in p[0] and "503" in p[0]


def test_telegram_nur_privat_nie_an_eine_gruppe(tmp_path):
    sent, macs = [], []
    used = alarm.notify("x", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "-1001234"},
                        post=lambda u, d: sent.append(d), mac=macs.append, log=tmp_path / "a.log")
    assert sent == [] and "telegram" not in used and macs == ["x"]
    assert "verweigert" in (tmp_path / "a.log").read_text()
    used = alarm.notify("y", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "4711"},
                        post=lambda u, d: sent.append((u, d)), mac=macs.append, log=tmp_path / "a.log")
    assert used == ["telegram", "mac", "log"] and sent[0][1]["chat_id"] == "4711" and "y" in sent[0][1]["text"]


def test_ohne_telegram_und_mac_bleibt_das_log(tmp_path):
    def no_mac(_):
        raise FileNotFoundError("osascript")
    used = alarm.notify("z", {}, mac=no_mac, log=tmp_path / "a.log")
    assert used == ["log"] and "z" in (tmp_path / "a.log").read_text()


def test_telegram_fehler_verraet_den_token_nicht(tmp_path):
    def boom(url, data):
        raise OSError(f"kaputt {url}")
    alarm.notify("w", {"TELEGRAM_BOT_TOKEN": "GEHEIM", "TELEGRAM_CHAT_ID": "1"}, post=boom, mac=lambda _: None,
                 log=tmp_path / "a.log")
    assert "GEHEIM" not in (tmp_path / "a.log").read_text()


def test_waechter_meldet_jedes_problem_einmal_am_tag(tmp_path):
    (tmp_path / "pipeline_status.json").write_text(json.dumps(_status(target="2026-10-22")))
    log, macs = tmp_path / "a.log", []
    kw = {"env": {}, "mac": macs.append, "log": log}
    assert len(alarm.check(tmp_path, _now(11, 45), **kw)) == 1
    assert alarm.check(tmp_path, _now(12, 0), **kw) == []  # schon gemeldet
    assert len(alarm.check(tmp_path, _now(11, 45, day="2026-10-23"), **kw)) == 1  # neuer Tag, wieder melden
    assert len(macs) == 2


def test_tageskette_meldet_ihren_abbruch(tmp_path, monkeypatch):
    from fldos.pipeline import __main__ as pm
    got = []
    monkeypatch.setattr(alarm, "pipeline_failed", got.append)
    rc = pm.run(["--skip-fetch", "--no-seed", "--data-dir", str(tmp_path)])  # leeres Datenverzeichnis → Merkmale scheitern
    assert rc == 1 and len(got) == 1 and "Merkmale" in got[0]


def test_tageskette_ohne_fehler_oder_bei_sperre_meldet_nichts(monkeypatch):
    from fldos.pipeline import __main__ as pm
    got = []
    monkeypatch.setattr(alarm, "pipeline_failed", got.append)
    for rc in (0, 2):  # 2 = läuft schon (Sperre), kein Fehler
        monkeypatch.setattr(pm, "main", lambda argv=None, rc=rc: rc)
        assert pm.run([]) == rc
    assert got == []


@pytest.mark.parametrize("chat", ["", "abc", "-5"])
def test_unbrauchbare_chat_id_sendet_nichts(tmp_path, chat):
    sent = []
    alarm.notify("v", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": chat}, post=lambda u, d: sent.append(d),
                 mac=lambda _: None, log=tmp_path / "a.log")
    assert sent == []
