// ui-helpers.js — shared chip / pill / sort helpers

export function chipRender(container, items, { onRemove, onClick, labelKey } = {}) {
  if (!container) return;
  container.innerHTML = '';
  (items || []).forEach(item => {
    const label = labelKey ? (item[labelKey] ?? item) : item;
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = label;
    if (onClick) chip.addEventListener('click', () => onClick(item));
    if (onRemove) {
      const x = document.createElement('button');
      x.className = 'chip-remove';
      x.textContent = '×';
      x.addEventListener('click', e => { e.stopPropagation(); onRemove(item); });
      chip.appendChild(x);
    }
    container.appendChild(chip);
  });
}

export function pillRender(container, items, opts = {}) {
  // Alias for chipRender with pill styling
  chipRender(container, items, opts);
}

export function sortArrows(th, order, key) {
  th.querySelectorAll('.sort-arrow').forEach(el => el.remove());
  const arrow = document.createElement('span');
  arrow.className = 'sort-arrow';
  arrow.textContent = order === 'asc' ? ' ▲' : ' ▼';
  const active = th.dataset.sortKey === key;
  arrow.style.opacity = active ? '1' : '0.3';
  th.appendChild(arrow);
}

export function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
