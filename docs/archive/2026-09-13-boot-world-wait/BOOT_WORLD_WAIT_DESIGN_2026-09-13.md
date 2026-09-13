# The boot world-wait fix, reapplied — the person list fills itself on start

Done 2026-09-13. This is a **port**, not a new design: the same field bug was
already fixed on the upstream session branch `arena/01a099fd-chat-v-bot`
(commits `93ff3ca` *fix(boot): the first page request WAITS for the world and
is answered* and `7e9e80a` *fix(boot): the person list fills itself on start,
no manual refresh*). This branch had diverged — it had restructured
`bridge/history_bridge.py` and `services/undo_service.py` into packages
(god-class round steps 6 and 7) — so the fix is reapplied to the new shape
rather than cherry-picked, and every claim below is re-measured here.

## The symptom, and why it kept coming back

> "after restart it should automatically upload all users, no need to wait a
> refresh button."

Reported four times. After a restart the **Full User Database** person list (and
the People list) stayed empty until ↻ was pressed.

`create_window` builds the page **before** `ApplicationLifecycle.startup` opens
any world: `memory.init()` and `history.init()` run while the page is already
booting and asking. So the window's first `userdb_page` reached a closed
`HistoryDB` and died with *"history database is not open"* — and that failure
was delivered through `history_error` **only**. No `userdb_page_ready` ever
followed, so the table waited for a reply that no longer existed.

## What this tree already had, and what it lacked

The first half of the upstream fix (`a0a8a65`, *Boot fills the windows by
itself*) **is** in this tree: `services/world_events.py::announce_world_live`
is the ONE emitter, `Router.announce_world_ready()` calls it, and
`ApplicationLifecycle.startup` calls that once `memory.init` + `history.init` +
`sync_world_state` are done — pinned by
`tests/unit/bridge_safety/test_world_ready.py` and
`tests/unit/app/test_app_lifecycle.py`.

The broadcast is necessary and not sufficient, which is why the symptom was
reported a third and a fourth time:

* it **cannot repair a request that is already dead** — the window asked, got an
  error on a channel it does not treat as an answer, and never re-asked;
* it can still **lose the JS-listener race** — `initApp` fired the
  HistoryDb/DbPanel loads from `init()`, *before* `setupBridgeListeners()`
  connected the handlers, so an announcement in that window is heard by nobody;
* and when a userdb read failed, `HistoryDb.loading` **stuck at `true` forever**
  with nothing to re-ask.

Missing here: `wait_for_world_open` / `run_when_world_open` (backend), the
`_run_async` / `_refresh_users_async` wiring, the page-side re-ask and the
bounded retry, and all five test suites that pin them.

## The port

One request → one answer, with both sides handled.

| Side | File | Change | Size |
|---|---|---|---|
| backend | `services/world_events.py` | + `WAIT_S = 15.0`, `wait_for_world_open(store, timeout=None, step=0.05)`, `run_when_world_open(scope, coro, store, on_error)`; module docstring now describes both halves ("the world's own clock: waiting for it, and announcing it is live") | 55 → **108** lines |
| backend | `bridge/history_bridge/runner.py` | `_run_async` becomes a 4-line call into `run_when_world_open`, passing `self.ctx.archive.db` and `self.history_error.emit`; the hand-rolled `guarded()` closure and its `logging` import go away | 54 → **58** lines, `RunnerMixin` **37/5 → 33/4** |
| backend | `bridge/people_bridge.py` | `_refresh_users_async` awaits `wait_for_world_open(self.ctx.memory)` before reading the queue | 149 → **155** lines |
| page | `ui/js/app.js` | `initApp` re-asks (`HistoryDb.reload()` + `DbPanel.refresh()`) right after the listeners connect; the `history_error` handler also calls `HistoryDb.onError(scope)` | 477 → **490** lines |
| page | `ui/js/history-db.js` | `RETRY_MAX 5` / `RETRY_MS 1000` / `_retries` / `_retryTimer`; `onError(scope)` un-sticks `loading` and retries only its own scopes; `reload(options)` normalizes options and lets a fresh load supersede a pending retry (a retry's own reload keeps counting); `onPage` pays the budget back on a good answer | 414 → **447** lines |

The two waits are bounded on purpose: `WAIT_S = 15.0` is the same patience the
world write gate gives an outside holder (I-17) — long enough for the install
migration on a big world, short enough that a world which never opens still
answers with an error instead of hanging. It is read at **call time** so a test
can shorten it, and a store without `is_open` (a test double) is never waited
on, so a unit test cannot become a 15-second sleep.

## Where this tree forced a different shape

Fidelity first: **7 of the 10 ported files are byte-identical to the fix as it
shipped** — `bridge/people_bridge.py`, `ui/js/history-db.js`, and all five test
suites (`test_boot_race.py`, `test_boot_chain.py`, `test_world_events.py`,
`test_history_panels_boot.js`, `test_userdb_refresh.js`). Three differ, and each
difference is this branch's structure, not a reinterpretation of the fix:
`services/world_events.py` (one docstring line: the caller's dotted path is
`bridge.history_bridge.runner._run_async` here, not
`bridge.history_bridge._run_async`), `bridge/history_bridge/runner.py` and
`ui/js/app.js`.

The port is not a patch application; three differences are this branch's own:

* **`_run_async` lives in a mixin now.** Step 6 moved it from
  `bridge/history_bridge.py` into `bridge/history_bridge/runner.py`
  (`RunnerMixin`), so the change lands there — and the class it belongs to
  **shrank** (37 LOC / 5 methods → 33 / 4) instead of growing, because the
  guard moved out into `services/`. Upstream measured the same effect against
  its ratchet ("the 493/45 ratchet class SHRANK to 482/44 instead of growing —
  the first attempt kept the guard in the class: 494 > 493, the gate caught
  it"). Here `HistoryBridge`'s facade stays at 24 LOC / 1 method and
  `RATCHET` in `tools/metrics/rule16_gate.py` is **empty** (step 6 emptied it),
  so there is nothing to ratchet against — the shrink is simply recorded.
* **`runner.py` shed its logging header.** With `guarded()` gone the mixin no
  longer logs, so `import logging` and `log = logging.getLogger("chatbot")`
  went with it (RULE 16 §16.4: remove unused imports). That dissolved the
  clone group step 6 had baselined as
  `("bridge/history_bridge/runner.py", "services/layout_service.py")` — the gate
  reported it **stale** and the entry is deleted, because the baseline may only
  shrink. `--with-clones` is back to 0 new / 0 stale.
* **`bridge/router.py` is untouched.** Upstream's router assembles *nine* domain
  bridges; this tree has ten (`FileBridge`), so the router diff between the two
  branches is this branch's own feature and none of the fix's business.
  `announce_world_ready` was already here.

`app.js` also keeps this branch's `WindowPresets` lines (`init()`, `refresh()`,
the `window_preset_list_updated` listener) — the re-ask is added beside them,
not instead of them.

## A harness bug the port exposed (step 6 regression, fixed here)

`tests/test_bridge_router.js` — the contract that every `App.bridge.<slot>()`
the UI calls has a Python `def` on a domain bridge — scanned `ui/js` with a
recursive walk but read `bridge/` with a **flat `readdirSync`**. When step 6
turned `bridge/history_bridge.py` and `bridge/stack_bridge.py` into packages,
every slot their leaves publish became invisible to it and the contract
reported **30 phantom "UI calls missing on Python"** (`userdb_page`,
`userdb_stats`, `run_stack`, `save_stack_preset`, …).

The pytest suite never caught it: the node suites are not part of it. It shows
up only when the JS sweep runs — which this port did, because it changes JS.
Fixed by walking `bridge/` with the same helper the JS side already used, so a
future split cannot hide a slot from the contract either (74 → 77 lines). All
**26 JS suites** pass now (`test_bridge_router.js`: 2 passed, 0 failed).

### A second hole the walk exposed, left open on purpose

Scanning *all* of `bridge/**.py` makes the contract answer "is this slot defined
somewhere under `bridge/`?" — not "does the assembled router actually expose
it?". Those differ, and the difference is live today:

* `ui/index.html` ships the Window Presets panel (`saveWindowPresetBtn`,
  `windowPresetPreviewApply`, `<script src="js/window-presets.js">`), and
  `ui/js/window-presets.js` calls `App.bridge.list_window_presets`,
  `save_window_preset`, `export_window_preset`, …;
* `bridge/window_preset_bridge.py` defines all of them plus the
  `window_preset_list_updated` signal that `app.js` connects;
* but `WindowPresetBridge` is **not** in `bridge/router.py::BRIDGE_CLASSES`
  (`git log -S WindowPresetBridge -- bridge/router.py` is empty — it never was),
  and it is a `QObject` subclass, which step 6 established cannot be assembled
  by `Bridge.__new__` + attribute copying (that is why every domain bridge here
  is a plain class).

So the panel is **localStorage-only at runtime**: every call site is guarded by
`if (App.bridge.list_window_presets)`, the guard fails silently, and named
presets never reach `stores/window_preset_store.py` (which `config_manager.py`
does construct). The contract test passes because the defs exist in a file the
router never loads — a false pass.

Not fixed in this commit, deliberately: closing it means converting a QObject
bridge to the plain-class domain-bridge shape (or registering a second channel
object), which is a feature change with its own design, tests and §16.5 risk —
not something to land inside a bug-fix port. Recorded in the SOR's Wire row as a
**known gap** so the next round sees it as work rather than as behaviour. The
harness follow-up that goes with it: collect defs only from the modules
`BRIDGE_CLASSES` names, so "defined but not assembled" fails the contract.

## Tests (RULE 8 — real objects, no fakes in the path)

Ported verbatim from upstream, and green against this tree's packages:

| Suite | Pins | Size |
|---|---|---|
| `tests/unit/bridge_safety/test_boot_race.py` (new) | the real `HistoryBridge` / `PeopleBridge` over a real world file, one request sent while both stores are closed: the page is answered with every nick, stats are answered, a world that never opens is a **bounded error naming the read**, People refresh waits | 157 |
| `tests/unit/bridge_safety/test_boot_chain.py` (new) | the SHIPPED order end to end: real `Router` + real `ApplicationLifecycle` + real `HistoryService` / `UserMemory`, the page asks *before* `startup` opens the world, the answer arrives with **zero** refresh calls | 143 |
| `tests/unit/services/test_world_events.py` | + `TestWaitForWorldOpen` / `TestRunWhenWorldOpen`: an open store is never slept on, a later one is waited for, a never-opening one gives up at the timeout, the work runs against the open world, a failure reaches the window or the log | 123 → **221** |
| `tests/test_userdb_refresh.js` | a late boot answer fills the table by itself (one request, no ↻, `loading` released), and a failed boot read retries by itself and fills the table | 230 → **273** |
| `tests/test_history_panels_boot.js` | the page half: un-stick the loader, scope filter (only `userdb_page`/`userdb_stats` retry), budget reset on a good answer, bounded at 5, a manual reload restarts the budget | 698 → **764** |

Upstream's mutation check (removing both waits fails 5 of the 8 boot tests;
restoring them turns all 8 green) is not re-run here — the tests are the same
files, byte-identical, and they fail without the waits for the same reason.

Measured here: `147 passed` for `tests/unit/bridge_safety` +
`test_world_events.py` + `test_app_lifecycle.py`; `26 / 26` JS suites; the full
suite `2778 passed, 3 skipped, 1 deselected, 1 xfailed, 777 subtests passed`
(12:27). Coverage of the ported code (`--branch`, 8 production packages):
**`services/world_events.py` 100%** (36 statements, 10 branches, nothing
missed), `bridge/history_bridge/runner.py` 91% — the three uncovered lines are
`_schedule`'s `except RuntimeError` (no running loop), pre-existing and
unrelated to the wait — and `bridge/people_bridge.py` 76%, whose gaps are the
delete/mark-messaged handlers that predate this change. Whole-tree coverage
moved **92.43 → 92.45% line, 87.99 → 88.04% branch, 91.57 → 91.60% combined**.

## RULE 16 / RULE 18 recheck

**RULE 16 (the fail lines).**

| Function | LOC | params | CC | verdict |
|---|---:|---:|---:|---|
| `wait_for_world_open` | 20 | 3 | 6 (B) | fits |
| `run_when_world_open` | 16 | 4 | 3 (A) | fits |
| `_run_async` (after) | 4 | 3 | 1 (A) | fits |
| `_refresh_users_async` (after) | 15 | 1 | 2 (A) | fits |

`tools/metrics/rule16_gate.py --with-clones` — exit 0: all owned functions fit,
`RATCHET` intact (still empty), no stale overrides, **0 new clone groups, 0
stale baseline entries** (after deleting the one this port dissolved). No smell
findings; the new code adds no duplicate window with anything in the tree.

**RULE 18 (the preferences, with a reason where we aim elsewhere).**

* Functions: all four in the **4–20** band; `_run_async` at 4 lines is the
  domain hook every archive slot answers through, so the short body earns its
  name (§18.1's "under 4 is fine when the name earns its place" applies to the
  neighbouring `_schedule` as well).
* Files: `services/world_events.py` at **108** and `runner.py` at **58** are
  leaves, which §18.2 calls "normal and good"; `people_bridge.py` at **155** is
  inside 150–300.
* `ui/js/history-db.js` at **447** is over 300 and says so in its own header,
  verbatim: `ideal-size: 447 lines reason=this is the ONE module behind the
  window's DOM (list, sort headers, paging, live refresh, per-row actions and
  the trash button); splitting it would put one window's behaviour in two files
  and break the HistoryDb.<method> surface the Node harness loads.` Updating
  that count from 414 is part of the port — the stated-reason mechanism §18
  asks for rather than a silent overshoot.
* `ui/js/app.js` went **477 → 490**, above the 150–300 ideal and inside the
  round's hard "no file over 500" line. Recorded rather than acted on: the 13
  lines are 8 lines of comment plus two re-ask calls and a four-line error
  handler, and extracting the bootstrap wiring is RULE 19 step-4 work, not
  something to attempt inside a bug-fix port. It is recorded here rather than
  in step 8 of the god-class round, whose stated scope is the *backend* modules
  over 500 LOC (`backend/config_manager.py` 502, `backend/dom_highlight.py`
  523) — `app.js` at 490 is under the round's hard line and is JS, so it is
  §18.2 preference debt for whoever next runs the file-size work. The tree's
  largest unannotated files stay `ui/js/sash-grid.js` (1359) and
  `ui/js/stack-dnd.js` (1247).
* One pre-existing class stays over the method ideal and is **not** worsened:
  `PeopleBridge` is 133 LOC / **20 methods** (gate: 15). The port adds a line
  inside an existing method and no method at all. It is not in `OWNED`, so the
  gate does not enforce it; it is noted here so the next round sees it.

Tree-wide RULE 16, re-measured the same day with `tools/metrics/current_audit.py`
(1991 functions): mean CC **3.11**, project max CC **10** (at the gate, nothing
over), mean cognitive 2.17, max nesting **4**, mean function LOC 9.62. The only
two functions over any fail line are the pre-existing cognitive-17 pair the
round plan already tracks separately (`bridge/router.py::_build_router_class`,
`stores/settings_store.py::get`) — neither is touched here, and neither may
worsen (§16.5). Class debt is unchanged by the port: 31 classes over 150 LOC,
22 over 15 methods. Files over 500: **2**. Mean MI 70.80. Exact clone groups:
**4** (66 duplicated physical lines), consistent with the gate's 2-entry
baseline, which this port shrank by one.

Tree-wide RULE 18, the same day: `reports/IDEAL_SIZE_BASELINE_2026-09-11.md` was
re-measured (it had gone stale before the round's steps 1–7). Function lengths
are effectively unchanged — 1991 functions, mean 9.6, median 7, 64.1% in the
4–20 band, max still 122 (`dom_probe.build_probe`) — because splitting by
responsibility moves code without lengthening it; the file picture moved a lot:
154 → **224** production files, median 145 → **99** lines, files over 500
**10 → 2**. Every package the round created sits inside the 5–15 file ideal.

## Rejected alternatives

* **Retrying in JS only** (poll until the list is non-empty) — rejected: it
  turns one dead request into N requests, cannot distinguish "world still
  opening" from "world genuinely empty", and leaves the backend able to lose an
  answer. The page-side retry that *is* ported is bounded (5 × 1 s), scoped to
  its own two read scopes, and is a healing net under a backend that answers —
  not the mechanism.
* **Making the broadcast re-fire until something answers** — rejected: the
  emitter would need to know what every window has loaded, which is the coupling
  `announce_world_live` exists to avoid (ONE emitter, one payload shape, shared
  by boot and switch).
* **Waiting inside `HistoryBridge`** — rejected, and upstream measured why: the
  first attempt kept the guard in the class and the ratchet caught it growing
  (494 > 493). The guard belongs in `services/`, beside the emitter it pairs
  with, so both bridges share it and the class shrinks.
* **An unbounded wait** — rejected: a world that never opens (a corrupt file, a
  failed migration) must still produce an error the window can show. Hence
  `WAIT_S`, and the bounded-error test in `test_boot_race.py`.
* **Swallowing the "database is not open" error** — rejected: that is the
  empty-vs-broken confusion RULE 4 forbids. The error still reaches
  `history_error` and the log; what changes is that the request is answered
  first.
* **Cherry-picking `93ff3ca` / `7e9e80a`** — rejected: the histories are
  unrelated and the files they patch (`bridge/history_bridge.py`,
  `services/undo_service.py`) no longer exist here. Applying them by hand to the
  package leaves, then re-measuring every number, is what makes the port
  checkable instead of hopeful.

## Docs that follow the code

`docs/current/SYSTEM_OF_RECORD.md`: the **Boot / world ready** row now states
both halves (wait + announce, plus the page-side re-ask and bounded retry) and
names the leaves that implement them here (`bridge/history_bridge/runner.py`,
`ui/js/app.js`, `ui/js/history-db.js`); **I-20** gains "and it never swallows a
request: a read that arrives before the world is open waits for it (bounded,
15 s) and is answered once"; the orchestration row calls `world_events.py` "the
world's clock: wait for it, announce it live"; the test map gains the two boot
suites. The archived 2026-09-11 DB-undo-restore design is **not** edited to
catch up (RULE 17) — this document is the dated record instead.
