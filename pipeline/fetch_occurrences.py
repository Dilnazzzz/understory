"""Fetch and clean GBIF occurrence records."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pygbif import occurrences as gbif_occurrences

VALID_BASIS = {
    "HUMAN_OBSERVATION",
    "OBSERVATION",
    "PRESERVED_SPECIMEN",
    "LIVING_SPECIMEN",
    "MATERIAL_SAMPLE",
}

# Records with coordinate uncertainty larger than this are too imprecise to
# place in a ~1.2 km hex with any honesty. Records with no stated uncertainty
# are kept (GBIF often omits it for otherwise good observations).
MAX_COORD_UNCERTAINTY_M = 5000

# GBIF caps offset-based paging at 100k; we stay well under.
GBIF_PAGE_SIZE = 300


def fetch_occurrences(
    taxon_key: int,
    bbox: list[float],
    debug: bool = False,
    limit: int = 2000,
) -> pd.DataFrame:
    """
    Fetch occurrence records for a taxon within a bounding box.

    bbox: [west, south, east, north]
    """
    west, south, east, north = bbox

    records: list[dict] = []
    offset = 0
    total_available = None

    while len(records) < limit:
        batch = gbif_occurrences.search(
            taxonKey=taxon_key,
            hasCoordinate=True,
            hasGeospatialIssue=False,
            decimalLatitude=f"{south},{north}",
            decimalLongitude=f"{west},{east}",
            limit=GBIF_PAGE_SIZE,
            offset=offset,
        )

        total_available = batch.get("count", total_available)
        results = batch.get("results", [])
        if not results:
            break

        records.extend(results)
        offset += GBIF_PAGE_SIZE

        if batch.get("endOfRecords") or len(results) < GBIF_PAGE_SIZE:
            break

    if debug:
        suffix = f" (of {total_available} available)" if total_available else ""
        print(f"  Fetched {len(records)} raw records{suffix}")

    df = clean_occurrences(records, bbox, debug=debug)
    df.attrs["totalAvailable"] = total_available
    return df


def clean_occurrences(
    records: list[dict],
    bbox: list[float],
    debug: bool = False,
) -> pd.DataFrame:
    """Filter, dedupe, and parse occurrence records."""
    west, south, east, north = bbox
    rows = []
    dropped_uncertain = 0

    for rec in records:
        lat = rec.get("decimalLatitude")
        lon = rec.get("decimalLongitude")
        if lat is None or lon is None:
            continue

        if not (south <= lat <= north and west <= lon <= east):
            continue

        basis = rec.get("basisOfRecord", "")
        if basis and basis not in VALID_BASIS:
            continue

        uncertainty = rec.get("coordinateUncertaintyInMeters")
        if uncertainty is not None and uncertainty > MAX_COORD_UNCERTAINTY_M:
            dropped_uncertain += 1
            continue

        event_date = rec.get("eventDate") or rec.get("year")
        parsed_date = _parse_date(event_date)

        rows.append(
            {
                "lat": lat,
                "lon": lon,
                "eventDate": parsed_date,
                "year": rec.get("year"),
                "basisOfRecord": basis,
                "gbifId": rec.get("key"),
                "datasetKey": rec.get("datasetKey"),
                "uncertaintyM": uncertainty,
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        if debug:
            print("  No records after cleaning")
        return df

    # Dedupe by rounded coordinates + date
    df["_lat_r"] = df["lat"].round(4)
    df["_lon_r"] = df["lon"].round(4)
    df["_date_key"] = df["eventDate"].astype(str)
    df = df.drop_duplicates(subset=["_lat_r", "_lon_r", "_date_key"])
    df = df.drop(columns=["_lat_r", "_lon_r", "_date_key"])

    if debug:
        extra = f", {dropped_uncertain} dropped (imprecise)" if dropped_uncertain else ""
        print(f"  {len(df)} records after cleaning{extra}")

    return df.reset_index(drop=True)


def _parse_date(value) -> datetime | None:
    """Parse GBIF date strings into datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime(int(value), 6, 15)

    text = str(value).strip()

    # Strip time component if present
    if "T" in text:
        text = text.split("T")[0]

    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue

    return None
