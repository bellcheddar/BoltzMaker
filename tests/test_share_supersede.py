"""Pointing a superseded share at the campaign that replaced it.

The rule this file exists to protect: an old share keeps working. Someone was
given that URL months ago and a campaign growing is not a reason for their link
to break, or to start showing them something they did not ask for.
"""

from __future__ import annotations

import io
import pathlib
import zipfile

import pytest

from boltzmaker_web import shares


def _pkg(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", f"<html><body>{text}</body></html>")
    return buf.getvalue()


@pytest.fixture
def root(tmp_path):
    return tmp_path


def _two(root):
    old, pw_old, rev_old = shares.create(root, _pkg("26 targets"), "GLP1R", run_key="K")
    new, pw_new, rev_new = shares.create(root, _pkg("86 targets"), "GLP1R", run_key="K")
    return (old, pw_old, rev_old), (new, pw_new, rev_new)


def test_the_revoke_token_is_what_authorises_it(root):
    """Not a matching run_key: that travels in the uploaded bundle and is therefore
    attacker-chosen, so anyone could pack a .bmz claiming this campaign and redirect
    its readers."""
    (old, _pw, rev), (new, _, _) = _two(root)
    assert shares.supersede(root, old.token, "not-the-token", new.token)
    assert shares.get(root, old.token).superseded_by == ""
    assert shares.supersede(root, old.token, rev, new.token) == ""
    assert shares.get(root, old.token).superseded_by == new.token


def test_the_old_share_keeps_working(root):
    (old, pw, rev), (new, _, _) = _two(root)
    shares.supersede(root, old.token, rev, new.token)
    assert shares.site_dir(root, old.token) is not None
    assert shares.verify_password(root, old.token, pw)


def test_a_share_cannot_supersede_itself(root):
    (old, _pw, rev), _ = _two(root)
    assert "itself" in shares.supersede(root, old.token, rev, old.token)


def test_the_target_has_to_exist_here(root):
    (old, _pw, rev), _ = _two(root)
    assert "does not exist" in shares.supersede(root, old.token, rev, "Zz" * 12)


def test_a_malformed_token_is_refused_before_it_touches_a_path(root):
    (old, _pw, rev), _ = _two(root)
    assert shares.supersede(root, old.token, rev, "../../etc/passwd")


def test_pointing_at_an_already_superseded_share_is_refused(root):
    (old, _pw, rev_old), (mid, _, rev_mid) = _two(root)
    newest, _, _ = shares.create(root, _pkg("96"), "GLP1R", run_key="K")
    shares.supersede(root, mid.token, rev_mid, newest.token)
    assert "newest" in shares.supersede(root, old.token, rev_old, mid.token)


def test_a_chain_resolves_to_the_current_share(root):
    """Extended three times, the first reader should still arrive in one click."""
    a, _, ra = shares.create(root, _pkg("v1"), "C", run_key="K")
    b, _, rb = shares.create(root, _pkg("v2"), "C", run_key="K")
    c, _, _rc = shares.create(root, _pkg("v3"), "C", run_key="K")
    shares.supersede(root, a.token, ra, b.token)
    shares.supersede(root, b.token, rb, c.token)
    assert shares.newest(root, a.token) == c.token


def test_a_cycle_terminates(root):
    """Someone will eventually make one, and an infinite redirect is worse than a
    slightly stale page."""
    a, _, ra = shares.create(root, _pkg("v1"), "C", run_key="K")
    b, _, rb = shares.create(root, _pkg("v2"), "C", run_key="K")
    shares.supersede(root, a.token, ra, b.token)
    shares.supersede(root, b.token, rb, a.token)
    assert shares.newest(root, a.token) in {a.token, b.token}


def test_a_revoked_target_does_not_leave_a_dead_pointer(root):
    (old, _pw, rev), (new, _, _) = _two(root)
    shares.supersede(root, old.token, rev, new.token)
    shares.delete(root, new.token)
    assert shares.newest(root, old.token) == old.token


# ---------------------------------------------------------------------------
#  The banner, and the routes that expose all this
# ---------------------------------------------------------------------------

def test_the_banner_is_injected_not_written_into_the_package(root):
    """The stored package is the campaign as it was. Rewriting it to announce a
    later version would be editing history."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    assert 'filename == "index.html"' in src
    assert "_superseded_banner" in src


def test_only_index_html_is_rewritten(root):
    """Every other asset in the package is served untouched, so a rewrite cannot
    corrupt a CIF, an image or the viewer's own javascript."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    block = src[src.index("banner = _superseded_banner"):src.index("send_from_directory(site, filename)")]
    assert 'if filename == "index.html"' in block


def test_superseding_is_a_post(root):
    """A link-scanning mail client fetching the URL must not change what readers
    are told -- the same reason Revoke is a POST."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    i = src.index('@share_bp.route("/<token>/supersede/')
    assert 'methods=["GET", "POST"]' in src[i:i + 120]
    assert 'if request.method == "POST":' in src[i:i + 1200]


def test_the_owner_can_paste_a_whole_url(root):
    """What they have to hand is the link, not a bare token."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    assert 'rsplit("/", 1)[-1]' in src
