/* tracker.js — user tracker list with status filters. */
(function () {
  "use strict";
  var refreshTimer = null;

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g,
      function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  window.refreshTracker = function () {
    var status = $("tracker-filter").value || null;
    var order = $("tracker-sort").value || "recent";
    callApi("getUsers", { status: status, order: order, limit: 500 }).then(function (data) {
      if (!data) return;
      State.users = data.rows || [];
      renderCounts(data.counts || {});
      renderUsers();
    });
  };

  function renderUsers() {
    var box = $("tracker");
    box.innerHTML = "";
    State.users.forEach(function (u) {
      var row = document.createElement("div");
      row.className = "user-row";
      var meta = u.registered ? "registered" : "guest";
      var extra = u.status === "MESSAGED"
        ? "messages: " + u.message_count
        : u.status === "SKIPPED" && u.skip_reason ? "reason: " + u.skip_reason
        : "seen " + (u.last_seen || "");
      row.innerHTML =
        '<div class="right"><span class="badge ' + esc(u.status) + '">' + esc(u.status) + "</span></div>" +
        '<div class="nick">' + esc(u.nickname) + "</div>" +
        '<div class="meta">' + (u.gender === "FEMALE" ? "♀" : u.gender === "MALE" ? "♂" : "?") +
        "  " + meta + " • " + esc(extra) + "</div>";
      row.title = "click for actions";
      row.addEventListener("click", function () { userMenu(u, row); });
      box.appendChild(row);
    });
    if (!State.users.length) {
      box.innerHTML = '<div class="hint" style="padding:8px">No users yet — run a Scroll &amp; Parse block.</div>';
    }
  }

  function userMenu(u, row) {
    var choice = prompt(
      u.nickname + "  [" + u.status + "]\n\n1 — reset to NEW\n2 — mark SKIPPED\n3 — delete\n4 — note\n" +
      (u.status === "MESSAGED" ? u.messaged_at : ""), "1");
    if (!choice) return;
    if (choice === "1") callApi("userAction", { action: "reset", id: u.id });
    else if (choice === "2") callApi("userAction", { action: "skip", id: u.id, reason: "manual" });
    else if (choice === "3") callApi("userAction", { action: "delete", id: u.id });
    else if (choice === "4") {
      var note = prompt("Note for " + u.nickname + ":", u.notes || "");
      if (note != null) callApi("userAction", { action: "note", id: u.id, notes: note });
    }
    refreshTracker();
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refreshTracker, 400);
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("tracker-filter").addEventListener("change", refreshTracker);
    $("tracker-sort").addEventListener("change", refreshTracker);
    $("btn-tracker-refresh").addEventListener("click", refreshTracker);
    $("btn-csv-export").addEventListener("click", function () {
      callApi("exportCsv").then(function (r) {
        if (r && r.ok) logLine("ok", "CSV exported: " + r.path + " (" + r.count + " rows)");
      });
    });
    $("btn-csv-import").addEventListener("click", function () {
      callApi("importCsv").then(function (r) {
        if (r && r.ok) logLine("ok", "CSV imported: " + r.imported + " rows");
        refreshTracker();
      });
    });
    $("btn-tracker-reset").addEventListener("click", function () {
      if (!confirm("Reset status of all NEW/QUEUED/SKIPPED users?")) return;
      callApi("resetUsers").then(function (r) {
        if (r && r.ok) { logLine("warn", "Reset " + r.reset + " users"); refreshTracker(); }
      });
    });
    refreshTracker();
  });
})();
