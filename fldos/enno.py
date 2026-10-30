"""Enno — Betriebsassistent von FLD OS.

Zwei Modi, dieselben Tools (echte Zahlen aus DB, Engine und Analyse-Cache — keine Halluzination):
- Basis (Default): erkennt die Frage per Muster, ruft die passenden Tools, antwortet in Klartext
  mit Sprunglinks. Kein Sprachmodell, keine Kosten, keine Daten nach außen.
- LLM (opt-in, FLD_LLM_PROVIDER=bedrock): Converse-API + Tool-Use über AWS Bedrock (EU-Region)
  mit eigenem Konto. Fällt bei Fehlern auf Basis zurück.
"""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import analytics, eeg, optimizers
from .storage import Repository

LLM_PROVIDER = os.environ.get("FLD_LLM_PROVIDER", "")  # "" = Basis-Modus; "bedrock" = LLM mit eigenem Konto
MODEL_ID = os.environ.get("FLD_LLM_MODEL", "eu.anthropic.claude-sonnet-4-6")
REGION = os.environ.get("AWS_REGION", "eu-central-1")

SYSTEM = (
    "Du bist Enno, der Betriebsoptimierungs-Agent der FLD-Biomethan-BHKW+PtX-Anlage. "
    "Du hilfst dem Betreiber: optimaler Tages-Fahrplan, Erlöse/Mehrerlös, Strategie, "
    "Was-wäre-wenn-Szenarien, Backtest-Wirtschaftlichkeit, Marktkontext. "
    "Nutze IMMER die Tools für Zahlen — erfinde niemals Werte. "
    "Antworte knapp und präzise auf Deutsch, mit konkreten Zahlen und Einheiten."
)

TOOLS = [
    {"toolSpec": {"name": "get_recommendation", "description": "Aktueller optimierter Fahrplan für morgen inkl. KPIs.",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "get_decision", "description": "Empfohlene Betriebsstrategie + Begründung des Entscheidungs-Agenten.",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "run_whatif", "description": "Re-optimiert den Tag unter geänderten Annahmen (MILP). Gibt Netto/Mehrerlös/Dispatch.",
                  "inputSchema": {"json": {"type": "object", "properties": {
                      "gas": {"type": "number", "description": "Gaspreis €/MWh"},
                      "h2": {"type": "number", "description": "H2-Wert €/MWh"},
                      "co2": {"type": "number", "description": "CO2/CDR €/t"},
                      "mode": {"type": "string", "enum": ["none", "electro", "plasma"]}},
                      "required": ["gas", "h2", "co2", "mode"]}}}},
    {"toolSpec": {"name": "get_backtest", "description": "Zusammenfassung des Backtests über alle nachgerechneten Tage (Mehrerlös, Treffsicherheit).",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "get_market", "description": "Aktuelle Gas- (TTF) und CO2- (EUA) Marktpreise.",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "search_memory", "description": "Durchsucht Ennos Langzeitgedächtnis (frühere Empfehlungen/Läufe) nach Ähnlichkeit.",
                  "inputSchema": {"json": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}},
]


async def _dispatch_tool(store: Repository, name: str, args: dict) -> str:
    if name == "get_recommendation":
        run = await store.latest_run()
        if not run:
            return "Kein Lauf vorhanden."
        k = run.kpis or {}
        return (f"Fahrplan {run.target_day} (algo {run.algo}): erwarteter Erlös {k.get('expected_revenue_eur')}€, "
                f"Mehrerlös vs. Dauerbetrieb {k.get('expected_uplift_eur')}€, BHKW-Laufzeit {k.get('bhkw_runtime_h')}h, "
                f"{k.get('bhkw_starts')} Starts, H2 {k.get('h2_produced_mwh')}MWh, "
                f"Preisprognose {k.get('pred_price_min')}–{k.get('pred_price_max')}€/MWh.")
    if name == "get_decision":
        run = await store.latest_run()
        d = await store.decision_for_run(run.id) if run else None
        if not d:
            return "Keine Entscheidung hinterlegt."
        return f"Strategie: {d.strategy}. Begründung: {'; '.join(d.rationale or []) or 'keine'}."
    if name == "run_whatif":
        prices = await store.prices_latest()
        if not prices:
            return "Keine Preisbasis — Pipeline noch nicht gelaufen."
        r = await asyncio.to_thread(optimizers.run_algo, "whatif", prices, gas=float(args["gas"]), h2=float(args["h2"]),
                                    co2=float(args["co2"]), mode=str(args["mode"]), plant=await _plant(store))
        return (f"Bei Gas {args['gas']}€/MWh, H2 {args['h2']}€/MWh, CO2 {args['co2']}€/t, Pfad {args['mode']}: "
                f"Netto {round(r['net_eur'])}€, Mehrerlös {round(r['uplift_eur'])}€, BHKW {r['bhkw_h']}h, "
                f"{r['starts']} Starts, H2 {round(r['h2_mwh'], 2)}MWh, Status {r['status']}.")
    if name == "get_backtest":
        bt = await store.backtest()
        if not bt:
            return "Kein Backtest vorhanden."
        sfc = sum(x.up_fc or 0 for x in bt)
        spf = sum(x.up_pf or 0 for x in bt)
        cap = (sfc / spf * 100) if spf else 0
        better = sum(1 for x in bt if (x.up_fc or 0) >= -0.5)  # wie _a_backtest: Mehrerlös ≥ 0, nicht Löserstatus
        return (f"Backtest: {len(bt)} Tage, Gesamt-Mehrerlös {round(sfc)}€, Ø {round(sfc/len(bt))}€/Tag, "
                f"Treffsicherheit {round(cap)}%, {better}/{len(bt)} Tage ≥ Dauerbetrieb.")
    if name == "get_market":
        m = await store.fundamentals()
        if not m:
            return "Keine Marktdaten."
        last = max(m, key=lambda x: x.day)
        return f"Markt {last.day}: TTF-Gas {last.ttf_gas_eur_mwh}€/MWh, EUA-CO2 {last.eua_co2_eur_t}€/t."
    if name == "search_memory":
        hits = await store.search_memory(str(args.get("query", "")))
        if not hits:
            return "Kein Gedächtnis-Treffer (oder Memory nicht verfügbar)."
        return "Frühere Einträge:\n" + "\n".join(f"- [{h.kind}] {h.content}" for h in hits)
    return f"Unbekanntes Tool: {name}"


def _client():
    if LLM_PROVIDER != "bedrock":
        return None
    try:
        import boto3
        from botocore.config import Config
        return boto3.client("bedrock-runtime", region_name=REGION,
                            config=Config(read_timeout=120, connect_timeout=15,
                                          retries={"max_attempts": 4, "mode": "adaptive"}))
    except Exception:
        return None


async def enno_chat(store: Repository, message: str, history: list[dict] | None = None,
                    page: str | None = None) -> dict:
    """history: [{role:'user'|'assistant', content:str}]. Returns {reply, tool_calls}."""
    client = _client()
    if client is None:
        return await basis_chat(store, message, page)

    messages: list[dict] = []
    for h in (history or [])[-8:]:
        messages.append({"role": h["role"], "content": [{"text": h["content"]}]})
    messages.append({"role": "user", "content": [{"text": message}]})

    tool_calls: list[dict] = []
    for _ in range(6):  # max Tool-Runden
        try:
            resp = await asyncio.to_thread(
                client.converse, modelId=MODEL_ID, messages=messages, system=[{"text": SYSTEM}],
                toolConfig={"tools": TOOLS}, inferenceConfig={"maxTokens": 1500, "temperature": 0.2},
            )
        except Exception as e:  # noqa: BLE001 — LLM/Netzfehler: auf Basis-Modus zurückfallen statt 500
            fallback = await basis_chat(store, message, page)
            fallback["reply"] = f"(Sprachmodell nicht erreichbar: {type(e).__name__}; Basis-Antwort)\n\n" + fallback["reply"]
            return fallback

        out = resp["output"]["message"]
        messages.append(out)
        if resp.get("stopReason") == "tool_use":
            results = []
            for block in out["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    res = await _dispatch_tool(store, tu["name"], tu.get("input") or {})
                    tool_calls.append({"name": tu["name"], "input": tu.get("input")})
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": res}]}})
            messages.append({"role": "user", "content": results})
            continue
        reply = "".join(b.get("text", "") for b in out["content"] if "text" in b)
        return {"reply": reply, "tool_calls": tool_calls, "actions": [], "mode": "llm"}

    return {"reply": "(Enno hat zu viele Tool-Runden gebraucht — bitte präziser fragen.)",
            "tool_calls": tool_calls, "actions": [], "mode": "llm"}


# ── Basis-Modus: Muster → Tools → Klartext (ohne Sprachmodell) ────────────────
STRATEGY_LABEL = {
    "SPOT_FLEX": "Flexibel am Spotmarkt fahren",
    "PTX_PRIORITY": "Günstigen Strom in Wasserstoff umwandeln",
    "REGELENERGIE_RESERVE": "Regelenergie vorhalten",
    "CONSERVATIVE_HEDGE": "Vorsichtig fahren (hohe Unsicherheit)",
}

PAGE_HELP = {
    "cockpit": "Das Cockpit zeigt, was die Anlage morgen tun soll, was es bringt und wie der Fahrplan über den Tag aussieht.",
    "empfehlung": "Hier steht der viertelstündliche Fahrplan: wann das BHKW läuft, wann Strom in Wasserstoff geht, und warum.",
    "was-waere-wenn": "Hier änderst du Gaspreis, H₂-Wert und CO₂-Preis — der Tag wird sofort neu optimiert.",
    "sensitivitaet": "Der Tornado zeigt, welche Annahme den Tageserlös am stärksten bewegt, wenn sie um ±30 % schwankt.",
    "risiko": "Hier siehst du, wie viel erwarteten Erlös ein Fahrplan kostet, der gegen schlechte Preistage abgesichert ist.",
    "pareto": "Hier wird Erlös gegen CO₂-Einsparung abgewogen — und verglichen, ob Umplanen billiger ist als ein Zertifikat.",
    "erloes-stapel": "Der Erlös-Stapel zeigt, wie viel zusätzlich drin ist, wenn Leistung als Regelenergie vorgehalten wird.",
    "plasma": "Hier wird verglichen: nur Strom, Strom plus Elektrolyse oder Strom plus Plasma-Pyrolyse.",
    "cdr": "Ab welchem Kohlenstoff-Preis lohnt sich Plasma-Pyrolyse mehr als Elektrolyse?",
    "eeg": "Bei begrenztem Jahresbudget an Betriebsstunden: an welchen Tagen lohnt sich der Lauf am meisten?",
    "prognose": "Wie gut trifft die Preisprognose den Ist-Preis?",
    "prognoseband": "Wie ehrlich ist die Unsicherheit? Ein 80-%-Band sollte 80 % der Ist-Preise enthalten.",
    "markt": "Gas-, CO₂- und Regelenergiepreise als Rahmen für die Entscheidungen.",
    "datenanalyse": "Die Datenanalyse zeigt, warum sich flexible Fahrweise lohnt: Preismuster, Treiber, Ausreißer.",
    "backtest": "Der Nachweis: echte Tage, Fahrplan auf der Prognose geplant und zu Ist-Preisen abgerechnet, gegen Dauerbetrieb.",
    "speicher": "Hier siehst du, was es bringt, den Gasspeicher über Tagesgrenzen hinweg zu planen.",
    "anlagendaten": "Hier kommen die echten Anlagenwerte von FLD hinein, damit die Modelle kalibriert werden können.",
}

Answer = dict  # {"reply": str, "tool_calls": list, "actions": list[{label, route}], "mode": "basis"}


def _de(v: float | None, dp: int = 1) -> str:
    """Deutsche Zahl: 1.234,5"""
    if v is None:
        return "—"
    return f"{v:,.{dp}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _eur(v: float | None) -> str:
    return "—" if v is None else f"{_de(v, 0)} €"


def _signed(v: float | None, unit: str = " €", dp: int = 0) -> str:
    """Mit Vorzeichen: +12 € / -12 € (nie „+-12 €“)."""
    return "—" if v is None else f"{'+' if v >= 0 else ''}{_de(v, dp)}{unit}"


def _day_s(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def _day(d) -> str:
    return d.strftime("%d.%m.%Y") if hasattr(d, "strftime") else str(d)


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()  # Marktzeit, nicht Rechnerzeit


def day_word(d: date | None) -> str:
    """„morgen“ nur, wenn der Liefertag wirklich morgen ist — sonst das Datum (Review M-07)."""
    if d is None:
        return "morgen"
    delta = (d - _today()).days
    return {0: "heute", 1: "morgen"}.get(delta, f"am {_day(d)}")


def stale_note(d: date | None) -> str:
    """Hinweis, wenn der jüngste Fahrplan nicht für morgen gilt (Tageskette heute noch nicht gelaufen)."""
    if d is None or d > _today():
        return ""
    return f"Achtung: Das ist der Stand vom {_day(d)} — die Tageskette ist seitdem nicht gelaufen.\n\n"


def _clean_reason(r: str) -> str:
    """Begründungen des Entscheidungs-Agenten lesbar machen (Codes, Pfeile, Einheiten)."""
    for code, label in STRATEGY_LABEL.items():
        r = r.replace(code, f"„{label}“")
    r = re.sub(r"\s*\(Co-Optimierung M\d[^)]*\)", "", r)
    r = r.replace("->", "→").replace("EUR/MWh", "€/MWh").replace("(EUR/MW)/h", "€/MW·h").replace(" EUR", " €")
    return re.sub(r"(\d)\.(\d)", r"\1,\2", r)  # 93.5 → 93,5


def _why_lead(rationale: list[str], strategy: str | None = None, when: str = "morgen") -> str:
    """Kernsatz zur getroffenen Entscheidung: was es bringt und warum (nicht nur, welche Zahl größer ist).

    Entschieden wird vor den Auktionen auf der Prognose („Spot-Flex a vs. Regelenergie b“); nach der Auktion steht
    zusätzlich das Ergebnis zu Auktionspreisen da („Ergebnis zu Auktionspreisen: x (nur Spot: y)“). Beides getrennt
    nennen — sonst begründet der Satz eine Entscheidung mit Zahlen, die es bei der Entscheidung noch nicht gab."""
    text = " ".join(rationale)
    m = re.search(r"Spot-Flex (-?[\d.]+) EUR vs\. Regelenergie (-?[\d.]+) EUR", text)
    if not m:
        return ""
    spot, reg = float(m.group(1)), float(m.group(2))
    res = re.search(r"Ergebnis zu Auktionspreisen: (-?[\d.]+) EUR gegenüber Dauerbetrieb \(nur Spot: (-?[\d.]+) EUR\)", text)
    Wh = f"{when[:1].upper()}{when[1:]}"
    if strategy == "REGELENERGIE_RESERVE":
        lead = (f"{Wh} lohnt es sich, zusätzlich Regelenergie vorzuhalten: laut Prognose {_signed(reg)} statt {_signed(spot)} "
                f"nur am Spotmarkt — jeweils gegenüber Dauerbetrieb.")
        if res:
            lead += (f" Zu den Auktionspreisen bringt der Plan {_signed(float(res.group(1)))} "
                     f"(nur Spot wären es {_signed(float(res.group(2)))} gewesen).")
        return lead
    what = "Flexibel fahren und in den billigsten Stunden Wasserstoff erzeugen" if strategy == "PTX_PRIORITY" else "Flexibel fahren"
    lead = f"{what} bringt {when} {_signed(float(res.group(1)) if res else spot)} gegenüber Dauerbetrieb."
    if reg - spot > 0.5:
        lead += f" Regelenergie brächte laut Prognose nur {_eur(reg - spot)} zusätzlich — zu wenig für den Aufwand."
    return lead


def _norm(text: str) -> str:
    t = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("₂", "2")):
        t = t.replace(a, b)
    # Datumsangaben (12.10. / 15.10.2026) sind keine Zahlen für Annahmen: „CO2-Preis am 12.10.“ ≠ CO₂ 12 €/t
    return re.sub(r"\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?", " ", t)


def _num_after(t: str, words: str) -> float | None:
    m = re.search(rf"(?:{words})\D{{0,20}}?(\d+(?:[.,]\d+)?)", t)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_whatif(text: str) -> dict | None:
    """Liest Gas/H₂/CO₂/Pfad aus einer Frage. None, wenn keine Zahl zu einer Annahme gehört.

    Nicht genannter Gaspreis bleibt None → der Aufrufer setzt den Marktwert (TTF + Biomethan-Aufschlag) ein,
    wie die Seite Was-wäre-wenn. Technik ohne Angabe = Anlage wie geplant (BHKW + Elektrolyseur)."""
    t = _norm(text)
    gas = _num_after(t, r"gas(?:preis)?")
    h2 = _num_after(t, r"h2(?:-wert)?|wasserstoff")
    co2 = _num_after(t, r"co2(?:-preis)?|cdr|kohlenstoff")
    if gas is None and h2 is None and co2 is None:
        return None
    mode = "electro"
    if re.search(r"plasma|pyrolyse", t):
        mode = "plasma"
    elif re.search(r"ohne ptx|nur bhkw|nur strom|ohne wasserstoff|ohne elektrolyse", t):
        mode = "none"
    return {"gas": gas, "h2": h2 if h2 is not None else 100.0, "co2": co2 if co2 is not None else 79.0, "mode": mode}


async def _market_gas(store: Repository, plant) -> float:
    """Biomethan heute: letzter TTF + Aufschlag der Anlage (wie der Startwert auf Was-wäre-wenn)."""
    rows = sorted((r for r in await store.fundamentals() if r.ttf_gas_eur_mwh is not None), key=lambda r: r.day)
    return round((rows[-1].ttf_gas_eur_mwh if rows else 40.0) + plant.bio_premium_eur_mwh)


async def _a_recommendation(store: Repository, _t: str, _p: str | None) -> Answer:
    run = await store.latest_run()
    if not run:
        return _ans("Es liegt noch kein Fahrplan vor. Sobald die Tageskette gelaufen ist, sage ich dir, was morgen dran ist.")
    k = run.kpis or {}
    d = await store.decision_for_run(run.id)
    strat = STRATEGY_LABEL.get(d.strategy, d.strategy) if d else "—"
    return _ans(
        f"{stale_note(run.target_day)}Für den {_day(run.target_day)} empfehle ich: **{strat}**.\n\n"
        f"Erwarteter Erlös {_eur(k.get('expected_revenue_eur'))}, das sind {_eur(k.get('expected_uplift_eur'))} mehr als Dauerbetrieb. "
        f"Das BHKW läuft {_de(k.get('bhkw_runtime_h'))} h, die Preise liegen zwischen {_de(k.get('pred_price_min'), 0)} "
        f"und {_de(k.get('pred_price_max'), 0)} €/MWh.",
        ["get_recommendation", "get_decision"],
        [("Fahrplan ansehen", "empfehlung"), ("Was wäre, wenn …", "was-waere-wenn")],
    )


async def _a_why(store: Repository, _t: str, _p: str | None) -> Answer:
    run = await store.latest_run()
    d = await store.decision_for_run(run.id) if run else None
    if not d:
        return _ans("Zur aktuellen Empfehlung ist keine Begründung hinterlegt.")
    reasons = "\n".join(f"- {_clean_reason(r)}" for r in (d.rationale or [])) or "- keine Begründung gespeichert"
    lead = _why_lead(d.rationale or [], d.strategy, day_word(run.target_day))
    return _ans(f"Ich empfehle **{STRATEGY_LABEL.get(d.strategy, d.strategy)}**. {lead}\n\nDie Details:\n{reasons}",
                ["get_decision"], [("Fahrplan ansehen", "empfehlung")])


async def _a_value(store: Repository, _t: str, _p: str | None) -> Answer:
    v = analytics.value_summary(await store.backtest())
    if v is None:
        return _ans("Es liegt noch kein Backtest vor — die Tageskette muss erst laufen.")
    cap = f" Das sind {_de(v['capture_pct'], 0)} % dessen, was mit perfekter Voraussicht möglich wäre." if v["capture_pct"] else ""
    return _ans(
        f"Hochgerechnet bringt die Optimierung **rund {_eur(round(v['per_year_eur'], -3))} pro Jahr und MW** mehr als Dauerbetrieb "
        f"({_signed(v['pct_vs_flat'], ' %')}).\n\nGemessen an {v['days']} echten Tagen ({_day(v['from_day'])} bis {_day(v['to_day'])}): "
        f"Fahrplan jeweils am Vortag auf der Prognose geplant und zu den tatsächlichen Preisen abgerechnet — "
        f"im Schnitt {_eur(v['per_day_eur'])} pro Tag.{cap}",
        ["get_value"], [("Nachweis ansehen", "backtest"), ("Mit eigenen Annahmen rechnen", "was-waere-wenn")],
    )


async def _a_timing(store: Repository, _t: str, _p: str | None) -> Answer:
    run = await store.latest_run()
    rows = await store.dispatch_for_run(run.id) if run else []
    if not rows:
        return _ans("Es liegt noch kein Fahrplan vor.")
    plant = await _plant(store)
    on = [r for r in rows if (r.bhkw_mw or 0) > 1e-6]
    off = [r for r in rows if (r.bhkw_mw or 0) <= 1e-6]
    avg = lambda xs: sum(r.pred_price or 0 for r in xs) / len(xs) if xs else None  # noqa: E731
    top = sorted(rows, key=lambda r: r.pred_price or 0, reverse=True)[:len(on)]
    share = sum(1 for r in top if (r.bhkw_mw or 0) > 1e-6) / len(top) if top else 0
    return _ans(
        f"Das BHKW läuft {_de(len(on) * plant.dt_h)} h, im Schnitt bei {_de(avg(on), 0)} €/MWh — in den übrigen Stunden läge der "
        f"Preis bei {_de(avg(off), 0)} €/MWh. Von den {_de(len(on) * plant.dt_h)} teuersten Stunden des Tages nutzt es "
        f"{_de(share * 100, 0)} %.\n\nWarum nicht einfach jede Preisspitze? Der Plan hält drei Grenzen der Anlage ein:\n"
        f"- **Gas kommt gleichmäßig** ({_de(plant.full_hours_per_day, 0)} Volllast-h pro Tag), der Speicher fasst {_de(plant.storage_hours, 0)} h — "
        f"wartet die Anlage zu lange, läuft er über; läuft sie zu lange am Stück, ist er leer.\n"
        f"- **Am Tagesende muss der Speicher wieder so voll sein wie am Morgen**, sonst fehlt am nächsten Tag Gas.\n"
        f"- **Wärme und Technik**: mindestens {_de(plant.heat_min_runtime_slots * plant.dt_h, 0)} h Lauf für die Wärme, "
        f"nach einem Start mindestens {_de(plant.min_up_slots * plant.dt_h, 0)} h, jeder Start kostet {_eur(plant.start_cost_eur)}.\n\n"
        f"Über mehrere Tage geplant wird die zweite Grenze lockerer — das zeigt die Seite Speicher.",
        ["get_recommendation"], [("Fahrplan ansehen", "empfehlung"), ("Mehrtages-Planung", "speicher")],
    )


async def _a_whatif(store: Repository, t: str, _p: str | None) -> Answer:
    args = parse_whatif(t)
    if args is None:
        return _ans("Nenn mir eine Annahme mit Zahl, zum Beispiel: „Rechne mit Gaspreis 100 und H₂-Wert 150.“",
                    actions=[("Regler öffnen", "was-waere-wenn")])
    prices = await store.prices_latest()
    if not prices:
        return _ans("Ich habe noch keine Preisbasis für einen Tag — die Tageskette muss erst laufen.")
    plant = await _plant(store)
    gas_now = await _market_gas(store, plant)
    if args["gas"] is None:
        args["gas"] = gas_now
    r = await asyncio.to_thread(optimizers.run_algo, "whatif", prices, **args, plant=plant)
    # Vergleich: der Plan wie im Cockpit (Gas heute, H₂ 100, CO₂ 79, BHKW + Elektrolyseur)
    base = await asyncio.to_thread(optimizers.run_algo, "whatif", prices, gas=gas_now, mode="electro", plant=plant)
    # Netto inkl. EEG wie auf der Seite (Marktprämie + Flexzuschlag, fldos/eeg.py)
    run = await store.latest_run()
    mw = await asyncio.to_thread(eeg.monthly_market_value, analytics.HISTORY, run.target_day) if run else None
    net = lambda x: eeg.net_incl_eeg(x, prices, plant, mw)  # noqa: E731 — dasselbe Netto wie Seite und Sensitivität
    delta = net(r) - net(base)
    label = "netto inkl. EEG" if mw is not None else "netto"
    pfad = {"plasma": "Plasma-Pyrolyse", "electro": "Elektrolyse", "none": "nur BHKW"}[args["mode"]]
    return _ans(
        f"Mit Gas {args['gas']:.0f} €/MWh, H₂ {args['h2']:.0f} €/MWh und CO₂ {args['co2']:.0f} €/t ({pfad}) "
        f"liegt der Tag bei **{_eur(net(r))} {label}** — {_signed(delta)} gegenüber dem Plan für morgen (Gas heute {_de(gas_now, 0)} €/MWh).\n\n"
        f"Das BHKW läuft {_de(r['bhkw_h'])} h, dazu {_de(r['h2_mwh'])} MWh Wasserstoff.",
        ["run_whatif"], [("Selbst an den Reglern drehen", "was-waere-wenn"), ("Welche Annahme zählt am meisten?", "sensitivitaet")],
    )


async def _a_backtest(store: Repository, _t: str, _p: str | None) -> Answer:
    bt = await store.backtest()
    if not bt:
        return _ans("Es liegt noch kein Backtest vor.")
    sfc = sum(x.up_fc or 0 for x in bt)
    spf = sum(x.up_pf or 0 for x in bt)
    better = sum(1 for x in bt if (x.up_fc or 0) >= -0.5)  # Mehrerlös ≥ 0 (Rundung), nicht Löserstatus
    return _ans(
        f"Über **{len(bt)} echte Tage** hat der optimierte Fahrplan {_eur(sfc)} mehr erlöst als Dauerbetrieb — "
        f"im Schnitt {_eur(sfc / len(bt))} pro Tag. Das sind {sfc / spf * 100:.0f} % dessen, was mit perfekter Voraussicht möglich wäre. "
        f"An {better} von {len(bt)} Tagen war er mindestens so gut wie Dauerbetrieb.",
        ["get_backtest"], [("Backtest ansehen", "backtest")],
    )


async def _a_market(store: Repository, _t: str, _p: str | None) -> Answer:
    m = await store.fundamentals()
    if not m:
        return _ans("Mir liegen keine Marktdaten vor.")
    last = max(m, key=lambda x: x.day)
    return _ans(f"Stand {_day(last.day)}: Gas (TTF) {_de(last.ttf_gas_eur_mwh)} €/MWh, CO₂ (EUA) {_de(last.eua_co2_eur_t)} €/t.",
                ["get_market"], [("Markt-Kontext", "markt")])


async def _plant(store: Repository):
    from config import PLANT
    return PLANT.with_overrides(await store.get_plant_config())


async def _cached(store: Repository, name: str, fn, *args, plant_free: bool = False):
    # Gleicher Schlüssel wie Endpoints/Warm-up: Anlage immer als plant=… (außer anlagenunabhängig)
    kw = {} if plant_free else {"plant": await _plant(store)}
    return await asyncio.to_thread(analytics.cached, name, fn, *args, **kw)


async def _a_risk(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "risk", analytics.risk)
    return _ans(
        f"Für den {_day_s(r['day'])}: Ein gegen schlechte Preisszenarien geplanter Fahrplan bringt {_eur(r['rp'])}, "
        f"der reine Punktprognose-Plan {_eur(r['eev'])}. Die Absicherung ist hier also {_eur(r['vss'])} wert; "
        f"perfekte Voraussicht brächte nochmal {_eur(r['evpi'])}.",
        ["risk"], [("Risiko ansehen", "risiko")],
    )


async def _a_plasma(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "plasma", analytics.plasma_compare, analytics.DEF_PLASMA_DAYS)
    winner = "Plasma-Pyrolyse" if r["uplift_pyro"] > r["uplift_electro"] else "Elektrolyse"
    return _ans(
        f"In den letzten {len(r['rows'])} Tagen bringt Elektrolyse {_signed(r['uplift_electro'])} und Plasma-Pyrolyse "
        f"{_signed(r['uplift_pyro'])} pro Tag gegenüber reinem Strombetrieb. Vorn liegt: **{winner}**. "
        f"Das kippt mit dem Kohlenstoff-Preis.",
        ["plasma_compare"], [("Vergleich ansehen", "plasma"), ("Ab welchem CO₂-Preis?", "cdr")],
    )


async def _a_stack(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "stack", analytics.revenue_stack, analytics.DEF_STACK_DAYS)
    return _ans(
        f"Wenn ein Teil der Leistung als Regelenergie vorgehalten wird, kommen im Schnitt **{_signed(r['avg_uplift'])} pro Tag** dazu "
        f"(≈ {_eur(r['uplift_per_mw_year'])} pro MW und Jahr). aFRR+ bringt Ø {_de(r['afrr'])}, aFRR− Ø {_de(r['afrr_neg'])}, FCR Ø {_de(r['fcr'])} €/MW·h.",
        ["revenue_stack"], [("Erlös-Stapel ansehen", "erloes-stapel")],
    )


async def _a_band(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "band", analytics.forecast_band, analytics.DEF_BAND_DAYS, plant_free=True)
    c = r["coverage"]
    return _ans(
        f"Das 80-%-Prognoseband trifft mit adaptiver Korrektur {c['aci'] * 100:.0f} % der Ist-Preise "
        f"(ohne Korrektur nur {c['raw'] * 100:.0f} %). Dafür ist es im Schnitt {r['width']['aci']:.0f} €/MWh breit.",
        ["forecast_band"], [("Prognoseband ansehen", "prognoseband")],
    )


async def _a_mpc(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "mpc", analytics.mpc_state, analytics.DEF_MPC_DAYS)
    d = r["total_mpc"] - r["total_base"]
    return _ans(
        f"Den Gasspeicher über Tagesgrenzen zu planen bringt in {len(r['days'])} Tagen {_signed(d)} "
        f"(≈ {_eur(r['uplift_per_mw_year'])} pro MW und Jahr). Mehr geht nicht, weil der Speicher nur etwa einen Tag fasst.",
        ["mpc"], [("Speicher ansehen", "speicher")],
    )


async def _a_pareto(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    r = await _cached(_s, "pareto", analytics.pareto)
    if r["slope_eur_t"] is None:
        return _ans("Für den Analysetag gibt es keinen Zielkonflikt zwischen Erlös und CO₂.", ["pareto"], [("Ansehen", "pareto")])
    verdict = "günstiger als ein Zertifikat" if r["cheaper_than_eua"] else "teurer als ein Zertifikat"
    return _ans(
        f"Mehr CO₂ durch Umplanen zu vermeiden kostet am {_day_s(r['day'])} rund {_eur(r['slope_eur_t'])} pro Tonne — "
        f"{verdict} ({_eur(r['eua'])}/t).",
        ["pareto"], [("Erlös ↔ CO₂ ansehen", "pareto")],
    )


async def _a_page(_s: AsyncSession, _t: str, page: str | None) -> Answer:
    text = PAGE_HELP.get(page or "", "Frag mich zu Fahrplan, Erlösen, Risiko, Prognose oder Technologie.")
    return _ans(text)


async def _a_help(_s: AsyncSession, _t: str, _p: str | None) -> Answer:
    return _ans(
        "Hallo, ich bin Enno. Ich kenne die Zahlen dieser Anlage und rechne für dich nach. Frag mich zum Beispiel:\n"
        "- Was soll die Anlage morgen tun?\n- Rechne mit Gaspreis 100.\n- Lohnt sich Plasma?\n- Wie gut war der Backtest?")


def _ans(reply: str, tools: list[str] | None = None, actions: list[tuple[str, str]] | None = None) -> Answer:
    return {"reply": reply, "tool_calls": [{"name": n, "input": {}} for n in (tools or [])],
            "actions": [{"label": lbl, "route": r} for lbl, r in (actions or [])], "mode": "basis"}


# Reihenfolge = Priorität. Was-wäre-wenn zuerst, weil „CO₂ 120“ sonst beim Markt landet.
INTENTS: list[tuple[str, Callable[[AsyncSession, str, str | None], Awaitable[Answer]]]] = [
    (r"rechne|was waere|wenn .*\d|\b(gas|h2|co2|cdr)\w*\D{0,20}\d", _a_whatif),
    (r"diese seite|was sehe ich|was zeigt|erklaer (mir )?(das|die seite)|was ist hier", _a_page),
    (r"(warum|wieso|weshalb).*(nachts|nachmittag|abend|morgens|frueh|spaet|uhr|zeit|spitze|teuer|laeuft)|wann laeuft", _a_timing),
    (r"warum|begruend|wieso", _a_why),
    (r"backtest|beweis|wie gut|zuverlaess|capture|historisch|nachweis", _a_backtest),
    (r"risiko|cvar|absicher|worst|robust", _a_risk),
    (r"plasma|pyrolyse|elektrolyse", _a_plasma),
    (r"regelenergie|afrr|fcr|reserve|erloes-?stapel|erloesquellen", _a_stack),
    (r"unsicher|prognoseband|\bband\b|genau|trefferquote", _a_band),
    (r"speicher|mpc|mehrere tage", _a_mpc),
    (r"co2 (sparen|vermeid)|klima|pareto|vermeidung|emission", _a_pareto),
    (r"markt|gaspreis|ttf|eua|co2-preis|zertifikat|kostet (das )?gas|gas (heute|aktuell|kostet)", _a_market),
    (r"im jahr|pro jahr|jaehrlich|mehrwert|was bringt|bringt (das|es|die)|lohnt (sich|das)|wie ?viel .*(verdien|mehr)|rendite", _a_value),
    (r"morgen|fahrplan|was soll|empfehl|heute|strategie|plan", _a_recommendation),
    (r"hilfe|was kannst|hallo|\bhi\b|moin|servus|wer bist", _a_help),
]


async def basis_chat(store: Repository, message: str, page: str | None = None) -> Answer:
    t = _norm(message)
    for pattern, handler in INTENTS:
        if re.search(pattern, t):
            return await handler(store, message, page)
    return _ans("Das kann ich noch nicht beantworten. Probier es mit Fahrplan, Erlösen, Risiko, Plasma, Prognose oder "
                "„Rechne mit Gaspreis 100“.")
