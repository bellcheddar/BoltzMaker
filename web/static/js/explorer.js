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
    var family = document.getElementById("filter-family").value;
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

  // ---- quadrant plot ------------------------------------------------------

  function renderPlot() {
    var el = document.getElementById("quadrant");
    if (!el || !window.Plotly) return;

    var points = data.targets.filter(function (t) {
      return t.confidence !== null && t.pic50 !== null;
    });
    if (!points.length) {
      el.innerHTML = '<p class="md-hint">No target has both a confidence score and a ' +
                     'predicted affinity, so there is nothing to plot.</p>';
      return;
    }

    var trace = {
      x: points.map(function (t) { return t.confidence; }),
      y: points.map(function (t) { return t.pic50; }),
      text: points.map(function (t) {
        var note = t.flags.length ? "<br>" + t.flags.join(", ").replace(/_/g, " ").toLowerCase() : "";
        return "<b>" + (t.name || t.id) + "</b><br>" + (t.ligand || "") +
               "<br>confidence " + fmt(t.confidence, 3) +
               "<br>pIC50 " + fmt(t.pic50, 2) +
               (t.plip_total ? "<br>" + t.plip_total + " interactions" : "") + note;
      }),
      customdata: points.map(function (t) { return t.id; }),
      mode: "markers",
      type: "scatter",
      hovertemplate: "%{text}<extra></extra>",
      marker: {
        size: 13,
        color: points.map(colourFor),
        line: { width: 1, color: "#ffffff" }
      }
    };

    var layout = {
      autosize: true,
      margin: { l: 60, r: 20, t: 10, b: 50 },
      font: { family: "Inter, sans-serif", size: 12 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { title: "Confidence score", zeroline: false, gridcolor: "#eef2f7" },
      yaxis: { title: "Predicted pIC50", zeroline: false, gridcolor: "#eef2f7" },
      shapes: [{
        type: "line", x0: data.low_confidence_threshold, x1: data.low_confidence_threshold,
        yref: "paper", y0: 0, y1: 1,
        line: { color: "#fcb900", width: 2, dash: "dash" }
      }],
      annotations: [{
        x: data.low_confidence_threshold, yref: "paper", y: 1,
        text: "low confidence ←", showarrow: false,
        xanchor: "right", yanchor: "top",
        font: { size: 11, color: "#8a6100" }
      }]
    };

    Plotly.newPlot(el, [trace], layout, {
      responsive: true, displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"]
    });
    el.on("plotly_click", function (ev) {
      if (ev.points && ev.points.length) select(ev.points[0].customdata);
    });
    window.addEventListener("resize", function () { Plotly.Plots.resize(el); });
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
    document.getElementById("detail-card").style.display = "";
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
    if (t.image) {
      var img = document.createElement("img");
      img.src = "/auto/analysis/" + token + "/image/" + encodeURIComponent(t.id);
      img.alt = "Detected interactions for " + (t.name || t.id);
      img.className = "md-plip-image";
      img.loading = "lazy";
      plip.appendChild(img);
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

    ["filter-text", "filter-family", "filter-flagged"].forEach(function (id) {
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
    renderPlot();

    // Restore the target named in the URL, if it is one this campaign has.
    var hash = decodeURIComponent((window.location.hash || "").replace(/^#/, ""));
    if (hash) select(hash, true);
  }

  function plotReportCharts(specs) {
    if (!window.Plotly || !Array.isArray(specs)) return;
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host) return;      // its panel was dropped
      try {
        // Responsive is forced on: the reports were laid out for a full-width
        // page and these panels are narrower.
        var config = spec.config || {};
        config.responsive = true;
        config.displaylogo = false;
        Plotly.newPlot(host, spec.data, spec.layout || {}, config);
      } catch (err) {
        host.innerHTML = '<p class="md-hint">This chart could not be drawn.</p>';
      }
    });
    window.addEventListener("resize", function () {
      specs.forEach(function (spec) {
        var host = document.getElementById(spec.id);
        if (host && host.data) Plotly.Plots.resize(host);
      });
    });
  }

  return { init: init, plotReportCharts: plotReportCharts };
})();
