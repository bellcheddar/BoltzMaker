"""Password-protected shares of a private campaign's HTML package.

A private campaign is deliberately not archived and not listed on /runs, which
leaves its owner with only two options: keep the whole thing to themselves, or
hand over a zip. A share is the middle ground -- the same self-contained package
the Download button produces, hosted at an unguessable URL behind a password the
owner passes on out of band.

**A share is still not a listed run.** It lives under <runs_root>/shares/, which
the Archive never reads: /runs and the landing page are built from registry.jsonl
plus bundles/ and results/, so a share cannot appear on either no matter how many
exist. That separation is the whole point, and it is why this is a separate module
rather than a flag on a Run.

**No expiry, by explicit choice.** Shares live until revoked. That makes the disk
cap load-bearing rather than advisory, so `create` refuses a new share when the
total would exceed MAX_SHARE_BYTES instead of evicting an old one -- evicting
would quietly break the promise that a link keeps working until you revoke it.

**Two independent secrets per share.** The URL token is unguessable on its own, so
the password is defence in depth rather than the only lock; the revoke token is
separate again, so handing someone the viewing password never lets them delete
anything. Nothing is stored in plaintext but the salt.

Sessions do not use Flask's signed cookies: the app has no SECRET_KEY, and a
per-share secret is better here anyway. Revoking a share deletes its secret, which
invalidates every cookie already issued for it -- a global key could not do that
without logging everyone out of everything.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

SHARES_DIRNAME = "shares"
MANIFEST_NAME = "share.json"
SITE_DIRNAME = "site"

# The droplet has ~16GB of disk shared with three other apps, and shares never
# expire. Refuse past this rather than evict.
MAX_SHARE_BYTES = 2 * 1024 * 1024 * 1024
MAX_SHARES = 50

# Deliberately expensive; a share password is short enough that iteration count is
# what stands between a leaked share.json and the password itself.
PBKDF2_ROUNDS = 240_000

MAX_ATTEMPTS = 10          # per share, before a cooldown
LOCKOUT_SECONDS = 900

TOKEN_RE = re.compile(r"\A[A-Za-z0-9_-]{16,64}\Z")


class ShareError(Exception):
    """Raised when a share cannot be created."""


@dataclass
class Share:
    token: str
    campaign: str
    created: str
    run_key: str = ""
    bytes_stored: int = 0
    attempts: int = 0
    locked_until: float = 0.0
    #: Token of the share that replaced this one, if any. The older share keeps
    #: working and keeps its content -- a link handed to someone months ago should
    #: not turn into a 404 because the campaign grew -- and gains a pointer onward.
    superseded_by: str = ""

    @property
    def is_locked(self) -> bool:
        return time.time() < self.locked_until


def _root(runs_root: Path) -> Path:
    return Path(runs_root) / SHARES_DIRNAME


def _dir(runs_root: Path, token: str) -> Path | None:
    """The share's directory, or None if the token is not a plausible one.

    Validated with a strict pattern rather than trusted: this value arrives in a
    URL and is about to be joined onto a path.
    """
    if not TOKEN_RE.match(token or ""):
        return None
    path = (_root(runs_root) / token).resolve()
    if path.parent != _root(runs_root).resolve():
        return None
    return path


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)


def new_password() -> str:
    """Short enough to retype from a message, long enough that the rate limit is
    not the only thing standing in the way."""
    return secrets.token_urlsafe(9)


def total_bytes(runs_root: Path) -> int:
    root = _root(runs_root)
    if not root.is_dir():
        return 0
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def list_tokens(runs_root: Path) -> list[str]:
    root = _root(runs_root)
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / MANIFEST_NAME).is_file())


def create(runs_root: Path, package: bytes, campaign: str, run_key: str = "") -> tuple[Share, str, str]:
    """Store a package as a new share. Returns (share, password, revoke_token).

    The password and revoke token are returned once and never stored, only their
    hashes -- there is no "remind me" path by design.
    """
    root = _root(runs_root)
    root.mkdir(parents=True, exist_ok=True)

    if len(list_tokens(runs_root)) >= MAX_SHARES:
        raise ShareError(f"this server already holds {MAX_SHARES} shares, its limit. "
                         "Revoke one you no longer need and try again.")
    if total_bytes(runs_root) + len(package) > MAX_SHARE_BYTES:
        raise ShareError("this server's share storage is full. Shares are kept until you "
                         "revoke them, so nothing is deleted automatically -- revoke one "
                         "you no longer need and try again.")

    token = secrets.token_urlsafe(24)
    password = new_password()
    revoke_token = secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)

    path = root / token
    site = path / SITE_DIRNAME
    site.mkdir(parents=True)
    try:
        with zipfile.ZipFile(BytesIO(package)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                # The names are ours, but this writes to disk from an archive, so
                # confine every one of them rather than trusting that.
                destination = (site / member.filename).resolve()
                if not str(destination).startswith(str(site.resolve()) + "/"):
                    raise ShareError("package contains an unsafe path")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(path, ignore_errors=True)
        raise ShareError(f"could not unpack the HTML package: {exc}") from exc

    stored = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    manifest = {
        "token": token,
        "campaign": campaign,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_key": run_key,
        "bytes_stored": stored,
        "salt": salt.hex(),
        "password_hash": _hash(password, salt).hex(),
        "revoke_hash": hashlib.sha256(revoke_token.encode("utf-8")).hexdigest(),
        "cookie_secret": secrets.token_hex(32),
        "attempts": 0,
        "locked_until": 0.0,
    }
    (path / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return _share_from(manifest), password, revoke_token


def _share_from(manifest: dict) -> Share:
    return Share(token=manifest["token"], campaign=manifest.get("campaign", ""),
                 created=manifest.get("created", ""), run_key=manifest.get("run_key", ""),
                 superseded_by=manifest.get("superseded_by", ""),
                 bytes_stored=int(manifest.get("bytes_stored", 0)),
                 attempts=int(manifest.get("attempts", 0)),
                 locked_until=float(manifest.get("locked_until", 0.0)))


def _manifest(runs_root: Path, token: str) -> dict | None:
    path = _dir(runs_root, token)
    if path is None or not (path / MANIFEST_NAME).is_file():
        return None
    try:
        return json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get(runs_root: Path, token: str) -> Share | None:
    manifest = _manifest(runs_root, token)
    return _share_from(manifest) if manifest else None


def verify_password(runs_root: Path, token: str, password: str) -> bool:
    """Constant-time check, with a per-share attempt limit.

    The limit is stored beside the share rather than in memory so it survives the
    gunicorn worker being recycled, which would otherwise reset it for free.
    """
    manifest = _manifest(runs_root, token)
    if manifest is None:
        return False
    if time.time() < float(manifest.get("locked_until", 0.0)):
        return False

    expected = bytes.fromhex(manifest["password_hash"])
    salt = bytes.fromhex(manifest["salt"])
    ok = hmac.compare_digest(_hash(password or "", salt), expected)

    manifest["attempts"] = 0 if ok else int(manifest.get("attempts", 0)) + 1
    if manifest["attempts"] >= MAX_ATTEMPTS:
        manifest["locked_until"] = time.time() + LOCKOUT_SECONDS
        manifest["attempts"] = 0
    path = _dir(runs_root, token)
    if path is not None:
        try:
            (path / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError:
            pass
    return ok


def cookie_value(runs_root: Path, token: str) -> str | None:
    """The value proving a visitor got past the password for this share."""
    manifest = _manifest(runs_root, token)
    if manifest is None:
        return None
    return hmac.new(manifest["cookie_secret"].encode("utf-8"),
                    token.encode("utf-8"), hashlib.sha256).hexdigest()


def cookie_valid(runs_root: Path, token: str, presented: str) -> bool:
    expected = cookie_value(runs_root, token)
    if expected is None or not presented:
        return False
    return hmac.compare_digest(expected, presented)


def site_dir(runs_root: Path, token: str) -> Path | None:
    path = _dir(runs_root, token)
    if path is None:
        return None
    site = path / SITE_DIRNAME
    return site if site.is_dir() else None


def supersede(runs_root: Path, token: str, revoke_token: str, new_token: str) -> str:
    """Point an older share at the one that replaced it.

    Authenticated by the REVOKE token, not by a matching run_key. run_key travels
    in the uploaded bundle and is therefore attacker-chosen: anyone could pack a
    .bmz claiming someone else's campaign and, if that were enough, redirect their
    readers to content of their choosing. The revoke token is the one secret that
    means "I own this share", and it is already separate from the viewing password
    so handing someone the password never lets them do this.

    The old share is left entirely intact -- same URL, same password, same
    content. It only gains a pointer, because a link given to a collaborator
    months ago should not break because the campaign grew.

    Returns "" on success, or a short reason why not.
    """
    manifest = _manifest(runs_root, token)
    if manifest is None:
        return "that share does not exist"
    presented = hashlib.sha256((revoke_token or "").encode("utf-8")).hexdigest()
    if not hmac.compare_digest(presented, manifest.get("revoke_hash", "")):
        return "that revoke link does not match this share"
    if not TOKEN_RE.match(new_token or ""):
        return "the newer share's link is not a valid one"
    if new_token == token:
        return "a share cannot supersede itself"
    target = _manifest(runs_root, new_token)
    if target is None:
        return "the newer share does not exist on this server"
    # One hop only. Chains are how a reader ends up following four redirects to
    # find the current version, and a cycle is how they never arrive at all.
    if target.get("superseded_by"):
        return "the newer share has itself been superseded -- point at the newest one"

    manifest["superseded_by"] = new_token
    path = _dir(runs_root, token)
    (path / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ""


def newest(runs_root: Path, token: str, hops: int = 8) -> str:
    """Follow the supersede pointers to the current share.

    Resolved when the page is rendered rather than rewritten when a share is
    superseded, because a campaign extended three times otherwise leaves the first
    reader following three redirects to arrive. A bounded hop count and a seen-set
    because a cycle is a mistake somebody will eventually make, and an infinite
    redirect is a worse answer than a slightly stale one.
    """
    seen = {token}
    current = token
    for _ in range(hops):
        manifest = _manifest(runs_root, current)
        if manifest is None:
            return current
        nxt = manifest.get("superseded_by") or ""
        if not nxt or nxt in seen or _manifest(runs_root, nxt) is None:
            return current
        seen.add(nxt)
        current = nxt
    return current


def revoke(runs_root: Path, token: str, revoke_token: str) -> bool:
    manifest = _manifest(runs_root, token)
    if manifest is None:
        return False
    presented = hashlib.sha256((revoke_token or "").encode("utf-8")).hexdigest()
    if not hmac.compare_digest(presented, manifest.get("revoke_hash", "")):
        return False
    return delete(runs_root, token)


def delete(runs_root: Path, token: str) -> bool:
    path = _dir(runs_root, token)
    if path is None or not path.is_dir():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def forget_for_run(runs_root: Path, run_key: str) -> list[str]:
    """Delete every share made from one campaign.

    Scoped to the campaign rather than wiping the whole shares directory: the
    Destroy button promises to remove everything held *for this campaign*, and
    taking another campaign's shares with it would make that promise false.
    """
    if not run_key:
        return []
    removed = []
    for token in list_tokens(runs_root):
        manifest = _manifest(runs_root, token)
        if manifest and manifest.get("run_key") == run_key and delete(runs_root, token):
            removed.append(token)
    return removed
