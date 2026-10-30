"""FLD-Firmendaten-Adapter — die Naht für reale Anlagentelemetrie.

Heute ein bewusster Stub: liefert einen definierten `not_connected`-Zustand, bis FLDs reale
Anlagendaten (Leistung, Speicherstand, Gaskosten, Wärme-/H₂-Werte, Intraday-Telemetrie)
angebunden sind. Sobald der Zugang steht, wird nur diese `ingest()` implementiert — Pipeline,
API und Agent bleiben unverändert.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .base import IngestResult, register


class FldPlantAdapter:
    name = "fld_plant"

    async def ingest(self, session: AsyncSession) -> IngestResult:  # noqa: ARG002
        return IngestResult(
            source=self.name,
            rows=0,
            status="not_connected",
            detail="reale FLD-Anlagentelemetrie noch nicht angebunden (Naht bereit)",
        )


register(FldPlantAdapter())
