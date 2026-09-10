# Scroll & Parse — remove duplicate filter control, add "Only scroll, no people adding"

Date: 2026-09-05
Status: design, written before implementation

Two changes to the Scroll & Parse block:

* **Bug #1** — remove the redundant "Also apply Filter panel criteria" checkbox.
* **Bug #2** — replace the failed backlog guard with a *scroll-only / seek* mode.

---

## 1. Bug #1 — duplicate filter controls

### 1.1 What is there now

The block config exposes **two** ways to filter the same people:

| Control | Kind | Effect |
| --- | --- | --- |
| Female / Registered / Guest / Anonymous | four tri-state selects (`any`/`yes`/`no`) | block-owned rules, stored as block params, travel with presets |
| Also apply Filter panel criteria | checkbox (`use_panel_filters`) | additionally runs the *global* Filter-panel rules from `CriteriaEngine` |

Two sources of truth for one decision. A person can be rejected by rules the
user cannot see in the block they are looking at, which makes "why was this
person dropped?" unanswerable from the block config alone.

### 1.2 The fix

Delete `use_panel_filters` entirely. The four selects are sufficient.

`panel_criteria` is then **never** applied by this block:

* `build_filter()` passes `panel_criteria=None` to `PersonFilter`.
* `build_parser()` passes `criteria=None` to `ScrollParser`.

### 1.3 What is deliberately *not* removed

`run_pipeline(..., panel_criteria=...)` and `ScrollParse.execute()`'s
`getattr(engine, "criteria", None)` keep their signatures. The engine and the
tests pass that argument today; keeping the parameter (and ignoring it) means
no caller breaks. The parameter is documented as accepted-and-ignored rather
than silently dropped.

Old presets that still carry `"use_panel_filters": true` must keep loading.
`BaseAction.__init__` swallows unknown keys into `self.config`, so a stale key
is inert — but `to_dict()` re-emits `self.config`, so the dead key would be
written back forever. The constructor therefore accepts and **discards** it
explicitly, so it disappears on the first save.

---

## 2. Bug #2 — "Only scroll, no people adding"

### 2.1 Why the backlog guard failed

The shipped guard (`skip_if_backlog` + `backlog_threshold`) answered
"should I collect at all?" with **skip the block entirely**. That is not what
was wanted. The user's need is to *scroll the live page to locate a person who
is already in People Memory but not yet messaged* — the scrolling still has to
happen, because the person must be found on screen before anything can be done
with them. A guard that skips the scroll can never find anybody.

**Both `skip_if_backlog` and `backlog_threshold` are removed**, along with
`CollectResult.skipped` / `.backlog`, `ActionEngine.backlog_count()`,
`ScrollParse._read_backlog()`, the STEP 0 block in `run_pipeline()` and the
skip branch in `_run_collect_phase()`. `UserMemory.count_unmessaged()` is
**kept** — the new mode needs exactly that number to decide which way to go.

### 2.2 The new setting

| Param | Type | Default | Label |
| --- | --- | --- | --- |
| `scroll_only` | checkbox | `False` | Only scroll, no people adding (find existing un-messaged person) |

Opt-in, one control, no threshold.

### 2.3 Behaviour

When `scroll_only` is **off** the block behaves exactly as it does today.

When **on**, at the top of `run_pipeline()`:

1. Read the un-messaged people from People Memory → the **target set** of nicks.
2. **If the target set is empty**, fall through to normal collection. This is
   the explicit requirement: *"IF there is no more Persons in list that has 'not
   messaged' status Then it work as before adding new people."* The mode is not
   a permanent off-switch; each run re-decides.
3. **If the target set is non-empty**, run the scroll in *seek mode*.

### 2.4 Seek mode inside `ScrollParser.collect()`

New parameter `seek_nicks: set[str] | None = None`. When present the per-item
logic changes:

| | normal mode | seek mode |
| --- | --- | --- |
| which people are examined | only nicks not seen before | **every rendered person**, seen or not |
| nick not in target set | filter + maybe collect | ignored, keep scrolling |
| fails the filter | rejected, record purged | **ignored, nothing purged** |
| passes the filter | collected, persisted | highlighted, returned, **scroll stops** |
| end of list, nothing found | returns what it collected | returns empty, `reached_end=True` |

Two properties matter and are called out because they are easy to get wrong:

* **Every rendered person is re-examined.** Normal mode short-circuits on
  `nick in self.known_nicks` because it only cares about *new* people. A target
  person is by definition *already known*, so that guard would skip precisely
  the people we are hunting for. Seek mode tests membership of the target set
  first and ignores `known_nicks`.
* **Nothing is written and nothing is destroyed.** No `on_collect`, no
  `on_reject`, no purge. "No people adding" is read strictly: the run must not
  change People Memory at all. In particular a target person who *fails* the
  filter is passed over silently rather than purged — they were not being
  evaluated for membership, only for suitability right now.

### 2.5 Result shape

`CollectResult` gains:

```python
seeking: bool = False   # this run was a seek, not a collection
found: object | None = None   # the UserRecord located on the page
```

On a hit, `collected == [found]`. That is deliberate: the engine builds its
queue from `collected`, so the located person flows into the rest of the stack
(Click on Person → message → send) with no engine changes. Per the decision
recorded with this task, seek stops the **scrolling**, not the run.

On a miss, `collected == []` and `execute()` returns `FAIL` with a distinct
message, so "no un-messaged person is currently on the page" is not confused
with "nobody matched the filter".

### 2.6 Persistence on a hit

`_run_collect_phase()` upserts everyone in `result.collected` as an idempotent
safety net. For a seek hit that re-writes a record that already exists, which
is harmless — it is the same person, already in the list, not a new one. The
invariant "no *new* people are added" holds. Guarding the upsert would risk
losing a legitimate live update to that person's flags, so it stays.

### 2.7 Logging

```
🔎 Scroll-only mode: 7 un-messaged person(s) in the list — searching the page for one of them
  🎯 Found “Anna” on the page (passes the filter) — orange outline drawn
⏹ Scroll-only: stopping the scroll, no new people were added
```

Empty target set:

```
🔎 Scroll-only mode: no un-messaged people in the list — collecting new people as usual
```

Miss:

```
⚠ Scroll-only: reached the end of the list, none of the 7 un-messaged people are on the page
```

### 2.8 Edge cases

| Case | Behaviour |
| --- | --- |
| Target set empty | Normal collection (explicit requirement) |
| Memory read fails | Fail open → normal collection, warn |
| Target person on page but fails the filter | Ignored, keep scrolling, not purged |
| Several targets on one screen | First in DOM order wins |
| User presses Stop mid-seek | `stopped=True`, same as normal mode |
| `min_new_users` | Ignored in seek mode — it counts *new* people, and seek adds none |
| `purge_rejected` | Ignored in seek mode (§2.4) |
| No engine / no memory | Fail open → normal collection |

### 2.9 Interaction with the rest of the stack

The mode changes only *which* person ends up in the queue, never the queue's
shape, so `CLICK_USER` and the messaging blocks are untouched. Running the
stack repeatedly with the checkbox on therefore walks the existing backlog one
person per cycle, and starts adding new people again on the cycle after the
last un-messaged person is dealt with — which is the requested loop.

---

## 3. Test plan

`tests/test_scroll_only_seek.py`:

* **Panel-criteria removal** — `use_panel_filters` gone from `config_schema()`
  and from `to_dict()`; a preset carrying the stale key still loads and drops
  it; panel criteria no longer influence the verdict.
* **Backlog guard removal** — the params, the schema entries and the UI
  defaults are gone; a preset carrying them still loads.
* **Mode decision** — empty target set collects normally; non-empty seeks;
  memory failure fails open.
* **Seek** — finds a target that is already known; ignores non-targets; ignores
  a target that fails the filter; stops scrolling on the first hit; scrolls to
  the end on a miss; honours Stop.
* **No writes** — `on_collect`/`on_reject` never fire in seek mode; memory row
  count is identical before and after a seek, hit or miss.
* **Engine integration** — a hit becomes the queue; a miss returns an empty
  queue; with the checkbox off nothing changes.
* **Round-trip** — `scroll_only` survives `to_dict()` and appears in
  `stack-dnd.js`.

Existing suites must stay green; the backlog-guard suite is deleted with the
feature it covered.
