# 0004 — PuLP-Pin pulp<4

Status: angenommen (2026-09-28, Grundgerüst `61b6dec`; hier nachträglich festgehalten)

## Kontext

Alle MILP-Modelle in `engine/` bauen auf PuLP/CBC. Sie legen Variablen mit positionalen Argumenten an,
etwa `pulp.LpVariable(f"rp{b}", 0, P)` in `engine/coopt_milp.py`. Laut Kommentar in `pyproject.toml`
bricht PuLP 4.0 diese positionalen `LpVariable`-Argumente; die Engine ist auf 3.3.x validiert (in der
Repo-venv liegt 3.3.2). Der Commit `61b6dec` nennt den Pin ausdrücklich: „pulp<4 gepinnt“.

## Entscheidung

`pyproject.toml` begrenzt die Abhängigkeit auf `pulp>=3.0,<4`. Der Pin gilt für Entwicklung und Image
(`Dockerfile` installiert aus `pyproject.toml`). Die Engine wird nicht auf PuLP 4 migriert.

## Konsequenzen

- Reproduzierbare Fahrpläne: `tests/test_engine_golden.py` vergleicht Zielwerte und Fahrpläne mit
  `tests/golden/engine_baseline.json`; ein stiller PuLP-Sprung würde dort auffallen.
- Fixes und Funktionen aus PuLP ≥ 4 fehlen, auch Sicherheitskorrekturen, sofern es welche gibt.
- Aufheben des Pins heißt: Variablen mit benannten Argumenten anlegen (`lowBound=`, `upBound=`, `cat=`)
  in allen Dateien unter `engine/`, dann Golden-Test auf dem neuen PuLP laufen lassen. Dieser Weg ist hier
  nicht versucht worden; ob PuLP 4 sonst noch bricht, ist unbekannt.
- `libgomp1` für CBC im `Dockerfile` ist davon unabhängig.
