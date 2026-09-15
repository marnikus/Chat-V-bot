/* window-presets.js — WindowPresets facade (H-B2b JS split, 376→~30)

Parts loaded before this one — see index.html:
  window-presets-core.js, window-presets-actions.js, window-presets-preview.js

Public API unchanged: window.WindowPresets
*/

'use strict';

const WindowPresets = {};

UIHelpers.mergeParts(WindowPresets, WindowPresetsCore, WindowPresetsActions, WindowPresetsPreview);

window.WindowPresets = WindowPresets;
