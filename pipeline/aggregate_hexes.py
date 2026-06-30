"""Aggregate occurrence points into H3 hex cells for privacy-safe mapping."""

from __future__ import annotations

from datetime import datetime

import h3
import pandas as pd

H3_RESOLUTION = 7  # ~1.2 km² cells — location fuzzing by design

# Records this recent count toward a hex's "still active" signal.
RECENT_WINDOW_YEARS = 10

# How many example occurrence IDs to keep per hex for "view the evidence" links.
SAMPLE_IDS_PER_HEX = 3


def aggregate_hexes(df: pd.DataFrame, resolution: int = H3_RESOLUTION) -> list[dict]:
    """
    Convert lat/lon points to H3 hex cells with counts and provenance.

    Never returns raw coordinates — only hex centroids. Each hex carries the
    evidence behind it: how many records, how recent, how many distinct
    datasets, and a few GBIF occurrence IDs you can click through to verify.
    """
    if df.empty:
        return []

    recent_cutoff = datetime.now().year - RECENT_WINDOW_YEARS

    buckets: dict[str, dict] = {}

    for _, row in df.iterrows():
        cell = h3.latlng_to_cell(row["lat"], row["lon"], resolution)
        b = buckets.setdefault(
            cell,
            {"count": 0, "recentCount": 0, "years": [], "datasets": set(), "ids": []},
        )
        b["count"] += 1

        year = _safe_int(row.get("year"))
        if year is not None:
            b["years"].append(year)
            if year >= recent_cutoff:
                b["recentCount"] += 1

        dataset = row.get("datasetKey")
        if isinstance(dataset, str):
            b["datasets"].add(dataset)

        gid = row.get("gbifId")
        if gid is not None and len(b["ids"]) < SAMPLE_IDS_PER_HEX:
            b["ids"].append(int(gid))

    hexes = []
    for cell_id, b in buckets.items():
        lat, lng = h3.cell_to_latlng(cell_id)
        years = b["years"]
        hexes.append(
            {
                "h3": cell_id,
                "count": b["count"],
                "recentCount": b["recentCount"],
                "lastSeen": max(years) if years else None,
                "firstSeen": min(years) if years else None,
                "datasetCount": len(b["datasets"]),
                "sampleIds": b["ids"],
                "lat": round(lat, 5),
                "lng": round(lng, 5),
            }
        )

    hexes.sort(key=lambda h: h["count"], reverse=True)
    return hexes


def _safe_int(value) -> int | None:
    """Coerce a possibly-NaN/float year to int, or None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
