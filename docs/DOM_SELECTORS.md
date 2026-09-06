# DOM Selector Reference — Verified from Saved HTML

**Source files:**
- `Вирт чат.html` — Main chat (user list) view
- `Вирт чат privat.html` — Private chat (1-on-1) view

All selectors below are **extracted from actual HTML** in this repository.
The target site is an Angular 22 app using Angular Material + CDK.

---

## User List Sidebar

The user list uses Angular CDK Virtual Scroll (`cdk-virtual-scroll-viewport`).
DOM nodes are **recycled** as the user scrolls — only visible items exist in DOM.

### Hierarchy

```
users-list
  └── cdk-virtual-scroll-viewport.users-list-viewport
        └── .cdk-virtual-scroll-content-wrapper  ← has translateY offset
              └── container-item
                    └── user-item
                          └── .user-container
                                ├── avatar-item
                                │     └── .avatar-wrapper [classes]
                                │           ├── mat-icon.avatar-icon (user SVG)
                                │           └── .badge [classes]
                                │                 └── mat-icon (badge SVG)
                                ├── .text-stack
                                │     ├── .primary-text-line
                                │     │     └── .primary-text  ← NICKNAME
                                │     └── .secondary-text
                                └── button.more-button
```

### Avatar Classes (on `.avatar-wrapper`)

| Class | Meaning | CSS Indicator |
|-------|---------|---------------|
| `female-avatar` | User is female | Pink border (#ad1457) |
| `male-avatar` | User is male | Blue border (#1976d2) |
| `trans-avatar` | User is trans | Purple border (#9c27b0) |
| `guest-avatar` | Guest (not registered) | Grey border (#9e9e9e) |
| `invisible-avatar` | Invisible status | Opacity 0.5 |

**Note:** `guest-avatar` can co-occur with `male-avatar` or `female-avatar`.
Example from HTML: `class="avatar-wrapper female-avatar guest-avatar"`

### Badge Classes (on `.badge`)

| Class | Meaning | Background Color |
|-------|---------|-----------------|
| `registered-badge` | Registered user | Green (#85d315) |
| `anonymous-badge` | Anonymous/guest | Grey (#9e9e9e) |
| `premium-badge` | Premium user | Dark + gold glow |

### Extracting User Data (JavaScript for CDP)

```javascript
// Run via Runtime.evaluate in CDP
(function() {
    const items = document.querySelectorAll('user-item');
    const users = [];
    items.forEach(item => {
        const wrapper = item.querySelector('.avatar-wrapper');
        const badge = item.querySelector('.badge');
        const nickEl = item.querySelector('.primary-text');
        
        if (!wrapper || !nickEl) return;
        
        const classes = wrapper.classList;
        users.push({
            nick: nickEl.textContent.trim(),
            female: classes.contains('female-avatar'),
            male: classes.contains('male-avatar'),
            guest: classes.contains('guest-avatar'),
            registered: badge ? badge.classList.contains('registered-badge') : false,
            anonymous: badge ? badge.classList.contains('anonymous-badge') : false
        });
    });
    return JSON.stringify(users);
})();
```

---

## Chat Area

### Message Structure

```
app-messages > .messages-root
  └── div
        └── .message-container [class: general-background | my-message-background]
              ├── mat-menu
              └── .message-content
                    ├── p.message
                    │     ├── span.additional-icon
                    │     │     ├── mat-icon[data-mat-icon-name='male'|'female']  ← gender
                    │     │     └── mat-icon[data-mat-icon-name='anonymous'|'registered']  ← badge
                    │     ├── span.from  ← SENDER NAME
                    │     ├── " ▸ "
                    │     ├── span.message  ← MESSAGE TEXT
                    │     └── app-chat-image (optional, for images)
                    └── .message-status
                          ├── span.sent-time  ← TIME
                          └── span.state-icon [class: sent|sending|error]
```

### Message Input Form

```
app-message-form
  └── form
        └── mat-form-field
              └── .mat-mdc-text-field-wrapper
                    └── .mat-mdc-form-field-flex
                          └── .mat-mdc-form-field-infix
                                └── textarea#mat-input-1
                                      placeholder="Сообщение"
                                      maxlength="1000"
                                      required
                          └── .mat-mdc-form-field-icon-suffix
                                ├── button[type='submit']  ← SEND
                                │     └── mat-icon: "send"
                                ├── button  ← IMAGE
                                │     └── mat-icon: "image"
                                └── button  ← EMOJI
                                      └── mat-icon: "insert_emoticon"
```

### Hidden File Input (for image upload)

```html
<input id="file" type="file" style="display: none;" accept="image/*">
```

This is a **global** input element, not inside the message form.
Located directly under the `footer` element.

---

## Tab Navigation

### Tab Structure

```
app-tab-scroller > .tab-scroller-container
  ├── button.indicator-zone.left  (scroll left)
  ├── .scroll-viewport (cdk-scrollable)
  │     └── .tabs-list (cdk-drop-list)
  │           └── .tab-item [role="tab"] [class: active?]
  │                 ├── mat-icon.chat-type-icon  (room SVG or user SVG)
  │                 ├── p.chat-title
  │                 │     ├── span.unread  (optional, unread count)
  │                 │     └── text  ← TAB NAME
  │                 └── button.tab-close-button  (optional, for private chats)
  │                       └── mat-icon.tab-close-icon: "close"
  └── button.indicator-zone.right  (scroll right)
```

### Tab Types

| Icon SVG Name | Meaning | Example |
|---------------|---------|---------|
| `data-mat-icon-name='room'` | Main room tab | "Гостиная" |
| `data-mat-icon-name='user'` | Private chat tab | Username |

### Finding Main Room Tab

```javascript
// The main room tab has a "room" icon, private chats have "user" icon
const tabs = document.querySelectorAll('.tab-item');
let mainTab = null;
tabs.forEach(tab => {
    const icon = tab.querySelector('mat-icon.chat-type-icon');
    if (icon && icon.getAttribute('data-mat-icon-name') === 'room') {
        mainTab = tab;
    }
});
return mainTab;
```

---

## Search Input

```html
<input matinput="" maxlength="20" class="mat-mdc-input-element ..."
       id="mat-input-9" aria-invalid="false" aria-required="false">
```

Label: "Поиск" (Search)  
Located in: `.search-field` > `mat-form-field`

---

## Virtual Scroll Mechanics

### Key Elements

| Element | Selector | Purpose |
|---------|----------|---------|
| Viewport | `cdk-virtual-scroll-viewport.users-list-viewport` | Scrollable container |
| Content | `.cdk-virtual-scroll-content-wrapper` | Absolutely positioned, translateY offset |
| Spacer | `.cdk-virtual-scroll-spacer` | Total list height indicator |
| Container items | `container-item` | Each visible item wrapper |

### Scroll Detection

```javascript
// Check current scroll position
const viewport = document.querySelector(
    'cdk-virtual-scroll-viewport.users-list-viewport'
);
const scrollTop = viewport.scrollTop;
const scrollHeight = viewport.scrollHeight;
const clientHeight = viewport.clientHeight;
const atBottom = (scrollTop + clientHeight) >= (scrollHeight - 10);
```

### Spacer Height (indicates total list size)

From main HTML: `style="height: 39139.3px"` — this represents the full
virtual list height. Each item is approximately 40px tall, suggesting ~978
total users in that session.

---

## CSS Class Quick Reference

### Avatar Color Scheme (from CSS)

| Gender | Background | Border |
|--------|-----------|--------|
| Male | `#1976d214` | `rgba(25,118,210,.5)` |
| Female | `#ad145714` | `rgba(173,20,87,.5)` |
| Trans | `#9c27b014` | `rgba(156,39,176,.5)` |
| Guest (no gender) | `#9e9e9e0f` | `rgba(158,158,158,.4)` |

### Badge Color Scheme

| Badge | Background | Text |
|-------|-----------|------|
| Registered | `#85d315` | White |
| Anonymous | `#9e9e9e` | White |
| Premium | `#1a1a1a` | Gold `#ffb300` |

---

*This document is auto-verified against the saved HTML files in this repository.*

---

## Message Archive / Passive Collector (added 2026-09-06)

The selectors the in-page agent (`backend/js/chat_agent.js`) depends on. They
were verified against the saved pages `Вирт чат.html` (main room, the only
page that contains message images) and `Вирт чат privat.html` (private chat).

### One message

```
div.message-container.my-message-background   → sent BY me      (dir = out)
div.message-container.general-background      → received        (dir = in)
  p.message
    span.from                                 → author nick
    " ▸ "                                     → separator text node
    span.message                              → the text, OR
    app-chat-image img[alt="chat image"]      → an image / GIF (src = url)
  span.sent-time                              → "HH:MM" only — no date
```

There are **no date separators** in the DOM, so absolute days are inferred by
the parser (see doc A §5) and stored per message as `day`.

### Which conversation is on screen

```
.tab-item.active                              → the active tab (class TOKEN
                                                match: the live attribute is
                                                "cdk-drag mat-ripple tab-item …")
  mat-icon.chat-type-icon[data-mat-icon-name="user"]  → private chat
  mat-icon.chat-type-icon[data-mat-icon-name="room"]  → the main room
  p.chat-title                                → the partner's nick
.users-counter                                → participant count (2 = private)
.primary-text.bold                            → my own row in the user list
```

### Agent contract

`window.__cvbAgent` (VERSION 3) exposes `state()`, `slice(a, b)` and
`drain()`; it buffers MutationObserver additions synchronously (cap 500,
`dropped++` beyond that) and notifies Python through the `__cvbPush` binding,
debounced by 120 ms. `state()` returns head/tail fingerprints only — never
the whole conversation — which is what keeps a steady-state poll free of any
node serialisation.

