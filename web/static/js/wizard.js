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
