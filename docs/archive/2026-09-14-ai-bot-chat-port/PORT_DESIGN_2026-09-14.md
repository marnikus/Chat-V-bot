# Reapplying "AI Prompt Editor, Connections & Presets" on the post-refactor tree

Port of a finished feature onto a tree that moved underneath it. The feature is
the AI Bot Chat window, the Grok Prompt Editor, named AI connections and prompt
presets; its own design record is the six-doc group
[`docs/archive/2026-09-13-ai-bot-chat/`](../2026-09-13-ai-bot-chat/) — this doc
is about the *transfer*, not about the feature.

This is the RULE 16 §16.6.2 record: what the two trees looked like, where the
seams were, what each conflict cost, and the numbers afterwards.

---

## 1. The trees

| | Commit | What it is |
|---|---|---|
| Feature (content source) | `arena/01a09b6e-chat-v-bot` @ `478fca5` | 11 commits from `0ad07c9` that build the feature to completion; 59 files, +9 600 / −162 |
| Refactored (target) | `arena/01a09e38-chat-v-bot` @ `51bae21` (G6.6) | Round G's quality work; `0ad07c9` → HEAD is 153 files, +7 481 / −3 628 |
| Parallel re-application | `arena/01a09cb8-chat-v-bot` @ `5e75a0d` | the same feature re-applied onto `d3e6245` (Round H step H2) — two commits short of complete |

`git merge-base HEAD 478fca5` is `0ad07c9` — the source's own base — so the
feature is *ancestral* to HEAD's diverging history rather than unrelated to it,
and every feature file is reachable by `git diff 0ad07c9 478fca5 -- <path>`.

The user named `arena/01a09b51-chat-v-bot` as the source. That branch (`47e44e6`)
holds none of this feature — it is Round F/G/H quality work — so the sources were
taken from the branch that does, `arena/01a09b6e-chat-v-bot`, at its last commit.
The second feature branch, `arena/01a09cb8-chat-v-bot`, is the same feature
*re-applied* onto a post-refactor tree: its first eight commits map one-to-one
onto the `01a09b6e` chain by commit subject, and it is content-short by the last
two fix commits — `d3b4a14` "Pin the popup's close cross instead of pushing it
with a margin" and `478fca5` "Scope the popup's buttons above `.layout-menu`'s
element selectors". The loss is not cosmetic: `.layout-menu button` is (0,1,1)
against `.ui-btn`'s (0,1,0), so without the second fix every button in the AI
Settings popup loses its styling. The tip-to-tip diffs show it exactly —
`bot-chat.css` 397 lines there against 421 here, `index.html` without the
`bot-settings-headings` wrapper that pins the close cross, `test_bot_chat_js.js`
80 lines shorter, and `CONNECTION_PICKER_REDESIGN_2026-09-13.md` 229 lines
against 286 (171 + 58 from the eight shared commits, + 20 and + 37 from the two
fix notes). `478fca5` is therefore the content source; `5e75a0d` was read as a
cross-check on how the author re-expressed the feature against refactored code.
It is also the closer tree: HEAD never received Round H, so the two tips differ
in 108 files that are almost entirely H1/H2's package splits
(`backend/history_query/`, `backend/chat_sync/`, `backend/scroll_parser/`).

## 2. Why a port and not a cherry-pick

The 11 commits *can* be cherry-picked (`0ad07c9` is an ancestor), and that was
the first candidate. It was rejected on the repo's own precedent for
cross-branch features (`e4ef002`, `657ab17`): the feature is one finished
artifact, the interesting content of the port is the *adaptation*, and a chain
of 11 cherry-picks would bury that adaptation in eleven conflict resolutions and
eleven commit messages, none of which is the record RULE 16 §16.6.2 asks for.
The port is therefore one change: the feature's files verbatim where the tree
allowed it, a 3-way patch per divergent file, and this doc.

## 3. The seam: 18 of the 24 ported files were byte-identical

The feature modifies 28 existing files and adds 31. Four of the 28 are
`config/*.json` — section 6. Everything else was compared as a blob
(`git rev-parse 0ad07c9:<path>` vs `git rev-parse HEAD:<path>`) before patching,
and **18 of the remaining 24 were byte-identical**, so `git apply --3way`
applied them verbatim: `bridge/layout_bridge.py`, `services/layout_service.py`,
`stores/preset_store.py`, `ui/index.html`, five `ui/js/*.js` (`app.js`,
`history-store.js`, `history-view.js`, `sash-core.js`, `sash-grid.js`), nine test
files and `docs/current/SYSTEM_OF_RECORD.md`.

Six files had moved, and each needed a decision — three in production code, two
in tests, one in docs:

* **`bridge/router.py`.** G6 split the router synthesis into `_register_signals`
  / `_register_slots` / `_register_legacy_attrs` (RULE 19 §19.5: long-and-flat →
  extract by phase). The feature's three edits were re-applied *into that
  shape*: the imports and the three bridge classes beside the other bridge
  classes, and `V4_WINDOW_IDS` into the attribute tuple inside
  `_register_legacy_attrs` — the phase that exists precisely so a new window id
  has one home. Taking the source file wholesale would have re-inlined
  `_build_router_class` and undone G6.
* **`backend/config_manager.py`.** Diverged by one comment (the `ideal-size:`
  note was re-worded when the AREA-D freeze was lifted). The feature's four
  lines — `"ai_connections"` and `"prompt_presets"` routed to the `presets`
  store — applied as written.
* **`tools/metrics/rule16_gate.py`.** Both sides grew an OWNED tail and touched
  the baseline tables, from different measured states (`0ad07c9` → HEAD alone is
  52 lines here; the feature is 44). Merged table by table:
  * OWNED — the feature's 125-entry block appended verbatim;
  * `SMELL_FILES` — HEAD's two files (`backend/history_query.py`,
    `bridge/history_bridge.py`) **kept** and the six new bot files added. The
    parallel 09cb8 port *deleted* those two, correctly for its own tree (H2
    split `history_query.py` into a package); here they still exist and are
    still the vulture/R0801 surface;
  * `CLONE_BASELINE` — `bridge/bot_bridge.py` joined the existing
    `(cdp_bridge, people_bridge)` header group, and the maintenance note about
    `bot_prompt_bridge.py` leaving the collector/label/layout/undo group was
    carried over with the group itself.
  The `--with-clones` run then proved the merge: **0 new groups, 0 stale
  baseline entries**.

Two test files were merged rather than applied: `tests/test_history_bridge.py`
(keep HEAD's `HistoryService(HistoryDeps(...))` **and** add the feature's
`AI_WINDOWS` list) and `tests/integration/services/test_services_undo.py` (keep
HEAD's `UndoDeps`/`PeopleDeps` call sites **and** the feature's
`LayoutService.GRID_VERSION` assertions instead of the literal `3`). The sixth
file is `docs/archive/README.md`: both sides appended to the end of the index,
so the feature's six-doc section was appended to HEAD's own file (asserted
absent first) rather than checked out over it.

## 4. The refactor the port had to speak

Round F/G replaced wide constructors with request objects. Everything the
feature builds itself (`BotChatService`, `ReactionLabels`, `PromptLibrary`,
`GrokClient`, `ConnectionStore`) is its own code and unaffected, but the one
place a ported *test* builds a refactored class was not:

```python
# source, pre-refactor                      # HEAD, after the F3/G4 refactor
HistoryService(cdp=None)                    HistoryService(HistoryDeps())
```

`HistoryService.__init__` now takes `services/history/requests.HistoryDeps`, so
`TestRealArchiveInterface` — the test whose whole point is to construct the REAL
archive — was rewritten to the current signature. The archive interface the
*production* code uses (`archive.query.page(nick, limit=…)`, `archive.db.is_open`,
`archive.parser`) is unchanged by the refactor, which the suite confirms.

## 5. The bug the port found (in the ported test, not in the feature)

After the port the whole suite was green — **3 030 passed** — and the process
then never exited. `py-spy dump` named it in one shot:

```
Thread-1451 (_connection_worker_thread):  aiosqlite/core.py:59
MainThread:                               threading.py:1583  _shutdown
```

`tests/unit/services/test_bot_chat_service.py` builds real worlds
(`await HistoryDB(path).init()`) for five of its classes and closed only the one
a test closed by hand. aiosqlite's connection worker is **not** a daemon thread
and `Connection.__del__` is what normally stops it, so an open handle parks the
interpreter in `threading._shutdown` forever: every test passed (0.77 s) and
`pytest` had to be killed at 10 minutes (rc 124).

The fix is test hygiene, not a product change: every world `make_db` opens is
registered, and a `WorldCase.tearDown` closes it (`close()` swaps the
connection out first, so it is idempotent and a test that already closed its own
world is not punished). Repro without the fix, 8 lines:
`HistoryDB(path).init()` + one INSERT + exit → rc 124.

## 6. What was deliberately not ported

**No `config/*.json` file is ported** — all four the feature touches are runtime
state owned by the machine that ran it, and one of them carries a plaintext API
key:

* `config/session.json` — the source's saved v4 grid tree (with the two new
  windows). A v3 payload is *upgraded* to v4 on load, not rejected
  (`LayoutService._window_set_ok` + `sash-core.migrate`), which is the migration
  case the feature added; copying an arrangement is not part of the feature and
  would overwrite the one this tree already has.
* `config/undo.json` — the source's undo timeline.
* `config/presets.json` — the source's presets, including the owner's
  `ai_connections` rows and their key.
* `config/settings.json` — the source's settings.

What the feature *needs* in there it seeds itself: `ConnectionStore` writes one
keyless row per provider on first read, `client_for` refuses until a key exists,
and the prompt library restores the shipped template when its section is absent
— so an empty `config/` yields a visible, working, keyless AI window rather than
an unreachable one. The routing that lets those sections live in `presets.json`
at all is `backend/config_manager.py`'s, and that *is* ported.

## 7. Numbers after the port

| Measurement | Before | After |
|---|---|---|
| Python suite | 2 828 passed / 2 skipped / 1 deselected / 1 xfailed | **3 030 passed** / 2 skipped / 1 deselected / 1 xfailed / 898 subtests |
| Suite exit | clean | clean (after §5) |
| JS suites | 26 files green | **28 files green** (92 + 17 new assertions) |
| Line coverage (§16.3 command) | 91.09 % (recorded baseline) | **91.59 %** |
| Branch coverage | 87.06 % (recorded baseline) | **87.76 %** |
| New functions with 0 hits | — | **0** of 143 |
| RULE 16 gate | rc 0 | rc 0; `--with-clones` **0 new, 0 stale** |
| Biggest new function | — | 24 LOC (`_adopt_legacy`, `services/bot_connections.py`); **0 over 30** |
| Functions in RULE 18's 4–20 band | tree 63.6 % | new code **69 %** (99/143) |

Sizes of the new production files (RULE 18 §18.2 aims at 150–300): services —
`bot_chat` 299, `bot_connections` 231, `bot_grok` 193, `bot_variables` 165,
`bot_providers` 162, `bot_reactions` 123, `bot_prompts` 118, `bot_presets` 85,
`bot_transcript` 68, `named_section` 35; bridges — `bot_bridge` 185,
`bot_prompt_bridge` 119, `bot_settings_bridge` 106; UI — `bot-chat.js` 396,
`bot-settings.js` 394, `bot-prompt.js` 354, `bot-connection-view.js` 237,
`dark-select.js` 194, `bot-messages.js` 75; `ui/css/bot-chat.css` 421.

## 8. RULE 18 recheck — and the deviations, stated

1. **Three AI JS files are over the 300-line ideal** (`bot-chat.js` 396,
   `bot-settings.js` 394, `bot-prompt.js` 354). They are *not* split: each is one
   window's controller, and splitting a controller by line count would put one
   window's state in two files, which is the second responsibility §18.2 warns
   about rather than a remedy for it. Each file's `ideal-size:` note names that
   constraint (§18.5). Three of those notes carried numbers from before the
   feature's last commits and were corrected here to the measured physical count
   (`bot-settings.js` 310 → 394, `bot-connection-view.js` 184 → 237,
   `dark-select.js` 193 → 194) — the same comment-only maintenance G6.1 did for
   the notes it found, and the same measurement RULE 18 §18.6 pins
   (`ui/js/history-db.js` is 447 lines and says 447).
   `ui/css/bot-chat.css` (421) carries no note on purpose: stylesheets are
   outside §18.2's file ideal by house practice — four CSS files predate this
   port at 309–539 lines and none of the eleven carries an `ideal-size:` note.
2. **`docs/current/SYSTEM_OF_RECORD.md` grew 328 → 341 lines** — 13 new rows
   (2 behaviour rows, 11 invariants I-23…I-33), each one line, each pinned to a
   module and a test. The file is an accepted §18.4 overrun *at its ceiling*,
   whose rule for the next edit is "move detail into the archive first". That is
   unchanged and now binding on the next edit: the invariants were kept inline
   because §18.4's stated exception is exactly that their value is sitting next
   to the module and the test that enforce them. §6's stale layer counts were
   corrected in place (no new lines).

Two stale `ideal-size:` notes in the ported Python were corrected to measured
LOC before this doc was written (`bot_chat.py` 292 → 299, `bot_transcript.py`
63 → 68, `named_section.py` 30 → 35).

## 9. Verified, not assumed

* `node tests/test_bot_chat_js.js` → 92 passed; `test_dark_select_js.js` → 17;
  the other 26 subject suites unchanged and green.
* `tests/test_bot_bridge.py` 65, `tests/unit/services/test_bot_reactions.py` 22,
  `tests/unit/services/test_bot_chat_service.py` 114 — each exits 0.
* Grid: `sash_core` 31, `sash_core_v2` 18, `sash_grid_window_controls` 16,
  `grid_persistence` 6, plus the new v3→v4 migration case in
  `tests/test_grid_layout_v2_migration.py`.
* The port added no tests of its own: the feature brought five suites / 310 tests
  with it (`test_bot_bridge.py` 65, `test_bot_chat_service.py` 114,
  `test_bot_reactions.py` 22, `test_bot_chat_js.js` 92,
  `test_dark_select_js.js` 17).
* The 143 new functions were measured with the same AST walk the gate uses: 0
  over 30 LOC, 99 in RULE 18's 4–20 band, 0 unreached by the coverage run.
* §16.7's last unverified line — "every new function has a test that would fail
  if deleted" — was checked rather than asserted: a copy of the tree was made,
  ONE function per new module was renamed in the copy (a function under another
  name is unreachable to every caller, which is what deleting it means), the
  feature's own suites were run against the copy, and the file restored. **13 of
  13 Python deletions and 3 of 3 JS deletions were noticed** — 11 by a failing
  test, 2 by an `ImportError` at collection (`client_for`, `item_text`: the test
  imports the function, so deleting it fails the suite before a single test
  runs), and 3 by the Node harness (`DarkSelect.attach`, `BotMessages.bubble`,
  `BotMessages._media`). The renamed function per module: `_all`,
  `ConnectionStore.all`, `for_template`, `render`, `fill`, `reply_of`,
  `client_for`, `apply`, `item_text`, `scoped_page`, `bot_send_message`,
  `bot_preview_prompt`, `bot_connections`. That is a spot check, not mutation
  testing of the whole tree — §16.8 puts the latter out of scope for one session.
