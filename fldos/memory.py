"""Enno-Langzeitgedächtnis — pgvector über Bedrock-Titan-Embeddings (EU, souverän).

remember() schreibt Zusammenfassungen (z.B. Tages-Empfehlungen) mit Embedding; search() macht
Cosine-Ähnlichkeitssuche. Ohne AWS-Creds (lokal) degradiert es sauber: Embedding=None, search=[].
"""
from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentMemory
from .settings import EMBED_DIM

EMBED_MODEL = os.environ.get("FLD_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
REGION = os.environ.get("AWS_REGION", "eu-central-1")
# Kostenpflichtiger Bedrock-Aufruf nur mit ausdrücklichem Opt-in (wie FLD_LLM_PROVIDER bei Enno); Standard: aus
EMBED_PROVIDER = os.environ.get("FLD_EMBED_PROVIDER", "").lower()


def _embed_sync(text_in: str) -> list[float] | None:
    if EMBED_PROVIDER != "bedrock":
        return None  # ohne Opt-in kein Aufruf: Eintrag ohne Embedding, search() nimmt die jüngsten Einträge
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=REGION)
        resp = client.invoke_model(
            modelId=EMBED_MODEL,
            body=json.dumps({"inputText": text_in, "dimensions": EMBED_DIM, "normalize": True}),
        )
        return json.loads(resp["body"].read())["embedding"]
    except Exception:
        return None


async def embed(text_in: str) -> list[float] | None:
    return await asyncio.to_thread(_embed_sync, text_in)


async def remember(session: AsyncSession, kind: str, content: str, meta: dict | None = None, *, tenant: str) -> None:
    emb = await embed(content)
    session.add(AgentMemory(tenant_id=tenant, kind=kind, content=content, embedding=emb, meta=meta))
    await session.commit()


async def search(session: AsyncSession, query: str, k: int = 4, *, tenant: str) -> list[AgentMemory]:
    emb = await embed(query)
    if emb is not None:
        # Semantische Vektorsuche (sobald ein Embedding-Modell in Bedrock freigeschaltet ist).
        q = (
            select(AgentMemory)
            .where(AgentMemory.tenant_id == tenant, AgentMemory.embedding.isnot(None))
            .order_by(AgentMemory.embedding.cosine_distance(emb))
            .limit(k)
        )
    else:
        # Fallback ohne Embedding: jüngste Einträge (stabil, ohne externe Modelle). query ungenutzt.
        q = (
            select(AgentMemory)
            .where(AgentMemory.tenant_id == tenant)
            .order_by(AgentMemory.created_at.desc())
            .limit(k)
        )
    return list((await session.execute(q)).scalars())
