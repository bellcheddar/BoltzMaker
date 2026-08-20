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
    // durationMs 0, here and at every other focusLoci: Mol* animates the camera by
    // default, and an animation started before `up` is set lands after it and undoes
    // it. That is why the pockets pane kept coming back level however many times the
    // orientation code was called -- the orientation was applied and then animated
    // away a few frames later.
    this.plugin.managers.camera.focusLoci({
      kind: "element-loci", structure: data,
      elements: data.units.map(function (unit) {
        return { unit: unit, indices: allIndices(unit) };
      }),
    }, { durationMs: 0 });
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

  /* Frame the camera on some of the loaded extras rather than all of them.

     A pane holding a dozen superposed receptors plus their ligands frames, with
     resetCamera, a box big enough for the receptors -- and on this campaign the
     ligands span 117A because a third of them docked onto the G protein instead
     of the receptor, so "everything" is an enormous box and the ligands inside it
     are sub-pixel. Mol*'s focusLoci takes an array and unions the bounding
     spheres, so a subset is one call. */
  Wrapper.prototype.frameExtras = function (names) {
    var self = this;
    var restoreUp = this._up;
    var loci = [];
    (names || Object.keys(this.extras)).forEach(function (name) {
      var entry = self.extras[name];
      var data = entry && entry.cell && entry.cell.obj && entry.cell.obj.data;
      if (!data || !data.units || !data.units.length) return;
      loci.push({
        kind: "element-loci", structure: data,
        elements: data.units.map(function (unit) {
          return { unit: unit, indices: allIndices(unit) };
        }),
      });
    });
    if (!loci.length) { this.resetCamera(); return false; }
    // A single-element array is not the array branch in Mol*'s own code, so hand
    // it the loci itself and let the ordinary path frame it.
    this.plugin.managers.camera.focusLoci(loci.length === 1 ? loci[0] : loci,
                                          { durationMs: 0 });
    if (restoreUp) this.orientUp(restoreUp);
    return true;
  };

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

  /* The orientation gizmo, off. It is a reasonable thing to have in a viewer the
     size of a card, and clutter in one the size of a stamp: in a 220px pair tile the
     axes cross is a fifth of the frame and sits over the molecule the tile exists to
     show. Set through canvas3d props because it is drawn into the WebGL scene, not
     into the DOM, so no amount of CSS reaches it. */
  /* Point the receptor's N-terminal end up the screen.

     For a class B GPCR that puts the extracellular domain on top and the
     transmembrane bundle below it, which is how these receptors are always drawn and
     how the membrane would sit. Mol* otherwise frames whatever orientation the
     coordinates happened to arrive in, so the same receptor faced a different way in
     every campaign and the two overlay panes disagreed with each other.

     Defined from the structure rather than as a fixed rotation, because a prediction
     has no canonical frame: "up" is the direction from the centroid of the C-terminal
     bulk to the centroid of the N-terminal quarter. That is the ECD for a class B
     GPCR and is at worst arbitrary-but-stable for anything else.
  */
  function chainSpan(structure, chainId) {
    // Residue numbers and CA-ish positions for one chain, in sequence order.
    var points = [];
    structure.units.forEach(function (unit) {
      var hierarchy = unit.model.atomicHierarchy;
      if (!hierarchy || !hierarchy.residueAtomSegments) return;
      var conformation = unit.conformation;
      for (var i = 0; i < unit.elements.length; i++) {
        var element = unit.elements[i];
        if (chainId) {
          var chainIndex = hierarchy.chainAtomSegments.index[element];
          if (hierarchy.chains.auth_asym_id.value(chainIndex) !== chainId) continue;
        }
        var residueIndex = hierarchy.residueAtomSegments.index[element];
        points.push({
          seq: hierarchy.residues.auth_seq_id.value(residueIndex),
          x: conformation.x(element), y: conformation.y(element), z: conformation.z(element),
        });
      }
    });
    return points;
  }

  function centroidOf(points) {
    var n = points.length, x = 0, y = 0, z = 0;
    for (var i = 0; i < n; i++) { x += points[i].x; y += points[i].y; z += points[i].z; }
    return n ? [x / n, y / n, z / n] : null;
  }

  /* Point a given world-space vector up the screen.

     Split out of orientNTerminusUp because the overlay panes cannot derive the axis
     from what they draw: their traces are the shared core the targets agree on, which
     on a class B GPCR excludes the extracellular domain entirely (measured: residues
     148-420, nothing below 140). The server sends the axis computed from the
     reference's full chain instead, and every overlay file is already in that frame.
  */
  Wrapper.prototype.orientUp = function (up) {
    if (!up || up.length !== 3 || !this.plugin.canvas3d) return this;
    // Remembered so a later re-frame can restore it: the pockets pane re-frames on
    // every row click, and each of those would otherwise level the camera again.
    this._up = up;
    var length = Math.sqrt(up[0] * up[0] + up[1] * up[1] + up[2] * up[2]);
    if (!length || !isFinite(length)) return this;
    return this._applyUp([up[0] / length, up[1] / length, up[2] / length]);
  };

  Wrapper.prototype.orientNTerminusUp = function (chainId) {
    var data = this.data();
    if (!data) {
      // The overlay panes hold only extras, so there is no "the" structure; the first
      // one loaded stands in, and they are superposed on each other anyway.
      var names = Object.keys(this.extras);
      for (var i = 0; i < names.length && !data; i++) {
        var entry = this.extras[names[i]];
        data = entry && entry.cell && entry.cell.obj && entry.cell.obj.data;
      }
    }
    if (!data || !data.units || !this.plugin.canvas3d) return this;

    var points = chainSpan(data, chainId);
    if (points.length < 20 && chainId) points = chainSpan(data, null);
    if (points.length < 20) return this;
    points.sort(function (a, b) { return a.seq - b.seq; });

    var head = centroidOf(points.slice(0, Math.max(1, Math.floor(points.length * 0.25))));
    var tail = centroidOf(points.slice(Math.floor(points.length * 0.5)));
    if (!head || !tail) return this;
    var up = [head[0] - tail[0], head[1] - tail[1], head[2] - tail[2]];
    var length = Math.sqrt(up[0] * up[0] + up[1] * up[1] + up[2] * up[2]);
    if (!length || !isFinite(length)) return this;
    up = [up[0] / length, up[1] / length, up[2] / length];

    return this._applyUp(up);
  };

  Wrapper.prototype._applyUp = function (up) {
    var camera = this.plugin.canvas3d.camera;
    var snapshot = camera.getSnapshot ? camera.getSnapshot() : camera.state;
    var target = snapshot.target, position = snapshot.position;
    var view = [position[0] - target[0], position[1] - target[1], position[2] - target[2]];
    var distance = Math.sqrt(view[0] * view[0] + view[1] * view[1] + view[2] * view[2]) || 1;

    // Look at the molecule side-on: strip the up component out of the current view
    // direction so the camera sits level with the axis rather than down it, which
    // would show the receptor end-on with the ECD hidden behind the bundle.
    var dot = view[0] * up[0] + view[1] * up[1] + view[2] * up[2];
    var side = [view[0] - dot * up[0], view[1] - dot * up[1], view[2] - dot * up[2]];
    var sideLength = Math.sqrt(side[0] * side[0] + side[1] * side[1] + side[2] * side[2]);
    if (sideLength < 1e-3) {
      // The view was straight down the axis, so any perpendicular will do.
      side = Math.abs(up[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
      dot = side[0] * up[0] + side[1] * up[1] + side[2] * up[2];
      side = [side[0] - dot * up[0], side[1] - dot * up[1], side[2] - dot * up[2]];
      sideLength = Math.sqrt(side[0] * side[0] + side[1] * side[1] + side[2] * side[2]);
    }
    side = [side[0] / sideLength * distance, side[1] / sideLength * distance,
            side[2] / sideLength * distance];

    // `camera.setState`, not `managers.camera.setSnapshot`: the manager applies
    // position and target and silently drops `up`, so the molecule moved and the
    // camera stayed level -- measured, up came back [0,1,0] against a computed axis
    // of [0.759, 0.538, 0.367]. Vec3s here are Float32Array, and gl-matrix writes
    // through them component-wise, so the arrays are converted rather than passed raw.
    var vec = function (a) { return new Float32Array([a[0], a[1], a[2]]); };
    camera.setState({
      target: vec(target),
      position: vec([target[0] + side[0], target[1] + side[1], target[2] + side[2]]),
      up: vec(up),
    }, 0);
    this.plugin.canvas3d.requestDraw();
    return this;
  };

  Wrapper.prototype.hideAxes = function () {
    if (!this.plugin.canvas3d) return this;
    this.plugin.canvas3d.setProps({
      camera: { helper: { axes: { name: "off", params: {} } } },
    });
    return this;
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
