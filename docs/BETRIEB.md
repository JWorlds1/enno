# FLD OS im Betrieb

Wie FLD OS täglich rechnet, woher die Daten kommen, wie der Fahrplan zu Leitwarte oder Direktvermarkter gelangt —
und was für einen echten Kundenbetrieb noch fehlt.

## Starten

```bash
./demo.sh                 # Daten auf heute ziehen (~12 min), dann Backend :8031 + Oberfläche :5173
./demo.sh --ohne-update   # sofort starten mit dem zuletzt gerechneten Stand
```

Voraussetzungen: Homebrew-Postgres 14 + pgvector (`brew services start postgresql@14`), `.venv` mit
`pip install -e '.[dev,pipeline]'`, `web/node_modules` (`cd web && npm ci`). ENTSO-E-Token optional in `.env`. In `.env` außerdem `FLD_DATABASE_URL=postgresql+asyncpg://<user>@localhost:5432/fld_os` — sonst nimmt die Tageskette den Docker-Standard (Port 5436) und bricht beim Schreiben in die DB ab.

## Die Tageskette (`python -m fldos.pipeline`)

| Schritt | Was | Quelle / Methode |
|---|---|---|
| Preise + Erzeugung | Day-Ahead DE-LU je ¼ h inkl. morgen (ab ~12:45), Last, Wind, Solar | Energy-Charts, Lücken aus SMARD |
| Wetterprognosen | Wind 100 m (5 Windregionen), Einstrahlung + Temperatur (4 Solarregionen) | Open-Meteo; Vergangenheit = Vorhersage vom Vortag (Previous-Runs-API, ab 2024), Zukunft = jüngster Lauf |
| Netzbetreiber-Prognosen | Last (A65), Wind/Solar (A69) | ENTSO-E (nur Vergleich: Wind/Solar erscheinen erst nach der Auktion) |
| Gas + CO₂ | TTF Front-Month, EUA-Primärauktion | Yahoo, EEX |
| Regelenergie | aFRR pos/neg mengengewichtet (pay-as-bid), FCR Abrechnungspreis | regelleistung.net, inkrementell (~35 s/Tag) |
| Prognose | LightGBM, nur Wissen vor der Auktion; rollierend gemessen (12 Monate), Bias-Korrektur, Quantile | `fldos/pipeline/model.py` |
| Backtest | Plan am Vortag auf Prognose, Abrechnung zu Ist-Preisen, gegen Dauerbetrieb | `fldos/pipeline/plan.py` |
| Empfehlung | Liefertag morgen (Marktzeit Berlin), Gebotsplan immer auf der Prognose; nach der Auktion zu Ist-Preisen bewertet | dito |
| Entscheidung | Spot vs. Spot + Regelenergie (Co-Optimierung auf der Prognose, vor den Auktionen); bei Reserve enthält der Fahrplan die freizuhaltenden MW | dito |
| Anlage | Werte der Anlagendaten-Seite des Mandanten (sonst Modellanlage) — stehen in `pipeline_status.json` | `plant_config` |
| Tagesbericht | `data/reports/<mandant>.html` (Cockpit → „Report öffnen“, nur für den eigenen Mandanten) | `fldos/pipeline/report.py` |
| Datenbank | Ergebnisse des Mandanten, Historie der Empfehlungen bleibt | `fldos/seed.py` |

`data/pipeline_status.json` hält fest, was wann mit welchem Datenstand gerechnet wurde (inkl. Prognosefehler).
Weiche Schritte (ENTSO-E, Gas/CO₂, Regelenergie) dürfen ausfallen — dann wird mit dem letzten Stand gerechnet
und der Fehler steht im Status.

## Täglich automatisch

Zwei Läufe: **09:30** (Plan auf Prognose — für ein Gebot vor der Auktion um 12:00) und **13:30** (Plan auf den
Auktionspreisen). Auf dem Mac per launchd, Uhrzeit in der Zeitzone des Rechners (Vorlage: Rechner auf deutscher Zeit):

```bash
cp deploy/launchd/de.fld-os.tageskette.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.fld-os.tageskette.plist
tail -f ~/Library/Logs/fld-os/tageskette.log
```

Auf einem Server: derselbe Befehl als Cron-Job oder Kubernetes-CronJob (`TZ=Europe/Berlin`, `30 9,13 * * *`).

## Alarm, wenn der Plan fehlt

Zwei Wege (`fldos/alarm.py`):

- **Die Tageskette meldet sich selbst**, sobald ein Pflichtschritt scheitert (Netz, Preise, Wetter, Merkmale, Prognose):
  sofort, mit Schritt und Fehler.
- **Der Wächter** sieht alle 15 min nach: Steht ab **11:30** (Auktion 12:00) kein Plan für morgen, oder ist ein
  Datenschritt (ENTSO-E, Gas/CO₂/Öl, Terminkurve, Regelenergie) ausgefallen, meldet er es. Er fängt auch den Lauf, der nie
  startete (Rechner aus oder im Schlaf). Dieselbe Meldung kommt höchstens einmal am Tag. Ist der Rechner aus, meldet niemand:
  das löst erst ein Server.

Gemeldet wird immer ins Log `~/Library/Logs/fld-os/alarm.log` und als Mac-Hinweis, per Telegram nur, wenn ein Bot
eingerichtet ist, und nur an einen **privaten** Chat (Gruppen-IDs, also negative IDs, werden verweigert):

1. In Telegram @BotFather → `/newbot` → Token kopieren. Dem neuen Bot einmal `/start` schreiben.
2. Eigene Chat-ID: `https://api.telegram.org/bot<TOKEN>/getUpdates` → `message.chat.id` (positive Zahl).
3. In `~/fld-os/.env`: `TELEGRAM_BOT_TOKEN=…` und `TELEGRAM_CHAT_ID=…` (die Datei ist nicht im Repo).

```bash
cp deploy/launchd/de.fld-os.waechter.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.fld-os.waechter.plist
tail -f ~/Library/Logs/fld-os/alarm.log
```

## Schnittstellen nach außen

| Weg | Wofür |
|---|---|
| `GET /api/v1/recommendation.csv` (Fahrplan → „Herunterladen“) | Fahrplan je ¼ h, Marktzeit + UTC, Semikolon/Dezimalkomma — für Leitwarte/Direktvermarkter |
| `GET /api/v1/report` | Tagesbericht als HTML (druck- und mailbar) |
| `GET /api/v1/recommendation`, `/decision`, `/value` | JSON für eigene Systeme; Vertrag: `docs/openapi.json` |
| `PUT /api/v1/plant-config` | echte Anlagenwerte (geprüft, inkl. Probelauf) |
| `POST /api/v1/measurements`, `GET /api/v1/shadow` | Messdaten der Anlage (CSV `zeit;leistung_kw`) → Schattenbetrieb: Empfehlung vs. gefahren |

## Mandanten

Jede Zeile in der Datenbank gehört einem Mandanten. Mit `FLD_REQUIRE_AUTH=1` bestimmt allein der Claim `tenant`
im Plattform-Token (HS256, `FLD_JWT_SECRET`) den Mandanten; zugelassen sind die in `FLD_TENANTS` (Komma-Liste).
Ohne Anmeldung (lokal/Demo) genau ein Mandant: `FLD_TENANT_ID`.

## Was für den Kundenbetrieb noch fehlt

1. **Echte Anlagendaten** je Kunde (Leistung, Wirkungsgrade, Gasspeicher, Wärmebedarf) — heute Modell-Anlage 1 MWel.
2. **Messdaten der Anlage** (Zähler/Leitwarte) für den Schattenbetrieb: Empfehlung vs. tatsächlicher Betrieb.
3. **Anbindung an den Direktvermarkter** (CSV/Mail heute; API je nach Partner).
4. **Hosting** (EU-Cloud), Login (SSO), Backups; Alarm läuft auf dem Mac (s. o.), auf dem Server als eigener Job.
5. **Vertraglich**: AVV, Haftungsrahmen (Empfehlung, Mensch gibt frei), Preismodell.
6. **Modell**: Wärmebedarf als Zeitreihe, Intraday-Nachsteuerung, Abrufenergie und Gebotsrisiko bei Regelenergie.

## Prüfen ohne den Betrieb zu stören

`~/.claude/bin/checks-run` (Definition: `.checksrc`) baut die eigene Test-DB `fld_os_test` aus dem letzten Stand der
Tageskette auf und prüft dort — die Betriebs-DB `fld_os` (echte Anlagenwerte, Messdaten) fasst sie nie an;
`tests/conftest.py` bricht ab, falls doch einmal `fld_os` eingestellt ist. Nur ein Lauf zur Zeit (Sperre).
