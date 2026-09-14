# §18.2 per-file history — extracted from AGENT_RULES.md

`docs/current/AGENT_RULES.md` §18.4 sets a ~730-line budget for itself and
says the next edit "extracts before it adds", naming §18.2's per-file history
as the next candidate to move. Round I did that. The NORM stays in the rules
file; the running history of which files were over the line, and when, lives
here.

## The AREA D freeze, and its lifting (Round G)

`backend/` used to be frozen against package splits because the AREA D public
API snapshot could not see into packages. Round G step G0 taught the snapshot
to walk into packages and to count a symbol defined in a submodule as owned by
its package, so the package remedy works there too. Proven three ways:

* a byte-identical dump of the unchanged tree;
* three splits — `chat_sync` 807, `scroll_parser` 706, `history_query` 603 —
  that pass `test_backend_api_snapshot.py` **unrefreshed**;
* worst MI 24.9, mean 68.08 at the time.

Rules, proof and the remaining candidates:
[`AREA_D_DECISION_2026-09-13.md`](../2026-09-13-round-g/AREA_D_DECISION_2026-09-13.md).

Two constraints on that freedom, both non-negotiable and both still in force
(they remain stated in §18.2 itself):

1. a package `__init__` must re-export the previous public surface
   **verbatim** — `owns()` does not make an un-exported symbol appear;
2. **when size and LCOM disagree, LCOM wins.** G3 split the module around
   `HistoryQuery` (LCOM 0.74) and left the class whole, because splitting a
   cohesive class by line count raises coupling to lower a number.

## Measured snapshots

| Date | Files | Median LOC | Over 500 | Mean MI |
|---|---|---|---|---|
| before Round G | 171 | 136 | 7 | — |
| 2026-09-13, after Round G | 190 | 126 | 4 | 68.08 |
| 2026-09-13, after Round H | 218 | — | 2 | 69.4 |
| 2026-09-14, Round I (I0 baseline) | 219 | — | **0 over 500; 2 over 400** | 69.38 |
| 2026-09-14, after Round I I1–I6 | 221 | — | 0 over 500; 2 over 400 | 69.60 |

Of the four files over 500 at Round G, `bridge/history_bridge.py` carried
step F4's §18.5 note naming its QWebChannel slot contract; the other three
were unblocked debt rather than exemptions. Round H cleared them: the tree has
had **no file over 500 lines** since. The two remaining over 400 are
`bridge/router.py` (530, composition root) and
`stores/history_schema_repair.py` (461, append-only migration ledger), each
carrying a `# ideal-size:` header re-derived from measurement in Round I
step I1.

## Why this history was extracted rather than deleted

§18.2's norm is three bullets long. The paragraphs above were the *evidence*
for one decision (unfreezing `backend/`) that is now settled and acted on. A
reader who needs the norm should not have to read the argument that produced
it; a reader who doubts the norm can follow one link. That is the same test
§18.4 applies to every context file.
