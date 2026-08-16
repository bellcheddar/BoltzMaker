"""Keep private, and the Runs archive.

The privacy decision travels in the user's own files -- the bundle carries a
`private` flag, pack_results copies it into the results manifest, and the site
honours it without consulting any record of its own. That is the property worth
testing: a private run must leave nothing behind, so there is nothing on the
server that could later be listed, leaked or subpoenaed.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
import zipfile

import pytest
from werkzeug.datastructures import MultiDict

from boltzmaker_web import bundle, options, runs as runs_archive
from boltzmaker_web.app import create_app

SEQUENCE = ("MNIFEMLRIDEGLRLKIYKDTEGYYTIGIGHLLTKSPSLNAAKSELDKAIGRNTNGVITKDEAEKLFNQ"
            "DVDAAVRGILRNAKLKPVYDSLDAVRRAALINMVFQMGETGVAGFTNSLRMLQQKRWDEAAVNLAKSRW"
            "YNQTPNRAKRVITTFRTGTWDAYKNL")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BOLTZMAKER_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("BOLTZMAKER_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BOLTZMAKER_SCRATCH_ROOT", str(tmp_path / "scratch"))
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def archive(app):
    return runs_archive.Archive(pathlib.Path(app.config["RUNS_ROOT"]))


# Every current browser sends this on a same-site form POST; no scripted HTTP client
# does. The archive gate requires it, so the tests that exercise archiving have to
# present themselves as the browser they are standing in for.
BROWSER = {"Sec-Fetch-Site": "same-origin"}


def _prepare(client, name: str, private: bool, headers=None):
    form = MultiDict([
        ("campaign_name", name),
        ("protein_name[]", "T4L"), ("protein_sequence[]", SEQUENCE), ("protein_partners[]", ""),
        ("ligand_name[]", "BNZ"), ("ligand_kind[]", "smiles"), ("ligand_value[]", "c1ccccc1"),
    ])
    if private:
        form.add("keep_private", "1")
    response = client.post("/auto/prepare", data=form,
                           headers=BROWSER if headers is None else headers)
    assert response.status_code == 200, response.data[:300]
    return response


def _pack(response, tmp_path: pathlib.Path) -> pathlib.Path:
    """Run the bundle's real packer over a minimal finished campaign."""
    work = tmp_path / f"campaign{id(response)}"
    work.mkdir()
    members = bundle.unpack(response.data)
    for name in ("pack_results.py", "boltz_input.md", "config.json"):
        (work / name).write_bytes(members[name])
    (work / "boltz_summary.csv").write_text(
        "target_id,cif_file,confidence_score\nT4L_BNZ,T4L_BNZ_model_0.cif,0.9\n")
    (work / "boltz_cif").mkdir()
    (work / "boltz_cif" / "T4L_BNZ_model_0.cif").write_text("data_x\n_atom_site.group_PDB\nATOM\n")
    proc = subprocess.run([sys.executable, "pack_results.py"], cwd=work,
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    packed = list(work.glob("*.bmz"))
    assert packed, proc.stdout
    return packed[0]


# ---- the flag travels in the files ---------------------------------------

def test_every_bundle_carries_a_run_key_and_a_private_flag(client):
    for private in (False, True):
        response = _prepare(client, "Campaign", private)
        config = json.loads(bundle.unpack(response.data)["config.json"])
        assert config["run_key"], "a run key is always needed to link results to a bundle"
        assert config["private"] is private


def test_the_packer_writes_both_into_the_results_manifest(client, tmp_path):
    """The generated packer is Python, not JSON. Rendering the flag with Jinja's
    tojson produced the literal `false`, which is not a Python name -- every
    bundle's packer died with NameError before this was caught."""
    for private in (False, True):
        packed = _pack(_prepare(client, "Campaign", private), tmp_path)
        manifest = json.loads(zipfile.ZipFile(packed).read("manifest.json"))
        assert manifest["private"] is private
        assert manifest["run_key"]


def test_keep_private_never_reaches_the_boltzmaker_cli():
    """It is a property of how this site handles files, not of the campaign. A
    stray --keep-private would make the generated run script fail at argparse."""
    config = options.defaults()
    config["keep_private"] = True
    assert not any("private" in arg for arg in options.to_cli_args(config))
    assert not any("private" in line for line in options.to_cli_lines(config))


# ---- what is and is not kept ---------------------------------------------

def test_a_private_bundle_is_not_archived(client, archive):
    _prepare(client, "Public one", private=False)
    _prepare(client, "Secret one", private=True)
    kept = [run.campaign for run in archive.list() if run.has_bundle]
    assert kept == ["Public one"]


def test_private_results_are_not_archived(client, archive, tmp_path):
    packed = _pack(_prepare(client, "Secret one", private=True), tmp_path)
    response = client.post(
        "/auto/analysis",
        data={"results_file": (io.BytesIO(packed.read_bytes()), "r.bmz")},
        content_type="multipart/form-data", headers=BROWSER)
    assert response.status_code == 200          # it still explores normally
    assert not [run for run in archive.list() if run.has_results]


def test_a_public_run_merges_onto_one_row(client, archive, tmp_path):
    """The bundle and the results file that came from it are one run, not two.
    This is why the key is always present and not only for private runs."""
    response = _prepare(client, "Public one", private=False)
    packed = _pack(response, tmp_path)
    client.post("/auto/analysis",
                data={"results_file": (io.BytesIO(packed.read_bytes()), "r.bmz")},
                content_type="multipart/form-data", headers=BROWSER)
    rows = [run for run in archive.list() if run.has_bundle or run.has_results]
    assert len(rows) == 1
    assert rows[0].has_bundle and rows[0].has_results


def test_the_runs_page_lists_public_runs_only(client, tmp_path):
    _prepare(client, "Visible campaign", private=False)
    _prepare(client, "Hidden campaign", private=True)
    html = client.get("/runs").data.decode()
    assert "Visible campaign" in html
    assert "Hidden campaign" not in html


def test_archived_files_can_be_downloaded_and_explored(client, archive, tmp_path):
    response = _prepare(client, "Public one", private=False)
    packed = _pack(response, tmp_path)
    client.post("/auto/analysis",
                data={"results_file": (io.BytesIO(packed.read_bytes()), "r.bmz")},
                content_type="multipart/form-data", headers=BROWSER)
    key = [run for run in archive.list() if run.has_results][0].key

    assert client.get(f"/runs/{key}/bundle").status_code == 200
    assert client.get(f"/runs/{key}/results").status_code == 200
    explored = client.get(f"/runs/{key}/explore")
    assert explored.status_code == 200
    assert "results-payload" in explored.data.decode()


def test_unknown_or_hostile_keys_are_refused(client):
    for key in ("nosuchkey", "../../etc/passwd", "a" * 200):
        for kind in ("bundle", "results", "explore"):
            assert client.get(f"/runs/{key}/{kind}").status_code in (400, 404)


# ---- retention ------------------------------------------------------------

def test_the_archive_is_capped_by_count(tmp_path, monkeypatch):
    """Unbounded growth on a host with ~16GB free is a slow disk-full outage."""
    monkeypatch.setattr(runs_archive, "MAX_RUNS", 3)
    archive = runs_archive.Archive(tmp_path / "runs")
    for index in range(6):
        archive.record_bundle(f"key{index}", f"Campaign {index}", 1, "b.command", b"x" * 100)
    kept = [run for run in archive.list() if run.has_bundle]
    assert len(kept) == 3
    assert len(list(archive.bundles.glob("*"))) == 3


def test_the_archive_is_capped_by_size(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_archive, "MAX_TOTAL_BYTES", 250)
    archive = runs_archive.Archive(tmp_path / "runs")
    for index in range(4):
        archive.record_bundle(f"key{index}", f"Campaign {index}", 1, "b.command", b"x" * 100)
    assert archive.total_bytes() <= 250


def test_a_torn_registry_line_does_not_break_the_page(tmp_path):
    archive = runs_archive.Archive(tmp_path / "runs")
    archive.record_bundle("good", "Fine campaign", 1, "b.command", b"x" * 10)
    with archive.registry.open("a") as handle:
        handle.write('{"key": "half-written"')      # a kill -9 mid-write
    assert [run.campaign for run in archive.list() if run.has_bundle] == ["Fine campaign"]


# ===========================================================================
#  The front page
# ===========================================================================

def test_the_landing_page_offers_the_runs_tab(client):
    html = client.get("/").data.decode()
    assert 'href="/runs"' in html


def test_the_landing_page_lists_the_latest_runs(client):
    _prepare(client, "Campaign one", private=False)
    _prepare(client, "Campaign two", private=False)
    html = client.get("/").data.decode()
    assert "Campaign one" in html and "Campaign two" in html
    assert "Latest runs" in html


def test_the_landing_page_shows_at_most_five(client):
    """A sign of life, not the table. The full list is at /runs."""
    for index in range(8):
        _prepare(client, f"Campaign {index}", private=False)
    html = client.get("/").data.decode()
    listed = [f"Campaign {index}" for index in range(8) if f"Campaign {index}</div>" in html]
    assert len(listed) == 5


def test_a_private_run_is_not_named_on_the_landing_page(client):
    """Same rule as the Runs tab: a private run leaves nothing on the server, so
    there is nothing here to list either."""
    _prepare(client, "Secret campaign", private=True)
    _prepare(client, "Public campaign", private=False)
    html = client.get("/").data.decode()
    assert "Public campaign" in html
    assert "Secret campaign" not in html


def test_the_landing_page_says_what_it_is_for(client):
    """The family-specific work is the part worth knowing about, and it is the
    part a first-time reader would never guess from "runs Boltz-2"."""
    html = client.get("/").data.decode()
    for claim in ("GPCRdb", "KLIFS", "Pfam", "TM1", "DFG"):
        assert claim in html, f"{claim} is not described on the landing page"


def test_the_landing_page_survives_an_empty_archive(client):
    html = client.get("/").data.decode()
    assert "Nothing here yet" in html


# --- the package, and destroying a campaign ------------------------------------

def _web(*parts):
    from pathlib import Path
    return Path(__file__).resolve().parents[1].joinpath("web", *parts)


def test_the_package_is_a_directory_of_files_not_one_giant_page():
    """"Self-contained" is satisfied by a single HTML too, and Mol* alone is 5MB
    before base64 adds a third to every structure. A directory is what a web
    server is for, and every path inside it is relative so a subdirectory works."""
    src = _web("boltzmaker_web", "package.py").read_text()
    assert "zipfile.ZipFile" in src
    assert 'href="assets/' in src and 'src="assets/' in src
    assert "/auto/analysis" not in src        # nothing points back at this server


def test_the_package_says_it_needs_a_web_server():
    """The page fetches its data and a browser refuses that from a file:// page.
    That is a rule in the browser, not something the package can arrange around,
    so it says so rather than appearing broken."""
    src = _web("boltzmaker_web", "package.py").read_text()
    assert "http.server" in src
    assert "file://" in src


def test_the_explorer_reads_from_one_place_that_can_be_swapped():
    """Served by the app the data is at /auto/analysis/<token>/…; unpacked it is a
    directory beside the page. One indirection means the package needs no second
    copy of the explorer."""
    js = _web("static", "js", "explorer.js").read_text()
    assert "function serverSources" in js and "function fileSources" in js
    # Nothing builds a session URL by hand any more.
    assert '"/auto/analysis/" + token + "/structure/' not in js


def test_destroying_is_a_post_only():
    """A prefetching browser or a link-scanning mail client following a GET would
    delete somebody's campaign on their behalf."""
    src = _web("boltzmaker_web", "views_auto.py").read_text()
    assert 'def destroy(' in src
    block = src[src.index("def destroy("):]
    assert 'methods=["POST"]' in src[max(0, src.index("def destroy(") - 200):src.index("def destroy(")]


def test_destroying_removes_the_archive_as_well_as_the_session():
    """"All data" has to mean all of it or the button is a lie."""
    src = _web("boltzmaker_web", "views_auto.py").read_text()
    block = src[src.index("def destroy("):src.index("def destroy(") + 1400]
    assert "forget(key)" in block
    assert "shutil.rmtree(session" in block


def test_forgetting_a_run_leaves_a_note_rather_than_erasing_the_row():
    """The registry is append-only: a later upload naming the same run_key has to
    find that the files are gone rather than find nothing and re-create the row."""
    src = _web("boltzmaker_web", "runs.py").read_text()
    block = src[src.index("def forget("):src.index("def prune(")]
    assert "_append" in block
    assert "destroyed at the owner" in block


def test_the_destroy_button_only_appears_for_a_private_campaign():
    html = _web("templates", "_explorer_panels.html").read_text()
    assert "{% if results.private and not package %}" in html
    assert 'id="destroy-all"' in html


def test_destroying_asks_for_the_word_rather_than_a_click():
    """It removes the only copy on the server and nothing here can undo it, so the
    cost of pressing it by accident should not be one careless click."""
    js = _web("static", "js", "explorer.js").read_text()
    block = js[js.index("function wireDestroy"):]
    assert "window.prompt" in block
    assert '"DESTROY"' in block


# --- the archive gate itself -------------------------------------------------
# Three bundles of a real, private campaign were published on /runs because the
# archive trusted every caller to have ticked "Keep private". Automated form posts
# made while testing against the live site had not. The gate now needs positive
# evidence of a person submitting the form from this site, and fails closed.

def test_a_scripted_post_is_never_archived(client, archive):
    """No Sec-Fetch-Site and no Referer: exactly what a script sends."""
    _prepare(client, "Scripted run", private=False, headers={})
    assert archive.list() == []


def test_a_client_can_opt_out_explicitly(client, archive):
    _prepare(client, "Opted out", private=False,
             headers={**BROWSER, "X-BoltzMaker-No-Archive": "1"})
    assert archive.list() == []


def test_a_cross_site_post_is_not_archived(client, archive):
    _prepare(client, "Cross site", private=False, headers={"Sec-Fetch-Site": "cross-site"})
    assert archive.list() == []


def test_a_same_origin_referer_is_accepted_when_sec_fetch_is_absent(client, archive):
    """Older browsers send no Sec-Fetch-Site; a same-origin Referer still counts."""
    _prepare(client, "Referred run", private=False,
             headers={"Referer": "http://localhost/auto/prepare"})
    assert len(archive.list()) == 1


def test_a_scripted_results_upload_is_not_archived(client, archive, tmp_path):
    packed = _pack(_prepare(client, "Scripted results", private=False), tmp_path)
    client.post("/auto/analysis",
                data={"results_file": (io.BytesIO(packed.read_bytes()), "r.bmz")},
                content_type="multipart/form-data")           # no browser headers
    assert not [run for run in archive.list() if run.has_results]
