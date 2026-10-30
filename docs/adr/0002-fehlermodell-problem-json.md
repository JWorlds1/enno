# 0002 — Fehlermodell: application/problem+json (RFC 9457)

Status: angenommen (2026-10-09, Lauf r-20261008-fld-os-autonom, Feature f04)

## Kontext

Fehlerantworten waren uneinheitlich: FastAPI lieferte `{"detail": …}` bzw. eine Fehlerliste bei 422,
die Auth-Middleware in `fldos/api.py` ein eigenes `{"detail": "unauthorized"}`, unbehandelte
Ausnahmen die Starlette-Standardantwort (Stand vor Commit `baf76be`). Das Frontend (`web/src/lib/api.ts`) hängt `detail` bei 422 direkt an die
Fehlermeldung, erwartet dort also einen String.

## Entscheidung

Jede Fehlerantwort ist `application/problem+json` mit `type`, `title`, `status`, `detail`.
`fldos/problem.py` stellt `problem()` und `install()` bereit; `fldos/api.py` installiert die Handler und
nutzt `problem()` auch für 401 und 503 (`/api/v1/ready`).

- `type` ist immer `about:blank`, `title` die HTTP-Reason-Phrase (RFC 9457 §4.2.1) – kein eigenes
  Typ-Vokabular, solange es keinen Konsumenten dafür gibt.
- 422: `detail` ist ein String `feld: meldung; …`, keine Fehlerliste. Damit bleibt `web/src/lib/api.ts`
  unverändert.
- 500: `detail` = „Interner Fehler“, der Traceback geht nur ins Log (`fldos.problem`). Der Handler setzt
  `X-Request-ID` selbst, weil `ServerErrorMiddleware` außerhalb von `fldos/request_id.py` antwortet.
- 503 bei `/ready` trägt ein festes `detail`, nie den Treiber-Fehlertext (könnte Host oder Zugangsdaten enthalten).

## Konsequenzen

- Clients lesen immer dasselbe Schema; `tests/abnahme/test_f04_fehlermodell.py` sichert es ab.
- Der Feldpfad bei 422 ist nur noch Text – maschinenlesbare Feldfehler gibt es nicht.
- `docs/openapi.json` beschreibt Fehlerantworten (422, 503) weiterhin als `HTTPValidationError` bzw.
  ohne Beschreibung; das Schema ist nicht an das Fehlermodell angeglichen (offener Punkt aus f08).
- `web/src/lib/api.ts` zeigt bei 4xx/5xx außer 422 nur den Status, nicht `detail`.
