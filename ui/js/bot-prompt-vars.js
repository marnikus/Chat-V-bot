/* bot-prompt-vars.js — variable library for BotPrompt facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const BotPromptVars = {
  loadVariables() { if (!App.bridge || !App.bridge.bot_get_variables) return; App.bridge.bot_get_variables((json) => this.setVariables(json)); },

  setVariables(json) {
    let list = []; try { list = JSON.parse(json || '[]'); } catch (err) { list = []; }
    this.variables = Array.isArray(list) ? list : []; this._renderVariables();
  },

  _renderVariables() {
    const host = this._els.vars; if (!host) return; host.textContent = '';
    this.variables.forEach((spec) => {
      const chip = document.createElement('button'); chip.type = 'button'; chip.className = 'bot-var'; chip.dataset.token = spec.token;
      const name = document.createElement('span'); name.className = 'bot-var-token'; name.textContent = spec.token;
      const desc = document.createElement('span'); desc.className = 'bot-var-desc'; desc.textContent = spec.description || '';
      chip.appendChild(name); chip.appendChild(desc); chip.title = 'Example → ' + (spec.example || ''); host.appendChild(chip);
    });
  },

  insert(token) {
    const box = this._els.text; if (!box) return;
    const value = String(box.value || ''); const at = typeof box.selectionStart === 'number' ? box.selectionStart : value.length;
    const end = typeof box.selectionEnd === 'number' ? box.selectionEnd : at;
    box.value = value.slice(0, at) + token + value.slice(end);
    const caret = at + token.length; if (typeof box.setSelectionRange === 'function') box.setSelectionRange(caret, caret); if (typeof box.focus === 'function') box.focus();
    this.checkVariables();
  },

  checkVariables() {
    if (!App.bridge || !App.bridge.bot_check_prompt || !this._els.text) return;
    App.bridge.bot_check_prompt(String(this._els.text.value || ''), (json) => this.showWarnings(json));
  },

  showWarnings(json) {
    let report = null; try { report = JSON.parse(json || 'null'); } catch (err) { report = null; }
    const box = this._els.warn; if (!box) return;
    const notes = report ? (report.unknown || []).map((n) => 'unknown variable {' + n + '}').concat((report.malformed || []).map((m) => 'malformed: ' + m)) : [];
    box.textContent = notes.join(' · '); box.classList.toggle('hidden', !notes.length);
  },
};

if (typeof window !== 'undefined') window.BotPromptVars = BotPromptVars;
