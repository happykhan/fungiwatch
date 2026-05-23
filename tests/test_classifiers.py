"""Smoke tests for classifiers.toml + classify_host / classify_submitter.

These guard against TOML format breakage and obvious classifier regressions.
Edit the keyword tables in classifiers.toml; if a test starts failing, decide
whether the keyword change was intended (update the test) or accidental
(revert the TOML edit).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch_metadata import classify_host, classify_submitter, _load_classifiers


def test_classifiers_toml_loads():
    data = _load_classifiers()
    assert "host" in data
    assert "submitter" in data
    assert isinstance(data["host"].get("order", []), list)
    assert isinstance(data["submitter"].get("order", []), list)
    # Every category named in `order` should have a table with `keywords`
    for section in ("host", "submitter"):
        cfg = data[section]
        for cat in cfg["order"]:
            assert cat in cfg, f"missing [{section}.{cat}] in classifiers.toml"
            assert "keywords" in cfg[cat], f"{section}.{cat} missing keywords"


@pytest.mark.parametrize("host,iso,disease,expected", [
    ("Homo sapiens", "", "", "human"),
    ("", "Human urine", "", "human"),
    ("", "clinical", "", "human"),
    ("", "blood", "", "human"),
    ("", "axilla and groin", "", "human"),
    ("", "in vitro evolved", "", "laboratory"),
    ("", "fluconazole evolved", "", "laboratory"),
    ("Cicer arietinum", "", "", "plant"),
    ("Triticum aestivum", "", "", "plant"),
    ("", "wheat", "", "plant"),
    ("Bos taurus", "", "", "animal"),
    ("Dasypus novemcinctus", "", "", "animal"),
    ("", "soil", "", "environment"),
    ("", "wastewater", "", "environment"),
    ("", "kombucha", "", "food"),
    ("", "hospital surface", "", "clinical_other"),
    ("", "", "", "unknown"),
])
def test_classify_host_cases(host, iso, disease, expected):
    assert classify_host(host, iso, disease) == expected


@pytest.mark.parametrize("submitter,expected", [
    ("UPHL_ID", "public_health"),
    ("NVSPHL", "public_health"),
    ("MDH_CSL", "public_health"),
    ("cdc-ncezid-mdb", "public_health"),
    ("Wisconsin State Laboratory of Hygiene", "public_health"),
    ("Public Health Agency of Canada", "public_health"),
    ("Chinese Center for Disease Control and Prevention", "public_health"),
    ("Wadsworth Center", "public_health"),
    ("MDUPHL", "public_health"),
    ("fda_NSPHL", "public_health"),
    ("National Health Laboratory Service", "public_health"),
    ("BI", "research_institute"),
    ("Broad Institute", "research_institute"),
    ("JGI", "research_institute"),
    ("EBI", "research_institute"),
    ("Institut Pasteur", "research_institute"),
    ("The Wellcome Trust Sanger Institute", "research_institute"),
    ("Leibniz-HKI", "research_institute"),
    ("TGen", "research_institute"),
    ("J. Craig Venter Institute", "research_institute"),
    ("Duke University", "university"),
    ("University of Birmingham", "university"),
    ("Wageningen University and Research", "university"),
    ("UMass Amherst", "university"),
    ("Shanghai Tenth People's Hospital", "hospital_clinical"),
    ("Memorial Sloan Kettering Cancer Center", "hospital_clinical"),
    ("Sidra Medicine", "hospital_clinical"),
    ("Oxford University Clinical Research Unit", "hospital_clinical"),
    ("United States Department of Agriculture", "agriculture"),
    ("AGRIBIO, CENTRE FOR AGRIBIOSCIENC", "agriculture"),
    ("Cook Lab - University of California at Davis", "agriculture"),
    ("CSIRO", "agriculture"),
    ("JMI Laboratories", "commercial"),
    ("Mateusiak/Brent", "other"),
    ("", "other"),
])
def test_classify_submitter_cases(submitter, expected):
    assert classify_submitter(submitter) == expected
