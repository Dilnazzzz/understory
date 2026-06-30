"""Resolve scientific names to GBIF taxon keys."""

from __future__ import annotations

from pygbif import species as gbif_species


def resolve_taxon(scientific_name: str, debug: bool = False) -> dict:
    """Look up a scientific name and return the best GBIF match."""
    results = gbif_species.name_backbone(
        scientificName=scientific_name,
        kingdom="Plantae",
        strict=False,
    )

    if not results:
        raise ValueError(f"No GBIF match for: {scientific_name}")

    # Handle both legacy flat and current nested response formats
    usage = results.get("usage") or results
    diagnostics = results.get("diagnostics") or results

    match_type = diagnostics.get("matchType", results.get("matchType", "NONE"))
    if match_type == "NONE":
        raise ValueError(f"No GBIF match for: {scientific_name}")

    taxon_key = (
        usage.get("key")
        or results.get("usageKey")
        or results.get("speciesKey")
    )
    if not taxon_key:
        raise ValueError(f"No taxonKey in GBIF response for: {scientific_name}")

    taxon_key = int(taxon_key)

    match = {
        "taxonKey": taxon_key,
        "scientificName": usage.get("name") or results.get("scientificName", scientific_name),
        "canonicalName": usage.get("canonicalName") or results.get("canonicalName"),
        "rank": usage.get("rank") or results.get("rank"),
        "matchType": match_type,
        "confidence": diagnostics.get("confidence") or results.get("confidence"),
    }

    if debug:
        print(f"  Resolved '{scientific_name}' → key={taxon_key} "
              f"({match['scientificName']}, {match['matchType']})")

    return match
