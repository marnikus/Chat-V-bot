/* bot-settings.js — BotSettings facade (H-B2b JS split, 395→~30)

Parts loaded before this one — see index.html:
  bot-settings-core.js, bot-settings-actions.js

Public API unchanged: window.BotSettings
*/

'use strict';

const BotSettings = {};

UIHelpers.mergeParts(BotSettings, BotSettingsCore, BotSettingsActions);

if (typeof document !== 'undefined' && document.addEventListener) {
  let insidePopup = false;
  document.addEventListener('click', (event) => {
    insidePopup = !!(event.target && event.target.closest && event.target.closest('#botSettingsBackdrop'));
  }, true);
  document.addEventListener('click', () => {
    if (!BotSettings.isOpen()) return;
    if (!insidePopup) BotSettings.close();
  });
}

if (typeof window !== 'undefined') window.BotSettings = BotSettings;
