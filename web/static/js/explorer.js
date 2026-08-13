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
  var CHART_HEIGHT = 420;
  // One margin for every chart. b holds a rotated, shortened category label; l
  // holds a y title plus tick labels, including a heatmap's row names; r holds a
  // legend or colourbar. Every plot area is then the same box.
  var CHART_MARGIN = { t: 20, b: 110, l: 120, r: 170 };
  var viewer = null;
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
      cell(fmt(t.confidence, 3), "num");
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
      ["Ligand", t.ligand || "—"],
      ["Role", t.role || "—"],
      ["SMILES", t.smiles || "—"]
    ];
  }

  function renderDetail(t) {
    document.getElementById("detail-title").textContent = t.name || t.id;

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

    // Counts and diagram are separate panes now, so each is filled on its own.
    var plip = document.getElementById("detail-plip");
    plip.innerHTML = "";
    if (t.plip_total) {
      var list = document.createElement("ul");
      list.className = "md-plip-list";
      Object.keys(t.plip).forEach(function (kind) {
        var li = document.createElement("li");
        li.innerHTML = "<b>" + t.plip[kind] + "</b> " + kind;
        list.appendChild(li);
      });
      plip.appendChild(list);
    } else {
      var none = document.createElement("p");
      none.className = "md-hint";
      none.textContent = t.plip_status && t.plip_status !== "ok"
        ? "PLIP did not run for this target (" + t.plip_status + ")."
        : "No protein-ligand interactions were detected for this target.";
      plip.appendChild(none);
    }

    var diagram = document.getElementById("detail-diagram");
    diagram.innerHTML = "";
    if (t.image) {
      var img = document.createElement("img");
      img.src = "/auto/analysis/" + token + "/image/" + encodeURIComponent(t.id);
      img.alt = "Detected interactions for " + (t.name || t.id);
      img.className = "md-plip-image";
      img.loading = "lazy";
      diagram.appendChild(img);
    } else {
      var noDiagram = document.createElement("p");
      noDiagram.className = "md-hint";
      // An apo target has no ligand, so there is nothing for PLIP to draw --
      // which is different from PLIP having failed, and should not read as it.
      noDiagram.textContent = t.ligand
        ? "No interaction diagram was produced for this target."
        : "This target has no ligand, so there are no interactions to draw.";
      diagram.appendChild(noDiagram);
    }

    loadStructure(t);
  }

  function loadStructure(t) {
    var host = document.getElementById("viewer");
    var note = document.getElementById("viewer-note");
    host.innerHTML = "";
    if (!t.structure) {
      note.textContent = "No structure was included for this target.";
      return;
    }
    if (!window.$3Dmol) {
      note.textContent = "The 3D viewer library did not load, so the pose cannot be shown. " +
                         "Everything else on this page still works.";
      return;
    }
    if (!hasWebGL()) {
      // Worth naming explicitly rather than letting 3Dmol fail opaquely further
      // down: this is the one failure here that is about the browser rather than
      // the data, and the user can act on it.
      note.textContent = "This browser has WebGL disabled or unavailable, which the 3D viewer " +
                         "needs. The interactions and metrics on the right are unaffected.";
      return;
    }
    note.textContent = "Loading structure…";

    fetch("/auto/analysis/" + token + "/structure/" + encodeURIComponent(t.id))
      .then(function (response) {
        if (!response.ok) throw new Error("structure request failed (" + response.status + ")");
        return response.text();
      })
      .then(function (cif) {
        viewer = $3Dmol.createViewer(host, { backgroundColor: "#f4f7fb" });
        viewer.addModel(cif, "cif");
        applyStyle("cartoon");
        note.textContent = "Drag to rotate, scroll to zoom. Ligand shown as sticks.";
      })
      .catch(function (err) {
        // Not every thrown value is an Error: 3Dmol can reject with a bare string
        // or an event, and "Could not load the structure: undefined" is the least
        // useful sentence this page could produce.
        var reason = (err && err.message) || (typeof err === "string" ? err : "") ||
                     "the viewer could not render this structure";
        note.textContent = "Could not load the structure: " + reason;
      });
  }

  function applyStyle(mode) {
    if (!viewer) return;
    viewer.setStyle({}, {});
    if (mode === "surface") {
      viewer.setStyle({}, { cartoon: { color: "spectrum", opacity: 0.9 } });
      viewer.addSurface($3Dmol.SurfaceType.VDW, { opacity: 0.55, color: "#cfe0f2" },
                        { hetflag: false });
    } else {
      viewer.setStyle({}, { cartoon: { color: "spectrum" } });
    }
    // Hetero atoms are the ligand: always sticks, always on top, in every mode --
    // it is the thing the campaign is actually about.
    viewer.setStyle({ hetflag: true }, { stick: { radius: 0.22, colorscheme: "orangeCarbon" } });
    viewer.zoomTo();
    viewer.render();
    if (mode === "spin") viewer.spin("y", 0.6); else viewer.spin(false);
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

  function init(sessionToken) {
    token = sessionToken;
    data = JSON.parse(document.getElementById("results-payload").textContent);

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

    document.querySelectorAll(".md-viewer-controls button").forEach(function (btn) {
      btn.addEventListener("click", function () { applyStyle(btn.getAttribute("data-style")); });
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


  function equaliseMargins(specs) {
    // Equal margins asked for are not equal margins drawn. Plotly measures a
    // legend or colourbar that sits outside the plot and widens that side to fit
    // it, and the widening is invisible in layout.margin -- it lands in
    // _fullLayout._size. The apo-vs-holo shift chart, whose legend is twelve full
    // target names, came out 611px wide against its neighbours' 620 that way.
    //
    // So: draw them all, read back the margins Plotly actually used, and give
    // every chart the largest of each. Because that is at least as big as any
    // chart's own legend, nothing gets widened a second time and one pass settles
    // it. This is the "use the minimal size" the sizing is meant to hit -- found
    // by measuring the most constrained chart rather than guessing at font
    // metrics, which is what the two previous attempts here did.
    var hosts = [], used = { l: 0, r: 0, t: 0, b: 0 };
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host || !host._fullLayout || !host._fullLayout._size) return;
      hosts.push(host);
      var size = host._fullLayout._size;
      ["l", "r", "t", "b"].forEach(function (side) {
        used[side] = Math.max(used[side], Math.ceil(size[side]));
      });
    });
    if (hosts.length < 2) return;
    hosts.forEach(function (host) {
      var size = host._fullLayout._size;
      if (Math.ceil(size.l) === used.l && Math.ceil(size.r) === used.r &&
          Math.ceil(size.t) === used.t && Math.ceil(size.b) === used.b) return;
      try {
        Plotly.relayout(host, {
          "margin.l": used.l, "margin.r": used.r,
          "margin.t": used.t, "margin.b": used.b,
        });
      } catch (err) { /* leave that chart at the size it drew itself */ }
    });
  }

  function plotReportCharts(specs) {
    if (!window.Plotly || !Array.isArray(specs)) return;
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host) return;      // its panel was dropped
      // The report's own div carries an inline height (260px, sized to its own
      // layout) and the sanitiser keeps style attributes, so plotting at a
      // different height drew a 420px chart inside a 260px box, which spilled
      // over the card below. The container is told the height too, not just Plotly.
      host.style.height = CHART_HEIGHT + "px";
      host.style.width = "100%";
      try {
        // Responsive is forced on: the reports were laid out for a full-width
        // page and these panels are narrower.
        var config = spec.config || {};
        config.responsive = true;
        config.displaylogo = false;

        // One height for every chart. The reports size each plot to its own
        // content, so a thirteen-bar chart came out twice the height of a
        // one-row heatmap and the panels read as a jumble of different objects.
        // autosize lets width follow the panel, and since every panel is the same
        // width and every margin below is the same, every plot area matches too.
        var layout = spec.layout || {};
        layout.height = CHART_HEIGHT;
        layout.autosize = true;
        // The same margins on every chart, which is what makes the plot AREAS match
        // rather than merely the containers. These are a floor, not the last word:
        // Plotly grows a margin on its own to fit a legend or colourbar drawn
        // outside the plot, so equaliseMargins() below settles the final number.
        layout.margin = { t: CHART_MARGIN.t, b: CHART_MARGIN.b,
                          l: CHART_MARGIN.l, r: CHART_MARGIN.r };
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
        // height. Shortened labels read fine at -45.
        if (layout.xaxis.tickangle === undefined || layout.xaxis.tickangle < -50) {
          layout.xaxis.tickangle = -45;
        }
        Plotly.newPlot(host, spec.data, layout, config);
        // The report's own confidence-against-affinity scatter is the one kept, so
        // it takes over the job of opening a target.
        if (spec.id === "chart-scatter") wireScatterClicks(host);
      } catch (err) {
        host.innerHTML = '<p class="md-hint">This chart could not be drawn.</p>';
      }
    });
    equaliseMargins(specs);
    window.addEventListener("resize", function () {
      specs.forEach(function (spec) {
        var host = document.getElementById(spec.id);
        if (host && host.data) Plotly.Plots.resize(host);
      });
      // A resize re-measures the legends against the new width, so the sizes have
      // to be settled again or they drift apart the first time the window moves.
      equaliseMargins(specs);
    });
  }

  return { init: init, plotReportCharts: plotReportCharts };
})();
