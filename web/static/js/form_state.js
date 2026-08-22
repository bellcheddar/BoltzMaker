/* Save, restore and transport everything typed into the Prepare form.
 *
 * One state representation with three sinks, deliberately: localStorage (so the
 * form survives downloading a bundle, wandering off to Step 2, a reload, or a
 * validation error), a downloaded .json file ("Save page"), and an uploaded one
 * ("Upload page"). Writing those as three separate serialisers is how they end
 * up disagreeing about which fields exist.
 *
 * Nothing here talks to the server. A campaign spec is not built from this file;
 * it is built from the form POST exactly as before, so an uploaded state file can
 * do nothing worse than fill in form fields you can see and edit.
 */
var BoltzFormState = (function () {
  "use strict";

  var STORAGE_KEY = "boltzmaker.prepare.v1";
  /* Bumped when a default changes or a field disappears. The version was written
     into the saved state from the start and never read back, so a form saved before
     a default moved kept re-applying the old value for ever -- which is exactly how
     a browser went on filling in the old 8A pocket distance after the default became
     4A, and would have restored the removed "use same pocket" box with it. */
  var STATE_VERSION = 2;
  var form = null;
  var statusEl = null;

  function scalarInputs() {
    // Everything that is not part of a repeating row. Row fields all end in "[]",
    // which is also what tells the server they are parallel arrays.
    return Array.prototype.filter.call(
      form.querySelectorAll("input[name], select[name], textarea[name]"),
      function (el) { return el.name.slice(-2) !== "[]" && el.type !== "file"; }
    );
  }

  /* A protein row contains nested pocket rows. Their inputs share names across
     rows, so folding them into the protein's flat dict keeps only the last and
     loses the rest -- they are saved separately, as an array, below. */
  function rowFields(rowEl) {
    var all = rowEl.querySelectorAll("input[name], select[name], textarea[name]");
    var out = [];
    for (var i = 0; i < all.length; i++) {
      if (!all[i].closest(".md-pocket-row")) out.push(all[i]);
    }
    return out;
  }

  // ---- collect -------------------------------------------------------------

  function collect() {
    var state = { version: STATE_VERSION, scalars: {}, groups: {} };

    scalarInputs().forEach(function (el) {
      state.scalars[el.name] = (el.type === "checkbox") ? !!el.checked : el.value;
    });

    BoltzWizard.GROUPS.forEach(function (group) {
      var container = document.getElementById(group.container);
      if (!container) return;
      var rows = [];
      Array.prototype.forEach.call(container.querySelectorAll(".md-repeat-block"), function (rowEl) {
        var row = {};
        Array.prototype.forEach.call(rowFields(rowEl), function (el) {
          row[el.name] = (el.type === "checkbox") ? !!el.checked : el.value;
        });
        if (group.key === "protein" && window.BoltzPockets) {
          row.pockets = window.BoltzPockets.rowsOf(rowEl);
        }
        rows.push(row);
      });
      state.groups[group.key] = rows;
    });

    return state;
  }

  function isEmpty(state) {
    var typed = Object.keys(state.scalars).some(function (k) {
      var v = state.scalars[k];
      return v !== "" && v !== false;
    });
    if (typed) return false;
    return !Object.keys(state.groups).some(function (key) {
      return state.groups[key].some(function (row) {
        return Object.keys(row).some(function (f) { return row[f] !== "" && row[f] !== false; });
      });
    });
  }

  // ---- apply ---------------------------------------------------------------

  function setValue(el, value) {
    if (value === undefined || value === null) return;
    if (el.type === "checkbox") { el.checked = !!value; return; }
    el.value = value;
  }

  function apply(state) {
    if (!state || typeof state !== "object" || !state.scalars || !state.groups) {
      throw new Error("that file does not look like a saved BoltzMaker page");
    }

    scalarInputs().forEach(function (el) {
      if (Object.prototype.hasOwnProperty.call(state.scalars, el.name)) {
        setValue(el, state.scalars[el.name]);
      }
    });

    BoltzWizard.GROUPS.forEach(function (group) {
      var rows = state.groups[group.key];
      if (!Array.isArray(rows)) return;
      BoltzWizard.clearRows(group.key);
      rows.forEach(function (row) {
        var rowEl = BoltzWizard.addRowFor(group.key);
        if (!rowEl) return;
        Array.prototype.forEach.call(rowFields(rowEl), function (el) {
          if (Object.prototype.hasOwnProperty.call(row, el.name)) setValue(el, row[el.name]);
        });
        if (group.key === "protein" && window.BoltzPockets) {
          // The row was created with one empty pocket row seeded; replace it with
          // exactly what was saved, or leave the empty one if none were.
          if (Array.isArray(row.pockets) && row.pockets.length) {
            window.BoltzPockets.clear(rowEl);
            row.pockets.forEach(function (saved) {
              window.BoltzPockets.restoreRow(rowEl, saved);
            });
          }
        }
      });
    });

    // Rows were rebuilt from scratch, so their checkbox ordinals are all stale.
    BoltzWizard.renumberAll();
  }

  // ---- persistence ---------------------------------------------------------

  function save() {
    try {
      var state = collect();
      if (isEmpty(state)) {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      }
    } catch (err) {
      // Private browsing, a full quota, or storage disabled entirely. Losing
      // autosave is not worth breaking the form over -- Save page still works.
    }
  }

  /* Attach the current state to the submission, so the bundle can carry it.
     Written on submit rather than kept in sync on every keystroke: the value is
     only ever read by the server at this moment, and a hidden field that updates
     continuously is one more thing to get out of step with the form. */
  function stampStateForSubmit() {
    var form = document.querySelector("form");
    var field = document.getElementById("page-state-field");
    if (!form || !field) return;
    form.addEventListener("submit", function () {
      try {
        field.value = JSON.stringify(collect());
      } catch (err) {
        field.value = "";        // a bundle without it still runs; it just cannot reload the form
      }
    });
  }

  function restore() {
    var raw;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      return false;
    }
    if (!raw) return false;
    try {
      var state = JSON.parse(raw);
      if (!state || state.version !== STATE_VERSION) {
        // Older layout: drop it rather than reviving defaults the page has moved on
        // from. Losing a saved draft is the lesser harm against silently running a
        // campaign with last month's settings.
        try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) {}
        return false;
      }
      apply(state);
      return true;
    } catch (err) {
      // A state file from an older layout, or corrupt. Drop it rather than
      // leaving a half-filled form the user cannot explain.
      try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      return false;
    }
  }

  function clear() {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (err) {}
  }

  // ---- status line ---------------------------------------------------------

  function status(message, tone) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = "md-hint" + (tone ? " md-status-" + tone : "");
    if (message) {
      window.clearTimeout(status._timer);
      status._timer = window.setTimeout(function () {
        statusEl.textContent = "";
        statusEl.className = "md-hint";
      }, 6000);
    }
  }

  // ---- save / upload to disk ----------------------------------------------

  /* Send a bundle to the server and get its saved page back.

     The wizard's state travels inside the bundle itself, which is what lets one
     file be the only thing anyone keeps: the .command runs the campaign AND
     restores this form. A finished campaign's .bmz carries the same state and is
     accepted too, as is an old .boltzpage.json, but neither is advertised -- one
     artefact to think about is the whole point.

     Unpacking happens on the server: the browser can read neither a tar.gz nor a
     zip without shipping a library to do it, and the server already has both. */
  function loadFromBundle(file, report) {
    // `report` lets the caller choose where the message appears. The button at
    // the top of the page is two screens from the bottom status line, and a
    // result the user has to go looking for reads as nothing having happened.
    report = report || status;
    var body = new FormData();
    body.append("results_file", file);
    report("Reading " + file.name + "...", "");
    fetch("/auto/prepare/page-state", { method: "POST", body: body })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          report(result.payload.error || "Could not read that file.", "bad");
          return;
        }
        try {
          apply(result.payload);
        } catch (err) {
          report(err.message, "bad");
          return;
        }
        save();
        report("Loaded the campaign from " + file.name
               + ". Add what you want and download a new bundle.", "ok");
      })
      .catch(function () { report("Could not read that file.", "bad"); });
  }

  function loadFromDisk(file, report) {
    report = report || status;
    // A .bmz is a zip and a .command is a shell script with a tar.gz stapled to it;
    // a saved page is JSON. Chosen by extension rather than by sniffing, because the
    // two are asked for by two different buttons' worth of intent and guessing wrong
    // wastes an upload. The server sniffs properly, which is what catches a file
    // whose extension is missing or wrong.
    if (/\.(bmz|command)$/i.test(file.name)) { loadFromBundle(file, report); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var parsed;
      try {
        parsed = JSON.parse(reader.result);
      } catch (err) {
        report("That file is not valid JSON.", "bad");
        return;
      }
      try {
        apply(parsed);
      } catch (err) {
        report(err.message, "bad");
        return;
      }
      save();
      report("Loaded " + file.name + ".", "ok");
    };
    reader.onerror = function () { report("Could not read that file.", "bad"); };
    reader.readAsText(file);
  }

  // ---- wiring --------------------------------------------------------------

  function init() {
    form = document.getElementById("wizard-form");
    if (!form) return;
    statusEl = document.getElementById("state-status");
    if (typeof BoltzWizard === "undefined" || !BoltzWizard.GROUPS) {
      // This used to be a silent early return, and it cost a real debugging
      // session: a stale cached wizard.js meant no BoltzWizard, so save/upload
      // quietly did nothing while the rest of the form worked normally. A dead
      // button with no explanation is the worst possible symptom -- say so.
      status("Page saving is unavailable: a stale copy of the page scripts is cached. "
             + "Reload with a hard refresh (Cmd-Shift-R) to fix it.", "bad");
      if (window.console) window.console.warn("BoltzWizard missing -- stale wizard.js?");
      return;
    }

    if (restore()) status("Restored what you last entered on this browser.", "ok");

    // Autosave. "input" covers typing, "change" covers selects, checkboxes and the
    // add/remove-row event below, which fires after the DOM has settled.
    form.addEventListener("input", save);
    form.addEventListener("change", save);
    document.addEventListener("boltz:form-changed", save);
    // Submitting downloads a file and leaves the page in place, so this is not a
    // navigation -- but saving here means the state is written even if the user
    // typed nothing since the last event.
    form.addEventListener("submit", save);
    stampStateForSubmit();

    /* The one upload control: "Upload bundle", above the form. Its own status
       line, so the message appears beside the button that was pressed rather than
       at the far end of the page. */
    var bundleBtn = document.getElementById("upload-bundle");
    var bundleInput = document.getElementById("upload-bundle-file");
    var bundleStatusEl = document.getElementById("bundle-status");
    function bundleStatus(message, tone) {
      if (!bundleStatusEl) return;
      bundleStatusEl.textContent = message;
      bundleStatusEl.className = "md-hint" + (tone ? " md-status-" + tone : "");
    }
    if (bundleBtn && bundleInput) {
      bundleBtn.addEventListener("click", function () { bundleInput.click(); });
      bundleInput.addEventListener("change", function () {
        if (bundleInput.files && bundleInput.files[0]) {
          loadFromDisk(bundleInput.files[0], bundleStatus);
        }
        // Reset so choosing the same file twice still fires a change event.
        bundleInput.value = "";
      });
    }

    var clearBtn = document.getElementById("clear-page");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (!window.confirm("Clear everything you have entered on this page?")) return;
        clear();
        window.location.reload();
      });
    }
  }

  document.addEventListener("boltz:wizard-ready", init);

  return { collect: collect, apply: apply, save: save, restore: restore, clear: clear };
})();
