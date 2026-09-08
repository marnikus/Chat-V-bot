# Person History: nested attachment capture and live media delivery

Date: 2026-09-09
Branch: `arena/01a08228-chat-v-bot`
Baseline: `8f950e1d5ff98aae6ae3b590aa1ccfdbf29a8db2`
Status: **Implemented and verified.** This design was written before application-code changes.

## 1. Requirement and scope

The user cannot save or display media in Person History and supplied the actual
message markup: an outgoing message from a previously declared self nickname,
with an `app-chat-image .image-wrapper img[loading=lazy]` inside
`.message-body .message-text`. The image source is an HTTPS, percent-encoded
GIF URL and the original displayed time is `23:29`.

Save supported chat images/GIFs, preserve their original URL, sender, direction,
time and any caption, and display the locally saved file in Person History.
Do not collect avatars, SVG status icons or inline emoji as attachments. Do not
require Clear History to recover still-visible, previously uncaptured messages.

All earlier protections remain controlling: verified private-chat ownership,
trusted (not hardcoded) historical-self names, Create versus Load separation,
transactional archive switching, full clean-slate Clear/Delete, isolated Undo,
per-person counters and chronological global undo. This repair does not access
or use Undo snapshots to discover media. No live user database was supplied.

## 2. Research and reproduced failures (before application-code changes)

### A. Supplied DOM is discarded before the downloader

The exact supplied message was loaded into the existing development DOM/CDP
host, inside a verified private-chat fixture. The **shipped generated probes**
and real `ChatParser`, `Collector`, service and SQLite write path were used.
Historical-self identity was declared through trusted identity data.

Agent v13 returned:

```json
{"dir":"out","from":"Пошлый01","time":"23:29","kind":"text",
 "text":"","media":null,"capture_pending":true,
 "capture_reason":"payload_empty"}
```

The collector consequently reported `capture_pending`; SQLite contained **zero
messages and zero media rows**. No network download could even be attempted.

Cause: `payloadParts()` selects `.message-text` as the text element and rejects
**every descendant image** with `isAncestor(span, candidate)`. That exclusion
was intended for inline emoji, but the new layout nests real attachment
components in the same text element. Existing media fixtures used the old
layout, with `app-chat-image` outside the selected text span.

### B. Saved media is still sent to live history as pending

A separate reproduction used a supported media record and a successful,
controlled download through the real repository/cache/collector path:

```
SQLite query after the tick: state=cached, path=<person>/gifs/<date>_001.gif
history_appended event:     state=pending, path=""
```

Cause: append records are assembled **before** `process_pending()` runs and
then emitted unchanged. The frontend intentionally renders only local files,
so this stale snapshot produces a restore marker even though bytes were saved.
An idle heartbeat also drains remaining downloads without any media-ready
notification. The existing `media_ready` signal is only used for explicit RPCs.

### C. Failure feedback and stale replies

`MediaStore.path_for()` omits `fail_reason` and can return `state=cached` with no
usable path if the file vanished. The frontend logs a generic unavailable
message and only updates its model when a nonempty path arrives. It cannot
clear a stale path on failure/eviction. Media replies, unlike history replies,
also lack the generation tag/check needed across Clear/Delete/Load.

The downloader already has page fetch, authenticated Python and browser-network
fallbacks. These are not replaced speculatively: the supplied DOM failure
happens before them. Network/CORS failure and retry behavior must remain tested.

## 3. Proposed structure and behavior

### A. Agent v14: classify attachment components, not text ancestry

1. Resolve `.message-content` (old layout) or `.message-body` (new layout) as
   the message payload scope, retaining the existing safe structural fallback.
2. Use a small shared attachment-container predicate for `app-chat-image` and
   `.image-wrapper`. A real attachment inside `.message-text`, `span.message`
   or `[data-message-text]` is eligible. Inline emoji/emoticons and metadata
   remain excluded. No dependency on generated Angular `_ngcontent` IDs.
3. Keep body text/caption extraction separate: skip attachment alt labels and
   component controls, preserve actual caption text/links/line breaks/emoji.
4. A present attachment component without its `<img>` or URL is explicitly
   `media_url_pending`, even when its caption has already rendered. Retry it
   rather than storing a misleading caption-only record.
5. Preserve the existing `currentSrc`/`src`/`data-src` behavior and mutation/
   reset cache invalidation. Set both JavaScript and Python agent versions to
   14 so an already installed v13 agent is replaced.
6. Existing empty-slot repair remains available for old blank records. Do not
   guess that an arbitrary historical text message was originally a caption;
   no broad/destructive message rewrite or schema migration is needed.

### B. Cache state is the authoritative delivery source

Add an optional, isolated media-state callback to the plain `MediaStore`.
After a cache write or terminal state change is committed, publish a small
media-info object (ID, state, local path, original URL, kind, bytes and error).
Callbacks must not break downloads; support synchronous and asynchronous
listeners. Do not send media bytes through QWebChannel.

- The bridge subscribes once to the attached service's store and forwards
  these changes through the existing `media_ready` signal, tagged with the
  service generation. A callback from a replaced service is ignored.
- Explicit media path/restore/copy responses carry the same generation.
- Before emitting newly appended rows, the collector refreshes their media
  fields from the current store. This closes the event-before-row race on an
  initial tick and avoids sending a known-obsolete pending path.
- A push can still publish a pending row immediately; the subsequent downloader
  event updates it without another message or a manual history reopen.
- Idle batches and action-stack downloads use the same cache callback, so
  completion is not tied to a new chat message or one particular collector
  branch. Shared media IDs update every matching loaded row, not other IDs.

No separate background downloader or new persistent registry is introduced.
The existing archive-operation lock continues to serialize cache work against
Clear/Delete/Load, and no post-reset task may reinsert deleted tracking state.

### C. Honest state and local-only presentation

`path_for` and history DTOs expose the actual download failure reason and a
truthful missing-file state. A blocked explicit restore explains whether media
caching is disabled, paused or unavailable, without changing user settings.

Person History accepts only current-generation media updates. Update both
loaded and buffered rows, including explicit empty paths and failure states;
do not keep showing a stale local file. Render the saved file with the existing
cross-platform `file://` conversion. Preserve scroll position and the Images
toggle. Search-result path updates retain GIF kind and copy/error behavior.
Pending media is visibly waiting; failed/missing media retains an actionable
retry marker with the concrete reason. Never silently use a remote URL as proof
that the image has been saved. A network/permission failure is not reported as
successful archiving of media bytes.

## 4. Regression and verification plan

1. Save the supplied message as a source fixture. Run generated probes against
   a real development DOM; assert GIF URL, sender, direction, `23:29`, no leaked
   icon/alt text and no pending flag. Repeat for incoming/outgoing images and
   captions, old/new layout, emoji/avatar exclusion and delayed component/src.
2. Real parser/service/SQLite/cache integration using controlled fixture bytes:
   assert URL registration, per-person GIF file, byte identity, metadata, live
   event path, normal page DTO, idempotent repeat scan and restart.
3. Clear and Delete then re-collect the same media DOM; isolated undo and fresh
   session-count semantics stay intact. Reject unknown authors and stale
   pre-reset pushes. Never request the example's actual private image bytes.
4. Initial tick, observer push, unchanged/idle cache batch and explicit restore
   all deliver saved paths. A download completing before its row is rendered
   must not strand that row in pending state.
5. Use real bridge signals and the real frontend store/view to prove pending →
   cached image, failure diagnostics, retry, missing files, Images off, buffered
   rows, search-result updates and rejection of stale-generation media events.
6. Preserve existing CORS/Python/network fallback, size caps, media layout,
   private-chat, historical-self, database safety and clean-slate tests.
7. Run the full Python suite with `REQUIRE_DOM_TESTS=1`, every JavaScript suite,
   compilation and whitespace checks. Report unavailable real-browser/layout
   checks separately; DOM tests and controlled bytes are not a live chat test.

## 5. Implementation and results

Completed 2026-09-09 on the stated baseline.

### Implemented

- Agent v14 now recognizes the exact supplied nested GIF component. Message
  body scope, attachment classification and caption extraction are separate;
  avatars, metadata and inline emoji remain excluded. An attachment component
  awaiting its image/URL is retried even when a caption is already present.
- `media_info()` in `backend/media_store.py` is the shared, byte-free DTO for
  repository live rows, history queries, cache events and media RPCs. Failed,
  evicted or missing files never advertise a usable local preview path.
- Cache success/failure/skip/eviction publishes a post-commit update through an
  optional callback, isolated from storage and supporting sync/async listeners.
  The bridge forwards it on `media_ready` with the active service generation;
  replaced-service events are dropped. Explicit media RPCs are tagged too.
- The collector refreshes media DTOs before publishing new rows, closing the
  initial-tick event-before-row race. Push, idle-batch and explicit-restore
  completions now update already rendered history through the same channel.
- Person History updates both loaded and buffered rows, accepts explicit empty
  paths, and rejects stale-generation media updates. Search-result updates reuse
  the normal media renderer, including GIF, copy and error/restore handlers.
  Waiting state and concrete errors are visible without substituting a remote
  image for a saved file. Images-off and scroll state remain respected.
- No schema, archive/Undo separation or download transport redesign was needed.
  Existing per-person storage, media fallback paths and all clean-slate reset
  behavior remain in place. User configuration was not modified.

### Verification

```sh
npm ci --prefix tests
REQUIRE_DOM_TESTS=1 QT_QPA_PLATFORM=offscreen \
QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
for test in tests/test_*.js; do node "$test" || exit 1; done
git diff --check
.venv/bin/python -m compileall -q backend tests
```

- **Python: 902 tests run — 901 passed, one skipped, no failures** (185.937 s).
  The existing Qt WebEngine layout smoke is skipped because `libGL.so.1` is
  unavailable. Existing broader tests still emit resource/pending-task warnings;
  this is not reported as a warning-free run.
- **JavaScript: 350 passed, zero failures across all 15 scripts.** Agent tests:
  **54/54**; real history-panel module integration: **53/53**.
- **21 new Python regressions** in `tests/test_person_history_media.py` execute
  the supplied HTML through generated probes and real parser/service/SQLite/
  cache/bridge code. A complete, controlled GIF is saved byte-for-byte in the
  person's GIF directory. The actual UI model/view receives the database DTO
  and renders its correctly escaped local file URI, not the CDN URL.
- Verified original sender, direction, `23:29`, original encoded URL, caption
  fidelity, lazy-host/URL retries, avatar/emoji exclusion and stranger rejection.
  Repeated collection stays idempotent; Clear/Delete re-collect the same media
  fresh with session totals `1 → 0 → 1` and without calling the Undo reader.
- A 28-attachment DOM case proves the first 25 downloads and the remaining
  three idle-heartbeat downloads all publish their cache state. Observer-push,
  initially disabled downloads, explicit restore, missing files, size limits,
  network fallback, callback failures and offline restart are covered too.
- Ten new frontend integrations cover pending → saved GIF, actual failure
  reason, stale-generation rejection, eviction/retry, Images off, buffered and
  shared IDs, search-result error/copy/restore behavior and stable message totals.
- Diff, Python compilation and new-file whitespace checks pass.

### Limits and applying the fix

This is exact-markup/generated-DOM/protocol and controlled-resource validation,
not a connection to the user's live Chrome or archive. No actual user image
bytes were recovered. The environment cannot run the Qt WebEngine layout check;
Windows preview URI handling is tested in JavaScript, not in a live Windows app.

After applying the code, restart and confirm **Capture agent v14**. Open the
same verified private chat with media downloads enabled and use **Collect now**.
Previously uncaptured, still-visible media can be collected without deleting
history. Existing failed/missing downloads retain an explicit restore control
and explain failure (host/network, file-size cap, disabled/paused cache, missing
file or disconnected browser). Expired source content cannot be invented.

The changes are saved locally; publication requires a separate user push request.
