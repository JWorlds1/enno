"""FastAPI — dünne Schicht, die die Optimierungs-Engine + DB als FLD-OS-API exponiert.

Alle Reads kommen aus der DB (vom täglichen Lauf befüllt); /whatif rechnet live über die Engine.
Mandant pro Anfrage aus dem Token (current_tenant); Speicher-Port je Mandant. Datenendpoints + Optimierer-Seam.
"""
from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import asdict, fields
from datetime import date, datetime
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import config

from . import analytics, eeg, enno, optimizers, repository, shadow
from .analytics import DEF_BAND_DAYS, DEF_MPC_DAYS, DEF_PLASMA_DAYS, DEF_STACK_DAYS
from .problem import ProblemDetails, install as install_problems, problem
from .request_id import RequestIdMiddleware
from .settings import DATABASE_URL, DATA_DIR, JWT_SECRET, REQUIRE_AUTH, TENANTS, WARMUP
from .storage import Repository, make_repository

FIGURES_DIR = DATA_DIR / "figures"
REPORTS_DIR = DATA_DIR / "reports"  # Tagesbericht je Mandant (enthält dessen Fahrplan) — Review M-11
HISTORY_PATH = DATA_DIR / "history.csv"

_heatmap_cache: dict = {"mtime": None, "data": None}

_memo_get = analytics.cached

_probe = make_repository(DATABASE_URL)  # nur für /ready (Speicher erreichbar?); verbindet erst beim ersten Zugriff
_repos: dict[str, Repository] = {}


def current_tenant(request: Request) -> str:
    """Mandant dieser Anfrage (Verfassung §9, kein Default-Scope).

    Mit Anmeldung entscheidet allein der Claim `tenant` im Token; fehlt er oder ist er nicht zugelassen → 403.
    Ohne Anmeldung (lokal, Demo) nur, wenn genau EIN Mandant konfiguriert ist."""
    if REQUIRE_AUTH:
        tenant = (getattr(request.state, "claims", None) or {}).get("tenant")
        if tenant not in TENANTS:
            raise HTTPException(403, "kein oder unbekannter Mandant im Token")
        return tenant
    if len(TENANTS) != 1:
        raise HTTPException(403, "mehrere Mandanten konfiguriert — Anmeldung erforderlich")
    return next(iter(TENANTS))


def get_repository(tenant: str = Depends(current_tenant)) -> Repository:
    """FastAPI-Dependency: der Speicher-Port, gebunden an den Mandanten der Anfrage."""
    # ponytail: ein Adapter je Mandant, nie geleert — Mandanten sind konfiguriert (TENANTS), nicht frei wählbar
    if tenant not in _repos:
        _repos[tenant] = make_repository(DATABASE_URL, tenant)
    return _repos[tenant]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Schwere Analysen im Hintergrund vorwärmen, damit die erste Ansicht nicht 30 s wartet.
    task = None
    if WARMUP:
        task = asyncio.create_task(asyncio.to_thread(_warmup))
    yield
    if task:
        task.cancel()


def _warmup() -> None:
    for name, fn, args in _WARM:
        try:
            _memo_get(name, fn, *args, **({} if name in _PLANT_FREE else {"plant": config.PLANT}))
        except (OSError, KeyError, ValueError, IndexError, StopIteration):
            pass  # best effort — der Endpoint meldet den Fehler beim Aufruf selbst


app = FastAPI(title="FLD OS API", version="0.1.0", lifespan=_lifespan)
install_problems(app)

_AUTH_EXEMPT = {"/api/v1/health", "/api/v1/ready"}  # /status zeigt Mandantendaten → braucht Token


def _claims(auth_header: str | None) -> dict | None:
    """Verifiziert den FLD-OS-Plattform-JWT (HS256) lokal; liefert die Claims oder None."""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    try:
        return jwt.decode(auth_header.split(" ", 1)[1], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _token_valid(auth_header: str | None) -> bool:
    return _claims(auth_header) is not None


@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    # flag-gated (Default AUS): schützt /fld-api tenant-scoped, ohne Monitoring zu brechen.
    if REQUIRE_AUTH and request.method != "OPTIONS" and request.url.path not in _AUTH_EXEMPT:
        claims = _claims(request.headers.get("authorization"))
        if claims is None:
            return problem(401, "unauthorized")
        request.state.claims = claims  # current_tenant liest daraus den Mandanten
    return await call_next(request)


app.add_middleware(RequestIdMiddleware)  # zuletzt hinzugefügt = äußerste Schicht: auch 401 trägt die ID


# ── Schemas ──────────────────────────────────────────────────────────────────
class DispatchSlot(BaseModel):
    slot: int
    ts: datetime | None = None
    pred_price: float | None = None
    bhkw_mw: float | None = None
    electrolyser_mw: float | None = None
    pyro_mw: float | None = None
    reserve_up_mw: float | None = None    # bei Strategie „Regelenergie vorhalten“: nach oben freigehaltene MW
    reserve_down_mw: float | None = None


class Recommendation(BaseModel):
    target_day: date
    algo: str
    kpis: dict | None = None
    created_at: datetime | None = None
    slots: list[DispatchSlot]


class ForecastPoint(BaseModel):
    ts: datetime
    actual: float | None = None
    pred_a: float | None = None
    pred_b: float | None = None
    p10: float | None = None
    p90: float | None = None


class BacktestPoint(BaseModel):
    day: date
    algo: str
    flat: float | None = None
    perfect: float | None = None
    forecast: float | None = None
    up_fc: float | None = None
    up_pf: float | None = None
    exp_fc: float | None = None  # vor der Auktion erwartet (Prognose) — Grundlage der EEG-Tagesauswahl
    ok: bool | None = None


class FundamentalPoint(BaseModel):
    day: date
    ttf_gas_eur_mwh: float | None = None
    eua_co2_eur_t: float | None = None


class RegelPoint(BaseModel):
    day: date
    product: str
    price_eur_mw_h: float


class DecisionOut(BaseModel):
    strategy: str
    label: str | None = None  # Klartext für die UI
    scores: dict | None = None
    guardrails: dict | None = None
    rationale: list | None = None
    summary: str | None = None  # derselbe Kernsatz, den Enno sagt (enno._why_lead)


class WhatifIn(BaseModel):
    gas: float = 70.0
    h2: float = 100.0
    co2: float = 79.0
    mode: str = "plasma"  # none | electro | plasma
    algo: str = "whatif"


class WhatifOut(BaseModel):
    net_eur: float
    flat_eur: float
    uplift_eur: float
    spot: float
    heat: float
    h2_eur: float
    carbon_eur: float
    h2_mwh: float
    carbon_t: float
    elcost: float
    gas_cost: float
    starts: int
    bhkw_h: float
    status: str
    bhkw: list[float]
    electro: list[float]
    pyro: list[float]
    # EEG (fldos/eeg.py): Netto inkl. Marktprämie + Flexibilitätszuschlag; None, wenn kein Marktwert ermittelbar
    marktwert_eur_mwh: float | None = None
    praemie_eur_mwh: float | None = None
    praemie_mwh: float | None = None
    eeg_premium_eur: float | None = None
    flex_eur: float | None = None
    net_eeg_eur: float | None = None


_mw_cache: dict = {}


def _marktwert(d: date) -> float | None:
    """Monatsmarktwert (Spot-Monatsmittel) für den Liefertag; neu gelesen, sobald history.csv sich ändert."""
    mtime = HISTORY_PATH.stat().st_mtime if HISTORY_PATH.exists() else None
    key = (d.year, d.month, mtime)
    if key not in _mw_cache:
        _mw_cache.clear()  # ponytail: nur der aktuelle Stand, ein Eintrag je Monat genügt
        _mw_cache[key] = eeg.monthly_market_value(HISTORY_PATH, d) if mtime else None
    return _mw_cache[key]


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok"}


READY_TIMEOUT_S = 3.0


@app.get("/api/v1/ready", responses={503: {"model": ProblemDetails, "description": "Speicher nicht erreichbar"}})
async def ready():
    """Bereitschaft: antwortet der Speicher? (/health prüft nur Lebendigkeit, ohne DB.) Mandantenlos."""
    repo = _probe
    try:
        await asyncio.wait_for(repo.ping(), READY_TIMEOUT_S)
    except Exception:  # auch TimeoutError; Ursache nicht nach außen (kann Host/Zugang enthalten)
        return problem(503, "Speicher nicht erreichbar")
    return {"status": "ready", "db": repo.kind}


class StatusOut(BaseModel):
    status: str
    db: str
    latest_target_day: date | None = None
    stale: bool
    memories: int


@app.get("/api/v1/status", response_model=StatusOut)
async def status(repo: Repository = Depends(get_repository)) -> StatusOut:
    """Betriebs-Status fürs Monitoring: DB erreichbar + Datenfrische (Fahrplan ≥ heute?)."""
    run = await repo.latest_run()
    target = run.target_day if run else None
    # frisch = Fahrplan für morgen (Marktzeit) liegt vor; ein Plan für heute heißt: Tageskette heute nicht gelaufen
    stale = target is None or target <= enno._today()
    return StatusOut(status="ok", db=repo.db_status, latest_target_day=target, stale=stale, memories=await repo.memory_count())


@app.get("/api/v1/recommendation", response_model=Recommendation)
async def recommendation(
    algo: str | None = Query(None), repo: Repository = Depends(get_repository)
) -> Recommendation:
    run = await repo.latest_run(algo=algo)
    if not run:
        raise HTTPException(404, "Noch kein Fahrplan — die Tageskette muss erst laufen.")
    rows = await repo.dispatch_for_run(run.id)
    return Recommendation(
        target_day=run.target_day,
        algo=run.algo,
        kpis=run.kpis,
        created_at=run.created_at,
        slots=[DispatchSlot.model_validate(r, from_attributes=True) for r in rows],
    )


@app.get("/api/v1/recommendation.csv", response_class=Response,
         responses={200: {"content": {"text/csv": {}}, "description": "Fahrplan je Viertelstunde (Semikolon, Dezimalkomma)"}})
async def recommendation_csv(repo: Repository = Depends(get_repository)) -> Response:
    """Fahrplan zum Weitergeben (Leitwarte, Direktvermarkter): Zeit in Marktzeit und UTC, Preis, BHKW, Elektrolyse,
    vorgehaltene Regelleistung nach oben/unten (0, wenn keine Reserve geplant ist)."""
    run = await repo.latest_run()
    if not run:
        raise HTTPException(404, "Noch kein Fahrplan — die Tageskette muss erst laufen.")
    from zoneinfo import ZoneInfo
    berlin = ZoneInfo("Europe/Berlin")
    de = lambda v: "" if v is None else f"{v:.3f}".replace(".", ",")  # noqa: E731 — Excel-DE liest das direkt
    lines = ["zeit_berlin;zeit_utc;preis_eur_mwh;bhkw_mw;elektrolyse_mw;reserve_hoch_mw;reserve_runter_mw"]
    for r in await repo.dispatch_for_run(run.id):
        ts = r.ts.replace(tzinfo=r.ts.tzinfo or ZoneInfo("UTC")) if r.ts else None
        lines.append(";".join([ts.astimezone(berlin).strftime("%Y-%m-%d %H:%M") if ts else str(r.slot),
                               ts.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%MZ") if ts else "",
                               de(r.pred_price), de(r.bhkw_mw), de(r.electrolyser_mw),
                               de(r.reserve_up_mw or 0.0), de(r.reserve_down_mw or 0.0)]))
    name = f"fahrplan_{run.target_day}.csv"
    return Response("\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/v1/decision", response_model=DecisionOut)
async def decision(repo: Repository = Depends(get_repository)) -> DecisionOut:
    run = await repo.latest_run()
    if not run:
        raise HTTPException(404, "Noch kein Fahrplan — die Tageskette muss erst laufen.")
    d = await repo.decision_for_run(run.id)
    if not d:
        raise HTTPException(404, "Zum jüngsten Fahrplan gibt es keine Entscheidung.")
    out = DecisionOut.model_validate(d, from_attributes=True)
    out.label = enno.STRATEGY_LABEL.get(d.strategy, d.strategy)
    out.summary = enno._why_lead(d.rationale or [], d.strategy, enno.day_word(run.target_day)) or None
    out.rationale = [enno._clean_reason(r) for r in d.rationale or []]  # lesbar wie bei Enno (Codes, €, Dezimalkomma)
    return out


@app.get("/api/v1/forecast", response_model=list[ForecastPoint])
async def forecast(repo: Repository = Depends(get_repository)) -> list[ForecastPoint]:
    run = await repo.latest_run()
    if not run:
        raise HTTPException(404, "Noch kein Fahrplan — die Tageskette muss erst laufen.")
    rows = await repo.forecasts_for_run(run.id)
    return [ForecastPoint.model_validate(r, from_attributes=True) for r in rows]


@app.get("/api/v1/backtest", response_model=list[BacktestPoint])
async def backtest(
    algo: str | None = Query(None), repo: Repository = Depends(get_repository)
) -> list[BacktestPoint]:
    rows = await repo.backtest(algo=algo)
    return [BacktestPoint.model_validate(r, from_attributes=True) for r in rows]


class ValueOut(BaseModel):
    days: int
    from_day: date
    to_day: date
    uplift_eur: float
    per_day_eur: float
    per_year_eur: float
    pct_vs_flat: float | None = None
    capture_pct: float | None = None


@app.get("/api/v1/value", response_model=ValueOut)
async def value(repo: Repository = Depends(get_repository)) -> dict:
    """Mehrwert aus dem Backtest: Fahrplan auf Prognose, Ist-Preise, gegen Dauerbetrieb (je MW, hochgerechnet aufs Jahr)."""
    v = analytics.value_summary(await repo.backtest())
    if v is None:
        raise HTTPException(404, "kein Backtest vorhanden")
    return v


class ModelOut(BaseModel):
    days: int
    from_day: str
    to_day: str
    mae_eur_mwh: float  # genutzte Prognose (kalibriert), 12 Monate rollierend
    mae_naive_eur_mwh: float
    bias_eur_mwh: float
    coverage_p10_p90: float


@app.get("/api/v1/model", response_model=ModelOut)
async def model_quality() -> dict:
    """Prognosegüte aus der letzten Tageskette (rollierende Messung, nicht ein einzelner Tag)."""
    import json
    p = DATA_DIR / "pipeline_status.json"
    if not p.exists():
        raise HTTPException(404, "Tageskette noch nicht gelaufen")
    m = json.loads(p.read_text())["model"]
    return {"days": m["days"], "from_day": m["from"], "to_day": m["to"], "mae_eur_mwh": m["mae"]["calibrated"],
            "mae_naive_eur_mwh": m["mae"]["naive"], "bias_eur_mwh": m["bias"]["pred_B"], "coverage_p10_p90": m["coverage_p10_p90"]}


@app.get("/api/v1/market", response_model=list[FundamentalPoint])
async def market(repo: Repository = Depends(get_repository)) -> list[FundamentalPoint]:
    rows = await repo.fundamentals()
    return [FundamentalPoint.model_validate(r, from_attributes=True) for r in rows]


@app.get("/api/v1/regelenergie", response_model=list[RegelPoint])
async def regelenergie(repo: Repository = Depends(get_repository)) -> list[RegelPoint]:
    rows = await repo.regelenergie()
    return [RegelPoint.model_validate(r, from_attributes=True) for r in rows]


@app.post("/api/v1/whatif", response_model=WhatifOut)
async def whatif_endpoint(
    body: WhatifIn, repo: Repository = Depends(get_repository)
) -> WhatifOut:
    prices = await repo.prices_latest()
    if not prices:
        raise HTTPException(404, "Keine Preisbasis — die Tageskette muss erst laufen.")
    try:
        plant = await _plant(repo)
        result = await asyncio.to_thread(
            optimizers.run_algo, body.algo, prices, gas=body.gas, h2=body.h2, co2=body.co2, mode=body.mode, plant=plant
        )
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    run = await repo.latest_run()
    mw = await asyncio.to_thread(_marktwert, run.target_day) if run else None
    if mw is not None:
        result = {**result, **eeg.day(result["bhkw"], prices, plant, mw), "net_eeg_eur": eeg.net_incl_eeg(result, prices, plant, mw)}
    await repo.save_whatif(body.model_dump(), result)
    return WhatifOut(**result)


class Figure(BaseModel):
    name: str
    title: str


@app.get("/api/v1/figures", response_model=list[Figure])
async def figures() -> list[Figure]:
    if not FIGURES_DIR.exists():
        return []
    return [Figure(name=p.name, title=p.stem.replace("_", " ")) for p in sorted(FIGURES_DIR.glob("*.png"))]


@app.get("/api/v1/figures/{name}")
async def figure(name: str) -> FileResponse:
    p = FIGURES_DIR / Path(name).name  # Traversal-Schutz: nur Dateiname
    if p.suffix != ".png" or not p.exists():
        raise HTTPException(404, "Grafik nicht gefunden.")
    return FileResponse(p, media_type="image/png")


class ChatTurn(BaseModel):
    role: str  # user | assistant
    content: str


class ChatIn(BaseModel):
    message: str
    history: list[ChatTurn] = []
    session_id: int | None = None
    page: str | None = None  # aktuelle Seite, damit Enno „diese Seite“ erklären kann


class ChatAction(BaseModel):
    label: str
    route: str


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[dict] = []
    actions: list[ChatAction] = []
    mode: str = "basis"
    session_id: int


@app.post("/api/v1/chat", response_model=ChatOut)
async def chat(body: ChatIn, repo: Repository = Depends(get_repository)) -> ChatOut:
    cs = await repo.get_or_create_chat_session(body.session_id)
    await repo.save_chat_message(cs.id, "user", body.message)
    result = await enno.enno_chat(repo, body.message, [t.model_dump() for t in body.history], body.page)
    await repo.save_chat_message(cs.id, "assistant", result["reply"], result.get("tool_calls"))
    return ChatOut(**result, session_id=cs.id)


@app.get("/api/v1/chat/{session_id}/history", response_model=list[ChatTurn])
async def chat_history(session_id: int, repo: Repository = Depends(get_repository)) -> list[ChatTurn]:
    msgs = await repo.chat_history(session_id)
    return [ChatTurn(role=m.role, content=m.content) for m in msgs]


@app.get("/api/v1/report")
async def report(tenant: str = Depends(current_tenant)) -> FileResponse:
    p = REPORTS_DIR / f"{Path(tenant).name}.html"
    if not p.exists():
        raise HTTPException(404, "Kein Tagesbericht vorhanden — die Tageskette muss erst laufen.")
    return FileResponse(p, media_type="text/html")


class HeatmapOut(BaseModel):
    weekdays: list[str]
    hours: list[int]
    matrix: list[list[float | None]]
    min: float
    max: float


def _compute_heatmap() -> dict:
    import pandas as pd
    df = pd.read_csv(HISTORY_PATH, usecols=["utc", "da_price_eur_mwh"], parse_dates=["utc"]).dropna(
        subset=["da_price_eur_mwh"])
    loc = df["utc"].dt.tz_convert("Europe/Berlin")  # Wochentag/Stunde in Marktzeit
    df["wd"] = loc.dt.weekday
    df["hr"] = loc.dt.hour
    piv = df.groupby(["wd", "hr"])["da_price_eur_mwh"].mean()
    matrix: list[list[float | None]] = []
    for wd in range(7):
        row: list[float | None] = []
        for hr in range(24):
            v = piv.get((wd, hr))
            row.append(round(float(v), 1) if v is not None and pd.notna(v) else None)
        matrix.append(row)
    vals = [v for r in matrix for v in r if v is not None]
    return {"weekdays": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"], "hours": list(range(24)),
            "matrix": matrix, "min": round(min(vals), 1) if vals else 0.0, "max": round(max(vals), 1) if vals else 0.0}


@app.get("/api/v1/price-heatmap", response_model=HeatmapOut)
async def price_heatmap() -> HeatmapOut:
    import asyncio
    if not HISTORY_PATH.exists():
        raise HTTPException(404, "keine Preishistorie")
    mtime = HISTORY_PATH.stat().st_mtime
    if _heatmap_cache["mtime"] != mtime or not _heatmap_cache["data"]:
        _heatmap_cache["data"] = await asyncio.to_thread(_compute_heatmap)
        _heatmap_cache["mtime"] = mtime
    return HeatmapOut(**_heatmap_cache["data"])


# ── CDR-Preis-Sensitivität (MA-Winkel: ab wann schlägt Plasma-Pyrolyse die Elektrolyse?) ──
_cdr_cache: dict = {"key": None, "data": None}


class CdrRow(BaseModel):
    co2: int
    plasma_net: float
    plasma_uplift: float
    plasma_carbon_t: float
    plasma_h2_mwh: float
    plasma_pyro: float
    electro_net: float


class CdrOut(BaseModel):
    rows: list[CdrRow]
    break_even_co2: int | None
    gas: float
    h2: float


def _compute_cdr(prices: list[float], gas: float, h2: float, plant: config.PlantConfig = config.PLANT) -> dict:
    import whatif
    rows = []
    for co2 in range(80, 251, 20):  # 80,100,…,240 €/t
        pl = whatif.solve_day(prices, gas_cost=gas, h2_value=h2, carbon_eur_t=co2, ptx_mode="plasma", plant=plant)
        el = whatif.solve_day(prices, gas_cost=gas, h2_value=h2, carbon_eur_t=co2, ptx_mode="electro", plant=plant)
        rows.append({
            "co2": co2, "plasma_net": round(pl["net_eur"], 1), "plasma_uplift": round(pl["uplift_eur"], 1),
            "plasma_carbon_t": round(pl["carbon_t"], 2), "plasma_h2_mwh": round(pl["h2_mwh"], 2),
            "plasma_pyro": round(sum(pl["pyro"]), 1), "electro_net": round(el["net_eur"], 1),
        })
    be = next((r["co2"] for r in rows if r["plasma_net"] >= r["electro_net"]), None)
    return {"rows": rows, "break_even_co2": be, "gas": gas, "h2": h2}


class EegBudgetOut(BaseModel):
    annual_hours: int
    daily_hours: float
    affordable_days: int
    total_days: int
    value_at_budget: float
    value_all: float
    pct_of_max: float
    cum_hours: list[int]
    cum_value: list[float]
    ranking: str = "prognose"  # Tage nach vorab erwartetem Mehrerlös gewählt; „nachträglich“ nur ohne exp_fc (alter Backtest)


@app.get("/api/v1/eeg-budget", response_model=EegBudgetOut)
async def eeg_budget(
    annual_hours: int = Query(876, ge=0, le=8784), daily_hours: float = Query(8.0, gt=0, le=24),
    repo: Repository = Depends(get_repository),
) -> EegBudgetOut:
    """Szenario § 39m EEG: die Marktprämie gilt nur für 10 % der Leistung (≈ 876 Volllaststunden je MW). Fährt die
    Anlage nur so viele Stunden — auf welchen Tagen? Rangfolge nach dem Mehrerlös, den die Prognose VOR der Auktion
    erwarten ließ (exp_fc, so wäre es im Betrieb entschieden worden); gezählt wird der tatsächlich erzielte (up_fc).
    Annahme: jeder Betriebstag verbraucht daily_hours Volllaststunden (= Gasbudget/Tag)."""
    bt = await repo.backtest()
    if not bt:
        raise HTTPException(404, "Kein Backtest vorhanden — die Tageskette muss erst laufen.")
    ranking = "prognose" if all(x.exp_fc is not None for x in bt) else "nachtraeglich"
    key = (lambda x: x.exp_fc) if ranking == "prognose" else (lambda x: x.up_fc or 0.0)
    ups = [x.up_fc or 0.0 for x in sorted(bt, key=key, reverse=True)]
    affordable = int(annual_hours / daily_hours) if daily_hours else 0
    ch = cv = 0.0
    cum_hours: list[int] = []
    cum_value: list[float] = []
    for u in ups:
        ch += daily_hours
        cv += u
        cum_hours.append(round(ch))
        cum_value.append(round(cv, 1))
    value_at_budget = round(sum(ups[:affordable]), 1)
    value_all = round(sum(ups), 1)
    pct = round(value_at_budget / value_all * 100, 1) if value_all else 0.0
    return EegBudgetOut(
        annual_hours=annual_hours, daily_hours=daily_hours, affordable_days=affordable,
        total_days=len(ups), value_at_budget=value_at_budget, value_all=value_all, pct_of_max=pct,
        cum_hours=cum_hours, cum_value=cum_value, ranking=ranking,
    )


@app.get("/api/v1/cdr-sensitivity", response_model=CdrOut)
async def cdr_sensitivity(
    gas: float = Query(70.0), h2: float = Query(100.0), repo: Repository = Depends(get_repository)
) -> CdrOut:
    import asyncio
    prices = await repo.prices_latest()
    if not prices:
        raise HTTPException(404, "keine Preisbasis")
    run = await repo.latest_run()
    plant = await _plant(repo)
    key = (run.id if run else 0, gas, h2, plant)
    if _cdr_cache["key"] != key or not _cdr_cache["data"]:
        _cdr_cache["data"] = await asyncio.to_thread(_compute_cdr, prices, gas, h2, plant)
        _cdr_cache["key"] = key
    return CdrOut(**_cdr_cache["data"])


# ── Analyse-Module (Engine-Anbindung) ────────────────────────────────────────
_WARM = (
    ("band", analytics.forecast_band, (DEF_BAND_DAYS,)), ("stack", analytics.revenue_stack, (DEF_STACK_DAYS,)),
    ("pareto", analytics.pareto, ()), ("plasma", analytics.plasma_compare, (DEF_PLASMA_DAYS,)),
    ("mpc", analytics.mpc_state, (DEF_MPC_DAYS,)), ("risk", analytics.risk, ()),
)


class FrontierPoint(BaseModel):
    lam: float
    expected: float
    cvar: float
    bhkw_h: float


class RiskOut(BaseModel):
    day: str
    scenarios: int
    alpha: float
    rp: float
    eev: float
    ws: float
    vss: float
    evpi: float
    frontier: list[FrontierPoint]


class ParetoPoint(BaseModel):
    co2_t: float
    profit: float


class ParetoOut(BaseModel):
    day: str
    gas_cost: float
    eua: float
    front: list[ParetoPoint]
    slope_eur_t: float | None
    cheaper_than_eua: bool


class StackRow(BaseModel):
    day: str
    spot_only: float
    coopt: float
    energy: float
    capacity: float
    uplift: float
    reserve_mw: float


class RevenueStackOut(BaseModel):
    afrr: float  # aFRR positiv ((EUR/MW)/h)
    afrr_neg: float | None = None
    fcr: float
    rows: list[StackRow]
    avg_uplift: float
    uplift_per_mw_year: float


class PlasmaRow(BaseModel):
    day: str
    power: float
    electro: float
    pyro: float
    gas_pyro_mwh: float
    h2_mwh: float
    carbon_t: float


class PlasmaOut(BaseModel):
    rows: list[PlasmaRow]
    avg: dict[str, float]
    uplift_electro: float
    uplift_pyro: float
    carbon_credit_eur_t: float


class BandPoint(BaseModel):
    ts: str
    actual: float
    raw_lo: float
    raw_hi: float
    aci_lo: float
    aci_hi: float
    aci_cov_24h: float


class ForecastBandOut(BaseModel):
    target: float
    calib_n: int
    test_n: int
    cqr_q: float
    coverage: dict[str, float]
    width: dict[str, float]
    series: list[BandPoint]


class MpcOut(BaseModel):
    horizon: int
    s_max: float
    days: list[str]
    base_eur: list[float]
    mpc_eur: list[float]
    total_base: float
    total_mpc: float
    uplift_per_mw_year: float
    level_base: list[float]
    level_mpc: list[float]


class SensitivityBar(BaseModel):
    param: str
    label: str
    base_value: float
    low_value: float
    high_value: float
    low_net: float
    high_net: float
    swing: float


class SensitivityOut(BaseModel):
    mode: str
    delta: float
    base_net: float
    bars: list[SensitivityBar]
    with_eeg: bool = False  # Netto inkl. Marktprämie + Flexzuschlag (eeg.net_incl_eeg), wie Was-wäre-wenn


async def _plant(repo: Repository) -> config.PlantConfig:
    """Die Anlage des Mandanten: Modellwerte, überschrieben mit importierten FLD-Werten."""
    return config.PLANT.with_overrides(await repo.get_plant_config())


# Analysen, die nicht von der Anlage abhängen (reine Prognose-/Marktauswertung)
_PLANT_FREE = {"band"}


async def _analysis(name: str, fn, *args, repo: Repository, key_extra=None, **extra) -> dict:
    kw = ({} if name in _PLANT_FREE else {"plant": await _plant(repo)}) | extra
    try:
        return await asyncio.to_thread(_memo_get, name, fn, *args, key_extra=key_extra, **kw)
    except FileNotFoundError as e:
        raise HTTPException(404, f"Datenbasis fehlt: {e.filename}")


@app.get("/api/v1/risk", response_model=RiskOut)
async def risk(repo: Repository = Depends(get_repository)) -> dict:
    """mean-CVaR-Effizienzfront + VSS/EVPI für den jüngsten Prognosetag."""
    return await _analysis("risk", analytics.risk, repo=repo)


@app.get("/api/v1/pareto", response_model=ParetoOut)
async def pareto(repo: Repository = Depends(get_repository)) -> dict:
    """Pareto-Front Erlös ↔ CO₂-Einsparung, Grenzvermeidungskosten vs. EUA."""
    return await _analysis("pareto", analytics.pareto, repo=repo)


@app.get("/api/v1/revenue-stack", response_model=RevenueStackOut)
async def revenue_stack(days: int = Query(DEF_STACK_DAYS, ge=1, le=30), repo: Repository = Depends(get_repository)) -> dict:
    """Erlös-Stapel je Tag: Energie (Spot/Wärme/PtX) + Regelenergie-Kapazität vs. Spot-only."""
    return await _analysis("stack", analytics.revenue_stack, days, repo=repo)


@app.get("/api/v1/plasma-compare", response_model=PlasmaOut)
async def plasma_compare(days: int = Query(DEF_PLASMA_DAYS, ge=1, le=40), repo: Repository = Depends(get_repository)) -> dict:
    """Nur Strom vs. Elektrolyse vs. Plasma-Pyrolyse auf Ist-Preisen."""
    return await _analysis("plasma", analytics.plasma_compare, days, repo=repo)


# ── Preisrechner + Splitter (Gas → Strom oder → H₂ + C je Viertelstunde) ─────────────────
class PriceRef(BaseModel):
    date: str
    source: str
    url: str
    comparable: bool
    note: str | None = None
    ref_eur_kg: float | None
    formula_eur_kg: float | None
    deviation_pct: float | None


class PriceCheck(BaseModel):
    status: str  # geprüft | nachjustiert | plausibel (grau unter grün) | unplausibel | nicht geprüft | Marktpreis (EUA)
    factor: float
    refs: list[PriceRef]


class PriceItem(BaseModel):
    eur_kg: float | None
    source: str
    formula: str
    inputs: dict[str, float | None]
    check: PriceCheck | None = None


class ValuePricesOut(BaseModel):
    as_of: str
    h2: PriceItem
    carbon: dict[str, PriceItem]


class SplitSlot(BaseModel):
    time: str
    price: float
    route: str
    sure: bool  # Prognoseband P10–P90 ganz auf einer Seite der Schwelle


class SplitterOut(BaseModel):
    target_day: date
    price_basis: str
    carbon: str
    h2_eur_kg: float
    c_eur_kg: float
    own_prices: bool
    threshold_eur_mwh: float
    ratio: dict[str, float]
    strom_slots: int
    switches: int
    unsure_slots: int
    margin_eur_mwh: float
    min_run_slots: int
    block_slots: int  # > 0: Ergebnis der Blockgebote (nach der Auktion), sonst Regel auf der Prognose
    blocks: list[str]
    revenue: dict[str, float]
    uplift_vs_best: float
    slots: list[SplitSlot]


_CARBON_PATHS = ("co2", "cdr", "black")


def _value_prices() -> dict:
    """Preisrechner auf dem jüngsten Tag von external_market.csv (Marktdaten, für alle Mandanten gleich)."""
    import pandas as pd
    import value_prices
    path = DATA_DIR / "external_market.csv"
    if not path.exists():
        raise HTTPException(404, "Marktdaten fehlen — die Tageskette muss erst laufen.")
    import price_check
    raw = pd.read_csv(path)
    ext = raw.dropna(subset=["ttf_eur_mwh", "eua_eur_t"])
    if ext.empty:
        raise HTTPException(404, "Keine Gas- und CO₂-Preise in den Marktdaten.")
    check = price_check.validate(raw)  # Formeln gegen öffentliche Referenzpunkte; nachjustierte Wege gehen ein
    out = value_prices.prices(ext.iloc[-1].to_dict(), factors=price_check.factors(check))
    out["h2"]["check"] = check["h2"]
    for k, item in out["carbon"].items():
        item["check"] = check[k]
    return out


@app.get("/api/v1/value-prices", response_model=ValuePricesOut)
async def value_prices_ep() -> dict:
    """Fairer Wert für H₂ (grauer H₂ aus Gas + CO₂) und Kohlenstoff (CO₂-Wert, Entnahme-Zertifikat, Industrieruß)."""
    return await asyncio.to_thread(_value_prices)


async def _splitter_inputs(carbon: str, h2: float | None, c: float | None, repo: Repository) -> dict:
    """Gemeinsam für Splitter und Splitter-Plan: Liefertag, Preisbasis wie der Fahrplan, H₂-/C-Wert, Anlage."""
    from zoneinfo import ZoneInfo
    if carbon not in _CARBON_PATHS:
        raise HTTPException(422, f"carbon muss eines von {', '.join(_CARBON_PATHS)} sein")
    run = await repo.latest_run()
    if not run:
        raise HTTPException(404, "Noch kein Fahrplan — die Tageskette muss erst laufen.")
    berlin, utc = ZoneInfo("Europe/Berlin"), ZoneInfo("UTC")
    rows = [f for f in await repo.forecasts_for_run(run.id)
            if f.ts and f.ts.replace(tzinfo=f.ts.tzinfo or utc).astimezone(berlin).date() == run.target_day]
    if not rows or any(f.pred_b is None for f in rows):
        raise HTTPException(404, f"Keine Preisprognose für {run.target_day}.")
    auction = all(f.actual is not None for f in rows)
    vp = await asyncio.to_thread(_value_prices) if h2 is None or c is None else None
    h2_used = h2 if h2 is not None else vp["h2"]["eur_kg"]
    c_used = c if c is not None else vp["carbon"][carbon]["eur_kg"]
    if h2_used is None or c_used is None:  # z. B. Industrieruß ohne Öldaten: keine Schätzung (Abbruchkriterium)
        raise HTTPException(422, "Für diese Verwertung fehlen Marktdaten — bitte eigenen Preis eingeben.")
    band = None if auction or any(f.p10 is None or f.p90 is None for f in rows) else ([f.p10 for f in rows], [f.p90 for f in rows])
    return {"day": run.target_day, "auction": auction, "band": band,
            "prices": [float(f.actual if auction else f.pred_b) for f in rows],
            "forecast": [float(f.pred_b) for f in rows],
            "times": [f.ts.replace(tzinfo=f.ts.tzinfo or utc).astimezone(berlin).strftime("%H:%M") for f in rows],
            "h2": h2_used, "c": c_used, "own": h2 is not None or c is not None, "plant": await _plant(repo)}


class CurveMonth(BaseModel):
    month: str
    ttf_eur_mwh: float | None
    brent_usd_bbl: float | None
    h2: float | None
    carbon: dict[str, float | None]
    threshold: dict[str, float | None]
    interpolated: list[str]


class ValueCurveOut(BaseModel):
    as_of: str
    eua_eur_t: float | None
    eurusd: float | None
    months: list[CurveMonth]


def _value_curve(plant: config.PlantConfig) -> dict:
    import pandas as pd
    import value_prices
    path = DATA_DIR / "forward_curve.csv"
    if not path.exists():
        raise HTTPException(404, "Terminkurve fehlt — die Tageskette muss erst laufen.")
    ext = pd.read_csv(DATA_DIR / "external_market.csv").dropna(subset=["eua_eur_t"])
    last = ext.iloc[-1].to_dict()
    rows = pd.read_csv(path).astype(object).where(lambda d: d.notna(), None).to_dict("records")
    return {"as_of": str(last["date"]), "eua_eur_t": value_prices._num(last.get("eua_eur_t")),
            "eurusd": value_prices._num(last.get("eurusd")), "months": value_prices.curve(rows, last.get("eua_eur_t"),
                                                                                          last.get("eurusd"), plant)}


@app.get("/api/v1/value-curve", response_model=ValueCurveOut)
async def value_curve(repo: Repository = Depends(get_repository)) -> dict:
    """Preiskurve der nächsten 12 Liefermonate: H₂-/Kohlenstoffwert und Splitter-Schwelle aus Terminpreisen (Gas, Öl);
    CO₂ und EUR/USD auf dem heutigen Wert. Lücken zwischen gelisteten Monaten linear, Ränder ohne Verlängerung."""
    return await asyncio.to_thread(_value_curve, await _plant(repo))


@app.get("/api/v1/splitter", response_model=SplitterOut)
async def splitter_ep(
    carbon: str = Query("co2", description="Kohlenstoff-Verwertung: co2 | cdr | black"),
    h2: float | None = Query(None, gt=0, description="eigener H₂-Preis €/kg statt Preisrechner"),
    c: float | None = Query(None, ge=0, description="eigener Kohlenstoffpreis €/kg statt Preisrechner"),
    repo: Repository = Depends(get_repository),
) -> dict:
    """Je Viertelstunde des Liefertags: Gas in Strom oder in H₂ + Kohlenstoff, was mehr bringt (FLD-Verhältnis
    aus den Anlagendaten). Preisbasis wie der Fahrplan: Prognose vor der Auktion, danach Auktionspreise.
    Auf der Prognose nur Umschalten mit Abstand ≥ Prognosefehler; BHKW-Läufe mindestens min_up_slots."""
    import splitter
    x = await _splitter_inputs(carbon, h2, c, repo)
    plant, band = x["plant"], x["band"]
    margin = 0.0 if x["auction"] else await asyncio.to_thread(_forecast_mae)  # Auktion: Preise bekannt
    block = max(4, plant.min_up_slots) if x["auction"] else None  # nach der Auktion: angenommene Blockgebote
    s = splitter.split_day(x["prices"], x["h2"], x["c"], plant, times=x["times"], margin=margin,
                           min_run=plant.min_up_slots, p10=band[0] if band else None, p90=band[1] if band else None,
                           block=block)
    return {"target_day": x["day"], "price_basis": "Auktion" if x["auction"] else "Prognose", "carbon": carbon,
            "h2_eur_kg": x["h2"], "c_eur_kg": x["c"], "own_prices": x["own"], "threshold_eur_mwh": s["threshold"],
            "ratio": {"el_kwh": plant.split_el_kwh, "h2_kg": plant.split_h2_kg, "c_kg": plant.split_c_kg,
                      "plasma_kwh": plant.split_plasma_kwh},
            "strom_slots": s["strom_slots"], "switches": s["switches"], "unsure_slots": s["unsure_slots"],
            "margin_eur_mwh": margin, "min_run_slots": plant.min_up_slots, "block_slots": block or 0,
            "blocks": s["blocks"],
            "revenue": s["revenue"], "uplift_vs_best": s["uplift_vs_best"],
            "slots": [{"time": t, "price": p, "route": r, "sure": ok}
                      for t, p, r, ok in zip(x["times"], x["prices"], s["route"], s["sure"])]}


@app.get("/api/v1/splitter-bids.csv", response_class=Response,
         responses={200: {"content": {"text/csv": {}}, "description": "Blockgebote je Stunde (Semikolon, Dezimalkomma)"}})
async def splitter_bids(
    carbon: str = Query("co2"), h2: float | None = Query(None, gt=0), c: float | None = Query(None, ge=0),
    repo: Repository = Depends(get_repository),
) -> Response:
    """Gebotsvorschlag für die Day-Ahead-Auktion (Direktvermarkter): je Stunde die BHKW-Leistung mit der Schwelle als
    Mindestpreis. Die Börse nimmt einen Block nur, wenn sein Preis darüber liegt — dann Strom, sonst Plasma."""
    import splitter
    x = await _splitter_inputs(carbon, h2, c, repo)
    de = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731 — Excel-DE
    lines = ["liefertag;von;bis;menge_mw;mindestpreis_eur_mwh;prognose_eur_mwh;voraussichtlich_angenommen"]
    for b in splitter.bids(x["forecast"], x["h2"], x["c"], x["plant"], times=x["times"], block=max(4, x["plant"].min_up_slots)):
        lines.append(";".join([str(x["day"]), b["from"], b["to"], de(b["mw"]), de(b["limit_eur_mwh"]),
                               de(b["forecast_eur_mwh"]), "ja" if b["expected"] else "nein"]))
    return Response("\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="gebote_{x["day"]}_{carbon}.csv"'})


class SplitterPlanOut(BaseModel):
    target_day: date
    price_basis: str
    status: str
    times: list[str]
    bhkw_mw: list[float]
    plasma_gas_mw: list[float]
    storage_mwh: list[float]
    revenue: dict[str, float]
    uplift_eur: float
    plasma_gas_mwh: float
    h2_kg: float
    c_kg: float
    starts: int
    bhkw_h: float


@app.get("/api/v1/splitter-plan", response_model=SplitterPlanOut)
async def splitter_plan(
    carbon: str = Query("co2"), h2: float | None = Query(None, gt=0), c: float | None = Query(None, ge=0),
    repo: Repository = Depends(get_repository),
) -> dict:
    """Splitter im Optimierer für den Liefertag: Gasspeicher, festes Tagesgas, Mindestlast, Starts, Mindestlauf-
    und -stillstandszeit, Wärme-Mindestlauf. Vergleich: dieselbe Anlage nur mit Strom (beide optimal)."""
    import splitter_milp
    x = await _splitter_inputs(carbon, h2, c, repo)
    r = await asyncio.to_thread(splitter_milp.solve, x["prices"], x["h2"], x["c"], x["plant"])
    if r["status"] != "Optimal":
        raise HTTPException(422, f"Mit diesen Anlagendaten ist kein Plan möglich (Optimierer: {r['status']}).")
    return {"target_day": x["day"], "price_basis": "Auktion" if x["auction"] else "Prognose", "times": x["times"],
            **{k: r[k] for k in ("status", "bhkw_mw", "plasma_gas_mw", "storage_mwh", "revenue", "uplift_eur",
                                 "plasma_gas_mwh", "h2_kg", "c_kg", "starts", "bhkw_h")}}


class MonthRow(BaseModel):
    month: str
    bhkw_pct: float
    uplift_eur: float


class SplitterYearOut(BaseModel):
    carbon: str
    days: int
    skipped: int
    from_: str = Field(alias="from")
    to: str
    margin_eur_mwh: float
    min_run_h: float
    per_year: dict[str, float]
    uplift_vs_best_pct: float
    capture_pct: float
    switches_per_year: float
    switches_per_day: float
    bhkw_share_pct: float
    bhkw_runs_per_year: float
    avg_run_h: float
    short_runs_per_year: float
    correct_pct: float
    unsure_pct: float
    bids: dict
    hourly_bhkw_pct: list[float]
    monthly: list[MonthRow]
    milp: dict


@app.get("/api/v1/splitter-year", response_model=SplitterYearOut, response_model_by_alias=True)
async def splitter_year(
    carbon: str = Query("co2"), milp_days: int = Query(14, ge=0, le=60), repo: Repository = Depends(get_repository),
) -> dict:
    """Nachrechnung über alle Tage mit Prognose (~12 Monate): Umschaltungen, BHKW-Zeiten, Erlös — Plan auf der
    damaligen Prognose mit Sicherheitsabstand, abgerechnet auf Ist; dazu die Optimierer-Variante für die letzten Tage."""
    if carbon not in _CARBON_PATHS:
        raise HTTPException(422, f"carbon muss eines von {', '.join(_CARBON_PATHS)} sein")
    margin = await asyncio.to_thread(_forecast_mae)
    return await _analysis("splitter_year", analytics.splitter_year, carbon, milp_days, repo=repo, margin=margin)


class ProofDay(BaseModel):
    day: str
    status: str
    issued: str | None
    basis: str | None
    h2_eur_kg: float | None = None
    c_eur_kg: float | None = None
    threshold_eur_mwh: float | None = None
    revenue: dict[str, float] | None = None
    plus_vs_best_eur: float | None = None
    capture_pct: float | None = None
    switches: int | None = None
    strom_slots: int | None = None
    correct_pct: float | None = None


class ProofSummary(BaseModel):
    settled_days: int
    missing_days: int
    pending_days: int
    late_days: int
    streak_days: int
    forecast_days: int
    plus_vs_best_eur: float
    capture_pct: float
    last_settled: str | None


class SplitterProofOut(BaseModel):
    carbon: str
    days: list[ProofDay]
    summary: ProofSummary


@app.get("/api/v1/splitter-proof", response_model=SplitterProofOut)
async def splitter_proof(
    carbon: str = Query("co2"), days: int = Query(60, ge=1, le=366), repo: Repository = Depends(get_repository),
) -> dict:
    """Tagesnachweis: je Liefertag der zuerst ausgegebene Plan (aus der Datenbank, so wie er damals rausging),
    abgerechnet auf die echten Day-Ahead-Preise. Lücken (kein Lauf) bleiben sichtbar."""
    import pandas as pd
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    if carbon not in _CARBON_PATHS:
        raise HTTPException(422, f"carbon muss eines von {', '.join(_CARBON_PATHS)} sein")
    berlin, utc = ZoneInfo("Europe/Berlin"), ZoneInfo("UTC")
    mae_now = await asyncio.to_thread(_forecast_mae)
    runs = []
    for run in await repo.runs_since(date.today() - timedelta(days=days)):
        rows = [f for f in await repo.forecasts_for_run(run.id)
                if f.ts and f.ts.replace(tzinfo=f.ts.tzinfo or utc).astimezone(berlin).date() == run.target_day]
        if not rows or any(f.pred_b is None for f in rows):
            continue
        auction = all(f.actual is not None for f in rows)  # wie /splitter: nach der Auktion zählt der echte Preis
        mae = (run.kpis or {}).get("forecast_mae_eur_mwh")
        runs.append({"day": run.target_day, "issued": run.created_at.replace(tzinfo=run.created_at.tzinfo or utc),
                     "basis": "Auktion" if auction else "Prognose", "mae": float(mae) if mae is not None else mae_now,
                     "ts": [f.ts.replace(tzinfo=f.ts.tzinfo or utc) for f in rows],
                     "pred": [float(f.actual if auction else f.pred_b) for f in rows],
                     "p10": [f.p10 for f in rows], "p90": [f.p90 for f in rows]})
    if not runs:
        raise HTTPException(404, "Noch kein ausgegebener Plan — die Tageskette muss erst laufen.")
    prices = await asyncio.to_thread(_prices_utc) if HISTORY_PATH.exists() else pd.Series(dtype=float)
    return await asyncio.to_thread(analytics.splitter_proof, runs, prices, carbon, await _plant(repo))


def _forecast_mae() -> float:
    """Mittlerer Prognosefehler des Lernmodells (rollierend gemessen, pipeline_status.json) = Sicherheitsabstand."""
    import json
    p = DATA_DIR / "pipeline_status.json"
    try:
        return float(json.loads(p.read_text())["model"]["mae"]["calibrated"])
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return 0.0  # ohne Messung kein erfundener Abstand


@app.get("/api/v1/forecast-band", response_model=ForecastBandOut)
async def forecast_band(days: int = Query(DEF_BAND_DAYS, ge=1, le=21), repo: Repository = Depends(get_repository)) -> dict:
    """Prognoseband roh / CQR / ACI mit realisierter Abdeckung."""
    return await _analysis("band", analytics.forecast_band, days, repo=repo)


@app.get("/api/v1/mpc", response_model=MpcOut)
async def mpc_state(days: int = Query(DEF_MPC_DAYS, ge=2, le=30), repo: Repository = Depends(get_repository)) -> dict:
    """Rolling-Horizon-MPC vs. tagesisoliert: Erlös und Speicherzustand über Tage."""
    return await _analysis("mpc", analytics.mpc_state, days, repo=repo)


@app.get("/api/v1/sensitivity", response_model=SensitivityOut)
async def sensitivity(
    gas: float = Query(70.0, ge=0), h2: float = Query(100.0, ge=0), co2: float = Query(79.0, ge=0),
    mode: str = Query("plasma", pattern="^(none|electro|plasma)$"),
    repo: Repository = Depends(get_repository),
) -> dict:
    """Tornado: Netto-Tageserlös bei ±30 % je Annahme (Gas, H₂, CO₂)."""
    prices = await repo.prices_latest()
    if not prices:
        raise HTTPException(404, "keine Preisbasis")
    run = await repo.latest_run()
    mw = await asyncio.to_thread(_marktwert, run.target_day) if run else None  # Netto inkl. EEG wie Was-wäre-wenn
    return await _analysis("sens", analytics.sensitivity, prices, gas, h2, co2, mode,
                           repo=repo, key_extra=run.id if run else 0, marktwert=mw)


# ── Schattenbetrieb: Empfehlung vs. gefahrene Anlage ─────────────────────────
class MeasurementsIn(BaseModel):
    csv: str  # Zeilen `zeit;leistung` (kW; Kopfzeile mit „MW“ → MW), Zeit ISO oder Marktzeit Berlin


class MeasurementsOut(BaseModel):
    rows: int
    from_ts: datetime | None = None
    to_ts: datetime | None = None


class ShadowDay(BaseModel):
    day: str
    energy_rec_mwh: float
    energy_meas_mwh: float
    revenue_rec_eur: float
    revenue_meas_eur: float
    price_rec_eur_mwh: float
    price_meas_eur_mwh: float
    extra_same_energy_eur: float


class ShadowSummary(BaseModel):
    days: int
    extra_same_energy_eur: float
    per_day_eur: float | None = None


class ShadowOut(BaseModel):
    days: list[ShadowDay]
    summary: ShadowSummary
    measurements: int


@app.post("/api/v1/measurements", response_model=MeasurementsOut)
async def upload_measurements(body: MeasurementsIn, repo: Repository = Depends(get_repository)) -> MeasurementsOut:
    """Gemessene Einspeisung der Anlage importieren (idempotent je Viertelstunde)."""
    rows = await asyncio.to_thread(shadow.parse_csv, body.csv)
    if not rows:
        raise HTTPException(422, "keine Zeile „zeit;leistung“ erkannt")
    await repo.upsert_measurements(rows)
    return MeasurementsOut(rows=len(rows), from_ts=rows[0]["ts"], to_ts=rows[-1]["ts"])


def _prices_utc() -> "pd.Series":
    import pandas as pd
    h = pd.read_csv(HISTORY_PATH, usecols=["utc", "da_price_eur_mwh"], parse_dates=["utc"]).dropna()
    return h.drop_duplicates("utc").set_index("utc")["da_price_eur_mwh"]


@app.get("/api/v1/shadow", response_model=ShadowOut)
async def shadow_compare(repo: Repository = Depends(get_repository)) -> dict:
    """Je Liefertag mit Empfehlung und ≥ 90 % Messwerten: Erlös empfohlen vs. gefahren, fair bei gleicher Energie."""
    import pandas as pd
    from datetime import timedelta
    runs = await repo.runs_since(date.today() - timedelta(days=180))
    latest = {r.target_day: r for r in runs}  # je Tag der jüngste Lauf (runs_since: älteste zuerst)
    plans = {}
    for day, run in latest.items():
        rows = [r for r in await repo.dispatch_for_run(run.id) if r.ts is not None]
        if rows:
            idx = pd.DatetimeIndex([pd.Timestamp(r.ts).tz_convert("UTC") if pd.Timestamp(r.ts).tzinfo else pd.Timestamp(r.ts, tz="UTC") for r in rows])
            plans[day] = pd.Series([r.bhkw_mw or 0.0 for r in rows], index=idx)
    if not plans:
        return {"days": [], "summary": {"days": 0, "extra_same_energy_eur": 0.0}, "measurements": 0}
    start = min(p.index.min() for p in plans.values())
    end = max(p.index.max() for p in plans.values()) + pd.Timedelta(minutes=15)
    meas = await repo.measurements(start.to_pydatetime(), end.to_pydatetime())
    measured = pd.Series([m.p_mw for m in meas], index=pd.DatetimeIndex([pd.Timestamp(m.ts).tz_convert("UTC") for m in meas]), dtype=float)
    prices = await asyncio.to_thread(_prices_utc) if HISTORY_PATH.exists() else pd.Series(dtype=float)
    return {**shadow.evaluate(plans, measured, prices), "measurements": len(meas)}


# ── Anlagendaten (Import/Kalibrierung) ───────────────────────────────────────
_PLANT_FIELDS = {f.name: f.type for f in fields(config.PlantConfig)}
_FIXED = {"dt_h", "slots_per_day"}                       # Zeitraster der Engine, kein Anlagenwert
_FRACTION = {"eta_el", "min_load", "eta_ptx", "eta_pyro_h2", "eeg_share"}  # 0 < x ≤ 1
_POSITIVE = {"p_bhkw_mw", "full_hours_per_day", "storage_hours", "split_el_kwh"}  # > 0 (Divisor/Kapazität)
_SLOTS = {"min_up_slots", "min_down_slots", "heat_min_runtime_slots"}  # ganze Viertelstunden ≤ 96


class PlantDiff(BaseModel):
    default: float
    plant: float


class PlantConfigOut(BaseModel):
    defaults: dict[str, float]
    override: dict[str, float]
    diff: dict[str, PlantDiff]
    applied_to_optimizer: bool
    fixed: list[str]


class PlantConfigIn(BaseModel):
    model_config = {"extra": "forbid"}
    params: dict[str, float]


def _plant_problems(params: dict[str, float]) -> list[str]:
    """Fachliche Prüfung importierter Werte — Meldungen in Klartext für die UI."""
    unknown = sorted(set(params) - set(_PLANT_FIELDS))
    if unknown:
        return [f"unbekannte Parameter: {', '.join(unknown)}"]
    if bad := sorted(k for k, v in params.items() if not math.isfinite(v)):
        return [f"keine gültige Zahl: {', '.join(bad)}"]  # NaN/Infinity: int(v) bricht sonst mit 500 ab
    out = []
    if fixed := sorted(set(params) & _FIXED):
        out.append(f"nicht änderbar (Zeitraster): {', '.join(fixed)}")
    if neg := sorted(k for k, v in params.items() if v < 0):
        out.append(f"negative Werte nicht zulässig: {', '.join(neg)}")
    if frac := sorted(k for k, v in params.items() if k in _FRACTION and not 0 < v <= 1):
        out.append(f"muss zwischen 0 und 1 liegen: {', '.join(frac)}")
    if zero := sorted(k for k, v in params.items() if k in _POSITIVE and v <= 0):
        out.append(f"muss größer als 0 sein: {', '.join(zero)}")
    if slots := sorted(k for k, v in params.items() if k in _SLOTS and (v != int(v) or v > 96)):
        out.append(f"ganze Zahl von 0 bis 96 (Viertelstunden): {', '.join(slots)}")
    if params.get("full_hours_per_day", 0) > 24:
        out.append("full_hours_per_day: höchstens 24 Volllaststunden pro Tag")
    return out


@app.get("/api/v1/plant-config", response_model=PlantConfigOut)
async def plant_config(repo: Repository = Depends(get_repository)) -> dict:
    """Modell-Defaults, importierte Anlagenwerte und Abweichungen."""
    defaults = asdict(config.PLANT)
    override = await repo.get_plant_config() or {}
    diff = {k: {"default": defaults[k], "plant": v} for k, v in override.items()
            if k in defaults and v != defaults[k]}
    return {"defaults": defaults, "override": override, "diff": diff, "applied_to_optimizer": True,
            "fixed": sorted(_FIXED)}


@app.put("/api/v1/plant-config", response_model=PlantConfigOut)
async def set_plant_config(body: PlantConfigIn, repo: Repository = Depends(get_repository)) -> dict:
    if problems := _plant_problems(body.params):
        raise HTTPException(422, "; ".join(problems))
    plant = config.PLANT.with_overrides(body.params)
    prices = await repo.prices_latest()
    if prices:  # Probelauf mit dem strengsten Modell (Fahrplan: Min-up/down, Wärme-Mindestlauf, Gasbudget)
        trial = await asyncio.to_thread(optimizers.run_algo, "schedule", prices, plant=plant)
        if trial["status"] != "Optimal":
            raise HTTPException(422, f"Mit diesen Werten ist kein Fahrplan möglich (Optimierer: {trial['status']}). "
                                     "Bitte Gasbudget, Speicher und Mindestlaufzeiten prüfen.")
    await repo.set_plant_config(body.params)
    return await plant_config(repo)
