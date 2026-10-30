"""Repository-Roundtrip gegen die lokale DB: save_run → lesen → aufräumen."""
import asyncio
from datetime import date

from sqlalchemy import delete

from fldos import models as M
from fldos import repository as repo
from fldos.db import SessionLocal, engine
from fldos.settings import TENANT_ID


def test_save_and_read_run_roundtrip():
    asyncio.run(_roundtrip())


async def _roundtrip() -> None:
    try:
        async with SessionLocal() as s:
            run = await repo.save_run(
                s,
                target_day=date(2099, 1, 1),  # Marker, kollidiert nicht mit echten Läufen
                algo="pytest",
                kpis={"expected_revenue_eur": 42.0},
                dispatch_rows=[
                    {"slot": 0, "ts": None, "pred_price": 50.0, "bhkw_mw": 1.0, "electrolyser_mw": 0.0, "pyro_mw": None},
                    {"slot": 1, "ts": None, "pred_price": 60.0, "bhkw_mw": 0.5, "electrolyser_mw": 0.1, "pyro_mw": None},
                ],
                tenant=TENANT_ID,
            )
            got = await repo.latest_run(s, algo="pytest", tenant=TENANT_ID)
            assert got is not None and got.id == run.id
            assert got.kpis["expected_revenue_eur"] == 42.0
            rows = await repo.dispatch_for_run(s, run.id, tenant=TENANT_ID)
            assert len(rows) == 2 and rows[0].pred_price == 50.0
            # cleanup (cascade löscht dispatch)
            await s.execute(delete(M.Run).where(M.Run.id == run.id))
            await s.commit()
    finally:
        await engine.dispose()
