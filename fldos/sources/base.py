"""SourceAdapter-Protocol + Registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class IngestResult:
    source: str
    rows: int
    status: str  # ok | not_connected | error
    detail: str = ""


@runtime_checkable
class SourceAdapter(Protocol):
    name: str

    async def ingest(self, session: AsyncSession) -> IngestResult: ...


_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter: SourceAdapter) -> SourceAdapter:
    _REGISTRY[adapter.name] = adapter
    return adapter


def registry() -> dict[str, SourceAdapter]:
    return dict(_REGISTRY)
