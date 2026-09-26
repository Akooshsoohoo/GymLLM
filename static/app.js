/* GymLLM front-end helpers. Every block guards on the elements it needs, so
   this one file is safe to load on every page. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var csrfToken = function () { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };

  // Local date, so "today" is the user's day, not the server's.
  function localDate() {
    var d = new Date();
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  $$(".client-date").forEach(function (el) { el.value = localDate(); });
  // Lets the server work out the user's "today" on plain page loads too.
  try { document.cookie = "tz_offset=" + new Date().getTimezoneOffset() + "; path=/; max-age=31536000; samesite=lax"; } catch (e) { /* cookies blocked */ }

  // ---------------------------------------------------------------- Day page navigation
  $$("a[data-today-link]").forEach(function (a) {
    a.href = a.href.replace(/\d{4}-\d{2}-\d{2}\/?$/, localDate());
  });
  $$("input[data-day-jump]").forEach(function (input) {
    input.addEventListener("change", function () {
      if (/^\d{4}-\d{2}-\d{2}$/.test(input.value)) window.location.href = input.dataset.dayBase + input.value;
    });
  });

  // ---------------------------------------------------------------- Browser-side LLM
  // Local providers (Ollama, LM Studio) run on the user's machine, so the page
  // calls them directly; the server only supplies prompts and validates output.
  var browserLLM = {
    // OpenAI-compatible chat call. Returns the assistant text. Mirrors the
    // server client: retry without response_format if the server rejects it.
    chat: function (cfg, system, user) {
      var messages = [{ role: "system", content: system }, { role: "user", content: user }];
      var call = function (withFormat) {
        var body = { model: cfg.model, messages: messages, temperature: 0, stream: false };
        if (withFormat) body.response_format = { type: "json_object" };
        return fetch(cfg.base_url + "/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
      };
      return call(true).then(function (r) {
        return r.status === 400 ? call(false) : r;
      }).then(function (r) {
        if (!r.ok) {
          return r.text().then(function (text) { throw browserLLM.httpError(cfg, r.status, text); });
        }
        return r.json();
      }).then(function (data) {
        var choice = data && data.choices && data.choices[0];
        var content = choice && choice.message && choice.message.content;
        if (typeof content !== "string" || !content.trim()) throw new Error("The model returned an empty response.");
        return content;
      });
    },
    httpError: function (cfg, status, text) {
      var msg;
      if (status === 404) {
        msg = "Model '" + cfg.model + "' was not found on " + cfg.label + ". Pull it or change the model on the Settings page.";
      } else {
        var detail = "";
        try { var j = JSON.parse(text); detail = (j.error && (j.error.message || j.error)) || j.message || ""; } catch (e) { detail = text; }
        msg = cfg.label + " returned an error (" + status + ")" + (detail ? ": " + String(detail).slice(0, 300) : ".");
      }
      var err = new Error(msg);
      err.described = true;
      return err;
    },
    // Human-readable message for anything chat() can throw.
    describe: function (cfg, err) {
      if (err && err.described) return err.message;
      if (err instanceof TypeError) {
        return "Could not reach " + cfg.label + " at " + cfg.base_url + " from this browser. Make sure it is running" +
          " and that it allows requests from " + window.location.origin + " (see the setup steps on the Settings page)." +
          " Safari does not allow this at all; use Chrome, Edge or Firefox.";
      }
      return (err && err.message) || "Something went wrong while talking to the model.";
    },
    // Lenient JSON extraction, same idea as extract_json on the server.
    parseJSON: function (text) {
      var cleaned = text.replace(/^\s*```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
      try { return JSON.parse(cleaned); } catch (e) { /* fall through */ }
      var a = cleaned.indexOf("{"), b = cleaned.lastIndexOf("}");
      if (a !== -1 && b > a) { try { return JSON.parse(cleaned.slice(a, b + 1)); } catch (e2) { /* ignore */ } }
      return null;
    },
    config: function (form) {
      try { return JSON.parse(form.dataset.browserLlm); } catch (e) { return null; }
    }
  };

  function setBusy(form, busy, statusText) {
    form.dataset.busy = busy ? "1" : "";
    $$("button[type=submit]", form).forEach(function (b) { b.disabled = busy; });
    var status = $("[data-llm-status]", form);
    if (status) {
      if (busy) { status.dataset.idle = status.dataset.idle || status.textContent; status.textContent = statusText; }
      else status.textContent = status.dataset.idle || "";
    }
  }
  function showLLMError(message) {
    var box = $("#llm-error");
    if (!box) { window.alert(message); return; }
    box.textContent = message;
    box.hidden = false;
    box.scrollIntoView({ block: "nearest" });
  }

  // Parse in the browser: fetch the system prompt, call the model, hand the raw
  // output to /review through the normal form post.
  $$("form[data-browser-llm]").forEach(function (form) {
    if (!$("input[name=llm_output]", form)) return;
    var cfg = browserLLM.config(form);
    if (!cfg) return;
    form.addEventListener("submit", function (ev) {
      var output = $("input[name=llm_output]", form);
      if (output.value || form.dataset.busy) return; // second pass: let it post
      ev.preventDefault();
      var text = ($("textarea[name=workout]", form) || {}).value || "";
      if (!text.trim()) return;
      var when = ($("input[name=client_date]", form) || {}).value || "";
      var unit = ($("input[name=weight_unit]", form) || {}).value || "lbs";
      var errBox = $("#llm-error"); if (errBox) errBox.hidden = true;
      setBusy(form, true, "Reading your workout\u2026");
      fetch("/llm/prompt?date=" + encodeURIComponent(when) + "&unit=" + encodeURIComponent(unit), { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error("Could not load the prompt from the server."); return r.json(); })
        .then(function (data) { return browserLLM.chat(cfg, data.system, text); })
        .then(function (content) {
          output.value = content;
          form.dataset.busy = "";
          form.submit();
        })
        .catch(function (err) {
          setBusy(form, false);
          showLLMError(browserLLM.describe(cfg, err));
        });
    });
  });

  // ---------------------------------------------------------------- Default weight unit
  // A small lbs/kg toggle next to the workout textarea. Every hidden .weight-unit-field
  // on the page is kept in sync so it rides along with whichever form gets submitted,
  // and the choice is saved server-side right away so it's there next time too.
  $$(".unit-toggle").forEach(function (group) {
    $$(".unit-btn", group).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var unit = btn.dataset.unit;
        $$(".unit-btn", group).forEach(function (b) {
          var active = b === btn;
          b.classList.toggle("is-active", active);
          b.setAttribute("aria-pressed", active ? "true" : "false");
        });
        $$(".weight-unit-field").forEach(function (input) { input.value = unit; });
        fetch("/weight-unit", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken() },
          body: "unit=" + encodeURIComponent(unit)
        }).catch(function () { /* the choice still posts with the next parse */ });
      });
    });
  });

  // ---------------------------------------------------------------- Sortable tables
  function cellText(td) {
    var input = td.querySelector("input[type=text]");
    return (input ? input.value : td.textContent).trim();
  }
  function rowText(tr) {
    return $$("td", tr).map(cellText).join(" ").toLowerCase();
  }
  function sortKey(text, type) {
    if (type === "number") { var m = text.match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : -Infinity; }
    return text.toLowerCase();
  }
  function initSortable(root) { $$("table.sortable", root).forEach(function (table) {
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
  }); }

  // ---------------------------------------------------------------- Table filter
  // <input data-filter="table selector" data-count="#counter" data-group=".group">
  // hides rows that don't match; groups left with no visible rows are hidden too.
  function initFilters(root) { $$("input[data-filter]", root).forEach(function (input) {
    var tables = $$(input.dataset.filter).filter(function (t) { return t.tBodies[0]; });
    if (!tables.length) return;
    var counter = input.dataset.count ? $(input.dataset.count) : null;
    var rows = [];
    tables.forEach(function (t) { rows = rows.concat($$("tr", t.tBodies[0])); });
    var groups = input.dataset.group ? $$(input.dataset.group) : [];
    var noun = counter ? (counter.textContent.match(/[a-z]+$/i) || ["rows"])[0].replace(/s$/, "") : "row";
    var apply = function () {
      var q = input.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var show = !q || rowText(row).indexOf(q) !== -1;
        row.hidden = !show;
        if (show) shown++;
      });
      groups.forEach(function (g) {
        g.hidden = !$$("tbody tr", g).some(function (r) { return !r.hidden; });
      });
      if (counter) counter.textContent = shown + " " + noun + (shown === 1 ? "" : "s") + (q ? " match" : "");
    };
    input.addEventListener("input", apply);
  }); }

  // ---------------------------------------------------------------- History: edit mode + dirty tracking
  var logForm = $("#log-edit-form");
  if (logForm) {
    var logRows = $$("tbody tr", logForm);
    var dirty = $("#dirty-count");
    var toggle = $("#edit-toggle");
    var cancel = $("#edit-cancel");

    var updateDirty = function () {
      var changed = 0, deleted = 0;
      logRows.forEach(function (row) {
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
    logForm.addEventListener("input", updateDirty);
    logForm.addEventListener("change", updateDirty);

    var setEditing = function (on) {
      logForm.classList.toggle("editing", on);
      if (on) {
        var first = $("tbody tr:not([hidden]) input[type=text]", logForm);
        if (first) first.focus();
      }
    };
    if (toggle) toggle.addEventListener("click", function () { setEditing(true); });
    if (cancel) cancel.addEventListener("click", function () {
      logForm.reset();
      logRows.forEach(function (row) { row.classList.remove("row-dirty", "row-deleted"); });
      if (dirty) { dirty.hidden = true; dirty.textContent = ""; }
      setEditing(false);
    });
  }

  // ---------------------------------------------------------------- Review page: remove/undo + add row
  var confirmForm = $("#confirm-form");
  var entriesTable = $("#entries-table");
  if (confirmForm && entriesTable && confirmForm.dataset.browserLlm) {
    var tagCfg = browserLLM.config(confirmForm);
    confirmForm.addEventListener("submit", function (ev) {
      if (!tagCfg || confirmForm.dataset.tagged || confirmForm.dataset.busy) return;
      ev.preventDefault();
      var rows = $$("[data-row]", entriesTable).filter(function (tr) {
        var box = $(".delete-box", tr);
        return !(box && box.checked);
      });
      var byName = {};
      rows.forEach(function (tr) {
        var input = $("input[name$=-exercise]", tr);
        var name = input ? input.value.trim() : "";
        if (name) (byName[name.toLowerCase()] = byName[name.toLowerCase()] || []).push(input.name.replace(/-exercise$/, ""));
      });
      var names = Object.keys(byName);
      var finish = function () { confirmForm.dataset.tagged = "1"; confirmForm.dataset.busy = ""; confirmForm.submit(); };
      if (!names.length) { finish(); return; }
      setBusy(confirmForm, true, "Saving\u2026");
      fetch(confirmForm.dataset.tagTargetsUrl || "/llm/tag-targets", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        credentials: "same-origin",
        body: JSON.stringify({ names: names })
      }).then(function (r) { return r.ok ? r.json() : { unmatched: [] }; }).then(function (data) {
        var todo = (data.unmatched || []).map(function (n) { return String(n).toLowerCase(); }).filter(function (n) { return byName[n]; });
        if (!todo.length) return;
        setBusy(confirmForm, true, "Sorting " + todo.length + " new exercise" + (todo.length === 1 ? "" : "s") + " into muscle groups\u2026");
        return todo.reduce(function (chain, name) {
          return chain.then(function () {
            return browserLLM.chat(tagCfg, data.system, "Exercise: " + name).then(function (content) {
              var parsed = browserLLM.parseJSON(content);
              var tags = parsed && parsed.tags;
              if (Array.isArray(tags)) tags = tags.join(";");
              if (typeof tags !== "string" || !tags.trim()) return;
              byName[name].forEach(function (prefix) {
                var hidden = document.createElement("input");
                hidden.type = "hidden"; hidden.name = prefix + "-tags"; hidden.value = tags;
                confirmForm.appendChild(hidden);
              });
            }).catch(function () { /* leave this exercise untagged, like llm_tags() on the server */ });
          });
        }, Promise.resolve());
      }).then(finish, finish);
    });
  }
  // Value pills grow with their text. Browsers without field-sizing get a size attribute.
  var fieldSizing = !!(window.CSS && CSS.supports && CSS.supports("field-sizing", "content"));
  function sizePills(root) {
    if (fieldSizing) return;
    $$(".vpill input", root).forEach(function (input) {
      var fit = function () { input.size = Math.max(2, (input.value || input.placeholder || "").length + 1); };
      fit();
      if (!input.dataset.sized) { input.dataset.sized = "1"; input.addEventListener("input", fit); }
    });
  }
  sizePills(document);

  if (confirmForm && entriesTable) {
    var saveBtn = $("button[type=submit]", confirmForm);
    confirmForm.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".row-remove");
      if (!btn) return;
      var row = btn.closest("[data-row]");
      var box = $(".delete-box", row);
      var removing = !row.classList.contains("row-deleted");
      row.classList.toggle("row-deleted", removing);
      if (box) box.checked = removing;
      btn.textContent = removing ? "Undo" : "Remove";
    });

    // "+ Add": copy the group's <template>, numbered the way the server expects.
    var addRowTo = function (button, list, counter, template) {
      if (!button || !list || !counter || !template) return;
      button.addEventListener("click", function () {
        var i = parseInt(counter.value, 10) || 0;
        var holder = document.createElement("div");
        holder.innerHTML = template.innerHTML.replace(/__i__/g, String(i)).trim();
        var row = holder.firstElementChild;
        list.appendChild(row);
        counter.value = i + 1;
        var empty = $('[data-empty-for="' + list.id + '"]', confirmForm);
        if (empty) empty.hidden = true;
        if (saveBtn) saveBtn.disabled = false;
        sizePills(row);
        $("input[type=text]", row).focus();
      });
    };
    addRowTo($("#add-row"), entriesTable, $("#num_entries"), $("#entry-template"));
    addRowTo($("#add-cardio"), $("#cardio-table"), $("#num_cardio"), $("#cardio-template"));
    var bodyweightField = $("#bodyweight");
    if (bodyweightField) bodyweightField.addEventListener("input", function () {
      if (saveBtn && bodyweightField.value.trim()) saveBtn.disabled = false;
    });
  }

  // "‹ Edit text" on the review page opens the box with what you typed.
  $$("[data-toggle]").forEach(function (btn) {
    var target = document.getElementById(btn.dataset.toggle);
    if (!target) return;
    btn.addEventListener("click", function () {
      var open = !target.classList.contains("is-open");
      target.classList.toggle("is-open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      var field = $("textarea", target);
      if (open && field) field.focus();
    });
  });

  // Example chips add their text to the log box.
  document.addEventListener("click", function (ev) {
    var chip = ev.target.closest("[data-insert]");
    if (!chip) return;
    var box = $("#workout");
    if (!box) return;
    var text = box.value.replace(/\s+$/, "");
    box.value = text ? text + (/[.,;]$/.test(text) ? " " : ", ") + chip.dataset.insert : chip.dataset.insert;
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  });

  // "+ Log workout" in the top bar: on Home it just jumps to the box.
  function focusLogBox() {
    var box = $("#workout");
    if (!box || !box.offsetParent) return false;
    box.scrollIntoView({ block: "center" });
    box.focus({ preventScroll: true });
    return true;
  }
  if (location.hash === "#log") focusLogBox();
  $$("a[data-log-link]").forEach(function (a) {
    a.addEventListener("click", function (ev) {
      if (new URL(a.href).pathname === location.pathname && focusLogBox()) ev.preventDefault();
    });
  });

  // Sheets (<dialog>) opened by a button with data-dialog-open="id"; a tap on the backdrop closes.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-dialog-open]");
    if (!btn) return;
    var dialog = document.getElementById(btn.dataset.dialogOpen);
    if (dialog && dialog.showModal) dialog.showModal();
  });
  $$("dialog.sheet").forEach(function (dialog) {
    dialog.addEventListener("click", function (ev) { if (ev.target === dialog) dialog.close(); });
  });

  // Menus built on <details>: close on a click elsewhere or on Escape.
  var openMenus = function () { return $$("details.account-menu[open], details.friends-menu[open]"); };
  document.addEventListener("click", function (ev) {
    openMenus().forEach(function (d) { if (!d.contains(ev.target)) d.open = false; });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    openMenus().forEach(function (d) { d.open = false; $("summary", d).focus(); });
  });

  // ---------------------------------------------------------------- Classic logger (Log page)
  // Search/pick an exercise to add a row; rows post to /confirm with the same field names
  // the review page uses.
  var classicForm = $("#classic-form");
  if (classicForm) {
    var esc = function (s) { return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); };
    // One search box + table per kind. columns: [field, extra attrs]; the first is filled from the search.
    var classicList = function (o) {
      var table = $(o.table), count = $(o.count), search = $(o.search);
      var add = function () {
        var name = search.value.trim();
        if (!name) return;
        var i = parseInt(count.value, 10) || 0;
        var tr = document.createElement("tr");
        tr.innerHTML = o.columns.map(function (col, idx) {
          return "<td" + (idx === 0 ? ' class="exercise-cell"' : "") + '><input type="text" name="' + o.prefix + "-" + i + "-" + col[0] +
            '" aria-label="' + col[0].charAt(0).toUpperCase() + col[0].slice(1) + '"' + (idx === 0 ? ' value="' + esc(name) + '"' : col[1] || "") + "></td>";
        }).join("") + '<td class="col-actions"><button type="button" class="btn btn-text row-remove">Remove</button></td>';
        table.tBodies[0].appendChild(tr);
        count.value = i + 1;
        table.hidden = false;
        search.value = "";
        tr.querySelectorAll("input")[1].focus();
      };
      $(o.button).addEventListener("click", add);
      search.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); add(); }
      });
      // A removed row is blanked, not deleted, so indexes stay contiguous; the server skips empty names.
      table.addEventListener("click", function (ev) {
        var btn = ev.target.closest(".row-remove");
        if (!btn) return;
        var tr = btn.closest("tr");
        tr.querySelector("input").value = "";
        tr.hidden = true;
        if (!$$("tr", table.tBodies[0]).some(function (r) { return !r.hidden; })) table.hidden = true;
      });
      return function () {
        return $$("tbody tr input:first-child", table).some(function (i) { return i.value.trim(); });
      };
    };
    var hasLifts = classicList({
      table: "#classic-table", count: "#classic-count", search: "#classic-search", button: "#classic-add", prefix: "entry",
      columns: [["exercise"], ["weight", ' placeholder="185 lbs"'], ["sets", ' class="narrow" inputmode="numeric"'],
                ["reps", ' placeholder="10, 8, 6"'], ["notes", ""]]
    });
    var hasCardio = classicList({
      table: "#classic-cardio-table", count: "#classic-cardio-count", search: "#classic-cardio-search", button: "#classic-cardio-add", prefix: "cardio",
      columns: [["activity"], ["distance", ' placeholder="3 miles"'], ["duration", ' placeholder="45 min"'], ["notes", ""]]
    });
    classicForm.addEventListener("submit", function (ev) {
      if (!hasLifts() && !hasCardio() && !$("#classic-bodyweight").value.trim()) {
        ev.preventDefault();
        $("#classic-search").focus();
      }
    });
  }

  // ---------------------------------------------------------------- Settings page
  var settingsForm = $("#settings-form");
  if (settingsForm) {
    var providers = {};
    try { JSON.parse(settingsForm.dataset.providers).forEach(function (p) { providers[p.id] = p; }); } catch (e) { /* ignore */ }
    var select = $("#provider"), model = $("#model"), apiKey = $("#api_key"), baseUrl = $("#base_url");
    var keyRow = $("#api-key-row"), urlRow = $("#base-url-row"), help = $("#provider-help");
    var suggestions = $("#model-suggestions"), setup = $("#browser-setup");
    var modelRow = $("#model-row"), siteNote = $("#site-note");
    var lastProvider = select.value;

    var render = function (changed) {
      var p = providers[select.value] || {};
      var isSite = p.id === "site";
      keyRow.hidden = isSite || (!p.needs_key && p.id !== "custom");
      urlRow.hidden = p.id !== "custom";
      if (modelRow) modelRow.hidden = isSite;
      if (siteNote) siteNote.hidden = !isSite;
      if (setup) {
        setup.hidden = !p.is_local;
        var lbl = $("[data-setup-label]", setup); if (lbl) lbl.textContent = p.label || "This provider";
        $$("[data-setup-for]", setup).forEach(function (el) { el.hidden = el.dataset.setupFor !== p.id; });
      }
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

    var toggleKey = $("#toggle-key");
    if (toggleKey) toggleKey.addEventListener("click", function () {
      var show = apiKey.type === "password";
      apiKey.type = show ? "text" : "password";
      toggleKey.textContent = show ? "hide" : "show";
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
    var testInBrowser = function (p) {
      var cfg = { base_url: p.base_url, model: model.value.trim() || p.default_model, label: p.label };
      var installed = [];
      return fetch(cfg.base_url + "/models").then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
        installed = ((data && data.data) || []).map(function (m) { return m.id; }).sort();
        if (installed.length) suggestions.innerHTML = installed.map(function (m) { return '<option value="' + m + '">'; }).join("");
        return browserLLM.chat(cfg, "You are a connectivity check. Reply with JSON only.", 'Return exactly this JSON object: {"ok": true}');
      }).then(function (content) {
        var parsed = browserLLM.parseJSON(content);
        if (!parsed || typeof parsed !== "object") return { ok: false, message: "The model answered, but not with a JSON object. Try a different model." };
        var msg = "Connected to " + cfg.label + " \u00b7 " + cfg.model + " from your browser.";
        if (installed.length) msg += " Installed models: " + installed.slice(0, 12).join(", ") + (installed.length > 12 ? ", ..." : "");
        return { ok: true, message: msg };
      }).catch(function (err) { return { ok: false, message: browserLLM.describe(cfg, err) }; });
    };
    if (testBtn) testBtn.addEventListener("click", function () {
      testBtn.disabled = true;
      result.className = "small muted";
      result.textContent = "Testing...";
      var p = providers[select.value] || {};
      if (p.is_local) {
        testInBrowser(p).then(function (data) {
          result.className = "small " + (data.ok ? "text-ok" : "text-error");
          result.textContent = data.message;
          testBtn.disabled = false;
        });
        return;
      }
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

  // ---------------------------------------------------------------- Charts (inline SVG, no library)
  // <svg data-chart="line|columns|spark" data-series='[...]' data-x="label" data-y="value">
  // One accent hue, hairline grid, thin marks, a hover/keyboard tooltip. Re-renders on resize.
  var charts = (function () {
    var ns = "http://www.w3.org/2000/svg";
    var NAMES = { sessions: "sessions", entries: "exercises", volume: "volume", weight: "weight", reps: "reps", distance: "distance", activities: "activities", minutes: "minutes", readings: "readings", low: "low", high: "high" };
    function el(tag, attrs, text) {
      var e = document.createElementNS(ns, tag);
      Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
      if (text != null) e.textContent = text;
      return e;
    }
    function fmt(n) {
      if (n == null || isNaN(n)) return "—";
      var abs = Math.abs(n);
      if (abs >= 100000) return Math.round(n / 1000).toLocaleString() + "k";
      if (abs >= 10000) return (n / 1000).toFixed(1) + "k";
      return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
    }
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    // Axis label for an x value: ISO dates become "27 May"; anything else is used as is.
    // Tooltip title: ISO dates become "Mon 10 Aug 2026".
    function titleLabel(v) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(v))) return String(v);
      var d = new Date(v + "T00:00:00");
      return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    }
    function axisLabel(v) {
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
      return m ? parseInt(m[3], 10) + " " + MONTHS[parseInt(m[2], 10) - 1] : String(v);
    }
    function niceStep(raw) {
      var p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
      var f = raw / p;
      return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
    }
    // Clean tick values covering [lo, hi]; zero-based when fromZero.
    function scale(lo, hi, fromZero) {
      if (fromZero) lo = 0;
      if (hi === lo) { hi = lo + 1; if (!fromZero) lo = lo - 1; }
      var step = niceStep((hi - lo) / 4);
      var min = Math.floor(lo / step) * step, max = Math.ceil(hi / step) * step;
      if (max === hi && !fromZero) max += step;
      if (min === lo && !fromZero && lo !== 0) min -= step;
      var ticks = [];
      for (var v = min; v <= max + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
      return { min: min, max: max, ticks: ticks };
    }
    // Measure the container, not the svg: an unrendered svg reports a default 300px.
    function width(svg) {
      var box = (svg.parentNode || svg).getBoundingClientRect();
      return Math.max(240, Math.floor(box.width) || 640);
    }
    function labelEvery(n, w) { return Math.max(1, Math.ceil(n / Math.max(2, Math.floor(w / 72)))); }

    // One tooltip per card, positioned relative to it.
    function tip(svg) {
      var card = svg.closest(".chart-card") || svg.parentNode;
      var t = card.querySelector(".chart-tip");
      if (!t) { t = document.createElement("div"); t.className = "chart-tip"; t.hidden = true; card.appendChild(t); }
      return {
        show: function (title, rows, px, py) {
          t.textContent = "";
          var h = document.createElement("div"); h.className = "tip-title"; h.textContent = title; t.appendChild(h);
          rows.forEach(function (r) {
            var d = document.createElement("div"); d.className = "tip-row";
            var s = document.createElement("strong"); s.textContent = r[1];
            var l = document.createElement("span"); l.textContent = r[0];
            d.appendChild(s); d.appendChild(l); t.appendChild(d);
          });
          t.hidden = false;
          var cr = card.getBoundingClientRect(), sr = svg.getBoundingClientRect();
          var x = sr.left - cr.left + px + 12, y = sr.top - cr.top + py - 12;
          if (x + t.offsetWidth > cr.width - 8) x = sr.left - cr.left + px - t.offsetWidth - 12;
          t.style.left = Math.max(4, x) + "px";
          t.style.top = Math.max(4, y) + "px";
        },
        hide: function () { t.hidden = true; }
      };
    }
    function rowsFor(p, yKey) {
      var rows = [[NAMES[yKey] || yKey, fmt(p[yKey])]];
      Object.keys(NAMES).forEach(function (k) {
        if (k !== yKey && typeof p[k] === "number") rows.push([NAMES[k], fmt(p[k])]);
      });
      return rows;
    }
    // Shared hover/keyboard handling: `place(i)` gives the pixel x of index i.
    function interactive(svg, n, place, onActive) {
      var active = -1;
      var set = function (i) { active = i; onActive(i); };
      svg.setAttribute("tabindex", "0");
      svg.addEventListener("pointermove", function (ev) {
        var r = svg.getBoundingClientRect(), x = ev.clientX - r.left;
        var best = 0, dist = Infinity;
        for (var i = 0; i < n; i++) { var d = Math.abs(place(i) - x); if (d < dist) { dist = d; best = i; } }
        if (best !== active) set(best);
      });
      svg.addEventListener("pointerleave", function () { set(-1); });
      svg.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowRight") { set(Math.min(n - 1, active + 1)); ev.preventDefault(); }
        else if (ev.key === "ArrowLeft") { set(Math.max(0, active < 0 ? n - 1 : active - 1)); ev.preventDefault(); }
        else if (ev.key === "Escape") set(-1);
      });
      svg.addEventListener("focus", function () { if (active < 0) set(n - 1); });
      svg.addEventListener("blur", function () { set(-1); });
    }

    // A point whose y is null (a period with no reading) keeps its slot on the axis but
    // draws nothing; the line runs straight between the readings on either side.
    // opts.y2 adds a second, muted series (Compare: you vs a friend) with no area or label.
    function line(svg, series, opts) {
      var W = width(svg), H = opts.h, L = 48, R = 20, T = 14, B = 30;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("height", H);
      var n = series.length;
      var valid = [];
      series.forEach(function (p, i) { if (typeof p[opts.y] === "number") valid.push(i); });
      if (!valid.length) { svg.hidden = true; return; }
      var ys = valid.map(function (i) { return series[i][opts.y]; });
      var valid2 = [];
      if (opts.y2) series.forEach(function (p, i) { if (typeof p[opts.y2] === "number") { valid2.push(i); ys.push(p[opts.y2]); } });
      var sc = scale(Math.min.apply(null, ys), Math.max.apply(null, ys), opts.zero);
      var x = function (i) { return n === 1 ? (L + W - R) / 2 : L + (i / (n - 1)) * (W - L - R); };
      var y = function (v) { return T + (1 - (v - sc.min) / (sc.max - sc.min)) * (H - T - B); };
      sc.ticks.forEach(function (v) {
        svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
        svg.appendChild(el("text", { x: L - 8, y: y(v) + 4, class: "axis-label", "text-anchor": "end" }, fmt(v)));
      });
      var d = valid.map(function (i, k) { return (k ? "L" : "M") + x(i).toFixed(1) + " " + y(series[i][opts.y]).toFixed(1); }).join(" ");
      var first = valid[0], last = valid[valid.length - 1];
      if (valid.length > 1 && !opts.y2) {
        var floor = (H - B).toFixed(1);
        svg.appendChild(el("path", { d: d + " L" + x(last).toFixed(1) + " " + floor + " L" + x(first).toFixed(1) + " " + floor + " Z", class: "area" }));
      }
      if (valid2.length) {
        var d2 = valid2.map(function (i, k) { return (k ? "L" : "M") + x(i).toFixed(1) + " " + y(series[i][opts.y2]).toFixed(1); }).join(" ");
        svg.appendChild(el("path", { d: d2, class: "line line-2" }));
      }
      svg.appendChild(el("path", { d: d, class: "line" }));
      var cross = el("line", { y1: T, y2: H - B, class: "crosshair" }); cross.style.display = "none"; svg.appendChild(cross);
      var every = labelEvery(n, W - L - R);
      var dotR = valid.length > 60 ? 0 : 4;
      series.forEach(function (p, i) {
        if ((i % every === 0 && n - 1 - i >= every) || i === n - 1) { // skip one that would crowd the last
          svg.appendChild(el("text", { x: x(i), y: H - B + 18, class: "axis-label", "text-anchor": "middle" }, axisLabel(p[opts.x])));
        }
      });
      var points = valid.map(function (i) {
        var c = el("circle", { cx: x(i), cy: y(series[i][opts.y]), r: dotR, class: "point" });
        svg.appendChild(c);
        return c;
      });
      var points2 = valid2.map(function (i) {
        var c = el("circle", { cx: x(i), cy: y(series[i][opts.y2]), r: dotR, class: "point point-2" });
        svg.appendChild(c);
        return c;
      });
      // Selective direct label: the latest value only.
      var lastP = series[last];
      if (!opts.y2) svg.appendChild(el("text", { x: Math.min(x(last), W - R - 4), y: y(lastP[opts.y]) - 10, class: "value-label", "text-anchor": n > 1 ? "end" : "middle" }, fmt(lastP[opts.y])));
      var t = tip(svg);
      interactive(svg, valid.length, function (k) { return x(valid[k]); }, function (k) {
        points.forEach(function (c, j) { c.setAttribute("r", j === k ? 6 : dotR); });
        points2.forEach(function (c) { c.setAttribute("r", k >= 0 && +c.getAttribute("cx") === x(valid[k]) ? 6 : dotR); });
        if (k < 0) { cross.style.display = "none"; t.hide(); return; }
        var i = valid[k], p = series[i];
        cross.style.display = ""; cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
        var rows = opts.y2
          ? [[opts.yLabel || opts.y, fmt(p[opts.y])], [opts.y2Label || opts.y2, fmt(p[opts.y2])]]
          : rowsFor(p, opts.y);
        t.show(titleLabel(p[opts.x]), rows, x(i), y(p[opts.y]));
      });
    }

    function columns(svg, series, opts) {
      var W = width(svg), H = 220, L = 44, R = 12, T = 18, B = 30;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("height", H);
      var n = series.length;
      var ys = series.map(function (p) { return p[opts.y] || 0; });
      var sc = scale(0, Math.max.apply(null, ys), true);
      var slot = (W - L - R) / n;
      var bw = Math.max(2, Math.min(24, slot - 2));
      var x = function (i) { return L + slot * (i + 0.5); };
      var y = function (v) { return T + (1 - v / sc.max) * (H - T - B); };
      sc.ticks.forEach(function (v) {
        svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
        svg.appendChild(el("text", { x: L - 8, y: y(v) + 4, class: "axis-label", "text-anchor": "end" }, fmt(v)));
      });
      var every = labelEvery(n, W - L - R);
      var maxI = ys.indexOf(Math.max.apply(null, ys));
      var bars = series.map(function (p, i) {
        var v = ys[i], top = y(v), base = H - B, r = Math.min(4, bw / 2, base - top);
        var left = x(i) - bw / 2;
        var d = v > 0
          ? "M" + left + " " + base + " V" + (top + r) + " a" + r + " " + r + " 0 0 1 " + r + " -" + r + " h" + (bw - 2 * r) +
            " a" + r + " " + r + " 0 0 1 " + r + " " + r + " V" + base + " Z"
          : "M" + left + " " + (base - 1) + " h" + bw + " v1 h-" + bw + " Z";
        var bar = el("path", { d: d, class: "bar" + (v > 0 ? "" : " empty") });
        svg.appendChild(bar);
        if ((i % every === 0 && n - 1 - i >= every) || i === n - 1) { // skip one that would crowd the last
          svg.appendChild(el("text", { x: x(i), y: H - B + 18, class: "axis-label", "text-anchor": "middle" }, axisLabel(p[opts.x])));
        }
        return bar;
      });
      if (ys[maxI] > 0) svg.appendChild(el("text", { x: x(maxI), y: y(ys[maxI]) - 6, class: "value-label", "text-anchor": "middle" }, fmt(ys[maxI])));
      var t = tip(svg);
      interactive(svg, n, x, function (i) {
        bars.forEach(function (b, j) { b.classList.toggle("active", j === i); });
        if (i < 0) { t.hide(); return; }
        t.show(titleLabel(series[i][opts.x]), rowsFor(series[i], opts.y), x(i), y(ys[i]));
      });
    }

    // Rounded bars with no axis: past periods in a soft tint, the current one (series
    // item with current: true) in coral. Labels under the first and last bar only.
    function bars(svg, series, opts) {
      var W = width(svg), H = opts.h, B = 22, T = 18;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("height", H);
      var n = series.length;
      var ys = series.map(function (p) { return p[opts.y] || 0; });
      var max = Math.max.apply(null, ys.concat([1]));
      var gap = Math.max(6, Math.min(12, W / n * 0.25));
      var bw = (W - gap * (n - 1)) / n;
      var x = function (i) { return i * (bw + gap); };
      var y = function (v) { return T + (1 - v / max) * (H - T - B); };
      var nodes = series.map(function (p, i) {
        var v = ys[i], top = v > 0 ? y(v) : H - B - 6, h = H - B - top, r = Math.min(8, bw / 2, h / 2);
        var cls = "rbar" + (p.current ? " current" : "") + (v > 0 ? "" : " zero");
        var bar = el("rect", { x: x(i).toFixed(1), y: top.toFixed(1), width: bw.toFixed(1), height: h.toFixed(1), rx: r, class: cls });
        svg.appendChild(bar);
        return bar;
      });
      var label = function (i, anchor, text) {
        svg.appendChild(el("text", { x: anchor === "end" ? x(i) + bw : x(i), y: H - 6, class: "axis-label", "text-anchor": anchor }, text));
      };
      label(0, "start", series[0][opts.x]);
      label(n - 1, "end", series[n - 1].current ? "This " + (opts.period || "week") : series[n - 1][opts.x]);
      var t = tip(svg);
      interactive(svg, n, function (i) { return x(i) + bw / 2; }, function (i) {
        nodes.forEach(function (b, j) { b.classList.toggle("active", j === i); });
        if (i < 0) { t.hide(); return; }
        var p = series[i], v = ys[i];
        t.show(p.title || p[opts.x], [[v === 1 ? "workout" : "workouts", String(v)]], x(i) + bw / 2, y(Math.max(v, 0)));
      });
    }

    function spark(svg, values) {
      var W = 96, H = 24, n = values.length;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
      if (lo === hi) { lo -= 1; hi += 1; }
      var x = function (i) { return 3 + (i / (n - 1)) * (W - 6); };
      var y = function (v) { return 3 + (1 - (v - lo) / (hi - lo)) * (H - 6); };
      var d = values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join(" ");
      svg.appendChild(el("path", { d: d, class: "line" }));
      svg.appendChild(el("circle", { cx: x(n - 1), cy: y(values[n - 1]), r: 2.5, class: "point" }));
      svg.appendChild(el("title", {}, values.map(fmt).join(" → ")));
    }

    var renderers = { line: line, columns: columns, bars: bars, spark: spark };
    function renderAll() {
      $$("svg[data-chart]").forEach(function (svg) {
        var fn = renderers[svg.dataset.chart];
        var series;
        try { series = JSON.parse(svg.dataset.series); } catch (e) { series = null; }
        if (!fn || !Array.isArray(series) || !series.length) { svg.hidden = true; return; }
        // Swap in a fresh node so old listeners go with the old render.
        var fresh = svg.cloneNode(false);
        svg.parentNode.replaceChild(fresh, svg);
        var ds = fresh.dataset;
        // data-narrow-last="8": on a narrow screen show only the latest 8 points.
        if (ds.narrowLast && width(fresh) < 480) series = series.slice(-parseInt(ds.narrowLast, 10));
        fn(fresh, series, {
          x: ds.x || "label", y: ds.y || "value", h: parseInt(ds.height, 10) || 220,
          y2: ds.y2, yLabel: ds.yLabel, y2Label: ds.y2Label, zero: "zero" in ds, period: ds.period
        });
      });
    }
    return { renderAll: renderAll };
  })();
  // ---------------------------------------------------------------- Share a day as an image
  // The button carries a JSON payload the server built without the weigh-in, so the
  // card can only ever show lifts and cardio. Drawn on a canvas, then handed to the
  // phone's share sheet (Web Share API with files) or downloaded on desktop.
  var shareBtn = $("#share-day");
  if (shareBtn) {
    var shareData = null;
    try { shareData = JSON.parse(shareBtn.dataset.share); } catch (e) { shareData = null; }
    var shareError = function (msg) {
      var box = $("#share-error");
      if (box) { box.textContent = msg; box.hidden = false; } else { window.alert(msg); }
    };
    var DISPLAY = '"Bricolage Grotesque", "Instrument Sans", system-ui, sans-serif';
    var FONT = '"Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
    var C = { bg: "#EC6A45", ink: "#1C1915", rule: "rgba(28, 25, 21, 0.25)" };
    var ellipsis = function (ctx, text, max) {
      if (ctx.measureText(text).width <= max) return text;
      while (text.length > 1 && ctx.measureText(text + "…").width > max) text = text.slice(0, -1);
      return text.replace(/\s+$/, "") + "…";
    };
    var trackedText = function (ctx, text, x, y, spacing, alignRight) {
      // Canvas letterSpacing isn't everywhere yet; draw letter by letter instead.
      var w = 0, widths = text.split("").map(function (ch) { var m = ctx.measureText(ch).width; w += m + spacing; return m; });
      w -= spacing;
      var cx = alignRight ? x - w : x;
      text.split("").forEach(function (ch, i) { ctx.fillText(ch, cx, y); cx += widths[i] + spacing; });
      return w;
    };

    // The coral poster from the day page at 1080x1350 (4:5): name and date on top,
    // the big headline, then one row per lift or activity. Never the weigh-in.
    var renderShareCard = function (data) {
      var W = 1080, H = 1350, P = 80;
      var lines = [];
      var seen = {};
      (data.lifts || []).forEach(function (l) {
        var key = l.exercise.toLowerCase();
        var weight = (l.weight || "").replace(/\s*(lbs?|kg)$/i, "");
        var sets = compact(l.sets_reps || "");
        var detail = [weight, sets].filter(Boolean).join(" × ");
        if (seen[key]) { if (l.pr) { seen[key].pr = true; seen[key].detail = detail; } return; }
        seen[key] = { name: l.exercise.charAt(0).toUpperCase() + l.exercise.slice(1), detail: detail, pr: !!l.pr };
        lines.push(seen[key]);
      });
      (data.cardio || []).forEach(function (c) {
        lines.push({ name: c.activity.charAt(0).toUpperCase() + c.activity.slice(1), detail: c.distance || c.duration || "" });
      });

      var canvas = document.createElement("canvas");
      canvas.width = W; canvas.height = H;
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = C.ink;

      // Top line: MAYA · THU 24 SEP ........ GYMLLM
      ctx.font = "700 30px " + FONT; ctx.textBaseline = "alphabetic";
      var brandW = trackedText(ctx, "GYMLLM", W - P, P + 30, 3, true);
      var top = [data.name, data.short].filter(Boolean).join(" · ");
      var maxTop = W - 2 * P - brandW - 40;
      while (top.length > 1 && ctx.measureText(top).width + top.length * 3 > maxTop) top = top.slice(0, -1);
      trackedText(ctx, top, P, P + 30, 3, false);

      // Rows from the bottom up, so the headline sits right above them.
      var rowH = 76, maxRows = 7;
      var shown = lines.length > maxRows ? lines.slice(0, maxRows - 1) : lines;
      var more = lines.length - shown.length;
      var rowsTop = H - P - (shown.length + (more ? 1 : 0)) * rowH;
      ctx.font = "600 36px " + FONT;
      shown.forEach(function (ln, i) {
        var y = rowsTop + i * rowH;
        ctx.fillStyle = C.rule; ctx.fillRect(P, y, W - 2 * P, 3);
        ctx.fillStyle = C.ink;
        var detailW = ctx.measureText(ln.detail).width;
        ctx.textAlign = "right"; ctx.fillText(ln.detail, W - P, y + 52); ctx.textAlign = "left";
        var name = ln.name + (ln.pr ? " · new best" : "");
        ctx.fillText(ellipsis(ctx, name, W - 2 * P - detailW - 32), P, y + 52);
      });
      if (more) {
        var my = rowsTop + shown.length * rowH;
        ctx.fillStyle = C.rule; ctx.fillRect(P, my, W - 2 * P, 3);
        ctx.fillStyle = C.ink; ctx.fillText("+ " + more + " more", P, my + 52);
      }

      // Headline: "8 sets. / 3 mi." shrinks until the widest line fits.
      var head = (data.headline && data.headline.length) ? data.headline : [data.label || data.date];
      var size = 176;
      var fit = function () {
        ctx.font = "800 " + size + "px " + DISPLAY;
        return Math.max.apply(null, head.map(function (t) { return ctx.measureText(t).width; }));
      };
      while (size > 72 && fit() > W - 2 * P) size -= 8;
      var lh = size * 0.9;
      var baseY = rowsTop - 48 - (head.length - 1) * lh;
      head.forEach(function (t, i) { ctx.fillText(ellipsis(ctx, t, W - 2 * P), P - 4, baseY + i * lh); });
      return canvas;
    };
    function compact(sr) {
      var parts = sr.split(",").map(function (p) { return p.trim(); });
      if (parts.length > 1 && /^\d+$/.test(parts[0]) && parts.every(function (p) { return p === parts[0]; })) return parts.length + "×" + parts[0];
      return sr;
    }

    var toBlob = function (canvas) {
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (b) { b ? resolve(b) : reject(new Error("Could not create the image.")); }, "image/png");
      });
    };
    // Render as soon as the font is in, so the click can share right away (iOS drops the
    // user activation if we do slow work first).
    var ready = (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve())
      .then(function () {
        if (!document.fonts || !document.fonts.load) return null;
        return Promise.all([document.fonts.load('800 160px "Bricolage Grotesque"'), document.fonts.load('600 36px "Instrument Sans"'), document.fonts.load('700 30px "Instrument Sans"')]);
      })
      .catch(function () { /* fall back to the system font */ })
      .then(function () { return shareData ? toBlob(renderShareCard(shareData)) : Promise.reject(new Error("Nothing to share.")); });

    // Desktop (or a share sheet that refused): save the file and show it on the page.
    var download = function (blob, name) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      var preview = $("#share-preview");
      if (preview) { var img = $("img", preview); if (img) img.src = url; preview.hidden = false; }
    };
    // The desktop header's "Share" hands its click (and the user activation) to this button.
    $$("[data-share-trigger]").forEach(function (b) { b.addEventListener("click", function () { shareBtn.click(); }); });
    shareBtn.addEventListener("click", function () {
      shareBtn.disabled = true;
      var idle = shareBtn.textContent;
      shareBtn.textContent = "Sharing…";
      var errBox = $("#share-error"); if (errBox) errBox.hidden = true;
      var done = function () { shareBtn.disabled = false; shareBtn.textContent = idle; };
      ready.then(function (blob) {
        var name = "gymllm-" + shareData.date + ".png";
        var file = new File([blob], name, { type: "image/png" });
        if (navigator.canShare && navigator.canShare({ files: [file] }) && navigator.share) {
          return navigator.share({ files: [file], title: "Workout " + shareData.date }).catch(function (err) {
            if (err && err.name === "AbortError") return; // user closed the sheet
            download(blob, name); // the sheet would not open here; a file is the next best thing
          });
        }
        download(blob, name);
      }).then(done, function (err) {
        done();
        shareError((err && err.message) || "Could not share this workout.");
      });
    });
  }

  // ---------------------------------------------------------------- Popover
  // One floating panel at a time (calendar, suggestions, select list), placed under
  // the control that opened it. Lives on <body> so table wrappers can't clip it.
  var popover = (function () {
    var node = null, owner = null, onClose = null, matchWidth = false;
    function place() {
      if (!node) return;
      var r = owner.getBoundingClientRect();
      node.style.minWidth = matchWidth ? r.width + "px" : "";
      var maxLeft = window.scrollX + document.documentElement.clientWidth - node.offsetWidth - 8;
      node.style.left = Math.max(window.scrollX + 8, Math.min(r.left + window.scrollX, maxLeft)) + "px";
      node.style.top = (r.bottom + window.scrollY + 4) + "px";
    }
    function close(refocus) {
      if (!node) return;
      var o = owner, cb = onClose;
      node.remove();
      node = owner = onClose = null;
      if (cb) cb();
      if (refocus && o) o.focus();
    }
    function open(anchor, panel, opts) {
      close(false);
      opts = opts || {};
      node = panel; owner = anchor; onClose = opts.onClose; matchWidth = !!opts.matchWidth;
      panel.classList.add("popover");
      document.body.appendChild(panel);
      place();
    }
    document.addEventListener("pointerdown", function (ev) {
      if (node && !node.contains(ev.target) && !owner.contains(ev.target)) close(false);
    }, true);
    window.addEventListener("resize", place);
    return { open: open, close: close, place: place, node: function () { return node; }, isOpenFor: function (a) { return !!node && owner === a; } };
  })();

  var escHtml = function (s) { return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); };
  var MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  function isoOf(d) {
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function parseIso(v) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }
  function niceDate(v) {
    var d = parseIso(v);
    return d ? DOW[d.getDay()] + " " + d.getDate() + " " + MONTH_NAMES[d.getMonth()].slice(0, 3) + " " + d.getFullYear() : "Pick a date";
  }
  // Point a <label for=…> at the button that now stands in for a hidden control.
  function relabel(control, btn) {
    if (!control.id) return;
    btn.id = control.id + "-btn";
    var label = $('label[for="' + control.id + '"]');
    if (label) label.htmlFor = btn.id;
  }

  // ---------------------------------------------------------------- Date picker
  // Each <input type="date"> is hidden (it still submits) behind a button that opens
  // a month calendar. Picking sets the input and fires "change".
  function openCalendar(input, btn) {
    var today = parseIso(localDate()), sel = parseIso(input.value), focus = sel || today;
    var box = document.createElement("div");
    box.className = "cal";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Choose a date");
    var render = function () {
      var first = new Date(focus.getFullYear(), focus.getMonth(), 1);
      var start = new Date(first.getFullYear(), first.getMonth(), 1 - ((first.getDay() + 6) % 7));
      var html = '<div class="cal-head"><button type="button" class="cal-nav" data-step="-1" aria-label="Previous month">&lsaquo;</button>' +
        '<span class="cal-title">' + MONTH_NAMES[first.getMonth()] + " " + first.getFullYear() + "</span>" +
        '<button type="button" class="cal-nav" data-step="1" aria-label="Next month">&rsaquo;</button></div><div class="cal-grid">';
      "MTWTFSS".split("").forEach(function (l) { html += '<span class="cal-dow" aria-hidden="true">' + l + "</span>"; });
      for (var i = 0; i < 42; i++) {
        var d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i), v = isoOf(d);
        var cls = "cal-day" + (d.getMonth() !== first.getMonth() ? " is-outside" : "") +
          (sel && v === isoOf(sel) ? " is-selected" : "") + (v === isoOf(today) ? " is-today" : "");
        html += '<button type="button" class="' + cls + '" data-date="' + v + '" aria-label="' + niceDate(v) + '"' +
          (sel && v === isoOf(sel) ? ' aria-pressed="true"' : "") + ' tabindex="' + (v === isoOf(focus) ? 0 : -1) + '">' + d.getDate() + "</button>";
      }
      html += '</div><div class="cal-foot"><button type="button" class="btn btn-text btn-sm" data-date="' + isoOf(today) + '">Today</button></div>';
      box.innerHTML = html;
    };
    var focusDay = function () {
      var b = box.querySelector('.cal-day[data-date="' + isoOf(focus) + '"]');
      if (b) b.focus();
    };
    var pick = function (v) {
      input.value = v;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      popover.close(true);
    };
    box.addEventListener("click", function (ev) {
      var nav = ev.target.closest("[data-step]");
      if (nav) {
        focus = new Date(focus.getFullYear(), focus.getMonth() + parseInt(nav.dataset.step, 10), 1);
        render();
        box.querySelector('[data-step="' + nav.dataset.step + '"]').focus();
        return;
      }
      var day = ev.target.closest("[data-date]");
      if (day) pick(day.dataset.date);
    });
    box.addEventListener("keydown", function (ev) {
      var moves = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      if (ev.key === "Escape") { ev.preventDefault(); popover.close(true); return; }
      if (!ev.target.classList.contains("cal-day")) return;
      if (moves[ev.key]) focus = new Date(focus.getFullYear(), focus.getMonth(), focus.getDate() + moves[ev.key]);
      else if (ev.key === "PageUp" || ev.key === "PageDown") focus = new Date(focus.getFullYear(), focus.getMonth() + (ev.key === "PageUp" ? -1 : 1), 1);
      else return;
      ev.preventDefault();
      render();
      focusDay();
    });
    render();
    btn.setAttribute("aria-expanded", "true");
    popover.open(btn, box, { onClose: function () { btn.setAttribute("aria-expanded", "false"); } });
    focusDay();
  }
  function initDatePickers(root) {
    $$('input[type="date"]', root).forEach(function (input) {
      if (input.dataset.enhanced) return;
      input.dataset.enhanced = "1";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = (input.className.replace(/\bclient-date\b/, "") + " date-trigger").trim();
      btn.setAttribute("aria-haspopup", "dialog");
      relabel(input, btn);
      // data-label: a fixed caption ("Pick a date"); data-relative: "Today · Thu 24 Sep".
      var sync = function () { btn.textContent = input.dataset.label || ("relative" in input.dataset ? relativeDate(input.value) : niceDate(input.value)); };
      sync();
      input.addEventListener("change", sync);
      input.hidden = true;
      input.parentNode.insertBefore(btn, input.nextSibling);
      // data-trigger: other elements (the day page's title) that open the same calendar.
      var triggers = [btn].concat(input.dataset.trigger ? $$(input.dataset.trigger) : []);
      triggers.forEach(function (t) {
        t.setAttribute("aria-haspopup", "dialog");
        t.addEventListener("click", function () {
          if (popover.isOpenFor(t)) popover.close(true); else openCalendar(input, t);
        });
      });
    });
  }
  function relativeDate(v) {
    var d = parseIso(v);
    if (!d) return "Pick a date";
    var today = parseIso(localDate());
    var days = Math.round((today - d) / 86400000);
    var short = DOW[d.getDay()] + " " + d.getDate() + " " + MONTH_NAMES[d.getMonth()].slice(0, 3) + (d.getFullYear() !== today.getFullYear() ? " " + d.getFullYear() : "");
    return (days === 0 ? "Today · " : days === 1 ? "Yesterday · " : "") + short;
  }

  // ---------------------------------------------------------------- Autocomplete
  // Inputs with list="…" get a styled suggestion panel instead of the browser's
  // datalist popup. Options are read from the datalist each time, so lists filled
  // later by script (Settings models) still work.
  var suggest = { input: null, items: [], active: -1 };
  function suggestItems(input) {
    var dl = document.getElementById(input.dataset.suggest);
    if (!dl) return [];
    var q = input.value.trim().toLowerCase(), seen = {}, out = [];
    $$("option", dl).forEach(function (o) {
      var k = o.value.toLowerCase();
      if (!o.value || seen[k] || k === q || (q && k.indexOf(q) === -1)) return;
      seen[k] = true;
      out.push(o.value);
    });
    // Matches at the start of the name first; otherwise keep the list's order.
    out.sort(function (a, b) { return (a.toLowerCase().indexOf(q) !== 0) - (b.toLowerCase().indexOf(q) !== 0); });
    return out.slice(0, 8);
  }
  function suggestSetActive(i) {
    var box = popover.node();
    suggest.active = i;
    $$(".suggest-item", box).forEach(function (li, j) { li.classList.toggle("is-active", j === i); li.setAttribute("aria-selected", j === i ? "true" : "false"); });
    if (i >= 0) {
      suggest.input.setAttribute("aria-activedescendant", "suggest-" + i);
      box.children[i].scrollIntoView({ block: "nearest" });
    } else {
      suggest.input.removeAttribute("aria-activedescendant");
    }
  }
  function showSuggest(input) {
    var items = suggestItems(input);
    if (!items.length) { if (popover.isOpenFor(input)) popover.close(false); return; }
    var open = popover.isOpenFor(input);
    var box = open ? popover.node() : document.createElement("ul");
    box.id = "suggest-list";
    box.className = "popover suggest";
    box.setAttribute("role", "listbox");
    box.innerHTML = items.map(function (v, i) {
      return '<li role="option" id="suggest-' + i + '" class="suggest-item" aria-selected="false" data-value="' + escHtml(v) + '">' + escHtml(v) + "</li>";
    }).join("");
    suggest.input = input; suggest.items = items; suggest.active = -1;
    input.setAttribute("aria-expanded", "true");
    input.removeAttribute("aria-activedescendant");
    if (open) { popover.place(); return; }
    box.addEventListener("pointerdown", function (ev) { ev.preventDefault(); }); // keep focus in the input
    box.addEventListener("click", function (ev) {
      var li = ev.target.closest(".suggest-item");
      if (li) pickSuggest(li.dataset.value);
    });
    popover.open(input, box, {
      matchWidth: true,
      onClose: function () { input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); suggest.input = null; }
    });
  }
  function pickSuggest(value) {
    var input = suggest.input;
    input.value = value;
    popover.close(false);
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function enhanceSuggest(input) {
    input.dataset.suggest = input.getAttribute("list");
    input.removeAttribute("list");
    input.setAttribute("autocomplete", "off");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", "suggest-list");
    input.setAttribute("aria-expanded", "false");
  }
  function initSuggest(root) { $$("input[list]", root).forEach(enhanceSuggest); }
  document.addEventListener("focusin", function (ev) {
    var t = ev.target;
    if (!t.matches || !t.matches("input[list], input[data-suggest]")) return;
    if (t.hasAttribute("list")) enhanceSuggest(t); // rows added after load
    showSuggest(t);
  });
  document.addEventListener("focusout", function (ev) {
    if (suggest.input && ev.target === suggest.input) popover.close(false);
  });
  document.addEventListener("input", function (ev) {
    if (ev.target.dataset && ev.target.dataset.suggest) showSuggest(ev.target);
  });
  // Capture phase, so an Enter that picks a suggestion lands before the page's own
  // Enter handlers (the Log page adds the picked exercise straight away).
  document.addEventListener("keydown", function (ev) {
    var input = ev.target;
    if (!input.dataset || !input.dataset.suggest) return;
    var open = popover.isOpenFor(input);
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!open) { showSuggest(input); return; }
      var n = suggest.items.length, step = ev.key === "ArrowDown" ? 1 : -1;
      suggestSetActive(suggest.active < 0 ? (step > 0 ? 0 : n - 1) : (suggest.active + step + n) % n);
    } else if (ev.key === "Enter" && open) {
      if (suggest.active >= 0) { ev.preventDefault(); pickSuggest(suggest.items[suggest.active]); }
      else popover.close(false);
    } else if (ev.key === "Escape" && open) {
      ev.preventDefault();
      popover.close(false);
    }
  }, true);

  // ---------------------------------------------------------------- Select
  // <select class="select"> becomes a button + styled list; the hidden select keeps
  // the value and still fires "change" for the page's own logic.
  function openSelect(select, btn) {
    var opts = Array.prototype.filter.call(select.options, function (o) { return !o.disabled; });
    var box = document.createElement("ul");
    box.className = "select-list";
    box.setAttribute("role", "listbox");
    box.innerHTML = opts.map(function (o) {
      var on = o.value === select.value;
      return '<li role="option" tabindex="-1" class="suggest-item' + (on ? " is-selected" : "") + '" aria-selected="' + on + '" data-value="' + escHtml(o.value) + '">' + escHtml(o.text) + "</li>";
    }).join("");
    var items = $$("li", box);
    var pick = function (v) {
      if (select.value !== v) { select.value = v; select.dispatchEvent(new Event("change", { bubbles: true })); }
      popover.close(true);
    };
    box.addEventListener("click", function (ev) {
      var li = ev.target.closest("li");
      if (li) pick(li.dataset.value);
    });
    box.addEventListener("keydown", function (ev) {
      var i = items.indexOf(document.activeElement);
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); items[(i + (ev.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus(); }
      else if (ev.key === "Home" || ev.key === "End") { ev.preventDefault(); items[ev.key === "Home" ? 0 : items.length - 1].focus(); }
      else if ((ev.key === "Enter" || ev.key === " ") && i >= 0) { ev.preventDefault(); pick(items[i].dataset.value); }
      else if (ev.key === "Escape" || ev.key === "Tab") { ev.preventDefault(); popover.close(true); }
    });
    btn.setAttribute("aria-expanded", "true");
    popover.open(btn, box, { matchWidth: true, onClose: function () { btn.setAttribute("aria-expanded", "false"); } });
    (items.filter(function (li) { return li.classList.contains("is-selected"); })[0] || items[0]).focus();
  }
  function initSelects(root) {
    $$("select.select", root).forEach(function (select) {
      if (select.dataset.enhanced) return;
      select.dataset.enhanced = "1";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "select select-trigger";
      btn.setAttribute("aria-haspopup", "listbox");
      relabel(select, btn);
      var sync = function () { var o = select.options[select.selectedIndex]; btn.textContent = o ? o.text : ""; };
      sync();
      select.addEventListener("change", sync);
      select.hidden = true;
      select.parentNode.insertBefore(btn, select.nextSibling);
      btn.addEventListener("click", function () {
        if (popover.isOpenFor(btn)) popover.close(true); else openSelect(select, btn);
      });
      btn.addEventListener("keydown", function (ev) {
        if ((ev.key === "ArrowDown" || ev.key === "ArrowUp") && !popover.isOpenFor(btn)) { ev.preventDefault(); openSelect(select, btn); }
      });
    });
  }

  // ---------------------------------------------------------------- Social
  // Kudos toggle in place; without JS the form posts and the page reloads at the card.
  document.addEventListener("submit", function (ev) {
    var form = ev.target.closest("form.kudos-form");
    if (!form || !window.fetch) return;
    ev.preventDefault();
    var btn = $("button", form);
    btn.disabled = true;
    fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json", "X-CSRFToken": csrfToken() }
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (data) {
      btn.classList.toggle("is-on", data.mine);
      btn.setAttribute("aria-pressed", data.mine ? "true" : "false");
      $(".kudos-count", btn).textContent = data.count;
    }).catch(function () {
      form.submit();
    }).then(function () {
      btn.disabled = false;
    });
  });
  // "N comments" sits beside High five as a pill; the thread opens full width below.
  // Without this script the <details> summary does the same job.
  function initComments(root) {
    $$(".social-bar > details.comments", root).forEach(function (details, n) {
      if (details.dataset.enhanced) return;
      details.dataset.enhanced = "1";
      var summary = $("summary", details);
      var pill = document.createElement("button");
      pill.type = "button";
      pill.className = "comments-pill";
      pill.textContent = summary.textContent.trim();
      if (!details.id) details.id = "comments-" + n + "-" + Math.random().toString(36).slice(2, 7);
      pill.setAttribute("aria-controls", details.id);
      var sync = function () { pill.setAttribute("aria-expanded", details.open ? "true" : "false"); };
      sync();
      details.addEventListener("toggle", sync);
      pill.addEventListener("click", function () {
        details.open = !details.open;
        var field = details.open && $("input[name=body]", details);
        if (field) field.focus();
      });
      details.parentNode.insertBefore(pill, details);
    });
  }

  // Copy buttons: <button data-copy="#input-id">.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("button[data-copy]");
    if (!btn) return;
    var input = $(btn.dataset.copy);
    if (!input) return;
    var done = function () {
      var label = btn.dataset.label || btn.textContent;
      btn.dataset.label = label;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = label; }, 1500);
    };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
    } else {
      input.select();
    }
  });

  // ---------------------------------------------------------------- Page setup
  // Everything that has to run again when <main> is swapped in without a reload.
  function enhance(root) {
    initSortable(root);
    initFilters(root);
    initDatePickers(root);
    initSuggest(root);
    initSelects(root);
    initComments(root);
    charts.renderAll();
  }
  enhance(document);
  var resizeTimer = null, lastWidth = window.innerWidth;
  window.addEventListener("resize", function () {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(charts.renderAll, 150);
  });

  // ---------------------------------------------------------------- Filters without a reload
  // Range and grouping links fetch the page and swap <main> in place. The Sessions
  // edit form has state of its own, so its links still load a fresh page.
  var main = $("main");
  function swapTo(url, push) {
    main.classList.add("is-loading");
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text().then(function (html) { return { html: html, url: r.url }; });
    }).then(function (res) {
      var doc = new DOMParser().parseFromString(res.html, "text/html");
      var next = doc.querySelector("main");
      if (!next || new URL(res.url).pathname !== new URL(url, location.href).pathname) throw new Error("unexpected page");
      var y = window.scrollY;
      popover.close(false);
      main.innerHTML = next.innerHTML;
      document.title = doc.title;
      if (push) history.pushState({ swap: true }, "", url);
      enhance(main);
      window.scrollTo(0, y);
    }).catch(function () {
      window.location.href = url;
    }).then(function () {
      main.classList.remove("is-loading");
    });
  }
  if (main && $(".filters", main)) {
    history.replaceState({ swap: true }, "");
    main.addEventListener("click", function (ev) {
      var a = ev.target.closest(".filters .segmented a, a.week-arrow, a.week-jump");
      if (!a || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      if ($("#log-edit-form")) return;
      ev.preventDefault();
      swapTo(a.href, true);
    });
    window.addEventListener("popstate", function (ev) {
      if (ev.state && ev.state.swap) swapTo(location.href, false);
    });
  }
})();
