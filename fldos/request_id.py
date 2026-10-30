"""X-Request-ID: Middleware (reines ASGI, damit auch Fehlerantworten die ID tragen) + Request-Logzeile mit ID."""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

HEADER = "x-request-id"
_VALID = re.compile(r"[A-Za-z0-9._-]{1,128}")  # Vertrauensgrenze: keine Zeilenumbrüche/Steuerzeichen in Header und Log

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("fldos.request")

_make_record = logging.getLogRecordFactory()


def _record_with_id(*a, **kw) -> logging.LogRecord:
    rec = _make_record(*a, **kw)
    rec.request_id = request_id_var.get()  # für Formatter mit %(request_id)s — jede Logzeile im Request
    return rec


logging.setLogRecordFactory(_record_with_id)

if not log.handlers:  # uvicorn konfiguriert nur seine eigenen Logger; ohne Handler gäbe es keine Zeile
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        sent = next((v.decode("latin-1") for k, v in scope["headers"] if k == HEADER.encode()), "")
        rid = sent if _VALID.fullmatch(sent) else uuid.uuid4().hex
        request_id_var.set(rid)  # je Request eigener Task, kein Reset nötig; bleibt für Exception-Handler außerhalb sichtbar
        scope.setdefault("state", {})["request_id"] = rid
        status, t0 = 500, time.perf_counter()

        async def send_with_id(msg):
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
                msg["headers"] = [*msg.get("headers", []), (HEADER.encode(), rid.encode())]
            await send(msg)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # Pfad ist url-dekodiert: %0A/%0D würden sonst Logzeilen fälschen, "=" ein falsches
            # request_id=-Feld einschleusen (Review H1)
            path = scope["path"].encode("unicode_escape").decode("ascii").replace("=", "\\x3d")
            log.info("%s %s -> %s %.1fms request_id=%s", scope["method"], path, status,
                     (time.perf_counter() - t0) * 1000, rid)
