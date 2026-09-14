/* GymLLM front-end helpers. Every block guards on the elements it needs, so
   this one file is safe to load on every page. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var csrfToken = function () { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };

  // Local date for the log/review forms, so "today" is the user's day, not the server's.
  $$(".client-date").forEach(function (el) {
    var d = new Date();
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    el.value = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  });

  // ---------------------------------------------------------------- Sortable tables
  function cellText(td) {
    var input = td.querySelector("input[type=text]");
    return (input ? input.value : td.textContent).trim();
  }
  function sortKey(text, type) {
    if (type === "number") { var m = text.match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : -Infinity; }
    return text.toLowerCase();
  }
  $$("table.sortable").forEach(function (table) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    $$("th[data-sort]", table).forEach(function (th, idx) {
      th.classList.add("sortable-th");
      th.addEventListener("click", function () {
        var type = th.dataset.sort;
        var asc = th.dataset.dir !== "asc";
        $$("th[data-sort]", table).forEach(function (o) { delete o.dataset.dir; o.classList.remove("sort-asc", "sort-desc"); });
        th.dataset.dir = asc ? "asc" : "desc";
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        var rows = $$("tr", tbody);
        rows.sort(function (a, b) {
          var ka = sortKey(cellText(a.children[idx]), type), kb = sortKey(cellText(b.children[idx]), type);
          if (ka < kb) return asc ? -1 : 1;
          if (ka > kb) return asc ? 1 : -1;
          return 0;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
      });
    });
  });

  // ---------------------------------------------------------------- Search page
  var query = $("#query");
  var workoutTable = $("#workout-table");
  if (query && workoutTable) {
    var rows = $$("tbody tr", workoutTable);
    var counter = $("#row-count");
    var applyFilter = function () {
      var q = query.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var text = $$("input[type=text]", row).map(function (i) { return i.value; }).join(" ").toLowerCase();
        var show = !q || text.indexOf(q) !== -1;
        row.hidden = !show;
        if (show) shown++;
      });
      if (counter) counter.textContent = shown + (shown === 1 ? " row" : " rows") + (q ? " match" : "");
    };
    query.addEventListener("input", applyFilter);

    var dirty = $("#dirty-count");
    var form = $("#log-edit-form");
    var updateDirty = function () {
      var changed = 0, deleted = 0;
      rows.forEach(function (row) {
        var box = $(".delete-box", row);
        if (box && box.checked) { deleted++; row.classList.add("row-deleted"); return; }
        row.classList.remove("row-deleted");
        var edited = $$("input[type=text]", row).some(function (i) { return i.value !== i.defaultValue; });
        row.classList.toggle("row-dirty", edited);
        if (edited) changed++;
      });
      if (dirty) {
        var parts = [];
        if (changed) parts.push(changed + " edited");
        if (deleted) parts.push(deleted + " to delete");
        dirty.textContent = parts.join(", ");
        dirty.hidden = !parts.length;
      }
    };
    if (form) {
      form.addEventListener("input", updateDirty);
      form.addEventListener("change", updateDirty);
    }
  }

  // ---------------------------------------------------------------- Review page: add row
  var addRow = $("#add-row");
  var entriesTable = $("#entries-table");
  if (addRow && entriesTable) {
    var numField = $("#num_entries");
    addRow.addEventListener("click", function () {
      var i = parseInt(numField.value, 10) || 0;
      var tr = document.createElement("tr");
      var cell = function (name, cls, extra) {
        return '<td' + (cls === "center" ? ' class="center"' : "") + '><input type="' + (name === "delete" ? "checkbox" : "text") +
          '" name="entry-' + i + "-" + name + '"' + (name === "delete" ? ' value="1"' : "") + (extra || "") + "></td>";
      };
      tr.innerHTML = cell("exercise", "", ' list="exercise-names"') + cell("weight") + cell("sets", "", ' class="narrow"') +
        cell("reps") + cell("notes") + cell("delete", "center");
      entriesTable.tBodies[0].appendChild(tr);
      numField.value = i + 1;
      var submit = $('#confirm-form button[type=submit]');
      if (submit) submit.disabled = false;
      tr.querySelector("input").focus();
    });
  }

  // ---------------------------------------------------------------- Settings page
  var settingsForm = $("#settings-form");
  if (settingsForm) {
    var providers = {};
    try { JSON.parse(settingsForm.dataset.providers).forEach(function (p) { providers[p.id] = p; }); } catch (e) { /* ignore */ }
    var select = $("#provider"), model = $("#model"), apiKey = $("#api_key"), baseUrl = $("#base_url");
    var keyRow = $("#api-key-row"), urlRow = $("#base-url-row"), help = $("#provider-help");
    var suggestions = $("#model-suggestions"), localWarning = $("#local-warning");
    var lastProvider = select.value;

    var render = function (changed) {
      var p = providers[select.value] || {};
      keyRow.hidden = !p.needs_key && p.id !== "custom";
      urlRow.hidden = p.id !== "custom";
      if (localWarning) localWarning.hidden = !p.is_local;
      apiKey.placeholder = p.key_hint || (p.id === "custom" ? "optional" : "");
      suggestions.innerHTML = (p.model_suggestions || []).map(function (m) { return '<option value="' + m + '">'; }).join("");
      var text = p.help_text || "";
      help.innerHTML = text + (p.help_url ? ' <a href="' + p.help_url + '" target="_blank" rel="noopener">' + p.help_url.replace(/^https?:\/\//, "") + "</a>" : "");
      if (changed && select.value !== lastProvider) {
        model.value = p.default_model || "";
        apiKey.value = "";
        lastProvider = select.value;
      }
    };
    select.addEventListener("change", function () { render(true); });
    render(false);

    var toggle = $("#toggle-key");
    if (toggle) toggle.addEventListener("click", function () {
      var show = apiKey.type === "password";
      apiKey.type = show ? "text" : "password";
      toggle.textContent = show ? "hide" : "show";
    });

    // One-time migration from the old localStorage-based settings.
    try {
      var oldKey = localStorage.getItem("openai_api_key");
      var oldMode = localStorage.getItem("llm_mode");
      if (oldMode === "local") {
        select.value = "ollama"; render(true);
        model.value = localStorage.getItem("local_model") || "llama3.2";
      } else if (oldKey && settingsForm.dataset.hasKey !== "1") {
        select.value = "openai"; render(true);
        apiKey.value = oldKey;
      }
      if (oldKey || oldMode) {
        settingsForm.addEventListener("submit", function () {
          ["openai_api_key", "llm_mode", "local_model"].forEach(function (k) { localStorage.removeItem(k); });
        });
      }
    } catch (e) { /* localStorage unavailable */ }

    var testBtn = $("#test-connection"), result = $("#test-result");
    if (testBtn) testBtn.addEventListener("click", function () {
      testBtn.disabled = true;
      result.className = "small muted";
      result.textContent = "Testing...";
      var body = new FormData(settingsForm);
      fetch(settingsForm.dataset.testUrl || "/settings/test", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body: body,
        credentials: "same-origin"
      }).then(function (r) { return r.json(); }).then(function (data) {
        result.className = "small " + (data.ok ? "text-ok" : "text-error");
        result.textContent = data.message;
      }).catch(function () {
        result.className = "small text-error";
        result.textContent = "Request failed.";
      }).then(function () { testBtn.disabled = false; });
    });
  }

  // ---------------------------------------------------------------- Exercise history chart (inline SVG)
  var chartWrap = $("#chart-wrap");
  if (chartWrap) {
    var series = [];
    try { series = JSON.parse(chartWrap.dataset.series); } catch (e) { series = []; }
    var svg = $("#progress-chart");
    var note = $("#chart-note");
    if (!series.length) {
      chartWrap.hidden = true;
    } else {
      if (note) note.hidden = false;
      var W = 640, H = 260, L = 54, R = 16, T = 16, B = 40;
      var xs = series.map(function (_, i) { return i; });
      var ys = series.map(function (p) { return p.weight; });
      var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
      if (yMin === yMax) { yMin = yMin - 5; yMax = yMax + 5; }
      var pad = (yMax - yMin) * 0.1; yMin -= pad; yMax += pad;
      var x = function (i) { return series.length === 1 ? (L + W - R) / 2 : L + (i / (series.length - 1)) * (W - L - R); };
      var y = function (v) { return T + (1 - (v - yMin) / (yMax - yMin)) * (H - T - B); };
      var ns = "http://www.w3.org/2000/svg";
      var el = function (tag, attrs, text) {
        var e = document.createElementNS(ns, tag);
        Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        if (text != null) e.textContent = text;
        return e;
      };
      // gridlines + y labels
      var ticks = 4;
      for (var t = 0; t <= ticks; t++) {
        var v = yMin + (t / ticks) * (yMax - yMin);
        svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
        svg.appendChild(el("text", { x: L - 8, y: y(v) + 4, class: "axis-label", "text-anchor": "end" }, Math.round(v)));
      }
      // line
      var d = xs.map(function (i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(ys[i]).toFixed(1); }).join(" ");
      svg.appendChild(el("path", { d: d, class: "line" }));
      // points + x labels (thin out labels when crowded)
      var every = Math.max(1, Math.ceil(series.length / 8));
      series.forEach(function (p, i) {
        var c = el("circle", { cx: x(i), cy: y(p.weight), r: 4, class: "point" });
        c.appendChild(el("title", {}, p.date + ": " + p.weight));
        svg.appendChild(c);
        if (i % every === 0 || i === series.length - 1) {
          svg.appendChild(el("text", { x: x(i), y: H - B + 18, class: "axis-label", "text-anchor": "middle" }, p.date.slice(5)));
        }
      });
    }
  }
})();
