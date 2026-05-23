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

# Placeholder host/source values that should be treated as missing
PLACEHOLDERS = {"missing", "not collected", "not applicable", "not provided",
                "unknown", "na", "n/a", "none", ""}


def _clean(value: str) -> str:
    """Strip and normalise NCBI placeholder strings to empty."""
    if not value:
        return ""
    v = value.strip()
    if v.lower() in PLACEHOLDERS:
        return ""
    return v


def classify_host(host: str, isolation_source: str, host_disease: str = "") -> str:
    """Classify a BioSample into a coarse origin category.

    Returns one of: human, animal, plant, environment, food, clinical_other, unknown.
    Looks at host, isolation_source, and host_disease together. The category is
    derived; the raw fields are retained alongside it.
    """
    blob = " ".join(filter(None, [host, isolation_source, host_disease])).lower()
    if not blob:
        return "unknown"

    # Human first: most fungal records are clinical
    human_terms = ("homo sapiens", "human", "patient", "clinical isolate",
                   "blood culture", "bronchoalveolar", "sputum", "csf",
                   "cerebrospinal", "nail", "skin scraping", "vaginal", "urine",
                   "stool", "throat swab", "ear swab")
    if any(t in blob for t in human_terms):
        return "human"

    # Built-environment / hospital surfaces: still environmental but flag clinical_other
    clinical_other = ("hospital", "icu", "catheter", "ventilator", "endoscope",
                      "healthcare", "medical device", "surgical", "ward")
    if any(t in blob for t in clinical_other):
        return "clinical_other"

    # Plant
    plant_terms = ("plant", "leaf", "leaves", "root", "rhizosphere", "stem",
                   "seed", "fruit", "grain", "wheat", "maize", "corn", "rice",
                   "banana", "tomato", "potato", "coffee", "cacao", "cotton",
                   "vine", "tree", "wood", "bark", "mycelium", "phyllosphere",
                   "triticum", "zea mays", "oryza", "musa", "agriculture",
                   "crop", "nursery", "greenhouse")
    if any(t in blob for t in plant_terms):
        return "plant"

    # Animal (non-human)
    animal_terms = ("dog", "cat", "cattle", "bovine", "horse", "equine", "sheep",
                    "pig", "swine", "porcine", "poultry", "chicken", "bird",
                    "bat", "rodent", "rat", "mouse", "fish", "amphibian", "frog",
                    "salamander", "reptile", "snake", "lizard", "insect", "bee",
                    "mosquito", "wildlife", "animal", "veterinary", "fur",
                    "felis", "canis")
    if any(t in blob for t in animal_terms):
        return "animal"

    # Food
    food_terms = ("food", "cheese", "wine", "beer", "fermented", "dairy",
                  "yogurt", "kefir", "bread", "kombucha")
    if any(t in blob for t in food_terms):
        return "food"

    # Environment (free-living, soil, water, air, built)
    env_terms = ("soil", "sediment", "water", "marine", "freshwater",
                 "groundwater", "river", "lake", "ocean", "sea", "air",
                 "dust", "compost", "manure", "mud", "sludge", "wastewater",
                 "sewage", "environment", "indoor", "outdoor", "biofilm",
                 "rhizoplane", "phylloplane", "litter", "cave")
    if any(t in blob for t in env_terms):
        return "environment"

    return "unknown"

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

    collection_date = _clean(attrs.get("collection_date") or biosample.get("collection_date", ""))
    geo_loc = _clean(attrs.get("geo_loc_name") or biosample.get("geo_loc_name", ""))
    host = _clean(attrs.get("host", "") or biosample.get("host", ""))
    isolation_source = _clean(attrs.get("isolation_source", "")
                              or biosample.get("isolation_source", ""))
    host_disease = _clean(attrs.get("host_disease", ""))
    env_broad = _clean(attrs.get("env_broad_scale", "") or attrs.get("env_biome", ""))

    assembly_submitter = _clean(assembly_info.get("submitter", ""))
    owner = biosample.get("owner") or {}
    biosample_owner = _clean(owner.get("name", "") if isinstance(owner, dict) else "")

    bioproject_accession = assembly_info.get("bioproject_accession", "")

    return {
        "accession": accession,
        "organism_name": organism.get("organism_name", ""),
        "tax_id": organism.get("tax_id"),
        "release_date": assembly_info.get("release_date", ""),
        "assembly_level": assembly_info.get("assembly_level", ""),
        "collection_date": collection_date,
        "geo_loc_name": geo_loc,
        "host": host,
        "isolation_source": isolation_source,
        "host_disease": host_disease,
        "env_broad_scale": env_broad,
        "host_category": classify_host(host, isolation_source, host_disease),
        "assembly_submitter": assembly_submitter,
        "biosample_owner": biosample_owner,
        "submitter": biosample_owner or assembly_submitter,
        "bioproject_accession": bioproject_accession,
        "genome_size_bp": int(assembly_stats["total_sequence_length"]) if assembly_stats.get("total_sequence_length") else None,
        "gc_percent": float(assembly_stats["gc_percent"]) if assembly_stats.get("gc_percent") else None,
    }


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH_SIZE = 200  # records per efetch call. Lower than the API max for stability.
MAX_RETRIES = 5


def entrez_request(endpoint: str, params: dict) -> bytes:
    """Make an E-utilities request with rate limiting and retry on transient errors."""
    import http.client
    import urllib.error

    query_str = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{EUTILS_BASE}/{endpoint}?{query_str}"

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fungiwatch/0.1"})
            time.sleep(0.35)  # NCBI rate limit: 3 req/sec without API key
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            backoff = 2 ** attempt + 1.0  # 2s, 3s, 5s, 9s, 17s
            print(f"    Transient error ({type(e).__name__}): retrying in {backoff:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(backoff)
    raise RuntimeError(f"E-utilities request failed after {MAX_RETRIES} retries: {last_err}")


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

            # Organism info
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

            # BioSample attributes (free-text tag/value pairs)
            attrs = {}
            if sample is not None:
                for sa in sample.findall(".//SAMPLE_ATTRIBUTE"):
                    tag = sa.find("TAG")
                    val = sa.find("VALUE")
                    if tag is not None and val is not None and tag.text and val.text:
                        attrs[tag.text] = val.text

            # Submitter / sequencing centre lives at the SUBMISSION element
            submission = pkg.find(".//SUBMISSION")
            center = submission.attrib.get("center_name", "") if submission is not None else ""
            if not center:
                # Fall back to EXPERIMENT center_name
                exp = pkg.find(".//EXPERIMENT")
                if exp is not None:
                    center = exp.attrib.get("center_name", "")

            # BioProject + Study accession (Study groups one or more samples;
            # BioProject is the umbrella project the study sits under). The
            # BioProject is exposed as an EXTERNAL_ID with namespace="BioProject"
            # under STUDY.
            study_accession = ""
            bioproject_accession = ""
            study = pkg.find(".//STUDY")
            if study is not None:
                study_accession = study.attrib.get("accession", "")
                for eid in study.findall(".//EXTERNAL_ID"):
                    if eid.attrib.get("namespace", "").lower() == "bioproject" and eid.text:
                        bioproject_accession = eid.text.strip()
                        break

            # Library + platform
            library_strategy = ""
            library_source = ""
            library_selection = ""
            platform = ""
            instrument_model = ""
            exp = pkg.find(".//EXPERIMENT")
            if exp is not None:
                ls = exp.find(".//LIBRARY_STRATEGY")
                if ls is not None and ls.text:
                    library_strategy = ls.text
                src = exp.find(".//LIBRARY_SOURCE")
                if src is not None and src.text:
                    library_source = src.text
                sel = exp.find(".//LIBRARY_SELECTION")
                if sel is not None and sel.text:
                    library_selection = sel.text
                # PLATFORM is a wrapper; the first child element is the platform name
                plat = exp.find(".//PLATFORM")
                if plat is not None and len(plat) > 0:
                    platform = plat[0].tag
                    im = plat[0].find("INSTRUMENT_MODEL")
                    if im is not None and im.text:
                        instrument_model = im.text

            geo_loc = _clean(attrs.get("geo_loc_name", ""))
            collection_date = _clean(attrs.get("collection_date", ""))
            host = _clean(attrs.get("host", ""))
            isolation_source = _clean(attrs.get("isolation_source", ""))
            host_disease = _clean(attrs.get("host_disease", ""))
            env_broad = _clean(attrs.get("env_broad_scale", "") or attrs.get("env_biome", ""))

            records.append({
                "accession": run_acc,
                "organism_name": organism_name,
                "tax_id": tax_id,
                "release_date": published,
                "collection_date": collection_date,
                "geo_loc_name": geo_loc,
                "host": host,
                "isolation_source": isolation_source,
                "host_disease": host_disease,
                "env_broad_scale": env_broad,
                "host_category": classify_host(host, isolation_source, host_disease),
                "submitter": _clean(center),
                "bioproject_accession": bioproject_accession,
                "study_accession": study_accession,
                "platform": platform,
                "instrument_model": instrument_model,
                "library_strategy": library_strategy,
                "library_source": library_source,
                "library_selection": library_selection,
                "source": "sra",
            })

        print(f"    Fetched {min(start + BATCH_SIZE, count)}/{count} SRA runs")

    return records


def species_has_new_schema(genome_path: Path, sra_path: Path) -> bool:
    """Return True if both files exist and already contain the new schema fields.

    Used to skip species that completed in a previous run when resuming a --full fetch.
    """
    for path in (genome_path, sra_path):
        if not path.exists():
            return False
        try:
            data = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            return False
        if not data:
            continue  # empty file is OK if the other one has data
        if "host_category" not in data[0]:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch genome metadata from NCBI for WHO FPPL")
    parser.add_argument("--full", action="store_true", help="Full re-fetch (ignore cached data)")
    parser.add_argument("--force-all", action="store_true",
                        help="With --full, re-fetch every species even if its files "
                             "already have the new schema. Default behaviour skips them.")
    args = parser.parse_args()

    METADATA_DIR.mkdir(exist_ok=True)

    last_fetch = None if args.full else load_last_fetch()
    if last_fetch:
        print(f"Incremental update (SRA since {last_fetch})")
    else:
        print("Full fetch (resumable, skips species already on the new schema)")

    all_genome_records = []
    all_sra_records = []

    for name, info in SPECIES.items():
        queries = info["queries"]
        safe_name = name.replace(" ", "_").replace(".", "")

        genome_path = METADATA_DIR / f"{safe_name}.json"
        sra_path = METADATA_DIR / f"{safe_name}_sra.json"

        if args.full and not args.force_all and species_has_new_schema(genome_path, sra_path):
            cached_g = json.load(open(genome_path))
            cached_s = json.load(open(sra_path))
            print(f"Skipping {name}: already on new schema "
                  f"({len(cached_g)} genomes, {len(cached_s)} SRA runs)")
            all_genome_records.extend(cached_g)
            all_sra_records.extend(cached_s)
            continue

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
        sra_fetch_failed = False
        for query in queries:
            try:
                fetched = fetch_sra_metadata(query, min_date=last_fetch)
            except Exception as e:
                print(f"  WARNING: SRA fetch failed for '{query}' after retries: {e}. "
                      f"Falling back to cached copy if available.")
                sra_fetch_failed = True
                fetched = []
            for rec in fetched:
                if rec["accession"] not in seen_sra:
                    seen_sra.add(rec["accession"])
                    new_sra.append(rec)

        if sra_fetch_failed and not new_sra:
            # Hard failure with nothing fresh: prefer the on-disk cache (which may
            # be richer than `cached_sra` if this is a --full run).
            disk_cache = load_cached(METADATA_DIR / f"{safe_name}_sra.json")
            if disk_cache:
                sra_records = disk_cache
                print(f"  SRA: using cached copy ({len(sra_records)} runs)")
            else:
                sra_records = cached_sra  # may also be empty
                print(f"  SRA: no cache, leaving empty for {name}")
        elif last_fetch:
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
            rec.setdefault("fppl_name", name)
            rec.setdefault("priority", info["priority"])

        # Save per-species files. If we fell back to cached SRA and have no fresh
        # genomes either (rare but possible), skip the genome write to avoid
        # clobbering a richer existing file with an empty list.
        if genome_records:
            with open(METADATA_DIR / f"{safe_name}.json", "w") as f:
                json.dump(genome_records, f, indent=2)
        if sra_records:
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
