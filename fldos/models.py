"""SQLAlchemy-Schema für den FLD-Tenant.

Gruppen (siehe Plan): Markt/Netz-Zeitreihen · Modell-Outputs · Config · Agent-Memory (pgvector) ·
Artefakte (hybrid: Blob im Volume, Metadaten hier). Jede Tabelle ist tenant_id-skopiert.
"""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .settings import EMBED_DIM


class Base(DeclarativeBase):
    pass


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)  # §9: kein Default-Mandant


class TimeMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Markt / Netz (Zeitreihen) ────────────────────────────────────────────────
class MarketPrice(Base, TenantMixin):
    __tablename__ = "market_prices"
    __table_args__ = (UniqueConstraint("tenant_id", "ts", "source", name="uq_market_prices"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price_eur_mwh: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class MarketFundamental(Base, TenantMixin):
    __tablename__ = "market_fundamentals"
    __table_args__ = (UniqueConstraint("tenant_id", "day", name="uq_market_fundamentals"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    ttf_gas_eur_mwh: Mapped[float | None] = mapped_column(Float)
    eua_co2_eur_t: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class GridTimeseries(Base, TenantMixin):
    """Last/Residual/Erzeugung/Wetter — Kernfelder als Spalten, Rest in extra."""
    __tablename__ = "grid_timeseries"
    __table_args__ = (UniqueConstraint("tenant_id", "ts", name="uq_grid_timeseries"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    load_mw: Mapped[float | None] = mapped_column(Float)
    residual_load_mw: Mapped[float | None] = mapped_column(Float)
    solar_mw: Mapped[float | None] = mapped_column(Float)
    wind_mw: Mapped[float | None] = mapped_column(Float)
    biomass_mw: Mapped[float | None] = mapped_column(Float)
    ee_share: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict | None] = mapped_column(JSON)


class EntsoeForecast(Base, TenantMixin):
    __tablename__ = "entsoe_forecasts"
    __table_args__ = (UniqueConstraint("tenant_id", "ts", name="uq_entsoe_forecasts"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    load_da: Mapped[float | None] = mapped_column(Float)
    solar_da: Mapped[float | None] = mapped_column(Float)
    wind_on_da: Mapped[float | None] = mapped_column(Float)
    wind_off_da: Mapped[float | None] = mapped_column(Float)


class RegelenergiePrice(Base, TenantMixin):
    __tablename__ = "regelenergie_prices"
    __table_args__ = (UniqueConstraint("tenant_id", "day", "product", name="uq_regelenergie"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    product: Mapped[str] = mapped_column(String(16))  # afrr | fcr
    price_eur_mw_h: Mapped[float] = mapped_column(Float)


# ── Modell-Outputs ───────────────────────────────────────────────────────────
class Run(Base, TenantMixin, TimeMixin):
    """Ein Lauf (täglich oder what-if) — Klammer über forecasts/dispatch/decisions."""
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_day: Mapped[date] = mapped_column(Date, index=True)
    algo: Mapped[str] = mapped_column(String(32), default="schedule")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    kpis: Mapped[dict | None] = mapped_column(JSON)


class Forecast(Base, TenantMixin):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actual: Mapped[float | None] = mapped_column(Float)
    pred_a: Mapped[float | None] = mapped_column(Float)
    pred_b: Mapped[float | None] = mapped_column(Float)
    p10: Mapped[float | None] = mapped_column(Float)
    p90: Mapped[float | None] = mapped_column(Float)


class Quantile(Base, TenantMixin):
    __tablename__ = "quantiles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    q: Mapped[dict] = mapped_column(JSON)  # {"q05":.., "q25":.., ...}


class Dispatch(Base, TenantMixin):
    __tablename__ = "dispatch"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    slot: Mapped[int] = mapped_column(Integer)  # 0..95
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # optional: slot ist der Index
    pred_price: Mapped[float | None] = mapped_column(Float)
    bhkw_mw: Mapped[float | None] = mapped_column(Float)
    electrolyser_mw: Mapped[float | None] = mapped_column(Float)
    pyro_mw: Mapped[float | None] = mapped_column(Float)
    reserve_up_mw: Mapped[float | None] = mapped_column(Float)    # aFRR+ und FCR vorgehalten (nur bei Strategie Reserve)
    reserve_down_mw: Mapped[float | None] = mapped_column(Float)  # aFRR− und FCR


class Decision(Base, TenantMixin, TimeMixin):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    strategy: Mapped[str] = mapped_column(String(48))
    scores: Mapped[dict | None] = mapped_column(JSON)
    guardrails: Mapped[dict | None] = mapped_column(JSON)
    rationale: Mapped[list | None] = mapped_column(JSON)


class BacktestResult(Base, TenantMixin):
    __tablename__ = "backtest_results"
    __table_args__ = (UniqueConstraint("tenant_id", "day", "algo", name="uq_backtest"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    algo: Mapped[str] = mapped_column(String(32), default="schedule")
    flat: Mapped[float | None] = mapped_column(Float)
    perfect: Mapped[float | None] = mapped_column(Float)
    forecast: Mapped[float | None] = mapped_column(Float)
    up_fc: Mapped[float | None] = mapped_column(Float)
    up_pf: Mapped[float | None] = mapped_column(Float)
    exp_fc: Mapped[float | None] = mapped_column(Float)  # Mehrerlös, den die Prognose vor der Auktion erwarten ließ
    ok: Mapped[bool | None] = mapped_column(Boolean)


class WhatifRun(Base, TenantMixin, TimeMixin):
    __tablename__ = "whatif_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


# ── Schattenbetrieb: gemessene Einspeisung der Anlage ─────────────────────────
class PlantMeasurement(Base, TenantMixin):
    __tablename__ = "plant_measurements"
    __table_args__ = (UniqueConstraint("tenant_id", "ts", name="uq_plant_measurements"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    p_mw: Mapped[float] = mapped_column(Float)


# ── Config ───────────────────────────────────────────────────────────────────
class PlantConfigRow(Base, TenantMixin):
    __tablename__ = "plant_config"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    params: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Agent-Memory (pgvector) ──────────────────────────────────────────────────
class AgentMemory(Base, TenantMixin, TimeMixin):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # report | decision | market | note
    content: Mapped[str] = mapped_column(String)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    meta: Mapped[dict | None] = mapped_column(JSON)


class ChatSession(Base, TenantMixin, TimeMixin):
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), default="enno")


class ChatMessage(Base, TenantMixin, TimeMixin):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool
    content: Mapped[str] = mapped_column(String)
    tool_calls: Mapped[dict | None] = mapped_column(JSON)


# ── Artefakte (hybrid) ───────────────────────────────────────────────────────
class Artifact(Base, TenantMixin, TimeMixin):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # report_pdf | eda_png | model_pkl
    path: Mapped[str] = mapped_column(String(512))  # relativ zu ARTIFACTS_DIR
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    meta: Mapped[dict | None] = mapped_column(JSON)
