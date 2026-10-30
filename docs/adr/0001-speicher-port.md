# 0001 — Speicher-Port: MemoryRepository und PostgresRepository

Status: angenommen (2026-10-09, Lauf r-20261008-fld-os-autonom, Feature f01/f02)

## Kontext

`fldos/repository.py` enthält typisierte Postgres-Zugriffe als freie Funktionen, die eine
`AsyncSession` erwarten. Die API (`fldos/api.py`) und der Assistent (`fldos/enno.py`) riefen sie
direkt auf und hingen damit an SQLAlchemy und `fldos/db.py`. Ohne Postgres ließ sich die API weder
testen noch betreiben; `fldos/db.py` baut bei `memory://` keinen Engine.

## Entscheidung

Persistenz liegt hinter einem Port in `fldos/storage.py` mit zwei Adaptern:

- `PostgresRepository` delegiert an `fldos/repository.py`, verwaltet die Session selbst, committet je
  Aufruf und erzeugt den Engine erst beim ersten Zugriff (`fldos/db.py`, `get_sessionmaker`).
- `MemoryRepository` hält den Zustand je Instanz im Prozess; jede Zeile trägt `tenant_id`
  (Default `settings.TENANT_ID` aus `fldos/settings.py`).
- `make_repository(url)` wählt den Adapter (`memory://` → Memory).

`fldos/api.py` und `fldos/enno.py` kennen nur den Port (`Depends(get_repository)` bzw. `store: Repository`).
`fldos/api.py` importiert weder sqlalchemy noch asyncpg noch `.db`; das erzwingt
`tests/abnahme/test_f03_architektur_grenzen.py`. `fldos/repository.py` blieb unverändert Bestand.

## Konsequenzen

- API und Tests laufen mit `FLD_DATABASE_URL=memory://` ohne Postgres (`tests/abnahme/test_f02_api_ohne_postgres.py`).
- Jede neue Persistenzfunktion muss in beiden Adaptern stehen; der Port wuchs bereits um
  `memory_count`, `search_memory` und `ping` (für `GET /api/v1/ready`).
- Der Chat ist keine einzelne Transaktion mehr: jede Port-Methode committet einzeln, bei einem Fehler
  in Enno bleibt die User-Nachricht gespeichert (`.lauf/annahmen.md`, f02).
- Abweichung der Adapter: `MemoryRepository.prices_latest()` liefert nur bei genau 96 Slots einen
  Vektor, der Postgres-Adapter delegiert unverändert.
- Die Postgres-Seite ist hier nur gegen eine unerreichbare DB geprüft; Postgres-Tests
  (`tests/test_fld_repository.py`, `tests/test_plant.py`) liefen in diesem Lauf nicht.
