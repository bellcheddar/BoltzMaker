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

  //: The ligand's colour in both viewers. Bright enough to find in a pocket, and
  //: not on the chain-id scale the protein is drawn from.
  var LIGAND_RED = 0xd81b60;

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
    this.overlay = null;
    this.pocket = null;
    this.extras = {};
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
      self.overlay = null;          // cleared with the scene by plugin.clear()
      self.pocket = null;
      self.extras = {};
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

  /* Chains for the protein, one flat red for the ligand.

     Colouring everything by chain-id gave the ligand a colour off the same scale
     as the protein chains, so on a five-chain complex it was the fifth colour in
     a series rather than the thing the campaign is about. Applied per component,
     which is why this cannot be a single call. */
  Wrapper.prototype.colourByChain = function () {
    if (!this.structure) return Promise.resolve();
    var manager = this.plugin.managers.structure.component;
    var polymer = [], ligand = [];
    this.components().forEach(function (component) {
      var key = component.key || "";
      (key.indexOf("ligand") >= 0 ? ligand : polymer).push(component);
    });
    var work = [];
    if (polymer.length) {
      work.push(manager.updateRepresentationsTheme(polymer, { color: "chain-id" }));
    }
    if (ligand.length) {
      work.push(manager.updateRepresentationsTheme(
        ligand, { color: "uniform", colorParams: { value: LIGAND_RED } }));
    }
    return Promise.all(work);
  };

  Wrapper.prototype.setSpin = function (on) {
    this.spinning = !!on;
    if (!this.plugin.canvas3d) return;
    this.plugin.canvas3d.setProps({
      trackball: { animate: on ? { name: "spin", params: { speed: 0.7 } }
                              : { name: "off", params: {} } },
    });
  };

  /* Everything, framed. Mol*'s own reset restores the camera it last considered
     "home", which after a focusLoci is that residue -- so this asks for the whole
     structure explicitly rather than for whatever home happens to be. */
  Wrapper.prototype.resetCamera = function () {
    var data = this.data();
    if (!data) {
      // The overlay panes hold only extras -- no "the" structure -- so there is
      // nothing for the loci route to frame and Mol*'s own reset is right.
      if (this.plugin.managers.camera) this.plugin.managers.camera.reset();
      return;
    }
    this.plugin.managers.interactivity.lociSelects.deselectAll();
    this.plugin.managers.camera.focusLoci({
      kind: "element-loci", structure: data,
      elements: data.units.map(function (unit) {
        return { unit: unit, indices: allIndices(unit) };
      }),
    });
  };

  function allIndices(unit) {
    var indices = new Int32Array(unit.elements.length);
    for (var i = 0; i < indices.length; i++) indices[i] = i;
    return indices;
  }

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
    // Framed, not selected. Mol* paints a selection bright green over whatever
    // theme is underneath, so leaving the ligand and its contacts selected made
    // the ligand green in a pane whose whole point was to show it red -- and the
    // contacts are already named in the list and marked on the sequence track.
    this.plugin.managers.camera.focusLoci(combined);
    return true;
  };

  /* A second structure in the same scene, already in the right frame -- the
     superposition was done server-side, so nothing here has to align anything.
     Held as its own hierarchy entry so removing it cannot take the prediction
     with it. */
  Wrapper.prototype.addOverlay = function (url) {
    var self = this;
    if (self.overlay) return Promise.resolve(true);
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error("overlay request failed (" + response.status + ")");
      return response.text();
    }).then(function (cif) {
      var before = self.plugin.managers.structure.hierarchy.current.structures.length;
      return self.viewer.loadStructureFromData(cif, "mmcif").then(function () {
        var structures = self.plugin.managers.structure.hierarchy.current.structures;
        if (structures.length <= before) throw new Error("the overlay did not load");
        self.overlay = structures[structures.length - 1];
        // One flat colour, so the overlay reads as a reference rather than as a
        // second thing coloured by the same scheme as the prediction.
        return self.plugin.managers.structure.component.updateRepresentationsTheme(
          self.overlay.components,
          { color: "uniform", colorParams: { value: 0x9b51e0 } });
      });
    }).then(function () { return true; });
  };

  Wrapper.prototype.removeOverlay = function () {
    if (!this.overlay) return Promise.resolve(false);
    var overlay = this.overlay;
    this.overlay = null;
    try {
      return Promise.resolve(
        this.plugin.managers.structure.hierarchy.remove([overlay])
      ).then(function () { return true; });
    } catch (err) {
      return Promise.resolve(false);
    }
  };

  Wrapper.prototype.hasOverlay = function () { return !!this.overlay; };

  /* An extra structure in the scene, kept by name so it can be hidden and shown
     again without reloading. Used by the two overlay panes, which hold one per
     target and toggle them from a checkbox. */
  Wrapper.prototype.loadExtra = function (name, url, options) {
    var self = this;
    options = options || {};
    if (self.extras[name]) return Promise.resolve(self.extras[name]);
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(response.status + " for " + name);
      return response.text();
    }).then(function (cif) {
      var before = self.plugin.managers.structure.hierarchy.current.structures.length;
      return self.viewer.loadStructureFromData(cif, "mmcif").then(function () {
        var structures = self.plugin.managers.structure.hierarchy.current.structures;
        if (structures.length <= before) throw new Error("nothing loaded for " + name);
        var entry = structures[structures.length - 1];
        self.extras[name] = entry;
        // Type FIRST, then colour, and in series -- not Promise.all. Changing a
        // representation's type rebuilds it with that type's default colour theme,
        // so a uniform colour applied concurrently is overwritten by whatever the
        // rebuild chose: element colours on a ligand (carbon grey, oxygen red,
        // nitrogen blue) and chain colours on a receptor. That is exactly the
        // "everything is a different colour" the pockets pane showed when it asked
        // for grey backbones and one-colour-per-pocket spheres.
        var done = Promise.resolve();
        if (options.type) {
          entry.components.forEach(function (component) {
            if (!component.representations.length) return;
            done = done.then(function () {
              return self.plugin.managers.structure.component.updateRepresentations(
                [component], component.representations[0],
                { type: { name: options.type, params: options.typeParams || {} } });
            });
          });
        }
        if (options.color !== undefined) {
          done = done.then(function () {
            return self.plugin.managers.structure.component.updateRepresentationsTheme(
              entry.components, { color: "uniform", colorParams: { value: options.color } });
          });
        }
        return done.then(function () { return entry; });
      });
    });
  };

  Wrapper.prototype.setExtraVisible = function (name, visible) {
    var entry = this.extras[name];
    if (!entry) return;
    var manager = this.plugin.managers.structure.hierarchy;
    // toggleVisibility flips whatever the current state is, so it is only safe to
    // call when the current state is known to differ from the wanted one.
    var hidden = !!(entry.cell && entry.cell.state && entry.cell.state.isHidden);
    if (hidden === !visible) return;
    manager.toggleVisibility([entry]);
  };

  Wrapper.prototype.frameAll = function () { this.resetCamera(); };

  /* Closest atom of a residue (or chain) to a reference point, as a one-atom
     loci. A contact is between two atoms, and a dashed line drawn between two
     whole residues is drawn between their centroids -- which for a tryptophan
     against a ligand is several angstrom from where the contact actually is. */
  function closestAtomLoci(structure, loci, target) {
    var best = null;
    loci.elements.forEach(function (element) {
      var unit = element.unit;
      var conformation = unit.conformation;
      for (var i = 0; i < element.indices.length; i++) {
        var index = element.indices[i];
        var id = unit.elements[index];
        var x = conformation.x(id), y = conformation.y(id), z = conformation.z(id);
        var distance = target
          ? Math.sqrt(Math.pow(x - target[0], 2) + Math.pow(y - target[1], 2) +
                      Math.pow(z - target[2], 2))
          : 0;
        if (!best || distance < best.distance) {
          best = { distance: distance, unit: unit, index: index, point: [x, y, z] };
        }
      }
    });
    if (!best) return null;
    return {
      loci: { kind: "element-loci", structure: structure,
              elements: [{ unit: best.unit, indices: new Int32Array([best.index]) }] },
      point: best.point,
    };
  }

  function centroidOf(loci) {
    var sum = [0, 0, 0], count = 0;
    loci.elements.forEach(function (element) {
      var conformation = element.unit.conformation;
      for (var i = 0; i < element.indices.length; i++) {
        var id = element.unit.elements[element.indices[i]];
        sum[0] += conformation.x(id);
        sum[1] += conformation.y(id);
        sum[2] += conformation.z(id);
        count++;
      }
    });
    return count ? [sum[0] / count, sum[1] / count, sum[2] / count] : null;
  }

  /* Each contact PLIP found, drawn: a dashed line between the two closest atoms
     with the distance on it.

     Mol* has an `interactions` representation that would compute its own, but it
     only sees the component it is given, and this build has no query language to
     build a "ligand plus surroundings" component with -- on the ligand alone it
     finds nothing and draws nothing. Measurements need no component, and drawing
     the contacts PLIP reported keeps the picture and the list beside it the same
     set of facts rather than two opinions. */
  Wrapper.prototype.showInteractions = function (ligandChain, contacts) {
    var data = this.data();
    var measurement = this.plugin.managers.structure.measurement;
    if (!data || !measurement || !ligandChain) return 0;
    var ligand = chainLoci(data, ligandChain);
    if (!ligand) return 0;
    var ligandCentre = centroidOf(ligand);
    var drawn = 0;
    (contacts || []).forEach(function (contact) {
      var residue = residueLoci(data, contact.chain, contact.resnr);
      if (!residue) return;
      // Nearest residue atom to the ligand, then nearest ligand atom to THAT --
      // one pass from each side lands on the pair actually in contact.
      var residueAtom = closestAtomLoci(data, residue, ligandCentre);
      if (!residueAtom) return;
      var ligandAtom = closestAtomLoci(data, ligand, residueAtom.point);
      if (!ligandAtom) return;
      try {
        measurement.addDistance(ligandAtom.loci, residueAtom.loci);
        drawn++;
      } catch (err) { /* one contact failing is not the whole pocket */ }
    });
    return drawn;
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
