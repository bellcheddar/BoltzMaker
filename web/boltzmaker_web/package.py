"""The campaign as a directory of files that works on any web server.

What comes out is a zip holding one page, the three libraries it needs, and the
campaign's own data -- no Python, no server, nothing fetched from anywhere. Drop
it in a web root and it is the same explorer.

A zip rather than one giant HTML. "Self-contained" is the requirement and a
single file satisfies it too, but Mol* alone is 5MB and base64 costs a third
again on top of every structure: a fifteen-target campaign came to something no
browser should be asked to parse in one go. A directory of files is what a web
server is for, and every path in it is relative, so it works from a subdirectory
as happily as from a root.

It is NOT loadable from a file:// URL, and says so in its own README: the page
fetches its data, and a browser refuses cross-origin reads from file://. That is
a browser rule, not something this can work around by trying harder.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

#: Everything the page needs, by where it goes in the zip. The libraries are the
#: same files this site serves, so there is one copy of each in the repo.
_ASSETS = (
    ("static/css/brand.css", "assets/brand.css"),
    ("static/js/explorer.js", "assets/explorer.js"),
    ("static/js/viewer.js", "assets/viewer.js"),
    ("static/vendor/molstar-4.9.0.js", "assets/molstar.js"),
    ("static/vendor/molstar-4.9.0.css", "assets/molstar.css"),
)

README = """\
{campaign} -- BoltzMaker analysis

Open index.html through a web server, not by double-clicking it.

    python3 -m http.server 8000

then visit http://localhost:8000/. Or copy this whole directory into a web
root and visit it there; every path inside is relative, so a subdirectory
works as well as a root.

Double-clicking index.html will not work, and cannot be made to: the page
reads its data from the files in data/, and a browser refuses to read
alongside files from a file:// page. That is a rule in the browser rather
than something this package can arrange around.

What is here
    index.html      the explorer, with this campaign's summary already in it
    assets/         Mol*, Plotly and this site's own page code
    data/           structures, sequences, interaction images and the
                    superposition this campaign computed

The AlphaFold overlay is the one thing that does not work in this copy: it
resolves an accession against UniProt and AlphaFold at the moment you press
it, which needs the server that built the campaign.
"""


def _read(path: Path) -> bytes:
    return path.read_bytes()


def build(session: Path, web_root: Path, repo_root: Path, loaded, payload: str,
          panels_html: str, charts: str, ligand_cards: str) -> bytes:
    """The zip, as bytes.

    Assembled in memory: the largest campaign seen is a few tens of megabytes and
    holding it beats writing a temporary tree that then has to be cleaned up on
    every path out of the request, including the ones that raise.
    """
    campaign = loaded.campaign_name or "campaign"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", README.format(campaign=campaign))
        zf.writestr("index.html", _page(campaign, payload, panels_html, charts,
                                        ligand_cards))

        for source, destination in _ASSETS:
            path = web_root / source
            if path.is_file():
                zf.writestr(destination, _read(path))
        plotly = repo_root / "vendor" / "plotly-2.35.2.min.js"
        if plotly.is_file():
            zf.writestr("assets/plotly.js", _read(plotly))

        campaign_dir = session / "campaign"
        for target in loaded.targets:
            structure = campaign_dir / "structures" / f"{target.target_id}.cif"
            if structure.is_file():
                zf.writestr(f"data/structures/{target.target_id}.cif", _read(structure))
            image = campaign_dir / "plip" / f"{target.target_id}.png"
            if image.is_file():
                zf.writestr(f"data/plip/{target.target_id}.png", _read(image))
            for name, destination in (
                (f"sequence-{target.target_id}.json", f"data/sequence/{target.target_id}.json"),
                (f"pocket-{target.target_id}.cif", f"data/pocket/{target.target_id}.cif"),
                (f"overlay-ca-{target.target_id}.cif", f"data/overlay/ca-{target.target_id}.cif"),
                (f"overlay-lig-{target.target_id}.cif", f"data/overlay/lig-{target.target_id}.cif"),
            ):
                path = session / name
                if path.is_file():
                    zf.writestr(destination, _read(path))

        overlay = session / "overlay.json"
        if overlay.is_file():
            zf.writestr("data/overlay.json", _read(overlay))

        # The ligand-pose pairs come straight out of the campaign rather than from a
        # session cache: nothing on the server computed them, BoltzMaker measured them
        # on the machine that ran the prediction and shipped them in the .bmz.
        pose_index = campaign_dir / "posepairs" / "index.json"
        if pose_index.is_file():
            zf.writestr("data/pose-pairs.json", _read(pose_index))
            for pair in loaded.pose_pairs:
                for which in ("pred", "ref"):
                    path = campaign_dir / "posepairs" / f"{pair.get('stem')}_{which}.cif"
                    if path.is_file():
                        zf.writestr(f"data/pose-pair/{which}-{pair['stem']}.cif",
                                    _read(path))

        # The campaign's own files, so the package is an archive as well as a
        # viewer: someone given only this can still read the numbers.
        for name in ("boltz_summary.csv", "boltz_interactions.csv",
                     "boltz_sse_comparison.csv"):
            path = campaign_dir / "summary" / name
            if path.is_file():
                zf.writestr(f"data/summary/{name}", _read(path))
        spec = campaign_dir / "boltz_input.md"
        if spec.is_file():
            zf.writestr("data/boltz_input.md", _read(spec))
    return buffer.getvalue()


def _page(campaign: str, payload: str, panels_html: str, charts: str,
          ligand_cards: str) -> str:
    """index.html: the explorer's markup with the campaign's data already in it.

    The panels are rendered by the server into this string rather than fetched,
    so the page needs no template engine and no request to draw itself.
    """
    return PAGE.format(
        campaign=_escape(campaign),
        panels=panels_html,
        payload=payload,
        charts=charts,
        ligands=ligand_cards,
    )


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{campaign} &middot; BoltzMaker</title>
<link rel="stylesheet" href="assets/brand.css">
<link rel="stylesheet" href="assets/molstar.css">
</head>
<body>
<header class="md-header">
  <div class="md-header-inner">
    <div class="md-header-brand">
      <a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">
        <span class="md-logo-dot"></span><span>Marc C. Deller, D.Phil.</span></a>
    </div>
    <div class="md-header-title"><h1>BoltzMaker</h1></div>
    <nav class="md-header-nav">
      <a href="https://boltzmaker.mdeller.com" target="_blank" rel="noopener noreferrer">
        boltzmaker.mdeller.com</a>
    </nav>
  </div>
</header>
<main class="md-main">
{panels}
</main>
<footer class="md-footer">
  Built with BoltzMaker by
  <a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">Marc C. Deller, D.Phil.</a>
  &middot; <a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a>
</footer>
<script id="results-payload" type="application/json">{payload}</script>
<script id="ligand-cards" type="application/json">{ligands}</script>
<script src="assets/plotly.js"></script>
<script src="assets/molstar.js"></script>
<script src="assets/viewer.js"></script>
<script src="assets/explorer.js"></script>
<script id="report-charts" type="application/json">{charts}</script>
<script>
  // No token: the explorer reads from the files beside this page instead of
  // from a session on a server.
  BoltzExplorer.init("");
  BoltzExplorer.plotReportCharts(JSON.parse(
    document.getElementById("report-charts").textContent));
</script>
</body>
</html>
"""
