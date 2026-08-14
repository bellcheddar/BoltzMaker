/* Mol* wrapper for the two structure panes.

   The pose pane and the interaction pane are the same viewer with different
   opening moves: one shows the whole complex coloured by chain, the other shows
   the ligand and the residues PLIP found touching it, and spins.

   Mol*'s "viewer" build exports almost nothing -- molstar.Viewer, and three debug
   switches. There is no query language on the global, so the usual
   Script.getStructureSelection route to "chain A residue 155" does not exist
   here. Selections are therefore built by walking the model's own tables, which
   ARE reachable through the loaded structure. That is the one piece of this file
   that reaches past the public surface, and it is confined to residueLoci(). */
(function () {
  "use strict";

  var OPTIONS = {
    /* No extensions. Mol* enables all of them by default, and one of those --
       Volumes & Segmentations -- fetches a listing from a server in Brno the
       moment a viewer is created. Twice a page, from a site that otherwise talks
       only to itself, for a feature nothing here uses. It fails silently when
       offline, which is exactly how it went unnoticed. */
    extensions: [],
    layoutIsExpanded: false,
    layoutShowControls: false,
    layoutShowSequence: false,
    layoutShowLog: false,
    layoutShowLeftPanel: false,
    layoutShowRemoteState: false,
    viewportShowExpand: false,
    viewportShowControls: false,
    viewportShowSettings: false,
    viewportShowSelectionMode: false,
    viewportShowAnimation: false,
    viewportShowTrajectoryControls: false,
  };

  function hasWebGL() {
    try {
      var canvas = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
                (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
    } catch (err) {
      return false;
    }
  }

  /* Every atom of one residue, as a Mol* Loci.

     A Loci element is {unit, indices}, where indices are offsets INTO
     unit.elements rather than element ids -- getting that wrong yields a loci
     that is accepted, highlights the wrong atoms and never errors. Chain and
     residue are both read per element rather than per unit: Mol* does split
     units by chain today, and a loop that assumes it silently returns nothing
     the day a structure arrives that does not. */
  function residueLoci(structure, chainId, seqId) {
    var elements = [];
    structure.units.forEach(function (unit) {
      var hierarchy = unit.model.atomicHierarchy;
      if (!hierarchy || !hierarchy.residueAtomSegments) return;
      var indices = [];
      for (var i = 0; i < unit.elements.length; i++) {
        var element = unit.elements[i];
        var chainIndex = hierarchy.chainAtomSegments.index[element];
        if (hierarchy.chains.auth_asym_id.value(chainIndex) !== chainId) continue;
        var residueIndex = hierarchy.residueAtomSegments.index[element];
        if (hierarchy.residues.auth_seq_id.value(residueIndex) === seqId) indices.push(i);
      }
      if (indices.length) elements.push({ unit: unit, indices: new Int32Array(indices) });
    });
    if (!elements.length) return null;
    return { kind: "element-loci", structure: structure, elements: elements };
  }

  function chainLoci(structure, chainId) {
    var elements = [];
    structure.units.forEach(function (unit) {
      var hierarchy = unit.model.atomicHierarchy;
      if (!hierarchy || !hierarchy.chainAtomSegments) return;
      var indices = [];
      for (var i = 0; i < unit.elements.length; i++) {
        var chainIndex = hierarchy.chainAtomSegments.index[unit.elements[i]];
        if (hierarchy.chains.auth_asym_id.value(chainIndex) === chainId) indices.push(i);
      }
      if (indices.length) elements.push({ unit: unit, indices: new Int32Array(indices) });
    });
    if (!elements.length) return null;
    return { kind: "element-loci", structure: structure, elements: elements };
  }

  function Wrapper(viewer, host) {
    this.viewer = viewer;
    this.plugin = viewer.plugin;
    this.host = host;
    this.structure = null;
    this.spinning = false;
    this.mode = "cartoon";
  }

  Wrapper.prototype.load = function (url) {
    var self = this;
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error("structure request failed (" + response.status + ")");
      return response.text();
    }).then(function (cif) {
      return self.plugin.clear().then(function () {
        return self.viewer.loadStructureFromData(cif, "mmcif");
      });
    }).then(function () {
      var current = self.plugin.managers.structure.hierarchy.current;
      self.structure = current.structures[0] || null;
      if (!self.structure) throw new Error("the file held no structure");
      return self.setStyle(self.mode);
    }).then(function () {
      // Resolve with the wrapper, not with whatever setStyle happened to return.
      // Returning setStyle's undefined made the caller's `.then(wrapper => ...)`
      // read as success and then fail on the first property it touched.
      return self;
    });
  };

  Wrapper.prototype.components = function () {
    return this.structure ? this.structure.components : [];
  };

  Wrapper.prototype.data = function () {
    return this.structure && this.structure.cell.obj ? this.structure.cell.obj.data : null;
  };

  /* Cartoon and surface are representation changes; spin is a camera property.
     They are one control row on screen, so they are one entry point here, and
     spin is a toggle over whichever representation is showing rather than a
     third mutually exclusive state -- asking for a spinning surface should not
     have to mean asking twice. */
  Wrapper.prototype.setStyle = function (mode) {
    var self = this;
    var manager = this.plugin.managers.structure.component;
    if (mode === "spin") {
      this.spinning = !this.spinning;
      this.setSpin(this.spinning);
      return Promise.resolve();
    }
    this.mode = mode;
    var polymer = this.components().filter(function (component) {
      return (component.key || "").indexOf("polymer") >= 0;
    })[0];
    if (!polymer || !polymer.representations.length) return Promise.resolve();
    var type = mode === "surface" ? "molecular-surface" : "cartoon";
    return manager.updateRepresentations([polymer], polymer.representations[0],
                                         { type: { name: type, params: {} } })
      .then(function () { return self.colourByChain(); });
  };

  Wrapper.prototype.colourByChain = function () {
    if (!this.structure) return Promise.resolve();
    return this.plugin.managers.structure.component.updateRepresentationsTheme(
      this.components(), { color: "chain-id" });
  };

  Wrapper.prototype.setSpin = function (on) {
    this.spinning = !!on;
    if (!this.plugin.canvas3d) return;
    this.plugin.canvas3d.setProps({
      trackball: { animate: on ? { name: "spin", params: { speed: 0.7 } }
                              : { name: "off", params: {} } },
    });
  };

  Wrapper.prototype.focusResidue = function (chainId, seqId) {
    var data = this.data();
    if (!data) return false;
    var loci = residueLoci(data, chainId, seqId);
    if (!loci) return false;
    this.plugin.managers.camera.focusLoci(loci);
    this.plugin.managers.structure.selection.fromLoci("set", loci);
    this.plugin.managers.interactivity.lociHighlights.highlightOnly({ loci: loci });
    return true;
  };

  Wrapper.prototype.highlightResidue = function (chainId, seqId) {
    var data = this.data();
    if (!data) return;
    var loci = residueLoci(data, chainId, seqId);
    if (loci) this.plugin.managers.interactivity.lociHighlights.highlightOnly({ loci: loci });
  };

  Wrapper.prototype.clearHighlight = function () {
    if (this.plugin.managers.interactivity) {
      this.plugin.managers.interactivity.lociHighlights.clearHighlights();
    }
  };

  Wrapper.prototype.focusChain = function (chainId) {
    var data = this.data();
    if (!data) return false;
    var loci = chainLoci(data, chainId);
    if (!loci) return false;
    this.plugin.managers.camera.focusLoci(loci);
    return true;
  };

  /* The interaction pane's opening view: sit on the ligand with its contacts
     selected, close enough that the pocket fills the pane. */
  Wrapper.prototype.focusContacts = function (ligandChain, contacts) {
    var data = this.data();
    if (!data) return false;
    var elements = [];
    var ligand = ligandChain ? chainLoci(data, ligandChain) : null;
    if (ligand) elements = elements.concat(ligand.elements);
    (contacts || []).forEach(function (contact) {
      var loci = residueLoci(data, contact.chain, contact.resnr);
      if (loci) elements = elements.concat(loci.elements);
    });
    if (!elements.length) return false;
    var combined = { kind: "element-loci", structure: data, elements: elements };
    this.plugin.managers.camera.focusLoci(combined);
    this.plugin.managers.structure.selection.fromLoci("set", combined);
    return true;
  };

  Wrapper.prototype.dispose = function () {
    try { this.viewer.dispose(); } catch (err) { /* already gone */ }
  };

  window.BoltzViewer = {
    available: function () {
      return !!(window.molstar && window.molstar.Viewer) && hasWebGL();
    },
    /* Why it is not available, in words a reader can act on. The library failing
       to load and the browser having no WebGL are different problems with
       different fixes, and "the viewer did not work" covers neither. */
    reason: function () {
      if (!(window.molstar && window.molstar.Viewer)) {
        return "The 3D viewer library did not load, so the structure cannot be shown. " +
               "Everything else on this page still works.";
      }
      if (!hasWebGL()) {
        return "This browser has WebGL disabled or unavailable, which the 3D viewer needs. " +
               "The interactions and metrics are unaffected.";
      }
      return "";
    },
    create: function (host) {
      return window.molstar.Viewer.create(host, OPTIONS).then(function (viewer) {
        return new Wrapper(viewer, host);
      });
    },
  };
})();
