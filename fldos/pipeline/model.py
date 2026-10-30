"""Day-Ahead-Preisprognose — nur mit Wissen, das vor der Auktion (D-1, 12:00 Uhr) vorliegt.

Merkmale: Kalender in Marktzeit (Europe/Berlin), Preise bis D-1 (Lags), Wetterprognosen für Wind- und
Solarregionen (Open-Meteo; in der Vergangenheit die damals gültige Vorhersage). Keine Ist-Werte von Tag D.

Messung rollierend wie im Betrieb: je Monat nur mit der Vergangenheit trainieren, den Monat vorhersagen.
Kalibrierung: Bias-Korrektur aus den Fehlern der Vortage; Quantile P05–P95 aus den Fehlern der letzten
60 Tage je Tagesstunde (empirisch, monoton — können sich nicht kreuzen).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

TZ = "Europe/Berlin"
CAL = ["qhour", "hour", "dow", "month", "weekend", "sin_h", "cos_h"]
LAG = ["lag_1d", "lag_2d", "lag_7d", "roll7d"]
QS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
PARAMS = dict(n_estimators=500, learning_rate=0.05, num_leaves=63, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, min_child_samples=50, verbose=-1, random_state=7, n_jobs=4)


def frame(data_dir: Path, until_day=None) -> tuple[pd.DataFrame, list[str]]:
    """Viertelstunden-Raster mit Preis, Lags, Kalender (Berlin) und Wetterprognose. → (df, Wettermerkmale)

    `until_day`: Raster reicht bis Ende dieses Liefertags (Berlin), auch ohne Preise — vor der Auktion gibt es
    für morgen noch keine; die Lags (≥ 1 Tag) sind trotzdem bekannt."""
    h = pd.read_csv(data_dir / "history.csv", usecols=["utc", "da_price_eur_mwh"], parse_dates=["utc"])
    h = h.drop_duplicates("utc").set_index("utc").sort_index()
    end = h.index.max()
    if until_day is not None:
        day_end = pd.Timestamp(until_day, tz=TZ) + pd.Timedelta(days=1) - pd.Timedelta(minutes=15)
        end = max(end, day_end.tz_convert("UTC"))
    grid = pd.date_range(h.index.min(), end, freq="15min", tz="UTC")
    d = pd.DataFrame(index=grid)
    known = h["da_price_eur_mwh"].reindex(grid[grid <= h.index.max()]).ffill(limit=3)  # Lücken nur innerhalb der Historie
    d["price"] = known.reindex(grid)
    loc = d.index.tz_convert(TZ)
    d["day"] = loc.date  # Liefertag nach Marktzeit
    d["qhour"] = loc.hour * 4 + loc.minute // 15
    d["hour"] = loc.hour
    d["dow"] = loc.dayofweek
    d["month"] = loc.month
    d["weekend"] = (loc.dayofweek >= 5).astype(int)
    d["sin_h"] = np.sin(2 * np.pi * d["qhour"] / 96)
    d["cos_h"] = np.cos(2 * np.pi * d["qhour"] / 96)
    # Lags ≥ 1 Tag: am Vortag der Lieferung vollständig bekannt (Auktion D-1 lief an D-2).
    d["lag_1d"] = d["price"].shift(96)
    d["lag_2d"] = d["price"].shift(192)
    d["lag_7d"] = d["price"].shift(672)
    d["roll7d"] = d["price"].shift(96).rolling(672, min_periods=96).mean()
    w = pd.read_csv(data_dir / "wetter.csv", parse_dates=["utc"]).drop_duplicates("utc").set_index("utc").sort_index()
    w = w.reindex(w.index.union(grid)).interpolate(limit=4, limit_area="inside").reindex(grid)
    wind = [c for c in w if c.startswith("wind_")]
    sun = [c for c in w if c.startswith("sun_")]
    d["wind_mean"] = w[wind].mean(axis=1)
    d["wind_power_idx"] = (w[wind].clip(upper=45) ** 3).mean(axis=1) / 1e3  # Leistung ~ v³ bis Nennleistung
    d["sun_mean"] = w[sun].mean(axis=1)
    d["temp_mean"] = w[[c for c in w if c.startswith("temp_")]].mean(axis=1)
    for c in wind + sun:
        d[c] = w[c]
    wx = ["wind_mean", "wind_power_idx", "sun_mean", "temp_mean", *wind, *sun]
    return d, wx


def _fit(tr: pd.DataFrame, feats: list[str]) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(**PARAMS).fit(tr[feats], tr["price"])


@dataclass
class Walk:
    pred: pd.DataFrame  # utc-Index: actual, pred_A, pred_raw, pred_B (kalibriert), q05…q95
    metrics: dict


def walk_forward(d: pd.DataFrame, wx: list[str], months: int = 12, until_day=None) -> Walk:
    """Rollierend: je Monat mit allem davor trainieren, den Monat vorhersagen (nur Tage < until_day)."""
    ok = d.dropna(subset=["price", *LAG, *wx])
    if until_day is not None:
        ok = ok[ok["day"] < until_day]
    last = pd.Timestamp(max(ok["day"]))
    starts = [(last - pd.DateOffset(months=k)).normalize().replace(day=1) for k in range(months - 1, -1, -1)]
    parts = []
    for i, m0 in enumerate(starts):
        m1 = starts[i + 1] if i + 1 < len(starts) else last + pd.Timedelta(days=1)
        is_tr = ok["day"] < m0.date()
        is_te = (ok["day"] >= m0.date()) & (ok["day"] < m1.date())
        tr, te = ok[is_tr], ok[is_te]
        if te.empty:
            continue
        parts.append(pd.DataFrame({"day": te["day"], "hour": te["hour"], "actual": te["price"], "naive": te["lag_1d"],
                                   "pred_A": _fit(tr, CAL + LAG).predict(te[CAL + LAG]),
                                   "pred_raw": _fit(tr, CAL + LAG + wx).predict(te[CAL + LAG + wx])}, index=te.index))
    p = pd.concat(parts)
    y = p["actual"]
    cal = p["pred_raw"] + _bias(p)
    mae = {k: float((p[k] - y).abs().mean()) for k in ("naive", "pred_A", "pred_raw")}
    mae["calibrated"] = float((cal - y).abs().mean())
    use_bias = mae["calibrated"] < mae["pred_raw"]  # Kalibrierung nur, wenn sie messbar besser ist
    p["pred_B"] = cal if use_bias else p["pred_raw"]
    p = p.join(_quantiles(p))
    m = {"days": int(p["day"].nunique()), "from": str(p["day"].min()), "to": str(p["day"].max()),
         "mae": {k: round(v, 2) for k, v in mae.items()},
         "bias": {k: round(float((p[k] - y).mean()), 2) for k in ("pred_A", "pred_raw", "pred_B")},
         "bias_correction": "an" if use_bias else "aus (verschlechtert MAE)"}
    cov = p.dropna(subset=["q10", "q90"])
    m["coverage_p10_p90"] = round(float(((cov["actual"] >= cov["q10"]) & (cov["actual"] <= cov["q90"])).mean()), 3)
    return Walk(p, m)


def _bias(p: pd.DataFrame, window: int = 28) -> pd.Series:
    """Tagesweise: mittlerer Fehler (Ist − Prognose) der `window` Vortage. Kennt nie den eigenen Tag."""
    daily = (p["actual"] - p["pred_raw"]).groupby(p["day"]).mean()
    corr = daily.shift(1).rolling(window, min_periods=7).mean().fillna(0.0)
    return p["day"].map(corr)


def _quantiles(p: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Je Tag und Tagesstunde: empirische Quantile der Fehler der `window` Vortage, auf die Prognose addiert."""
    res = (p["actual"] - p["pred_B"]).rename("r").to_frame().assign(day=p["day"], hour=p["hour"])
    days = sorted(p["day"].unique())
    out = pd.DataFrame(index=p.index, columns=[f"q{int(q * 100):02d}" for q in QS], dtype=float)
    for i, dy in enumerate(days):
        past = res[res["day"].isin(days[max(0, i - window):i])]
        if past["day"].nunique() < 14:
            continue
        today = p["day"] == dy
        for hr, grp in past.groupby("hour"):
            rows = today & (p["hour"] == hr)
            out.loc[rows, :] = (p.loc[rows, "pred_B"].to_numpy()[:, None]
                                + np.quantile(grp["r"], QS)[None, :])
    return out


def predict_day(d: pd.DataFrame, wx: list[str], walk: Walk, day) -> pd.DataFrame:
    """Prognose für einen Liefertag: Training auf allem vor dem Tag, Bias + Quantile aus der Messung."""
    ok = d.dropna(subset=["price", *LAG, *wx])
    tr = ok[ok["day"] < day]
    te = d[d["day"] == day].dropna(subset=[*LAG, *wx])
    out = pd.DataFrame({"day": te["day"], "hour": te["hour"], "actual": te["price"],
                        "pred_A": _fit(tr, CAL + LAG).predict(te[CAL + LAG]),
                        "pred_raw": _fit(tr, CAL + LAG + wx).predict(te[CAL + LAG + wx])}, index=te.index)
    p = walk.pred
    bias = 0.0
    if walk.metrics["bias_correction"] == "an":
        daily = (p["actual"] - p["pred_raw"]).groupby(p["day"]).mean()
        bias = float(daily.tail(28).mean())
    out["pred_B"] = out["pred_raw"] + bias
    recent = p[p["day"].isin(sorted(p["day"].unique())[-60:])]
    for hr, grp in (recent["actual"] - recent["pred_B"]).groupby(recent["hour"]):
        rows = out["hour"] == hr
        qv = np.quantile(grp, QS)
        for j, q in enumerate(QS):
            out.loc[rows, f"q{int(q * 100):02d}"] = out.loc[rows, "pred_B"] + qv[j]
    return out
