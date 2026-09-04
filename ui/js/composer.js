/* ═══════════════════════════════════════════════════════════════
   composer.js — Message composer: textarea, variables, templates.
   Template presets are persisted through the backend and rendered as
   chips / a picker list (BUG #1 — same store pattern as stack presets).
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const Composer = {
  init() {
    const textarea = document.getElementById('messageInput');
    const charCount = document.getElementById('charCount');
    const varMenu = document.getElementById('varMenu');
    const insertBtn = document.getElementById('insertVarBtn');

    // Character counter
    textarea.addEventListener('input', () => {
      const len = textarea.value.length;
      charCount.textContent = `${len} / 1000`;
      charCount.className = len > 950 ? 'at-limit' : len > 800 ? 'near-limit' : '';
      if (App.bridge) App.bridge.save_message(textarea.value);
    });

    // Variable insert menu
    insertBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      varMenu.classList.toggle('hidden');
      const rect = insertBtn.getBoundingClientRect();
      varMenu.style.position = 'fixed';
      varMenu.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
      varMenu.style.left = rect.left + 'px';
    });

    varMenu.querySelectorAll('.var-item').forEach(el => {
      el.addEventListener('click', () => {
        const v = el.dataset.var;
        const start = textarea.selectionStart;
        textarea.value = textarea.value.substring(0, start) + v + textarea.value.substring(textarea.selectionEnd);
        textarea.selectionStart = textarea.selectionEnd = start + v.length;
        textarea.focus();
        varMenu.classList.add('hidden');
        textarea.dispatchEvent(new Event('input'));
      });
    });

    document.addEventListener('click', () => varMenu.classList.add('hidden'));

    // Template save (real persistence through the backend)
    document.getElementById('saveTemplateBtn').addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      if (!textarea.value.trim()) {
        LogConsole.log('⚠ Composer is empty — type a message first', 'warn');
        return;
      }
      PresetsUI.promptName('Save message template', 'e.g. Greeting RU',
        'Save', (name) => {
          App.bridge.save_template_preset(name, textarea.value);
        });
    });

    // Template load — opens the picker list of saved templates
    document.getElementById('loadTemplateBtn').addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      App.bridge.list_template_presets((json) => {
        PresetsUI.setTemplatePresets(json);
        PresetsUI.toggleTemplatePicker(document.getElementById('loadTemplateBtn'));
      });
    });
  },

  setMessage(text) {
    const textarea = document.getElementById('messageInput');
    if (!textarea) return;
    textarea.value = text || '';
    textarea.dispatchEvent(new Event('input'));
  },
};

document.addEventListener('DOMContentLoaded', () => Composer.init());
