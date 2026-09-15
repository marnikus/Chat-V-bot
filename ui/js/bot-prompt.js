/* bot-prompt.js — BotPrompt facade (H-B2b JS split, 355→~20)

Parts loaded before this one — see index.html:
  bot-prompt-core.js, bot-prompt-vars.js, bot-prompt-presets.js, bot-prompt-actions.js

Public API unchanged: window.BotPrompt
*/

'use strict';

const BotPrompt = {};

UIHelpers.mergeParts(BotPrompt, BotPromptCore, BotPromptVars, BotPromptPresets, BotPromptActions);

if (typeof window !== 'undefined') window.BotPrompt = BotPrompt;
if (typeof module === 'object' && module.exports) module.exports = BotPrompt;
