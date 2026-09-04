/* composer.js — filter rules + message composer + image folder. */
(function () {
  "use strict";
  var OPS = {
    CLASS_INCLUDES: "Must contain class",
    CLASS_EXCLUDES: "Must NOT contain class",
    REGEX_MATCH: "Nickname matches regex",
    REGEX_NOT_MATCH: "Nickname NOT matches regex"
  };

  function $(id) { return document.getElementById(id); }

  function renderRules(rules) {
    State.rules = rules || [];
    var box = $("rules");
    box.innerHTML = "";
    State.rules.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "rule";
      var cb = document.createElement("input");
      cb.type = "checkbox"; cb.className = "enabled"; cb.checked = r.enabled;
      cb.addEventListener("change", function () {
        callApi("saveRule", Object.assign({}, r, { enabled: cb.checked }))
          .then(function (d) { renderRules(d && d.rules); });
      });
      var op = document.createElement("span");
      op.className = "op";
      op.textContent = OPS[r.type] || r.type;
      var input = document.createElement("input");
      input.type = "text";
      input.value = r.type.indexOf("REGEX") === 0 ? r.value : r.selector;
      input.addEventListener("change", function () {
        var next = Object.assign({}, r);
        if (r.type.indexOf("REGEX") === 0) next.value = input.value;
        else next.selector = input.value;
        callApi("saveRule", next).then(function (d) {
          if (d && !d.ok) { alert("Rule invalid: " + d.error); }
          renderRules(d && d.rules);
        });
      });
      var del = document.createElement("button");
      del.textContent = "✕";
      del.addEventListener("click", function () {
        callApi("deleteRule", { rule_id: r.rule_id }).then(function (d) {
          renderRules(d && d.rules);
        });
      });
      row.appendChild(cb); row.appendChild(op); row.appendChild(input); row.appendChild(del);
      box.appendChild(row);
    });
  }

  function refreshImageRow() {
    callApi("getComposer").then(function (d) {
      if (!d) return;
      $("img-folder").textContent = d.image_folder ? d.image_folder + " (" + d.image_count + " files)" : "—";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    callApi("getRules").then(function (d) { renderRules(d && d.rules); });
    callApi("getComposer").then(function (d) {
      if (!d) return;
      $("message").value = d.message || "";
      if (d.pool) document.querySelector('input[name="msgmode"][value="pool"]').checked = true;
      $("img-attach").checked = !!d.attach_image;
      refreshImageRow();
    });

    $("btn-add-rule").addEventListener("click", function () {
      var type = prompt("New rule type:\n1 — Must contain class (e.g. female-avatar)\n2 — Must NOT contain class (e.g. registered-badge)\n3 — Nickname matches regex\n4 — Nickname NOT matches regex", "1");
      var map = { "1": "CLASS_INCLUDES", "2": "CLASS_EXCLUDES", "3": "REGEX_MATCH", "4": "REGEX_NOT_MATCH" };
      if (!type || !map[type]) return;
      var val = prompt("Value (class name or regex):", "");
      if (val == null) return;
      var isRegex = type.charAt(0) === "3" || type.charAt(0) === "4";
      callApi("saveRule", {
        type: map[type],
        selector: isRegex ? "nickname" : val,
        value: isRegex ? val : "",
        enabled: true,
        position: State.rules.length
      }).then(function (d) {
        if (d && !d.ok) alert("Rule invalid: " + d.error);
        renderRules(d && d.rules);
      });
    });

    function bindComposer() {
      var mode = document.querySelector('input[name="msgmode"]:checked').value;
      var payload = {
        message: mode === "pool" ? $("message").value : $("message").value,
        pool: mode === "pool" ? $("message").value : "",
        attach_image: $("img-attach").checked
      };
      // single mode stores message, pool mode stores pool (textarea = active editor)
      payload.message = mode === "single" ? $("message").value : (State._single || "");
      payload.pool = mode === "pool" ? $("message").value : (State._pool || "");
      return payload;
    }
    State._single = $("message").value;
    State._pool = "";
    document.querySelectorAll('input[name="msgmode"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        var mode = document.querySelector('input[name="msgmode"]:checked').value;
        if (mode === "single") {
          State._pool = $("message").value;
          $("message").value = State._single;
        } else {
          State._single = $("message").value;
          $("message").value = State._pool;
        }
        updateCount();
      });
    });
    function updateCount() {
      var n = $("message").value.length;
      $("char-count").textContent = n + " / 1000";
      $("char-count").style.color = n >= 1000 ? "#F44336" : "";
    }
    $("message").addEventListener("input", updateCount);
    updateCount();

    $("btn-img-browse").addEventListener("click", function () {
      callApi("browseImageFolder").then(function (r) {
        if (r && r.ok) {
          $("img-folder").textContent = r.path + " (" + r.count + " files)";
          logLine("ok", "Image folder: " + r.path + " (" + r.count + " files)");
        }
      });
    });

    $("btn-save-composer").addEventListener("click", function () {
      var payload = bindComposer();
      State._single = payload.message;
      State._pool = payload.pool;
      callApi("saveComposer", payload).then(function (r) {
        if (r && r.ok) logLine("ok", "Composer saved");
      });
    });
  });
})();
