"""Tests for Fully Automated Mode: the bundle, the .bmz contract, and the routes.

The centre of gravity here is the round trip. The bundle's pack_results.py and
the server's results.py are two halves of one contract that live in different
files, run on different machines and are written in different Python versions --
exactly the shape of thing that drifts silently. So rather than asserting
against a hand-written .bmz fixture (which would encode this module's *belief*
about the format and keep passing after the real packer changed), these tests
render the actual packer out of a real bundle, run it over a synthetic campaign,
and read the result back with the real reader.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from boltzmaker_web import bundle, options, results as bmz
from boltzmaker_web.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
#  Fixtures
# ===========================================================================

@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def built_bundle():
    return bundle.build(
        "Test campaign", "Settings:\nOutput folder: ./boltz_yamls\n",
        options.defaults(), target_count=2, config_json='{"run_settings": {}}',
    )


SUMMARY_HEADER = (
    "target_id,family_id,family_group,partner_ids,display_name,ligand_id,ligand_smiles,"
    "ligand_role,flags,confidence_score,ptm,iptm,complex_plddt,affinity_pred_value,"
    "pIC50,pIC50_ensemble_mean,pIC50_ensemble_std,cif_file,plip_status,plip_png_path,"
    "plip_hydrophobic_count,plip_hydrogen_bonds_count,plip_salt_bridges_count,"
    "plip_pi_stacks_count,plip_halogen_bonds_count,notes\n"
)


@pytest.fixture
def packed_bmz(tmp_path, built_bundle):
    """A .bmz produced by the real generated packer over a synthetic campaign."""
    campaign = tmp_path / "campaign"
    campaign.mkdir()

    (campaign / "pack_results.py").write_bytes(bundle.unpack(built_bundle.content)["pack_results.py"])
    (campaign / "boltz_input.md").write_text("Settings:\nOutput folder: ./boltz_yamls\n")
    (campaign / "config.json").write_text('{"run_settings": {}}')
    (campaign / "boltz_summary.csv").write_text(
        SUMMARY_HEADER
        + ("AAA_LIG,FAM1,FAM1,,AAA with LIG,LIG,c1ccccc1,agonist,,0.91,0.9,0.88,0.87,-2.5,"
           "9.10,9.15,0.20,AAA_LIG_model_0.cif,ok,boltz_plip/AAA_LIG.png,3,2,1,0,0,\n")
        + ("BBB_LIG,FAM2,FAM2,,BBB with LIG,LIG,c1ccccc1,antagonist,LOW_CONFIDENCE,0.32,0.3,0.3,"
           "0.31,,,,,BBB_LIG_model_0.cif,skipped,,,,,,,low structural confidence.\n")
    )
    cif_dir = campaign / "boltz_cif"
    cif_dir.mkdir()
    # Minimal but genuinely parseable mmCIF, so the reader is never handed a shape
    # a real structure would not have.
    (cif_dir / "AAA_LIG_model_0.cif").write_text(
        "data_test\n_atom_site.group_PDB\n_atom_site.id\n_atom_site.type_symbol\nATOM 1 C\n"
    )
    (cif_dir / "BBB_LIG_model_0.cif").write_text("data_test\n_atom_site.group_PDB\nATOM\n")
    plip_dir = campaign / "boltz_plip"
    plip_dir.mkdir()
    (plip_dir / "AAA_LIG.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)

    proc = subprocess.run([sys.executable, "pack_results.py"], cwd=campaign,
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"packer failed:\n{proc.stdout}\n{proc.stderr}"
    out = campaign / "Test_campaign.bmz"
    assert out.is_file(), f"packer wrote nothing; stdout was:\n{proc.stdout}"
    return out


# ===========================================================================
#  Run-settings registry
# ===========================================================================

def test_blank_numeric_field_means_the_default_not_zero():
    """A cleared box and a deliberate 0 are different intents, and several of
    these options take 0 as a real value."""
    cfg = options.parse_form({"workers": "", "recycling_steps": ""})
    assert cfg["workers"] == 2          # the registry default
    assert cfg["recycling_steps"] is None  # omit the flag, defer to Boltz


def test_zero_is_preserved_where_it_is_meaningful():
    cfg = options.parse_form({"workers": "0"})
    assert cfg["workers"] == 0
    assert "--workers 0" in options.to_cli_lines(cfg)


def test_out_of_range_and_non_numeric_are_rejected():
    with pytest.raises(options.OptionError):
        options.parse_form({"workers": "999"})
    with pytest.raises(options.OptionError):
        options.parse_form({"workers": "lots"})
    with pytest.raises(options.OptionError):
        options.parse_form({"accelerator": "quantum"})


def test_none_valued_options_are_omitted_entirely():
    """Writing Boltz's current default into the script would silently pin it."""
    args = options.to_cli_args(options.defaults())
    assert "--recycling-steps" not in args
    assert "--sampling-steps" not in args


def test_cli_lines_keep_each_flag_with_its_value():
    lines = options.to_cli_lines(options.parse_form({"accelerator": "cpu", "strict": "1"}))
    assert "--accelerator cpu" in lines
    assert "--strict" in lines


def test_every_registry_flag_exists_on_the_real_cli():
    """The flags are only exercised on the user's machine, so a typo here would
    surface hours later as a failed run. Checked against BoltzMaker's own parser."""
    helptext = subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "python3"), str(REPO_ROOT / "BoltzMaker.py"),
         "all", "--help"],
        capture_output=True, text=True, timeout=120,
    ).stdout
    missing = [o.flag for o in options.RUN_OPTIONS if o.flag not in helptext]
    assert not missing, f"flags not accepted by `BoltzMaker.py all`: {missing}"


# ===========================================================================
#  Bundle
# ===========================================================================

def test_bundle_round_trips_every_member(built_bundle):
    members = bundle.unpack(built_bundle.content)
    assert set(members) == {
        "BoltzMaker.py", "README.md", "boltz_input.md", "config.json",
        "pack_results.py", "pixi.lock", "pixi.toml", "run_campaign.sh",
    }
    assert members["BoltzMaker.py"] == (REPO_ROOT / "BoltzMaker.py").read_bytes()
    assert members["pixi.lock"] == (REPO_ROOT / "pixi.lock").read_bytes()


def test_generated_shell_scripts_are_valid_bash(tmp_path, built_bundle):
    """These only ever run on someone else's machine, so a syntax error would be
    discovered by the user, not by us."""
    for name, source in (("bundle.command", built_bundle.content),
                         ("run_campaign.sh", bundle.unpack(built_bundle.content)["run_campaign.sh"])):
        path = tmp_path / name
        path.write_bytes(source)
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{name} is not valid bash:\n{proc.stderr}"


@pytest.mark.parametrize("shell", ["sh", "bash", "dash", "zsh", "ksh"])
def test_bundle_extracts_under_any_shell(tmp_path, built_bundle, shell):
    """`sh ./bundle.command` is the documented invocation, so it has to work where
    /bin/sh is dash as well as where it is bash.

    Before the re-exec guard this passed on macOS and died on the second line of
    any Linux box with "Illegal option -o pipefail", which is exactly the failure
    a Mac-only test run would never see. The final `exec` is stubbed out so the
    test extracts the payload without starting a real multi-hour campaign.
    """
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not installed")

    script = tmp_path / "bundle.command"
    source = built_bundle.content.decode("utf-8", errors="surrogateescape")
    script.write_text(
        source.replace('exec bash "$TARGET/run_campaign.sh"', 'exit 0'),
        errors="surrogateescape",
    )
    proc = subprocess.run([shell, str(script)], cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, f"{shell} failed:\n{proc.stdout}\n{proc.stderr}"

    unpacked = tmp_path / "Test_campaign"
    assert unpacked.is_dir(), f"{shell} did not unpack: {proc.stdout}"
    assert (unpacked / "run_campaign.sh").is_file()
    assert (unpacked / "BoltzMaker.py").is_file()


def test_generated_packer_is_valid_python(built_bundle):
    import ast
    ast.parse(bundle.unpack(built_bundle.content)["pack_results.py"].decode())


def test_bundle_is_deterministic():
    """Same inputs, byte-identical output -- what makes the payload checksummable."""
    args = ("Test campaign", "Settings:\n", options.defaults(), 2, "{}")
    assert bundle.build(*args).content == bundle.build(*args).content


def test_slugify_refuses_to_emit_shell_metacharacters():
    for hostile in ("../../etc/passwd", "a; rm -rf /", "$(whoami)", "name with spaces", ""):
        slug = bundle.slugify(hostile)
        assert all(c.isalnum() or c in "._-" for c in slug), slug
        assert slug


def test_unpack_rejects_a_file_that_is_not_a_bundle():
    with pytest.raises(bundle.BundleError):
        bundle.unpack(b"just some bytes")


# ===========================================================================
#  The .bmz contract, end to end
# ===========================================================================

def test_packer_output_is_readable_by_the_reader(tmp_path, packed_bmz):
    dest = tmp_path / "out"
    dest.mkdir()
    bmz.extract(packed_bmz, dest)
    loaded = bmz.load(dest)

    assert len(loaded.targets) == 2
    assert loaded.families == ["FAM1", "FAM2"]
    assert loaded.has_affinity

    first = loaded.targets[0]
    assert first.target_id == "AAA_LIG"
    assert first.confidence == pytest.approx(0.91)
    assert first.pic50 == pytest.approx(9.15)     # the ensemble mean, not plain pIC50
    assert first.plip_total == 6
    assert first.has_structure and first.has_image

    second = loaded.targets[1]
    assert second.flags == ["LOW_CONFIDENCE"]
    # An absent affinity must stay absent rather than becoming 0.0, or the target
    # reads as the weakest binder in the campaign instead of an unmeasured one.
    assert second.pic50 is None
    assert not second.has_image


def test_manifest_records_what_was_not_packed(tmp_path, packed_bmz):
    """Silent omission would make a half-populated explorer unexplainable."""
    with zipfile.ZipFile(packed_bmz) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["bmz_version"] == bundle.BMZ_VERSION
    assert manifest["targets_in_summary"] == 2
    assert manifest["structures_included"] == 2
    assert manifest["images_included"] == 1
    assert manifest["boltzmaker_sha256"] is None or len(manifest["boltzmaker_sha256"]) == 64


def test_payload_json_matches_the_loaded_results(tmp_path, packed_bmz):
    dest = tmp_path / "out"
    dest.mkdir()
    bmz.extract(packed_bmz, dest)
    payload = json.loads(bmz.to_json(bmz.load(dest)))
    assert [t["id"] for t in payload["targets"]] == ["AAA_LIG", "BBB_LIG"]
    assert payload["low_confidence_threshold"] == bmz.LOW_CONFIDENCE_THRESHOLD
    assert payload["targets"][1]["pic50"] is None


# ===========================================================================
#  Hostile uploads
# ===========================================================================

def _zip_with(tmp_path, members: dict) -> Path:
    path = tmp_path / "hostile.bmz"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


@pytest.mark.parametrize("members,fragment", [
    ({"../escape.txt": "x"}, "traversal"),
    ({"/etc/passwd": "x"}, "absolute path"),
    ({f"f{i}.txt": "x" for i in range(bmz.MAX_ENTRIES + 1)}, "entries"),
])
def test_structural_attacks_are_refused(tmp_path, members, fragment):
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(bmz.BmzError) as exc:
        bmz.extract(_zip_with(tmp_path, members), dest)
    assert fragment in str(exc.value)


def test_compression_bomb_is_refused(tmp_path):
    path = tmp_path / "bomb.bmz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.cif", "\0" * (40 * 1024 * 1024))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(bmz.BmzError) as exc:
        bmz.extract(path, dest)
    assert "compression ratio" in str(exc.value)


def test_not_a_zip_is_refused(tmp_path):
    path = tmp_path / "nope.bmz"
    path.write_bytes(b"definitely not a zip")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(bmz.BmzError):
        bmz.extract(path, dest)


@pytest.mark.parametrize("members,fragment", [
    ({"summary/boltz_summary.csv": "target_id\nA\n"}, "No manifest.json"),
    ({"manifest.json": json.dumps({"bmz_version": 99}),
      "summary/boltz_summary.csv": "target_id\nA\n"}, "format version"),
    ({"manifest.json": "3", "summary/boltz_summary.csv": "target_id\nA\n"}, "not a JSON object"),
    ({"manifest.json": "{not json", "summary/boltz_summary.csv": "target_id\nA\n"}, "not valid JSON"),
    ({"manifest.json": json.dumps({"bmz_version": 1})}, "no summary"),
    ({"manifest.json": json.dumps({"bmz_version": 1}),
      "summary/boltz_summary.csv": "target_id,flags\n"}, "no rows"),
])
def test_malformed_results_files_are_refused_with_a_readable_message(tmp_path, members, fragment):
    dest = tmp_path / "out"
    dest.mkdir()
    bmz.extract(_zip_with(tmp_path, members), dest)
    with pytest.raises(bmz.BmzError) as exc:
        bmz.load(dest)
    assert fragment in str(exc.value)


# ===========================================================================
#  Routes
# ===========================================================================

@pytest.mark.parametrize("path", ["/", "/stepwise", "/auto", "/auto/", "/auto/prepare",
                                  "/auto/analysis", "/new", "/generate", "/preflight",
                                  "/analyze", "/healthz"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_landing_offers_both_modes(client):
    html = client.get("/").data.decode()
    assert 'href="/auto"' in html
    assert 'href="/stepwise"' in html


def _nav(html: str) -> str:
    """Just the <nav> element.

    Scoped deliberately: a first cut of this test searched the whole page for
    "Preflight" and failed, because the Prepare form has a run setting labelled
    "Preflight size-warning threshold". The nav was correct all along -- the
    assertion was not.
    """
    return html[html.index("<nav"):html.index("</nav>")]


def test_nav_shows_only_the_current_mode(client):
    auto = _nav(client.get("/auto/prepare").data.decode())
    assert 'href="/auto/prepare"' in auto
    assert 'href="/preflight"' not in auto and 'href="/generate"' not in auto

    stepwise = _nav(client.get("/generate").data.decode())
    assert 'href="/preflight"' in stepwise
    assert 'href="/auto/prepare"' not in stepwise


def test_no_template_references_a_static_asset_without_cache_busting():
    """nginx serves /static/ as `public, max-age=31536000, immutable`, which is a
    promise that the bytes at a URL never change. Any tag using a bare
    url_for('static', ...) therefore pins returning visitors to that file for a
    year, however many times it is edited.

    This is not hypothetical. wizard.js was the one tag the asset() helper never
    reached, and when it grew the BoltzWizard API every returning visitor kept the
    old copy -- so form_state.js found no BoltzWizard and quietly did nothing,
    which presented as a Save page button that did not respond while the rest of
    the form worked perfectly.
    """
    offenders = []
    for template in (Path(__file__).resolve().parent.parent / "web" / "templates").glob("*.html"):
        # Strip {# ... #} comments first, including multi-line ones: the comment
        # explaining this very rule quotes the pattern it forbids, and a scan that
        # cannot tell prose from an expression fails on its own documentation.
        source = re.sub(r"\{#.*?#\}", "", template.read_text(), flags=re.S)
        for number, line in enumerate(source.splitlines(), 1):
            if re.search(r"\{\{[^}]*url_for\(\s*['\"]static['\"]", line):
                offenders.append(f"{template.name}:{number}: {line.strip()}")
    assert not offenders, (
        "use asset('...') instead of a bare url_for('static', ...):\n" + "\n".join(offenders)
    )


def test_every_script_and_stylesheet_is_versioned(client):
    """The rendered page, not just the source: catches an asset that slipped
    through in a way the template scan cannot see."""
    for path in ("/auto/prepare", "/auto/analysis", "/new", "/"):
        html = client.get(path).data.decode()
        unversioned = [
            url for url in re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
            if "?v=" not in url
        ]
        assert not unversioned, f"{path} serves un-versioned static assets: {unversioned}"


def test_vendor_route_is_an_allowlist_not_a_file_server(client):
    assert client.get("/vendor/3Dmol-2.5.5-min.js").status_code == 200
    assert client.get("/vendor/../BoltzMaker.py").status_code == 404
    assert client.get("/vendor/nope.js").status_code == 404


def test_analysis_rejects_an_empty_upload(client):
    response = client.post("/auto/analysis", data={}, content_type="multipart/form-data")
    assert response.status_code == 200
    assert ".bmz results file" in response.data.decode()


def test_unknown_session_token_is_a_clean_404(client):
    response = client.get("/auto/analysis/aaaaaaaaaaaaaaaaaaaa")
    assert response.status_code == 404
    assert "expired" in response.data.decode()


def test_upload_creates_an_explorable_session(client, packed_bmz):
    data = {"results_file": (io.BytesIO(packed_bmz.read_bytes()), "results.bmz")}
    response = client.post("/auto/analysis", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    html = response.data.decode()
    assert "results-payload" in html
    assert "AAA_LIG" in html

    token = html.split('BoltzExplorer.init("')[1].split('"')[0]
    assert client.get(f"/auto/analysis/{token}").status_code == 200
    assert client.get(f"/auto/analysis/{token}/structure/AAA_LIG").status_code == 200
    assert client.get(f"/auto/analysis/{token}/summary.csv").status_code == 200
    # A target with no packed image, and a target that does not exist at all.
    assert client.get(f"/auto/analysis/{token}/image/BBB_LIG").status_code == 404
    assert client.get(f"/auto/analysis/{token}/structure/NOSUCH").status_code == 404


def test_prepare_builds_a_bundle_from_the_wizard(client):
    response = client.post("/auto/prepare", data={
        "campaign_name": "Route test",
        "protein_name[]": "P1", "protein_sequence[]": "MKVLAAGIVGLNLGGK", "protein_partners[]": "",
        "ligand_name[]": "L1", "ligand_kind[]": "smiles", "ligand_value[]": "c1ccccc1",
        "accelerator": "cpu", "workers": "1",
    })
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].endswith('"boltzmaker_Route_test.command"')
    members = bundle.unpack(response.data)
    assert "--accelerator cpu" in members["run_campaign.sh"].decode()


def test_every_ligand_row_carries_its_own_identifier_type(client):
    """Two ligands must produce two ligands.

    The form used a radio pair per row, all sharing name="ligand_kind[]" -- which
    makes every row part of ONE radio group, so only one row could hold a
    selection. The browser then posted a single ligand_kind for N rows and the
    server's zip() over the three parallel arrays truncated to the shortest,
    dropping every ligand after the first with no error anywhere. A real campaign
    would have been built and run missing its ligands.
    """
    form = MultiDict([
        ("campaign_name", "Two ligands"),
        ("protein_name[]", "P1"), ("protein_sequence[]", "MKVLAAGIVGLNLGGK"),
        ("protein_partners[]", ""),
        ("ligand_name[]", "LG1"), ("ligand_name[]", "LG2"),
        ("ligand_kind[]", "smiles"), ("ligand_kind[]", "ccd"),
        ("ligand_value[]", "c1ccccc1"), ("ligand_value[]", "ATP"),
    ])
    response = client.post("/auto/prepare", data=form)
    assert response.status_code == 200, response.data[:400]
    md = bundle.unpack(response.data)["boltz_input.md"].decode()
    assert [line.split(":", 1)[1].strip()
            for line in md.splitlines() if line.startswith("Ligand:")] == ["LG1", "LG2"]
    assert "SMILES: c1ccccc1" in md
    assert "CCD: ATP" in md


def test_the_ligand_type_field_is_not_a_shared_radio_group(client):
    """Guards the shape, not just the behaviour: a radio pair per row would
    reintroduce the bug above while every server-side test still passed, because
    the server never sees the markup that produced the truncated post."""
    html = client.get("/auto/prepare").data.decode()
    ligand_template = html[html.index('id="tpl-ligand"'):]
    ligand_template = ligand_template[:ligand_template.index("</template>")]
    assert 'type="radio"' not in ligand_template
    assert 'name="ligand_kind[]"' in ligand_template


def test_uneven_ligand_arrays_are_reported_not_truncated(client):
    """Defence in depth for the same failure: if the form ever posts ragged
    arrays again, say so rather than silently building a smaller campaign."""
    form = MultiDict([
        ("campaign_name", "Ragged"),
        ("protein_name[]", "P1"), ("protein_sequence[]", "MKVLAAGIVGLNLGGK"),
        ("protein_partners[]", ""),
        ("ligand_name[]", "LG1"), ("ligand_name[]", "LG2"),
        ("ligand_kind[]", "smiles"),                      # one type for two rows
        ("ligand_value[]", "c1ccccc1"), ("ligand_value[]", "ATP"),
    ])
    response = client.post("/auto/prepare", data=form)
    assert response.headers.get("Content-Disposition") is None
    assert "arrived unevenly" in response.data.decode()


def test_prepare_reports_a_bad_spec_instead_of_shipping_it(client):
    """A 6-character chain id parses fine but is doomed later, so it has to be
    caught here rather than on the user's machine."""
    response = client.post("/auto/prepare", data={
        "campaign_name": "Bad", "protein_name[]": "TOOLONG",
        "protein_sequence[]": "MKVLAA", "protein_partners[]": "",
        "ligand_name[]": "L1", "ligand_kind[]": "smiles", "ligand_value[]": "c1ccccc1",
    })
    assert response.status_code == 200
    assert response.headers.get("Content-Disposition") is None
    # wizard.validate_name's own wording, checked verbatim so a reworded message
    # has to be acknowledged here rather than quietly weakening the test.
    assert "MAX 5 CHARACTERS" in response.data.decode()
