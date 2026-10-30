"""F09 Architekturentscheidungen sind festgehalten (docs/adr/NNNN-*.md) und zeigen auf echten Code."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PFLICHT = {  # Thema → Wort, das die ADR enthalten muss
    "Speicher-Port": "MemoryRepository",
    "Fehlermodell": "problem+json",
    "Engine-Kopie statt geteiltem Paket": "fld-energy",
    "PuLP-Pin": "pulp<4",
}


def _adrs() -> list[Path]:
    return sorted((ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_struktur():
    adrs = _adrs()
    assert len(adrs) >= 4, [a.name for a in adrs]
    for a in adrs:
        t = a.read_text()
        for teil in ("Status:", "## Kontext", "## Entscheidung", "## Konsequenzen"):
            assert teil in t, (a.name, teil)


def test_pflichtthemen_abgedeckt():
    texte = [a.read_text() for a in _adrs()]
    fehlt = [thema for thema, wort in PFLICHT.items() if not any(wort in t for t in texte)]
    assert not fehlt, fehlt


def test_jede_adr_zeigt_auf_existierenden_code():
    for a in _adrs():
        pfade = [p for p in re.findall(r"`([\w./-]+\.(?:py|ts|tsx|css|toml|json))`", a.read_text())]
        assert pfade, f"{a.name}: kein Code-Pfad in Backticks"
        fehlt = [p for p in pfade if not (ROOT / p).exists()]
        assert not fehlt, (a.name, fehlt)
