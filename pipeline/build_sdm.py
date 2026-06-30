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


def build_sdm(debug: bool = False) -> dict:
    species_json = json.loads((DATA_DIR / "species.json").read_text())
    region = species_json["region"]
    bbox = region["bbox"]

    if debug:
        print("Building environmental grid...")
    cells = build_env_grid(bbox, cache_path=ENV_CACHE, debug=debug)
    grid = [{"lat": c["lat"], "lng": c["lng"]} for c in cells]

    out_species = {}
    for sp in species_json["species"]:
        presence_idx = _presence_indices(sp, cells)
        model = fit_predict(cells, presence_idx)
        if model is None:
            if debug:
                print(f"  {sp['commonName']}: skipped ({len(presence_idx)} presence cells)")
            continue
        out_species[sp["id"]] = model
        if debug:
            print(
                f"  {sp['commonName']}: {model['presenceCells']} presence cells, "
                f"AUC={model['auc']}, weights={model['weights']}"
            )

    output = {
        "predStep": json.loads(ENV_CACHE.read_text()).get("predStep", 0.075),
        "grid": grid,
        "species": out_species,
    }

    (DATA_DIR / "suitability.json").write_text(json.dumps(output))
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (WEB_DATA_DIR / "suitability.json").write_text(json.dumps(output))
    if debug:
        print(f"\nWrote suitability.json ({len(out_species)} species, {len(grid)} cells)")

    return output


def main():
    parser = argparse.ArgumentParser(description="Build SDM suitability surfaces")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    build_sdm(debug=args.debug)


if __name__ == "__main__":
    main()
