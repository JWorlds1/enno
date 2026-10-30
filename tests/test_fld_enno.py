"""Enno-Tools gegen die lokale DB (die deterministische, LLM-freie Logik).

Der LLM-Loop (Bedrock) wird live getestet; hier die Tool-Dispatches, die die echten Zahlen liefern.
"""
import asyncio

from fldos import enno
from fldos.db import engine
from fldos.storage import PostgresRepository


def test_enno_tools_return_grounded_strings():
    asyncio.run(_t())


async def _t() -> None:
    try:
        s = PostgresRepository()
        rec = await enno._dispatch_tool(s, "get_recommendation", {})
        assert isinstance(rec, str) and ("Fahrplan" in rec or "Kein Lauf" in rec)

        wf = await enno._dispatch_tool(s, "run_whatif", {"gas": 70, "h2": 100, "co2": 79, "mode": "plasma"})
        assert "Netto" in wf or "Keine Preisbasis" in wf

        bt = await enno._dispatch_tool(s, "get_backtest", {})
        assert "Backtest" in bt

        mk = await enno._dispatch_tool(s, "get_market", {})
        assert "Markt" in mk or "Keine Marktdaten" in mk

        sm = await enno._dispatch_tool(s, "search_memory", {"query": "empfehlung"})
        assert isinstance(sm, str)

        unknown = await enno._dispatch_tool(s, "nope", {})
        assert "Unbekannt" in unknown
    finally:
        await engine.dispose()


# ── Basis-Modus (ohne Sprachmodell) ─────────────────────────────────────────
def test_parse_whatif_reads_numbers_and_mode():
    assert enno.parse_whatif("Rechne mit Gaspreis 100 und H2-Wert 150.") == {"gas": 100.0, "h2": 150.0, "co2": 79.0, "mode": "electro"}
    assert enno.parse_whatif("H2-Wert 150 mit Plasma") == {"gas": None, "h2": 150.0, "co2": 79.0, "mode": "plasma"}
    assert enno.parse_whatif("was wäre wenn CO₂ 120 €/t mit Elektrolyse")["co2"] == 120.0
    assert enno.parse_whatif("gas 80,5 nur bhkw") == {"gas": 80.5, "h2": 100.0, "co2": 79.0, "mode": "none"}
    assert enno.parse_whatif("Was soll die Anlage morgen tun?") is None
    assert enno.parse_whatif("Wie hoch war der CO2-Preis am 12.10.?") is None  # Datum, keine Annahme
    assert enno.parse_whatif("Rechne mit Gas 90 für den 15.10.2026") == {"gas": 90.0, "h2": 100.0, "co2": 79.0, "mode": "electro"}


def test_basis_routes_questions_to_grounded_answers():
    asyncio.run(_basis())


async def _basis() -> None:
    try:
        s = PostgresRepository()
        cases = {
            "Was soll die Anlage morgen tun?": "get_recommendation",
            "Rechne mit Gaspreis 100": "run_whatif",
            "CO₂ 150 bitte": "run_whatif",
            "Wie gut war der Backtest?": "get_backtest",
            "Wie steht der Gaspreis am Markt?": "get_market",
            "Warum diese Strategie?": "get_decision",
            # M-08: ein Datum ist keine Annahme, „Gas heute“ ist eine Marktfrage
            "Wie hoch war der CO2-Preis am 12.10.?": "get_market",
            "Was kostet Gas heute?": "get_market",
        }
        for q, tool in cases.items():
            a = await enno.basis_chat(s, q)
            assert a["mode"] == "basis"
            names = [c["name"] for c in a["tool_calls"]]
            assert tool in names or "Kein" in a["reply"] or "keine" in a["reply"], (q, a)
        page = await enno.basis_chat(s, "Was sehe ich hier?", page="risiko")
        assert page["reply"] == enno.PAGE_HELP["risiko"]
        unknown = await enno.basis_chat(s, "Wie wird das Wetter in Rom?")
        assert unknown["tool_calls"] == [] and "noch nicht" in unknown["reply"]
    finally:
        await engine.dispose()


def test_every_ui_suggestion_gets_a_real_answer():
    """Jeder Vorschlags-Button in der Enno-Leiste muss eine echte Antwort liefern, nie den Fallback."""
    import pathlib
    import re as _re
    src = (pathlib.Path(__file__).resolve().parent.parent / "web/src/Enno.tsx").read_text()
    block = src[src.index("const GENERAL"):src.index("/** Minimal-Markdown")]
    questions = sorted(set(_re.findall(r"'([^']+\?|Rechne[^']*)'", block)))
    assert len(questions) >= 10
    asyncio.run(_suggestions(questions))


async def _suggestions(questions: list[str]) -> None:
    try:
        s = PostgresRepository()
        for q in questions:
            a = await enno.basis_chat(s, q, page="risiko")
            assert "noch nicht beantworten" not in a["reply"], q
    finally:
        await engine.dispose()
