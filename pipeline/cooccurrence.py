"""Indicator-species graph: which species share ground, more than by chance.

Foragers reason by association — "where there's X, look for Y." We approximate
that from spatial overlap of occurrence hexes, scored with statistics that
correct for how common each species is:

  conditional P(Y|X) = |Hx ∩ Hy| / |Hx|
      Of the areas where X occurs, the fraction that also have Y. Directional,
      and the natural "found X → expect Y" reading.

  lift = P(X∩Y) / (P(X)·P(Y)) = shared·N / (|Hx|·|Hy|)
      How much more often X and Y share a hex than if they were independent.
      lift > 1 = positively associated; lift ≈ 1 = no signal (both just common);
      lift < 1 = avoid each other. This is what keeps ubiquitous species from
      looking "associated with everything."

Season overlap is added as a secondary signal — two species that share ground
*and* fruit at the same time are a more useful pairing for a forager.
"""

from __future__ import annotations


def _season_overlap(a_weeks: list[int], b_weeks: list[int]) -> float:
    """Jaccard overlap of two active-week sets (0–1)."""
    if not a_weeks or not b_weeks:
        return 0.0
    sa, sb = set(a_weeks), set(b_weeks)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def compute_cooccurrence(
    species_list: list[dict],
    min_shared: int = 2,
    min_lift: float = 1.2,
    min_conditional: float = 0.15,
    top_n: int = 5,
) -> dict[str, list[dict]]:
    """
    Return {species_id: [association, ...]} ranked by conditional probability.

    An association is kept only if the two species share at least `min_shared`
    hexes, have lift >= `min_lift` (genuinely co-located, not just both common),
    and P(Y|X) >= `min_conditional` (worth surfacing as "found X → expect Y").
    """
    hex_sets = {
        s["id"]: {h["h3"] for h in s.get("hexes", [])} for s in species_list
    }
    weeks = {s["id"]: s.get("season", {}).get("activeWeeks", []) for s in species_list}
    names = {s["id"]: s["commonName"] for s in species_list}

    universe: set[str] = set()
    for cells in hex_sets.values():
        universe |= cells
    n_total = len(universe)

    result: dict[str, list[dict]] = {}

    for s in species_list:
        x = s["id"]
        hx = hex_sets[x]
        if not hx or n_total == 0:
            result[x] = []
            continue

        assocs = []
        for t in species_list:
            y = t["id"]
            if y == x:
                continue
            hy = hex_sets[y]
            if not hy:
                continue

            shared = len(hx & hy)
            if shared < min_shared:
                continue

            conditional = shared / len(hx)
            if conditional < min_conditional:
                continue
            lift = (shared * n_total) / (len(hx) * len(hy))
            if lift < min_lift:
                continue

            assocs.append(
                {
                    "id": y,
                    "commonName": names[y],
                    "sharedHexes": shared,
                    "conditional": round(conditional, 3),
                    "lift": round(lift, 2),
                    "seasonOverlap": round(_season_overlap(weeks[x], weeks[y]), 2),
                }
            )

        assocs.sort(key=lambda a: (a["conditional"], a["lift"]), reverse=True)
        result[x] = assocs[:top_n]

    return result
