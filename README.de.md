# FLD OS

Betriebsoptimierungs-Plattform für Biomethan-BHKW, Wasserstoff (Elektrolyse) und Plasma-Pyrolyse.
Erster Mandant: **FLD Technologies**. Aus jedem Tag mit Markt- und Wetterdaten wird ein
viertelstündlicher Fahrplan, dazu Risiko-, Erlös- und CO₂-Analysen.

## Aufbau

| Teil | Pfad | Inhalt |
|---|---|---|
| Engine | `engine/` | MILP-Modelle (PuLP/CBC): Fahrplan, What-if, Plasma, Co-Optimierung, mean-CVaR, Pareto, MPC |
| API | `fldos/` | FastAPI + Postgres/pgvector, mandantenfähig (`tenant_id`), Analyse-Endpoints mit Cache |
| Web | `web/` | React + Vite + chart.js, Marke/Farben zentral in `web/src/brand.ts` und `web/src/theme.css` |
| Daten | `data/` (gitignored) | Preis-/Prognose-CSVs, Abbildungen, Report — per `FLD_DATA_DIR` umlenkbar |

## Module

Betrieb: Cockpit · Fahrplan & Empfehlung · Assistent Enno ·
Planung: Was-wäre-wenn · Sensitivität (Tornado) · Risiko & Robustheit (mean-CVaR) · Erlös ↔ CO₂ (Pareto) ·
Erlöse & Technologie: Erlös-Stapel (Spot ↔ Regelenergie) · Plasma vs. Elektrolyse · CDR-Sensitivität · EEG-Jahresbudget ·
Prognose & Markt: Prognose-Güte · Prognoseband (CQR/ACI) · Markt-Kontext · Datenanalyse ·
Nachweis: Backtest · Speicher & MPC · Anlage: Anlagendaten (Import + Validierung)

## Lokal starten

```bash
# einmalig
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
createdb fld_os && psql -d fld_os -c "create extension vector"
export FLD_DATABASE_URL=postgresql+asyncpg://$USER@localhost:5432/fld_os PYTHONPATH=.:engine
.venv/bin/alembic upgrade head && .venv/bin/python -m fldos.seed
cd web && npm install

# täglich (2 Terminals)
./run-backend.sh            # API :8031
cd web && npm run dev       # UI  :5173  → http://localhost:5173
```

## Prüfen

```bash
FLD_WARMUP=0 FLD_DATABASE_URL=... .venv/bin/pytest     # Engine-Invarianten + API
cd web && npm run build                                 # Typecheck + Build
```

## API-Vertrag

`docs/openapi.json` ist der eingecheckte Vertrag der API (OpenAPI aus `app.openapi()`). Neu erzeugen,
sobald sich Routen, Parameter, Antwortmodelle (Pydantic) oder Fehlerantworten ändern — und den Diff
mit committen:

```bash
PYTHONPATH=.:engine .venv/bin/python scripts/export_openapi.py   # setzt FLD_DATABASE_URL=memory:// selbst
```

Der Abnahmetest `tests/abnahme/test_f08_openapi_vertrag.py` schlägt fehl, wenn die Datei veraltet ist
oder ein bisheriger Pfad fehlt.

## Konfiguration

| Variable | Zweck |
|---|---|
| `FLD_DATABASE_URL` | asyncpg-DSN |
| `FLD_DATA_DIR` | Datenverzeichnis (Default `./data`) |
| `FLD_TENANT_ID` | Mandant (Default `fld-energy`) |
| `FLD_REQUIRE_AUTH` / `FLD_JWT_SECRET` | Plattform-JWT (HS256), Default aus |
| `FLD_WARMUP` | Analysen beim Start vorrechnen (Default `1`) |

## Bekannte Grenzen

- Importierte Anlagendaten werden gespeichert und geprüft, wirken aber noch nicht auf die Optimierer.
- Parameter sind Modellwerte einer 1-MWel-Referenzanlage, bis FLD reale Anlagendaten liefert.
- `docker-compose.yml` ist noch nicht gebaut/getestet.
