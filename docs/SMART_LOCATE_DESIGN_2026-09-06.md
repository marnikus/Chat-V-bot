# Smart Locate — finding any user in the virtualized list without blind scrolling

Date: 2026-09-06 · Status: design (research done; no code changed)

## 0. The question

> Returning to the chat resets the lazy list, and I can't get the item
> easily to select and click it again. I want to "load it full", or save the
> item as an object and click it virtually with scrolling + searching.
> Is there something better than scroll-and-find?

Short answers (details below):

1. **You cannot "load the list full" — and you don't need to.** The site
   (Angular 22 + Material + CDK) uses **virtual scrolling**: the DOM only
   ever contains the ~25 rows around the viewport, recycled as you scroll.
   Even after scrolling to the very bottom, only ~25 rows exist in the DOM.
   The *complete* catalog lives in the Angular component's array, which is
   not in the DOM.
2. **Saving the DOM element ("item as object") does not work.** Virtual
   scroll **recycles** nodes — the element you saved gets repurposed for
   another user the moment it leaves the viewport. What you *can* save is
   the **identity** (nick + avatar/badge fingerprint, and the internal id if
   we capture the API payload once). Clicking later = re-materialize the row
   (bring it into the rendered window) and do a **real UI click** on it.
3. **Yes, there is something far better than scroll-and-find.** Three cheap,
   verifiable tricks exist on this exact page:
   the **Поиск search box** built into the user list, the **spacer height**
   (= total list height, always present), and **direct scrollTop jumps**
   (CDK renders on demand — you do not need wheel events). Combined they can
   locate a specific nick in **1 action or ~10 jumps** instead of up to
   ~1000 wheel-scroll steps.

---

## 1. What the page actually is (verified)

Source: the saved authenticated sessions in the repo — `Вирт чат.html`
(main chat) and `Вирт чат privat.html` (private chat) — plus
`docs/DOM_SELECTORS.md`.

### 1.1 Virtual-scroll facts (evidence in `Вирт чат.html`)

| Fact | Evidence |
|---|---|
| Users list = CDK virtual scroll | `<cdk-virtual-scroll-viewport autosize class="...users-list-viewport cdk-virtual-scroll-orientation-vertical">` |
| Only the visible window is in the DOM | 25 `<user-item>` / 25 `.primary-text` nodes present |
| Total list size is **always** in the DOM | `<div class="cdk-virtual-scroll-spacer" style="height: 39139.3px;">` |
| Rows ≈ 40 px tall | `container-item > div { min-height: 40px }` + 1px `mat-divider` |
| ~978 users that session | 39139.3 px ÷ 40 px |
| Current render offset is readable | `.cdk-virtual-scroll-content-wrapper { transform: translateY(12144.2px) }` |
| Row DOM (given by user) | `container-item > div[min-height:40px] > user-item > .user-container > .text-stack > .primary-text-line > span.primary-text` ← nick; sibling `button.more-button`; trailing `mat-divider` |
| Nick + avatar/badge all in one snapshot | see extract JS in `backend/scroll_parser.py` L26–62 |
| A **Поиск (Search)** box lives **in the users list** | `<users-list>…<div class="search-field">…<mat-label>Поиск</mat-label>…<input matinput maxlength="20" id="mat-input-9">` — right above the viewport |
| Search untouched in the snapshot | input `ng-pristine`, empty |
| Visible rows were all around "L…" | `LadyToi, Lamm, lavalava, Le1t, Lena1990, Li69, Lily31, …` — consistent with an **A–Z (case-insensitive) sorted list** and scroll at ≈ index 300 of ~978 |
| Private chats are tabs | main room tab icon `room` ("Гостиная"), private tabs icon `user`, title = nick, each with `button.tab-close-button` |

### 1.2 Why "returning to chat resets the list" hurts

When you go back to the Гостиная tab, the users-list component re-renders /
its scroll window resets. Only ~25 rows exist in the DOM **around the
current scrollTop**. A person you chatted with earlier sits somewhere among
~978 rows; unless their index is inside that 25-row window, **there is no
DOM node for them at all** — nothing to find, highlight, or click until the
viewport is moved to their index.

### 1.3 How the bot scrolls today (evidence in `backend/scroll_parser.py`)

* `_do_scroll()` (L207) = **one physical mouse-wheel event** of
  `scroll_delta_y` px at the viewport centre.
* After every wheel step, `_settle()` (L223) polls up to
  `load_timeout_ms` (2500 ms) for new nicks / scroll stability, then a
  `scroll_pause_ms` (default 800 ms) sleeps.
* To traverse the whole 39 000 px list the seek mode issues
  `39 000 ÷ scroll_delta_y` wheel steps — with the default 300 px step that
  is **~130 steps, each ≥0.8 s**, worst case ~2 min *per person*, and the
  target may be at the very bottom.

Wheel events are also the wrong primitive: the browser applies momentum /
coalescing, so each step is non-deterministic, and CDK needs the scroll
event to render the new window — which we then have to wait for blindly.

---

## 2. The three building blocks of the better solution

### B1 — Direct `scrollTop` jumps (replaces wheel steps)

CDK renders on demand from its array: set the viewport's `scrollTop` to any
value and (after Angular renders) the correct window of rows appears. No
wheel, no momentum, deterministic. A jump is one CDP `Runtime.evaluate`:

```javascript
(() => {
  const vp = document.querySelector('cdk-virtual-scroll-viewport.users-list-viewport');
  if (!vp) return JSON.stringify({ok:false});
  vp.scrollTop = <target>;            // direct assignment fires the scroll event
  vp.dispatchEvent(new Event('scroll')); // belt & braces for CDK
  return JSON.stringify({ok:true});
})()
```

The **spacer height** (B2) gives us `<scrollHeight>` for free, so any
*fraction* of the list is reachable in one jump: `target = fraction * (spacer)`,
then a `_settle()`-style wait only until the rendered nick at that offset
changes (fast, because render is local — no network round-trip per window,
unlike the lazy *new-people* loads the collect mode waits for).

> Safety: if a direct jump ever fails to move CDK (defensive), fall back to
> one wheel step. This must be verified on the live page once (implementation
> step), but CDK's own `scrollToIndex` does exactly this internally.

### B2 — Total count / geometry, always available

`spacerHeight` (= `viewport.scrollHeight`) is in the DOM at all times; row
height is measurable from any rendered `container-item`. That yields:

* total row count `N = spacerHeight / rowHeight` **without scrolling**;
* index↔offset math for fine positioning:
  `scrollTop(index) ≈ index × rowHeight − clientHeight/2`.

We do not need the site's internal API for geometry-based locating.

### B3 — The Поиск search box (the "search manually" you mentioned, automated)

The `users-list` component carries its own search input (`.search-field
input[matinput]`, maxlength 20 ≈ nick length). Typing there almost certainly
filters the list's data array client-side, so the matching row(s) render at
the top of the virtual viewport — **one keystroke-set + click**.

Angular inputs need a native setter + `input` event so `ngModel` updates:

```javascript
(() => {
  const el = document.querySelector('.search-field input[matinput]');
  if (!el) return JSON.stringify({ok:false});
  el.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, <nick>);                    // bypass Angular's value guard
  el.dispatchEvent(new Event('input', {bubbles:true}));
  return JSON.stringify({ok:true});
})()
```

*(Reuse the proven value-injection approach from `backend/message_injector.py`
— the same "native setter + event" trick the paste-fallback work validated.)*

Unknown to verify on the live page (cannot be answered from static HTML):
whether the filter is substring/prefix and whether it is debounced or
server-side. The design below therefore **self-verifies** before trusting it.

---

## 3. Design: `PageLocator` — a "find this nick's row" service

### 3.1 One shared service

New module `backend/page_locator.py` + a thin UI setting. Both existing
code paths that hunt for a nick use it:

* **Scroll & Parse → scroll-only seek** (`scroll_parser.collect`, seek mode):
  today it scrolls blindly until *any* target appears. It will instead ask
  the locator for the *specific* nick.
* **Click User** (used by the `respect_order` queue flow and `{{nick}}`
  loops): before `find_and_click_exact` gives up, it asks the locator to
  bring the nick's row on screen, then clicks it normally (highlight +
  real UI click — unchanged, tab-verification included).

### 3.2 Locate ladder (each rung is cheap and **self-verifying**)

```
locate(nick):
  1. SNAPSHOT     — read current rendered rows (existing extract JS).
                    nick present?        → done (row already on screen).
  2. SEARCH       — ONLY if search box verified usable this session:
                    type nick into Поиск, wait ~300 ms, snapshot.
                    nick present?        → done (clear the box afterwards).
                    box unusable / no hit → clear box, continue.
  3. SORT CHECK   — cheap monotonicity probe (see below). Sorted A–Z?
     │  yes → 4a. BINARY JUMP: probe nick at scrollTop 25%/50%/75%…
     │             ≤ ⌈log2 N⌉ ≈ 10 jumps; then fine-nudge ±1 row.
     │  no  → 4b. STRIDE SCAN: jump by (clientHeight − rowHeight) windows,
     │             snapshot each — N/25 ≈ 40 renders worst case for 978 rows
     │             (still ~3× fewer steps than wheel scrolling, each step
     │             milliseconds instead of ~1 s, because no wheel+settle).
  5. LEGACY       — last resort: today's incremental wheel seek (unchanged).
```

**Sort check (rung 3)** — cheap and decisive: jump to 4 fractions (0.08,
0.33, 0.66, 0.92), read the first rendered nick at each, and require the
casefolded nicks to be strictly increasing. The saved HTML already suggests
the list is A–Z, but the check re-validates it live every session and only
*then* enables binary jumping. (If the site ever gains server-side search or
a different sort, the ladder degrades gracefully instead of misbehaving.)

**Probe function (rung 4a)** — jump to a fraction, read the **first
rendered `.primary-text`** (CDK renders a small buffer above `scrollTop`, so
the first row is the reliable anchor), return `casefold(nick)`.

### 3.3 Verification hooks (run once per session, cheap)

* Search-box usability: type a nick already visible in the current snapshot
  and confirm the list narrows to it; then clear.
* After *any* jump: snapshot until the anchor nick changes or 500 ms passes.
* Re-verify the target is still Status-New / un-messaged *before* clicking,
  using the same person-filter checks as Scroll & Parse today (so a person
  who just got messaged elsewhere is never clicked twice).

### 3.4 What we deliberately do **not** do

* **Do not** try to keep a JS reference to the DOM node across re-renders
  (it is recycled — clicking it later clicks a *different* user, a real
  mis-click risk). Save the **locator**: `{nick, casefold, avatar/badge
  fingerprint}` (+ optional API id captured from the network tab later).
* **Do not** fabricate clicks on detached nodes. The chat only opens the
  private tab through the app's real `(click)` handler, so we always render
  the row first and click it for real (visual confirmation outlines +
  "new tab opened" verification already in Click User).
* **Do not** scrape/fake the internal API without the user's explicit go —
  geometry + search + real clicks cover the need with zero extra
  permissions. (Optionally, one day, a "capture the users XHR once" feature
  could record each user's internal id and make the index jump one-step;
  see §5 — open question.)

### 3.5 UX: where the toggle lives

A new dropdown on the **Scroll & Parse** block (and reused by Click User):

* `locate: auto` (default) — the ladder above;
* `locate: search-first` — prefer Поиск, skip binary jump;
* `locate: jump` — geometry only (search box off);
* `locate: legacy` — today's wheel seek, unchanged.

Card summary shows the mode, e.g. "locate: auto". OFF/legacy keeps every
current stack byte-identical.

---

## 4. Expected gains (design targets)

| Metric (978-user list) | Today (wheel seek) | Smart Locate |
|---|---|---|
| Find a nick that is not on screen | ~130 steps × ~1 s ≈ **2 min worst** | search: **~0.5 s**; A–Z jump: **~10 × 0.2 s ≈ 2 s** |
| Reach the last row | ~130 wheel steps | **1 jump** |
| Locate after returning to Гостиная | re-traverse from top | position-independent (search/jump by nick) |
| Determinism | wheel momentum varies | exact offsets |
| Risk to existing flows | — | none while `locate=auto` verification fails open → legacy |

---

## 5. Open questions (need one live session to finalize)

1. **Поиск semantics** — substring or prefix? client-side filter of the
   *full* list (hoped) or server round-trip / only-online subset?
   (Implementation will self-verify and log the finding.)
2. **Sort order** — is the lobby list always A–Z case-insensitive, or does
   it change (sections, sort menu, by-gender tabs)? Saved HTML suggests A–Z
   but only one window was observed.
3. **Reset behavior** — does returning to Гостиная reset `scrollTop` to 0,
   reload data, or both? (Matters only for diagnostics; locator is
   position-independent either way.)
4. **Internal user ids** — optional later feature: record the users XHR/WS
   payload once, store `id` next to each nick, and jump straight by index.

## 6. Suggested implementation slice (when approved)

1. `backend/page_locator.py`: geometry probes, jump, search injection,
   binary search, stride scan — each unit-testable against a fake CDP that
   emulates a virtual list (rows materialize only around `scrollTop`).
2. Wire into `scroll_parser` seek path + `ClickUser` pre-click ensure.
3. `ScrollParse.locate` setting + `ui/js/stack-dnd.js` dropdown + summary.
4. Tests: virtual-list fake, sorted & unsorted fixtures, search-box hit/miss,
   spacer-based N, fallback-to-legacy, no-click-if-messaged.
