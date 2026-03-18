# fungi.watch

Automated surveillance dashboard for the [WHO Fungal Priority Pathogens List](https://www.who.int/publications/i/item/9789240060241). Fetches genome assembly and SRA whole-genome sequencing metadata from NCBI for all 19 priority fungal pathogens, then generates a self-contained interactive HTML report.

**Live report: [fungiwatch.vercel.app](https://fungiwatch.vercel.app)**

## What it tracks

| Priority | Species |
|----------|---------|
| **Critical** | *Cryptococcus neoformans*, *Candida auris*, *Aspergillus fumigatus*, *Candida albicans* |
| **High** | *Nakaseomyces glabrata*, *Histoplasma* spp., Eumycetoma agents, *Mucorales*, *Fusarium* spp., *Candida tropicalis*, *Candida parapsilosis* |
| **Medium** | *Scedosporium* spp., *Lomentospora prolificans*, *Coccidioides* spp., *Pichia kudriavzevii*, *Cryptococcus gattii*, *Talaromyces marneffei*, *Pneumocystis jirovecii*, *Paracoccidioides* spp. |

## Report features

- **Data availability table** — sortable by species/priority, filterable by source (Genomes, SRA, or combined), with metadata completeness stats
- **Metadata completeness chart** — horizontal stacked bars showing proportion with location, collection date, both, or neither
- **Choropleth world map** — geographic distribution with log-scale colour gradient, filterable by species or priority group
- **Published over time** — stacked bar chart of genome/SRA release dates, grouped by priority or species
- **Genome size vs GC content** — scatter plot for assembled genomes, filterable by species or priority
- **Sample collection timeline** — histogram of BioSample collection dates
- **CSV downloads** — every chart and table has a CSV export button, plus full record-level data dumps
- **SVG/PNG export** — all visualisations can be downloaded as SVG or PNG

## Quick start

Requires [Pixi](https://pixi.sh) (handles Python, `ncbi-datasets-cli`, and all dependencies).

```bash
# Install dependencies
pixi install

# Fetch all metadata from NCBI (~15-30 min on first run)
pixi run python fetch_metadata.py

# Generate the HTML report
pixi run python generate_report.py

# Open the report
open build/index.html
```

## Incremental updates

After the first run, subsequent fetches only pull new SRA records published since the last run:

```bash
pixi run python fetch_metadata.py          # incremental (SRA only fetches new)
pixi run python fetch_metadata.py --full   # force full re-fetch
pixi run python generate_report.py
```

The fetch date is tracked in `metadata/last_fetch.json`. Genome assemblies are always fully re-fetched (fast via CLI, ~4K records). SRA runs (~54K records) use E-utilities `mindate` filtering for incremental updates.

## How it works

```
fetch_metadata.py → metadata/*.json → generate_report.py → build/index.html
                                                          → build/genomes.csv
                                                          → build/sra_runs.csv
```

1. **`fetch_metadata.py`** queries NCBI for each species:
   - Assembled genomes via the [NCBI Datasets CLI](https://www.ncbi.nlm.nih.gov/datasets/) (`datasets summary genome taxon`)
   - SRA WGS runs via [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25500/) (esearch + efetch), filtered to `library_source=GENOMIC` and `library_strategy=WGS`
   - Extracts BioSample attributes (collection date, geographic location) from both sources
   - Handles taxonomy synonyms (e.g. *Candida glabrata* → *Nakaseomyces glabrata*) with deduplication

2. **`generate_report.py`** processes the metadata:
   - Downloads Natural Earth 110m GeoJSON for the world map
   - Computes statistics (counts, completeness, geographic distribution, temporal trends)
   - Renders a Jinja2 template to a self-contained HTML file with inline SVG charts
   - Generates companion CSV files for full data downloads

## Data sources

- **Assembled genomes**: [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/) — GenBank and RefSeq assemblies
- **SRA WGS runs**: [NCBI SRA](https://www.ncbi.nlm.nih.gov/sra) via E-utilities — whole-genome sequencing reads
- **World map**: [Natural Earth](https://www.naturalearthdata.com/) 110m admin boundaries (public domain)
- **Species list**: [WHO Fungal Priority Pathogens List (2022)](https://www.who.int/publications/i/item/9789240060241)

## Running tests

```bash
pixi run python -m pytest tests/ -v
```

## License

MIT
