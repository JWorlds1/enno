"""fldos — thin API + DB-Fundament, das die Optimierungs-Engine mandantenfähig als FLD OS exponiert.

Die bestehenden flachen Compute-Module (backtest_forecast, whatif, decision_agent, …) bleiben
unangetastet und werden nur importiert. Dieses Paket ergänzt: DB-Persistenz (Postgres+pgvector),
FastAPI-Endpoints, pluggable Ingestion-Adapter und den Agenten Enno.
"""
