// Vanilla JS add/remove-row for the wizard's repeating blocks (partners, proteins,
// constraints, ligands). No build step, no framework -- clones a <template>, appends
// it, wires up its own remove button. All real validation happens server-side
// (wizard.py/views_new.py); this only makes the form usable.
//
// Exposes BoltzWizard so the Prepare page's save/restore layer (form_state.js) can
// rebuild rows without duplicating the template ids or the remove-button wiring.
var BoltzWizard = (function () {
  "use strict";

  // One entry per repeating block. form_state.js reads this rather than keeping its
  // own copy: two lists of template ids that must agree is one list too many.
  var GROUPS = [
    { key: "protein", button: "add-protein", template: "tpl-protein", container: "protein-rows", seed: true },
    { key: "partner", button: "add-partner", template: "tpl-partner", container: "partner-rows", seed: false },
    { key: "constraint", button: "add-constraint", template: "tpl-constraint", container: "constraint-rows", seed: false },
    { key: "ligand", button: "add-ligand", template: "tpl-ligand", container: "ligand-rows", seed: true }
  ];

  function wireRemove(rowEl) {
    var btn = rowEl.querySelector(".md-remove-row");
    if (btn) {
      btn.addEventListener("click", function () {
        rowEl.remove();
        renumberAll();
        document.dispatchEvent(new CustomEvent("boltz:form-changed"));
      });
    }
  }

  function addRow(templateId, containerId) {
    var tpl = document.getElementById(templateId);
    var container = document.getElementById(containerId);
    if (!tpl || !container) return null;
    container.appendChild(tpl.content.cloneNode(true));
    // The fragment's nodes were moved by appendChild, so re-query the attached row.
    var rowEl = container.lastElementChild;
    wireRemove(rowEl);
    return rowEl;
  }

  // Row-ordinal stamping. Checkboxes inside repeating rows post nothing when
  // unchecked, so a shared name="x[]" cannot say WHICH rows were ticked. Giving each
  // one its row index as its value turns the post into a set of indices, which is
  // unambiguous however many are left unticked.
  function renumber(group) {
    var container = document.getElementById(group.container);
    if (!container) return;
    var rows = container.querySelectorAll(".md-repeat-block");
    for (var i = 0; i < rows.length; i++) {
      var boxes = rows[i].querySelectorAll('input[type="checkbox"][name$="[]"]');
      for (var j = 0; j < boxes.length; j++) boxes[j].value = String(i);
    }
  }

  function renumberAll() {
    GROUPS.forEach(renumber);
  }

  function groupFor(key) {
    for (var i = 0; i < GROUPS.length; i++) {
      if (GROUPS[i].key === key) return GROUPS[i];
    }
    return null;
  }

  function addRowFor(key) {
    var group = groupFor(key);
    return group ? addRow(group.template, group.container) : null;
  }

  function clearRows(key) {
    var group = groupFor(key);
    if (!group) return;
    var container = document.getElementById(group.container);
    if (container) container.innerHTML = "";
  }

  function wireAdd(group) {
    var btn = document.getElementById(group.button);
    if (!btn) return;
    btn.addEventListener("click", function () {
      addRow(group.template, group.container);
      renumber(group);
      document.dispatchEvent(new CustomEvent("boltz:form-changed"));
    });
    if (group.seed) addRow(group.template, group.container);
  }

  document.addEventListener("DOMContentLoaded", function () {
    GROUPS.forEach(wireAdd);
    renumberAll();
    // Announce that the default rows exist, so anything restoring saved state knows
    // the DOM it is about to replace is ready.
    document.dispatchEvent(new CustomEvent("boltz:wizard-ready"));
  });

  return { GROUPS: GROUPS, addRowFor: addRowFor, clearRows: clearRows,
           renumber: renumber, renumberAll: renumberAll };
})();

/* UniProt autofill.

   Typing an accession fills that row's short name and sequence. Delegated from
   the document rather than bound per input, because rows are cloned from a
   <template> at any time and a handler bound at load would never reach them.

   It fills only empty fields. Someone who has pasted their own construct and
   then names the accession for the AlphaFold overlay must not have that
   construct silently replaced by the canonical sequence -- the two are often
   different on purpose, which is the whole reason the accession is asked for
   separately. */
(function () {
  "use strict";

  var LOOKUP = "/auto/uniprot/";

  function noteFor(input) {
    var field = input.closest(".md-uniprot-field");
    return field ? field.querySelector(".md-uniprot-note") : null;
  }

  function rowFields(input) {
    var row = input.closest(".md-repeat-block");
    if (!row) return null;
    var kind = input.getAttribute("data-uniprot-for");
    return {
      name: row.querySelector('[name="' + kind + '_name[]"]'),
      sequence: row.querySelector('[name="' + kind + '_sequence[]"]'),
    };
  }

  function fill(input) {
    var accession = (input.value || "").trim().toUpperCase().split("-")[0].split(".")[0];
    if (!accession) return;
    input.value = accession;
    var note = noteFor(input);
    var fields = rowFields(input);
    if (!fields) return;
    if (note) note.textContent = "Looking up " + accession + "…";

    fetch(LOOKUP + encodeURIComponent(accession) + ".json")
      .then(function (response) { return response.json(); })
      .then(function (entry) {
        if (entry.error) {
          if (note) note.textContent = entry.error;
          return;
        }
        var filled = [];
        if (fields.name && !fields.name.value.trim() && entry.gene) {
          fields.name.value = entry.gene;
          filled.push("short name");
        }
        if (fields.sequence && !fields.sequence.value.trim() && entry.sequence) {
          fields.sequence.value = entry.sequence;
          filled.push(entry.length + " residues");
        }
        if (note) {
          note.textContent = entry.entry + " · " + (entry.name || entry.accession)
            + (entry.organism ? " (" + entry.organism + ")" : "")
            + (filled.length ? " — filled in " + filled.join(" and ") + "."
                             : " — left what you had already typed.");
        }
      })
      .catch(function () {
        if (note) note.textContent = "UniProt could not be reached.";
      });
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (input && input.matches && input.matches("[data-uniprot-for]")) fill(input);
  });
})();

/* Enter must not submit the form.

   A form with a submit button submits on Enter from any text input, which on a
   page like this means: type a protein name, press Enter out of habit, and the
   server answers "At least one ligand is required" -- an error about the bottom
   of the page while you are still filling in the top. Adding the UniProt boxes
   made it worse, because Enter is exactly what anyone types after an accession.

   Textareas keep Enter: a sequence is pasted into one and newlines belong there.
   The submit button keeps it too, so the form can still be sent from the
   keyboard by anyone who has tabbed to it deliberately. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("wizard-form");
    if (!form) return;
    form.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.shiftKey) return;
      var el = event.target;
      if (!el || !el.tagName) return;
      var tag = el.tagName.toLowerCase();
      if (tag === "textarea") return;
      if (tag === "button" || (tag === "input" && el.type === "submit")) return;
      event.preventDefault();
      // Enter on an accession should do the obvious thing rather than nothing.
      if (el.matches && el.matches("[data-uniprot-for]")) {
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });
})();

/* Take the page to the error.

   The server says what is missing; the sections say where it lives. On a form
   this long "at least one ligand is required" can be two screens below the
   protein someone was filling in when they triggered it, which reads as the page
   objecting to what they were doing rather than to what they had not reached
   yet. */
(function () {
  "use strict";

  //: Which section a failed field belongs to. The parser's field names are the
  //: keys because they are what the error already carries.
  var SECTIONS = {
    proteins: "protein-rows", protein_name: "protein-rows",
    protein_sequence: "protein-rows", protein_partners: "protein-rows",
    protein_apo_pdb: "protein-rows", protein_uniprot: "protein-rows",
    partner_name: "partner-rows", partner_sequence: "partner-rows",
    partner_uniprot: "partner-rows",
    constraint_owner: "constraint-rows", constraint_kind: "constraint-rows",
    ligands: "ligand-rows", ligand_name: "ligand-rows", ligand_value: "ligand-rows",
    campaign_name: "campaign_name",
  };

  document.addEventListener("DOMContentLoaded", function () {
    var alert = document.getElementById("form-error");
    if (!alert) return;
    var field = alert.getAttribute("data-field") || "";
    var target = document.getElementById(SECTIONS[field] || "");
    if (!target) return;
    var card = target.closest(".md-card") || target;
    card.classList.add("md-card-needs-attention");
    // After the restore, which rebuilds the rows and would otherwise scroll the
    // page out from under this.
    window.setTimeout(function () {
      card.scrollIntoView({ behavior: "smooth", block: "start" });
      var first = card.querySelector("input, textarea, select");
      if (first) first.focus({ preventScroll: true });
    }, 250);
  });
})();

/* "Use same pocket": list the ligands in each LIGAND row's holo reference and let
   the user pick which one defines that ligand's pocket.

   Per ligand rather than per protein because a pocket belongs to the pair: measured
   on GLP1R/GIPR, orforglipron's site on GLP1R and LSN1's site on GIPR share 3
   residues out of ~60. Waters, ions, buffers, sugars and lipids are filtered
   server-side in pocket.py, so this file never has to know that cholesterol is not a
   ligand -- and an empty list is a real answer that gets said out loud.  */
(function () {
  var LOOKUP = "/auto/pocket-ligands/";
  var toggle = document.getElementById("use-same-pocket");
  if (!toggle) return;

  function showHide() {
    var on = toggle.checked;
    var dist = document.querySelector(".md-pocket-distance");
    if (dist) dist.hidden = !on;
    var fields = document.querySelectorAll(".md-pocket-field");
    for (var i = 0; i < fields.length; i++) fields[i].hidden = !on;
    if (on) {
      var ids = document.querySelectorAll('input[name="ligand_pocket_pdb[]"]');
      for (var j = 0; j < ids.length; j++) if (ids[j].value.trim()) load(ids[j]);
    }
  }

  function partsFor(input) {
    var row = input.closest(".md-row") || input.parentNode.parentNode;
    return {
      select: row ? row.querySelector('select[name="ligand_pocket_ligand[]"]') : null,
      status: row ? row.querySelector(".md-pocket-status") : null
    };
  }

  function load(input) {
    var p = partsFor(input);
    if (!p.select || !p.status) return;
    var id = input.value.trim();
    if (!id) { p.status.textContent = "Enter a holo PDB id above to list its ligands."; return; }
    p.status.textContent = "Looking up ligands in " + id.toUpperCase() + "\u2026";
    fetch(LOOKUP + encodeURIComponent(id) + ".json")
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        while (p.select.options.length > 1) p.select.remove(1);
        if (!res.ok) { p.status.textContent = res.d.error || "Lookup failed."; return; }
        var ligands = res.d.ligands || [];
        if (!ligands.length) {
          p.status.textContent = res.d.pdb_id + " has no ligand that could define a pocket "
            + "\u2014 only waters, ions, sugars or lipids. That is an apo structure, not a "
            + "holo one; pick a structure with this ligand bound.";
          return;
        }
        for (var i = 0; i < ligands.length; i++) {
          var o = document.createElement("option");
          o.value = ligands[i].key;
          o.textContent = ligands[i].label;
          p.select.appendChild(o);
        }
        p.select.selectedIndex = 1;      /* largest, which the endpoint sorts first */
        p.status.textContent = ligands.length === 1
          ? "One ligand found; its pocket will be used."
          : ligands.length + " ligands found \u2014 the largest is selected.";
      })
      .catch(function () { p.status.textContent = "Could not reach the server."; });
  }

  toggle.addEventListener("change", showHide);
  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!toggle.checked || !el || !el.matches) return;
    if (el.matches('input[name="ligand_pocket_pdb[]"]')) load(el);
  });
  document.addEventListener("click", function (event) {
    if (event.target && event.target.id === "add-ligand") setTimeout(showHide, 0);
  });
  showHide();
})();
