"""Tests for generate_report.py."""

import json
import sys

import pytest

sys.path.insert(0, ".")
from generate_report import (
    parse_country,
    country_to_iso3,
    parse_year,
    compute_stats,
    geojson_to_svg_paths,
    build_stacked_bar_data,
    build_scatter_svg_data,
    COUNTRY_ALIASES,
)


# -- parse_country --

def test_parse_country_with_region():
    assert parse_country("USA: California") == "USA"


def test_parse_country_no_region():
    assert parse_country("Japan") == "Japan"


def test_parse_country_empty():
    assert parse_country("") == ""


def test_parse_country_none():
    assert parse_country(None) == ""


def test_parse_country_multiple_colons():
    assert parse_country("India: Karnataka: Bengaluru") == "India"


# -- country_to_iso3 --

def test_country_alias():
    assert country_to_iso3("USA") == "USA"
    assert country_to_iso3("United States") == "USA"
    assert country_to_iso3("UK") == "GBR"


def test_country_already_iso3():
    assert country_to_iso3("BRA") == "BRA"


def test_country_unknown():
    assert country_to_iso3("Atlantis") == ""


def test_country_empty():
    assert country_to_iso3("") == ""


# -- parse_year --

def test_parse_year_full_date():
    assert parse_year("2023-06-15") == 2023


def test_parse_year_partial():
    assert parse_year("2020-03") == 2020


def test_parse_year_only():
    assert parse_year("2019") == 2019


def test_parse_year_empty():
    assert parse_year("") is None


def test_parse_year_none():
    assert parse_year(None) is None


def test_parse_year_invalid():
    assert parse_year("missing") is None


def test_parse_year_out_of_range():
    assert parse_year("1800") is None


# -- compute_stats --

def make_record(**overrides):
    rec = {
        "accession": "GCA_000001",
        "organism_name": "Candida auris",
        "tax_id": 498019,
        "fppl_name": "Candida auris",
        "priority": "Critical",
        "release_date": "2023-01-15",
        "assembly_level": "Scaffold",
        "collection_date": "2020-06",
        "geo_loc_name": "USA: California",
        "genome_size_bp": 12345678,
        "gc_percent": 45.5,
    }
    rec.update(overrides)
    return rec


def test_compute_stats_basic():
    genomes = [
        make_record(accession="GCA_001"),
        make_record(accession="GCA_002", geo_loc_name="Japan", fppl_name="Candida auris"),
        make_record(accession="GCA_003", fppl_name="Aspergillus fumigatus",
                    priority="Critical", geo_loc_name="UK: London"),
    ]
    stats = compute_stats(genomes, [])
    assert stats["total_genomes"] == 3
    assert stats["genome_counts"]["Candida auris"] == 2
    assert stats["genome_counts"]["Aspergillus fumigatus"] == 1
    assert stats["genome_priority"]["Critical"] == 3


def test_compute_stats_completeness():
    genomes = [
        make_record(geo_loc_name="USA: CA", collection_date="2020"),
        make_record(geo_loc_name="", collection_date="2020"),
        make_record(geo_loc_name="Japan", collection_date=""),
        make_record(geo_loc_name="", collection_date=""),
    ]
    stats = compute_stats(genomes, [])
    c = stats["genome_completeness"]["Candida auris"]
    assert c["has_location"] == 2
    assert c["has_date"] == 2
    assert c["has_both"] == 1


def test_compute_stats_with_sra():
    genomes = [make_record(accession="GCA_001")]
    sra = [
        {"accession": "SRR001", "fppl_name": "Candida auris", "priority": "Critical",
         "release_date": "2023-01-01", "collection_date": "2020", "geo_loc_name": "India", "source": "sra"},
        {"accession": "SRR002", "fppl_name": "Candida auris", "priority": "Critical",
         "release_date": "2023-06-01", "collection_date": "", "geo_loc_name": "", "source": "sra"},
    ]
    stats = compute_stats(genomes, sra)
    assert stats["total_genomes"] == 1
    assert stats["total_sra"] == 2
    assert stats["sra_counts"]["Candida auris"] == 2
    assert stats["combined_completeness"]["Candida auris"]["total"] == 3


def test_compute_stats_empty():
    stats = compute_stats([], [])
    assert stats["total_genomes"] == 0
    assert stats["total_sra"] == 0


# -- geojson_to_svg_paths --

def test_geojson_to_svg_paths_polygon():
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"ISO_A3": "USA", "name": "United States"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-120, 40], [-110, 40], [-110, 30], [-120, 30], [-120, 40]]],
            },
        }],
    }
    paths = geojson_to_svg_paths(geojson)
    assert len(paths) == 1
    assert paths[0]["iso3"] == "USA"
    assert paths[0]["name"] == "United States"
    assert "M" in paths[0]["d"]
    assert "Z" in paths[0]["d"]


def test_geojson_to_svg_paths_multipolygon():
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"ISO_A3": "JPN", "name": "Japan"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[130, 30], [140, 30], [140, 35], [130, 35], [130, 30]]],
                    [[[141, 42], [146, 42], [146, 45], [141, 45], [141, 42]]],
                ],
            },
        }],
    }
    paths = geojson_to_svg_paths(geojson)
    assert len(paths) == 1
    assert paths[0]["iso3"] == "JPN"


def test_geojson_to_svg_paths_empty():
    paths = geojson_to_svg_paths({"type": "FeatureCollection", "features": []})
    assert paths == []


# -- build_stacked_bar_data --

def test_stacked_bar_data():
    year_counts = {
        "Critical": {2020: 10, 2021: 15},
        "High": {2020: 5, 2022: 8},
    }
    colors = {"Critical": "#dc2626", "High": "#f59e0b"}
    result = build_stacked_bar_data(year_counts, colors)
    assert result["years"] == [2020, 2021, 2022]
    assert len(result["series"]) == 2


def test_stacked_bar_data_empty():
    result = build_stacked_bar_data({}, {})
    assert result == {"years": [], "series": []}


# -- build_scatter_svg_data --

def test_scatter_data():
    data = [
        {"size": 1e7, "gc": 45.0, "species": "A", "priority": "Critical", "accession": "X"},
    ]
    colors = {"A": "#ff0000"}
    result = build_scatter_svg_data(data, colors)
    assert len(result) == 1
    assert result[0]["color"] == "#ff0000"


def test_scatter_data_empty():
    assert build_scatter_svg_data([], {}) == []
