/* presets-ui.js — PresetsUI facade (H-B2b JS split, 474→~30)

Parts loaded before this one — see index.html:
  presets-ui-core.js, presets-ui-stack.js, presets-ui-templates.js,
  presets-ui-blocks.js, presets-ui-import.js

Public API unchanged: window.PresetsUI
*/

'use strict';

const PresetsUI = {};

UIHelpers.mergeParts(PresetsUI,
  PresetsUICore, PresetsUIStack, PresetsUITemplates,
  PresetsUIBlocks, PresetsUIImport);

if (typeof window !== 'undefined') window.PresetsUI = PresetsUI;

document.addEventListener('click', (e) => {
  if (!e.target.closest('#presetPicker')) {
    const p1 = document.getElementById('presetPicker');
    if (p1 && !e.target.closest('#loadStackBtn')) p1.classList.add('hidden');
  }
  if (!e.target.closest('#templatePicker')) {
    const p2 = document.getElementById('templatePicker');
    if (p2 && !e.target.closest('#loadTemplateBtn')) p2.classList.add('hidden');
  }
});
