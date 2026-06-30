"""Derive foraging season from occurrence date distributions."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def _week_of_year(d: date) -> int:
    """Return ISO week number (1-52)."""
    return d.isocalendar()[1]


def _is_valid_date(d) -> bool:
    """Check if value is a usable date (not None/NaT)."""
    if d is None:
        return False
    if isinstance(d, float) and pd.isna(d):
        return False
    if pd.isna(d):
        return False
    return True


def derive_season(
    dates: list,
    today: date | None = None,
) -> dict:
    """
    Build season metadata from a list of occurrence dates.

    Returns activeWeeks, peakWeeks, inSeasonNow, and a 52-bin histogram.
    """
    today = today or date.today()

    valid_dates = [d for d in dates if _is_valid_date(d)]
    if not valid_dates:
        return {
            "activeWeeks": [],
            "peakWeeks": [],
            "inSeasonNow": False,
            "histogram": [0] * 52,
            "recordCount": 0,
        }

    # Normalize to date objects
    normalized = [
        d.date() if isinstance(d, datetime) else d
        for d in valid_dates
    ]

    histogram = [0] * 52
    for d in normalized:
        week = _week_of_year(d)
        if 1 <= week <= 52:
            histogram[week - 1] += 1

    peak_count = max(histogram) if histogram else 0
    if peak_count == 0:
        return {
            "activeWeeks": [],
            "peakWeeks": [],
            "inSeasonNow": False,
            "histogram": histogram,
            "recordCount": len(normalized),
        }

    # Active: weeks with >= 5% of peak count (minimum 1)
    threshold = max(1, int(peak_count * 0.05))
    active_weeks = [
        w + 1 for w, count in enumerate(histogram) if count >= threshold
    ]

    # Peak: top 20% of non-zero weeks by count
    nonzero = [(w + 1, c) for w, c in enumerate(histogram) if c > 0]
    nonzero.sort(key=lambda x: x[1], reverse=True)
    n_peak = max(1, int(len(nonzero) * 0.2))
    peak_weeks = sorted(w for w, _ in nonzero[:n_peak])

    current_week = _week_of_year(today)
    # Check current week ±1 for season status
    nearby = {current_week - 1, current_week, current_week + 1}
    # Handle week 1 / 52 wrap
    if current_week == 1:
        nearby.add(52)
    if current_week == 52:
        nearby.add(1)

    in_season_now = bool(set(active_weeks) & nearby)

    return {
        "activeWeeks": active_weeks,
        "peakWeeks": peak_weeks,
        "inSeasonNow": in_season_now,
        "histogram": histogram,
        "recordCount": len(normalized),
    }
