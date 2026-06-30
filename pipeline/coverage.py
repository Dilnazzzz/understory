"""Coverage grid: how much data backs each part of a region — gaps included.

A coverage map is the honest counterpart to the occurrence map. It bins every
species' observations into a coarse grid and reports, per cell, how many records
and how many distinct species we actually have there. Empty cells are kept (not
dropped) so the gaps are visible — "we have little data here" is itself
information a forager should see.
"""

from __future__ import annotations

COVERAGE_STEP = 0.1


def _frange(start: float, stop: float, step: float) -> list[float]:
    vals, v = [], start
    while v <= stop + 1e-9:
        vals.append(round(v, 5))
        v += step
    return vals


def compute_coverage(
    species_results: list[dict], bbox: list[float], step: float = COVERAGE_STEP
) -> dict:
    """Bin all species' hexes into a coarse density grid over the bbox."""
    west, south, east, north = bbox
    lats = _frange(south, north, step)
    lngs = _frange(west, east, step)

    # cell key -> {count, species set}
    buckets: dict[tuple[int, int], dict] = {}

    def cell_key(lat: float, lng: float) -> tuple[int, int]:
        i = min(range(len(lats)), key=lambda k: abs(lats[k] - lat))
        j = min(range(len(lngs)), key=lambda k: abs(lngs[k] - lng))
        return (i, j)

    for sp in species_results:
        sid = sp["id"]
        for hex_ in sp.get("hexes", []):
            key = cell_key(hex_["lat"], hex_["lng"])
            b = buckets.setdefault(key, {"count": 0, "species": set()})
            b["count"] += hex_.get("count", 1)
            b["species"].add(sid)

    cells = []
    for i, lat in enumerate(lats):
        for j, lng in enumerate(lngs):
            b = buckets.get((i, j))
            cells.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "count": b["count"] if b else 0,
                    "species": len(b["species"]) if b else 0,
                }
            )

    nonempty = [c for c in cells if c["count"] > 0]
    return {
        "step": step,
        "cells": cells,
        "summary": {
            "totalRecords": sum(c["count"] for c in cells),
            "cellsWithData": len(nonempty),
            "cellsTotal": len(cells),
            "coveragePct": round(100 * len(nonempty) / len(cells), 1) if cells else 0,
            "maxCount": max((c["count"] for c in cells), default=0),
        },
    }
