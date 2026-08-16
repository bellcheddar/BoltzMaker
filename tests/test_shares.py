"""Password-protected shares of a private campaign.

A share deliberately keeps private data on the server, so the tests that matter
here are the negative ones: that it never reaches /runs, that the password is
really required, that only hashes are stored, and that revoking is complete.
"""
import io
import json
import pathlib
import zipfile

import pytest
from werkzeug.datastructures import MultiDict

from boltzmaker_web import runs as runs_archive, shares

from test_runs_privacy import BROWSER, SEQUENCE, _pack, _prepare, app, archive, client  # noqa: F401


def _package(names=("index.html", "assets/app.js", "data/summary.json")) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name in names:
            zf.writestr(name, f"contents of {name}")
    return buffer.getvalue()


@pytest.fixture
def runs_root(app) -> pathlib.Path:                       # noqa: F811
    return pathlib.Path(app.config["RUNS_ROOT"])


# --- the store --------------------------------------------------------------

def test_a_share_stores_no_secret_in_plaintext(runs_root):
    share, password, revoke = shares.create(runs_root, _package(), "Secret campaign")
    manifest = json.loads((runs_root / "shares" / share.token / "share.json").read_text())
    blob = json.dumps(manifest)
    assert password not in blob
    assert revoke not in blob
    assert manifest["password_hash"] and manifest["revoke_hash"]


def test_the_right_password_verifies_and_a_wrong_one_does_not(runs_root):
    share, password, _ = shares.create(runs_root, _package(), "C")
    assert shares.verify_password(runs_root, share.token, password)
    assert not shares.verify_password(runs_root, share.token, password + "x")
    assert not shares.verify_password(runs_root, share.token, "")


def test_repeated_wrong_passwords_lock_the_share(runs_root):
    share, password, _ = shares.create(runs_root, _package(), "C")
    for _ in range(shares.MAX_ATTEMPTS):
        shares.verify_password(runs_root, share.token, "wrong")
    assert shares.get(runs_root, share.token).is_locked
    # even the correct password is refused while locked, so a brute force cannot
    # simply keep going and win
    assert not shares.verify_password(runs_root, share.token, password)


def test_a_share_is_invisible_to_the_runs_archive(runs_root):
    shares.create(runs_root, _package(), "Very private")
    assert runs_archive.Archive(runs_root).list() == []


def test_the_viewing_password_cannot_revoke(runs_root):
    share, password, revoke = shares.create(runs_root, _package(), "C")
    assert not shares.revoke(runs_root, share.token, password)
    assert shares.get(runs_root, share.token) is not None
    assert shares.revoke(runs_root, share.token, revoke)
    assert shares.get(runs_root, share.token) is None


def test_revoking_removes_the_files_not_just_the_row(runs_root):
    share, _, revoke = shares.create(runs_root, _package(), "C")
    site = shares.site_dir(runs_root, share.token)
    assert (site / "index.html").is_file()
    shares.revoke(runs_root, share.token, revoke)
    assert not (runs_root / "shares" / share.token).exists()


def test_a_hostile_token_cannot_escape_the_shares_directory(runs_root):
    for token in ("../../etc", "..", "a/../../b", "", "short"):
        assert shares.get(runs_root, token) is None
        assert shares.site_dir(runs_root, token) is None


def test_a_package_with_an_unsafe_member_is_refused(runs_root):
    with pytest.raises(shares.ShareError):
        shares.create(runs_root, _package(names=("../escaped.html",)), "C")


def test_storage_is_capped_and_refuses_rather_than_evicting(runs_root, monkeypatch):
    """Shares never expire, so the cap must not delete one to make room -- that
    would break the promise that a link works until it is revoked."""
    share, _, _ = shares.create(runs_root, _package(), "First")
    monkeypatch.setattr(shares, "MAX_SHARE_BYTES", 1)
    with pytest.raises(shares.ShareError):
        shares.create(runs_root, _package(), "Second")
    assert shares.get(runs_root, share.token) is not None      # the old one survives


def test_forget_for_run_takes_only_that_campaigns_shares(runs_root):
    mine, _, _ = shares.create(runs_root, _package(), "Mine", run_key="RUN-A")
    theirs, _, _ = shares.create(runs_root, _package(), "Theirs", run_key="RUN-B")
    assert shares.forget_for_run(runs_root, "RUN-A") == [mine.token]
    assert shares.get(runs_root, theirs.token) is not None


# --- the routes -------------------------------------------------------------

def test_the_page_is_not_served_without_the_password(client, runs_root):   # noqa: F811
    # A distinctive name, because the assertion below is that it does NOT appear:
    # a short one would be a substring of the page chrome and pass for free.
    share, password, _ = shares.create(runs_root, _package(), "Zolpidem_GPR171_secret")
    body = client.get(f"/share/{share.token}").data.decode()
    assert "password" in body.lower()
    assert "Zolpidem_GPR171_secret" not in body    # the name is not leaked pre-auth

    # asking for the content directly just bounces back to the prompt
    assert client.get(f"/share/{share.token}/page/index.html").status_code == 302

    wrong = client.post(f"/share/{share.token}", data={"password": "nope"})
    assert wrong.status_code == 401
    assert client.get(f"/share/{share.token}/page/index.html").status_code == 302


def test_the_right_password_opens_the_report(client, runs_root):           # noqa: F811
    share, password, _ = shares.create(runs_root, _package(), "C")
    assert client.post(f"/share/{share.token}",
                       data={"password": password}).status_code == 302
    page = client.get(f"/share/{share.token}/page/index.html")
    assert page.status_code == 200
    assert b"contents of index.html" in page.data


def test_an_unknown_share_is_a_404_not_a_prompt(client):                   # noqa: F811
    assert client.get("/share/" + "z" * 24).status_code == 404


def test_revoking_needs_a_post_so_link_previews_cannot_delete(client, runs_root):  # noqa: F811
    share, _, revoke = shares.create(runs_root, _package(), "C")
    assert client.get(f"/share/{share.token}/revoke/{revoke}").status_code == 200
    assert shares.get(runs_root, share.token) is not None      # GET did not delete
    assert client.post(f"/share/{share.token}/revoke/{revoke}").status_code == 200
    assert shares.get(runs_root, share.token) is None


def test_a_wrong_revoke_token_is_refused(client, runs_root):               # noqa: F811
    share, _, _ = shares.create(runs_root, _package(), "C")
    assert client.post(f"/share/{share.token}/revoke/{'x' * 24}").status_code == 403
    assert shares.get(runs_root, share.token) is not None


def test_a_public_campaign_cannot_be_shared_this_way(client, tmp_path):    # noqa: F811
    """A public run is already on /runs with an explore link; a second
    password-gated copy would only be confusing."""
    response = _prepare(client, "Public one", private=False)
    packed = _pack(response, tmp_path)
    analysis = client.post("/auto/analysis",
                           data={"results_file": (io.BytesIO(packed.read_bytes()), "r.bmz")},
                           content_type="multipart/form-data", headers=BROWSER)
    token = analysis.request.path.rsplit("/", 1)[-1] if False else None
    # find the session token from the rendered page
    import re
    match = re.search(r"/auto/analysis/([A-Za-z0-9_-]{16,})", analysis.data.decode())
    assert match, "no session token in the analysis page"
    assert client.post(f"/auto/analysis/{match.group(1)}/share").status_code == 400
