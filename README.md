# Understory

A foraging resource that shows **what grows where and when** — grounded in GBIF occurrence data, localized to your spot with real climate data, and built safety-first.

## What it does

- **Where**: live GBIF occurrence records aggregated into privacy-safe H3 hexes (~1.2 km), with per-hex evidence (recency, sources, click-through GBIF links).
- **When**: foraging season derived from the day-of-year distribution of dated records.
- **Near you**: optional geolocation centers the map, sorts species by nearest patch, and shows distances.
- **Local season (GDD)**: when located, real daily temperatures ([Open-Meteo](https://open-meteo.com/), no key) drive a growing-degree-day model that shifts each season earlier/later for your microclimate.
- **Safety-first**: deadly-lookalike gating, hazards, and "not a sole ID authority" throughout.

## Quick start

```bash
# Install pipeline dependencies
pip install -r requirements.txt

# Build data for one species (debug)
cd pipeline
python build.py --species rubus_armeniacus --debug

# Build all seed species
python build.py --all

# Serve the web app
cd web
python3 -m http.server 8080
# Open http://localhost:8080
```

## Project layout

```
understory/
├── pipeline/          # GBIF fetch → season → H3 hex aggregation
├── data/              # Generated species.json (frontend reads this)
└── web/               # Static MapLibre map + season calendar
```

## Safety

This tool is **not** a sole identification authority. Always verify with a field guide or expert before harvesting. See disclaimers in the web UI.

## Data sources

- Occurrence data: [GBIF](https://www.gbif.org/) (CC BY / CC0)
- Daily temperature: [Open-Meteo](https://open-meteo.com/) archive API (no key) for the GDD phenology model
- Edibility: curated from PFAF, USDA, and field-guide references — marked as draft, verify before use

## Roadmap

- [x] Data depth + provenance (richer GBIF sampling, per-hex evidence)
- [x] Near-me + GDD-localized season
- [ ] Co-occurrence / indicator-species graph ("found X → Y is nearby")
- [ ] MaxEnt species-distribution surface (predict where it grows, not just where it was seen)
