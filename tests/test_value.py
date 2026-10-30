"""Mehrwert-Kennzahl: eine Rechnung für Cockpit und Enno."""
from datetime import date
from types import SimpleNamespace as R

from fldos.analytics import value_summary


def test_value_summary_from_backtest_rows():
    rows = [R(day=date(2026, 1, 1), flat=1000.0, up_fc=300.0, up_pf=400.0),
            R(day=date(2026, 1, 2), flat=1000.0, up_fc=100.0, up_pf=200.0),
            R(day=date(2026, 1, 3), flat=None, up_fc=None, up_pf=None)]  # unvollständig → ignoriert
    v = value_summary(rows)
    assert v["days"] == 2 and v["uplift_eur"] == 400 and v["per_day_eur"] == 200
    assert v["per_year_eur"] == 73000 and v["pct_vs_flat"] == 20.0
    assert v["capture_pct"] == round(400 / 600 * 100, 1)
    assert value_summary([]) is None
