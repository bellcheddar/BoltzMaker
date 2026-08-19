/* Analysis explorer for Fully Automated Mode.
 *
 * Everything here reads one JSON payload that the server already parsed out of
 * the .bmz -- there is no second fetch for data, only for the per-target
 * structure and interaction image, which are fetched lazily because a campaign
 * can carry dozens of multi-megabyte CIFs and almost nobody opens all of them.
 *
 * The one piece of real domain care in here: nothing recomputes BoltzMaker's
 * flags. They come from the summary as-is, and the plot deliberately draws only
 * the confidence cutoff, which is a genuine absolute threshold (0.5), and never
 * a horizontal affinity line -- the affinity mismatch flags are within-campaign
 * terciles, so a line implying an absolute cutoff would be a claim the data does
 * not support.
 */
var BoltzExplorer = (function () {
  "use strict";

  var data = null;
  var token = null;
  // Every report chart is drawn at this height, so the panels line up as a set.
  // One height for every report chart. Tall enough that a rotated axis label fits
  // inside it: the alternative, clipping the panel, removed the labels instead of
  // containing them.
  // One margin for every chart. b holds a rotated, shortened category label; l
  // holds a y title plus tick labels, including a heatmap's row names; r holds a
  // legend or colourbar. Every plot area is then the same box.
  //
  // The narrow set exists because the wide one is most of a phone: 120 + 170 of
  // a 330px panel left about 40px of plot, which is what the charts on an iPhone
  // were. Nothing can sit beside a plot at this width, so the legend goes above
  // it and the colourbar below, and the margins shrink to what the tick labels
  // alone need.
  var NARROW = 768;
  var CHART_WIDE = { height: 420, margin: { t: 20, b: 110, l: 120, r: 170 } };
  var CHART_NARROW = { height: 460, margin: { t: 64, b: 150, l: 46, r: 14 } };
  function isNarrow() { return window.innerWidth <= NARROW; }

  //: A chart in a two-column grid is half a page wide even on a desktop, and the
  //: wide margins are most of it: a fingerprint in a 530px cell came out 157px
  //: square, having reserved 120 for row names and 250 for a two-word legend. The
  //: margins follow the CHART's width rather than the window's.
  var NARROW_CHART = 620;

  function chartMetrics(host) {
    var width = host && host.offsetWidth ? host.offsetWidth : window.innerWidth;
    return (isNarrow() || width <= NARROW_CHART) ? CHART_NARROW : CHART_WIDE;
  }
  var viewers = { pose: { promise: null, wrapper: null },
                  contacts: { promise: null, wrapper: null },
                  ligands: { promise: null, wrapper: null },
                  traces: { promise: null, wrapper: null },
                  pockets: { promise: null, wrapper: null } };
  var sequence = null;      // the open target's track, logo and chain map
  var ligandCards = {};     // ligand id -> the report's own depiction
  var extraSpecs = [];      // charts this page builds rather than replays
  var fingerprintMax = 1;   // one colour scale across every fingerprint
  var current = null;
  var sortKey = "confidence";
  var sortDir = -1;

  // Flag -> colour. Unflagged targets stay neutral so the flagged ones carry the
  // only strong colour on the plot.
  var FLAG_COLOURS = {
    MISSING_OUTPUTS: "#d81b8c",
    LOW_CONFIDENCE: "#fcb900",
    HIGH_CONFIDENCE_POOR_AFFINITY: "#ff6900",
    LOW_CONFIDENCE_STRONG_AFFINITY: "#9b51e0",
    LOW_POCKET_PLDDT: "#4a9fd4"
  };
  var NEUTRAL = "#1e73be";

  function hasWebGL() {
    try {
      var canvas = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
                (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
    } catch (err) {
      return false;
    }
  }

  function fmt(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function primaryFlag(target) {
    for (var i = 0; i < target.flags.length; i++) {
      if (FLAG_COLOURS[target.flags[i]]) return target.flags[i];
    }
    return null;
  }

  function colourFor(target) {
    var flag = primaryFlag(target);
    return flag ? FLAG_COLOURS[flag] : NEUTRAL;
  }

  // ---- filtering and sorting ---------------------------------------------

  function visibleTargets() {
    var text = (document.getElementById("filter-text").value || "").toLowerCase().trim();
    var family = document.getElementById("filter-protein").value;
    var flaggedOnly = document.getElementById("filter-flagged").checked;

    return data.targets.filter(function (t) {
      if (family && t.family !== family) return false;
      if (flaggedOnly && !t.flags.length) return false;
      if (text) {
        var haystack = (t.id + " " + t.name + " " + t.ligand + " " + t.family + " " + t.group).toLowerCase();
        if (haystack.indexOf(text) === -1) return false;
      }
      return true;
    }).sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      // Missing values sort to the bottom in both directions: a target with no
      // affinity prediction is not "the weakest binder", it is unmeasured, and
      // letting it head the ascending sort would read as the former.
      var xMissing = (x === null || x === undefined || x === "");
      var yMissing = (y === null || y === undefined || y === "");
      if (xMissing && yMissing) return 0;
      if (xMissing) return 1;
      if (yMissing) return -1;
      if (typeof x === "string") return x.localeCompare(y) * sortDir;
      return (x - y) * sortDir;
    });
  }

  function renderTable() {
    var rows = visibleTargets();
    var tbody = document.querySelector("#target-table tbody");
    tbody.innerHTML = "";

    rows.forEach(function (t) {
      var tr = document.createElement("tr");
      tr.className = "md-row" + (current === t.id ? " md-row-active" : "");
      tr.addEventListener("click", function () { select(t.id); });

      function cell(text, cls) {
        var td = document.createElement("td");
        td.textContent = text;
        if (cls) td.className = cls;
        tr.appendChild(td);
        return td;
      }

      cell(t.name || t.id);
      cell(t.family || "—");
      cell(t.ligand || "—");
      cell(fmt(t.confidence, 2), "num");
      cell(t.pic50 === null ? "—" : fmt(t.pic50, 2), "num");
      cell(t.plip_total ? String(t.plip_total) : "—", "num");

      var flagCell = document.createElement("td");
      t.flags.forEach(function (flag) {
        var pill = document.createElement("span");
        pill.className = "md-flag";
        pill.style.background = FLAG_COLOURS[flag] || "#6b7c93";
        pill.textContent = flag.replace(/_/g, " ").toLowerCase();
        pill.title = data.flag_notes[flag] || flag;
        flagCell.appendChild(pill);
      });
      if (!t.flags.length) flagCell.textContent = "—";
      tr.appendChild(flagCell);

      tbody.appendChild(tr);
    });

    document.getElementById("empty-note").style.display = rows.length ? "none" : "";
    document.getElementById("stat-shown").textContent = rows.length;
    document.getElementById("stat-flagged").textContent =
      data.targets.filter(function (t) { return t.flags.length; }).length;
    document.getElementById("stat-structures").textContent =
      data.targets.filter(function (t) { return t.structure; }).length;
  }

  // ---- the report's scatter, made clickable ---------------------------------

  function targetByDisplayName(name) {
    // The report labels its points with the display name ("HTR2A_GNAI1+GNB1+GNG2_8NU"),
    // while everything here is keyed by target id ("HTR2A_8NU"). Match on the
    // display name first, then fall back to the id for a report that used it.
    var match = data.targets.filter(function (t) { return t.name === name; })[0];
    return match || data.targets.filter(function (t) { return t.id === name; })[0];
  }

  function wireScatterClicks(host) {
    if (!host || !host.on) return;
    host.on("plotly_click", function (ev) {
      if (!ev.points || !ev.points.length) return;
      var point = ev.points[0];
      var label = point.text || (point.data && point.data.text && point.data.text[point.pointIndex]);
      var target = label && targetByDisplayName(String(label));
      if (target) select(target.id);
    });
  }

  // ---- per-target detail --------------------------------------------------

  function metricRows(t) {
    return [
      ["Confidence score", fmt(t.confidence, 3)],
      ["pTM", fmt(t.ptm, 3)],
      ["ipTM", fmt(t.iptm, 3)],
      ["Complex pLDDT", fmt(t.plddt, 3)],
      ["Predicted affinity value", fmt(t.affinity, 3)],
      ["pIC50", t.pic50 === null ? "—" :
        fmt(t.pic50, 2) + (t.pic50_std === null ? "" : " ± " + fmt(t.pic50_std, 2))],
      // Named for what it is. compare-sse measures per motif, so this is an
      // aggregate over the regions it could align, not a whole-chain
      // superposition -- and a row called plainly "RMSD to apo" would be read as
      // the latter.
      ["C\u03b1 RMSD to apo", t.apo_rmsd
        ? t.apo_rmsd.rmsd.toFixed(2) + " \u00c5 (over " + t.apo_rmsd.motifs + " motifs)"
        : "\u2014"],
      ["Ligand", t.ligand || "—"],
      ["Role", t.role || "—"],
      ["SMILES", t.smiles || "—"]
    ];
  }

  function renderDetail(t) {
    var picker = document.getElementById("detail-target");
    if (picker.value !== t.id) picker.value = t.id;

    var metrics = document.getElementById("detail-metrics");
    metrics.innerHTML = "";
    metricRows(t).forEach(function (pair) {
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.textContent = pair[0];
      th.style.width = "45%";
      var td = document.createElement("td");
      td.textContent = pair[1];
      // SMILES can be long enough to force the whole table wide otherwise.
      if (pair[0] === "SMILES") td.style.wordBreak = "break-all";
      tr.appendChild(th); tr.appendChild(td);
      metrics.appendChild(tr);
    });

    renderLigandCard(t);
    renderInteractions(t);

    // The sequence track, the conservation logo and the chain-letter mapping all
    // come from one request, which is also what the interaction pane needs to
    // know which chain the ligand is -- so the structures are loaded after it
    // rather than in parallel with it.
    sequence = null;
    document.getElementById("af-ask").hidden = true;
    renderSequence(t, null);
    fetch(sources.sequence(t.id))
      .then(function (response) { return response.ok ? response.json() : null; })
      .catch(function () { return null; })
      .then(function (payload) {
        if (current !== t.id) return;       // a faster click already moved on
        sequence = payload;
        renderSequence(t, payload);
        loadStructures(t);
      });
  }


  function renderLigandCard(t) {
    var host = document.getElementById("detail-ligand");
    host.innerHTML = "";
    var cell = ligandCards[t.ligand];
    if (!cell) {
      // An apo target genuinely has no ligand, which is not the same as a
      // depiction having failed to come across.
      var note = document.createElement("p");
      note.className = "md-hint";
      note.style.margin = "10px 0 0";
      note.textContent = t.ligand
        ? "No depiction was included for " + t.ligand + "."
        : "This target has no ligand.";
      host.appendChild(note);
      return;
    }
    var wrap = document.createElement("div");
    wrap.className = "lig-page md-detail-lig-page";
    wrap.innerHTML = cell;
    host.appendChild(wrap);
  }

  //: What each PLIP interaction is, in one line, because the type names alone
  //: ("pi stacks") say what was measured and not why it matters.
  var INTERACTION_NOTES = {
    "hydrophobic": "greasy contact, no charge or hydrogen involved",
    "hydrogen bonds": "a donor and an acceptor sharing a hydrogen",
    "salt bridges": "opposite charges within reach of each other",
    "pi stacks": "two aromatic rings face to face or edge to face",
    "halogen bonds": "a halogen acting as an electron acceptor",
    "water bridges": "linked through a bridging water",
    "pi-cation": "an aromatic ring against a positive charge",
  };

  function renderInteractions(t) {
    var host = document.getElementById("detail-plip");
    host.innerHTML = "";
    var rows = t.interactions || [];
    if (!rows.length) {
      var none = document.createElement("p");
      none.className = "md-hint";
      none.textContent = t.plip_status && t.plip_status !== "ok"
        ? "PLIP did not run for this target (" + t.plip_status + ")."
        : (t.ligand ? "No protein-ligand interactions were detected for this target."
                    : "This target has no ligand, so there are no interactions to detect.");
      host.appendChild(none);
      return;
    }

    // Grouped by type and ordered by how many there are, so the interaction that
    // dominates the pocket is the one read first.
    var groups = {};
    rows.forEach(function (row) { (groups[row.type] = groups[row.type] || []).push(row); });
    var kinds = Object.keys(groups).sort(function (a, b) {
      return groups[b].length - groups[a].length || a.localeCompare(b);
    });

    kinds.forEach(function (kind) {
      var block = document.createElement("div");
      block.className = "md-plip-group";

      var heading = document.createElement("h4");
      heading.className = "md-plip-kind";
      heading.innerHTML = '<span class="md-plip-count">' + groups[kind].length + "</span> " + kind;
      block.appendChild(heading);

      if (INTERACTION_NOTES[kind]) {
        var note = document.createElement("p");
        note.className = "md-plip-note";
        note.textContent = INTERACTION_NOTES[kind];
        block.appendChild(note);
      }

      groups[kind].sort(function (a, b) { return (a.resnr || 0) - (b.resnr || 0); });
      groups[kind].forEach(function (row) {
        block.appendChild(interactionRow(row));
      });
      host.appendChild(block);
    });
  }

  function interactionRow(row) {
    var item = document.createElement("div");
    item.className = "md-plip-row";
    item.setAttribute("data-chain", row.chain || "");
    item.setAttribute("data-resnr", row.resnr === null ? "" : row.resnr);

    var name = document.createElement("span");
    name.className = "md-plip-res";
    name.textContent = (row.restype || "?") + (row.resnr === null ? "" : row.resnr);
    item.appendChild(name);

    var chain = document.createElement("span");
    chain.className = "md-plip-chain";
    chain.textContent = "chain " + (row.chain || "?");
    item.appendChild(chain);

    if (row.distance !== null && row.distance !== undefined) {
      var distance = document.createElement("span");
      distance.className = "md-plip-dist";
      distance.textContent = row.distance.toFixed(2) + " \u00c5";
      item.appendChild(distance);
    }

    if (row.geometry && row.geometry.length) {
      var geometry = document.createElement("div");
      geometry.className = "md-plip-geom";
      row.geometry.forEach(function (field) {
        var span = document.createElement("span");
        span.innerHTML = '<i>' + field.label + "</i> " + field.value +
                         (field.unit ? " " + field.unit : "");
        geometry.appendChild(span);
      });
      item.appendChild(geometry);
    }

    // The row, the sequence track and the pose are three views of one residue.
    if (row.resnr !== null && row.resnr !== undefined) {
      item.addEventListener("click", function () { focusResidue(row.chain, row.resnr); });
      item.addEventListener("mouseenter", function () { highlightResidue(row.chain, row.resnr); });
      item.addEventListener("mouseleave", clearResidueHighlight);
      item.classList.add("md-plip-clickable");
    }
    return item;
  }

  function chainIdFor(letter) {
    var chains = (sequence && sequence.chains) || [];
    for (var i = 0; i < chains.length; i++) {
      if (chains[i].letter === letter) return chains[i].id;
    }
    return letter;
  }

  function focusResidue(chainLetter, resnr) {
    var chain = chainIdFor(chainLetter);
    ["pose", "contacts"].forEach(function (which) {
      var wrapper = viewers[which].wrapper;
      if (wrapper) wrapper.focusResidue(chain, resnr);
    });
    drawSequence(resnr);
  }

  function highlightResidue(chainLetter, resnr) {
    var chain = chainIdFor(chainLetter);
    ["pose", "contacts"].forEach(function (which) {
      var wrapper = viewers[which].wrapper;
      if (wrapper) wrapper.highlightResidue(chain, resnr);
    });
  }

  function clearResidueHighlight() {
    ["pose", "contacts"].forEach(function (which) {
      var wrapper = viewers[which].wrapper;
      if (wrapper) wrapper.clearHighlight();
    });
  }


  /* Two panes, one library. Creating a Mol* viewer is async and costs a WebGL
     context, so each pane's viewer is created once and reused for every target
     rather than rebuilt on each selection. */
  var VIEWER_HOSTS = {
    pose: "viewer", contacts: "viewer-contacts",
    ligands: "viewer-ligands", traces: "viewer-traces",
    pockets: "viewer-pockets",
  };

  function ensureViewer(which) {
    var slot = viewers[which];
    if (slot.promise) return slot.promise;
    var host = document.getElementById(VIEWER_HOSTS[which]);
    slot.promise = BoltzViewer.create(host).then(function (wrapper) {
      slot.wrapper = wrapper;
      return wrapper;
    });
    return slot.promise;
  }

  function noteFor(which) {
    return document.getElementById(which === "pose" ? "viewer-note" : "contacts-note");
  }

  function loadStructures(t) {
    ["pose", "contacts"].forEach(function (which) {
      var note = noteFor(which);
      if (!t.structure) {
        note.textContent = "No structure was included for this target.";
        return;
      }
      if (!BoltzViewer.available()) {
        note.textContent = BoltzViewer.reason();
        return;
      }
      note.textContent = "Loading structure\u2026";
      ensureViewer(which)
        .then(function (wrapper) {
          return wrapper.load(sources.structure(t.id));
        })
        .then(function (wrapper) {
          if (current !== t.id) return;      // a faster click already moved on
          if (which === "pose") {
            note.textContent = "Drag to rotate, scroll to zoom. Coloured by chain.";
            return;
          }
          // The interaction pane opens on the pocket and turns, which is the
          // whole reason it is a viewer and not the flat diagram it replaced.
          var ligand = (sequence && sequence.chains || []).filter(function (c) {
            return c.kind === "ligand";
          })[0];
          var contacts = contactResidues(t);
          // The pocket as its own small structure, so the residues can be
          // sticks: a representation needs a component, and this Mol* build
          // cannot build one from a selection. Same coordinates as the full
          // structure, so it lands exactly where those residues already are.
          //
          // Loaded BEFORE the framing, not after. Loading a structure resets the
          // camera to fit everything, so doing it last threw away the framing and
          // left the pane showing the whole complex from across the room.
          var ligandId = ligand ? ligand.id : "";
          return wrapper
            .loadExtra("pocket", sources.pocket(t.id), { type: "ball-and-stick" })
            .catch(function () { /* the cartoon alone is still usable */ })
            .then(function () {
              if (current !== t.id) return;
              var framed = wrapper.focusContacts(ligandId, contacts);
              var drawn = wrapper.showInteractions(ligandId, contacts);
              wrapper.setSpin(true);
              note.textContent = !framed
                ? "No contacts to frame, so the whole complex is shown."
                : contacts.length + " contacting residue"
                  + (contacts.length === 1 ? "" : "s") + " and the ligand as sticks"
                  + (drawn ? ", with " + drawn + " contact" + (drawn === 1 ? "" : "s")
                             + " drawn and measured." : ".");
            });
        })
        .catch(function (err) {
          // Not every thrown value is an Error: a rejected load can be a bare
          // string or an event, and "Could not load: undefined" helps nobody.
          var reason = (err && err.message) || (typeof err === "string" ? err : "") ||
                       "the viewer could not render this structure";
          note.textContent = "Could not load the structure: " + reason;
        });
    });
  }

  /* PLIP's contacts as {chain, resnr} against the CIF's own chain names. PLIP
     says "chain A" because it reads a PDB conversion where chains are lettered
     in order; the sequence payload carries that mapping. Without it the letters
     are passed through, which is right for any structure whose chains really
     are called A, B, C. */
  function contactResidues(t) {
    var byLetter = {};
    ((sequence && sequence.chains) || []).forEach(function (c) { byLetter[c.letter] = c.id; });
    var seen = {};
    var out = [];
    (t.interactions || []).forEach(function (row) {
      if (row.resnr === null || row.resnr === undefined) return;
      var chain = byLetter[row.chain] || row.chain;
      var key = chain + ":" + row.resnr;
      if (seen[key]) return;
      seen[key] = true;
      out.push({ chain: chain, resnr: row.resnr, restype: row.restype });
    });
    return out;
  }

  function applyStyle(which, mode) {
    var wrapper = viewers[which].wrapper;
    if (!wrapper) return;
    if (mode === "alphafold") {
      toggleAlphaFold(which);
      return;
    }
    if (mode === "reset") {
      // Back to the framing the pane opened with, which is not the same in the
      // two panes: the pose opened on the whole complex, the interaction pane on
      // the pocket. Resetting both to "everything" would throw away the second
      // pane's entire reason for being.
      if (which === "contacts") {
        var target = data.targets.filter(function (x) { return x.id === current; })[0];
        var ligand = ((sequence && sequence.chains) || []).filter(function (c) {
          return c.kind === "ligand";
        })[0];
        if (target && wrapper.focusContacts(ligand ? ligand.id : "", contactResidues(target))) return;
      }
      wrapper.resetCamera();
      return;
    }
    wrapper.setStyle(mode);
  }





  /* The height of the sticky header, published to CSS so a panel scrolled to can
     leave room for it. Measured rather than assumed: the nav wraps to a second
     row on a narrow screen, which makes the bar half as tall again. */
  function trackHeaderHeight() {
    var header = document.querySelector(".md-header");
    if (!header) return;
    var publish = function () {
      document.documentElement.style.setProperty(
        "--md-header-height", header.offsetHeight + "px");
    };
    publish();
    window.addEventListener("resize", publish);
  }


  /* Where the data comes from.

     Served by this app it is /auto/analysis/<token>/…; unpacked from the
     downloadable package it is a directory of files sitting next to the page.
     Everything that fetches goes through here, so the second case needs no
     second copy of the explorer -- the package writes one line of config and the
     same code reads it. */
  var sources = null;

  function serverSources(sessionToken) {
    var base = "/auto/analysis/" + sessionToken + "/";
    return {
      sequence: function (id) { return base + "sequence/" + encodeURIComponent(id) + ".json"; },
      structure: function (id) { return base + "structure/" + encodeURIComponent(id); },
      pocket: function (id) { return base + "pocket/" + encodeURIComponent(id) + ".cif"; },
      overlayIndex: function () { return base + "overlay.json"; },
      overlay: function (kind, id) {
        return base + "overlay/" + kind + "/" + encodeURIComponent(id) + ".cif";
      },
      image: function (id) { return base + "image/" + encodeURIComponent(id); },
      alphafoldInfo: function (id, accession) {
        return base + "alphafold/" + encodeURIComponent(id) + ".json"
               + (accession ? "?accession=" + encodeURIComponent(accession) : "");
      },
      alphafold: function (id, accession) {
        return base + "alphafold/" + encodeURIComponent(id) + "/"
               + encodeURIComponent(accession) + ".cif";
      },
      // The package is a set of files, not a server: an accession it has no file
      // for cannot be fetched on demand.
      live: true,
    };
  }

  function fileSources() {
    return {
      sequence: function (id) { return "data/sequence/" + encodeURIComponent(id) + ".json"; },
      structure: function (id) { return "data/structures/" + encodeURIComponent(id) + ".cif"; },
      pocket: function (id) { return "data/pocket/" + encodeURIComponent(id) + ".cif"; },
      overlayIndex: function () { return "data/overlay.json"; },
      overlay: function (kind, id) {
        return "data/overlay/" + kind + "-" + encodeURIComponent(id) + ".cif";
      },
      image: function (id) { return "data/plip/" + encodeURIComponent(id) + ".png"; },
      alphafoldInfo: function () { return ""; },
      alphafold: function () { return ""; },
      live: false,
    };
  }


  /* The destroy button.

     Typed confirmation rather than a dialog: this removes the only copy on the
     server and there is nothing here that can undo it, so the cost of pressing
     it by accident should not be one careless click. The request is a POST for
     the same reason -- a prefetching browser or a link-scanning mail client
     following a GET would delete somebody's campaign on their behalf. */
  function wireDestroy() {
    var button = document.getElementById("destroy-all");
    if (!button || !token) return;
    var note = document.getElementById("destroy-note");
    button.addEventListener("click", function () {
      var typed = window.prompt(
        "This removes the campaign from the server and cannot be undone.\n\n" +
        "Type DESTROY to confirm.");
      if ((typed || "").trim().toUpperCase() !== "DESTROY") {
        if (note) note.textContent = "Nothing was removed.";
        return;
      }
      button.disabled = true;
      if (note) note.textContent = "Removing\u2026";
      fetch("/auto/analysis/" + token + "/destroy", { method: "POST" })
        .then(function (response) { return response.json(); })
        .then(function (result) {
          if (note) {
            note.textContent = result.status === "destroyed"
              ? "Removed. This page is now the only copy -- nothing about this "
                + "campaign is left on the server."
              : "There was nothing left to remove.";
          }
          document.body.classList.add("md-destroyed");
        })
        .catch(function () {
          button.disabled = false;
          if (note) note.textContent = "The request failed; nothing was removed.";
        });
    });
  }

  // ---- the two campaign-wide overlay panes --------------------------------

  //: Enough colours to tell fifteen targets apart, and none of them the ligand
  //: red the per-target viewers use for their own ligand.
  var OVERLAY_COLOURS = [
    0x1e73be, 0x00875a, 0xb07d00, 0x9b51e0, 0x0f9ba8, 0xc45500, 0x4a9fd4,
    0x00b578, 0x8a6100, 0x6a3fb5, 0x2f6f9f, 0x7a9a01, 0xcf6679, 0x3d8361, 0x8d6e63,
  ];

  function overlayColour(index) {
    return OVERLAY_COLOURS[index % OVERLAY_COLOURS.length];
  }

  function hexOf(value) {
    return "#" + ("000000" + value.toString(16)).slice(-6);
  }

  /* Both panes draw the same fifteen structures from one superposition, so the
     listing is fetched once and each pane loads only the files it draws: the
     ligand pane the ligands, the trace pane the CA. */
  function loadOverlays() {
    if (!BoltzViewer.available()) {
      ["ligands", "traces"].forEach(function (which) {
        document.getElementById(which + "-note").textContent = BoltzViewer.reason();
      });
      return;
    }
    fetch(sources.overlayIndex())
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        if (!payload || !payload.targets || !payload.targets.length) throw new Error("none");
        overlayPane("ligands", payload, function (row) { return row.has_ligand; },
                    "lig", { type: "ball-and-stick" });
        overlayPane("traces", payload, function () { return true; },
                    "ca", { type: "backbone" });
        pocketsPane(payload);
      })
      .catch(function () {
        ["ligands", "traces"].forEach(function (which) {
          document.getElementById(which + "-note").textContent =
            "The superposition could not be computed for this campaign.";
        });
      });
  }

  function overlayPane(which, payload, include, kind, options) {
    var rows = payload.targets.filter(include);
    var note = document.getElementById(which + "-note");
    var list = document.getElementById(which + "-list");
    list.innerHTML = "";
    if (!rows.length) {
      note.textContent = which === "ligands"
        ? "No target in this campaign has a ligand."
        : "Nothing could be superposed.";
      return;
    }
    var reference = payload.reference;
    note.textContent = which === "ligands"
      ? rows.length + " ligands, in the frame of " + reference + "."
      : rows.length + " targets on " + reference + ", over the "
        + (payload.shared || 0) + " residues most of them agree on. "
        + "Every trace is that same region, so the RMSDs compare like with like.";

    rows.forEach(function (row, index) {
      var colour = overlayColour(index);
      var label = document.createElement("label");
      label.className = "md-overlay-row";

      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = true;
      label.appendChild(box);

      var swatch = document.createElement("span");
      swatch.className = "md-overlay-swatch";
      swatch.style.background = hexOf(colour);
      label.appendChild(swatch);

      var name = document.createElement("span");
      name.className = "md-overlay-name";
      // The target's name in both panes, not the ligand's. Several targets share
      // a ligand -- RISP is bound to 5HT2A with and without its G protein -- so a
      // list of ligand ids read as "RISP, PSIL, RISP" with no way to tell which
      // row was which.
      name.textContent = row.name;
      name.title = row.name;
      label.appendChild(name);

      if (which === "traces") {
        var rmsd = document.createElement("span");
        rmsd.className = "md-overlay-rmsd";
        rmsd.textContent = row.rmsd === null || row.rmsd === undefined
          ? "\u2014"
          : row.rmsd.toFixed(2) + " \u00c5";
        rmsd.title = row.rmsd === null
          ? "Too little in common with the reference to superpose."
          : "RMSD over the " + (row.shared || 0) + " residues drawn, of "
            + row.matched + " this target pairs with the reference";
        label.appendChild(rmsd);
      }

      box.addEventListener("change", function () {
        var wrapper = viewers[which].wrapper;
        if (wrapper) wrapper.setExtraVisible(row.id, box.checked);
      });
      list.appendChild(label);
    });

    ensureViewer(which).then(function (wrapper) {
      // In series, not in parallel: fifteen concurrent loads into one Mol* plugin
      // race each other through its state tree, and the structure a load returns
      // is then not always the one it just added.
      return rows.reduce(function (chain, row, index) {
        return chain.then(function () {
          var url = sources.overlay(kind, row.id);
          return wrapper.loadExtra(row.id, url, {
            color: overlayColour(index), type: options.type,
          }).catch(function () { /* one missing file is not the whole pane */ });
        });
      }, Promise.resolve()).then(function () {
        wrapper.frameAll();
      });
    });
  }

  // ---- the pockets pane ----------------------------------------------------

  //: Pocket 1 green, pocket 2 blue, then on through hues that stay apart on a
  //: grey background; the unconstrained baseline is always red, whichever
  //: position it holds, because it is the control every named pocket is read
  //: against and it should not change colour between campaigns.
  var POCKET_COLOURS = [0x00875a, 0x1e73be, 0xb07d00, 0x9b51e0, 0x0f9ba8, 0xc45500];
  var POCKET_BASELINE = 0xcf2f3c;
  //: One mid grey for every receptor. The point of this pane is where the ligands
  //: went, and colouring twelve near-identical superposed backbones would say
  //: "these differ" about the one thing that does not.
  var RECEPTOR_GREY = 0x808080;
  //: Translucent so the poses read through the backbones rather than from behind
  //: them -- a dozen superposed traces are otherwise a solid cage around exactly
  //: the thing the pane exists to show. The ligands stay fully opaque: they are
  //: the subject, and transparency on a sphere reads as uncertainty about where
  //: the atom is.
  var RECEPTOR_ALPHA = 0.3;

  function pocketColour(payload, group) {
    var order = payload.pocket_order || [];
    if (group === "Unconstrained" || group === "Unnamed pocket") return POCKET_BASELINE;
    var named = order.filter(function (g) {
      return g !== "Unconstrained" && g !== "Unnamed pocket";
    });
    var at = named.indexOf(group);
    return POCKET_COLOURS[(at < 0 ? 0 : at) % POCKET_COLOURS.length];
  }

  /* Only the targets that actually bind something: a ligand-free (apo) target has
     no pose to place, and drawing its receptor would add a backbone to the grey
     haze while contributing nothing to the question the pane asks. In the 15-target
     5-HT2 campaign that is the 12 with a ligand, and the three apo targets are
     left to the Superposed targets pane, which is about backbones. */
  //: target id -> its checkbox, so a click on the table can drive the same
  //: controls the reader can drive by hand, rather than a parallel hidden state.
  var pocketBoxes = {};
  var pocketRowSelected = null;

  function setPocketRowVisible(id, visible) {
    var wrapper = viewers.pockets.wrapper;
    if (!wrapper) return;
    wrapper.setExtraVisible("lig:" + id, visible);
    wrapper.setExtraVisible("ca:" + id, visible);
  }

  function clearPocketTableSelection() {
    if (!pocketRowSelected) return;
    pocketRowSelected.classList.remove("md-row-selected");
    pocketRowSelected = null;
  }

  function showOnlyPocketTargets(ids) {
    Object.keys(pocketBoxes).forEach(function (id) {
      var wanted = !ids || ids.indexOf(id) >= 0;
      pocketBoxes[id].checked = wanted;
      setPocketRowVisible(id, wanted);
    });
  }

  /* The table above the viewer is a summary of the same targets, one row per
     pocket and protein, so a row is already the selection a reader wants: "show me
     just orforglipron and friends in the V6G site of GLP1R". The row carries no
     ids -- it is markup the report generated and this page only sanitised -- so
     the match is made on what the row displays: its Pocket and Protein cells
     against each target's own pocket and family. */
  function wirePocketTable(rows) {
    var pane = document.querySelector(".md-pockets-pane");
    var card = pane && pane.closest(".md-card");
    var table = card && card.querySelector("table.full-table");
    if (!table || !table.tBodies.length) return;

    Array.prototype.slice.call(table.tBodies[0].rows).forEach(function (tr) {
      if (tr.cells.length < 2) return;
      var pocket = tr.cells[0].textContent.trim();
      var family = tr.cells[1].textContent.trim();
      var ids = rows.filter(function (row) {
        return row.pocket === pocket && row.family === family;
      }).map(function (row) { return row.id; });
      if (!ids.length) return;          // a row whose targets produced no structure

      tr.classList.add("md-row-clickable");
      tr.title = "Show only these " + ids.length + " structure(s)";
      tr.addEventListener("click", function () {
        if (pocketRowSelected === tr) {   // clicking the selected row shows everything
          clearPocketTableSelection();
          showOnlyPocketTargets(null);
          return;
        }
        clearPocketTableSelection();
        tr.classList.add("md-row-selected");
        pocketRowSelected = tr;
        showOnlyPocketTargets(ids);
      });
    });
  }

  function pocketsPane(payload) {
    var note = document.getElementById("pockets-note");
    var list = document.getElementById("pockets-list");
    if (!note || !list) return;               // report predates the Pockets panel
    if (!BoltzViewer.available()) { note.textContent = BoltzViewer.reason(); return; }

    var rows = payload.targets.filter(function (row) { return row.has_ligand; });
    list.innerHTML = "";
    pocketBoxes = {};
    pocketRowSelected = null;
    if (!rows.length) {
      note.textContent = "No target in this campaign has a ligand to place.";
      return;
    }
    var groups = [];
    rows.forEach(function (row) {
      if (groups.indexOf(row.pocket) < 0) groups.push(row.pocket);
    });
    note.textContent = rows.length + " ligand" + (rows.length === 1 ? "" : "s")
      + " across " + groups.length + " pocket" + (groups.length === 1 ? "" : "s")
      + ", every receptor superposed on " + payload.reference
      + " and drawn in grey. Colours match the table above, and clicking a row of it "
      + "shows only that row's structures -- click it again for all of them.";

    rows.forEach(function (row) {
      var colour = pocketColour(payload, row.pocket);
      var label = document.createElement("label");
      label.className = "md-overlay-row";

      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = true;
      label.appendChild(box);

      var swatch = document.createElement("span");
      swatch.className = "md-overlay-swatch";
      swatch.style.background = hexOf(colour);
      label.appendChild(swatch);

      var name = document.createElement("span");
      name.className = "md-overlay-name";
      name.textContent = row.name;
      name.title = row.name + " -- " + row.pocket;
      label.appendChild(name);

      var tag = document.createElement("span");
      tag.className = "md-overlay-rmsd";
      tag.textContent = row.pocket;
      tag.title = "The pocket this target was run against";
      label.appendChild(tag);

      // One checkbox hides the ligand and its receptor together: they are one
      // prediction, and leaving a backbone behind after its pose has gone
      // misreports which structures are still on screen.
      box.addEventListener("change", function () {
        setPocketRowVisible(row.id, box.checked);
        // The table highlight claims "you are looking at exactly this row". Once a
        // single checkbox has been touched that is no longer true, so it goes.
        clearPocketTableSelection();
      });
      pocketBoxes[row.id] = box;
      list.appendChild(label);
    });

    wirePocketTable(rows);

    ensureViewer("pockets").then(function (wrapper) {
      // In series for the same reason the other panes are: concurrent loads race
      // each other through Mol*'s state tree and the structure a load returns is
      // then not always the one it just added.
      return rows.reduce(function (chain, row) {
        return chain.then(function () {
          return wrapper.loadExtra("ca:" + row.id, sources.overlay("ca", row.id),
                                   { color: RECEPTOR_GREY, type: "backbone",
                                     typeParams: { alpha: RECEPTOR_ALPHA } })
            .catch(function () { /* one missing file is not the whole pane */ });
        }).then(function () {
          // Spheres, not sticks: at this scale a stick model of a dozen ligands is a
          // thicket, while space-filling shows which volume each pocket's poses
          // actually occupy -- which is the comparison being made.
          return wrapper.loadExtra("lig:" + row.id, sources.overlay("lig", row.id),
                                   { color: pocketColour(payload, row.pocket),
                                     type: "spacefill" })
            .catch(function () { /* ditto */ });
        });
      }, Promise.resolve()).then(function () {
        wrapper.frameAll();
      });
    });
  }

  // ---- the AlphaFold overlay ----------------------------------------------

  //: Per target, once resolved: the accession, how it was resolved, and the fit.
  //: Kept so the second pane does not repeat the lookup the first one just did.
  var alphaFold = {};
  var typedAccession = {};

  function toggleAlphaFold(which) {
    var wrapper = viewers[which].wrapper;
    var note = noteFor(which);
    if (!wrapper) return;
    if (wrapper.hasOverlay()) {
      wrapper.removeOverlay().then(function () { note.textContent = defaultNote(which); });
      return;
    }
    var target = current;
    if (!sources.live) {
      note.textContent = "The AlphaFold overlay needs the server that built this "
        + "campaign; this is the downloaded copy.";
      return;
    }
    note.textContent = "Looking for the AlphaFold model\u2026";
    resolveAlphaFold(target).then(function (info) {
      if (current !== target) return;
      if (!info || info.status !== "ok") {
        note.textContent = (info && info.message) || "The AlphaFold model could not be loaded.";
        // Only ask for an accession when the reason is that none was found --
        // a network failure is not something a reader can type their way out of.
        document.getElementById("af-ask").hidden =
          !(info && /No UniProt entry|not a UniProt/.test(info.message || ""));
        return;
      }
      document.getElementById("af-ask").hidden = true;
      var url = sources.alphafold(target, info.accession);
      return wrapper.addOverlay(url).then(function () {
        if (current !== target) return;
        note.textContent = info.entry + " \u00b7 " + info.source + " \u00b7 fitted on " +
          info.matched + " C\u03b1 with pLDDT \u2265 " + info.cutoff + ", " +
          info.rmsd + " \u00c5 RMSD. Press again to remove.";
      });
    }).catch(function () {
      note.textContent = "The AlphaFold model could not be loaded.";
    });
  }

  function resolveAlphaFold(target) {
    if (alphaFold[target]) return Promise.resolve(alphaFold[target]);
    var url = sources.alphafoldInfo(target, typedAccession[target]);
    return fetch(url).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (info) {
      // Only a success is remembered: a failure is usually the network, and the
      // next press should try again rather than repeat the old complaint.
      if (info && info.status === "ok") alphaFold[target] = info;
      return info;
    });
  }

  function defaultNote(which) {
    return which === "pose"
      ? "Drag to rotate, scroll to zoom. Coloured by chain."
      : "Drag to rotate, scroll to zoom.";
  }

  // ---- sequence track and conservation logo -------------------------------

  //: Coloured by the property that makes a contact make sense, so a run of
  //: greasy residues or a pair of opposite charges reads off the track itself.
  var RESIDUE_CLASS = {
    A: "hydrophobic", V: "hydrophobic", L: "hydrophobic", I: "hydrophobic",
    M: "hydrophobic", P: "hydrophobic", F: "aromatic", W: "aromatic", Y: "aromatic",
    G: "small", C: "small", S: "polar", T: "polar", N: "polar", Q: "polar",
    D: "acidic", E: "acidic", K: "basic", R: "basic", H: "basic",
  };
  /* Six hues that stay apart from each other. The first attempt was six tints of
     the same pale blue-grey, which on screen was one colour: a track that is
     coloured by property has to make the properties distinguishable, or the
     colour is decoration. Kept light enough for black letters on top. */
  var CLASS_COLOUR = {
    hydrophobic: "#f4e3c8", aromatic: "#ddd4f2", small: "#e7eaed",
    polar: "#c8e8d6", acidic: "#f8c9d1", basic: "#c9dff8", other: "#eeeeee",
  };
  var CLASS_INK = {
    hydrophobic: "#6b4a12", aromatic: "#3c2a7a", small: "#4a5561",
    polar: "#0e5c3c", acidic: "#8a1330", basic: "#12467f", other: "#5d6b7d",
  };

  var CELL = 12;              // px per residue
  var LOGO_HEIGHT = 56;
  var TRACK_HEIGHT = 22;
  var RULER_HEIGHT = 16;
  var MAX_BITS = Math.log(20) / Math.log(2);

  function residueClass(letter) { return RESIDUE_CLASS[letter] || "other"; }

  function contactsByNumber(t) {
    // Only the receptor's own contacts: a contact on a partner chain is real but
    // has no place on this track, which is one chain's sequence.
    var letter = sequence ? sequence.letter : "";
    var map = {};
    (t.interactions || []).forEach(function (row) {
      if (row.chain !== letter || row.resnr === null || row.resnr === undefined) return;
      (map[row.resnr] = map[row.resnr] || []).push(row);
    });
    return map;
  }

  function renderSequence(t, payload) {
    var title = document.getElementById("seq-title");
    var note = document.getElementById("seq-note");
    var legend = document.getElementById("seq-legend");
    var canvas = document.getElementById("seq-canvas");
    if (!payload || !payload.letters) {
      title.textContent = "Sequence";
      note.textContent = payload ? "No protein chain was found in this structure."
                                 : "Reading the sequence\u2026";
      canvas.width = 0; canvas.height = 0;
      legend.innerHTML = "";
      return;
    }
    title.textContent = "Sequence \u00b7 chain " + payload.letter + " (" + payload.receptor + ")";
    var contacts = Object.keys(contactsByNumber(t)).length;
    note.textContent = payload.letters.length + " residues"
      + (contacts ? ", " + contacts + " in contact with the ligand" : "")
      + (payload.logo && payload.logo.length
         ? ". The stack above each residue is how conserved that position is across the "
           + payload.aligned_count + " distinct proteins in this campaign, in bits."
         : ". Only one distinct protein in this campaign, so there is nothing to compare it with.")
      + " Hover for the residue, click to open it in both viewers.";

    legend.innerHTML = "";
    ["hydrophobic", "aromatic", "polar", "acidic", "basic", "small"].forEach(function (kind) {
      var item = document.createElement("span");
      item.className = "md-seq-key";
      item.innerHTML = '<i style="background:' + CLASS_COLOUR[kind] + '"></i>' + kind;
      legend.appendChild(item);
    });
    var contactKey = document.createElement("span");
    contactKey.className = "md-seq-key";
    contactKey.innerHTML = '<i class="md-seq-key-contact"></i>contacts the ligand';
    legend.appendChild(contactKey);

    drawSequence(null);
  }

  function drawSequence(focusNumber) {
    var canvas = document.getElementById("seq-canvas");
    if (!sequence || !sequence.letters) return;
    var target = data.targets.filter(function (x) { return x.id === current; })[0];
    var contacts = target ? contactsByNumber(target) : {};
    var count = sequence.letters.length;
    var hasLogo = !!(sequence.logo && sequence.logo.length);
    var logoHeight = hasLogo ? LOGO_HEIGHT : 0;
    var height = logoHeight + TRACK_HEIGHT + RULER_HEIGHT;

    // Drawn at the device's own pixel density: a canvas sized in CSS pixels is
    // resampled on a retina screen, and 12px letters come out muddy.
    var ratio = window.devicePixelRatio || 1;
    canvas.width = count * CELL * ratio;
    canvas.height = height * ratio;
    canvas.style.width = (count * CELL) + "px";
    canvas.style.height = height + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, count * CELL, height);
    ctx.textAlign = "center";

    for (var i = 0; i < count; i++) {
      var x = i * CELL;
      var letter = sequence.letters[i];
      var number = sequence.numbers[i];
      var kind = residueClass(letter);
      var isContact = !!contacts[number];

      if (hasLogo) {
        var column = sequence.logo[sequence.columns[i]] || [];
        var y = logoHeight;
        column.forEach(function (entry) {
          // entry is [letter, fraction of the column, bits of information]
          var slice = (entry[1] * entry[2] / MAX_BITS) * (logoHeight - 4);
          if (slice < 0.6) return;
          ctx.save();
          ctx.translate(x + CELL / 2, y);
          ctx.scale(1, slice / 10);          // 10px glyphs stretched to the slice
          ctx.font = "700 10px ui-monospace, Menlo, monospace";
          ctx.fillStyle = CLASS_INK[residueClass(entry[0])];
          ctx.fillText(entry[0], 0, 0);
          ctx.restore();
          y -= slice;
        });
      }

      var top = logoHeight;
      ctx.fillStyle = CLASS_COLOUR[kind];
      ctx.fillRect(x, top, CELL - 1, TRACK_HEIGHT - 2);
      if (isContact) {
        ctx.fillStyle = "#c0166f";
        ctx.fillRect(x, top + TRACK_HEIGHT - 4, CELL - 1, 3);
      }
      if (number === focusNumber) {
        ctx.strokeStyle = "#16202b";
        ctx.lineWidth = 2;
        ctx.strokeRect(x - 0.5, top - 1, CELL, TRACK_HEIGHT);
      }
      ctx.fillStyle = CLASS_INK[kind];
      ctx.font = (isContact ? "700 " : "") + "11px ui-monospace, Menlo, monospace";
      ctx.fillText(letter, x + CELL / 2, top + 15);

      // A number every ten residues, against the residue it belongs to.
      if (number % 10 === 0) {
        ctx.fillStyle = "#6b7c93";
        ctx.font = "9px ui-monospace, Menlo, monospace";
        ctx.fillText(String(number), x + CELL / 2, logoHeight + TRACK_HEIGHT + 11);
      }
    }
  }

  function sequenceIndexAt(event) {
    var canvas = document.getElementById("seq-canvas");
    var rect = canvas.getBoundingClientRect();
    var index = Math.floor((event.clientX - rect.left) / CELL);
    if (!sequence || index < 0 || index >= sequence.letters.length) return -1;
    return index;
  }

  function wireSequence() {
    var canvas = document.getElementById("seq-canvas");
    var tooltip = document.getElementById("seq-tooltip");

    canvas.addEventListener("mousemove", function (event) {
      var index = sequenceIndexAt(event);
      if (index < 0) { tooltip.hidden = true; return; }
      var target = data.targets.filter(function (x) { return x.id === current; })[0];
      var contacts = target ? contactsByNumber(target) : {};
      var number = sequence.numbers[index];
      var rows = contacts[number] || [];
      var parts = [sequence.restypes[index] + number + " \u00b7 chain " + sequence.letter];
      rows.forEach(function (row) {
        parts.push(row.type + (row.distance ? " " + row.distance.toFixed(2) + " \u00c5" : ""));
      });
      if (sequence.logo && sequence.logo.length) {
        var column = sequence.logo[sequence.columns[index]] || [];
        var top = column[column.length - 1];
        if (top) {
          parts.push("conserved " + Math.round(top[1] * 100) + "% as " + top[0] +
                     " across " + sequence.aligned_count + " proteins");
        }
      }
      tooltip.textContent = parts.join(" \u2014 ");
      tooltip.hidden = false;
      var host = canvas.parentNode.getBoundingClientRect();
      // Clamped to the scroll box so the tooltip never hangs off the card.
      var left = event.clientX - host.left;
      tooltip.style.left = Math.max(0, Math.min(left, host.width - 20)) + "px";
      highlightResidue(sequence.letter, number);
    });

    canvas.addEventListener("mouseleave", function () {
      tooltip.hidden = true;
      clearResidueHighlight();
    });

    canvas.addEventListener("click", function (event) {
      var index = sequenceIndexAt(event);
      if (index < 0) return;
      focusResidue(sequence.letter, sequence.numbers[index]);
    });
  }

  function select(targetId, skipScroll) {
    var t = data.targets.filter(function (x) { return x.id === targetId; })[0];
    if (!t) return;
    current = targetId;
    // Deep-linkable: the open target lives in the URL hash, so a link to one
    // target in a campaign can be shared or reloaded for as long as the session
    // lives, rather than being state that exists only in this tab.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", "#" + encodeURIComponent(targetId));
    }
    renderTable();
    renderDetail(t);
    if (!skipScroll) {
      document.getElementById("detail-card").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // ---- wiring -------------------------------------------------------------

  // The report's own tables (the summary table and the SSE motif-shift table, both
  // rendered as .full-table) arrive here as markup only -- reports.py strips every
  // script from an upload on purpose, so the sorting BoltzMaker embeds in the
  // standalone dashboard cannot run on this page. The behaviour therefore has to be
  // the site's, applied to markup it did not write. Sorting the DOM rather than
  // re-rendering from data is deliberate: these cells carry formatting that has no
  // raw equivalent here ("0.82 +/- 0.03", a CIF link, the N/A span for apo rows).
  function enableReportTableSorting() {
    function value(cell) {
      var t = cell.textContent.trim();
      if (t === "" || t === "N/A" || t === "--") return null;
      var m = t.match(/^-?\d+(\.\d+)?/);       // "0.82 +/- 0.03" ranks by the estimate
      return m ? parseFloat(m[0]) : t.toLowerCase();
    }
    document.querySelectorAll("table.full-table").forEach(function (table) {
      var head = table.tHead;
      if (!head || !head.rows.length || !table.tBodies.length) return;
      var row = head.rows[head.rows.length - 1];   // not the column-group row above it
      Array.prototype.slice.call(row.cells).forEach(function (th, index) {
        th.addEventListener("click", function () {
          var asc = !th.classList.contains("ft-sorted-asc");
          Array.prototype.slice.call(row.cells).forEach(function (other) {
            other.classList.remove("ft-sorted-asc", "ft-sorted-desc");
          });
          th.classList.add(asc ? "ft-sorted-asc" : "ft-sorted-desc");
          var dir = asc ? 1 : -1;
          var body = table.tBodies[0];
          var rows = Array.prototype.slice.call(body.rows);
          rows.forEach(function (r, i) { r._i = i; });   // stable: ties keep their order
          rows.sort(function (a, b) {
            var x = value(a.cells[index]), y = value(b.cells[index]);
            // Blanks sink whichever way the column is sorted -- "sort by pIC50" should
            // surface the strongest, never a screenful of apo rows.
            if (x === null && y === null) return a._i - b._i;
            if (x === null) return 1;
            if (y === null) return -1;
            if (x === y) return a._i - b._i;
            if (typeof x === "number" && typeof y === "number") return dir * (x - y);
            return dir * String(x).localeCompare(String(y));
          });
          rows.forEach(function (r) {
            // Family dividers assume each family's rows are contiguous, which stops
            // being true the moment the reader sorts by anything else.
            r.classList.remove("row-group-start");
            body.appendChild(r);
          });
        });
      });
    });
  }

  function init(sessionToken) {
    token = sessionToken;
    sources = token ? serverSources(token) : fileSources();
    data = JSON.parse(document.getElementById("results-payload").textContent);
    var cards = document.getElementById("ligand-cards");
    ligandCards = cards ? JSON.parse(cards.textContent) : {};

    ["filter-text", "filter-protein", "filter-flagged"].forEach(function (id) {
      var el = document.getElementById(id);
      el.addEventListener(el.tagName === "INPUT" && el.type !== "checkbox" ? "input" : "change",
                          renderTable);
    });

    document.querySelectorAll("#target-table th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        if (key === sortKey) { sortDir = -sortDir; } else { sortKey = key; sortDir = -1; }
        document.querySelectorAll("#target-table th").forEach(function (other) {
          other.classList.remove("md-sorted-asc", "md-sorted-desc");
        });
        th.classList.add(sortDir > 0 ? "md-sorted-asc" : "md-sorted-desc");
        renderTable();
      });
    });

    enableReportTableSorting();

    document.querySelectorAll(".md-viewer-controls").forEach(function (row) {
      var which = row.getAttribute("data-viewer");
      row.querySelectorAll("button").forEach(function (btn) {
        btn.addEventListener("click", function () {
          applyStyle(which, btn.getAttribute("data-style"));
        });
      });
    });

    var picker = document.getElementById("detail-target");
    picker.addEventListener("change", function () { select(picker.value); });
    data.targets.forEach(function (t) {
      var option = document.createElement("option");
      option.value = t.id;
      option.textContent = t.name || t.id;
      picker.appendChild(option);
    });

    wireSequence();

    trackHeaderHeight();
    loadOverlays();

    wireDestroy();

    var nav = document.getElementById("panel-nav");
    if (nav) {
      nav.addEventListener("change", function () {
        var panel = document.getElementById(nav.value)
                    || document.querySelector('[data-anchor="' + nav.value + '"]');
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }

    document.getElementById("af-accession-go").addEventListener("click", function () {
      var value = (document.getElementById("af-accession").value || "").trim().toUpperCase();
      if (!value) return;
      typedAccession[current] = value;
      delete alphaFold[current];
      document.getElementById("af-ask").hidden = true;
      toggleAlphaFold("pose");
    });

    renderTable();

    // Open on a target from the start. The detail panels used to stay hidden until
    // something was clicked, which on a single-target campaign meant they never
    // appeared at all -- there was nothing to click that was not already the only
    // row. The URL wins if it names one.
    var hash = decodeURIComponent((window.location.hash || "").replace(/^#/, ""));
    var opening = (hash && data.targets.filter(function (t) { return t.id === hash; })[0])
                  || visibleTargets()[0] || data.targets[0];
    if (opening) select(opening.id, true);
  }

  // A target name like "HTR2A_GNAI1+GNB1+GNG2_8NU" is 25 characters, and a dozen
  // of them rotated at 45 degrees take more height than the plot itself. The axis
  // is shortened and the full name kept on hover, which is where anyone reading a
  // specific bar looks anyway.
  var MAX_TICK = 16;

  function shorten(value) {
    return (typeof value === "string" && value.length > MAX_TICK)
      ? value.slice(0, MAX_TICK - 1) + "\u2026" : value;
  }

  function shortenCategories(traces, layout) {
    // The labels are NOT in the traces. These charts plot against numeric
    // positions (x: [0]) and carry the names in layout.xaxis.ticktext, which is
    // why a first attempt that read trace.x changed nothing at all.
    var axis = layout.xaxis;
    if (axis && Array.isArray(axis.ticktext)) {
      axis.ticktext = axis.ticktext.map(shorten);
    }
    (traces || []).forEach(function (trace) {
      if (Array.isArray(trace.x) && trace.x.some(function (v) { return typeof v === "string"; })) {
        if (!trace.hovertext) trace.hovertext = trace.x.slice();
        trace.x = trace.x.map(shorten);
      }
      // Heatmaps label both axes.
      if (Array.isArray(trace.y) && trace.type === "heatmap") trace.y = trace.y.map(shorten);
      if (Array.isArray(trace.x) && trace.type === "heatmap") trace.x = trace.x.map(shorten);
      // And the legend, which is the other place a target name appears. A legend
      // sitting outside the plot pushes the right margin out on its own, past the
      // reserve set above and regardless of automargin -- that is what made the
      // apo-vs-holo shift chart, whose twelve entries are full target names, 552px
      // wide where every other chart was 620.
      if (typeof trace.name === "string") trace.name = shorten(trace.name);
    });
  }



  function placeLegendAndColourbar(layout, narrow) {
    // Wide: both sit to the right of the plot, in the margin reserved for them.
    // Narrow: there is no room beside the plot, so the legend goes above it as a
    // single wrapping row and the colourbar below, under the category labels. Set
    // explicitly in both directions -- these charts are relaid out when the window
    // crosses the breakpoint, so leaving a property alone means keeping the
    // placement from the width the page happened to load at.
    if (layout.showlegend !== false) {
      var legend = layout.legend || {};
      if (narrow) {
        legend.orientation = "h";
        // Centred on the plot, which is where the axis title and the colourbar are
        // centred too, so the three of them share one line down the middle of the
        // card. Left-aligned it sat a legend's worth of internal padding in from
        // the axis, which read as a near-miss rather than a choice.
        legend.x = 0.5; legend.xanchor = "center";
        legend.y = 1.02; legend.yanchor = "bottom";
        legend.font = { size: 10 };
        // A legend box drawn over the plot is the report's own choice for the two
        // scatters; above the plot it would be floating in the margin.
        legend.bgcolor = "rgba(0,0,0,0)";
        legend.borderwidth = 0;
      } else {
        legend.orientation = "v";
        delete legend.xanchor; delete legend.yanchor;
      }
      layout.legend = legend;
    }
    // The colourbar is reached either through coloraxis or through the trace, and
    // the reports use both. Only the layout one can be moved from here; the trace
    // form is handled in placeTraceColourbars.
    if (layout.coloraxis) {
      layout.coloraxis.colorbar = colourbarPlacement(layout.coloraxis.colorbar, narrow);
    }
  }

  function colourbarPlacement(bar, narrow) {
    bar = bar || {};
    if (narrow) {
      bar.orientation = "h";
      // x against the plot, y against the container. Both against the container
      // drew the coloured fill to a fraction of one width and its outline to a
      // fraction of the other, so the colours sat inside a box that did not
      // contain them -- 56..216 of fill in a 56..237 box. In paper units x: 0.5
      // with len 1 spans exactly the plot area, so the bar starts and ends on the
      // axis ends and shares a centre line with the axis title below it.
      //
      // y stays on the container because against the plot it is a fraction of the
      // plot's height, so the margin it pushes depends on the height, and the
      // height is derived from that margin -- the two chased each other a pixel
      // apart and never settled.
      bar.xref = "paper"; bar.yref = "container";
      bar.x = 0.5; bar.xanchor = "center";
      bar.y = 0.02; bar.yanchor = "bottom";
      bar.len = 1; bar.lenmode = "fraction"; bar.thickness = 12;
      // xpad defaults to 10, which is a gap between the coloured bar and the
      // outline drawn around it: the colours filled 56..308 of a 46..319 box and
      // read as a bar sitting loose inside a rectangle. At 0 the outline is the
      // edge of the colours.
      bar.xpad = 0; bar.ypad = 0;
      bar.title = bar.title || {};
      if (typeof bar.title === "object") bar.title.side = "bottom";
      bar.tickfont = { size: 9 };
    } else {
      bar.orientation = "v";
      bar.xref = "paper"; bar.yref = "paper";
      bar.x = undefined; bar.y = undefined;
      bar.xanchor = undefined; bar.yanchor = undefined;
      bar.len = 1; bar.lenmode = "fraction"; bar.thickness = 15;
      bar.xpad = 10; bar.ypad = 10;   // Plotly's defaults, restated so the
                                      // breakpoint can be crossed both ways.
      if (bar.title && typeof bar.title === "object") bar.title.side = "right";
      bar.tickfont = undefined;
    }
    return bar;
  }

  function placeTraceColourbars(traces, narrow) {
    (traces || []).forEach(function (trace) {
      if (trace && trace.colorbar) trace.colorbar = colourbarPlacement(trace.colorbar, narrow);
      if (trace && trace.marker && trace.marker.colorbar) {
        trace.marker.colorbar = colourbarPlacement(trace.marker.colorbar, narrow);
      }
    });
  }

  function equaliseMargins(specs) {
    // Equal margins asked for are not equal margins drawn. Plotly measures a
    // legend or colourbar that sits outside the plot and widens that side to fit
    // it, and the widening is invisible in layout.margin -- it lands in
    // _fullLayout._size. The apo-vs-holo shift chart, whose legend is twelve full
    // target names, came out 611px wide against its neighbours' 620 that way.
    //
    // Equalised WITHIN a column width, not across the page. A chart in a
    // two-column grid is half as wide as a full-width one, so forcing it to carry
    // the same 170px legend reserve leaves it 160px of plot: the reserve is for a
    // legend it does not have, since the set shares one. Charts of the same width
    // are the ones worth comparing, and they are the ones equalised together.
    var groups = {};
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host || !host._fullLayout || !host._fullLayout._size) return;
      // Width AND the panel it sits in. Width alone conflated two different
      // two-column grids that happen to have the same cell width: the per-motif
      // pair, whose legend is twelve full target names, and the fingerprints,
      // whose legend is two words. Equalised together, the fingerprints inherited
      // a 250px legend reserve for a legend they do not have and came out 157px
      // square inside a 530px cell.
      var panel = host.closest(".md-fingerprint-grid, .md-motif-grid, .md-card");
      var key = Math.round((host.offsetWidth || 0) / 20) * 20 + "|" +
                (panel ? (panel.id || panel.className) : "");
      (groups[key] = groups[key] || []).push({ host: host, spec: spec });
    });

    var changed = false;
    Object.keys(groups).forEach(function (key) {
      var hosts = groups[key];
      var wide = { l: 0, r: 0, t: 0, b: 0 };
      hosts.forEach(function (entry) {
        var size = entry.host._fullLayout._size;
        wide.l = Math.max(wide.l, Math.ceil(size.l));
        wide.r = Math.max(wide.r, Math.ceil(size.r));
        // Top and bottom too, but only WITHIN a panel. Across the whole page this
        // was wrong and produced a 50px letterbox: one chart's twelve-name legend
        // became every chart's top margin. Within one grid it is right -- the two
        // per-motif charts sit side by side and only one carries the legend, so
        // without it one card is 551px and its neighbour 474.
        wide.t = Math.max(wide.t, Math.ceil(size.t));
        wide.b = Math.max(wide.b, Math.ceil(size.b));
      });

      hosts.forEach(function (entry) {
        var size = entry.host._fullLayout._size;
        var update = {};
        if (Math.ceil(size.l) !== wide.l) update["margin.l"] = wide.l;
        if (Math.ceil(size.r) !== wide.r) update["margin.r"] = wide.r;
        // Pin top and bottom to whole pixels as well. A legend Plotly measures at
        // 63.6px leaves a plot one pixel short of the height derived from ceil(),
        // which is how 272x260 and 272x259 ended up on the same page.
        var top = wide.t, bottom = wide.b;
        if (Math.ceil(size.t) !== top) update["margin.t"] = top;
        if (Math.ceil(size.b) !== bottom) update["margin.b"] = bottom;

        // Height is not equalised the way width is. On a phone the legend sits
        // above the plot, so a twelve-name legend is a block of top margin, and
        // taking the largest gave every chart a 400px margin inside a 460px box.
        // Each chart keeps its own top and bottom and its height holds them plus
        // a plot area -- square for a fingerprint, where the two axes are
        // residues and ligands and a wide thin box makes the cells unreadable.
        var width = Math.round(entry.host._fullLayout.width - wide.l - wide.r);
        var narrowChart = chartMetrics(entry.host) === CHART_NARROW;
        var plotHeight = isFingerprint(entry.spec)
          ? Math.max(120, width)
          : (narrowChart ? 260 : 290);
        var height = top + bottom + plotHeight;
        if (Math.round(entry.host._fullLayout.height) !== height) {
          update.height = height;
          // The container is sized in CSS as well as in the layout; left at 460 a
          // taller chart would be drawn behind the card below it.
          entry.host.style.height = height + "px";
          entry.spec.layout.height = height;
        }
        if (!Object.keys(update).length) return;
        changed = true;
        try {
          Plotly.relayout(entry.host, update);
        } catch (err) { /* leave that chart at the size it drew itself */ }
      });
    });
    return changed;
  }

  function settleMargins(specs) {
    // Relayout changes the plot's width, which can rewrap a horizontal legend and
    // so change the very top margin the height was just derived from. Two passes
    // reach a fixed point in every case seen; the third is a stop, not a plan.
    for (var pass = 0; pass < 3; pass++) {
      if (!equaliseMargins(specs)) return;
    }
  }

  function normaliseSpec(spec, host) {
    // Everything that depends on the width the page is being read at. Called on
    // the first draw and again whenever the window crosses the breakpoint, so it
    // must set each property in both directions rather than leaving one alone.
    var metrics = chartMetrics(host);
    // The report's own div carries an inline height (260px, sized to its own
    // layout) and the sanitiser keeps style attributes, so plotting at a
    // different height drew a 420px chart inside a 260px box, which spilled
    // over the card below. The container is told the height too, not just Plotly.
    host.style.height = metrics.height + "px";
    host.style.width = "100%";

    // Responsive is forced on: the reports were laid out for a full-width
    // page and these panels are narrower.
    var config = spec.config || {};
    config.responsive = true;
    config.displaylogo = false;
    // The modebar is an absolutely positioned strip over the top of the plot.
    // At desktop width it sits in the margin; on a phone it covered the top
    // third of the chart, and none of it is reachable by touch anyway.
    config.displayModeBar = !isNarrow();
    spec.config = config;

    // One height for every chart. The reports size each plot to its own
    // content, so a thirteen-bar chart came out twice the height of a
    // one-row heatmap and the panels read as a jumble of different objects.
    // autosize lets width follow the panel, and since every panel is the same
    // width and every margin below is the same, every plot area matches too.
    var layout = spec.layout || {};
    layout.height = metrics.height;
    layout.autosize = true;
    // The same margins on every chart, which is what makes the plot AREAS match
    // rather than merely the containers. These are a floor, not the last word:
    // Plotly grows a margin on its own to fit a legend or colourbar drawn
    // outside the plot, so equaliseMargins() below settles the final number.
    layout.margin = { t: metrics.margin.t, b: metrics.margin.b,
                      l: metrics.margin.l, r: metrics.margin.r };
    var narrow = metrics === CHART_NARROW;
    placeLegendAndColourbar(layout, narrow);
    placeTraceColourbars(spec.data, narrow);
    // The scatters label every point with its target name. Fifteen of those in a
    // 250px-wide plot is a thicket, and each one is a name already truncated to
    // sixteen characters. On a phone the markers stand alone -- the point is still
    // tappable, which is how a target is opened from here anyway.
    (spec.data || []).forEach(function (trace) {
      if (!trace || typeof trace.mode !== "string") return;
      if (trace._fullMode === undefined) trace._fullMode = trace.mode;
      trace.mode = isNarrow()
        ? trace._fullMode.split("+").filter(function (m) { return m !== "text"; }).join("+") || "markers"
        : trace._fullMode;
    });
    // Created if the report did not define them: guarding on `if (layout.xaxis)`
    // used to leave the settings below unapplied wherever a report had no axis
    // block, and those charts then sized themselves however they liked.
    layout.xaxis = layout.xaxis || {};
    layout.yaxis = layout.yaxis || {};
    // automargin OFF, deliberately. It expands the margin to fit the labels,
    // which is exactly what makes every plot area a different size; the labels
    // are shortened below so they fit the fixed margin instead.
    layout.xaxis.automargin = false;
    layout.yaxis.automargin = false;
    shortenCategories(spec.data, layout);
    // -75 is almost vertical, which is what made short labels take so much
    // height. Shortened labels read fine at -45. Narrower still on a phone,
    // where the labels have to fit a third of the width.
    if (layout.xaxis.tickangle === undefined || layout.xaxis.tickangle < -50) {
      layout.xaxis.tickangle = -45;
    }
    if (layout.xaxis.tickfont === undefined) layout.xaxis.tickfont = {};
    layout.xaxis.tickfont.size = isNarrow() ? 9 : 11;
    layout.yaxis.tickfont = layout.yaxis.tickfont || {};
    layout.yaxis.tickfont.size = isNarrow() ? 9 : 11;
    spec.layout = layout;
    return spec;
  }





  //: The fingerprints all measure the same thing on the same scale, so one
  //: colourbar serves the set. The first keeps it; the rest are the same plot
  //: with the same legend printed again.
  function isFingerprint(spec) {
    return String(spec.id || "").indexOf("chart-fingerprint") === 0;
  }

  function shareFingerprintScale(spec, drawn) {
    if (!isFingerprint(spec)) return;
    var first = !drawn.some(isFingerprint);
    (spec.data || []).forEach(function (trace) {
      // No colourbar at all. The values are 0 and 1 -- touched or not -- and a bar
      // running 0, 0.5, 1 under the word "contacts" invited a reading of how many,
      // which the plot does not say. The report's own two-swatch legend does say
      // it, in words.
      trace.showscale = false;
      // Fixed ends, so a colour means the same thing in every plot. Left to
      // itself each heatmap scales to its own maximum.
      trace.zmin = 0;
      trace.zmax = fingerprintMax;
    });
    // One legend for the set. It is the same two swatches six times over, and six
    // copies of it cost more vertical space than the plots they explain.
    if (spec.layout) spec.layout.showlegend = first;
    (spec.data || []).forEach(function (trace) {
      if (trace.type !== "heatmap") trace.showlegend = first;
    });
  }

  function computeFingerprintMax(specs) {
    var top = 1;
    specs.filter(isFingerprint).forEach(function (spec) {
      (spec.data || []).forEach(function (trace) {
        // z is a grid, and Plotly's typed-array spec can encode it either as an
        // array of encoded rows or as one encoded block for the whole thing. The
        // second is not iterable, and assuming the first threw on every load and
        // took every chart on the page down with it.
        var rows = Array.isArray(trace.z) ? trace.z : [trace.z];
        rows.forEach(function (row) {
          toArray(row).forEach(function (value) {
            if (typeof value === "number" && value > top) top = value;
          });
        });
      });
    });
    return top;
  }

  /* Family x ligand selectivity, rebuilt rather than replayed.

     The report draws this one as a PNG, so the number in a cell could only be
     read off the colour. The same pivot is in the payload -- family, ligand and
     pIC50 per target -- so it is redrawn here as a heatmap that can be hovered.
     Falls back to the report's image if the campaign predicted no affinity. */
  function drawSelectivity() {
    var host = document.getElementById("chart-selectivity");
    if (!host || !data.has_affinity) return;
    var families = [], ligands = [], seenF = {}, seenL = {};
    data.targets.forEach(function (t) {
      if (t.pic50 === null || t.pic50 === undefined || !t.ligand) return;
      var family = t.group || t.family;
      if (!seenF[family]) { seenF[family] = true; families.push(family); }
      if (!seenL[t.ligand]) { seenL[t.ligand] = true; ligands.push(t.ligand); }
    });
    if (!families.length || !ligands.length) return;

    // Several targets can share a family and ligand -- the same receptor with and
    // without its G protein -- so the strongest of them stands for the pair,
    // which is what a selectivity panel is asking about.
    var best = {};
    data.targets.forEach(function (t) {
      if (t.pic50 === null || t.pic50 === undefined || !t.ligand) return;
      var key = (t.group || t.family) + "\u0000" + t.ligand;
      if (best[key] === undefined || t.pic50 > best[key]) best[key] = t.pic50;
    });

    var z = families.map(function (family) {
      return ligands.map(function (ligand) {
        var value = best[family + "\u0000" + ligand];
        return value === undefined ? null : value;
      });
    });

    var spec = {
      id: "chart-selectivity",
      data: [{
        type: "heatmap", x: ligands, y: families, z: z,
        colorscale: "Viridis", xgap: 2, ygap: 2,
        hovertemplate: "%{y} \u00b7 %{x}<br>pIC50 %{z:.2f}<extra></extra>",
        colorbar: { title: { text: "pIC50" } },
      }],
      layout: { yaxis: { autorange: "reversed" } },
      config: {},
    };
    drawSpec(spec, host);
    extraSpecs.push(spec);
  }

  //: The bars carry a raw float, so the default hover reads 0.8275268673896790.
  //: Two decimals is the precision these numbers are quoted at everywhere else on
  //: the page, and the table beside them.
  var HOVER_2DP = {
    "chart-pic50": "%{customdata}<br>pIC50 %{y:.2f}<extra></extra>",
    "chart-confidence": "%{customdata}<br>confidence %{y:.2f}<extra></extra>",
  };

  function roundHovers(spec) {
    var template = HOVER_2DP[spec.id];
    if (!template) return;
    // The bars are plotted against numeric positions with the names in ticktext,
    // so the name has to be carried per point for the hover to be able to say it.
    var names = (spec.layout && spec.layout.xaxis && spec.layout.xaxis.ticktext) || [];
    (spec.data || []).forEach(function (trace) {
      trace.hovertemplate = template;
      if (names.length) trace.customdata = names.slice();
    });
  }

  //: Which motifs belong to which of the two per-motif panels. A GPCR's loops
  //: move on a scale that hides what the helices do -- an ICL2 shifting 18A puts
  //: a 2A change in TM6 flat against the axis -- so they are drawn apart.
  function motifClass(name) {
    var label = String(name || "").toUpperCase();
    if (label.indexOf("TM") === 0) return "tm";
    return "loop";       // ICL, ECL, H8 and its loop: everything that is not a helix crossing
  }

  /* The per-motif chart, drawn twice: loops in one panel, transmembrane in the
     other, sharing one legend. The traces are per target, so the split is on the
     x categories rather than on the traces. */
  function splitMotifChart(spec) {
    var loops = document.getElementById("chart-sse-loops");
    var tm = document.getElementById("chart-sse-tm");
    if (!loops || !tm) return false;

    ["loop", "tm"].forEach(function (kind) {
      var host = kind === "loop" ? loops : tm;
      var traces = (spec.data || []).map(function (trace) {
        var copy = {};
        Object.keys(trace).forEach(function (key) { copy[key] = trace[key]; });
        var keepIndex = [];
        (trace.x || []).forEach(function (name, index) {
          if (motifClass(name) === kind) keepIndex.push(index);
        });
        var y = toArray(trace.y);
        copy.x = keepIndex.map(function (i) { return trace.x[i]; });
        copy.y = keepIndex.map(function (i) { return y[i]; });
        copy.hovertemplate = "%{fullData.name}<br>%{x}: %{y:.2f} \u00c5<extra></extra>";
        // One legend for the pair: the second panel's traces are the same twelve
        // targets, and a second copy of the list says nothing the first did not.
        copy.showlegend = kind === "loop";
        return copy;
      }).filter(function (trace) { return trace.x.length; });
      if (!traces.length) return;
      var layout = JSON.parse(JSON.stringify(spec.layout || {}));
      layout.showlegend = kind === "loop";
      // The report pins the category list so every chart shares one x ordering.
      // Left alone, both halves draw all fifteen motifs and only half of each has
      // any bars -- the split was in the data and invisible on screen.
      if (layout.xaxis && Array.isArray(layout.xaxis.categoryarray)) {
        layout.xaxis.categoryarray = layout.xaxis.categoryarray.filter(function (name) {
          return motifClass(name) === kind;
        });
      }
      var clone = { id: host.id, data: traces, layout: layout,
                    config: JSON.parse(JSON.stringify(spec.config || {})) };
      drawSpec(clone, host);
      extraSpecs.push(clone);
    });
    return true;
  }

  //: Plotly's typed-array spec: numbers that came from numpy arrive as base64
  //: rather than as a JSON array. Splitting a trace by index means decoding it,
  //: because trace.y[i] on one of these is undefined and every bar would vanish.
  var TYPED_ARRAYS = {
    f8: Float64Array, f4: Float32Array, i4: Int32Array, i2: Int16Array,
    i1: Int8Array, u4: Uint32Array, u2: Uint16Array, u1: Uint8Array,
  };

  function toArray(values) {
    if (Array.isArray(values)) return values;
    if (!values || values.bdata === undefined) return [];
    var View = TYPED_ARRAYS[values.dtype];
    if (!View) return [];
    try {
      var binary = atob(values.bdata);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      return Array.prototype.slice.call(new View(bytes.buffer));
    } catch (err) {
      return [];
    }
  }

  function drawSpec(spec, host) {
    try {
      normaliseSpec(spec, host);
      Plotly.newPlot(host, spec.data, spec.layout, spec.config);
      // The report's own confidence-against-affinity scatter is the one kept, so
      // it takes over the job of opening a target.
      if (spec.id === "chart-scatter") wireScatterClicks(host);
    } catch (err) {
      host.innerHTML = '<p class="md-hint">This chart could not be drawn.</p>';
    }
  }

  function plotReportCharts(specs) {
    if (!window.Plotly || !Array.isArray(specs)) return;
    var drawn = [];
    fingerprintMax = computeFingerprintMax(specs);
    specs.forEach(function (spec) {
      // Two charts the page rebuilds rather than replays: the per-motif RMSD is
      // split in two, and the selectivity heatmap replaces a flat image.
      if (spec.id === "chart-sse-shift" && splitMotifChart(spec)) return;
      var host = document.getElementById(spec.id);
      if (!host) return;      // its panel was dropped
      roundHovers(spec);
      shareFingerprintScale(spec, drawn);
      drawSpec(spec, host);
      drawn.push(spec);
    });
    drawSelectivity();
    specs = drawn.concat(extraSpecs);
    settleMargins(specs);

    var wasNarrow = isNarrow();
    window.addEventListener("resize", function () {
      var nowNarrow = isNarrow();
      if (nowNarrow !== wasNarrow) {
        // Crossing the breakpoint changes the margins, the legend's orientation
        // and whether there is a modebar, and none of those are things resize()
        // recomputes. react() takes the new config as well as the new layout,
        // which relayout() cannot.
        wasNarrow = nowNarrow;
        specs.forEach(function (spec) {
          var host = document.getElementById(spec.id);
          if (!host || !host.data) return;
          try {
            normaliseSpec(spec, host);
            Plotly.react(host, spec.data, spec.layout, spec.config);
          } catch (err) { /* leave that chart as it is */ }
        });
      } else {
        specs.forEach(function (spec) {
          var host = document.getElementById(spec.id);
          if (host && host.data) Plotly.Plots.resize(host);
        });
      }
      // A resize re-measures the legends against the new width, so the sizes have
      // to be settled again or they drift apart the first time the window moves.
      settleMargins(specs);
    });
  }

  return { init: init, plotReportCharts: plotReportCharts };
})();
