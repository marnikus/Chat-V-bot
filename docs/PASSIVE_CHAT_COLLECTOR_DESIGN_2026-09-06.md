# Passive Private-Chat Message Collector — Background Architecture

Date: 2026-09-06
Status: **DESIGN ONLY — no code written for this feature yet**
Parent: `MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md` (doc A)

> "create algo mechanism that saves resources of computer to collect this
> msg that helps not parse full chat as it could be too big. Design solution
> here first" — this document is that solution.

---

## 1. Goal, constraints, non-goals

**Goal.** While the user chats normally, every line of every private
conversation (both directions, text and media) ends up in the archive,
in real time, with a truthful status indicator — and the app stays as
responsive as if the collector did not exist.

**Hard constraints**

| # | Constraint | Consequence |
|---|---|---|
| C-1 | Must not freeze the UI window | no blocking calls on the Qt/qasync loop; every unit of work is bounded and awaits |
| C-2 | Must not re-parse a long chat repeatedly | steady-state cost must be independent of conversation length |
| C-3 | One CDP socket shared with the action engine | collector work is preemptible and low priority (decision D-3) |
| C-4 | Must not disturb the page the user is using | no clicks, no focus changes, no scrolling, no DOM mutations except one detached script object |
| C-5 | Must survive Angular re-renders, tab switches and reconnects | supervisor + re-injection + resync |
| C-6 | Incomplete data is acceptable; **silently** incomplete is not | explicit `gaps` rows and visible statuses |

**Non-goals (v1).** Collecting background (non-active) private tabs;
archiving the main room; scrolling the page to harvest older history
automatically; editing or deleting messages on the site.

---

## 2. Detection: "is the current tab a private chat?"

### 2.1 The evidence available (verified in `Вирт чат privat.html`)

```
.tab-item.active                                   ← the tab the user is looking at
   ├── mat-icon.chat-type-icon[data-mat-icon-name]  'user' = private, 'room' = main
   └── p.chat-title                                 partner nick (strip span.unread)
users-list … users-header-item .users-counter       participant count → "2"
users-list … user-item .primary-text                each participant
users-list … user-item .primary-text.bold           ← ME
app-messages (visible one) > .messages-root         the conversation body
```

### 2.2 Decision procedure (one cheap probe, §3.2)

```
if !cdp.connected                     → DISCONNECTED
if no .tab-item.active                → UNKNOWN (page still booting)
if active tab icon != 'user'          → NOT_PRIVATE            ("Not in private tab now")
partner := text(.tab-item.active p.chat-title) minus .unread, normalised
count   := int(.users-counter) if present else distinct nicks in the visible list
if require_two_participants and count != 2   → GROUP_TAB       ("Group tab — not collecting")
if my_nick set and partner == my_nick        → AMBIGUOUS       (warn, do not collect)
otherwise                                     → PRIVATE(partner)
```

Fallback chain when `.users-counter` is missing (site change / collapsed
sidebar): distinct `user-item .primary-text` values → distinct `.from`
nicks among the rendered messages. Each fallback is logged **once per
conversation**, never per tick.

### 2.3 Which `app-messages` to read

The page can keep several conversations mounted. `chat_agent_js` resolves
the **visible** one exactly like `backend/media_handler.py`'s
`CTX_PROBE_JS` does for the composer: pick the `app-messages` whose
`offsetParent !== null` and which shares an ancestor with the visible
`app-message-form`. If that resolution fails, the collector reports
`AMBIGUOUS` and stops rather than scraping a hidden list — a wrong
conversation in the archive is worse than a missing one.

### 2.4 My Nick

* Canonical value: `config.collector.my_nick`, edited in the **pinned
  header** field (doc C §1.2), persisted immediately, mirrored in the
  Collector window.
* `detect_my_nick` reads `user-item .primary-text.bold` from the private
  tab and offers it ("Detect" button); the user confirms — never silently
  overwritten, because it is also used to attribute past rows.
* Changing My Nick does **not** rewrite existing rows. Each message keeps
  the `my_nick` it was collected under, which is exactly what the request
  asks for ("my nick could be every time different"), and the preview
  draws a divider when it changes.
* Direction does not depend on it: `.my-message-background` decides
  `in`/`out`. My Nick is the cross-check (mismatch ⇒ one warn line, class
  wins).

---

## 3. The collection algorithm — three tiers

The core idea: **stop asking the page questions; make the page tell us.**

```
 T0 BOOTSTRAP     once per conversation, chunked, paced      O(n) once
 T1 LIVE PUSH     MutationObserver in-page → CDP binding     O(new lines)
 T2 HEARTBEAT     tiny supervisory probe every 1.5–3 s       O(1), ~500 bytes
```

Steady state — a private tab open, nobody typing — costs one ~500-byte
probe every 1.5 s and **zero** DOM serialisation. That is what satisfies
C-2.

### 3.1 T0 — Bootstrap (the "parse full current history" phase)

Triggered when a conversation becomes active and its cursor says
`bootstrapped = 0`, or when the supervisor demands a resync.

```
count := agent.count()                       # childElementCount — O(1)
if count > bootstrap_max_messages:           # default 5000
    collect the newest bootstrap_max_messages and record a gap row
for start in range(count-1 → 0, step = -chunk):        # newest chunk first
    batch := agent.slice(start, start+chunk)           # chunk default 80 nodes
    records := parse(batch)                            # fingerprints computed in-page
    if should_stop(): report "stopped", break          # RULE 7
    align + insert (one transaction)                   # §3.5
    report progress: "Bootstrapped 240/1310 …"         # RULE 5
    await sleep(bootstrap_pause_ms)                    # default 40 ms → UI breathes
mark cursor.bootstrapped = 1, store head_sig/tail_sig/tail_fps/dom_count
```

Why newest-first: the preview opens at the newest end, so the user sees
their conversation populate immediately while older pages stream in.

Cost control:
* the agent returns **already-parsed records**, not HTML — a 80-message
  chunk is ~12 KB of JSON, not ~400 KB of markup;
* `chunk` and `pause` are settings (halved/doubled under throttle);
* `await` between chunks is what keeps Qt repainting (C-1).

### 3.2 T2 — Heartbeat probe (the supervisor)

One `Runtime.evaluate` returning a fixed, tiny object:

```jsonc
{
  "ok": true,
  "agent": 3,            // agent protocol version, 0 = not installed
  "tab": "private",      // private | room | none | unknown
  "partner": "На работе 25",
  "participants": 2,
  "me": "HiHoney",       // bold participant row, when visible
  "count": 1310,         // messages-root childElementCount  (O(1))
  "head": "a91f…",       // fingerprint of the FIRST rendered node
  "tail": "77c2…",       // fingerprint of the LAST rendered node
  "pending": 0,          // records queued in the agent (drain fallback)
  "scroll": {"top": 8123, "height": 9410}
}
```

Only `head`/`tail` hash one node each (payload truncated to 200 chars), so
the probe is O(1) in conversation length.

Decision table:

| Observation | Meaning | Action |
|---|---|---|
| `agent == 0` | Angular re-rendered / page reloaded | re-inject agent, then resync |
| `tab` changed | user switched conversation | flush current cursor, switch context, bootstrap if needed |
| `count == cursor.dom_count` and `tail == cursor.tail_sig` | nothing happened | status `no_new`, extend interval (adaptive backoff) |
| `count > dom_count`, `head` unchanged | new messages at the bottom | tail delta (should already have arrived via T1; if not, self-heal) |
| `head` changed, `count` grew | older messages were loaded above (user scrolled up) | head backfill |
| `count < dom_count` | the site trimmed its buffer | resync + evaluate for a gap |
| `pending > 0` | binding push unavailable → drain fallback | `agent.drain()` |

### 3.3 T1 — Live push (steady state)

The in-page agent installs **one** `MutationObserver` on the resolved
`.messages-root`:

```js
observer = new MutationObserver(muts => {
   for (const m of muts) for (const n of m.addedNodes) queue.push(n);
   schedule();                       // debounce
});
observer.observe(root, {childList:true, subtree:false});
```

* **Debounce** `batch_debounce_ms` (default 250 ms) using
  `requestIdleCallback` with a `setTimeout` fallback — a burst of 20
  messages produces one batch, not 20 round-trips.
* **Batch cap** `max_batch` (default 40); overflow stays queued and is
  drained on the next tick, so a flood can never build an unbounded string.
* **Delivery**: `__cvbPush(JSON.stringify(batch))`, a function created by
  CDP `Runtime.addBinding`. Python receives `Runtime.bindingCalled` events —
  no polling at all.
* **Fallback**: if `addBinding` is unavailable or the binding disappears,
  the agent keeps the batch in `queue` and reports `pending` in the
  heartbeat; the supervisor calls `agent.drain()`. Same data path, one
  extra round-trip — the feature degrades, it does not break.
* The agent also observes the tab strip (`.tabs-list`) with a second, tiny
  observer so a conversation switch is pushed instantly instead of waiting
  for the next heartbeat.

**Required CDP client change** (doc A §8): `_receive_loop()` currently
discards every frame without an `id`. It must fan out
`{"method": …, "params": …}` frames to registered listeners
(`cdp.on_event("Runtime.bindingCalled", cb)`), and expose
`add_binding(name)` / `add_script_on_new_document(src)`. This is ~45 lines
and is a strict addition — no existing behaviour changes.

### 3.4 The in-page agent contract (`window.__cvbAgent`)

```js
window.__cvbAgent = {
  v: 3,                       // protocol version (heartbeat checks it)
  state(),                    // → the heartbeat object of §3.2
  slice(from, to),            // → parsed records for rendered nodes [from,to)
  drain(max),                 // → queued records (fallback path)
  reattach(),                 // re-resolve the visible root, re-arm observers
  stop(),                     // disconnect observers, delete queue
  parse1(node)                // internal: one node → record
};
```

One parsed record:

```jsonc
{
  "fp": "5f3c…",              // fingerprint (doc A §6.1), computed in-page
  "dir": "out",               // from .my-message-background
  "from": "HiHoney",
  "kind": "text",             // text | image | gif | service
  "text": "повезло ученикам))",
  "media": null,              // or {"url": "https://…gif", "kind": "gif"}
  "time": "17:31",
  "occ": 0,                   // minute_occurrence (doc A §6.1)
  "idx": 1307                 // position in the rendered list
}
```

Design notes:
* **Fingerprints are computed in the page** (a 25-line FNV-1a/SHA-1-lite
  hash) so Python never receives text it is going to throw away, and the
  heartbeat can hash `head`/`tail` without transferring them.
* The agent is **read-only** on the page: no styles, no attributes, no
  classes, and it holds no strong references to removed nodes (the queue
  stores parsed records, not DOM nodes — an Angular recycle cannot leak).
* Injection: `Page.addScriptToEvaluateOnNewDocument` (survives SPA
  navigation) **plus** an immediate `Runtime.evaluate` for the page that is
  already open. Idempotent — re-injection replaces observers cleanly via
  `stop()` then re-arm.

### 3.5 Alignment and insert (shared by T0/T1/T2 and the action block)

```
records  → drop service/system rows unless collect_service
         → align against cursor.tail_fps (doc A §6.4)
         → assign ord = cursor.last_ord + 1 …
         → compute day buckets (doc A §6.3) and dedupe keys
         → ONE transaction:
              INSERT OR IGNORE INTO messages …          (executemany)
              register media rows (state='pending')
              UPDATE persons counters, last_seen, my_nicks
              UPDATE cursors (last_ord, dom_count, head/tail sig, tail_fps)
         → enqueue media downloads (unless paused)
         → emit history_appended (only if this conversation is open in the UI)
         → emit collector_status (coalesced)
```

Everything is one transaction so a crash mid-batch leaves the cursor and
the rows consistent — the next run simply re-aligns.

---

## 4. Scheduler, throttling and CDP fairness

### 4.1 The supervisor task

A single `asyncio.Task` created on the qasync loop at startup (never a
`QThread`: the CDP client, `aiosqlite` and Qt signals all live on this
loop; a second thread would buy nothing and cost a lock).

```
while not stopped:
    t0 = now()
    if not cdp.connected:      set_status(DISCONNECTED); await sleep(2s); continue
    if paused:                 set_status(PAUSED);       await sleep(0.5s); continue
    hb = await lease.low( agent_state_probe )       # §4.2
    apply the §3.2 decision table  (bootstrap / delta / resync / nothing)
    await sleep(next_interval(hb, t0))
```

`next_interval` — adaptive backoff, all bounded:

```
base        = heartbeat_ms                       (1500)
if status == NOT_PRIVATE or DISCONNECTED: base = idle_heartbeat_ms      (3000)
if run_active and throttle_during_run:    base *= throttle_factor       (×4)
if last probe took > 500 ms:              base = min(base*2, 8000)      (page is busy)
if a delta arrived this tick:             base = max(base/2, 600)       (chat is hot)
```

Live push means these intervals only govern *supervision*, not latency: a
new message still lands in ≤ `batch_debounce_ms` + one round-trip.

### 4.2 CDP priority lease

```
class CdpLease:                    # ~40 lines, in cdp_client.py
    high(coro)  – action engine: acquires immediately, may preempt waiters
    low(coro)   – collector: waits while any high holder or waiter exists
```

Rules:
* the collector holds the lease for **one evaluate at a time** (never
  across a whole bootstrap loop), so a run never waits longer than one
  probe;
* `high` waiters jump the queue (a simple two-deque fair-ish lock);
* under `run_active` the collector additionally: ×4 interval, ½ chunk size,
  media downloads paused (`media.pause_during_run`), bootstrap deferred to
  after the run unless the user forces it.

This is decision D-3 ("keep collecting, throttled") made concrete: live
push still works during a run (it is event-driven and costs the page
nothing), only *our* polling and downloads step aside.

### 4.3 Non-blocking guarantees (C-1)

| Risk | Mitigation |
|---|---|
| Big JSON parse | chunk cap 80 records ⇒ ~12 KB per message |
| Base64 media decode + file write | `asyncio.to_thread` |
| SHA-256 of a 5 MB file | same worker thread |
| SQLite writes | `aiosqlite` (own thread) + batched transactions |
| UI signal storm | `collector_status` coalesced to ≤4 Hz; `history_appended` only for the open conversation |
| Long bootstrap | paced chunks with `await`, cancellable, progress reported |
| Unbounded memory | agent queue cap, `tail_fps` capped at 200, in-memory write buffer capped at 500 rows |

**Performance budget** (targets to verify in M6, doc D): idle CPU < 1 % of
one core; heartbeat payload < 700 B; new-message latency < 400 ms; append
< 5 ms/message; bootstrap of 2 000 messages < 6 s with no frame longer
than 16 ms in the app window.

---

## 5. Status model

One enum, one LED, one sentence — shown in the Collector window, the
pinned header (compact dot + text), and the Log Console on transitions.

| State | LED | Text shown | Meaning |
|---|---|---|---|
| `DISCONNECTED` | grey | "Not connected" | no CDP session |
| `OFF` | grey | "Collector off" | disabled in settings |
| `PAUSED` | amber | "Paused" | user pressed Pause |
| `NOT_PRIVATE` | grey-blue | **"Not in private tab now"** | active tab is the room / no tab |
| `GROUP_TAB` | grey-blue | "Group tab — not collecting" | participants ≠ 2 |
| `BOOTSTRAPPING` | blue pulse | **"Collecting — {nick} {done}/{total}"** | first full parse in progress |
| `COLLECTING` | green pulse | **"Collecting — {nick} (+{n})"** | a delta is being appended |
| `COLLECTED` | green | **"Collected — {n} messages"** | delta finished (auto-fades to `NO_NEW` after 3 s) |
| `NO_NEW` | green dim | **"No new messages"** | private tab open, nothing new |
| `THROTTLED` | green dim | "Collecting (throttled — run active)" | decision D-3 in effect |
| `RESYNC` | blue | "Re-syncing — {nick}" | agent lost / buffer trimmed |
| `ERROR` | red | "Error: {short reason}" | last operation failed; retry countdown shown |

The three phrasings the request asked for map to `COLLECTING`,
`COLLECTED`/`NO_NEW`, and `NOT_PRIVATE`. Transitions are logged once
(never repeated every tick — RULE 5's "surface it as it happens" must not
become log spam).

Status payload:

```jsonc
{"state":"COLLECTING","nick":"На работе 25","my_nick":"HiHoney",
 "added":3,"total":1313,"pending_media":2,"throttled":false,
 "since":"2026-09-06T17:32:04","error":"","agent":3,"fts":true}
```

---

## 6. Failure modes and self-healing

| Failure | Detected by | Recovery |
|---|---|---|
| Page reload / SPA route change | `agent == 0` in heartbeat | re-inject (also pre-armed via `addScriptToEvaluateOnNewDocument`), resync, status `RESYNC` |
| Binding lost (new execution context) | `pending > 0` while no pushes arrive | drain fallback; re-`addBinding` on the new context |
| Observer silently detached (root replaced) | `count` grew but no push arrived | `reattach()` + tail delta; counted in a `self_heals` metric shown in the panel |
| Tab switched mid-bootstrap | heartbeat `partner` changed | abandon the chunk loop cleanly (cursor keeps what was committed), start the new conversation |
| Two conversations with the same nick | nick is the identity by design | they merge — this is the requested behaviour ("do not create a duplicate entry") |
| Site renames the message classes | records parse with `dir` unknown | fall back to My Nick comparison, warn once, keep collecting |
| CDP evaluate timeout (30 s) | exception | one retry with backoff, then `ERROR` + retry countdown; the supervisor loop itself never dies |
| Archive DB unavailable | open/write exception | collector switches to `ERROR`, buffers ≤500 rows in memory, retries every 15 s; the rest of the app is untouched |

Invariant: **the supervisor task must never die.** Every iteration body is
wrapped; an unexpected exception logs a traceback, sets `ERROR`, and the
loop continues after a backoff.

---

## 7. Interaction with the Action Stack engine

* `ActionEngine` gains two notifications (`run_started` / `run_finished`,
  ~15 lines) that the collector subscribes to for throttling. No engine
  logic changes.
* The collector is **not** part of a run and does not appear in run traces,
  except as ordinary log lines.
* If the run itself sends a message (Type Message → Click Send), the new
  line appears in the DOM and is archived by the normal live path with
  `direction = 'out'` — the collector is the single writer, so there is no
  double-accounting between "the bot sent it" and "the archive saw it".

---

## 8. The `COLLECT_HISTORY` action block

`actions/collect_history.py` — "📥 Collect Message History".

**Purpose (from the request).** "Create the Action Block to parse full
current msg history and add new lines of msg if new upcoming — add this
data to DB for this Nick."

**Settings** (plain attributes, RULE 3; mirrored in `ui/js/stack-dnd.js`):

| Setting | Default | Meaning |
|---|---|---|
| `target` | `"active_tab"` | `active_tab` \| `memory_nick` (`{{nick}}` from Pick Person / Click User) |
| `mode` | `"sync"` | `sync` (align + append) \| `full` (force a complete re-scan) \| `delta` (only what is newer than the cursor) |
| `require_private` | `true` | fail when the active tab is not a 2-person private chat |
| `max_messages` | `5000` | safety cap for `full` |
| `chunk_size` | `80` | nodes per evaluate |
| `chunk_pause_ms` | `40` | pacing between chunks |
| `download_media` | `true` | queue media for caching |
| `fail_if_empty` | `false` | if true, "no new messages" is a failure (default: OK/info — RULE 4) |
| `pre_delay_ms`, `enabled` | 500 / true | inherited |

**Result mapping** (RULE 4 — an empty result is not a failure):

| Outcome | Result | Reported line |
|---|---|---|
| Appended N rows | `OK` | ✅ "Archived 12 new messages with «Nick» (total 1 313)" |
| Nothing new | `OK` | ℹ️ "No new messages with «Nick» — archive already up to date" |
| Not a private tab (and `require_private`) | `FAIL` | ❌ "Active tab is not a private chat — nothing archived" |
| Target nick not resolvable | `FAIL` | ❌ "No nick in memory — run Pick Person / Click User first" |
| Stopped mid-way | `OK` (stopped) | ⏹ "Stopped after 240 messages — cursor saved" (RULE 7: stopped ≠ failed) |
| Parse/DB error | `FAIL` | ❌ with the reason |

Progress is reported per chunk (RULE 5), and the block reuses
`chat_parser` + `history_repo` — **no parsing logic is duplicated** between
the block and the collector. `target=memory_nick` verifies that the active
conversation actually belongs to that nick before writing, and fails
loudly if it does not (never write Alice's lines under Bob's nick).

---

## 9. Test plan for this half

| Suite | Kind | Proves |
|---|---|---|
| `tests/test_history_agent_js.js` | `js_harness.js` + DOM stub built from the saved private page | one node → correct record (direction, nick, text, media, time, occurrence); fingerprint stability; slice bounds; drain cap |
| `tests/test_chat_parser_delta.py` | fake CDP client scripted with DOM states | bootstrap → tail delta → prepend backfill → buffer trim → alignment lost (+gap row); idempotency: replaying the same states inserts nothing |
| `tests/test_collector_state.py` | fake CDP + fake clock | every row of the §5 status table; throttling under `run_active`; stop is prompt inside a bootstrap (RULE 7); supervisor survives an injected exception |
| `tests/test_collect_history_block.py` | fake CDP + temp DB | all six result mappings, settings round-trip through `to_dict()` |
| `tests/test_cdp_events.py` | fake websocket | event fan-out, binding registration, lease priority (a high waiter overtakes a queued low one) |

A test that would pass with the feature deleted is not a test (RULE 8):
every suite above asserts on **rows actually written to a temp SQLite file**
or on parsed records, never on generated strings.
