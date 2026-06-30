#!/usr/bin/env python3
"""Build species-distribution suitability surfaces (the MaxEnt-equivalent step).

Separate from build.py because it's the heavy, optional layer: it pulls an
environmental grid (cached) and fits a per-species model. Run after build.py:

    python build_sdm.py --debug
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from env_grid import build_env_grid
from sdm import fit_predict

PIPELINE_DIR = Path(__file__).parent
DATA_DIR = PIPELINE_DIR.parent / "data"
WEB_DATA_DIR = PIPELINE_DIR.parent / "web" / "data"
ENV_CACHE = DATA_DIR / "env_grid.json"


def _nearest_cell(lat: float, lng: float, cells: list[dict]) -> int:
    best_i, best_d = 0, float("inf")
    for i, c in enumerate(cells):
        d = (c["lat"] - lat) ** 2 + (c["lng"] - lng) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def _presence_indices(species: dict, cells: list[dict]) -> list[int]:
    """Map a species' occurrence hexes to the grid cells that contain them."""
    idx = set()
    for hex_ in species.get("hexes", []):
        idx.add(_nearest_cell(hex_["lat"], hex_["lng"], cells))
    return sorted(idx)


def _survey_effort(species_list: list[dict], cells: list[dict]) -> list[float]:
    """Total target-group observations per grid cell (the sampling-bias proxy)."""
    effort = [0.0] * len(cells)
    for sp in species_list:
        for hex_ in sp.get("hexes", []):
            i = _nearest_cell(hex_["lat"], hex_["lng"], cells)
            effort[i] += hex_.get("count", 1)
    return effort


def build_region_sdm(region_data: dict, region_id: str, debug: bool = False) -> dict:
    bbox = region_data["region"]["bbox"]
    cache = DATA_DIR / f"env_grid-{region_id}.json"

    if debug:
        print(f"\n=== SDM: {region_data['region']['name']} ({region_id}) ===")
    cells = build_env_grid(bbox, cache_path=cache, debug=debug)
    grid = [{"lat": c["lat"], "lng": c["lng"]} for c in cells]

    effort = _survey_effort(region_data["species"], cells)
    if debug:
        surveyed = sum(1 for e in effort if e > 0)
        print(f"  Survey effort: {surveyed}/{len(cells)} cells have target-group records")

    out_species = {}
    for sp in region_data["species"]:
        presence_idx = _presence_indices(sp, cells)
        model = fit_predict(cells, presence_idx, effort)
        if model is None:
            if debug:
                print(f"  {sp['commonName']}: skipped ({len(presence_idx)} presence cells)")
            continue
        out_species[sp["id"]] = model
        if debug:
            print(
                f"  {sp['commonName']}: {model['presenceCells']} cells, "
                f"AUC={model['auc']} (background) / {model['spatialAuc']} (spatial CV)"
            )

    return {
        "predStep": json.loads(cache.read_text()).get("predStep", 0.075),
        "grid": grid,
        "species": out_species,
    }


def build_sdm(region_ids: list[str] | None = None, debug: bool = False) -> None:
    index = json.loads((DATA_DIR / "regions.json").read_text())
    regions = index["regions"]
    if region_ids:
        regions = [r for r in regions if r["id"] in region_ids]

    for entry in regions:
        rid = entry["id"]
        region_data = json.loads((DATA_DIR / entry["file"]).read_text())
        output = build_region_sdm(region_data, rid, debug=debug)

        fname = f"suitability-{rid}.json"
        (DATA_DIR / fname).write_text(json.dumps(output))
        WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (WEB_DATA_DIR / fname).write_text(json.dumps(output))
        if debug:
            print(f"  Wrote {fname} ({len(output['species'])} species, {len(output['grid'])} cells)")


def main():
    parser = argparse.ArgumentParser(description="Build SDM suitability surfaces")
    parser.add_argument("--region", type=str, help="Limit to a single region id")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    build_sdm(region_ids=[args.region] if args.region else None, debug=args.debug)


if __name__ == "__main__":
    main()
