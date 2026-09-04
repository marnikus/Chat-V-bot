/* palette.js — action palette (draggable source). */
(function () {
  "use strict";
  var PALETTE_ORDER = ["go_main_tab", "scroll_parse", "pick_target", "click_user",
    "type_message", "attach_image", "send_message", "close_tab",
    "wait", "loop", "condition"];

  function $(id) { return document.getElementById(id); }

  window.initPalette = function () {
    var palette = $("palette");
    var seq = $("sequence");
    callApi("getBlockSchemas").then(function (data) {
      State.schemas = data || {};
      PALETTE_ORDER.forEach(function (type) {
        var s = State.schemas[type];
        if (!s) return;
        var item = document.createElement("div");
        item.className = "palette-item";
        item.setAttribute("data-action", type);
        item.innerHTML = "<span>" + s.icon + "</span><span>" + s.label + "</span>";
        palette.appendChild(item);
      });
      DnD.initPalette(palette, seq, function (actionType, index) {
        addBlock(actionType, index);
      });
    });
  };
})();
