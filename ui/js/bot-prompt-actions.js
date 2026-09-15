/* bot-prompt-actions.js — save/cancel/reset/preview for BotPrompt facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const BotPromptActions = {
  save() {
    if (!this.current || !App.bridge || !App.bridge.bot_save_prompt) return;
    const text = this._els.text ? this._els.text.value : '';
    App.bridge.bot_save_prompt(this.current, text, (ok) => {
      this.setStatus(ok ? 'Saved — it will be used from now on.' : '⚠ Not saved: the template must keep only the {nick}, {conversation} and {last_message} fields.');
    });
  },

  cancel() { this.select(this.current); this.setStatus('Changes discarded.'); },

  reset() {
    if (!this.current || !App.bridge || !App.bridge.bot_reset_prompt) return;
    App.bridge.bot_reset_prompt(this.current, (ok) => { this.setStatus(ok ? 'Back to the shipped template.' : 'Already the shipped template.'); });
  },

  preview() {
    const nick = this.nick || (typeof BotChat !== 'undefined' ? BotChat.nick : '');
    if (!App.bridge || !App.bridge.bot_preview_prompt) return;
    if (!nick) { this.setStatus('⚠ Pick a person in the AI Bot Chat first.'); return; }
    this._previewId = 'prompt' + (++this._seq);
    const scope = (typeof BotChat !== 'undefined' && BotChat.scope) ? BotChat.scope() : 'today';
    App.bridge.bot_preview_prompt(this._previewId, nick, this.current, scope);
  },

  onReply(reqId, json) {
    if (reqId !== this._previewId) return;
    let payload = null; try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload || !this._els.preview) return;
    this._els.preview.textContent = payload.prompt || ''; this._els.preview.classList.remove('hidden'); this.setStatus('This is exactly what would be sent to Grok.');
  },
};

if (typeof window !== 'undefined') window.BotPromptActions = BotPromptActions;
