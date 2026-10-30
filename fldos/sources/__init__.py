"""Ingestion-Adapter — pluggable Naht zwischen Rohquellen und DB.

Markt-Adapter (SMARD/ENTSO-E/DWD/regelleistung) schreiben Open-Data in die DB; der
`FldPlantAdapter` ist der typisierte Stub, an dem reale FLD-Anlagentelemetrie später einrastet —
ohne Pipeline/API/Agent zu ändern.
"""
from . import company  # noqa: F401  (registriert FldPlantAdapter)
from .base import IngestResult, SourceAdapter, register, registry

__all__ = ["IngestResult", "SourceAdapter", "register", "registry"]
