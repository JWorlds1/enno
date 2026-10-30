"""Der Kernsatz (Cockpit + Enno) begründet die getroffene Entscheidung — nie das Gegenteil."""
from fldos.enno import _why_lead

R = ["Spot-Flex 592.0 EUR vs. Regelenergie 604.2 EUR (Spot + Reserve; …)."]


def test_lead_follows_decision_not_bigger_number():
    ptx = _why_lead(R, "PTX_PRIORITY")
    assert "Wasserstoff" in ptx and "+592 €" in ptx and "nur 12 € zusätzlich" in ptx
    assert "lohnt es sich, zusätzlich Regelenergie" not in ptx
    assert "+604 € statt +592 €" in _why_lead(R, "REGELENERGIE_RESERVE")
    assert _why_lead(["Spot-Flex 300.0 EUR vs. Regelenergie 300.0 EUR"], "SPOT_FLEX") == "Flexibel fahren bringt morgen +300 € gegenüber Dauerbetrieb."


def test_day_word_and_stale_note_follow_market_date(monkeypatch):
    # M-07: „morgen“ nur, wenn der Liefertag morgen ist; alter Fahrplan → Hinweis mit Datum
    from datetime import date

    from fldos import enno
    monkeypatch.setattr(enno, "_today", lambda: date(2026, 10, 14))
    assert enno.day_word(date(2026, 10, 15)) == "morgen"
    assert enno.day_word(date(2026, 10, 14)) == "heute"
    assert enno.day_word(date(2026, 10, 11)) == "am 11.10.2026"
    assert enno.stale_note(date(2026, 10, 15)) == ""
    assert "Stand vom 11.10.2026" in enno.stale_note(date(2026, 10, 11))
    assert _why_lead(["Spot-Flex 300.0 EUR vs. Regelenergie 300.0 EUR"], "SPOT_FLEX", "am 11.10.2026") == \
        "Flexibel fahren bringt am 11.10.2026 +300 € gegenüber Dauerbetrieb."


def test_lead_separates_decision_on_forecast_from_auction_result():
    """Entschieden vor der Auktion (Prognose), bewertet danach (Auktion): nie „lohnt sich: +257 € statt +297 €“."""
    r = ["Entscheidung auf der Prognose: Spot-Flex 296.0 EUR vs. Regelenergie 333.0 EUR (Spot + Reserve; …).",
         "Ergebnis zu Auktionspreisen: 257.0 EUR gegenüber Dauerbetrieb (nur Spot: 297.0 EUR)."]
    lead = _why_lead(r, "REGELENERGIE_RESERVE")
    assert "laut Prognose +333 € statt +296 €" in lead
    assert "Zu den Auktionspreisen bringt der Plan +257 €" in lead and "nur Spot wären es +297 €" in lead
    spot = _why_lead(["Entscheidung auf der Prognose: Spot-Flex 296.0 EUR vs. Regelenergie 300.0 EUR (…).",
                      "Ergebnis zu Auktionspreisen: 305.0 EUR gegenüber Dauerbetrieb (nur Spot: 305.0 EUR)."], "SPOT_FLEX")
    assert spot.startswith("Flexibel fahren bringt morgen +305 €")  # Kernsatz = Zahl der Kachel (Auktion)
