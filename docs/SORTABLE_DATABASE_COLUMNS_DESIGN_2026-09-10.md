# Sortable columns in the Full User Database (BD)

Date: 2026-09-10
Status: implementation design, written **before** the code changed
Request: *"Sortable Columns in BD — the table columns (Nick and etc.) are not
sortable. Add clickable sort arrows (▲▼) next to each column label; clicking a
header sorts ascending/descending; the sort state persists while the app runs."*

---

## 1. Audit — which table is actually unsortable

The page ships **two** nick tables, and only one of them lacks sorting. The
audit is recorded here because it decides the whole shape of the change.

| Window | Element | Renderer | Sortable today? |
|---|---|---|---|
| **User Memory** (People queue) | `#userTable` | `ui/js/user-table.js` | **Yes** — `data-sort` headers, `▲▼` arrows, `UserTable.sortBy()`, added by `docs/GRID_WINDOW_MEMORY_SORT_DESIGN_2026-09-05.md` §5 |
| **Full User Database** (BD) | `#userdbTable` | `ui/js/history-db.js` | **No** — `<th>Nick</th><th>Msgs</th>…` are bare labels with no handler, no arrow, no `aria-sort` |

So the gap is the **Full User Database** table:

```html
<thead><tr>
  <th>Nick</th><th>Msgs</th><th>Media</th>
  <th>First</th><th>Last</th><th>My nick</th><th>Actions</th>
</tr></thead>
```

`HistoryDb` already keeps a `sort: 'recent'` field and already sends it to the
backend, but **nothing in the UI can change it** — there is no header
interaction at all. That is the "cannot organize the list by any column"
behaviour.

The User Memory table is left functionally untouched; it gets regression tests
(§6.2) so the two tables cannot silently diverge again.

### 1.1 The trap that makes a naive fix wrong

`#userdbTable` is **server-paged**. `HistoryDb._request()` asks Python for
`limit: 50, offset: n` and appends each page to `this.rows` as the user scrolls;
`render()` paints exactly what has been loaded. Therefore:

> Sorting `this.rows` in JavaScript sorts *the 50 rows that happen to be in
> memory*, not the database. "Sort by Nick" would show the alphabetically
> smallest nicks **among the 50 most recent people**, which is simply a lie.

The order must be decided in SQL, and a header click must **reset the paging
window** and re-fetch from offset 0. Client-side sorting is explicitly out of
scope for this table (it stays correct for User Memory, which is a fully
loaded, in-memory list).

A second, quieter consequence: `ORDER BY last_seen DESC, message_count DESC`
is **not a total order**. With `LIMIT/OFFSET` paging, ties between pages make
SQLite free to re-shuffle, so a row can appear on two pages or on none. Any
sortable, paged list needs a deterministic tiebreaker — see §3.3.

---

## 2. Requirements, restated as behaviour

1. Every data column header of the Full User Database becomes a real button
   with a `▲▼` indicator: **Nick · Msgs · Media · First · Last · My nick**.
   `Actions` and the row checkbox stay non-sortable (no data to order by).
2. First click on a column sorts it in its **natural** direction (nick/first
   ascending, counts and "last" descending — the useful order first); a second
   click on the same column reverses it.
3. Clicking a *different* column switches to that column in its natural
   direction (it never inherits the previous column's direction).
4. The active header shows `▲` or `▼`, carries `aria-sort`, and is visually
   accented; inactive headers show the idle `▲▼`.
5. The order is computed by the database, over **all** rows, not only the
   loaded page; paging restarts at offset 0 and the list scrolls back to the
   top.
6. The sort survives every later refresh — search typing, `Preload` changes,
   the ⟳ button, `userdb_changed` pushes, label-filter changes — for as long as
   the app runs. It resets only when the page is recreated. (Same lifetime as
   `UserTable.sort`; no new persistence key, per RULE 10 — one decision, one
   place.)
7. Keyboard: the header is focusable and `Enter` / `Space` sorts, like the
   User Memory headers.
8. The nick search keeps its "prefix matches first" ranking **on top of** the
   chosen column order — a search must not lose its relevance ordering.

---

## 3. Data contract

### 3.1 The wire payload

`HistoryDb._request()` sends, as today, one JSON blob to
`HistoryBridge.userdb_page(req_id, query_json)`:

```json
{"q": "", "limit": 50, "offset": 0, "sort": "nick", "dir": "asc"}
```

* `sort` — a **key**, not SQL: one of `nick | msgs | media | first | last |
  my_nick`, plus the historical `messages` / `recent` aliases.
* `dir` — `"asc"` | `"desc"`. Empty/absent means *"the key's natural
  direction"*, which is what every pre-existing caller (and every saved
  setting) asks for, so old payloads keep behaving exactly as before.

The answer echoes both, plus everything it returned before:

```json
{"items": [...], "total": 128, "has_more": true, "offset": 0, "limit": 50,
 "query": "", "sort": "nick", "dir": "asc", "req_id": "u7"}
```

### 3.2 Key → ORDER BY

`HistoryQuery` owns a **whitelist**. A key that is not in the table below falls
back to the default key; no user text ever reaches SQL (RULE: never build SQL
from input — the same discipline `_like_escape` / `_fts_query` already follow).

| key | ORDER BY (natural direction) |
|---|---|
| `nick` | `nick_lc ASC` |
| `msgs` / `messages` | `message_count DESC, last_seen DESC` |
| `media` | `media_count DESC, last_seen DESC` |
| `first` | `first_seen ASC` |
| `last` / `recent` (default) | `last_seen DESC, message_count DESC` |
| `my_nick` | `my_nicks ASC` |

`dir="desc"` flips **every** column of the chosen key, so the secondary column
stays consistent with the primary one (`msgs desc` = fewest messages first, and
among equals, the *oldest* last activity).

`my_nicks` is a JSON array stored as text (`'["Me","Me2"]'`), and the column
displays it joined. Ordering the **stored text** is deliberate: it needs no
JSON1 extension (this codebase already treats optional SQLite features such as
FTS5 as optional), it cannot fail on a hand-edited row, and for the common case
of one identity it is exactly the displayed order. The one wrinkle is pinned by
a test rather than hidden: a person with several identities sorts just before
one sharing the same first identity, because `","` < `"]"` — `["Me", "Old"]`
before `["Me"]`.

### 3.3 Deterministic tiebreaker

After the key's columns, `nick_lc ASC, id ASC` is appended (skipping a column
the key already uses). `nick` is unique, so the resulting order is total:
`LIMIT ? OFFSET ?` can no longer duplicate or drop a row between two pages of
the same sort. This is a fix, not a cosmetic change — the old `recent` order
had the same latent bug, it was just invisible while the sort could not change.

### 3.4 Search interaction

The existing prefix-boost clause stays **first**:

```sql
ORDER BY (nick_lc LIKE ? ESCAPE '\') DESC, LENGTH(nick_lc) ASC, <key order>, nick_lc ASC, id ASC
```

so "Ангел" still lists Ангел / Ангелина before Мой Ангел.

Note what this means precisely, because it is a *deliberate* limit on the new
feature: relevance is a two-part rule — *starts with the needle* first, then
*shorter nick* — and **both parts outrank the chosen column**. A search answers
"who did I mean", not "who has the most messages", so 900 messages must not
lift `Мой Ангел` above `Ангел` while the user is typing a name. The chosen
column decides the order **inside** each relevance tier, which is what the tests
pin.

### 3.5 Public API

`HistoryQuery.list_persons()` gains one optional keyword:

```python
async def list_persons(self, q="", limit=DEFAULT_LIMIT, offset=0,
                       sort="recent", dir="", include_deleted=False) -> dict
```

This is additive and backwards compatible (every existing call site omits
`dir` and therefore keeps its natural direction), but it *is* a signature
change, so the AREA D golden file is updated and the diff is reviewed to contain
**only** this one line. `tests/unit/backend/test_backend_api_snapshot.py` exists
precisely to make such a change visible.

The line is edited rather than the file regenerated wholesale:
`dump_public_api.py --write` also picks up a pre-existing, unrelated staleness
(`BaseAction.click_runner` exists in the code but was never written into the
snapshot). The test explicitly allows new symbols, so that gap is harmless and
out of scope here.

---

## 4. UI contract

### 4.1 Markup (`ui/index.html`)

Each sortable header keeps the shape the User Memory table already proved:

```html
<th data-sort="nick" tabindex="-1" aria-sort="none">
  <button type="button" class="sort-button" title="Sort by Nick">
    Nick <span class="sort-arrow">▲▼</span>
  </button>
</th>
```

A `<button>` (not a bare `<th onclick>`) because it is focusable, announces
itself to screen readers, and works with `Enter`/`Space` for free. The existing
`.sort-button` / `.sort-arrow` styles are reused verbatim, so the two tables
render the same control.

### 4.2 State and behaviour (`ui/js/history-db.js`)

```js
sortKey: 'last',      // current column
sortDir: 'desc',      // current direction
NATURAL: { nick: 'asc', first: 'asc', my_nick: 'asc',
           msgs: 'desc', media: 'desc', last: 'desc' },
```

* `sortBy(key)` — same key ⇒ flip; new key ⇒ `NATURAL[key]`; then `reload()`.
* `reload()` already clears `rows` / `hasMore` / `loading`; it additionally
  resets the scroll position, because a new order makes the old offset
  meaningless.
* `_sortRequest()` returns `{sort, dir}`; `_request()` spreads it into the
  payload, so **every** page request — first load, search, scroll, refresh —
  carries the current order. That is what makes the state "stick".
* `_updateSortHeaders()` writes `aria-sort` (`ascending` / `descending` /
  `none`), toggles `.sort-active`, and asks `UIHelpers.sortArrow()` for the
  glyph — the *same* helper User Memory uses, so `▲▼` / `▲` / `▼` can never
  drift between the two tables.
* The label filter still runs client-side on the loaded page (`visibleRows()`),
  which is correct: it hides rows, it does not re-order them.

### 4.3 Styles (`ui/css/history.css`)

`.userdb-table th[data-sort]` gets the pointer cursor, hover/focus accent and
`.sort-active` colour that `#userTable th[data-sort]` already has. No new
glyph, no new component.

---

## 5. What is deliberately NOT changed

* **User Memory sorting.** Already implemented and correct; it only gains
  regression tests.
* **No persisted sort.** The request asks for the state to survive *while the
  app runs*. Writing it to `app_settings` would add a second source of truth
  for a one-click decision (RULE 10) and would need a migration for no gain.
* **No client-side comparator for `#userdbTable`.** See §1.1.
* **No change to the `persons` schema**, the tombstone rule (RULE 14), or the
  bridge's `req_id` protocol.

---

## 6. Test plan — written before the implementation

RULE 8: tests execute the real shipped module against a DOM stub, and fail if
the feature is deleted.

### 6.1 `tests/test_userdb_sort.js` (new, Node)

Parses the **real** `#userdbTable` `<thead>` out of `ui/index.html`, builds DOM
nodes from it, loads the **real** `ui/js/history-db.js`, and asserts:

* markup: every data column has `data-sort` + a `.sort-button` + a
  `.sort-arrow`; `Actions` has none;
* boot: the default order is the historical `recent`/`desc`, and the first
  `userdb_page` payload carries it;
* click on `Nick` ⇒ one new request with `{sort:'nick', dir:'asc'}`, paging
  reset to offset 0, rows cleared, list scrolled to the top;
* second click ⇒ `dir:'desc'`; clicking `Msgs` ⇒ `msgs`/`desc` (natural, not
  inherited); unknown keys are ignored;
* `aria-sort` + arrow glyph follow the state; exactly one header is active;
* `Enter`/`Space` on a header sorts;
* the state survives `onChanged()`, a search, a `Preload` change and a later
  page (offset 50) — every payload repeats the current `sort`/`dir`;
* **regression guard:** loaded rows are painted in the order the server sent
  them, i.e. the module never re-sorts client-side.

### 6.2 `tests/test_user_memory_sort.js` (new, Node)

Pins the *existing* User Memory behaviour so the two tables cannot diverge:
toggling, natural first direction, per-key comparators (text / timestamp /
0-1 booleans), empty values last in **both** directions, survival of a
`users_updated` re-render, and header/`aria-sort` agreement.

### 6.3 `tests/test_userdb_sort_query.py` (new, pytest)

Drives the **real** `HistoryQuery` over a real SQLite file:

* each key orders as specified, in both directions;
* `dir=""` reproduces the historical order for `recent` / `messages` / `nick`
  / `first` (backwards compatibility);
* an unknown key falls back to the default rather than raising;
* the ORDER BY is a total order — walking a 25-row list in pages of 5 yields
  every nick exactly once, with ties on `last_seen` / `message_count`;
* the nick-search prefix boost still wins over the column order;
* tombstoned people stay hidden under every sort (RULE 14);
* no key can inject SQL.

### 6.4 `tests/test_userdb_sort_bridge.py` (new, pytest)

Drives the **real** `HistoryBridge.userdb_page` slot over QWebChannel:

* `dir` reaches `list_persons` and the answer echoes it;
* an absent `dir` keeps the natural direction;
* a hostile `sort` / `dir` string cannot break the query.

### 6.5 Existing suites that must stay green

`tests/test_history_query.py`, `tests/test_history_query_edges.py`,
`tests/test_history_bridge.py`, `tests/test_history_panels_boot.js`,
`tests/unit/backend/test_backend_api_snapshot.py` (golden file refreshed with
only the `list_persons` line changed), and the full `pytest` run.

---

## 7. Verification matrix

| Claim | Proven by |
|---|---|
| Headers are clickable and show ▲▼ | `test_userdb_sort.js` markup + arrow cases |
| Click toggles asc/desc; new column starts natural | `test_userdb_sort.js` click sequence |
| Order is computed over the whole DB, not one page | `test_userdb_sort_query.py` per-key ordering on a seeded DB |
| Paging is stable under a sort | `test_userdb_sort_query.py` page-walk uniqueness |
| Sort survives refreshes while the app runs | `test_userdb_sort.js` state-persistence cases |
| Nothing else broke | full `pytest` + all `tests/*.js` |

## 8. Files touched

```
backend/history_query.py     sort-key whitelist, `dir`, tiebreaker, payload echo
bridge/history_bridge.py     forward `dir`
ui/index.html                sortable headers on #userdbTable
ui/js/history-db.js          sort state, header wiring, arrows, paging reset
ui/css/history.css           header affordance for .userdb-table
README.md                    the Full User Database row gains "sortable"
tests/…                      the four new suites above
tests/unit/backend/backend_api_snapshot.json   refreshed (one line)
```
