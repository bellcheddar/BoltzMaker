// Vanilla JS add/remove-row for the wizard's repeating blocks (partners, proteins,
// constraints, ligands). No build step, no framework -- clones a <template>, appends
// it, wires up its own remove button. All real validation happens server-side
// (wizard.py/views_new.py); this only makes the form usable.
(function () {
  function wireRemove(rowEl) {
    var btn = rowEl.querySelector(".md-remove-row");
    if (btn) {
      btn.addEventListener("click", function () {
        rowEl.remove();
      });
    }
  }

  function addRow(templateId, containerId) {
    var tpl = document.getElementById(templateId);
    var container = document.getElementById(containerId);
    if (!tpl || !container) return;
    var clone = tpl.content.cloneNode(true);
    var rowEl = clone.querySelector(".md-repeat-block");
    container.appendChild(clone);
    // rowEl was detached from the fragment by appendChild's move; re-query the
    // just-appended last child instead, which is the actual attached row.
    wireRemove(container.lastElementChild);
  }

  function wireAdd(buttonId, templateId, containerId, seedOne) {
    var btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener("click", function () {
      addRow(templateId, containerId);
    });
    if (seedOne) addRow(templateId, containerId);
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireAdd("add-partner", "tpl-partner", "partner-rows", false);
    wireAdd("add-protein", "tpl-protein", "protein-rows", true);
    wireAdd("add-constraint", "tpl-constraint", "constraint-rows", false);
    wireAdd("add-ligand", "tpl-ligand", "ligand-rows", true);
  });
})();
