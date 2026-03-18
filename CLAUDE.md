# FungiWatch

Pipeline that fetches genome metadata from NCBI for the 19 WHO Fungal Priority Pathogens and generates a self-contained HTML report.

## Architecture

```
fetch_metadata.py → metadata/*.json → generate_report.py → build/index.html
```

- `fetch_metadata.py` — Uses `datasets` CLI to query NCBI genome metadata per species
- `generate_report.py` — Reads combined metadata, downloads world GeoJSON, computes stats, renders Jinja2 template
- `templates/report.html` — Self-contained HTML with inline SVGs, JS-driven filtering, download buttons

## Commands

```bash
pixi run python fetch_metadata.py      # Fetch metadata from NCBI
pixi run python generate_report.py     # Generate HTML report
pixi run python -m pytest tests/       # Run tests
```

## Key decisions

- All charts are inline SVGs rendered client-side from embedded JSON data
- World map uses Natural Earth 110m GeoJSON converted to SVG paths at build time
- Country parsing extracts text before ":" from NCBI's `geo_loc_name` field
- Biosample attributes are a list of `{"name": ..., "value": ...}` dicts in NCBI data
