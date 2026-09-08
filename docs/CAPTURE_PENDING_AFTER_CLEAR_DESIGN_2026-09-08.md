# Capture pending after clearing Person History

Date: 2026-09-08
Status: **Implemented and verified.** The investigation/design above was written before application-code changes; the implementation record is in §5.
Branch: `arena/01a08228-chat-v-bot`
Baseline: `1d2c09ddbd1e58b8bc843341f533f489f1683263`

## 1. User report and clarified acceptance criteria

The supplied screenshot shows:

- two visible messages, two participants, one pane;
- zero archived messages;
- `capture_pending`, `awaiting retry 2`, full scan pending;
- a contradictory **No new messages** status;
- an effective 20,000 ms interval despite the 1,500 ms setting.

The user explicitly clarified:

1. **Clear must keep old messages deleted. Only subsequently sent/received messages should be saved.** Neither Collect now nor Backfill is permission to undo a clear.
2. The two messages in question are **plain text**, not images/GIFs.

Therefore do not "fix" this by restoring tombstones, deleting dedupe keys, creating another database, accepting empty payloads as saved, or relaxing the private-chat gate. Preserve the previous DB Connection protections and chronological undo.

## 2. Investigation and evidence

### Confirmed behavior / reproduced defects

1. **Clear itself is not a collection off-switch.** With the real HistoryService, repository, and temporary SQLite file: archive two complete records → clear → append a genuinely new complete record. Visible counts are `2 → 0 → 1`, with the two old rows still hidden. The failure is upstream of a successful append, not a reason to undelete old rows.
2. **Errors are collapsed into empty captures.** `CDPClient.evaluate()` ignores CDP protocol errors and `exceptionDetails`. `ChatParser.slice()` uses `_payload()`, which ignores `{ok:false,error:...}` and silently drops malformed records. The caller labels an empty failed read as missing text; the collector then reports No new messages. The screenshot cannot distinguish this from a genuinely empty text node.
3. **An unreadable first range starves later messages.** With three DOM records, chunk size one, and only the first payload empty, the shipped sync reads `(0,1)` four times, then breaks. The two later, complete text records are never examined: `count=3, added=0, reason=capture_pending`.
4. **Text extraction is tied to one wrapper/class.** The shipped generated install/state/slice expressions were executed in jsdom against the repository's saved private-chat HTML. The original layout yields four ready records. Removing only the payload spans' `message` class leaves all visible text/author/time intact but yields four incomplete records and zero ready records. The extractor must handle structurally identifiable body text without harvesting sender/time/icon/menu text.
5. **Paragraph-only media lookup is also brittle.** Parsing the saved room HTML with a standards-compliant HTML parser closes a paragraph around block image wrappers; media becomes a sibling of `p.message`. The old lookup misses 22 valid image elements. This is a separately reproduced layout issue, **not evidence that the user's two text messages are media**.
6. **Backfill runs before visible capture.** Automatic first-read/backfill scrolls before saving the already visible text. This can destabilize a virtualized view before its ready payloads are archived. A failure leaves full-scan-complete false and repeats the same scroll on every retry.
7. **Retry waits inflate browser backoff.** The penalty uses the duration of an entire tick, including intentional 200 ms retries, scroll settling, SQLite and downloads. A 600 ms intentional retry wait alone drives the maximum penalty; classifying the result as idle multiplies the 5,000 ms idle interval to 20,000 ms. This is not evidence of a slow browser probe.

8. **The DOM integration test exposed a nickname/badge collision.** `ownText()` subtracts child-element text using first-occurrence `String.replace`. A title `Svetik25❤️` with an unread badge `2` becomes `Svetik5❤️2`, and the valid private chat is refused. Fix by reading direct text nodes (with a safe adapter fallback), not deleting substrings from the nickname. This is an independently reproduced gate bug; the screenshot's correct displayed partner does not establish that it caused this particular capture-pending state.

### Limits of the evidence

The user's live Chrome DOM and SQLite file are not accessible here. The screenshot plus answers identify the failure stage, but do not prove the exact live selector/JavaScript error. Do not claim that the live messages have already been captured or invent their contents. Tests must cover the actual generated expressions and DOM parsing, not only Python fake pages returning prebuilt records.

A real Chromium test installation was attempted during investigation. The browser CDN failed TLS connections; jsdom is available in an external test cache. This limitation will be reported separately from test results. Browser/test dependencies and generated data must not enter production storage or the Git patch.

## 3. Proposed structure

### A. One scoped payload extractor

Refactor the agent's per-message extraction, not database schema:

- Scope to the selected message container / its `.message-content`, never all text from the pane.
- Prefer the known payload selector. If absent, traverse the message body structurally, excluding sender, timestamp/status, icons, controls, menus, scripts/styles, hidden decoration and the sender/body separator. Preserve Unicode, nested links, emoji alt text and line breaks.
- Never turn metadata-only containers into successful text captures.
- Locate actual message media within the message content even when outside a paragraph. Do not treat avatars/sender icons or inline text emoji as message attachments.
- Use the same extractor for first parse, invalidation, retries and push. An explicit refresh can invalidate cached fields for a requested range without changing the selected conversation.
- Report compact structural diagnostics (source/reason/counts, no message contents) and a meaningful pane-selection source. Bump the agent version so old code is replaced.

### B. Typed capture failures and bounded retries

Keep the existing `MessageRecord` / repository interface, but make probe outcomes explicit:

- CDP exceptions/protocol errors become typed evaluation errors; legitimate JavaScript undefined is not itself an exception.
- Failed or malformed slice responses raise a capture/probe error instead of becoming `[]`.
- Distinguish a valid empty/raced range, valid records with missing bodies, and a failed probe. Log the range and diagnostic reason without logging private message bodies.
- Retry a range at most four times, check Stop inside waits, and force-refresh/reinstall at most once when the agent/probe is stale or fails. Never retry a refused private-chat gate into a write.
- After a range exhausts its retries, record the incomplete/error outcome and **advance to later ranges**. Save their complete records normally. Do not mark the cursor/full scan complete while a range is still unreadable.
- Carry capture error / missing counts and diagnostics through `SyncResult`. Failed reads must not masquerade as a successful no-op, including the manual Collect History block.

### C. Visible-first collection and truthful status

- Save the visible conversation before initiating a potentially destructive scroll-to-top phase. Preserve per-range gates and database operation boundaries across both phases.
- Automatic backfill must not keep resetting a currently incomplete visible capture. Retain backfill eligibility until the visible pass succeeds; explicit Backfill remains available but still captures the visible view first.
- Distinguish `capture_pending` from `no_new`; show pending capture as a warning, probe errors as errors, and include partial progress when some messages were saved.
- Measure actual CDP evaluate latency for adaptive browser backoff, excluding deliberate waits and unrelated work. Pending capture uses the configured active heartbeat, not the long idle delay. Genuine slow probes can still back off.
- Keep `[text not captured]` for historical rows whose payload really is unavailable. Continue refusing new metadata-only archive rows.

### D. Clear means delete, not pause or implicit restore

- Keep soft-delete tokens and dedupe against hidden old messages.
- Do not implicitly unpause disabled/paused collection, change the DB connection, or reset private-chat verification to an unsafe state.
- Tests must invoke the real Clear bridge/repository path, then send new DOM text and verify it is saved. Also verify old visible rows remain hidden after Collect now and Backfill, and Ctrl+Z still reverses the clear.
- Explain this behavior in Clear's confirmation/help text: new messages continue to be collected; Ctrl+Z restores cleared history.

## 4. Verification plan

1. Add DOM/protocol integration using an actual DOM implementation and the shipped generated install/state/slice expressions. The adapter may replace the transport/browser host, not the expression code or parsed message records.
2. Feed those results through the real CDP decoder, ChatParser, Collector, HistoryService, Bridge and temporary SQLite files. Cover the user's two-text-message/new-only-clear sequence.
3. Test normal text, body text without the exact payload class, nested text/newlines/emoji, metadata-only nodes, sibling media, invalidated cache, and hostile/mismatched panes.
4. Test probe exceptions and malformed responses, bounded fresh retries, later ranges surviving an unreadable first range, genuinely new rows after Clear, hidden rows staying hidden, and correct undo.
5. Test visible-first capture when scroll-to-top removes/unloads the payload; make the test fail under the old ordering.
6. Test that retry/settling waits do not turn 1,500 ms into 20,000 ms, while real slow evaluate latency still throttles.
7. Run the existing Python/JavaScript suites and record exact results and environmental skips. Do not overwrite the prior design's historical test record.

## 5. Implementation and verification record

Completed 2026-09-08. No application code was changed before this document was written.

### Implementation

- Agent **v11**: scoped payload-element / structural-message-content extraction; metadata, sender, clock, controls, icons and avatars are excluded; media siblings are recognized. Incomplete or explicitly refreshed ranges are re-parsed. Direct text-node reading preserves nicknames containing unread-badge digits.
- Production CDP decoder raises explicit JavaScript/protocol failures rather than returning `None` for them. Slice decoding rejects failed/malformed responses and carries privacy-conscious structural diagnostics (not message contents).
- Four bounded attempts per range, one forced agent reinstall for failed probes, per-retry private-chat checks, and later-range continuation. Complete later messages are saved even if an earlier range fails. Cursors remain incomplete for unfinished captures.
- Visible-first collection precedes a requested automatic/manual backfill. Incomplete visible passes retry in place rather than repeatedly scrolling away the content. The same operation lock protects both phases.
- Distinct warning/error statuses replace false “No new messages” results. The manual Collect History block reports incomplete capture as incomplete, not success. Actual probe latency controls backoff; deliberate retry/settling waits are excluded. The UI includes Capture agent, Last read, and Text source diagnostics.
- **No database schema change, no tombstone removal, and no implicit restoration.** The real Clear bridge path, subsequent incoming/outgoing text, manual backfill, observer push and Ctrl+Z behavior are tested. The previous DB Connection protections remain in place.

### Reproducible verification

```sh
npm ci --prefix tests
REQUIRE_DOM_TESTS=1 QT_QPA_PLATFORM=offscreen \
QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q

for test in tests/test_*.js; do node "$test" || exit 1; done

git diff --check
```

- **Python: 832 tests run — 831 passed, one skipped, no failures** (161.411 s).
  The skip is the existing Qt WebEngine layout smoke test: this sandbox lacks
  `libGL.so.1`. The broader suite still emits pre-existing resource/pending-task
  warnings in other tests; this is not described as a warning-free run.
- **JavaScript: 329 passed, zero failed across 15 scripts**, including agent
  **48/48** and history-panel integration **38/38**.
- New `tests/test_capture_after_clear.py`: **22 tests**, including **17 DOM /
  protocol / storage integrations** and **five decoder/timing contract tests**.
  They execute generated install/state/slice expressions in `capture_dom_host.js`
  with jsdom, pass CDP-shaped replies through the production decoder and parser,
  and use the actual service, collector, bridge and temporary SQLite database.
  No marker-based fake returns prebuilt message records for these integrations.
- The Clear regression verifies `2 visible → Clear → 0 visible → new text → 1
  visible`, with the original two rows still hidden. Separate tests cover direct
  outgoing text, real MutationObserver push, explicit Backfill not undoing Clear,
  and a single global undo restoring old rows while retaining the newly saved row.
- Native text-node/HTML parsing exposed the previously missed unread-badge nick
  corruption and detects paragraph/sibling layout differences. The same suite
  tests metadata-only refusal, empty primary span with a ready sibling, nested
  text/links/newlines/emoji, malformed/permanently failed probes, one-shot agent
  repair, later-range progress, and visible capture before a destructive scroll.

The dependency is **development-only** (`tests/package.json` / lockfile).
`node_modules` and browser/download caches are excluded from Git. `REQUIRE_DOM_TESTS=1`
ensures CI cannot silently skip these integrations when the dependency is absent.

### Live validation boundary / next diagnostic

The user's live Chrome page/archive were not accessible and have not been claimed
fixed in-place. Chromium installation was attempted, but its download endpoint
failed TLS connections; jsdom is a DOM/protocol integration host, **not Chrome
layout/CDP transport validation**. This limitation is separate from the passing
integration results above.

After applying the changes and restarting the app, confirm **Capture agent v11**.
Keep the original private chat open and send/receive a genuinely new message.
Cleared messages should remain hidden. If capture still fails, the new Last read,
Text source and Error fields identify the actual failed range/response instead
of repeating an ambiguous “awaiting retry” message. A sanitized DOM snippet or
those diagnostics would be needed to verify any still-different live layout;
no private message body or user database needs to be guessed or fabricated.
