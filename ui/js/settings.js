/* settings.js — settings modal (docs §8.7). */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  window.openSettings = function () {
    $("settings-modal").classList.remove("hidden");
    callApi("getSettings").then(function (s) {
      if (!s) return;
      $("st-host").value = s.cdp_host;
      $("st-port").value = s.cdp_port;
      $("st-pattern").value = s.tab_url_pattern;
      $("st-jitter").value = s.jitter;
      $("st-cps").value = s.typing_cps;
      $("st-var").value = s.typing_var;
      $("st-mpe").value = s.micro_pause_every;
      $("st-mps").value = s.micro_pause_sec;
      $("st-cooldown").value = s.cooldown_days;
      $("st-level").value = s.log_level || "INFO";
      $("st-retention").value = s.retention_days;
      $("st-policy").value = s.fail_policy || "skip_block";
    });
  };

  function closeModal() { $("settings-modal").classList.add("hidden"); }

  function saveSettings() {
    var payload = {
      cdp_host: $("st-host").value,
      cdp_port: parseInt($("st-port").value, 10) || 9222,
      tab_url_pattern: $("st-pattern").value,
      jitter: parseFloat($("st-jitter").value) || 0,
      typing_cps: parseInt($("st-cps").value, 10) || 60,
      typing_var: parseFloat($("st-var").value) || 0,
      micro_pause_every: parseInt($("st-mpe").value, 10) || 0,
      micro_pause_sec: parseFloat($("st-mps").value) || 0,
      cooldown_days: parseInt($("st-cooldown").value, 10) || 0,
      log_level: $("st-level").value,
      retention_days: parseInt($("st-retention").value, 10) || 7,
      fail_policy: $("st-policy").value
    };
    callApi("saveSettings", payload).then(function (r) {
      if (r && r.ok) { logLine("ok", "Settings saved"); closeModal(); }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("btn-settings-close").addEventListener("click", closeModal);
    $("btn-settings-cancel").addEventListener("click", closeModal);
    $("btn-settings-save").addEventListener("click", saveSettings);
    $("btn-test-conn").addEventListener("click", function () {
      $("test-result").textContent = "testing…";
      // apply connection fields to settings first so the test uses them
      callApi("saveSettings", {
        cdp_host: $("st-host").value,
        cdp_port: parseInt($("st-port").value, 10) || 9222,
        tab_url_pattern: $("st-pattern").value
      }).then(function () {
        return callApi("testConnection");
      });
    });
    $("btn-reset-memory").addEventListener("click", function () {
      if (!confirm("Delete ALL remembered users?")) return;
      callApi("resetUsers").then(function (r) {
        if (r && r.ok) logLine("warn", "Memory reset: " + r.reset + " users");
      });
    });
    Bus.on("test_result", function (r) {
      $("test-result").textContent = r.ok
        ? "OK — " + r.pages + " pages" + (r.chat_tab_found ? ", chat tab found" : ", NO chat tab")
        : "FAIL — " + r.error;
      $("test-result").style.color = r.ok ? "#4CAF50" : "#F44336";
    });
  });
})();
