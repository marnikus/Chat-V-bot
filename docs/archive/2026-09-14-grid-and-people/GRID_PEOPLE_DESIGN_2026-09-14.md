# Design — Person tracking + adaptive grid layouts (5 issues)

Investigated at commit `bbc70d4`. Every claim below was checked against the
running code or an executable probe; where a probe contradicted the reported
symptom, that is stated rather than smoothed over.

**Status: design only. No production code has been changed.**

---

## 0. Summary of what the investigation actually found

| # | Reported | Verdict after investigation |
|---|---|---|
| 1 | People not reaching the Person List | **Confirmed, cause found.** Not a timing bug — rejected people are *deliberately deleted* (`purge_rejected=True` by default) and the default filter is narrow. |
| 2 | Save/restore from file fails "bridge required" | **Confirmed, cause found.** Export is bridge-only by design; import already works bridge-free, but `_persistDocument` then re-validates against the *live* window set. |
| 3 | Presets must tolerate different window sets | **Confirmed.** `validatePortablePreset` hard-rejects any document whose window list ≠ the current 14 ids. Three separate checks enforce it. |
| 4 | Drag cannot create rows | **Partly mis-stated.** Row creation exists in the model *and* in the UI; what is unreachable is the **between-row** drop. Cause is hit-testing, not the tree algebra. |
| 5 | Sashes vanish, cannot move lines | **Confirmed, cause found — and it is NOT the stale-class line I first suspected.** It is a `MIN_PX` arithmetic lockout. |

---

## 1. Issue 1 — people are added, then deleted

### What happens
`backend/scroll_parser/judge.py::_judge` reports *every* person it sees into
`result.all_people`, then splits them:

* passes the filter → `_collect_one` → `_notify_collected` → engine
  `person_collected` → `memory.upsert_user` → **appears in the list**;
* fails the filter → `_reject_one` → `_notify_rejected` → engine
  `person_rejected` → **`memory.delete_user(nick)`** → removed from the list.

So a parsed person who fails the filter is not merely skipped — any existing
record for them is destroyed. That is deliberate (RULE 6, "a person who does
not pass the filter can never linger from an earlier run"), but it is exactly
the reported symptom.

### Why so many fail
`ScrollParse` defaults (`actions/scroll_parse.py:66`) are narrow:

```
filter_female = YES      filter_registered = NO
filter_guest  = YES      filter_anonymous  = NO
```

A registered (non-guest) person fails two rules at once. Combined with
`purge_rejected = True` (line 64) the default configuration *removes*
registered users from the Person List on every scroll.

### Design
Keep RULE 6 intact; separate "seen" from "kept".

1. **`ScrollParse.purge_rejected` default flips to `False`.** Purging stays
   available, but destroying records must be opted into, not inherited. This
   is a one-token change plus its schema default and pinned tests.
2. **Report the purge honestly.** `_collect_summary` already prints
   `N removed`; add the reason breakdown so the log says *why* a person
   vanished instead of leaving the user to guess.
3. **No new state field.** The two-tier "provisional person" idea is rejected:
   it needs a schema migration, a UI state, and it duplicates what
   `all_people` vs `collected` already expresses.

**Risk:** flipping a default changes observable behaviour. Mitigated by
pinning the new default in `tests/test_filter_purge.py` (which already
inspects these knobs) and stating it in SYSTEM_OF_RECORD.

---

## 2. Issue 2 — file save / restore

### What actually fails
Three different paths, only one of which is really "bridge required":

* **Export** (`window-presets.js:223`) — genuinely bridge-only, because it
  opens a native folder picker. The message is correct but the *capability*
  is missing: there is no browser-side download fallback.
* **Import** (`_readFile`, line 274) — already works without a bridge; it
  reads the file with `FileReader` and validates locally. **This path is not
  broken.**
* **The real defect:** `_applyPreview` → `_persistDocument` (line 73)
  re-runs `validatePortablePreset` *after* the user accepts the import, and
  that validation is against the live window set (§3). A file saved on a
  build with a different window list is accepted at preview and then
  rejected at save, producing a confusing late failure.

### Design
* Split validation into **structural** (format, schema, JSON, bounds
  arithmetic) and **environmental** (does this window still exist).
  `_persistDocument` runs structural only — a file is storable whether or not
  today's app can show every window in it.
* Add a bridge-free export fallback (`Blob` + object URL) so "save to file"
  works in any host; keep the native picker when the bridge exists.
* The round-trip test the ticket asks for (`save → restart → import`) becomes
  a Node harness: build a document, serialise, re-parse in a *fresh* module
  instance with no bridge and no localStorage, assert the tree is identical.

---

## 3. Issue 3 — adaptive restore

### The three hard rejections
In `sash-grid.js::validatePortablePreset` and its helpers:

| Line | Check | Effect |
|---|---|---|
| `_portableWindows` | `doc.windows.length !== SashCore.WINDOW_IDS.length` | any count mismatch → reject |
| `_portableWindows` | `!SashCore.WINDOW_IDS.includes(item.id)` | one unknown id → reject |
| `validatePortablePreset` | `grid.window_count !== SashCore.WINDOW_IDS.length` | metadata mismatch → reject |

Plus `SashCore.deserialize` rejects a tree containing an unknown leaf. So a
preset from any build with a different window list is unusable — which is
what the ticket describes.

### Design — a reconciliation pass, not a looser validator
Validation stays strict about *structure*; a new pure function adapts the
document to the live set **before** the tree is applied:

```
reconcile(doc, liveIds) -> {
  tree,                     // pruned + grafted
  matched[], skipped[], extra[],   // the summary the ticket asks for
}
```

Rules, in order:
1. **Match** by exact id (the stable key). No fuzzy title matching — a
   renamed window is a different window, and guessing would silently move a
   user's layout.
2. **Skip** saved ids not in `liveIds`: remove the leaf, then collapse any
   split left with one child (`SashCore` already has the collapse primitive
   used by `moveWindow`'s removal step, so this is reuse, not new algebra).
3. **Graft** live ids absent from the document: append as new rows at the
   root, each at an equal share — visible and usable, never off-screen.
4. **Renormalise** every split's `sizes` to sum 100 (the invariant the probe
   in §6 confirmed holds today).
5. Report `matched/skipped/extra` into the existing preview meta line.

Off-screen safety is already guaranteed: bounds are normalised 0–1 and
`_validPortableBounds` enforces `x+width <= 1.001`, so a resolution change
re-projects rather than displacing. The stored `screen` block stays advisory.

---

## 4. Issue 4 — between-row drops

### What already works
Dragging to a window's top/bottom edge creates a horizontal split
(`_computeSpec` line 1034, `dir:'col'`). Row creation is *not* missing.

### What is unreachable, and why
The root node is a **column**, so its children *are* the rows. Dropping on the
sash between two root children inserts a new row — I proved this with a probe:
root children went 6 → 7 and the dragged window became its own full-width row.

The UI can almost never deliver that spec:

* `_computeSpec` iterates **window rectangles first** and returns on the first
  hit; the sash loop is only reached when the pointer is inside no window.
* A sash is `flex: 0 0 6px` (`sash-layout.css:86`). The reachable target is a
  6-pixel band.

So the capability exists and the hit-testing hides it.

### Design
* Give sashes a **hit band** (~14 px) independent of their 6 px paint: test
  sash proximity *before* the window loop when the pointer is within the band.
  Painted width is unchanged, so nothing moves visually.
* Render a **full-width horizontal preview line** for a row insertion, which
  `_showSpec` already distinguishes (`spec.dir === 'row'` vs `'col'`).
* Undo is inherited: `_dragUp` calls `_save()`, and grid state already flows
  into the global undo record via `App.recordGlobal`.
* Tests: first, middle and last row insertion asserted on the **tree**, which
  needs no DOM (the §6 probe style).

---

## 5. Issue 5 — sashes disappear and stop moving

### The suspect I rejected
`_syncEmptySplits` (line 740) **adds** `sash-hidden` and never clears it,
while the earlier pass (line 701) uses `toggle`. That asymmetry looks like the
bug. It is not, in the current code: every call site runs `_syncHidden()`
(the toggling pass) immediately before `_syncEmptySplits()`, so the flag is
always recomputed. I verified this with a two-pass model probe — the flag
cleared correctly in both the window-neighbour and split-neighbour cases.
It remains a latent trap and the design fixes it, but it is not the cause.

### The actual cause
`_resizePixelAllocation` (line 1211):

```js
const span = axis - others - sashTotal;
if (span < this.MIN_PX * 2) return null;   // resize silently does nothing
```

`others` is every non-adjacent child, each held at `MIN_PX = 96`, and each
child's panel also has `min-*: 96px` in CSS. As drags accumulate children into
one split, `span` shrinks until it crosses `2 × 96`. Measured:

| children in one column (700 px tall) | span | resizable |
|---|---:|---|
| 2 | 694 px | yes |
| 5 | 388 px | yes |
| 6 | 286 px | yes |
| **7** | **184 px** | **no — dead** |
| **8** | **82 px** | **no — dead** |

A 1200 px-wide row survives to 8+, which is why the fault appears only after
"moving some rows and columns" — it is specifically **vertical stacking** that
runs out of room first. And a drag probe showed `moveWindow` happily producing
a 6-child split, so reaching 7 is ordinary use, not abuse.

The sashes also *look* gone because `.sash::before` paints inside a strip that
has been squeezed, and `_beginDrag` skips any sash with no `offsetWidth/Height`
— so once collapsed they stop being drop targets too, matching "I can not move
lines anymore".

### Design
1. **Scale the floor instead of failing.** Replace the hard bail with an
   effective minimum `min(MIN_PX, axis / (n + 1))`, so a crowded split keeps
   *proportional* minimums and stays resizable. The 96 px floor remains
   whenever there is room for it.
2. **Return a reason, not `null`.** `_resizePixelAllocation` returning `null`
   silently is what made this invisible; it should log once per gesture.
3. **Make the CSS minimum follow the same rule** via a `--sash-min-panel`
   override set on crowded splits, so CSS cannot re-impose a floor the JS has
   just relaxed.
4. **Fix the latent toggle asymmetry** (line 740 → `toggle`) while here, with
   a test that pins it independently of call order.

---

## 6. Verification probes used

All probes were run and deleted; none remain in the tree.

* `moveWindow` fuzz — 300 edge drops, then 500 mixed edge/sibling/sash drops:
  tree stayed valid, no leaf lost, sizes summed to 100, min child share 12%.
* Adjacent-pair sash fuzz — 140 real sash drops, all valid.
* Between-row probe — proved a root-level sash drop creates a new row (6→7).
* `MIN_PX` arithmetic table — reproduced the resize lockout at 7 children.
* Two-pass `sash-hidden` model — disproved the stale-class hypothesis.

## 7. Step plan

| Step | Scope | Est. |
|---|---|---|
| K1 | Issue 5 — resize lockout + toggle asymmetry + tests | 8–12 h |
| K2 | Issue 3 — `reconcile()` + summary, pure and unit-tested | 12–16 h |
| K3 | Issue 2 — split validation, bridge-free export, round-trip test | 10–14 h |
| K4 | Issue 4 — sash hit band, row preview, insertion tests | 10–14 h |
| K5 | Issue 1 — purge default + reason reporting + pins | 8–10 h |
| K6 | Round close: re-measure RULE 16 / RULE 18, docs, SLOC budget | 6–8 h |

Order is deliberate: K1 is the one that makes the app unusable, K2 is the
largest piece of new logic and everything in K3 depends on it, and K5 is last
because flipping a default is the change most likely to need discussion.

## 8. RULE 16 / RULE 18 commitments

* Every new function targets ≤ 20 lines, CC ≤ 10, ≤ 4 params. `reconcile()`
  decomposes into `match / prune / graft / renormalise` so no single unit
  carries the whole algorithm.
* `sash-grid.js` is already the repo's second-largest file (1 341 lines) and
  **the Round J plan flags it as a complexity cluster**. This work must not
  grow it: `reconcile()` and the preset validation split land in new modules
  (`ui/js/core/preset-reconcile.js`, `ui/js/core/preset-validate.js`), which
  also makes them unit-testable without a DOM.
* Node harnesses for every new unit; `rule16_gate.py --with-clones`,
  `dump_public_api.py --diff` and the full pytest suite green per step.
* SLOC delta stated per step, round total ≤ 2% (§18.2b).
