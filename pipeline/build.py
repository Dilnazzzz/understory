#!/usr/bin/env python3
"""Orchestrate the Understory data pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from aggregate_hexes import aggregate_hexes
from derive_season import derive_season
from fetch_occurrences import fetch_occurrences
from resolve_taxa import resolve_taxon

PIPELINE_DIR = Path(__file__).parent
DATA_DIR = PIPELINE_DIR.parent / "data"


def load_config() -> tuple[dict, dict]:
    with open(PIPELINE_DIR / "seed_species.yaml") as f:
        seed = yaml.safe_load(f)
    with open(PIPELINE_DIR / "edibility.yaml") as f:
        edibility = yaml.safe_load(f)
    return seed, edibility


def process_species(
    species_entry: dict,
    region: dict,
    edibility: dict,
    debug: bool = False,
) -> dict | None:
    """Run the full pipeline for one species."""
    species_id = species_entry["id"]
    scientific_name = species_entry["scientificName"]
    common_name = species_entry["commonName"]

    if debug:
        print(f"\nProcessing {common_name} ({scientific_name})...")

    try:
        taxon = resolve_taxon(scientific_name, debug=debug)
    except ValueError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None

    df = fetch_occurrences(
        taxon_key=taxon["taxonKey"],
        bbox=region["bbox"],
        debug=debug,
    )

    dates = df["eventDate"].tolist() if not df.empty else []
    season = derive_season(dates)

    # Conservation-sensitive species: omit hex detail (safety layer)
    edibility_data = edibility.get(species_id, {})
    conservation = edibility_data.get("conservation", "common")

    if conservation == "sensitive":
        hexes = []
    else:
        hexes = aggregate_hexes(df)

    if debug:
        print(f"  Season: active weeks {season['activeWeeks'][:5]}..."
              f"{season['activeWeeks'][-3:] if len(season['activeWeeks']) > 5 else ''}")
        print(f"  In season now: {season['inSeasonNow']}")
        print(f"  Hexes: {len(hexes)}")

    return {
        "id": species_id,
        "scientificName": taxon["scientificName"],
        "commonName": common_name,
        "taxonKey": taxon["taxonKey"],
        "occurrenceCount": len(df),
        "season": {
            "activeWeeks": season["activeWeeks"],
            "peakWeeks": season["peakWeeks"],
            "inSeasonNow": season["inSeasonNow"],
            "histogram": season["histogram"],
        },
        "hexes": hexes,
        "edibility": edibility_data,
    }


def build(species_ids: list[str] | None = None, debug: bool = False) -> dict:
    """Build species.json for requested species (or all)."""
    seed, edibility = load_config()
    region = seed["region"]
    all_species = seed["species"]

    if species_ids:
        selected = [s for s in all_species if s["id"] in species_ids]
        if not selected:
            raise ValueError(f"No matching species: {species_ids}")
    else:
        selected = all_species

    results = []
    for entry in selected:
        result = process_species(entry, region, edibility, debug=debug)
        if result:
            results.append(result)

    output = {
        "region": region,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "species": results,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "species.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Copy for static web server (served from web/)
    web_data = PIPELINE_DIR.parent / "web" / "data"
    web_data.mkdir(parents=True, exist_ok=True)
    with open(web_data / "species.json", "w") as f:
        json.dump(output, f, indent=2)

    if debug:
        print(f"\nWrote {out_path} ({len(results)} species)")

    return output


def main():
    parser = argparse.ArgumentParser(description="Build Understory species data")
    parser.add_argument("--species", type=str, help="Process a single species by id")
    parser.add_argument("--all", action="store_true", help="Process all seed species")
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if not args.species and not args.all:
        parser.error("Specify --species <id> or --all")

    species_ids = [args.species] if args.species else None
    build(species_ids=species_ids, debug=args.debug)


if __name__ == "__main__":
    main()
