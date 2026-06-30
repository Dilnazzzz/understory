# Safety layer (v0)

Understory is a foraging reference, not an identification authority. These rules are enforced in code:

## Location privacy
- Raw observer coordinates are **never** exposed in the API or UI
- All points are aggregated to **H3 resolution 7** (~1.2 km²) in `aggregate_hexes.py`
- Only hex centroids are stored in `species.json`

## Identification
- Footer disclaimer on every page
- Detail panel requires "Verify with field guide / expert" section
- Deadly lookalike species (wild fennel, three-cornered leek) gate harvest info behind an acknowledgment button

## Conservation
- Species with `conservation: sensitive` in `edibility.yaml` have hex data omitted entirely
- UI encourages taking ≤25% of any patch (footer text)

## Data trust
- Edibility data is marked as curated draft — verify against PFAF, USDA, and field guides before shipping publicly
- GBIF occurrence data filtered to research-grade basis types where possible
