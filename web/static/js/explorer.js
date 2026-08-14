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
  function chartMetrics() { return isNarrow() ? CHART_NARROW : CHART_WIDE; }
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



  function placeLegendAndColourbar(layout) {
    // Wide: both sit to the right of the plot, in the margin reserved for them.
    // Narrow: there is no room beside the plot, so the legend goes above it as a
    // single wrapping row and the colourbar below, under the category labels. Set
    // explicitly in both directions -- these charts are relaid out when the window
    // crosses the breakpoint, so leaving a property alone means keeping the
    // placement from the width the page happened to load at.
    var narrow = isNarrow();
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
    // So: draw them all, read back the margins Plotly actually used, and settle
    // them. Left and right take the largest of each, which is what makes the plot
    // areas the same WIDTH -- the most constrained chart sets it, found by
    // measuring rather than by guessing at font metrics.
    //
    // Height is not done that way, and the first attempt that did was wrong. On a
    // phone the legend sits above the plot and the colourbar below, so a legend of
    // twelve names is a block of margin, not a column beside the plot. Taking the
    // largest top and bottom then gave every chart a 400px margin inside a 460px
    // box: a 50px letterbox where the plot should be. Instead each chart keeps its
    // own top and bottom, and its height is set to hold them plus a plot area of a
    // fixed size. The plot areas still match exactly -- it is the cards around
    // them that differ, by however much legend each one has to carry.
    var hosts = [], wide = { l: 0, r: 0 };
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host || !host._fullLayout || !host._fullLayout._size) return;
      hosts.push({ host: host, spec: spec });
      var size = host._fullLayout._size;
      wide.l = Math.max(wide.l, Math.ceil(size.l));
      wide.r = Math.max(wide.r, Math.ceil(size.r));
    });
    if (!hosts.length) return false;

    var plotHeight = isNarrow() ? 260 : 290;
    var changed = false;
    hosts.forEach(function (entry) {
      var size = entry.host._fullLayout._size;
      var update = {};
      if (Math.ceil(size.l) !== wide.l) update["margin.l"] = wide.l;
      if (Math.ceil(size.r) !== wide.r) update["margin.r"] = wide.r;
      // Pin top and bottom to whole pixels as well. A legend Plotly measures at
      // 63.6px leaves a plot one pixel short of the height derived from ceil(),
      // which is how 272x260 and 272x259 ended up on the same page. Setting the
      // margin to the value it already pushed to is stable: the final margin is
      // the larger of the two and they are now the same number.
      var top = Math.ceil(size.t), bottom = Math.ceil(size.b);
      if (size.t !== top) update["margin.t"] = top;
      if (size.b !== bottom) update["margin.b"] = bottom;
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
    var metrics = chartMetrics();
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
    placeLegendAndColourbar(layout);
    placeTraceColourbars(spec.data, isNarrow());
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

  function plotReportCharts(specs) {
    if (!window.Plotly || !Array.isArray(specs)) return;
    specs.forEach(function (spec) {
      var host = document.getElementById(spec.id);
      if (!host) return;      // its panel was dropped
      try {
        normaliseSpec(spec, host);
        Plotly.newPlot(host, spec.data, spec.layout, spec.config);
        // The report's own confidence-against-affinity scatter is the one kept, so
        // it takes over the job of opening a target.
        if (spec.id === "chart-scatter") wireScatterClicks(host);
      } catch (err) {
        host.innerHTML = '<p class="md-hint">This chart could not be drawn.</p>';
      }
    });
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
