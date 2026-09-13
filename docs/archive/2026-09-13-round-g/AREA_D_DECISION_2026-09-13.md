# G0 — the AREA D snapshot decision

**Date:** 2026-09-13 · **Step:** Round G / G0 · **Status:** decided and implemented
**Decision: option B — teach the dumper package-awareness.**
**Plan:** `ROUND_G_PLAN_2026-09-13.md` · **Measurements:** `reports/CODE_QUALITY_METRICS_2026-09-13.md`

## 1. Understand the problem

`tests/unit/backend/test_backend_api_snapshot.py` enforces
`backend_api_snapshot.json` over `backend/**` and `actions/**`. Its stated
contract is asymmetric and correct: **adding** public symbols is allowed,
**changing or removing** them fails.

Two implementation details of `tools/metrics/dump_public_api.py` went beyond
that contract without anyone deciding they should:

| Line | Code | Accidental consequence |
|---|---|---|
| `module_names()` | `if info.ispkg: continue` | packages are skipped entirely, so `backend/chat_sync.py` → `backend/chat_sync/` makes the qualname **disappear** → `test_no_module_disappeared_or_failed_to_import` fails |
| `dump_module()` | `owner == qualname` | a symbol re-exported from a sibling submodule is **not owned**, so moving `SyncSession` one file down reads as *removed* |

Neither is the guarantee. The guarantee is "no public symbol vanished or
changed shape". Both are artefacts of *how* the dump enumerates.

The cost is concrete and was measured: **5 of the 7 files over 500 lines live
in `backend/`**, including `chat_sync.py` at 807 lines and MI **11.4** — half
the next-worst file in the repo and a sixth of the project mean. The
prefix-family recipe that successfully fixed `stores/history_repo*` and
`services/db_deletion*` was unavailable in precisely the area that needed it
most. That is why `stores/` and `services/` are tidy and `backend/` is not: not
because anyone judged those files acceptable, but because the tooling forbade
the fix.

## 2. Research and design — the three options

### Option A — refresh the snapshot whenever a split needs it
Cheapest. But the golden file's value is that a diff means something; refreshing
it on demand trains everyone to refresh it on demand. Each use weakens the next.
**Rejected** — it trades a permanent guarantee for a one-off convenience.

### Option B — make the dumper package-aware *(chosen)*
Two changes, each narrow:

1. **`module_names()` walks into packages** and yields both the package
   qualname and its submodules. `backend.chat_sync` therefore stays a key in
   the snapshot after the split, and is checked against the package's
   `__init__`.
2. **`owns(owner, qualname)` replaces `owner == qualname`**: true on exact
   match, or when `owner` is a *submodule* of `qualname`. A package that
   re-exports `SyncSession` from `backend.chat_sync.session` still owns it —
   the symbol moved down inside the area, not away from it.

What this deliberately does **not** loosen: a re-export from a *different* area
(`from services.x import Y`) is still disowned, so cross-area leakage still
fails. A deleted symbol still vanishes from the dump. A deleted module still
disappears. The guarantee is untouched; only the false ban on splitting dies.

**The falsifiable claim, and how it was checked:** if option B were a
loosening, the dump of the *unchanged* tree would change. It does not — see §4.

### Option C — leave `backend/` frozen forever
Accept MI 11.4 permanently and rewrite RULE 18.2 to record it as accepted debt
rather than pending work. Honest, and better than pretending a blocked step is
merely unstarted. **Rejected** because option B costs ~10 hours and removes the
constraint outright; C pays that price in every future round instead.

## 3. Implement

`tools/metrics/dump_public_api.py`:

* `module_names()` → recursive `_walk()`, yielding packages *and* descending;
* new `owns()` predicate, documented with the reason it exists;
* three call sites migrated: public functions, public classes, public values;
* `_shipped_blocks()` also uses `owns()`, so an action block defined in a
  submodule of its package is still attributed to that block module.

New test: `tests/unit/backend/test_public_api_dumper.py` — 10 tests that check
**the detector, not the tree**. `test_backend_api_snapshot.py` asks "did this
tree drift?"; a loosened detector would pass that vacuously. These ask the prior
question:

| Test | Proves |
|---|---|
| `test_a_package_owns_what_its_submodule_defines` | the freedom G0 buys |
| `test_a_foreign_module_is_disowned` | cross-area re-export still fails |
| `test_a_prefix_that_is_not_a_submodule_is_disowned` | `chat_syncster` ≠ `chat_sync.*` |
| `test_flat_module_and_its_package_split_dump_the_same_surface` | end-to-end: split on a synthetic area loses nothing |
| `test_the_package_qualname_is_still_enumerated` | the snapshot key survives |
| `test_a_deleted_symbol_is_still_absent_after_the_split` | **removals stay visible** |
| `test_an_import_failure_is_still_reported` | broken module still reported |

## 4. Verify — the empty-diff proof

The decisive check for a change to a measuring instrument: **on an unchanged
tree, the new instrument must read exactly what the old one read.**

```bash
# dump with the ORIGINAL dumper (git stash), then with the NEW one
diff /tmp/snap_orig.json /tmp/snap_after.json
→ *** IDENTICAL ***
```

Byte-identical. So option B changed no measurement on the current tree; it only
changed what *becomes possible*.

Separately, `--diff` against the committed golden file reports **"no removed or
changed symbols"**, and the block wire snapshot diff is empty. The committed
snapshot is missing some already-allowed *additions* (`click_runner`,
`actions.cancellation`, `PersonPageRequest` — all added by earlier rounds under
the "new symbols are allowed" clause). Those were present before this change
too, proven by the identical-dump check above, so **G0 does not refresh the
golden file**. It is left exactly as found; refreshing it is G1's business, when
a split actually needs it.

| Check | Result |
|---|---|
| Old vs new dumper on unchanged tree | **byte-identical** |
| `dump_public_api.py --diff` | no removed or changed symbols |
| Block wire snapshot | empty diff |
| New dumper tests | 10 passed |
| `test_backend_api_snapshot.py` | 9 passed |

## 5. What this unblocks

`backend/` and `actions/` may now be split into packages, with `__init__.py`
re-exporting the public surface, and the snapshot will confirm — not merely
tolerate — that nothing was lost. G1 (`chat_sync.py`, 807 lines / MI 11.4) is
now executable, and `scroll_parser.py`, `history_query.py`, `dom_highlight.py`
and `config_manager.py` stop being structurally frozen.

One rule for everyone who uses this freedom, and it is not optional: **the
package `__init__` must re-export the module's previous public surface
verbatim.** `owns()` makes a submodule symbol count as owned; it does not make
an un-exported one appear. Split the file, keep the front door.
