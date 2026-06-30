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
from cooccurrence import compute_cooccurrence
from coverage import compute_coverage
from derive_season import derive_season
from fetch_occurrences import fetch_occurrences
from resolve_taxa import resolve_taxon

# Below this many records in a region's bbox, a species isn't shown there.
MIN_REGION_RECORDS = 10

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

    provenance = _build_provenance(df, taxon["taxonKey"])

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
        "provenance": provenance,
        "edibility": edibility_data,
    }


def _build_provenance(df, taxon_key: int) -> dict:
    """Summarize the evidence behind a species: counts, recency, sources."""
    gbif_url = f"https://www.gbif.org/species/{taxon_key}"

    if df is None or df.empty:
        return {
            "recordCount": 0,
            "totalAvailable": None,
            "yearRange": None,
            "recentCount": 0,
            "datasetCount": 0,
            "gbifTaxonUrl": gbif_url,
        }

    years = [int(y) for y in df["year"].dropna().tolist()] if "year" in df else []
    recent_cutoff = datetime.now(timezone.utc).year - 10
    datasets = (
        df["datasetKey"].dropna().nunique() if "datasetKey" in df else 0
    )

    return {
        "recordCount": int(len(df)),
        "totalAvailable": df.attrs.get("totalAvailable"),
        "yearRange": [min(years), max(years)] if years else None,
        "recentCount": int(sum(1 for y in years if y >= recent_cutoff)),
        "datasetCount": int(datasets),
        "gbifTaxonUrl": gbif_url,
    }


def _load_regions(seed: dict) -> list[dict]:
    """Support both the new `regions` list and the legacy single `region`."""
    if "regions" in seed:
        return seed["regions"]
    return [{"id": "default", **seed["region"]}]


def _region_center(bbox: list[float]) -> list[float]:
    west, south, east, north = bbox
    return [round((west + east) / 2, 5), round((south + north) / 2, 5)]


def build_region(
    region: dict, species: list[dict], edibility: dict, debug: bool = False
) -> dict:
    """Build one region's data: species (filtered), co-occurrence, coverage."""
    if debug:
        print(f"\n=== Region: {region['name']} ({region['id']}) ===")

    results = []
    for entry in species:
        result = process_species(entry, region, edibility, debug=debug)
        if result is None:
            continue
        if result["occurrenceCount"] < MIN_REGION_RECORDS:
            if debug:
                print(f"  (dropped {result['commonName']}: "
                      f"{result['occurrenceCount']} < {MIN_REGION_RECORDS} records)")
            continue
        results.append(result)

    associations = compute_cooccurrence(results)
    for sp in results:
        sp["associations"] = associations.get(sp["id"], [])

    coverage = compute_coverage(results, region["bbox"])
    if debug:
        edges = sum(len(v) for v in associations.values())
        cov = coverage["summary"]
        print(f"  {len(results)} species, {edges} associations, "
              f"coverage {cov['coveragePct']}% ({cov['cellsWithData']}/{cov['cellsTotal']} cells)")

    return {
        "region": {
            "id": region["id"],
            "name": region["name"],
            "bbox": region["bbox"],
            "center": _region_center(region["bbox"]),
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "species": results,
        "coverage": coverage,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def build(
    region_ids: list[str] | None = None,
    species_ids: list[str] | None = None,
    debug: bool = False,
) -> dict:
    """Build per-region data files plus a regions.json index."""
    seed, edibility = load_config()
    regions = _load_regions(seed)
    all_species = seed["species"]

    if region_ids:
        regions = [r for r in regions if r["id"] in region_ids]
        if not regions:
            raise ValueError(f"No matching regions: {region_ids}")

    if species_ids:
        species = [s for s in all_species if s["id"] in species_ids]
        if not species:
            raise ValueError(f"No matching species: {species_ids}")
    else:
        species = all_species

    web_data = PIPELINE_DIR.parent / "web" / "data"
    index_entries = []

    for region in regions:
        region_data = build_region(region, species, edibility, debug=debug)
        fname = f"region-{region['id']}.json"
        _write_json(DATA_DIR / fname, region_data)
        _write_json(web_data / fname, region_data)

        index_entries.append({
            "id": region["id"],
            "name": region["name"],
            "bbox": region["bbox"],
            "center": region_data["region"]["center"],
            "file": fname,
            "speciesCount": len(region_data["species"]),
            "coverage": region_data["coverage"]["summary"],
        })

    index = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "regions": index_entries,
    }
    _write_json(DATA_DIR / "regions.json", index)
    _write_json(web_data / "regions.json", index)

    if debug:
        print(f"\nWrote {len(index_entries)} region(s) + regions.json")

    return index


def main():
    parser = argparse.ArgumentParser(description="Build Understory region data")
    parser.add_argument("--species", type=str, help="Limit to a single species id")
    parser.add_argument("--region", type=str, help="Limit to a single region id")
    parser.add_argument("--all", action="store_true", help="Process all regions/species")
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if not args.all and not args.species and not args.region:
        parser.error("Specify --all (or narrow with --region/--species)")

    build(
        region_ids=[args.region] if args.region else None,
        species_ids=[args.species] if args.species else None,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
