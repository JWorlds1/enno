"""Fehlermodell nach RFC 9457: jede Fehlerantwort ist application/problem+json mit type, title, status, detail."""
from __future__ import annotations

import http
import logging

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("fldos.problem")


class ProblemDetails(BaseModel):
    """Schema der Fehlerantwort (siehe `problem()`), nur für die OpenAPI-Beschreibung."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str


def problem(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """type bleibt `about:blank` (RFC 9457 §4.2.1): kein eigenes Typ-Vokabular, title = HTTP-Reason-Phrase."""
    return JSONResponse({"type": "about:blank", "title": http.HTTPStatus(status).phrase, "status": status,
                         "detail": detail}, status_code=status, media_type="application/problem+json",
                        headers=headers)


def _de_msg(e: dict) -> str:
    """Pydantic-Meldung auf Deutsch — sie erscheint so in der Oberfläche (Review N-03). Unbekanntes bleibt im Original."""
    ctx, t = e.get("ctx") or {}, e.get("type", "")
    de = {"missing": "fehlt", "float_parsing": "keine gültige Zahl", "float_type": "keine gültige Zahl",
          "int_parsing": "keine ganze Zahl", "int_type": "keine ganze Zahl", "int_from_float": "keine ganze Zahl",
          "finite_number": "keine endliche Zahl", "string_type": "kein Text", "bool_parsing": "kein Ja/Nein-Wert",
          "dict_type": "erwartet ein Objekt", "list_type": "erwartet eine Liste", "json_invalid": "ungültiges JSON",
          "string_pattern_mismatch": "ungültiger Wert", "literal_error": "ungültiger Wert", "enum": "ungültiger Wert",
          "greater_than": f"muss größer als {ctx.get('gt')} sein", "greater_than_equal": f"mindestens {ctx.get('ge')}",
          "less_than": f"muss kleiner als {ctx.get('lt')} sein", "less_than_equal": f"höchstens {ctx.get('le')}"}
    return de.get(t, e.get("msg", "ungültig"))


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:  # auch unbekannte Route (404)
        if not is_body_allowed_for_status_code(exc.status_code):  # 204/304: kein Body (RFC 9110 §15.3.5/§15.4.5)
            return Response(status_code=exc.status_code, headers=exc.headers)
        return problem(exc.status_code, str(exc.detail), exc.headers)  # Allow (405), künftig WWW-Authenticate/Retry-After

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # detail bleibt ein String (Frontend zeigt ihn an); Feldpfad ohne das Präfix body/query
        msgs = [f"{'.'.join(str(p) for p in e['loc'][1:]) or e['loc'][0]}: {_de_msg(e)}" for e in exc.errors()]
        return problem(422, "; ".join(msgs))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unbehandelte Ausnahme bei %s %s", request.method, request.url.path, exc_info=exc)
        # ServerErrorMiddleware sitzt außerhalb der RequestIdMiddleware: die ID hier selbst setzen
        return problem(500, "Interner Fehler", {"x-request-id": request.state.request_id})  # kein Stacktrace nach außen


    def _openapi() -> dict:
        if not app.openapi_schema:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            comps = schema.setdefault("components", {}).setdefault("schemas", {})
            comps["ProblemDetails"] = ProblemDetails.model_json_schema()
            for path in schema["paths"].values():
                for op in path.values():
                    for code, resp in op["responses"].items():
                        if code == "422":  # FastAPIs HTTPValidationError wird nie gesendet (siehe _validation)
                            resp["content"] = {"application/json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}}
                        if code[0] in "45" and "content" in resp:
                            resp["content"] = {"application/problem+json": v for v in resp["content"].values()}
            comps.pop("HTTPValidationError", None)
            comps.pop("ValidationError", None)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = _openapi
