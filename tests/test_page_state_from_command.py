"""Reading the wizard's state back out of a .command bundle.

The .bmz results file only exists once a campaign has finished, so restoring the
form from that alone meant a bundle could not be reopened and corrected until
after it had been run -- the wrong way round, since a wrong ligand is worth
catching before the GPU time rather than after. The .command bundle exists from
the moment a campaign is described, and is what the Runs tab hands back under
"Bundle", so it is the artefact people actually have.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import tarfile

import pytest

from boltzmaker_web import bundle, views_auto


MD = "Protein: RECP1\nSequence: MDILC\n\nLigand: LIG1\nSMILES: CCO\n"
CFG = {"accelerator": "auto", "workers": 2}


def _command(state: dict | None, **kw) -> bytes:
    return bundle.build(
        "RoundTrip", MD, CFG, 1, json.dumps(CFG), run_key="k", private=False,
        page_state=json.dumps(state, indent=2, sort_keys=True) if state else "",
        **kw,
    ).content


def _rewrap(data: bytes, width: int) -> bytes:
    """Re-flow the base64 payload, as a mail system or a copy-paste path would."""
    head, _, payload = data.partition(b"\n" + views_auto._PAYLOAD_MARKER + b"\n")
    flat = b"".join(payload.split())
    lines = [flat[i:i + width] for i in range(0, len(flat), width)]
    return head + b"\n" + views_auto._PAYLOAD_MARKER + b"\n" + b"\n".join(lines) + b"\n"


def test_a_bundles_page_survives_the_round_trip():
    state = {"protein_sequence[]": ["MKT"], "ligand_value[]": ["CCO"]}
    assert json.loads(views_auto._page_state_from_command(_command(state))) == state


def test_the_marker_inside_the_extractor_script_is_not_mistaken_for_the_payload():
    """The extractor greps for its own marker, so the name appears twice.

    Taking the first match slices the shell script itself in as base64, which
    fails with a padding error rather than anything that names the real problem.
    """
    data = _command({"a": 1})
    assert data.count(views_auto._PAYLOAD_MARKER) >= 2, "fixture no longer covers this"
    assert json.loads(views_auto._page_state_from_command(data)) == {"a": 1}


def test_a_rewrapped_payload_still_decodes():
    """Why the builder wraps at 76 columns: a re-flowed payload must survive."""
    state = {"x": "y"}
    for width in (40, 64, 100):
        got = views_auto._page_state_from_command(_rewrap(_command(state), width))
        assert json.loads(got) == state


def test_a_bundle_without_a_saved_page_says_so_and_is_a_404():
    with pytest.raises(views_auto._BundleReadError) as caught:
        views_auto._page_state_from_command(_command(None))
    assert caught.value.status == 404
    assert "no saved page" in str(caught.value)


def test_a_file_that_is_not_a_bundle_is_refused():
    for junk in (b"", b"#!/bin/bash\necho hello\n", b"\x00\x01\x02", b"PK\x03\x04junk"):
        with pytest.raises(views_auto._BundleReadError):
            views_auto._page_state_from_command(junk)


def test_a_truncated_payload_is_refused_rather_than_half_read():
    data = _command({"a": 1})
    with pytest.raises(views_auto._BundleReadError):
        views_auto._page_state_from_command(data[: len(data) // 2])


def test_a_decompression_bomb_is_refused_before_it_is_committed_to_memory():
    """A gzip member that expands past the ceiling must not be read into RAM."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(b"\0" * (views_auto._MAX_PAYLOAD_BYTES + 4096))
    payload = base64.b64encode(buf.getvalue())
    data = b"#!/usr/bin/env bash\n" + views_auto._PAYLOAD_MARKER + b"\n" + payload + b"\n"
    with pytest.raises(views_auto._BundleReadError) as caught:
        views_auto._page_state_from_command(data)
    assert caught.value.status == 413


def test_an_oversized_page_member_is_refused():
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        tarbuf = io.BytesIO()
        with tarfile.open(fileobj=tarbuf, mode="w") as tar:
            blob = b"x" * (views_auto._MAX_PAGE_STATE_BYTES + 1024)
            info = tarfile.TarInfo(views_auto.PAGE_STATE_NAME)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
        gz.write(tarbuf.getvalue())
    payload = base64.b64encode(buf.getvalue())
    data = b"#!/usr/bin/env bash\n" + views_auto._PAYLOAD_MARKER + b"\n" + payload + b"\n"
    with pytest.raises(views_auto._BundleReadError) as caught:
        views_auto._page_state_from_command(data)
    assert caught.value.status == 413


# ---- through the route, which is where the format is sniffed ----------------

@pytest.fixture
def client():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _post(client, data: bytes, name: str):
    return client.post("/auto/prepare/page-state",
                       data={"results_file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_the_route_accepts_a_command_bundle(client):
    state = {"protein_name[]": ["GLP1R"], "ligand_value[]": ["CCO"]}
    r = _post(client, _command(state), "boltzmaker_x.command")
    assert r.status_code == 200 and r.get_json() == state


def test_the_route_sniffs_the_format_rather_than_trusting_the_name(client):
    """A browser that renamed the download must still work.

    The extension is a hint the uploader controls; the first bytes are not.
    """
    state = {"a": 1}
    for name in ("boltzmaker_x.command", "boltzmaker_x.command.txt", "download", "x.bmz"):
        r = _post(client, _command(state), name)
        assert r.status_code == 200, f"{name} -> {r.status_code}"
        assert r.get_json() == state


def test_the_route_still_accepts_a_bmz(client):
    """The pre-existing path must keep working -- it is what Step 2 hands back."""
    import zipfile
    state = {"b": 2}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("page_state.json", json.dumps(state))
    r = _post(client, buf.getvalue(), "results.bmz")
    assert r.status_code == 200 and r.get_json() == state


def test_a_bundle_with_no_saved_page_falls_back_to_its_spec(client):
    """It used to give up with a 404. Now the form is rebuilt from boltz_input.md,
    which is what makes every bundle in the Runs archive loadable."""
    r = _post(client, _command(None), "boltzmaker_x.command")
    assert r.status_code == 200, r.get_json()
    payload = r.get_json()
    assert payload["derived_from_spec"] is True
    assert payload["groups"]["protein"][0]["protein_name[]"] == "RECP1"


def test_the_route_refuses_a_file_that_is_neither(client):
    r = _post(client, b"#!/bin/bash\necho not a bundle\n", "x.command")
    assert r.status_code == 400
    assert "not a BoltzMaker bundle" in r.get_json()["error"]
