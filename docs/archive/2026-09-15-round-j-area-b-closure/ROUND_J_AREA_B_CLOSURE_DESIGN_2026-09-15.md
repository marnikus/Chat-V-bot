# Round J design — closing Area B: the eight criteria the rebuild left open

Date 2026-09-15 · branch `arena/01a0a1d3-chat-v-bot` · base `6e03a53` (Round H
Area B rebuild) · owns `backend/**/*.py` (except `backend/js/`) and `bridge/**/*.py`

**Status: PLAN, then implementation in the same session.** Every number below
was measured on this tree with the commands in *Reproduction* at the end.
Required by RULE 16 §16.6 step 2 and RULE 17.

## 1. What is still open, re-measured

Round H step H-B1 and H-B6 landed in `6e03a53`, and the search half of H-B2 with
them. Re-running the Area B design's own criteria against the tree
(`tools/metrics/current_audit.py`, `tools/metrics/rule16_gate.py`) leaves eight
open — every one of them a **criterion from
[`AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md`](../2026-09-14-round-h/AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md)**,
not a new wish:

| # | Criterion (source) | Target | Measured now | File |
|---|---|---|---:|---|
| 1 | H-B1 `Target: file ≤ 200 lines` | ≤ 200 | **241** | `bridge/history_bridge.py` |
| 2 | H-B2 `facade ≤ 350 lines` | ≤ 350 | **531** | `backend/history_query.py` |
| 3 | H-B2 `HistoryQuery ≤ 10 methods` | ≤ 10 | **14** | `backend/history_query.py` |
| 4 | H-B2 `MI ≥ 50` | ≥ 50 | **42.0** | `backend/history_query.py` |
| 5 | H-B3 `Target: ≤ 300 lines, ConfigManager ≤ 15 methods, coverage ≥ 90%` | all three | **511 · 20 · 85.8%** | `backend/config_manager.py` |
| 6 | H-B4 `Target: ≤ 300 lines of Python` + payload module | ≤ 300 | **514**, payloads embedded | `backend/dom_highlight.py` |
| 7 | H-B5 (router) — 8-param constructor → parameter object | ≤ 4 params | **8** | `bridge/router.py` (486) |
| 8 | H-B5 (media_handler, chat_parser) — payload module, dialog vs attachment, parsing vs settle policy | split by responsibility | **474 / 426, unsplit** | `backend/media_handler.py`, `backend/chat_parser.py` |
| 9 | H-B6 `CDPClient ≤ 15 methods` | ≤ 15 | **20** | `backend/cdp_client.py` |

The area's own floor is unfinished with them: **8 files in `backend/` +
`bridge/` sit below the round's MI ≥ 45 goal and 8 are over RULE 18.2's 300-line
band** (four of them over 400):

| LOC | MI | File | | LOC | MI | File |
|---:|---:|---|---|---:|---:|---|
| 531 | 42.0 | `backend/history_query.py` | | 333 | 39.7 | `bridge/stack_bridge_parts.py` |
| 514 | 54.9 | `backend/dom_highlight.py` | | 332 | 37.5 | `bridge/file_bridge.py` |
| 511 | 40.9 | `backend/config_manager.py` | | 297 | 40.9 | `backend/chat_sync_session.py` |
| 486 | 44.2 | `bridge/router.py` | | 193 | 40.9 | `bridge/window_preset_bridge.py` |
| 474 | 46.1 | `backend/media_handler.py` | | | | |
| 426 | 40.9 | `backend/chat_parser.py` | | | | |

## 2. Three findings that decide *how* each step is done

**(a) The API snapshot has an explicit inherited-method allowance, so criterion 9
is reachable without shrinking the frozen API.** `tools/metrics/dump_public_api.py
::_class_drift` says it in its own docstring: *"A member that moved UP into a
shared base is not a lost symbol: the class still answers to it with the same
signature, from `inherited`. A base class may gain parents as long as every
recorded one is still an ancestor."* So the CDP command surface moves into a
`WireCommands` base in `backend/cdp_client_transport.py`: the names stay callable
on `CDPClient`, the signatures stay byte-identical in the snapshot, and the class
body defines only what is genuinely the façade's. This is *not* the
metric-dodging §16.2 forbids (an assignment of functions into a namespace to hide
them from an AST walk): the methods become real inherited API, which is why the
dumper models it as a first-class case.

**(b) `bridge/router.py` has no class in its AST.** `Router` is assembled at
import time with `type(QObject)` (Shiboken's metaclass) from the eleven domain
bridges, so the gate's class rules never see it and the file's 486 lines are
three responsibilities stacked in one module: the assembly machinery (~190
lines), the hand-written Router surface (~180), and the legacy undo/history
shims the test suite is the contract for (~120). Splitting it is a move of whole
functions plus the constructor change the design asks for — no behaviour edit.

**(c) `_my_nicks` mutant 7 is an equivalent mutant, and H-B2b removes it from the
mutation job's reach entirely.** Round I's `tests/test_history_query_gaps.py`
records the measurement (`json.loads(v or "[]")` vs `json.loads(v or "XX[]XX")`
cannot be told apart by any input) and pins both paths. H-B2b moves the function
into the rows module, which is outside `setup.cfg`'s `source_paths` for the
mutation job — so the mutant is not "closed by a test", it stops being
generated, and the equivalence argument stays in the suite where it was
measured. That is recorded here because the Area B design's wording ("close
mutant 7 with a test that fails on the mutant") predates the measurement.

## 3. The steps

Each step is one commit, each re-measures itself, and the files a step owns are
listed before it starts (the round's disjoint-ownership rule).

### J-1 — `bridge/history_bridge.py` 241 → ≤ 200 (criterion 1)

Move the two module-level helpers off the wire façade and into the parts that
use them: `_person_request` (16 lines, read) → `history_bridge_read.py`;
`_qt_clipboard` / `_copy_file_to` (25 lines, media) → `history_bridge_media.py`.
The seven signals and the twenty-one `@Slot`s stay; the seven-line import window
that is a clone-baseline pair with `db_bridge.py` stays byte-identical (its
`tests/test_rule16_new_code.py` pin is what makes that non-negotiable), and the
`OWNED` row for `_person_request` follows the function to its new file in the
same commit (RULE 16 §16.6's "edit the rows in the commit that renames them").

### J-2 — `backend/history_query.py` 531 → ≤ 350, `HistoryQuery` 14 → 10 methods, MI ≥ 50 (criteria 2–4)

New `backend/history_query_rows.py`: the row → payload projection
(`_person_item`, `_apply_specs`, `_item_media`, `_stat_int`, `_day_bounds`) plus
the four helpers that exist only to serve it (`_clamp`, `_my_nicks`,
`_person_row`, `_item`). The façade keeps `PersonPageRequest` and `HistoryQuery`
with exactly ten methods: `__init__`, `page`, `around`, `gaps`, `search_person`,
`search_global`, `_search`, `list_persons`, `db_stats`, `person_stats`.

Interfaces that may not change shape (Area B §6): `HistoryQuery`'s public method
signatures and `PersonPageRequest`'s six pinned properties. `_person_item` and
the other private helpers are exempt from the snapshot (the dumper skips
`_`-prefixed names), which is what makes the move invisible to it — and their
test (`tests/test_person_item.py`) is updated in the same commit, not left
importing a name that no longer exists.

With the class at 10 methods and ~95 LOC the `RATCHET` row for
`HistoryQuery` (266/14) is **deleted rather than lowered**: the class is inside
`CLASS_LIMITS` (150/15) on its own and the gate's per-file class loop then
enforces it without an exemption.

### J-3 — `backend/config_manager.py` 511 → ≤ 300, `ConfigManager` ≤ 15 methods, coverage ≥ 90% (criterion 5)

Three responsibilities, three files:

* `backend/config_defaults.py` — `DEFAULTS`, `MAX_STACK_HISTORY`,
  `_SECTION_ROUTES`, `_UNDO_STATE_KEYS`, `_deep_merge`, `_set_nested`,
  `json_dumps`: the shipped tree and the two pure tree helpers. Public names
  (`DEFAULTS`, `MAX_STACK_HISTORY`, `json_dumps`) are re-exported from
  `backend.config_manager` so every existing importer and the snapshot keep
  working;
* `backend/config_owners.py` — the `_Owner` family (dispatch, per-store quirks,
  named-thing verbs): the part the façade currently hosts 170 lines of;
* `backend/config_manager.py` — `ConfigManager` itself: `load`, `save`, the
  get/set/get_copy/set_state surface, `validate`, delegating state traffic to
  `config_state.py` (`state_data`, `get_state`, `set_state`, `_state_default` as
  functions over the manager).

Coverage: the 85.8% baseline's gaps are the migration/repair branches
(`_repair_path`, the legacy-import path, `named_*` errors). J-3 adds the missing
cases as tests *before* the move, so the 90% floor is measured on behaviour that
was verified, not on lines that merely execute.

### J-4 — `backend/dom_highlight.py` 514 → ≤ 300 of Python + a payload module (criterion 6)

`backend/dom_highlight_js.py` takes the five JS payloads and the three
`_splice`-time fragments (`_HELPERS_JS` 69, the `_empty_diagnostic` body 8,
`_PROBE_JS` 12, `_QUERY_VARS` 6, `_LABEL_JS` 8, `_MATCH_JS` 6, the two spliced
bodies `_FIND_BODY` 35 / `_HIGHLIGHT_BODY` 21, and `_CLICK_BODY` 62) as
module-level constants, and carries the `ideal-size:` note RULE 16 §16.1.5
requires for a literal it hosts. The Python side keeps every builder signature
and the CC/nesting budget it has today.

### J-5 — `bridge/router.py` 486 → assembly + surface + legacy; constructor → parameter object (criterion 7)

* `bridge/router_assembly.py` — the machinery: `_QT_TYPES`, `_py_type`,
  `_qt_text`, `_meta_members`, `_make_forwarder`, `BRIDGE_SPECS`,
  `_register_signals`, `_register_slots`, `_register_legacy_attrs`,
  `_build_router_class`, `_router_method`, `_ROUTER_METHODS`, `BRIDGE_CLASSES`.
* `bridge/router_legacy.py` — the historical shims (`_get_hist` / `_set_hist` /
  `_push_hist`, the three undo projection pairs, `_people_rows`,
  `_push_people_entry`, `_labels_for_nicks`, `_install_label_guard`, the
  `_do_*` queue helpers), registered through the same decorator.
* `bridge/router.py` — the live surface: `__init__`, `_ensure_ctx`, `_bridge`,
  the context write-through properties, `attach_history`, `sync_world_state`,
  `announce_world_ready`, and the `Router = _build_router_class()` line.

`__init__` becomes `(self, ctx=None, parent=None, **legacy)`: `ctx` is the
`BridgeContext` G4 introduced — the parameter object the design names, not a new
one — and the eight historical keywords are absorbed and folded into that
context, so `Bridge(cdp=…)` in `app/bootstrap.py` and every test keep working.
`PresetStore(config=…)` synthesis and the one-time legacy import stay unchanged.
The `quality-override: params=8` marker goes away with the parameter list.

### J-6 — `backend/media_handler.py` 474 → payload module + dialog/attachment split (criterion 8)

* `backend/media_handler_js.py` — `CTX_PROBE_JS` (53 lines) and the two
  readback builders (`_count_messages_js`, `_readback_js`).
* `backend/media_dialog.py` — driving the composer's attachment dialog:
  `_open_dialog`, `_probe_file_input`, `_inject_file`, `_readback_count`,
  `_verify_sent`.
* `backend/media_handler.py` — folder/pattern policy (`parse_patterns`,
  `_glob_for`, `list_image_files`, `_scan_folder`), the target-context probe,
  `AttachOptions`, `_AttachState`, `_AttachRefused`, and the two orchestrators
  `attach_with_options` / `attach_image` that call the dialog module.

### J-7 — `backend/chat_parser.py` 426 → parsing / gate / settle policy (criterion 8)

`ChatParser`'s LCOM is 0.94 — the fields are shared by two jobs that share a
class. Split:

* `backend/chat_parser_gate.py` — the private-chat verdict: `PrivateCheck`,
  `_GateNames`, `title_matches`, `_is_self_chat`, `_split_authors`,
  `_authors_of`, `_foreign_authors`, `verify_private` and its three gates;
* `backend/chat_parser_settle.py` — the timing policy: `settle_after_top`,
  `_poll_snapshot`, `_settle_exit`;
* `backend/chat_parser.py` — `parse_records` / `align` and `ChatParser`'s DOM
  surface (`state`, `install`, `ensure_agent`, `slice`, `drain`,
  `scroll_to_top`, `restore_scroll`, `pause`).

`verify_private` is imported by `services/` and the collector — its signature is
part of the module's effective API, so it keeps its name and is re-exported from
`backend.chat_parser` (the pattern the CDP split already uses: leaves may be
imported from their new home, the historical module keeps answering).

### J-8 — `backend/cdp_client.py`: `CDPClient` 20 → 11 methods (criterion 9)

Per finding (a): the nine command verbs (`add_binding`,
`add_script_on_new_document`, `remove_script_on_new_document`, `evaluate`,
`get_cookies`, `click_at`, `mouse_wheel`, `get_element_rect`,
`set_file_input_files`) move into `class WireCommands` in
`backend/cdp_client_transport.py`; `CDPClient(QObject, WireCommands)` inherits
them. The façade keeps `__init__`, the two `_event` verbs + `_dispatch_event`,
the three lifecycle verbs (`connect`, `disconnect`, `send`), `_receive_loop`,
and the two properties — eleven ≤ fifteen. `cdp.send` shadowing, `cdp._ws` and
`cdp._connected` assignment all still work (instance attributes beat inherited
methods), which is what the two pinned test files exercise.

### J-9 — close the area: floor, gates, snapshot, docs

* MI: `history_query` ≥ 50 (J-2), `config_manager` ≥ 45 (J-3), `router` ≥ 45
  (J-5), `chat_parser` ≥ 45 (J-7); every file in `backend/` + `bridge/` ≤ 300
  lines; **zero files over 500 anywhere**.
* Gates: `rule16_gate.py --with-clones` green with the `OWNED` / `RATCHET` /
  `SMELL_FILES` rows edited in the commit that moved the code; the API snapshot
  regenerated **additively** (new modules only, plus `CDPClient`'s methods
  moving to `inherited` — the one entry finding (a) sanctions) with the diff
  printed in the commit message; the I-1.3 sleep ratchet unchanged (every new
  test is a yield-point test, never `sleep(0.0N)`).
* Coverage: the full suite under `--branch`, reported per touched file, with
  `config_manager` at ≥ 90% and no touched file below its pre-round number.
* Docs: `docs/current/SYSTEM_OF_RECORD.md` §6 layer rows, `docs/current/
  AGENT_RULES.md` §18.2/§18.3 measurements, `docs/README.md` and
  `docs/archive/README.md` indexes, and the *as-built* half of this document.

## 4. What this round deliberately does not do

* `bridge/stack_bridge_parts.py` (333 / 39.7), `bridge/file_bridge.py`
  (332 / 37.5), `backend/chat_sync_session.py` (297 / 40.9) and
  `bridge/window_preset_bridge.py` (193 / 40.9) are below the MI floor but are
  not 500-line or criteria offenders: they are Round K's, and the MI floor stays
  recorded as open rather than quietly re-scoped here.
* The JavaScript frontend (Area A) and the verification platform (Area D) stay
  untouched — they belong to their own areas.
* No public symbol is removed anywhere. Where a criterion and the snapshot's
  freeze touched (criterion 9), the snapshot's own inherited-method rule is what
  resolves it; the fallback would have been to record the target as unreachable,
  not to lift the freeze.

## 5. Definition of done

Every row of §1's table met *or* recorded with the measured reason it is not;
full suite green; `rule16_gate.py --with-clones`, `stores_modules.py`,
`dump_public_api.py --diff` green; coverage floors reported; the docs of §J-9
current; one commit per step plus the closing commit; pushed to
`arena/01a0a1d3-chat-v-bot`.

## Reproduction (evidence for every number in §1 and §3)

```bash
cd /home/user/Chat-V-bot
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q -p no:randomly \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_j.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python tools/metrics/dump_public_api.py --diff
COVERAGE_FILE=/tmp/.coverage_j .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q
COVERAGE_FILE=/tmp/.coverage_j .venv/bin/python -m coverage json -o /tmp/coverage_j.json
```
