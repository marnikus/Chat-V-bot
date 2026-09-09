# `actions/` — Execution Layer: test design (spec-first)

Date: 2026-09-09
Scope: section **B** of the coverage plan — `actions/registry.py`,
`base_action.py`, `click_user.py`, `scroll_parse.py`, `type_message.py`,
`wait_page.py`, `pause.py`, `collect_history.py`, `search_users.py`,
`custom_find.py`, `attach_image.py`.

## 0. Method (why this document exists)

Every case below was written **from the contract only** — the module
docstring, the `config_schema()` the UI renders, the house rules quoted in
the docstrings (RULE 3/4/5/7), and the design target column of the coverage
table — *before* the implementation was read. Each row therefore states the
path the code **should** take. A test that only reproduces the code it sits
next to can never fail, so it can never find a bug; a test written from the
contract fails exactly where the code and its promise disagree.

Where a test failed on first run, the row is marked 🔴 and the mismatch is
described in §12 (Bug ledger) instead of the expectation being softened to
match the code.

Contract sources used, per module:

| Module | Contract source |
|---|---|
| `registry.py` | module docstring (`@register` + `discover()` scan), `register` docstring ("block_id must be non-empty"), `discover` docstring ("returns number of newly discovered"), `actions/__init__.py` docstring ("fires @register decorators **or** `__init_subclass__` hooks") |
| `base_action.py` | class docstring ("every action block inherits this and implements execute()"), `to_dict` docstring ("serialize the block with ALL of its settings, **round-trip safe**"), `display_name` docstring, `__init__` comment ("enabled and pre_delay_ms may arrive inside kwargs when built from dict") |
| `type_message.py` | module docstring (composer mirror), inline comment (`{{nick}}` → remembered selected user, falls back to the queued user) |
| `wait_page.py` | module docstring (polls, reports each probe, found moment, timeout with last known DOM state) |
| `pause.py` | docstring ("pause manages its own delay") |
| `search_users.py` | module docstring + `config_schema` label **"Search text ({{nick}} = selected user)"** |
| `custom_find.py` | module docstring (FIND/CLICK phases) + `config_schema` label **"…{{nick}} = selected user"** |
| `click_user.py` | module docstring (exact nick match, *confirm a new tab really appeared*) |
| `scroll_parse.py` | module docstring (STEP 1-3, scroll-only mode), `build_filter`/`run_pipeline` param docs ("accepted for call-compatibility and IGNORED", "fails open") |
| `collect_history.py` | RULE 3 (settings round-trip), RULE 4 ("nothing new" ≠ "not a private chat"), RULE 5 (per-chunk progress), RULE 7 (stop ≠ failure) |
| `attach_image.py` | `config_schema` defaults, module docstring (9-argument delegation) |

Notation: **expected path** = the observable outcome the contract demands
(return value, delegated arguments, reported lines, elapsed time).

---

## 1. `actions/registry.py` — P0 (target: 100 % branch)

| ID | Case | Expected path |
|---|---|---|
| REG-01 | `import actions; get_action_class("PAUSE")` | the `Pause` class — the package's public API must resolve every block, whichever of the two documented mechanisms registered it |
| REG-02 | `all_action_ids()` after `import actions` | contains **every** `block_id` declared in `actions/*.py` (16 today, `COLLECT_HISTORY` included) |
| REG-03 | `get_action_class("NO_SUCH_BLOCK")` | `None`, never `KeyError` |
| REG-04 | `@register("TEST_ID")` on a class | decorator returns the *same* class, sets `cls.block_id`, id resolvable |
| REG-05 | `@register("")` applied to a class | `ValueError("register: block_id must be non-empty")` |
| REG-06 | duplicate: same id registered twice | last class wins; `all_action_ids()` lists the id **once** |
| REG-07 | shadow: id already held by a real block re-registered | overwrite is *reported* (log warning) — a silent hijack of the palette is not acceptable |
| REG-08 | `discover()` called twice | 2nd call returns `0` (documented "newly discovered"), registry content unchanged, no exception |
| REG-09 | `discover("no_such_package")` | `0`, no raise (documented `ImportError` guard) |
| REG-10 | `discover()` module skip list | `actions.registry` / `actions.base_action` are never imported as blocks |
| REG-11 | a block module that raises on import | the *other* blocks still register **and** the failure is logged (a block must not vanish from the palette silently) |
| REG-12 | `ActionContext(cdp=…)` | `memory`/`criteria`/`engine` default `None`, `user_nick` defaults `""` |

*Design-target gap:* the plan asks for "clear". No `clear()` exists (the
registry is process-global and nothing outside tests needs to empty it), so
the tests save/restore `_REGISTRY` through a fixture instead of a public
`clear()`. Recorded, not implemented.

## 2. `actions/base_action.py` — P0

| ID | Case | Expected path |
|---|---|---|
| BASE-01 | instantiate `BaseAction` directly | `TypeError` — `execute` is `@abstractmethod` |
| BASE-02 | subclass that does not implement `execute` | `TypeError` on instantiation |
| BASE-03 | `pre_delay_ms=0` → `await pre_delay()` | returns in < 20 ms (no sleep) |
| BASE-04 | `pre_delay_ms=120` | elapsed ≥ 0.115 s |
| BASE-05 | `enabled` positional `False` / kwarg `False` / `None` | `False` / `False` / `True` (`None` means "unset" → default on) |
| BASE-06 | unknown kwargs | kept in `.config`, re-emitted by `to_dict()` (legacy presets load) |
| BASE-07 | `to_dict()` | has `block_id`, `pre_delay_ms`, `enabled` and every public setting; no `config` key; no `_private` key |
| BASE-08 | round-trip `Cls(**(to_dict() - block_id)).to_dict()` | byte-identical to the first `to_dict()` |
| BASE-09 | `json.dumps(block.to_dict())` | serialises — `bridge/stack_bridge.get_stack_json()` does exactly this on the live stack |
| BASE-10 | `display_name` | `custom_name` when non-blank; `name` when blank/absent |
| BASE-11 | `config_schema()` | always contains `pre_delay_ms`; a subclass schema is a superset of the base one |
| BASE-12 | subclass with its own `block_id` | auto-registered by `__init_subclass__` |
| BASE-13 | subclass that only **inherits** a `block_id` | must **not** re-register (and thus silently replace) the parent class |
| BASE-14 | `ActionResult.OK/FAIL/SKIP` | three distinct strings |
| BASE-15 | `execute(user_nick, cdp, engine=None)` | the documented 3-argument call shape works on a concrete block |

## 3. `actions/type_message.py` — P1 (payload / inject / failure)

| ID | Case | Expected path |
|---|---|---|
| TYPE-01 | defaults | `message=""`, `use_composer=False`, `typing_speed_ms=30`, `pre_delay_ms=500` |
| TYPE-02 | composer off, injector `True` | injector receives `self.message` + speed; `OK` |
| TYPE-03 | injector `False` | `FAIL` |
| TYPE-04 | `{{nick}}` + `engine.selected_nick="Ann"` | typed text `Hi Ann` |
| TYPE-05 | `{{nick}}` + engine with empty `selected_nick` | falls back to the queued `user_nick` |
| TYPE-06 | `{{nick}}` twice | both occurrences replaced |
| TYPE-07 | composer on, composer text non-empty | composer text typed, own `message` ignored |
| TYPE-08 | composer on, composer empty/whitespace/`None` | `FAIL`, injector **not** called, one `warn` line |
| TYPE-09 | composer on, `engine=None` | `FAIL`, no crash |
| TYPE-10 | `pre_delay_ms=0` | execute returns without the 500 ms default |
| TYPE-11 | `report` | the engine's `report` is handed to the injector |
| TYPE-12 | `config_schema()` | `use_composer` + `message` + `typing_speed_ms` **and** inherited `pre_delay_ms` |

## 4. `actions/wait_page.py` — P1 (timeout / met / never met)

| ID | Case | Expected path |
|---|---|---|
| WAIT-01 | probe answers `found:true` at once | `OK`, exactly **1** `cdp.evaluate` call, success line reported |
| WAIT-02 | never found, `timeout_ms=300` | `FAIL`, elapsed in [0.30, 1.20] s (honours the deadline, no runaway) |
| WAIT-03 | found on the 2nd probe | `OK`, 2 evaluate calls |
| WAIT-04 | probe raises every time | `FAIL` (not a crash), one `error` line on attempt 1 |
| WAIT-05 | probe returns `""` / `None` | treated as "not found" → timeout `FAIL` |
| WAIT-06 | probe returns malformed JSON | "not found", no `JSONDecodeError` escaping |
| WAIT-07 | `target_selector=""` | falls back to the documented `TEXTAREA_SEL` |
| WAIT-08 | `timeout_ms=0`, element absent | `FAIL` after a single probe (no sleep loop) |
| WAIT-09 | reporting | start line (`info`), throttled "not present yet" (`warn`), final "Failed to find … timeout after N ms" (`error`) |
| WAIT-10 | `found:false, total:3` | the not-found line names the matched node count |
| WAIT-11 | `engine=None` | same `OK`/`FAIL`, no crash |

## 5. `actions/pause.py` — P2 (resume / cancel)

| ID | Case | Expected path |
|---|---|---|
| PAU-01 | `duration_ms=0` | `OK` in < 20 ms |
| PAU-02 | `duration_ms=150` | `OK`, elapsed ≥ 0.145 s |
| PAU-03 | reporting | "Pausing for N ms" then "Pause finished" |
| PAU-04 | `pre_delay_ms=999` passed in | dropped — `to_dict()["pre_delay_ms"] == 0` ("pause manages its own delay") |
| PAU-05 | `config_schema()` | describes `duration_ms` |
| PAU-06 | `duration_ms="250"` (string — what a JSON/Qt preset can deliver for a `number` field) | still pauses; **no `TypeError`** — every sibling block coerces with `int()` |
| PAU-07 | negative `duration_ms` | `OK`, no crash |

## 6. `actions/search_users.py` — P1 (filter / empty / partial)

| ID | Case | Expected path |
|---|---|---|
| SU-01 | plain text, `type_search` → `True` | text reaches `type_search` unchanged, `OK` |
| SU-02 | `type_search` → `False` | `FAIL` |
| SU-03 | text contains `{{nick}}` | expanded to `engine.selected_nick`, else the queued `user_nick` — the block's own schema label promises it |
| SU-04 | reporting | `engine.report` forwarded to the injector |
| SU-05 | `pre_delay_ms=0` | no 500 ms default sleep |
| SU-06 | empty text | still delegated (the injector owns the empty-text warning) |

## 7. `actions/custom_find.py` — P2 (find rules / fallback)

| ID | Case | Expected path |
|---|---|---|
| CF-01 | delegation | `find_and_click` gets `match_mode=MATCH_CONTAINS` + all nine settings |
| CF-02 | `click_enabled=False` | forwarded (find without clicking) |
| CF-03 | `_label()` | `element 'X'` / `+ text inside 'Y'` / `+ matching "Z"` as configured |
| CF-04 | negative `confirm_pause_ms` / `highlight_ms` | clamped to `0` |
| CF-05 | `{{nick}}` in `match_text` | expanded — the block's own schema label promises it |
| CF-06 | `custom_name` | drives `display_name` |
| CF-07 | runner returns `FAIL` | `FAIL` passed through unchanged |

## 8. `actions/click_user.py` — P1 (order / memory / find / not-found)

| ID | Case | Expected path |
|---|---|---|
| CU-01 | runner does not return `OK` | that outcome is returned, no tab probe, nick **not** remembered |
| CU-02 | `verify_new_tab=False` | `OK` after one runner call, no tab probe at all, nick remembered |
| CU-03 | tab count grows 1 → 2 | `OK`, success line says `tab count 1 → 2` |
| CU-04 | count unchanged but a tab title contains the nick | `OK` ("a tab titled … is open") |
| CU-05 | count unchanged, no title match | `FAIL` + `error` line naming the open titles |
| CU-06 | tab probe returns malformed JSON | treated as unreadable → "assuming the click worked" → `OK` |
| CU-07 | probe raises before the click, valid after | no crash, still `OK` |
| CU-08 | `use_person_from_memory` + `engine=None` | `FAIL`, runner never called |
| CU-09 | `use_person_from_memory` + empty `selected_nick` | `FAIL` with the "add a Pick Person block" hint |
| CU-10 | `use_person_from_memory` + `selected_nick="Ann"` | the runner is asked for **Ann**, not the queued user |
| CU-11 | `build_tab_count_js` | both selectors embedded JSON-escaped (a `"` in a selector cannot break out of the JS string) |
| CU-12 | `tab_pause_ms=0` | no sleep between click and the after-probe |

## 9. `actions/scroll_parse.py` — P1 (delta / corrupt / max-depth)

| ID | Case | Expected path |
|---|---|---|
| SP-01 | `build_filter(panel_criteria=obj)` | the four block rules only, `panel_criteria` **ignored** (documented) |
| SP-02 | invalid filter value | `normalize()` falls back to the documented default |
| SP-03 | `build_parser` | `criteria` always `None`; scroll knobs forwarded verbatim |
| SP-04 | `purge_rejected` | `True` → parser `on_reject` forwarded; `False` → `None` (nothing destroyed) |
| SP-05 | retired keys (`use_panel_filters`, `skip_if_backlog`, `backlog_threshold`) | accepted, dropped from attributes **and** from `to_dict()` |
| SP-06 | `min_new_users=-3` | clamped to `0` |
| SP-07 | `_read_unmessaged` | engine `None` → `set()`; no reader → `set()`; reader raises → `set()` (**fails open**); list → `set` |
| SP-08 | `scroll_only` + engine reader returns nicks | parser receives exactly those `seek_nicks`, warn line names the count |
| SP-09 | `scroll_only` + empty backlog | `seek_nicks=None` + "collecting new people as usual" |
| SP-10 | `scroll_only=False` | `seek_nicks` forced to `None` even when passed explicitly |
| SP-11 | engine hooks | `person_collected` / `person_rejected` / `is_stopping` preferred over `None` |
| SP-12 | `execute` mapping | collected → `OK`; nothing collected → `FAIL` + warn; seeking with nothing → `FAIL` |
| SP-13 | `to_dict()` **after a run** | still JSON-serialisable — `bridge/stack_bridge.get_stack_json()` snapshots the live stack |
| SP-14 | explicit `seek_nicks` argument | used as-is, engine reader not consulted |

## 10. `actions/collect_history.py` — P1 (empty / duplicate / block match)

CH-00 is the gate: the block cannot be imported while
`backend.chat_parser` fails to import (§12 BUG-02).

| ID | Case | Expected path |
|---|---|---|
| CH-00 | `import backend.chat_parser` | imports cleanly |
| CH-01 | no `engine.history` | `FAIL` + "archive service is not available" |
| CH-02 | `service.enabled` false | `FAIL` + "archive is disabled" |
| CH-03 | service without `repo`/`parser` | `FAIL` + "incomplete" |
| CH-04 | `require_private` + tab ≠ private | `FAIL` + "not a private chat" (RULE 4: loud) |
| CH-05 | `require_private=False` + main tab | proceeds |
| CH-06 | no partner resolved | `FAIL` + "could not tell who this conversation is with" |
| CH-07 | `target=memory_nick`, no `selected_nick` | `FAIL` + "add a Pick Person" |
| CH-08 | `target=memory_nick`, nick ≠ partner | `FAIL` + "nick mismatch … nothing was written" |
| CH-09 | `target=memory_nick`, nick == partner (case/whitespace) | proceeds with `verify_partner=True` |
| CH-10 | agent not installed | `parser.install()` called, state re-read |
| CH-11 | `mode=full` | `repo.reset_cursor(nick)` called |
| CH-12 | ok + `added>0` | `OK` + "Archived N new message(s)" |
| CH-13 | ok + `added=0`, `fail_if_empty=False` | **`OK`** + "No new messages" (RULE 4: quiet) |
| CH-14 | ok + `added=0`, `fail_if_empty=True` | `FAIL` |
| CH-15 | `result.stopped` | **`OK`** + "stopped on request" (RULE 7: never a failure) |
| CH-16 | not-ok reasons `not_private` / `partner_mismatch` / other | `FAIL` with three *distinct* messages (RULE 4) |
| CH-17 | chunk settings | pushed onto the parser before syncing |
| CH-18 | `download_media` | `True` → `media=repo.media`; `False` → `media=None` |
| CH-19 | `media.process_pending()` raises | swallowed, run still `OK` |
| CH-20 | progress | one report per chunk (RULE 5) |
| CH-21 | `my_nick` | service value wins, else the parser state's `me` |

## 11. `actions/attach_image.py` — P1 (missing file / corrupt / success)

`tests/test_attach_image.py` already covers the media pipeline (formats,
active-chat scoping, dialog, read-back, verification). The uncovered
contract is the **block's own plumbing**: nine positional arguments, so a
reorder silently swaps a timeout for a boolean.

| ID | Case | Expected path |
|---|---|---|
| AI-01 | delegation | `attach_image()` receives, in order: folder, pattern, rotation, simulate_dialog, verify_timeout_ms, highlight_enabled, confirm_pause_ms, report |
| AI-02 | defaults | pattern = `DEFAULT_FILE_PATTERN`, sequential, simulate on, verify 8000, highlight on, confirm 700 |
| AI-03 | `file_pattern=""` | replaced by `DEFAULT_FILE_PATTERN` |
| AI-04 | negative / `None` `verify_timeout_ms` and `confirm_pause_ms` | clamped to `0` |
| AI-05 | handler `True` / `False` | `OK` / `FAIL` |
| AI-06 | `report` | `engine.report` forwarded, `None` without an engine |
| AI-07 | `to_dict()` round-trip | every setting survives, JSON-safe |

---

## 12. Bug ledger (what the spec-first pass actually found)

Status: **FIXED** = repaired in this change and pinned by a test;
**OPEN** = reported, deliberately not repaired here.

| ID | Sev | Status | Module | Finding | Evidence |
|---|---|---|---|---|---|
| BUG-01 | **P0** | **FIXED** | `actions/registry.py`, `actions/__init__.py` | **Two registries.** `registry._REGISTRY` was filled only by `@register`, which **no** module uses; the live registry is `base_action._REGISTRY`, filled by `__init_subclass__`. The package re-exported the *empty* one, so `actions.all_action_ids()` → `[]` and `actions.get_action_class("PAUSE")` → `None` while 15 blocks were really registered. Fixed by moving `register` / `get_action_class` / `all_action_ids` next to the hook (one dict, two documented doors) and re-exporting them. | before: `python3 -c "import actions; print(actions.all_action_ids())"` → `[]`; after → 15 ids. REG-01/REG-02 |
| BUG-02 | **P0** | **OPEN** | `backend/history_db_parts/helpers.py` (blocks `actions/collect_history.py`) | `TABLE_ORDER` / `TABLE_COLUMNS` / `TABLE_CONSTRAINTS` are used at import time but **defined nowhere in the repo** → `NameError` on `import backend.history_db`. So `actions/collect_history.py` cannot be imported, `COLLECT_HISTORY` never registers, and **19 test modules** die at collection. Not repaired here: the canonical column declarations cannot be recovered from the repo, and inventing them risks corrupting user archives. | `git grep TABLE_ORDER` → 4 uses, 0 definitions; `pytest tests/` → `19 errors`, identical at HEAD and here |
| BUG-03 | P1 | **FIXED** | `actions/__init__.py`, `registry.discover()` | One `from actions import (…16 names…)` inside a single `try/except Exception: pass` — **one** broken module killed all 16 legacy imports, and `discover()`'s `except Exception: continue` hid every import failure. A block disappeared from the app with nothing logged (this is how BUG-02 stayed invisible). Now: `discover()` imports module-by-module and logs a warning per failure. | before: silence; after: `Action module actions.collect_history failed to import - its block(s) are unavailable: name 'TABLE_ORDER' is not defined`. REG-11 |
| BUG-04 | P1 | **FIXED** | `search_users.py`, `custom_find.py`, `click_back.py`, `click_main_tab.py` | `config_schema` advertised **"{{nick}} = selected user"** but only `type_message.py` expanded it. Typing `Привет {{nick}}` into *Search Users* searched for the literal string `{{nick}}`. Fixed with one shared `base_action.resolve_nick()` used by all five blocks. | `git grep '{{nick}}'` → expansion only at `type_message.py:49`. SU-03, CF-05, `test_click_tab_blocks.py` |
| BUG-05 | P1 | **FIXED** | `actions/scroll_parse.py` | `run_pipeline` stored a `CollectResult` on the public attribute `last_result`; `to_dict()` serialises every public attribute and `bridge/stack_bridge.get_stack_json()` does `json.dumps(...)`, so after **any** run the stack snapshot raised `TypeError: Object of type CollectResult is not JSON serializable`. Now `_last_result` + a read-only property: runtime state is not a setting. | mutation check: reverting `actions/scroll_parse.py` to HEAD makes SP-13 fail with `'last_result' unexpectedly found in {... 'last_result': CollectResult(...)}` |
| BUG-06 | P2 | **FIXED** | `actions/pause.py` | `duration_ms` was never coerced: `Pause(duration_ms="1500")` (a `"number"` field arriving as a string from a preset) ended the run with `TypeError: unsupported operand type(s) for /: 'str' and 'float'`; `None` did the same. Every sibling block coerces. | PAU-06, `test_none_duration_is_treated_as_zero` |
| BUG-07 | P2 | **FIXED** | `actions/base_action.py` | `__init_subclass__` registered on *inherited* `block_id` too, so any subclass silently replaced its parent in the palette. Now only a class that **declares** an id registers. | BASE-13 |
| BUG-08 | P2 | **FIXED** | `actions/wait_page.py` | A probe payload that parsed to a non-object (`json.loads("[1,2,3]")`) crashed the wait with `AttributeError: 'list' object has no attribute 'get'` instead of counting as "no data". `click_user._read_tabs` already applied this `isinstance(res, dict)` guard. | WAIT-06, `test_a_non_dict_json_payload_does_not_escape` |
| BUG-09 | P2 | **FIXED** | `actions/click_user.py` | "Use Person from Memory" treated a whitespace-only `selected_nick` as a real nick (`"   " or ""` → `"   "`), so the block searched for a blank person instead of failing loudly as its own docstring requires ("Never click blindly"). | `test_a_whitespace_only_memory_is_treated_as_empty` |
| BUG-10 | P1 | **OPEN** (out of section B) | `bridge/router.py` | `Router(QObject, GridMixin)` never aggregates the domain bridges its own docstring promises — `save_grid_layout` lives in `bridge/layout_bridge.py`, `label_create` in `bridge/label_bridge.py`, `save_message` in `stack_bridge.py` and none are mixed in. This is the cause of **all 58 pre-existing test failures** (`test_grid_persistence` 19, `test_person_labels` 14, `test_live_status_and_order` 10, `test_people_undo` 8, `test_grid_layout_v2_migration` 4, `test_merge_undo_enabled` 2, `test_message_block_composer` 1) — the same "lost in the <150-LOC split" family as BUG-02. | `AttributeError: 'Router' object has no attribute 'save_grid_layout'` |
| NOTE-01 | — | — | coverage table | The plan lists `actions/base.py` (160 LOC / 12 fn). **No such file exists**; the base is `actions/base_action.py`. Line/function counts for `registry.py` (83/5, not 110/10) and `custom_find.py` (109, not 140) are also stale. | `wc -l actions/*.py` |
| NOTE-02 | — | — | `registry.py` | The design target asks for "clear"; there is no `clear()`. The tests save/restore `_REGISTRY` in a fixture instead of adding a public API that could empty the live palette. | `registry.py` |
| NOTE-03 | — | — | `base_action.py:62-65` | The `if "enabled" in kwargs` / `if "pre_delay_ms" in kwargs` defensive branches are **unreachable**: `BaseAction.__init__` declares both as named parameters, so a caller can never leave them in `**kwargs`. Harmless, but they are the last 2 uncovered statements in the module. | coverage `Missing 63, 65` |

---

## 13. Results

Suite: `python3 -m pytest tests/ --continue-on-collection-errors --cov=actions`
(19 modules still cannot be collected — BUG-02, identical at HEAD).

| | HEAD (`d8d0e09`) | this branch |
|---|---|---|
| passed | 390 | **637** (+247) |
| failed | 58 | **58** (identical set — `comm` on the FAILED lists is empty both ways) |
| xfailed | 0 | 2 (REG-02 and CH-00, both pinned to BUG-02) |
| collection errors | 19 | 19 (BUG-02) |

New tests: **249** across 12 files. On first run 12 of them failed; every one
was a real defect (BUG-01/03/04/05/06/07/08/09) — none was softened to match
the code.

### `actions/` coverage, before → after

| Module | Before | After |
|---|---|---|
| `registry.py` | 71 % | **94 %** |
| `base_action.py` | 93 % | **97 %** |
| `wait_page.py` | **28 %** | **100 %** |
| `pause.py` | 67 % | **100 %** |
| `collect_history.py` | **7 %** | **100 %** |
| `attach_image.py` | 88 % | **100 %** |
| `click_user.py` | 89 % | **100 %** |
| `scroll_parse.py` | 96 % | **100 %** |
| `type_message.py` | 100 % | 100 % |
| `search_users.py` | 100 % | 100 % |
| `custom_find.py` | 100 % | 100 % |
| `click_back.py` / `click_main_tab.py` | 93 % | **100 %** |
| `click_send.py` *(not in section B)* | 41 % | 57 % |
| **`actions/` total** | **60 %** | **68 %** |

Remaining gaps in section B: `registry.py:80-81` (the `except: pass` around
the import-time auto-scan), `base_action.py:63,65` (unreachable branch,
NOTE-03), and `click_send.py` — the one block in the package with no
dedicated test file, and the obvious next target.

### Files

| Test file | Cases | Covers |
|---|---|---|
| `tests/test_action_registry.py` | 15 | REG-01 … REG-13 |
| `tests/test_base_action_contract.py` | 25 | BASE-01 … BASE-15 |
| `tests/test_type_message_block.py` | 21 | TYPE-01 … TYPE-12 |
| `tests/test_wait_page_block.py` | 17 | WAIT-01 … WAIT-11 |
| `tests/test_pause_block.py` | 11 | PAU-01 … PAU-07 |
| `tests/test_search_users_contract.py` | 14 | SU-01 … SU-06 |
| `tests/test_custom_find_block.py` | 17 | CF-01 … CF-07 |
| `tests/test_attach_image_block_plumbing.py` | 14 | AI-01 … AI-07 |
| `tests/test_click_user_tab_verify.py` | 24 | CU-01 … CU-12 |
| `tests/test_scroll_parse_contract.py` | 34 | SP-01 … SP-14 |
| `tests/test_collect_history_contract.py` | 42 | CH-00 … CH-21 |
| `tests/test_click_tab_blocks.py` | 15 | BUG-04 group (click_back / click_main_tab) |

### Source changes

| File | Change |
|---|---|
| `actions/base_action.py` | one registry + `register()` / `_register_class()` (warns on a collision); `__init_subclass__` registers only declared ids; new `resolve_nick()` |
| `actions/registry.py` | re-exports the shared registry; `discover()` logs import failures |
| `actions/__init__.py` | dropped the all-or-nothing import block and the redundant second `discover()` |
| `actions/type_message.py` | uses `resolve_nick()` (same behaviour, one source of truth) |
| `actions/search_users.py`, `custom_find.py`, `click_back.py`, `click_main_tab.py` | honour the `{{nick}}` their schema advertises |
| `actions/click_user.py` | a blank memory nick is "no nick" |
| `actions/scroll_parse.py` | `last_result` → `_last_result` + property |
| `actions/wait_page.py` | non-object probe payload counts as "no data" |
| `actions/pause.py` | `duration_ms` coerced and clamped |
