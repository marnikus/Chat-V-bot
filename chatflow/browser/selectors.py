"""Verified DOM selectors for ru.virt-chat.com.

Every constant below was extracted from the saved snapshots in this repo
(see docs/ARCHITECTURE.md §1.6). Keep this module Playwright-free so it can
be imported by tests and the UI.

Resilience rules: no _ngcontent/_nghost attributes, no mat-input-N ids,
always trim() text (real trailing spaces observed), re-query before acting.
"""
from __future__ import annotations

# --- user list (CDK virtual scroll) ---------------------------------------
VIEWPORT = 'cdk-virtual-scroll-viewport.users-list-viewport'
ROW = 'cdk-virtual-scroll-viewport.users-list-viewport .cdk-virtual-scroll-content-wrapper > container-item'
USER_ROW = ROW + ':has(user-item)'
HEADER_ROW = ROW + ':has(users-header-item)'
NICK = 'user-item .primary-text'
AVATAR = 'user-item .avatar-wrapper'
FEMALE = 'user-item .avatar-wrapper.female-avatar'
MALE = 'user-item .avatar-wrapper.male-avatar'
REGISTERED = 'user-item .avatar-wrapper .registered-badge'
ANON = 'user-item .avatar-wrapper .anonymous-badge'
SEARCH_INPUT = 'users-list .search-field input[matinput]'

# --- tab scroller -----------------------------------------------------------
TAB_LIST = '[role=tablist].tabs-list'
TAB = '[role=tablist].tabs-list div[role=tab]'
TAB_ACTIVE = '.tab-item.active'
TAB_TITLE = 'div[role=tab] p.chat-title'
TAB_CLOSE = 'div[role=tab] button.tab-close-button'
TAB_TYPE_ICON = 'div[role=tab] mat-icon.chat-type-icon'

# --- message form -----------------------------------------------------------
TEXTAREA = 'app-message-form textarea[matinput]'
SEND_BTN = 'app-message-form button[type=submit]'
IMAGE_BTN = 'app-message-form button:has(mat-icon)'
FILE_INPUT = 'input#file[type=file]'
CHAR_COUNTER = 'app-message-form mat-hint-end'
APP_ROOT = 'app-chat'


def tab_selector(index: int) -> str:
    """1-based index of a tab inside the tab list."""
    return f"{TAB}:nth-child({index})"


def tab_title_selector(index: int) -> str:
    return f"{TAB}:nth-child({index}) {TAB_TITLE}"


def row_selector(index: int) -> str:
    """1-based index of a rendered row inside the scroll content wrapper."""
    return f"{ROW}:nth-child({index})"


def nick_selector(index: int) -> str:
    return f"{ROW}:nth-child({index}) {NICK}"


# --- JS helpers (pass to Page.evaluate) ------------------------------------
# Returns [{nickname, classes[]}] for every rendered user row (header rows
# are skipped because they have no <user-item>).
ROWS_JS = r"""
() => {
  const rows = document.querySelectorAll("""" + ROW + r"""");
  const out = [];
  for (const row of rows) {
    const ui = row.querySelector("user-item");
    if (!ui) continue;
    const n = ui.querySelector(".primary-text");
    if (!n) continue;
    const a = ui.querySelector(".avatar-wrapper");
    const cls = a ? a.className.split(/\s+/).filter(Boolean) : [];
    ui.querySelectorAll(".badge").forEach(b =>
      cls.push(...b.className.split(/\s+/).filter(Boolean)));
    out.push({nickname: (n.textContent || "").trim(), classes: cls});
  }
  return out;
}
"""

# Cleaned title of one tab: removes the unread-count span, trims.
TAB_TITLE_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return "";
  const c = el.cloneNode(true);
  const u = c.querySelector("span.unread");
  if (u) u.remove();
  return (c.textContent || "").trim();
}
"""

# Plain trimmed text of an element.
TEXT_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  return el ? (el.textContent || "").trim() : "";
}
"""

# Clear the composer textarea (Angular needs an input event), then focus.
CLEAR_TEXTAREA_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  el.value = "";
  el.dispatchEvent(new Event("input", {bubbles: true}));
  el.focus();
  return true;
}
"""
