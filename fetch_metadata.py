#!/usr/bin/env python3
"""Fetch genome metadata from NCBI for WHO Fungal Priority Pathogens."""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

METADATA_DIR = Path("metadata")
LAST_FETCH_FILE = METADATA_DIR / "last_fetch.json"

# WHO Fungal Priority Pathogens List (19 entities)
# Priority groups: Critical, High, Medium
SPECIES = {
    # Critical priority
    "Cryptococcus neoformans": {"priority": "Critical", "queries": ["Cryptococcus neoformans"]},
    "Candida auris": {"priority": "Critical", "queries": ["Candida auris"]},
    "Aspergillus fumigatus": {"priority": "Critical", "queries": ["Aspergillus fumigatus"]},
    "Candida albicans": {"priority": "Critical", "queries": ["Candida albicans"]},
    # High priority — include old/synonym names to catch un-retaxonomized entries
    "Nakaseomyces glabrata": {"priority": "High", "queries": ["Nakaseomyces glabrata", "Candida glabrata"]},
    "Histoplasma spp.": {"priority": "High", "queries": ["Histoplasma"]},
    "Eumycetoma agents": {"priority": "High", "queries": ["Madurella", "Medicopsis", "Falciformispora", "Trematosphaeria"]},
    "Mucorales": {"priority": "High", "queries": ["Mucorales"]},
    "Fusarium spp.": {"priority": "High", "queries": ["Fusarium"]},
    "Candida tropicalis": {"priority": "High", "queries": ["Candida tropicalis"]},
    "Candida parapsilosis": {"priority": "High", "queries": ["Candida parapsilosis"]},
    # Medium priority
    "Scedosporium spp.": {"priority": "Medium", "queries": ["Scedosporium"]},
    "Lomentospora prolificans": {"priority": "Medium", "queries": ["Lomentospora prolificans"]},
    "Coccidioides spp.": {"priority": "Medium", "queries": ["Coccidioides"]},
    "Pichia kudriavzevii": {"priority": "Medium", "queries": ["Pichia kudriavzevii"]},
    "Cryptococcus gattii": {"priority": "Medium", "queries": ["Cryptococcus gattii"]},
    "Talaromyces marneffei": {"priority": "Medium", "queries": ["Talaromyces marneffei"]},
    "Pneumocystis jirovecii": {"priority": "Medium", "queries": ["Pneumocystis jirovecii"]},
    "Paracoccidioides spp.": {"priority": "Medium", "queries": ["Paracoccidioides"]},
}


def load_last_fetch() -> str | None:
    """Load last fetch date (YYYY-MM-DD) if available."""
    if LAST_FETCH_FILE.exists():
        with open(LAST_FETCH_FILE) as f:
            data = json.load(f)
            return data.get("last_fetch_date")
    return None


def save_last_fetch():
    """Save current date as last fetch date."""
    with open(LAST_FETCH_FILE, "w") as f:
        json.dump({
            "last_fetch_date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": time.time(),
        }, f, indent=2)


def load_cached(path: Path) -> list[dict]:
    """Load cached records from a JSON file."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def merge_records(existing: list[dict], new_records: list[dict]) -> list[dict]:
    """Merge records, deduplicating by accession. New records overwrite existing."""
    by_acc = {r["accession"]: r for r in existing}
    for r in new_records:
        by_acc[r["accession"]] = r
    return list(by_acc.values())


def fetch_genomes(query: str) -> list[dict]:
    """Run datasets summary genome taxon and return parsed records."""
    cmd = [
        "datasets", "summary", "genome", "taxon", query, "--as-json-lines",
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  Warning: datasets returned {result.returncode} for '{query}'")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")
        return []

    records = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Handle both single-record and paginated responses
        if "reports" in data:
            for report in data["reports"]:
                rec = extract_record(report)
                if rec:
                    records.append(rec)
        else:
            rec = extract_record(data)
            if rec:
                records.append(rec)

    return records


def extract_record(report: dict) -> dict | None:
    """Extract relevant fields from an NCBI datasets genome report."""
    accession = report.get("accession")
    if not accession:
        return None

    organism = report.get("organism", {})
    assembly_info = report.get("assembly_info", {})
    assembly_stats = report.get("assembly_stats", {})
    biosample = assembly_info.get("biosample", {})

    # Parse biosample attributes (list of {"name": ..., "value": ...} dicts)
    attrs = {}
    for attr in biosample.get("attributes", []):
        if isinstance(attr, dict):
            attrs[attr.get("name", "")] = attr.get("value", "")

    collection_date = attrs.get("collection_date") or biosample.get("collection_date", "")
    geo_loc = attrs.get("geo_loc_name") or biosample.get("geo_loc_name", "")

    return {
        "accession": accession,
        "organism_name": organism.get("organism_name", ""),
        "tax_id": organism.get("tax_id"),
        "release_date": assembly_info.get("release_date", ""),
        "assembly_level": assembly_info.get("assembly_level", ""),
        "collection_date": collection_date,
        "geo_loc_name": geo_loc,
        "genome_size_bp": int(assembly_stats["total_sequence_length"]) if assembly_stats.get("total_sequence_length") else None,
        "gc_percent": float(assembly_stats["gc_percent"]) if assembly_stats.get("gc_percent") else None,
    }


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH_SIZE = 400  # records per efetch call


def entrez_request(endpoint: str, params: dict) -> bytes:
    """Make an E-utilities request with rate limiting."""
    query_str = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{EUTILS_BASE}/{endpoint}?{query_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "fungiwatch/0.1"})
    time.sleep(0.35)  # NCBI rate limit: 3 req/sec without API key
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_sra_metadata(query: str, min_date: str | None = None) -> list[dict]:
    """Fetch SRA WGS genomic run metadata with BioSample attributes via Entrez.

    Args:
        query: Organism name to search.
        min_date: If set (YYYY-MM-DD), only fetch records published on/after this date.
    """
    import xml.etree.ElementTree as ET

    term = f"{query}[Organism] AND GENOMIC[Source] AND WGS[Strategy]"

    # Step 1: esearch with history
    params = {
        "db": "sra", "term": term, "retmax": 0,
        "usehistory": "y", "retmode": "json",
    }
    if min_date:
        params["datetype"] = "pdat"
        params["mindate"] = min_date.replace("-", "/")
        params["maxdate"] = "3000"  # no upper bound
    data = json.loads(entrez_request("esearch.fcgi", params))
    count = int(data["esearchresult"]["count"])
    if count == 0:
        return []
    webenv = data["esearchresult"]["webenv"]
    qkey = data["esearchresult"]["querykey"]
    print(f"    SRA esearch: {count} runs for '{query}'")

    # Step 2: efetch in batches, parse XML for run + biosample attributes
    records = []
    for start in range(0, count, BATCH_SIZE):
        xml_bytes = entrez_request("efetch.fcgi", {
            "db": "sra", "WebEnv": webenv, "query_key": qkey,
            "retstart": start, "retmax": BATCH_SIZE,
            "rettype": "full", "retmode": "xml",
        })
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            print(f"    XML parse error at batch {start}: {e}")
            continue

        for pkg in root.findall("EXPERIMENT_PACKAGE"):
            run_el = pkg.find(".//RUN")
            if run_el is None:
                continue
            run_acc = run_el.attrib.get("accession", "")
            published = run_el.attrib.get("published", "")

            # Get organism info
            sample = pkg.find(".//SAMPLE")
            organism_name = ""
            tax_id = None
            if sample is not None:
                sn = sample.find(".//SCIENTIFIC_NAME")
                if sn is not None:
                    organism_name = sn.text or ""
                ti = sample.find(".//TAXON_ID")
                if ti is not None:
                    try:
                        tax_id = int(ti.text)
                    except (ValueError, TypeError):
                        pass

            # Get BioSample attributes
            attrs = {}
            if sample is not None:
                for sa in sample.findall(".//SAMPLE_ATTRIBUTE"):
                    tag = sa.find("TAG")
                    val = sa.find("VALUE")
                    if tag is not None and val is not None and tag.text and val.text:
                        attrs[tag.text] = val.text

            geo_loc = attrs.get("geo_loc_name", "")
            collection_date = attrs.get("collection_date", "")
            # Filter out placeholder values
            if collection_date and collection_date.lower() in ("missing", "not collected", "not applicable", "unknown", "na", "n/a"):
                collection_date = ""
            if geo_loc and geo_loc.lower() in ("missing", "not collected", "not applicable", "unknown", "na", "n/a"):
                geo_loc = ""

            records.append({
                "accession": run_acc,
                "organism_name": organism_name,
                "tax_id": tax_id,
                "release_date": published,
                "collection_date": collection_date,
                "geo_loc_name": geo_loc,
                "source": "sra",
            })

        print(f"    Fetched {min(start + BATCH_SIZE, count)}/{count} SRA runs")

    return records


def main():
    parser = argparse.ArgumentParser(description="Fetch genome metadata from NCBI for WHO FPPL")
    parser.add_argument("--full", action="store_true", help="Full re-fetch (ignore cached data)")
    args = parser.parse_args()

    METADATA_DIR.mkdir(exist_ok=True)

    last_fetch = None if args.full else load_last_fetch()
    if last_fetch:
        print(f"Incremental update (SRA since {last_fetch})")
    else:
        print("Full fetch")

    all_genome_records = []
    all_sra_records = []

    for name, info in SPECIES.items():
        queries = info["queries"]
        safe_name = name.replace(" ", "_").replace(".", "")
        print(f"Fetching: {name} (queries: {queries})")

        # --- Assembled genomes via NCBI Datasets CLI (always full, fast) ---
        seen_accessions = set()
        genome_records = []
        for query in queries:
            fetched = fetch_genomes(query)
            for rec in fetched:
                if rec["accession"] not in seen_accessions:
                    seen_accessions.add(rec["accession"])
                    rec["source"] = "genome"
                    genome_records.append(rec)
            print(f"  Genomes {query}: {len(fetched)} raw, {len(genome_records)} unique")

        # --- SRA WGS runs via Entrez (incremental if cache exists) ---
        cached_sra = load_cached(METADATA_DIR / f"{safe_name}_sra.json") if last_fetch else []
        seen_sra = set()
        new_sra = []
        for query in queries:
            fetched = fetch_sra_metadata(query, min_date=last_fetch)
            for rec in fetched:
                if rec["accession"] not in seen_sra:
                    seen_sra.add(rec["accession"])
                    new_sra.append(rec)

        if last_fetch:
            sra_records = merge_records(cached_sra, new_sra)
            print(f"  SRA: {len(new_sra)} new, {len(sra_records)} total (merged with cache)")
        else:
            sra_records = new_sra

        print(f"  Totals: {len(genome_records)} genomes, {len(sra_records)} SRA runs")

        # Tag records with FPPL name and priority
        for rec in genome_records:
            rec["fppl_name"] = name
            rec["priority"] = info["priority"]
        for rec in sra_records:
            rec["fppl_name"] = name
            rec["priority"] = info["priority"]

        # Save per-species files
        with open(METADATA_DIR / f"{safe_name}.json", "w") as f:
            json.dump(genome_records, f, indent=2)
        with open(METADATA_DIR / f"{safe_name}_sra.json", "w") as f:
            json.dump(sra_records, f, indent=2)

        all_genome_records.extend(genome_records)
        all_sra_records.extend(sra_records)

    # Save combined files
    with open(METADATA_DIR / "all_metadata.json", "w") as f:
        json.dump(all_genome_records, f, indent=2)
    with open(METADATA_DIR / "all_sra_metadata.json", "w") as f:
        json.dump(all_sra_records, f, indent=2)

    save_last_fetch()

    # Summary
    sra_with_loc = sum(1 for r in all_sra_records if r.get("geo_loc_name"))
    sra_with_date = sum(1 for r in all_sra_records if r.get("collection_date"))
    print(f"\nAssembled genomes: {len(all_genome_records)}")
    print(f"SRA WGS runs: {len(all_sra_records)}")
    print(f"  SRA with location: {sra_with_loc} ({sra_with_loc*100//max(len(all_sra_records),1)}%)")
    print(f"  SRA with collection date: {sra_with_date} ({sra_with_date*100//max(len(all_sra_records),1)}%)")


if __name__ == "__main__":
    main()
