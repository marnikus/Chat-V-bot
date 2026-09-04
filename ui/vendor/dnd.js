/*!
 * dnd.js — minimal dependency-free drag & drop for the sequence builder.
 * Supports: palette -> builder (clone), builder -> builder (reorder),
 * drop-at-position insertion. Same mental model as SortableJS for our use.
 */
(function () {
  "use strict";

  function insertIndex(container, y) {
    var items = Array.prototype.slice.call(container.children).filter(function (el) {
      return el.classList && el.classList.contains("block");
    });
    for (var i = 0; i < items.length; i++) {
      var box = items[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) return i;
    }
    return items.length;
  }

  function makeDraggable(el, type, payload) {
    el.setAttribute("draggable", "true");
    el.addEventListener("dragstart", function (ev) {
      ev.dataTransfer.setData("text/cf-type", type);
      ev.dataTransfer.setData("text/cf-payload", payload);
      ev.dataTransfer.effectAllowed = "copyMove";
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", function () { el.classList.remove("dragging"); });
  }

  window.DnD = {
    initPalette: function (paletteEl, seqEl, onAdd) {
      function bindItem(item) {
        makeDraggable(item, "new-block", item.getAttribute("data-action"));
      }
      Array.prototype.forEach.call(paletteEl.querySelectorAll(".palette-item"), bindItem);
      paletteEl._bindItem = bindItem; // for items added later
      seqEl.addEventListener("dragover", function (ev) {
        if (ev.dataTransfer.types.indexOf("text/cf-type") === -1) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
      });
      seqEl.addEventListener("drop", function (ev) {
        ev.preventDefault();
        var type = ev.dataTransfer.getData("text/cf-type");
        if (type !== "new-block") return;
        var index = insertIndex(seqEl, ev.clientY);
        onAdd(ev.dataTransfer.getData("text/cf-payload"), index);
      });
    },

    initSequence: function (seqEl, onReorder) {
      function makeBlockDraggable(blockEl) {
        var handle = blockEl.querySelector(".block-handle");
        if (!handle || handle._bound) return;
        handle._bound = true;
        handle.addEventListener("mousedown", function () {
          blockEl.setAttribute("draggable", "true");
        });
        blockEl.addEventListener("dragstart", function (ev) {
          blockEl.setAttribute("draggable", "false"); // re-enabled on next mousedown
          ev.dataTransfer.setData("text/cf-type", "reorder");
          blockEl.classList.add("dragging");
        });
        blockEl.addEventListener("dragend", function () {
          blockEl.classList.remove("dragging");
          blockEl.setAttribute("draggable", "false");
          onReorder();
        });
      }
      seqEl._makeBlockDraggable = makeBlockDraggable;
      Array.prototype.forEach.call(seqEl.querySelectorAll(".block"), makeBlockDraggable);
      seqEl.addEventListener("dragover", function (ev) {
        if (ev.dataTransfer.types.indexOf("text/cf-type") === -1) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
      });
    }
  };
})();
