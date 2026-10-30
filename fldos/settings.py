"""Laufzeit-Settings (env-getrieben) — einziger Ort mit Infra-Kopplung.

Nichts hier ist an einen konkreten Host gebunden: DATABASE_URL/Ports kommen aus der
Umgebung, damit lokal und im Container dieselbe Code-Basis läuft.
"""
import os
from pathlib import Path

# asyncpg-DSN. Lokal default gegen die pgvector-Docker aus docker-compose (Port 5436).
DATABASE_URL: str = os.environ.get(
    "FLD_DATABASE_URL",
    "postgresql+asyncpg://fld:fld@localhost:5436/fld_energy",
)

# Mandant dieses Deployments (Seed, Warm-up, Betrieb ohne Anmeldung). Jede Zeile ist tenant_id-skopiert.
TENANT_ID: str = os.environ.get("FLD_TENANT_ID", "fld-energy")
# Zugelassene Mandanten der API (Komma-Liste). Mit Anmeldung wählt der Token-Claim `tenant` daraus.
TENANTS: frozenset[str] = frozenset(
    t.strip() for t in os.environ.get("FLD_TENANTS", TENANT_ID).split(",") if t.strip()
)

# Embedding-Dimension für agent_memory (pgvector). Lokale/EU-Embeddings, Default = bge-m3/e5-large.
# ponytail: die eine Zahl, die je Modell variiert, parametrisiert — kein Config-Framework.
EMBED_DIM: int = int(os.environ.get("FLD_EMBED_DIM", "1024"))

# Große Artefakte (Report-PDF, EDA-PNG, Modelle) liegen im Dateisystem/Volume, nur Pfad in der DB.
ARTIFACTS_DIR: Path = Path(
    os.environ.get("FLD_ARTIFACTS_DIR", str(Path(__file__).resolve().parent.parent / "artifacts"))
)

# Auth (flag-gated, Default AUS): wenn AN, wird der FLD-OS-Plattform-JWT (HS256) lokal verifiziert.
REQUIRE_AUTH: bool = os.environ.get("FLD_REQUIRE_AUTH", "0") == "1"
JWT_SECRET: str = os.environ.get("FLD_JWT_SECRET", "")

# Marktdaten, Prognosen, Abbildungen — außerhalb des Codes (gitignored), gleiche Variable wie engine/config.py.
DATA_DIR: Path = Path(os.environ.get("FLD_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))

# Schwere Analysen beim Start im Hintergrund vorrechnen (Tests/CLI: FLD_WARMUP=0).
WARMUP: bool = os.environ.get("FLD_WARMUP", "1") == "1"
