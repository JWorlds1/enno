"""Gemeinsamer Abnahme-Client: FLD OS ohne Postgres (FLD_DATABASE_URL=memory://), ASGI im Prozess."""
import asyncio
import os

os.environ["FLD_DATABASE_URL"] = "memory://"
os.environ["FLD_WARMUP"] = "0"

import httpx  # noqa: E402

from fldos.api import app  # noqa: E402


def call(method: str, url: str, **kw) -> httpx.Response:
    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://abnahme") as c:
            return await c.request(method, url, **kw)
    return asyncio.run(go())


def assert_problem(r: httpx.Response, status: int | tuple[int, ...]) -> dict:
    """RFC 9457: application/problem+json mit type, title, status, detail; status == HTTP-Status."""
    ok = status if isinstance(status, tuple) else (status,)
    assert r.status_code in ok, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json"), r.headers["content-type"]
    body = r.json()
    for k in ("type", "title", "status", "detail"):
        assert k in body, (k, body)
    assert body["status"] == r.status_code
    return body
