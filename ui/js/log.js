/* log.js — live execution log panel. */
(function () {
  "use strict";
  var MAX_LINES = 500;
  var lines = [];

  function $(id) { return document.getElementById(id); }

  window.logLine = function (cls, text) {
    var el = $("log");
    var ts = new Date().toTimeString().slice(0, 8);
    lines.push(ts + "  " + text);
    if (lines.length > MAX_LINES) lines.splice(0, lines.length - MAX_LINES);
    var div = document.createElement("div");
    div.className = "log-line" + (cls ? " " + cls : "");
    var tsSpan = document.createElement("span");
    tsSpan.className = "ts";
    tsSpan.textContent = ts + "  ";
    div.appendChild(tsSpan);
    div.appendChild(document.createTextNode(text));
    el.appendChild(div);
    while (el.childElementCount > MAX_LINES) el.removeChild(el.firstChild);
    if ($("log-autoscroll").checked) el.scrollTop = el.scrollHeight;
  };

  function onBusEvent(name, payload) {
    if (name === "log") {
      var cls = payload.level === "error" ? "err"
              : payload.level === "warn" ? "warn" : "";
      logLine(cls, (payload.icon ? payload.icon + " " : "") + payload.msg);
    } else if (name === "error") {
      logLine("err", "ERROR [" + payload.code + "] " + payload.msg);
    } else if (name === "run_summary") {
      logLine("ok", "Run summary: sent=" + payload.sent + " passes=" + payload.passes +
        " errors=" + payload.errors + " new=" + payload.new_users +
        " (" + payload.elapsed + "s)");
    } else if (name === "connection_lost") {
      logLine("err", "Chat tab lost — reconnect Chrome and resume when ready.");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("cf-api-ready", function () { Bus.on("log", onBusEvent); Bus.on("error", onBusEvent); Bus.on("run_summary", onBusEvent); Bus.on("connection_lost", onBusEvent); });
    $("btn-log-clear").addEventListener("click", function () {
      lines = [];
      $("log").innerHTML = "";
    });
    $("btn-log-save").addEventListener("click", function () {
      callApi("saveLog", { text: lines.join("\n") }).then(function (r) {
        if (r && r.ok) logLine("ok", "Log saved: " + r.path);
      });
    });
    logLine("", "UI ready. Waiting for API…");
  });
})();
