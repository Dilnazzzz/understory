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

# (Optional) Build predicted-suitability surfaces (SDM).
# First run fetches + caches an environmental grid (elevation + climate).
python build_sdm.py --debug

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
- [x] Co-occurrence / indicator-species graph ("found X → Y is nearby")
- [x] Species-distribution surface — used-vs-available logistic SDM (MaxEnt-equivalent) over elevation + climate
- [ ] Multi-region expansion + coverage map
- [ ] Spatial bias correction (target-group background) + spatial cross-validation

### How the SDM works

A used-vs-available logistic regression (cells with occurrences = used, the
whole grid = available background). In the heavy-background limit this is an
inhomogeneous Poisson point process — the model MaxEnt fits (Renner & Warton
2013) — so it's a legitimate SDM written transparently in numpy. Features
(elevation, annual temperature, temperature seasonality, precipitation) are
standardized with quadratic terms for unimodal niches; L2 regularization is the
analogue of MaxEnt's. Honest limits: presence-only data is spatially biased
(records cluster near people), background AUC is optimistic, and predictions are
suitability — a hypothesis — not confirmed sightings.
