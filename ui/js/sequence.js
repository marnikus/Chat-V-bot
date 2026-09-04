/* sequence.js — sequence builder: render, reorder, params, presets. */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function defaultParams(schema) {
    var p = {};
    (schema.params || []).forEach(function (f) { p[f.key] = f.default; });
    return p;
  }

  window.addBlock = function (actionType, index) {
    var schema = State.schemas[actionType] || { icon: "❓", label: actionType, params: [] };
    var block = {
      block_id: uuid(),
      action_type: actionType,
      params: defaultParams(schema),
      delay_after: 1.0,
      enabled: true,
      position: index == null ? State.blocks.length : index
    };
    if (index == null) State.blocks.push(block);
    else State.blocks.splice(index, 0, block);
    renderSequence();
  };

  function removeBlock(id) {
    State.blocks = State.blocks.filter(function (b) { return b.block_id !== id; });
    renderSequence();
  }

  function renderParamFields(body, schema, block) {
    (schema.params || []).forEach(function (f) {
      var row = document.createElement("div");
      row.className = "row";
      var label = document.createElement("label");
      label.textContent = f.label + ":";
      var input;
      if (f.type === "select") {
        input = document.createElement("select");
        (f.options || []).forEach(function (opt) {
          var o = document.createElement("option");
          o.value = opt; o.textContent = opt;
          if (opt === block.params[f.key]) o.selected = true;
          input.appendChild(o);
        });
      } else {
        input = document.createElement("input");
        input.type = f.type === "number" ? "number" : "text";
        if (f.type === "number") {
          input.step = f.min != null && f.max != null ? String((f.max - f.min) / 100) : "1";
          if (f.min != null) input.min = f.min;
          if (f.max != null) input.max = f.max;
        }
        input.value = block.params[f.key] == null ? "" : block.params[f.key];
      }
      input.addEventListener("change", function () {
        block.params[f.key] = input.type === "number" ? parseFloat(input.value) : input.value;
        if (input.type === "number" && isNaN(block.params[f.key])) block.params[f.key] = f.default;
      });
      row.appendChild(label);
      row.appendChild(input);
      body.appendChild(row);
    });
  }

  window.renderSequence = function () {
    var seq = $("sequence");
    seq.innerHTML = "";
    State.blocks.forEach(function (block, i) {
      var schema = State.schemas[block.action_type] || { icon: "❓", label: block.action_type, params: [] };
      var el = document.createElement("div");
      el.className = "block" + (block.enabled ? "" : " disabled");
      el.setAttribute("data-id", block.block_id);

      var head = document.createElement("div");
      head.className = "block-head";
      var handle = document.createElement("span");
      handle.className = "block-handle"; handle.textContent = "⋮";
      var num = document.createElement("span");
      num.textContent = i + 1;
      var title = document.createElement("span");
      title.className = "block-title";
      title.textContent = schema.icon + " " + schema.label;
      head.appendChild(handle); head.appendChild(num); head.appendChild(title);

      var enable = document.createElement("input");
      enable.type = "checkbox"; enable.checked = block.enabled;
      enable.title = "enabled";
      enable.addEventListener("change", function () {
        block.enabled = enable.checked;
        el.classList.toggle("disabled", !block.enabled);
      });
      var del = document.createElement("button");
      del.textContent = "✕"; del.title = "remove";
      del.addEventListener("click", function () { removeBlock(block.block_id); });
      head.appendChild(enable); head.appendChild(del);
      el.appendChild(head);

      var body = document.createElement("div");
      body.className = "block-body";
      renderParamFields(body, schema, block);
      el.appendChild(body);

      var foot = document.createElement("div");
      foot.className = "block-foot";
      foot.innerHTML = "⏱ Pause after:";
      var delay = document.createElement("input");
      delay.type = "number"; delay.step = "0.1"; delay.min = "0"; delay.max = "60";
      delay.value = block.delay_after;
      delay.addEventListener("change", function () {
        block.delay_after = Math.min(60, Math.max(0, parseFloat(delay.value) || 0));
      });
      foot.appendChild(delay);
      el.appendChild(foot);

      seq.appendChild(el);
    });
    $("drop-hint").style.visibility = State.blocks.length ? "hidden" : "visible";
    updateStepCount();
    if (window.DnD) DnD.initSequence(seq, syncOrderFromDom);
  };

  function syncOrderFromDom() {
    var order = Array.prototype.map.call($("sequence").querySelectorAll(".block"),
      function (el) { return el.getAttribute("data-id"); });
    State.blocks.sort(function (a, b) { return order.indexOf(a.block_id) - order.indexOf(b.block_id); });
    State.blocks.forEach(function (b, i) { b.position = i; });
    renderSequence();
  }

  window.serializeBlocks = function () {
    return State.blocks.map(function (b, i) {
      return { block_id: b.block_id, action_type: b.action_type, params: b.params,
               delay_after: b.delay_after, enabled: b.enabled, position: i };
    });
  };

  window.loadBlocks = function (blocks) {
    State.blocks = (blocks || []).map(function (b, i) {
      return { block_id: b.block_id || uuid(), action_type: b.action_type,
               params: b.params || {}, delay_after: b.delay_after || 0,
               enabled: b.enabled !== false, position: i };
    });
    renderSequence();
  };

  function initPresets() {
    var sel = $("preset-select");
    function refresh(selectedName) {
      callApi("getPresets").then(function (data) {
        var presets = (data && data.presets) || [];
        var current = sel.value;
        sel.innerHTML = "";
        var none = document.createElement("option");
        none.value = ""; none.textContent = "— presets —";
        sel.appendChild(none);
        presets.forEach(function (p) {
          var o = document.createElement("option");
          o.value = p.name; o.textContent = p.name;
          sel.appendChild(o);
        });
        sel.value = selectedName || (presets.some(function (p) { return p.name === current; }) ? current : "");
      });
    }
    refresh();
    sel.addEventListener("change", function () {
      if (sel.value) loadPresetByName(sel.value);
    });
    window.loadPresetByName = function (name) {
      callApi("getPreset", { name: name }).then(function (data) {
        if (data && data.blocks) loadBlocks(data.blocks);
      }).catch(function () {});
    };
    $("btn-save-preset").addEventListener("click", function () { promptSavePreset(); });
    window.promptSavePreset = function () {
      var name = prompt("Preset name:", "Default");
      if (!name) return;
      callApi("savePreset", { name: name, description: "", blocks: serializeBlocks() })
        .then(function () { $("preset-select").value = ""; refresh(name); logLine("ok", "Preset saved: " + name); });
    };
  }

  document.addEventListener("DOMContentLoaded", function () {
    DnD.initSequence($("sequence"), syncOrderFromDom);
    initPresets();
  });
})();
