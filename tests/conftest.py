import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
