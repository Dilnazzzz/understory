# Understory

A foraging resource that shows **what grows where and when** — grounded in GBIF occurrence data, with safety-first edibility information.

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
- Edibility: curated from PFAF, USDA, and field-guide references — marked as draft, verify before use

## v2 roadmap

- MaxEnt species distribution modeling
- Co-occurrence / indicator species graph
- GDD-adjusted phenology
