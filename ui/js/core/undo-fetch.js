// undo-fetch.js — shared undo history fetch + bridge sync
import { bridgeReady } from './bridge-ready.js';

export function fetchUndo() {
  return new Promise(resolve => {
    bridgeReady(bridge => {
      try {
        const raw = bridge.get_undo_history ? bridge.get_undo_history() : bridge.get_stack_history();
        resolve(JSON.parse(raw || '{"history":[],"index":-1}'));
      } catch (e) { resolve({ history: [], index: -1 }); }
    });
  });
}

export function pushUndo(kind, value) {
  return new Promise(resolve => {
    bridgeReady(bridge => {
      try {
        if (bridge.push_global_history) {
          resolve(bridge.push_global_history(kind, JSON.stringify(value)));
        } else if (bridge.push_stack_history) {
          resolve(bridge.push_stack_history(JSON.stringify(value)));
        } else resolve(false);
      } catch (e) { resolve(false); }
    });
  });
}
