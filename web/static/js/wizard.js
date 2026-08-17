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

/* "Use same pocket": repeatable pocket references on each protein row.

   Each reference names a site the protein's ligands are run against, alongside an
   unconstrained baseline. `pocket_owner[]` carries the ordinal of the protein row a
   pocket sits in, restamped on every change and again on submit: these rows repeat
   inside a repeating row, so position alone cannot say which protein a pocket belongs
   to once any row is added or removed.

   Waters, ions, buffers, sugars and lipids are filtered server-side in pocket.py, so
   this file never has to know that cholesterol is not a ligand, and an empty list is a
   real answer that gets said out loud.  */
(function () {
  var LOOKUP = "/auto/pocket-ligands/";
  var toggle = document.getElementById("use-same-pocket");
  if (!toggle) return;

  function proteinRows() {
    var c = document.getElementById("protein-rows");
    return c ? c.querySelectorAll(".md-repeat-block") : [];
  }

  /* Ordinals are only meaningful at the moment they are read, so restamp rather than
     trusting whatever a cloned row happened to carry. */
  function restamp() {
    var rows = proteinRows();
    for (var i = 0; i < rows.length; i++) {
      var owners = rows[i].querySelectorAll('input[name="pocket_owner[]"]');
      for (var j = 0; j < owners.length; j++) owners[j].value = String(i);
    }
  }

  function setEnabled() {
    var on = toggle.checked;
    var dist = document.querySelector(".md-pocket-distance");
    if (dist) dist.hidden = false;
    var controls = document.querySelectorAll(
      '.md-pocket-distance input, .add-pocket, .md-pocket-row input, .md-pocket-row select');
    for (var i = 0; i < controls.length; i++) controls[i].disabled = !on;
  }

  function statusOf(row) { return row.querySelector(".md-pocket-status"); }

  function load(input) {
    var row = input.closest(".md-pocket-row");
    if (!row) return;
    var select = row.querySelector('select[name="pocket_ligand[]"]');
    var status = statusOf(row);
    var id = input.value.trim();
    if (!select || !status) return;
    if (!id) { status.textContent = "Waters, ions, sugars and lipids are filtered out."; return; }
    status.textContent = "Looking up ligands in " + id.toUpperCase() + "\u2026";
    fetch(LOOKUP + encodeURIComponent(id) + ".json")
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        while (select.options.length > 1) select.remove(1);
        if (!res.ok) { status.textContent = res.d.error || "Lookup failed."; return; }
        var ligands = res.d.ligands || [];
        if (!ligands.length) {
          status.textContent = res.d.pdb_id + " has no ligand that could define a pocket "
            + "\u2014 only waters, ions, sugars or lipids. That is an apo structure; a pocket "
            + "needs a holo one.";
          return;
        }
        for (var i = 0; i < ligands.length; i++) {
          var o = document.createElement("option");
          o.value = ligands[i].key;
          o.textContent = ligands[i].label;
          select.appendChild(o);
        }
        select.selectedIndex = 1;      /* largest, which the endpoint sorts first */
        status.textContent = ligands.length === 1
          ? "One ligand found; its site will be used."
          : ligands.length + " ligands found \u2014 the largest is selected.";
      })
      .catch(function () { status.textContent = "Could not reach the server."; });
  }

  document.addEventListener("click", function (event) {
    var el = event.target;
    if (!el || !el.matches) return;
    if (el.matches(".add-pocket")) {
      var host = el.closest(".md-repeat-block");
      var container = host ? host.querySelector(".md-pocket-rows") : null;
      var tpl = document.getElementById("tpl-pocket");
      if (container && tpl) {
        container.appendChild(tpl.content.cloneNode(true));
        var added = container.lastElementChild;
        var remove = added.querySelector(".md-remove-row");
        if (remove) remove.addEventListener("click", function () {
          added.parentNode.removeChild(added); restamp();
        });
        restamp(); setEnabled();
      }
    }
    if (el.id === "add-protein") setTimeout(function () { restamp(); setEnabled(); }, 0);
  });

  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!el || !el.matches) return;
    if (el === toggle) setEnabled();
    if (el.matches('input[name="pocket_pdb[]"]')) load(el);
  });

  /* Ordinals must be right at submit time above all. */
  var form = document.querySelector("form");
  if (form) form.addEventListener("submit", restamp);

  restamp(); setEnabled();
})();
