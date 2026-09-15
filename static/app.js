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
      var errBox = $("#llm-error"); if (errBox) errBox.hidden = true;
      setBusy(form, true, "Parsing with " + cfg.model + " in your browser\u2026");
      fetch("/llm/prompt?date=" + encodeURIComponent(when), { credentials: "same-origin" })
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

  // ---------------------------------------------------------------- Table filter
  // <input data-filter="#table" data-count="#counter"> hides rows that don't match.
  $$("input[data-filter]").forEach(function (input) {
    var table = $(input.dataset.filter);
    if (!table || !table.tBodies[0]) return;
    var counter = input.dataset.count ? $(input.dataset.count) : null;
    var rows = $$("tr", table.tBodies[0]);
    var noun = counter ? (counter.textContent.match(/[a-z]+$/i) || ["rows"])[0].replace(/s$/, "") : "row";
    var apply = function () {
      var q = input.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var show = !q || rowText(row).indexOf(q) !== -1;
        row.hidden = !show;
        if (show) shown++;
      });
      if (counter) counter.textContent = shown + " " + noun + (shown === 1 ? "" : "s") + (q ? " match" : "");
    };
    input.addEventListener("input", apply);
  });

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
      var rows = $$("tbody tr", entriesTable).filter(function (tr) {
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
      setBusy(confirmForm, true, "Checking exercise names\u2026");
      fetch(confirmForm.dataset.tagTargetsUrl || "/llm/tag-targets", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        credentials: "same-origin",
        body: JSON.stringify({ names: names })
      }).then(function (r) { return r.ok ? r.json() : { unmatched: [] }; }).then(function (data) {
        var todo = (data.unmatched || []).map(function (n) { return String(n).toLowerCase(); }).filter(function (n) { return byName[n]; });
        if (!todo.length) return;
        setBusy(confirmForm, true, "Tagging " + todo.length + " new exercise" + (todo.length === 1 ? "" : "s") + " with " + tagCfg.model + "\u2026");
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
  if (confirmForm && entriesTable) {
    confirmForm.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".row-remove");
      if (!btn) return;
      var row = btn.closest("tr");
      var box = $(".delete-box", row);
      var removing = !row.classList.contains("row-deleted");
      row.classList.toggle("row-deleted", removing);
      if (box) box.checked = removing;
      btn.textContent = removing ? "Undo" : "Remove";
    });

    var addRow = $("#add-row");
    var numField = $("#num_entries");
    if (addRow && numField) addRow.addEventListener("click", function () {
      var i = parseInt(numField.value, 10) || 0;
      var tr = document.createElement("tr");
      var text = function (name, extra) {
        return '<td' + (name === "exercise" ? ' class="exercise-cell"' : "") + '><input type="text" name="entry-' + i + "-" + name +
          '" aria-label="' + name.charAt(0).toUpperCase() + name.slice(1) + '"' + (extra || "") + "></td>";
      };
      tr.innerHTML = text("exercise", ' list="exercise-names"') + text("weight", ' placeholder="185 lbs"') +
        text("sets", ' class="narrow" inputmode="numeric"') + text("reps", ' placeholder="10, 8, 6"') + text("notes") +
        '<td class="col-actions"><input type="checkbox" name="entry-' + i + '-delete" value="1" class="delete-box" hidden tabindex="-1" aria-hidden="true">' +
        '<button type="button" class="btn btn-text row-remove">Remove</button></td>';
      entriesTable.tBodies[0].appendChild(tr);
      numField.value = i + 1;
      var submit = $('button[type=submit]', confirmForm);
      if (submit) submit.disabled = false;
      tr.querySelector("input[type=text]").focus();
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
      // area + line
      var d = xs.map(function (i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(ys[i]).toFixed(1); }).join(" ");
      if (series.length > 1) {
        var floor = (H - B).toFixed(1);
        svg.appendChild(el("path", { d: d + " L" + x(series.length - 1).toFixed(1) + " " + floor + " L" + x(0).toFixed(1) + " " + floor + " Z", class: "area" }));
      }
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
