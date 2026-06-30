"""Build a cached environmental predictor grid for the region.

Species-distribution models need environmental layers. We assemble a light
but honest predictor set over the region:

  elevation        — fine grid, from Open-Meteo's batch elevation API
  temp             — annual mean temperature
  tempSeasonality  — std of the 12 monthly mean temperatures (continentality)
  precip           — annual precipitation

Climate is sampled on a COARSE grid (it varies smoothly) and interpolated to
the fine prediction grid with inverse-distance weighting — standard practice
that keeps the number of API calls small. Elevation is sampled at full
resolution because near the coast it's the predictor that varies fastest.

The whole grid is cached to JSON so rebuilds never re-fetch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ELEV_BATCH = 100


def _frange(start: float, stop: float, step: float) -> list[float]:
    vals, v = [], start
    while v <= stop + 1e-9:
        vals.append(round(v, 5))
        v += step
    return vals


def _grid_points(bbox: list[float], step: float) -> list[tuple[float, float]]:
    west, south, east, north = bbox
    pts = []
    for lat in _frange(south, north, step):
        for lng in _frange(west, east, step):
            pts.append((lat, lng))
    return pts


def _fetch_elevations(points: list[tuple[float, float]], debug: bool) -> list[float]:
    elevations: list[float] = []
    for i in range(0, len(points), ELEV_BATCH):
        chunk = points[i : i + ELEV_BATCH]
        lats = ",".join(str(p[0]) for p in chunk)
        lngs = ",".join(str(p[1]) for p in chunk)
        resp = requests.get(
            ELEVATION_URL, params={"latitude": lats, "longitude": lngs}, timeout=30
        )
        resp.raise_for_status()
        elevations.extend(resp.json()["elevation"])
        if debug:
            print(f"    elevation {min(i + ELEV_BATCH, len(points))}/{len(points)}")
        time.sleep(0.3)
    return elevations


def _fetch_climate(
    point: tuple[float, float], years: tuple[int, int]
) -> dict[str, float]:
    lat, lng = point
    resp = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "start_date": f"{years[0]}-01-01",
            "end_date": f"{years[1]}-12-31",
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "auto",
        },
        timeout=60,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    times = daily["time"]
    temps = daily["temperature_2m_mean"]
    precip = daily["precipitation_sum"]

    valid_temps = [t for t in temps if t is not None]
    annual_temp = sum(valid_temps) / len(valid_temps) if valid_temps else 0.0

    n_years = years[1] - years[0] + 1
    total_precip = sum(p for p in precip if p is not None)
    annual_precip = total_precip / n_years

    # Monthly means -> seasonality (std across the 12 month-of-year averages).
    month_sums: dict[int, list[float]] = {}
    for t, temp in zip(times, temps):
        if temp is None:
            continue
        month = int(t[5:7])
        month_sums.setdefault(month, []).append(temp)
    monthly_means = [sum(v) / len(v) for v in month_sums.values() if v]
    seasonality = _std(monthly_means)

    return {"temp": annual_temp, "tempSeasonality": seasonality, "precip": annual_precip}


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var ** 0.5


def _idw(lat: float, lng: float, samples: list[dict], k: int = 4) -> dict[str, float]:
    """Inverse-distance-weighted interpolation of climate from coarse samples."""
    scored = sorted(
        samples,
        key=lambda s: (s["lat"] - lat) ** 2 + (s["lng"] - lng) ** 2,
    )[:k]
    keys = ("temp", "tempSeasonality", "precip")
    out, wsum = {key: 0.0 for key in keys}, 0.0
    for s in scored:
        d2 = (s["lat"] - lat) ** 2 + (s["lng"] - lng) ** 2
        if d2 < 1e-9:
            return {key: s[key] for key in keys}
        w = 1.0 / d2
        wsum += w
        for key in keys:
            out[key] += w * s[key]
    return {key: out[key] / wsum for key in keys}


def build_env_grid(
    bbox: list[float],
    pred_step: float = 0.075,
    clim_step: float = 0.25,
    clim_years: tuple[int, int] = (2022, 2024),
    cache_path: Path | None = None,
    debug: bool = False,
) -> list[dict]:
    """Return (and cache) the environmental predictor grid."""
    if cache_path and cache_path.exists():
        if debug:
            print(f"  Using cached env grid: {cache_path}")
        return json.loads(cache_path.read_text())["cells"]

    pred_points = _grid_points(bbox, pred_step)
    if debug:
        print(f"  Prediction grid: {len(pred_points)} cells")

    elevations = _fetch_elevations(pred_points, debug)

    clim_points = _grid_points(bbox, clim_step)
    if debug:
        print(f"  Climate grid: {len(clim_points)} samples ({clim_years[0]}-{clim_years[1]})")
    clim_samples = []
    for idx, pt in enumerate(clim_points):
        c = _fetch_climate(pt, clim_years)
        clim_samples.append({"lat": pt[0], "lng": pt[1], **c})
        if debug and (idx + 1) % 10 == 0:
            print(f"    climate {idx + 1}/{len(clim_points)}")
        time.sleep(0.3)

    cells = []
    for (lat, lng), elev in zip(pred_points, elevations):
        clim = _idw(lat, lng, clim_samples)
        cells.append({"lat": lat, "lng": lng, "elevation": elev, **clim})

    if cache_path:
        cache_path.write_text(
            json.dumps({"bbox": bbox, "predStep": pred_step, "cells": cells}, indent=2)
        )
        if debug:
            print(f"  Cached env grid -> {cache_path}")

    return cells
