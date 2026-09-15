/* labels-edit.js — inline editor for Labels facade (H-B2b JS split)

Rename + recolour inline editor: startEdit, cancelEdit, saveEdit, _editRow.

Design: AREA_H §6.4 — ≤200 LOC.
*/

'use strict';

const LabelsEdit = {
  startEdit(id) {
    const label = this.byId(id);
    if (!label) return;
    this.editing = id;
    this.editName = label.name;
    this.editColor = label.color;
    this.renderActive();
    const input = this._els.active ? this._els.active.querySelector('.label-edit-input') : null;
    if (input) {
      if (typeof input.focus === 'function') input.focus();
      if (typeof input.select === 'function') input.select();
    }
  },

  cancelEdit() {
    this.editing = '';
    this.renderActive();
  },

  saveEdit() {
    const label = this.byId(this.editing);
    if (!label) { this.cancelEdit(); return; }
    const name = String(this.editName || '').trim();
    if (!name) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ A label needs a name', 'warn');
      return;
    }
    const color = String(this.editColor || '');
    const bridge = this._bridge('label_update');
    if (!bridge) { this.cancelEdit(); return; }
    const nameChanged = name !== label.name ? name : '';
    const colorChanged = color && color !== label.color ? color : '';
    if (!nameChanged && !colorChanged) { this.cancelEdit(); return; }
    bridge.label_update(label.id, nameChanged, colorChanged);
    this.cancelEdit();
  },

  _editRow(label) {
    const row = document.createElement('span');
    row.className = 'label-edit-row';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'label-edit-input';
    input.value = this.editName || label.name;
    input.spellcheck = false;
    input.maxLength = 40;
    input.title = 'Rename this label — Enter saves, Escape cancels';
    input.addEventListener('input', () => { this.editName = input.value; });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        if (e.preventDefault) e.preventDefault();
        this.saveEdit();
      } else if (e.key === 'Escape') {
        if (e.preventDefault) e.preventDefault();
        this.cancelEdit();
      }
    });
    row.appendChild(input);
    const colorBtn = document.createElement('button');
    colorBtn.type = 'button';
    colorBtn.className = 'label-edit-color';
    colorBtn.style.background = this.editColor || label.color;
    colorBtn.title = 'Change the label colour';
    colorBtn.addEventListener('click', () => {
      ColorPicker.open({
        anchor: colorBtn,
        color: this.editColor || label.color,
        title: 'Pick Color — ' + label.name,
        onPick: (hex) => {
          this.editColor = hex;
          colorBtn.style.background = hex;
        },
      });
    });
    row.appendChild(colorBtn);
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'btn-small btn-primary label-edit-save';
    save.textContent = 'Save';
    save.title = 'Save the new name and colour';
    save.addEventListener('click', () => this.saveEdit());
    row.appendChild(save);
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn-small label-edit-cancel';
    cancel.textContent = 'Cancel';
    cancel.title = 'Discard the changes';
    cancel.addEventListener('click', () => this.cancelEdit());
    row.appendChild(cancel);
    return row;
  },
};

if (typeof window !== 'undefined') window.LabelsEdit = LabelsEdit;
