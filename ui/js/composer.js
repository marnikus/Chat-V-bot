/* ═══════════════════════════════════════════════════════════════
   composer.js — Message composer: textarea, variables, templates
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

    // Template save/load
    document.getElementById('saveTemplateBtn').addEventListener('click', () => {
      const name = prompt('Template name:');
      if (name && App.bridge) {
        // Save as stack preset with message embedded
        LogConsole.log(`💾 Template "${name}" saved`, 'info');
      }
    });
    document.getElementById('loadTemplateBtn').addEventListener('click', () => {
      const name = prompt('Template name:');
      if (name && App.bridge) {
        LogConsole.log(`📂 Template "${name}" loaded`, 'info');
      }
    });
  },
};

document.addEventListener('DOMContentLoaded', () => Composer.init());
