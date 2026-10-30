#!/usr/bin/env bash
# FLD OS — Demo/Betrieb lokal starten: Daten auf heute ziehen (Tageskette), Backend + Oberfläche starten.
#
#   ./demo.sh                 Tageskette (~12 min: Daten, Prognose, Backtest, Empfehlung) und dann starten
#   ./demo.sh --ohne-update   sofort starten mit dem zuletzt gerechneten Stand
#
# Voraussetzung: Homebrew-Postgres läuft (brew services start postgresql@14), .venv + web/node_modules installiert.
# ENTSO-E-Token optional in .env (ENTSOE_TOKEN=…); ohne Token fehlt nur der Netzbetreiber-Vergleich.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
export PATH="/usr/local/opt/postgresql@14/bin:$PATH"
export PYTHONPATH=.:engine
export FLD_DATABASE_URL="${FLD_DATABASE_URL:-postgresql+asyncpg://$USER@localhost:5432/fld_os}"
# Logs nicht nach /tmp: macOS leert /tmp beim Neustart, dann ist die Ursache eines Fehlers weg
LOGS="$HOME/Library/Logs/fld-os"; mkdir -p "$LOGS"

pg_isready -q -h localhost || { echo "✗ Postgres antwortet nicht — brew services start postgresql@14"; exit 1; }
for port in 8031 5173; do
  if lsof -ti "tcp:$port" >/dev/null 2>&1; then
    echo "✗ Port $port ist belegt (läuft FLD OS schon?). Beenden mit: kill \$(lsof -ti tcp:$port)"; exit 1
  fi
done

if [ "${1:-}" != "--ohne-update" ]; then
  echo "▶ Tageskette: Daten bis morgen holen und neu rechnen …"
  # Fehler (kein Internet, Quelle down) ist kein Grund, nichts zu zeigen: warnen und mit dem letzten Stand starten
  # pipefail: der Status der Tageskette, nicht der von tee; im if-Zweig bricht set -e nicht ab
  if ! .venv/bin/python -m fldos.pipeline 2>&1 | tee "$LOGS/tageskette.log"; then
    echo "⚠ Tageskette nicht vollständig — FLD OS startet mit dem zuletzt gerechneten Stand. Log: $LOGS/tageskette.log"
  fi
fi

./run-backend.sh > "$LOGS/backend.log" 2>&1 & BACK=$!
(cd web && npm run --silent dev -- --host 127.0.0.1) > "$LOGS/web.log" 2>&1 & WEB=$!
trap 'kill $BACK $WEB 2>/dev/null' EXIT INT TERM

up=0
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8031/api/v1/health >/dev/null && curl -sf http://127.0.0.1:5173 >/dev/null && { up=1; break; }
  sleep 1
done
if [ "$up" != 1 ]; then
  echo "✗ FLD OS antwortet nach 60 s nicht. Logs: $LOGS/backend.log und $LOGS/web.log"; exit 1
fi
echo "✓ FLD OS läuft: http://localhost:5173/#/cockpit   (Tagesbericht: http://localhost:5173/fld-api/report)"
echo "  Die schweren Analysen rechnen ~1 min im Hintergrund vor. Beenden: Ctrl+C"
open "http://localhost:5173/#/cockpit" 2>/dev/null || true
wait
