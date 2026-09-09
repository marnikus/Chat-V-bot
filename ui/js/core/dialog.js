// dialog.js — shared confirm dialog (ES module)
export function confirmDialog(message, title = 'Confirm') {
  return new Promise(resolve => {
    if (typeof window !== 'undefined' && window.confirm) {
      resolve(window.confirm(`${title}\n\n${message}`));
      return;
    }
    resolve(false);
  });
}

export function alertDialog(message, title = 'Info') {
  if (typeof window !== 'undefined' && window.alert) window.alert(`${title}\n\n${message}`);
}

export function promptDialog(message, defaultValue = '') {
  if (typeof window !== 'undefined' && window.prompt) return window.prompt(message, defaultValue);
  return null;
}
