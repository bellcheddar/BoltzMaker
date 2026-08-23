import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The Flask app is a package under web/, not at the repo root, so it needs its own
# entry. Done here rather than via `pip install -e` because an editable install
# silently does nothing on this machine (site.py skips hidden .pth files).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

def pytest_configure(config):
    # Opt-in only. The placement tests need root for powermetrics and an idle machine
    # to mean anything, so they must never run as part of the ordinary suite or in CI.
    config.addinivalue_line(
        "markers",
        "hardware: needs this specific Mac, root, and an idle machine "
        "(run with -m hardware under sudo)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") and "hardware" in str(config.getoption("-m")):
        return
    skip = pytest.mark.skip(reason="hardware test; run with -m hardware under sudo")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


FIXTURES = Path(__file__).parent / "fixtures"
SSE_FIXTURES = FIXTURES / "sse"
EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def adrb2_sequence():
    return (
        "MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAK"
        "FERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTAS"
        "IETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQE"
        "AINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRF"
        "HVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQD"
        "NLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNT"
        "GEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL"
    )


@pytest.fixture
def egfr_sequence():
    lines = Path(SSE_FIXTURES / "egfr_human.fasta").read_text().splitlines()[1:]
    return "".join(lines)


@pytest.fixture
def adrb2_apo_path():
    return SSE_FIXTURES / "2rh1_adrb2_apo.pdb"


@pytest.fixture
def adrb2_holo_cif_path():
    return EXAMPLES / "adrb2_gs_panel" / "boltz_cif" / "ADRB2_ISO1_model_0.cif"


@pytest.fixture
def egfr_apo_path():
    return SSE_FIXTURES / "1m14_egfr_apo.pdb"


@pytest.fixture
def egfr_holo_cif_path():
    return EXAMPLES / "egfr_covalent" / "boltz_cif" / "EGFR_FRAG1_model_0.cif"
