"""Tests for fetch_metadata.py."""

import json
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, ".")
from fetch_metadata import extract_record, fetch_genomes, merge_records, SPECIES


# -- extract_record tests --

def make_report(**overrides):
    """Create a minimal NCBI genome report for testing."""
    report = {
        "accession": "GCA_000001",
        "organism": {"organism_name": "Candida auris", "tax_id": 498019},
        "assembly_info": {
            "release_date": "2023-01-15",
            "assembly_level": "Scaffold",
            "biosample": {
                "attributes": [
                    {"name": "collection_date", "value": "2020-06"},
                    {"name": "geo_loc_name", "value": "USA: California"},
                ],
                "collection_date": "2020-06",
                "geo_loc_name": "USA: California",
            },
        },
        "assembly_stats": {
            "total_sequence_length": "12345678",
            "gc_percent": 45.5,
        },
    }
    report.update(overrides)
    return report


def test_extract_record_basic():
    rec = extract_record(make_report())
    assert rec["accession"] == "GCA_000001"
    assert rec["organism_name"] == "Candida auris"
    assert rec["tax_id"] == 498019
    assert rec["release_date"] == "2023-01-15"
    assert rec["assembly_level"] == "Scaffold"
    assert rec["collection_date"] == "2020-06"
    assert rec["geo_loc_name"] == "USA: California"
    assert rec["genome_size_bp"] == 12345678
    assert rec["gc_percent"] == 45.5


def test_extract_record_no_accession():
    report = make_report()
    del report["accession"]
    assert extract_record(report) is None


def test_extract_record_missing_biosample():
    report = make_report()
    report["assembly_info"] = {"release_date": "2023-01-15", "assembly_level": "Scaffold"}
    rec = extract_record(report)
    assert rec["collection_date"] == ""
    assert rec["geo_loc_name"] == ""


def test_extract_record_no_stats():
    report = make_report()
    report["assembly_stats"] = {}
    rec = extract_record(report)
    assert rec["genome_size_bp"] is None
    assert rec["gc_percent"] is None


def test_extract_record_string_gc():
    report = make_report()
    report["assembly_stats"]["gc_percent"] = "38.2"
    rec = extract_record(report)
    assert rec["gc_percent"] == 38.2


def test_extract_record_biosample_fallback():
    """When attributes list is empty, should fall back to top-level biosample fields."""
    report = make_report()
    report["assembly_info"]["biosample"]["attributes"] = []
    rec = extract_record(report)
    assert rec["collection_date"] == "2020-06"
    assert rec["geo_loc_name"] == "USA: California"


# -- fetch_genomes tests --

def test_fetch_genomes_parses_jsonlines():
    record1 = json.dumps(make_report(accession="GCA_001"))
    record2 = json.dumps(make_report(accession="GCA_002"))
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = f"{record1}\n{record2}\n"
    mock_result.stderr = ""

    with patch("fetch_metadata.subprocess.run", return_value=mock_result):
        results = fetch_genomes("Candida auris")

    assert len(results) == 2
    assert results[0]["accession"] == "GCA_001"
    assert results[1]["accession"] == "GCA_002"


def test_fetch_genomes_handles_reports_wrapper():
    """Handle responses where records are wrapped in a 'reports' key."""
    inner = make_report(accession="GCA_wrapped")
    wrapper = json.dumps({"reports": [inner]})
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = wrapper
    mock_result.stderr = ""

    with patch("fetch_metadata.subprocess.run", return_value=mock_result):
        results = fetch_genomes("test")

    assert len(results) == 1
    assert results[0]["accession"] == "GCA_wrapped"


def test_fetch_genomes_handles_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error"

    with patch("fetch_metadata.subprocess.run", return_value=mock_result):
        results = fetch_genomes("nonexistent")

    assert results == []


# -- Species list sanity --

def test_species_list_has_19_entries():
    assert len(SPECIES) == 19


def test_all_priorities_present():
    priorities = set(info["priority"] for info in SPECIES.values())
    assert priorities == {"Critical", "High", "Medium"}


def test_critical_has_4_species():
    critical = [k for k, v in SPECIES.items() if v["priority"] == "Critical"]
    assert len(critical) == 4


# -- merge_records --

def test_merge_records_dedup():
    existing = [{"accession": "A", "val": 1}, {"accession": "B", "val": 2}]
    new = [{"accession": "B", "val": 99}, {"accession": "C", "val": 3}]
    merged = merge_records(existing, new)
    by_acc = {r["accession"]: r for r in merged}
    assert len(merged) == 3
    assert by_acc["B"]["val"] == 99  # new overwrites
    assert by_acc["C"]["val"] == 3


def test_merge_records_empty():
    assert merge_records([], []) == []
    assert len(merge_records([{"accession": "A"}], [])) == 1
    assert len(merge_records([], [{"accession": "A"}])) == 1
