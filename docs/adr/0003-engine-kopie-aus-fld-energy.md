# 0003 — Engine als Kopie aus fld-energy statt geteiltem Paket

Status: angenommen (2026-09-28, Grundgerüst `61b6dec`; hier nachträglich festgehalten)

## Kontext

Die MILP-Modelle in `engine/` stammen laut Commit `61b6dec` aus dem Thesis-Repo („Aus dem Thesis-Repo
übernommen und entkoppelt“). Dass dieses Repo `fld-energy` heißt, ist im Code nicht belegt; der Name
steht nur als Mandanten-Default (`FLD_TENANT_ID`, `fldos/settings.py`) und im Datenbanknamen
`fld_energy` – die Gleichsetzung ist eine Annahme (`.lauf/annahmen.md`). Beim Übernehmen wurden
Paketname, JWT, Datenverzeichnis (`FLD_DATA_DIR`, `engine/config.py`) und die Thesis-CLIs
herausgelöst. Die Engine kennt keine DB (`fldos/repository.py` trennt sie von der API).

## Entscheidung

`engine/` ist eine eigenständige Kopie im FLD-OS-Repo, kein geteiltes Paket und keine Abhängigkeit auf
fld-energy. Sie wird über `PYTHONPATH=.:engine` importiert (`run-backend.sh`, `Dockerfile`) und gehört
ab da FLD OS: `engine/dispatch.py` ist nun der gemeinsame Rechenkern, `engine/config.py` (`PlantConfig`)
die einzige Quelle für Anlagenwerte (Commit `b2febee`). Rückwärtskompatibel bleibt das über die
Vergleichswerte in `tests/test_engine_golden.py` und `tests/golden/engine_baseline.json` (Commit `2312926`).

## Konsequenzen

- Die Engine lässt sich frei umbauen (Commit `b2febee`: −116 Zeilen, 13/13 Golden-Fälle identisch;
  f07: `whatif.solve_day(on=…)`, `coopt_milp.optimise(detail=True)`), ohne ein zweites Repo abzustimmen.
- Änderungen in fld-energy kommen nicht automatisch an; sie müssen von Hand übertragen werden, und die
  Kopie wird davon weg driften. Es gibt kein Verfahren, das den Abstand misst.
- Variablennamen und Bedingungsreihenfolge sind Teil des Interfaces (Kopf von `engine/dispatch.py`):
  PuLP sortiert nach Namen, CBC rechnet in dieser Reihenfolge – der Golden-Test sichert das ab.
- Der Import über `PYTHONPATH` statt über ein installiertes Paket ist Bestand; `fldos` und `engine`
  sind separat zu erreichen.
