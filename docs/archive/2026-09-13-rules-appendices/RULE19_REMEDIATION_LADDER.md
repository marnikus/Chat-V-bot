# RULE 19 appendix — the remediation ladder and its worked case studies

Extracted from [`docs/current/AGENT_RULES.md`](../../current/AGENT_RULES.md)
RULE 19 on 2026-09-13 — the §18.4 *extract-first* paydown that brought the
rules file from 763 lines back inside its ~730 budget. The norms (the order,
the fail lines vs. ideals distinction, the long-and-flat exception, the
verify-after-every-step rule) stay in RULE 19; this appendix holds the ladder
diagram and the repo case studies that illustrate each step. True as of the
extraction date; archived per RULE 17.

## The ladder

```
Step 1:  Fix NESTING DEPTH first (> 4 → flatten)
         ├── Guard clauses / early returns
         ├── Invert conditions
         └── Extract deeply nested blocks

Step 2:  Fix CYCLOMATIC COMPLEXITY (> 10 → simplify)
         ├── Replace conditionals with polymorphism / dispatch
         ├── Strategy pattern for branching
         └── Lookup tables instead of if/elif chains

Step 3:  Fix COGNITIVE COMPLEXITY (> 15 → clarify)
         ├── Break compound boolean expressions into named variables
         ├── Replace clever tricks with obvious code
         └── Simplify control flow

Step 4:  NOW check SIZE — it's probably already fixed
         ├── If function still > 20 LOC → extract by concept
         ├── If class still > 120 LOC → single responsibility split
         └── If params > 3 → introduce parameter object
```

Steps 1–3 quote the **fail lines** (RULE 16: nesting 4, CC 10, cognitive 15).
Step 4 quotes the **ideals** (RULE 18 / §16.1 "prefer": 20 / 120 / 3) — *not*
fail lines, which are 30 / 150 / 4. Nothing in step 4 rejects a change on its
own.

## Worked case studies (per step)

**Step 1 — nesting (> 4).** Guard clauses: refuse early and return so the
happy path is never indented — structurally, the way `services/db_deletion_flow.py`
raises `_PhaseRefusal` from a phase and catches it once in `delete_world`,
instead of 27 nested early-return blocks. Invert (`if not ok: return`, not
`if ok:` around the body). Extract the *innermost* deep block first — smallest
scope, safest move. Measured by the AST walker in `tests/test_rule16_new_code.py`.

**Step 2 — cyclomatic (> 10).** Dispatch instead of branching on a type:
the 16 blocks are a registry lookup (`actions/registry.py` `get_action_class`),
not an `if/elif` over block ids. Lookup tables are data, not branches:
`choose_cycle_mode()` returns `CycleDecision(mode, reason)` from a precedence
table; `DB_GROUP_SUFFIXES`, `MIME_EXT`, `IMAGE_EXT` are tuples/dicts. Two
interchangeable back-ends behind one call, not a branch at every call site:
archive search is FTS5 when SQLite offers it and a `text_lc LIKE` scan when it
does not (`backend/history_query.py`). Never delete a real decision to reach the
number — four independent binary outcomes cost CC 5 minimum (§16.2).

**Step 3 — cognitive (> 15).** Name the compound: `if _is_self_chat(names)`
reads, `if a and not b and c or d` does not; `StackFacts.has_mem_click` exists so
nobody re-scans the stack inside a condition. Obvious beats clever — a comment
explaining a trick is a request to delete the trick. Scored by
`cognitive-complexity` 1.3.x.

**Step 4 — size, last.** By now the function is often already inside the
ideal. If not, extract **by concept** with a name that already exists in the
domain (`_gate_before_cycle`, `_announce_stopped`, `inspect_stack`) — never
`foo_part1`. A class over the ideal gets a single-responsibility split, the way
`services/run/` and `stores/history_repo*` were split (§18.2). Too many params
get a parameter object: `PersonPageRequest` in `backend/history_query.py` is the
model — `needle` / `where` / `order` / `spec` / `columns` as properties of one
typed request instead of five arguments.

**When the ladder does not apply.** A function that is long but *flat* —
sequential phases or a fallback ladder, little nesting — is not fixed by steps
1–3. Two real cases: `DbLifecycle._delete_unlocked` was 631 LOC at CC 143
because it ran seven sequential phases, and the fix was extraction by phase
(`validate → scan → switch → detach → database → media → finalize`);
`backend/message_injector.py` `_run_type_strategies` (70 LOC) is a verified
typing ladder — value setter → Ctrl+V → `insertText` — whose length is three
real attempts plus their read-backs, so it extracts per attempt, not per branch.
In both, step 4 was the tool rather than the fallback. Read the shape before
picking a step: nested → 1, branching → 2, dense → 3, long-and-flat → 4.
(A third case, added the day of extraction: G6 §3 reduced
`bridge/router.py::_build_router_class` from cognitive 17 by exactly this read —
four numbered registration phases, each already a concept, each became one
function.)
