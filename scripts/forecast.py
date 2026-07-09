"""Monatsend-Umsatzprognose (Werktags-Blend).

Reine, testbare Funktion. Bläht früh im Monat die stabile Baseline (Ø der letzten
Vollmonate) ein und gewichtet mit fortschreitendem Monat die tatsächliche Lauf-Rate
stärker — so wird Einzelrechnungs-Rauschen am Monatsanfang gedämpft.

Formel:
    runrate  = MTD / bd_elapsed
    w        = min(1, bd_elapsed / K)
    blended  = w * runrate + (1 - w) * baseline_daily
    forecast = MTD + blended * bd_remaining
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class ForecastResult:
    mtd: float                 # Ist-Netto-Umsatz Monat bis heute
    forecast: float            # Punktprognose Monatsende
    target: float
    gap: float                 # target - forecast (positiv = unter Ziel)
    attainment_pct: float      # forecast / target
    bd_elapsed: int
    bd_remaining: int
    bd_total: int
    runrate_daily: float
    baseline_daily: float
    blended_daily: float
    weight: float              # w — Vertrauen in die Lauf-Rate (0..1)
    required_daily: float      # nötiger Tages-Netto für Restwerktage bis zum Ziel
    forecast_low: float        # Unsicherheitsband unten
    forecast_high: float       # Unsicherheitsband oben
    status: str                # "green" | "amber" | "red"

    def to_dict(self) -> dict:
        return asdict(self)


def forecast_month_end(
    mtd: float,
    bd_elapsed: int,
    bd_total: int,
    baseline_daily: float,
    target: float,
    K: int = 5,
    uncertainty_pct: float = 0.15,
    amber_threshold: float = 0.85,
) -> ForecastResult:
    mtd = float(mtd)
    baseline_daily = max(0.0, float(baseline_daily))
    bd_total = max(1, int(bd_total))
    bd_elapsed = max(0, min(int(bd_elapsed), bd_total))
    bd_remaining = bd_total - bd_elapsed

    if bd_elapsed > 0:
        runrate_daily = mtd / bd_elapsed
        weight = min(1.0, bd_elapsed / float(K)) if K > 0 else 1.0
        blended_daily = weight * runrate_daily + (1.0 - weight) * baseline_daily
    else:
        # Lauf am 1. / an einem Feiertag: rein auf Baseline stützen.
        runrate_daily = 0.0
        weight = 0.0
        blended_daily = baseline_daily

    forecast = mtd + blended_daily * bd_remaining

    gap = target - forecast
    attainment = forecast / target if target else 0.0
    required_daily = (target - mtd) / bd_remaining if bd_remaining > 0 else 0.0
    if required_daily < 0:
        required_daily = 0.0

    # Unsicherheitsband: nur der noch nicht realisierte Teil ist unsicher,
    # und je weniger Werktage verstrichen sind, desto breiter.
    projected_part = blended_daily * bd_remaining
    band = projected_part * uncertainty_pct * (1.0 - weight + 0.25)
    forecast_low = forecast - band
    forecast_high = forecast + band

    if attainment >= 1.0:
        status = "green"
    elif attainment >= amber_threshold:
        status = "amber"
    else:
        status = "red"

    return ForecastResult(
        mtd=round(mtd, 2),
        forecast=round(forecast, 2),
        target=round(float(target), 2),
        gap=round(gap, 2),
        attainment_pct=round(attainment, 4),
        bd_elapsed=bd_elapsed,
        bd_remaining=bd_remaining,
        bd_total=bd_total,
        runrate_daily=round(runrate_daily, 2),
        baseline_daily=round(baseline_daily, 2),
        blended_daily=round(blended_daily, 2),
        weight=round(weight, 4),
        required_daily=round(required_daily, 2),
        forecast_low=round(max(forecast_low, mtd), 2),
        forecast_high=round(forecast_high, 2),
        status=status,
    )
