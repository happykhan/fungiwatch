#!/usr/bin/env python3
"""Generate self-contained HTML report from NCBI genome metadata."""

import csv
import json
import math
import re
import subprocess
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

METADATA_FILE = Path("metadata/all_metadata.json")
SRA_METADATA_FILE = Path("metadata/all_sra_metadata.json")
BUILD_DIR = Path("build")
TEMPLATE_DIR = Path("templates")
GEOJSON_CACHE = Path("metadata/world.geojson")

# Natural Earth 110m countries GeoJSON (public domain, ~300KB)
GEOJSON_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"

# Country name → ISO 3166-1 alpha-3 mapping (common NCBI geo_loc_name values)
COUNTRY_ALIASES = {
    "USA": "USA", "United States": "USA", "United States of America": "USA",
    "UK": "GBR", "United Kingdom": "GBR",
    "South Korea": "KOR", "Republic of Korea": "KOR", "Korea": "KOR",
    "North Korea": "PRK",
    "China": "CHN", "People's Republic of China": "CHN",
    "Taiwan": "TWN",
    "Russia": "RUS", "Russian Federation": "RUS",
    "Iran": "IRN", "Islamic Republic of Iran": "IRN",
    "Syria": "SYR", "Czech Republic": "CZE", "Czechia": "CZE",
    "The Netherlands": "NLD", "Netherlands": "NLD",
    "Ivory Coast": "CIV", "Cote d'Ivoire": "CIV",
    "Democratic Republic of the Congo": "COD", "DR Congo": "COD",
    "Republic of the Congo": "COG", "Congo": "COG",
    "Tanzania": "TZA", "United Republic of Tanzania": "TZA",
    "Vietnam": "VNM", "Viet Nam": "VNM",
    "Laos": "LAO", "Bolivia": "BOL", "Venezuela": "VEN",
}

# Full ISO 3166-1 alpha-3 country name mapping (subset for common names)
# This gets extended at runtime from GeoJSON properties
COUNTRY_TO_ISO3 = {}

PRIORITY_COLORS = {
    "Critical": "#dc2626",
    "High": "#f59e0b",
    "Medium": "#3b82f6",
}

SPECIES_COLORS = [
    "#dc2626", "#f59e0b", "#3b82f6", "#10b981", "#8b5cf6",
    "#ec4899", "#f97316", "#06b6d4", "#84cc16", "#6366f1",
    "#14b8a6", "#e11d48", "#a855f7", "#0ea5e9", "#d946ef",
    "#65a30d", "#0891b2", "#c026d3", "#ea580c",
]


def load_metadata() -> list[dict]:
    with open(METADATA_FILE) as f:
        return json.load(f)


def parse_country(geo_loc_name: str) -> str:
    """Extract country from geo_loc_name like 'USA: California' → 'USA'."""
    if not geo_loc_name:
        return ""
    country = geo_loc_name.split(":")[0].strip()
    return country


def country_to_iso3(country: str) -> str:
    """Convert country name to ISO 3166-1 alpha-3 code."""
    if not country:
        return ""
    # Check aliases first
    if country in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[country]
    # Check full mapping
    if country in COUNTRY_TO_ISO3:
        return COUNTRY_TO_ISO3[country]
    # Already an ISO3 code?
    if len(country) == 3 and country.isupper():
        return country
    return ""


def parse_year(date_str: str) -> int | None:
    """Extract year from various date formats."""
    if not date_str:
        return None
    # Try YYYY-MM-DD or YYYY-MM or YYYY
    m = re.match(r"(\d{4})", str(date_str))
    if m:
        year = int(m.group(1))
        if 1950 <= year <= 2030:
            return year
    return None


def download_geojson() -> dict:
    """Download and cache world GeoJSON."""
    if GEOJSON_CACHE.exists():
        with open(GEOJSON_CACHE) as f:
            return json.load(f)

    print("Downloading world GeoJSON...")
    GEOJSON_CACHE.parent.mkdir(exist_ok=True)

    try:
        req = urllib.request.Request(GEOJSON_URL, headers={"User-Agent": "fungiwatch/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        with open(GEOJSON_CACHE, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"  Download failed: {e}")
        return generate_minimal_world_map()


def generate_minimal_world_map() -> dict:
    """Generate a minimal world map GeoJSON with approximate country rectangles."""
    # This is a fallback — real GeoJSON is preferred
    return {"type": "FeatureCollection", "features": []}


def build_country_name_map(geojson: dict):
    """Build country name → ISO3 mapping from GeoJSON properties."""
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        iso3 = props.get("ISO_A3") or props.get("iso_a3") or props.get("id", "")
        name = props.get("name") or props.get("NAME") or props.get("ADMIN", "")
        if iso3 and len(iso3) == 3 and iso3 != "-99":
            if name:
                COUNTRY_TO_ISO3[name] = iso3
                COUNTRY_ALIASES[name] = iso3


def geojson_to_svg_paths(geojson: dict) -> list[dict]:
    """Convert GeoJSON features to SVG path data using equirectangular projection."""
    paths = []
    width, height = 960, 480

    def project(lon, lat):
        x = (lon + 180) / 360 * width
        y = (90 - lat) / 180 * height
        return x, y

    def coords_to_path(coords):
        parts = []
        for ring in coords:
            if not ring:
                continue
            points = [project(p[0], p[1]) for p in ring]
            d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
            for p in points[1:]:
                d += f"L{p[0]:.1f},{p[1]:.1f}"
            d += "Z"
            parts.append(d)
        return " ".join(parts)

    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        iso3 = props.get("ISO_A3") or props.get("iso_a3") or props.get("id", "")
        name = props.get("name") or props.get("NAME") or props.get("ADMIN", "")
        geom = feature.get("geometry", {})
        geom_type = geom.get("type", "")
        coords = geom.get("coordinates", [])

        if not coords or (iso3 == "-99" and not name):
            continue

        if geom_type == "Polygon":
            d = coords_to_path(coords)
        elif geom_type == "MultiPolygon":
            d = " ".join(coords_to_path(poly) for poly in coords)
        else:
            continue

        if d.strip():
            paths.append({
                "iso3": iso3 if iso3 != "-99" else "",
                "name": name,
                "d": d,
            })

    return paths


def _completeness(records: list[dict]) -> dict:
    """Compute metadata completeness per species for a set of records."""
    comp = defaultdict(lambda: {"total": 0, "has_location": 0, "has_date": 0, "has_both": 0})
    for r in records:
        name = r["fppl_name"]
        comp[name]["total"] += 1
        has_loc = bool(r.get("geo_loc_name"))
        has_date = bool(r.get("collection_date"))
        if has_loc:
            comp[name]["has_location"] += 1
        if has_date:
            comp[name]["has_date"] += 1
        if has_loc and has_date:
            comp[name]["has_both"] += 1
    return dict(comp)


def _country_counts(records: list[dict]) -> tuple[dict, dict, dict]:
    """Compute country counts: all, by species, by priority."""
    all_c = Counter()
    by_species = defaultdict(Counter)
    by_priority = defaultdict(Counter)
    for r in records:
        country = parse_country(r.get("geo_loc_name", ""))
        iso3 = country_to_iso3(country)
        if iso3:
            all_c[iso3] += 1
            by_species[r["fppl_name"]][iso3] += 1
            by_priority[r["priority"]][iso3] += 1
    return dict(all_c), {k: dict(v) for k, v in by_species.items()}, {k: dict(v) for k, v in by_priority.items()}


def _year_counts(records: list[dict], use_field: str = "release_date") -> tuple[dict, dict, dict]:
    """Compute year counts: all, by species, by priority."""
    all_y = Counter()
    by_species = defaultdict(Counter)
    by_priority = defaultdict(Counter)
    for r in records:
        year = parse_year(r.get(use_field, "")) or parse_year(r.get("collection_date", ""))
        if year:
            all_y[year] += 1
            by_species[r["fppl_name"]][year] += 1
            by_priority[r["priority"]][year] += 1
    return dict(all_y), {k: dict(v) for k, v in by_species.items()}, {k: dict(v) for k, v in by_priority.items()}


def _collection_years(records: list[dict]) -> dict:
    """Compute collection year histogram."""
    years = Counter()
    for r in records:
        year = parse_year(r.get("collection_date", ""))
        if year:
            years[year] += 1
    return dict(years)


def _merge_counters(*dicts):
    """Merge multiple Counter-like dicts by summing values."""
    merged = Counter()
    for d in dicts:
        for k, v in d.items():
            merged[k] += v
    return dict(merged)


def _merge_nested(*dicts):
    """Merge nested dicts of counters (e.g. by_species)."""
    merged = defaultdict(Counter)
    for d in dicts:
        for k, v in d.items():
            for k2, v2 in v.items():
                merged[k][k2] += v2
    return {k: dict(v) for k, v in merged.items()}


def compute_stats(genome_records: list[dict], sra_records: list[dict]) -> dict:
    """Compute all statistics needed for the report."""
    all_records = genome_records + sra_records
    species_names = sorted(set(r["fppl_name"] for r in all_records)) if all_records else []
    species_color_map = {name: SPECIES_COLORS[i % len(SPECIES_COLORS)]
                         for i, name in enumerate(species_names)}

    species_priority_map = {}
    for r in all_records:
        species_priority_map[r["fppl_name"]] = r["priority"]

    # Counts per source
    genome_counts = Counter(r["fppl_name"] for r in genome_records)
    sra_counts = Counter(r["fppl_name"] for r in sra_records)
    genome_priority = Counter(r["priority"] for r in genome_records)
    sra_priority = Counter(r["priority"] for r in sra_records)

    # Completeness per source
    genome_completeness = _completeness(genome_records)
    sra_completeness = _completeness(sra_records)
    combined_completeness = _completeness(all_records)

    # Country counts per source and combined
    g_cc_all, g_cc_sp, g_cc_pr = _country_counts(genome_records)
    s_cc_all, s_cc_sp, s_cc_pr = _country_counts(sra_records)
    c_cc_all = _merge_counters(g_cc_all, s_cc_all)
    c_cc_sp = _merge_nested(g_cc_sp, s_cc_sp)
    c_cc_pr = _merge_nested(g_cc_pr, s_cc_pr)

    # Year counts (published) per source and combined
    g_yc_all, g_yc_sp, g_yc_pr = _year_counts(genome_records, "release_date")
    s_yc_all, s_yc_sp, s_yc_pr = _year_counts(sra_records, "release_date")
    c_yc_all = _merge_counters(g_yc_all, s_yc_all)
    c_yc_sp = _merge_nested(g_yc_sp, s_yc_sp)
    c_yc_pr = _merge_nested(g_yc_pr, s_yc_pr)

    # Collection year histogram combined
    collection_years = _collection_years(all_records)

    # Genome size & GC% scatter (genomes only — SRA lacks these)
    scatter_data = []
    for r in genome_records:
        size = r.get("genome_size_bp")
        gc = r.get("gc_percent")
        if size and gc:
            scatter_data.append({
                "size": size, "gc": gc,
                "species": r["fppl_name"], "priority": r["priority"],
                "accession": r["accession"],
            })

    return {
        "species_names": species_names,
        "species_color_map": species_color_map,
        "species_priority_map": species_priority_map,
        "genome_counts": dict(genome_counts),
        "sra_counts": dict(sra_counts),
        "genome_priority": dict(genome_priority),
        "sra_priority": dict(sra_priority),
        "genome_completeness": genome_completeness,
        "sra_completeness": sra_completeness,
        "combined_completeness": combined_completeness,
        "country_counts_all": c_cc_all,
        "country_counts_by_species": c_cc_sp,
        "country_counts_by_priority": c_cc_pr,
        "year_counts_all": c_yc_all,
        "year_counts_by_species": c_yc_sp,
        "year_counts_by_priority": c_yc_pr,
        "scatter_data": scatter_data,
        "collection_years": collection_years,
        "priority_colors": PRIORITY_COLORS,
        "total_genomes": len(genome_records),
        "total_sra": len(sra_records),
    }


def generate_choropleth_svg(country_counts: dict, max_count: int | None = None) -> str:
    """Generate inline SVG choropleth. Colors applied via JS at runtime."""
    # SVG is rendered in the template with JS-driven coloring
    # This function is not needed — the template handles it
    pass


def build_stacked_bar_data(year_counts_by_group: dict[str, dict], color_map: dict) -> dict:
    """Prepare data for stacked bar chart."""
    if not year_counts_by_group:
        return {"years": [], "series": []}

    all_years = set()
    for counts in year_counts_by_group.values():
        all_years.update(counts.keys())

    if not all_years:
        return {"years": [], "series": []}

    min_year = min(all_years)
    max_year = max(all_years)
    years = list(range(min_year, max_year + 1))

    series = []
    for group_name in sorted(year_counts_by_group.keys()):
        counts = year_counts_by_group[group_name]
        values = [counts.get(y, 0) for y in years]
        series.append({
            "name": group_name,
            "values": values,
            "color": color_map.get(group_name, "#999"),
        })

    return {"years": years, "series": series}


def build_scatter_svg_data(scatter_data: list[dict], species_color_map: dict) -> list[dict]:
    """Prepare scatter plot point data."""
    if not scatter_data:
        return []

    points = []
    for d in scatter_data:
        points.append({
            "x": d["size"],
            "y": d["gc"],
            "species": d["species"],
            "priority": d["priority"],
            "color": species_color_map.get(d["species"], "#999"),
            "accession": d["accession"],
        })
    return points


def write_genome_csv(records: list[dict], path: Path):
    """Write assembled genome records to CSV."""
    fields = ["accession", "organism_name", "tax_id", "fppl_name", "priority",
              "release_date", "assembly_level", "collection_date", "geo_loc_name",
              "genome_size_bp", "gc_percent"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def write_sra_csv(records: list[dict], path: Path):
    """Write SRA run records to CSV."""
    fields = ["accession", "organism_name", "tax_id", "fppl_name", "priority",
              "release_date", "collection_date", "geo_loc_name"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main():
    if not METADATA_FILE.exists():
        print(f"Error: {METADATA_FILE} not found. Run fetch_metadata.py first.")
        return

    genome_records = load_metadata()
    print(f"Loaded {len(genome_records)} genome records")

    sra_records = []
    if SRA_METADATA_FILE.exists():
        with open(SRA_METADATA_FILE) as f:
            sra_records = json.load(f)
        print(f"Loaded {len(sra_records)} SRA records")

    # Download and process world GeoJSON
    geojson = download_geojson()
    build_country_name_map(geojson)
    svg_paths = geojson_to_svg_paths(geojson)
    print(f"Processed {len(svg_paths)} country paths for map")

    # Build ISO3 → country name map for CSV exports
    iso3_to_name = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        iso3 = props.get("ISO_A3") or props.get("iso_a3") or ""
        name = props.get("name") or props.get("NAME") or ""
        if iso3 and len(iso3) == 3 and iso3 != "-99" and name:
            iso3_to_name[iso3] = name

    # Compute statistics (combined genome + SRA)
    stats = compute_stats(genome_records, sra_records)

    # Build chart data
    bar_data_priority = build_stacked_bar_data(
        stats["year_counts_by_priority"], PRIORITY_COLORS
    )
    bar_data_species = build_stacked_bar_data(
        stats["year_counts_by_species"], stats["species_color_map"]
    )

    scatter_points = build_scatter_svg_data(
        stats["scatter_data"], stats["species_color_map"]
    )

    # Render template
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("report.html")

    html = template.render(
        stats=stats,
        svg_paths=svg_paths,
        bar_data_priority=bar_data_priority,
        bar_data_species=bar_data_species,
        scatter_points=scatter_points,
        country_data=json.dumps(stats["country_counts_all"]),
        country_data_by_species=json.dumps(stats["country_counts_by_species"]),
        country_data_by_priority=json.dumps(stats["country_counts_by_priority"]),
        priority_colors=json.dumps(PRIORITY_COLORS),
        species_color_map=json.dumps(stats["species_color_map"]),
        iso3_to_name=json.dumps(iso3_to_name),
        generation_date=__import__("datetime").date.today().isoformat(),
    )

    BUILD_DIR.mkdir(exist_ok=True)
    out_path = BUILD_DIR / "index.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Report written to {out_path}")

    # Write companion CSV files for full record dumps
    write_genome_csv(genome_records, BUILD_DIR / "genomes.csv")
    print(f"Genome CSV written to {BUILD_DIR / 'genomes.csv'} ({len(genome_records)} rows)")
    write_sra_csv(sra_records, BUILD_DIR / "sra_runs.csv")
    print(f"SRA CSV written to {BUILD_DIR / 'sra_runs.csv'} ({len(sra_records)} rows)")


if __name__ == "__main__":
    main()
