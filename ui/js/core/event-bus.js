// event-bus.js — tiny JS event bus mirroring Python core/events.py
export class EventBus {
  constructor() { this.handlers = new Map(); }
  on(event, fn) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    const lst = this.handlers.get(event);
    if (!lst.includes(fn)) lst.push(fn);
  }
  off(event, fn) {
    if (!fn) { this.handlers.delete(event); return; }
    const lst = this.handlers.get(event) || [];
    const i = lst.indexOf(fn);
    if (i !== -1) lst.splice(i, 1);
    if (!lst.length) this.handlers.delete(event);
  }
  emit(event, payload) {
    const lst = (this.handlers.get(event) || []).slice();
    lst.forEach(fn => { try { fn(payload); } catch (e) { console.error(e); } });
  }
  clear() { this.handlers.clear(); }
}
export const bus = new EventBus();
