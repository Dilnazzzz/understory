"""Aggregate occurrence points into H3 hex cells for privacy-safe mapping."""

from __future__ import annotations

import h3
import pandas as pd

H3_RESOLUTION = 7  # ~1.2 km² cells — location fuzzing by design


def aggregate_hexes(df: pd.DataFrame, resolution: int = H3_RESOLUTION) -> list[dict]:
    """
    Convert lat/lon points to H3 hex cells with counts.

    Never returns raw coordinates — only hex centroids.
    """
    if df.empty:
        return []

    hex_counts: dict[str, int] = {}

    for _, row in df.iterrows():
        cell = h3.latlng_to_cell(row["lat"], row["lon"], resolution)
        hex_counts[cell] = hex_counts.get(cell, 0) + 1

    hexes = []
    for cell_id, count in hex_counts.items():
        lat, lng = h3.cell_to_latlng(cell_id)
        hexes.append(
            {
                "h3": cell_id,
                "count": count,
                "lat": round(lat, 5),
                "lng": round(lng, 5),
            }
        )

    hexes.sort(key=lambda h: h["count"], reverse=True)
    return hexes
