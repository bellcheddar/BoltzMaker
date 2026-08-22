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

  /* Examples that change down a repeating list. Every row is cloned from the same
     <template>, so without this the second and third partner rows both read "e.g.
     GNAS" -- which reads as a suggestion to type GNAS three times rather than as a
     heterotrimer. Placeholders only: they are grey, never submitted, and vanish the
     moment anything is typed. */
  var ROW_EXAMPLES = {
    "partner_name[]": ["e.g. GNAS", "e.g. GNB1", "e.g. GNG2"],
    "partner_uniprot[]": ["e.g. P63092 (GNAS)", "e.g. P62873 (GNB1)", "e.g. P59768 (GNG2)"],
    "pocket_pdb[]": ["e.g. 7E14", "e.g. 7RBT"],
  };

  /* Shared, because the pocket rows are added from a second IIFE further down this
     file and a function declared in this one is not in scope there. */
  window.BoltzWizardRows = window.BoltzWizardRows || {};
  window.BoltzWizardRows.stamp = stampExamples;

  function stampExamples(container) {
    if (!container) return;
    Object.keys(ROW_EXAMPLES).forEach(function (name) {
      var inputs = container.querySelectorAll('input[name="' + name + '"]');
      for (var i = 0; i < inputs.length; i++) {
        var examples = ROW_EXAMPLES[name];
        // Past the end of the list the last example stands rather than a blank: a
        // fourth partner still wants to be shown the shape of the thing.
        inputs[i].placeholder = examples[Math.min(i, examples.length - 1)];
      }
    });
  }

  function addRow(templateId, containerId) {
    var tpl = document.getElementById(templateId);
    var container = document.getElementById(containerId);
    if (!tpl || !container) return null;
    container.appendChild(tpl.content.cloneNode(true));
    // The fragment's nodes were moved by appendChild, so re-query the attached row.
    var rowEl = container.lastElementChild;
    wireRemove(rowEl);
    stampExamples(container);
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
      // File inputs are named per row rather than as a `name[]` array: an empty one
      // posts nothing, so the array would be shorter than every other field and each
      // uploaded file would land on the wrong protein. The ordinal is in the name,
      // so the server can pair them by row however many are left empty.
      var uploads = rows[i].querySelectorAll("[data-apo-upload]");
      for (var k = 0; k < uploads.length; k++) {
        uploads[k].name = "protein_apo_file_" + i;
      }
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

  /* Setting .value in script fires nothing, so anything listening for the field to
     change never hears it. A partner filled in from its accession therefore did not
     appear in the proteins' partner pickers until some later edit happened to
     trigger a re-sync -- which read as "partners only show up when I add another
     one". Autosave missed it the same way: an autofilled name and sequence were not
     written to browser storage until the next keystroke elsewhere. */
  function setFilled(field, value) {
    field.value = value;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
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
          setFilled(fields.name, entry.gene);
          filled.push("short name");
        }
        if (fields.sequence && !fields.sequence.value.trim() && entry.sequence) {
          setFilled(fields.sequence, entry.sequence);
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

  /* Direct children only. Pocket rows are themselves .md-repeat-block and are nested
     inside protein rows, so a descendant query returns protein0, pocket0, protein1,
     pocket1... -- the indices shift and every pocket ends up stamped with the wrong
     owner. That put a pocket meant for the first protein onto the second in a real
     campaign. */
  function proteinRows() {
    var c = document.getElementById("protein-rows");
    return c ? c.querySelectorAll(":scope > .md-repeat-block") : [];
  }

  /* Ordinals are only meaningful at the moment they are read, so restamp rather than
     trusting whatever a cloned row happened to carry. */
  function restamp() {
    var rows = proteinRows();
    for (var i = 0; i < rows.length; i++) {
      // Only this protein's own pocket container, so nothing can reach across rows.
      var container = rows[i].querySelector(".md-pocket-rows");
      if (!container) continue;
      var owners = container.querySelectorAll('input[name="pocket_owner[]"]');
      for (var j = 0; j < owners.length; j++) owners[j].value = String(i);
    }
  }

  /* Nothing is disabled. Gating the controls on the checkbox meant they depended on
     an event that a restored form never fires, which left the Add button dead for
     anyone with a saved page. Adding a pocket reference is a clear enough statement
     of intent to tick the box itself. */
  function setEnabled() {
    var dist = document.querySelector(".md-pocket-distance");
    if (dist) dist.hidden = false;
  }

  function addPocketRow(host) {
    var container = host ? host.querySelector(".md-pocket-rows") : null;
    var tpl = document.getElementById("tpl-pocket");
    if (!container || !tpl) return null;
    container.appendChild(tpl.content.cloneNode(true));
    window.BoltzWizardRows.stamp(container);
    var added = container.lastElementChild;
    var remove = added.querySelector(".md-remove-row");
    if (remove) remove.addEventListener("click", function () {
      added.parentNode.removeChild(added); restamp();
    });
    restamp();
    return added;
  }

  /* Every protein starts with one empty pocket row, so the fields are on screen
     rather than behind a button someone has to know to press. */
  function seedRows() {
    var rows = proteinRows();
    for (var i = 0; i < rows.length; i++) {
      var container = rows[i].querySelector(".md-pocket-rows");
      if (container && !container.querySelector(".md-pocket-row")) addPocketRow(rows[i]);
    }
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
      addPocketRow(el.closest(".md-repeat-block"));
    }
    if (el.id === "add-protein") setTimeout(function () { restamp(); setEnabled(); }, 0);
  });

  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!el || !el.matches) return;
    if (el.matches('input[name="pocket_pdb[]"]')) load(el);
  });

  /* Ordinals must be right at submit time above all. */
  var form = document.querySelector("form");
  if (form) form.addEventListener("submit", restamp);

  /* Rows are seeded inside DOMContentLoaded, and this file runs before it, so a
     bare call here finds no rows and leaves the seeded row's button disabled
     forever. Re-sync on every event that can change the rows. */
  function sync() {
    seedRows(); restamp(); setEnabled();
    window.BoltzWizardRows.stamp(document.getElementById("partner-rows"));
    var pocketHosts = document.querySelectorAll(".md-pocket-rows");
    for (var i = 0; i < pocketHosts.length; i++) window.BoltzWizardRows.stamp(pocketHosts[i]);
  }
  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("boltz:wizard-ready", sync);
  document.addEventListener("boltz:form-changed", sync);
  document.addEventListener("boltz:form-restored", sync);
  sync();
  setTimeout(sync, 0);   /* after any restore that replaces rows */

  /* Used by form_state.js: pocket rows are nested inside protein rows, so the
     generic per-group save/restore cannot see them at all. */
  window.BoltzPockets = {
    clear: function (host) {
      var c = host ? host.querySelector(".md-pocket-rows") : null;
      if (c) c.innerHTML = "";
    },
    restoreRow: function (host, saved) {
      var row = addPocketRow(host);
      if (!row) return;
      var pdb = row.querySelector('input[name="pocket_pdb[]"]');
      var sel = row.querySelector('select[name="pocket_ligand[]"]');
      if (pdb && saved && saved.pdb) {
        pdb.value = saved.pdb;
        if (sel && saved.ligand) sel.setAttribute("data-restore", saved.ligand);
        load(pdb);            /* repopulates, then applies data-restore */
      }
    },
    rowsOf: function (host) {
      var out = [];
      var rows = host ? host.querySelectorAll(".md-pocket-row") : [];
      for (var i = 0; i < rows.length; i++) {
        var pdb = rows[i].querySelector('input[name="pocket_pdb[]"]');
        var sel = rows[i].querySelector('select[name="pocket_ligand[]"]');
        if (pdb && pdb.value.trim()) {
          out.push({ pdb: pdb.value.trim(), ligand: sel ? sel.value : "" });
        }
      }
      return out;
    }
  };
})();

/* Run summary: what this form will actually cost, recomputed as it is edited.

   The fan-out rule is BoltzMaker's own: each protein runs every ligand once
   unconstrained, plus once per pocket reference on that protein, and each
   ligand-free companion is a target in its own right. Predictions is the number
   worth watching -- it is what the run costs, and adding a second pocket to two
   proteins doubles it rather than adding two.  */
(function () {
  /* No early return on a missing table. This file is loaded from the end of
     _wizard_fields.html, which is included ABOVE the Run summary card, so at
     script-execution time the panel has not been parsed yet -- bailing out here
     meant no listeners were ever attached and the numbers never moved. Resolve it
     lazily instead, and no-op until it exists. */

  /* Sequence fields are textareas and short fields are inputs, so every lookup asks
     for both. Querying only `input` is what made Co-folded partners read 0 while
     three were entered. */
  function fields(name, root) {
    return (root || document).querySelectorAll(
      'input[name="' + name + '"], textarea[name="' + name + '"], select[name="' + name + '"]');
  }
  function filled(nodes) {
    var n = 0;
    for (var i = 0; i < nodes.length; i++) if (nodes[i].value.trim()) n++;
    return n;
  }
  function set(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function recount() {
    if (!document.querySelector(".md-run-summary")) return;
    var proteinRows = document.querySelectorAll("#protein-rows > .md-repeat-block");
    var ligands = filled(fields("ligand_value[]"));
    var partners = filled(fields("partner_sequence[]"));

    var proteins = 0, apo = 0, pockets = 0, predictions = 0;
    for (var i = 0; i < proteinRows.length; i++) {
      var row = proteinRows[i];
      var seq = fields("protein_sequence[]", row)[0];
      if (!seq || !seq.value.trim()) continue;         // a blank row is not a protein
      proteins++;
      var mine = 0;
      var pdbs = fields("pocket_pdb[]", row);
      var codes = fields("pocket_ligand[]", row);
      for (var j = 0; j < pdbs.length; j++) {
        if (pdbs[j].value.trim() && codes[j] && codes[j].value) mine++;
      }
      pockets += mine;
      // one unconstrained baseline per ligand, plus one per pocket
      predictions += ligands * (1 + mine);
      var predictApo = fields("protein_apo_predict[]", row)[0];
      if (predictApo && predictApo.checked) { apo++; predictions++; }
    }

    set("sum-proteins", proteins);
    set("sum-partners", partners);
    set("sum-ligands", ligands);
    set("sum-pockets", pockets);
    set("sum-apo", apo);
    set("sum-total", predictions);

    var note = document.getElementById("sum-proteins-note");
    if (note) note.textContent = partners
      ? "Each is folded with the " + partners + " partner chain" + (partners === 1 ? "" : "s") + "."
      : "Folded on their own.";
    var pnote = document.getElementById("sum-pockets-note");
    if (pnote) pnote.textContent = pockets
      ? "Each ligand also runs once unconstrained, so a protein with " +
        "N pockets gives N+1 runs per ligand."
      : "No pocket constraint; ligands fold freely and may land anywhere.";
    var tnote = document.getElementById("sum-total-note");
    if (tnote) {
      tnote.textContent = predictions
        ? "Roughly " + Math.round(predictions * 50 / 60 * 10) / 10 + " h at ~50 min each on one GPU."
        : "Add a protein and a ligand to see the count.";
    }
  }

  document.addEventListener("input", recount);
  document.addEventListener("change", recount);
  document.addEventListener("click", function () { setTimeout(recount, 0); });
  document.addEventListener("DOMContentLoaded", recount);
  document.addEventListener("boltz:wizard-ready", recount);
  document.addEventListener("boltz:form-changed", recount);
  recount();
  setTimeout(recount, 0);
})();

/* ---- Co-folded partners: tickboxes, not a typed list -----------------------

   The protein's partner list and the Partner blocks' short names had to agree
   exactly and were typed in two places. Renaming a partner after a protein
   referenced it, or one typo, failed validation at download time with the whole
   campaign already entered. The picker is built from the Partner rows themselves,
   so the two cannot disagree.

   It writes the same comma-separated `protein_partners[]` the server has always
   read. The visible tickboxes carry no name and are never posted -- one hidden
   input per protein row keeps the parallel arrays the same length, which is the
   thing that quietly breaks when a control posts nothing. */
(function () {
  "use strict";

  function partnerNames() {
    var seen = [];
    Array.prototype.forEach.call(
      document.querySelectorAll('[name="partner_name[]"]'), function (input) {
        var value = (input.value || "").trim();
        if (value && seen.indexOf(value) === -1) seen.push(value);
      });
    return seen;
  }

  function chosen(hidden) {
    return (hidden.value || "").split(",")
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function render(picker) {
    var row = picker.closest(".md-repeat-block");
    if (!row) return;
    var hidden = row.querySelector('[name="protein_partners[]"]');
    if (!hidden) return;

    var names = partnerNames();
    // Keep a selection whose partner has been renamed or removed, rather than
    // dropping it silently: it still shows, ticked, flagged as missing, so the
    // person can see what happened instead of finding the partner simply gone.
    var picked = chosen(hidden);
    var missing = picked.filter(function (n) { return names.indexOf(n) === -1; });

    if (!names.length && !missing.length) {
      picker.innerHTML = '<span class="md-partner-empty">No partners defined yet.</span>';
      return;
    }

    picker.innerHTML = "";
    names.concat(missing).forEach(function (name) {
      var isMissing = names.indexOf(name) === -1;
      var label = document.createElement("label");
      label.className = "md-partner-option" + (isMissing ? " md-partner-missing" : "");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.value = name;
      box.checked = picked.indexOf(name) !== -1;
      box.addEventListener("change", function () { commit(picker); });
      label.appendChild(box);
      label.appendChild(document.createTextNode(
        " " + name + (isMissing ? " (no such partner)" : "")));
      picker.appendChild(label);
    });
  }

  function commit(picker) {
    var row = picker.closest(".md-repeat-block");
    var hidden = row && row.querySelector('[name="protein_partners[]"]');
    if (!hidden) return;
    var picked = [];
    Array.prototype.forEach.call(
      picker.querySelectorAll('input[type="checkbox"]'), function (box) {
        if (box.checked) picked.push(box.value);
      });
    hidden.value = picked.join(", ");
    // So form_state.js autosaves and anything else watching the form reacts. The
    // hidden input's own value change fires nothing on its own.
    hidden.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function syncAll() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-partner-picker]"), render);
  }

  document.addEventListener("boltz:wizard-ready", syncAll);
  document.addEventListener("boltz:form-changed", syncAll);
  // Typing a partner's name should update the pickers as it happens, not only when
  // a row is added or removed.
  ["input", "change"].forEach(function (kind) {
    document.addEventListener(kind, function (event) {
      if (event.target && event.target.matches &&
          event.target.matches('[name="partner_name[]"]')) syncAll();
    });
  });
  document.addEventListener("boltz:page-applied", syncAll);
  syncAll();
})();

/* ---- Verify a PDB id by reading the entry back -----------------------------

   Same shape as the UniProt autofill above, and for the same reason: four
   characters means every typo is another valid id, so the only way to know the
   right structure was named is to see its title. The bound-ligand list is the
   part that matters most here -- "apo" in a title is not a guarantee, and this
   project has twice measured against a reference that was not what it claimed. */
(function () {
  "use strict";

  function noteFor(input) {
    var field = input.closest(".md-apo-field");
    return field ? field.querySelector(".md-pdb-note") : null;
  }

  function verify(input) {
    var note = noteFor(input);
    var id = (input.value || "").trim().toUpperCase();
    input.value = id;
    if (!note) return;
    if (!id) { note.textContent = ""; note.className = "md-hint md-pdb-note"; return; }
    if (!/^[0-9][A-Za-z0-9]{3}$/.test(id)) {
      note.textContent = "A PDB id is four characters starting with a digit.";
      note.className = "md-hint md-pdb-note md-status-bad";
      return;
    }
    note.textContent = "Looking up " + id + "…";
    note.className = "md-hint md-pdb-note";

    fetch("/auto/pdb/" + encodeURIComponent(id) + ".json")
      .then(function (r) { return r.json(); })
      .then(function (entry) {
        if (entry.error) {
          note.textContent = entry.error;
          note.className = "md-hint md-pdb-note md-status-bad";
          return;
        }
        var bits = [entry.pdb_id + " · " + (entry.title || "untitled")];
        var facts = [];
        if (entry.method) facts.push(entry.method.toLowerCase());
        if (entry.resolution) facts.push(entry.resolution + " Å");
        if (entry.released) facts.push("released " + entry.released);
        if (facts.length) bits.push(facts.join(", "));
        if (entry.ligands && entry.ligands.length) {
          bits.push("bound: " + entry.ligands.map(function (l) { return l.id; }).join(", ")
                    + " — check none of these makes it non-apo");
        } else {
          bits.push("no bound ligands listed");
        }
        note.textContent = bits.join(" — ");
        note.className = "md-hint md-pdb-note"
          + (entry.ligands && entry.ligands.length ? " md-status-warn" : " md-status-ok");
      })
      .catch(function () {
        note.textContent = "RCSB could not be reached.";
        note.className = "md-hint md-pdb-note md-status-bad";
      });
  }

  document.addEventListener("change", function (event) {
    if (event.target && event.target.matches && event.target.matches("[data-pdb-verify]")) {
      verify(event.target);
    }
  });
})();
