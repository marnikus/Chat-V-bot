# Historical self nicknames and restoring cleared history

Date: 2026-09-08
Status: **Implemented and verified. Design was written before application-code changes.**
Baseline: `8aec80a8869b3b02927736725229ee8d62c8d36d`
Branch: `arena/01a08228-chat-v-bot`

## 1. Report and clarified intent

The new screenshot is not a `capture_pending` failure. Agent v11 reports two
messages/two participants/one pane, but the gate refuses `Пошлый01` as a
stranger while the configured My Nick is `Хорошо Все` and the partner is
`Катя462`. The user confirmed:

- `Пошлый01` is their **previous** nickname.
- These are the **same two messages that were cleared**, and they want them
  restored/re-imported into Person History.

There are therefore two independent requirements: recognize a previously
declared self identity without admitting actual strangers, and provide an
explicit way to restore cleared rows. Preserve automatic Clear behavior: a
background tick/Collect now/Backfill must not silently undo a deletion. A
separate **Restore cleared** action is authorized by the latest clarification.

## 2. Research and reproduction

The current gate compares message author strings with only the currently
configured nickname. It ignores:

1. `state.my_nick_recent` in config — the nicknames the user explicitly entered
   through the existing My Nick control;
2. `persons.my_nicks` in the archive — previously used self-nickname metadata,
   retained even when that person's messages are cleared;
3. the distinction between a configured nickname and the current self in the
   selected browser pane.

Reproduction using the actual generated JS in the DOM/protocol host, the real
HistoryService/repository, and a temporary SQLite file:

1. Capture two private messages with self `Пошлый01` and partner `Катя462`.
2. Clear those rows.
3. Change only the browser roster/current My Nick to `Хорошо Все`, leaving the
   historical outgoing author `Пошлый01`.
4. The collector returns `group_tab`. The archive still holds
   `persons.my_nicks=['Пошлый01']`, config has both explicit nickname entries,
   and SQLite contains two hidden rows. The gate ignores both identity sources.

Clear uses soft-delete tokens. The unique/dedupe keys deliberately keep ticks
and backfill from re-adding those exact rows. Ctrl+Z can reverse the clear, but
there is no direct per-person Restore cleared control after intervening edits.
The zero-row view gives no indication that messages are recoverable but hidden.

The user's actual DOM/database are not accessible; the reproduction matches the
reported names and failure using controlled data, not access to their private
messages. Do not infer ownership of every outbound-looking unknown author.

## 3. Identity contract

### Trusted self names

Use one `verify_private` identity resolver for heartbeat, slice retries,
backfill, manual Collect History, and push:

- currently configured My Nick (explicit user declaration);
- explicit My Nick history from config, validated as a list of nick strings;
- that conversation's `persons.my_nicks` metadata;
- the selected pane's current self **only with scoped roster evidence**: the
  bold self row and exact two-member roster agree with the active private peer.

Do not learn self aliases from arbitrary author strings or fields supplied in
a push payload. Push may use only self names approved by a preceding live gate;
an unknown identity change requires a new verification pass. No personal name
is hardcoded into defaults or a global allowlist.

### Two participants, possibly more historical spellings

The two identities are self and the exact active partner. Known historical
self names are the same identity, not a third person. All other authors remain
strangers, regardless of `dir='out'` or visual color. The existing optional numeric
participant-counter guard remains configurable for legacy layouts; disabling
that numeric hint never disables actual author/roster validation. Scoped self
detection still requires an exact two-member roster/count. Main-room/group/title-
mismatch/ambiguous-roster/missing-author checks stay closed. Legacy agents or
test adapters without scoped roster evidence do not gain authority to override
an explicitly configured name.

Known self aliases can occur on a general-background historical line after a
site nickname change. Normalize the record's direction/fingerprint to the
verified self/partner identity before dedupe, while preserving `from_nick`,
text, timestamps, media and existing stored rows. Do not rewrite historical
sender names to the current nickname. Keep current profile display distinct
from historical sender names and retain previous user configuration.

Agent v12 will report scoped self/roster provenance for this decision and UI
diagnostics. A current configured-vs-browser name mismatch must be explained,
not mislabeled as a third participant.

## 4. Explicit restoration contract

Add **Restore cleared** to Person History, enabled only when that person has
recoverable cleared messages. The empty view/header shows the cleared count.

- Restore existing rows **in place**, not INSERT duplicate message copies.
- Target only that person's Clear operations. Individual message deletions and
  a deleted person remain deleted.
- New Clear tokens receive a `clear:` purpose prefix (no new SQLite columns).
- Recognize old unprefixed Clear tokens from existing global undo commands for
  the same person. Unknown unprefixed deletion tokens are not guessed to be Clear.
- The operation does not require the current Chrome chat: it unhides previously
  archived data, as existing undo does. Any subsequent DOM text repair still
  goes through the full private-chat gate.
- Record one reversible `archive/restore_cleared` command in the existing global
  chronological history. Its compact snapshot contains row IDs grouped by their
  prior clear token, never message bodies/media bytes. Undo re-hides only those
  rows; redo restores only those rows. Messages collected afterward are untouched.
- Keep the operation inside the shared archive boundary and bind its undo to
  the archive path. Never apply stored row IDs to a different database.
- No automatic reset/load/create of a database. No implicit restoration during
  Collect now or Backfill. If rows were hard-purged rather than soft-cleared,
  they must be re-extracted or restored from the existing DB backup feature.

The new control is an explicit edit, not a second undo timeline. Ctrl+Z remains
the single chronological undo mechanism for it and all other editable surfaces.

## 5. Verification plan

- Reproduce old-self rejection before changing the gate.
- Unit gates: current self, known old self from each trusted source, stale config
  vs scoped browser self, untrusted global self fallback, unknown inbound/outbound
  author, actual third participant, wrong peer/title, missing evidence.
- DOM/protocol/service tests with reported names: capture → rename → clear → gate
  succeeds but background collection keeps rows hidden → explicit restore gives
  two original IDs/full bodies → new messages append → undo/redo restore affects
  only the original IDs. Cover historical CSS direction changes and normal push.
- Restore safety: individual deletion stays hidden; other person/other DB
  unaffected; empty/double restore is a no-op; legacy Clear recognized; unknown
  legacy tombstone refused; metadata and media references unchanged; no duplicates.
- UI tests: cleared-count notice, Restore enablement/confirmation, effective and
  configured self diagnostics, explicit restore call and refresh, no per-surface
  undo controls.
- Run the existing full Python and Node suites. Preserve prior DB Connection,
  capture, retry, stop, private-scope, text recovery and Clear regressions.

## 6. Implementation / verification record

Completed 2026-09-08. No application source was edited before this design was written.

### Implemented behavior

- One identity resolver is used by heartbeat, full/incremental reads, retries,
  backfill, manual Collect History and push. The inputs are the existing
  declared My Nick history, the selected conversation's self-nickname metadata,
  and validated pane-roster evidence. **No personal nickname is hardcoded.**
- Agent **v12** reports current-self provenance and roster nicknames. Historical
  self names remain original `from_nick` values; their direction/fingerprint is
  normalized to the already verified identity before dedupe. Missing sender
  data remains incomplete rather than being assigned a guessed author.
- The current browser self and configured nickname are displayed separately;
  the configured input is not silently overwritten. Unknown inbound/outbound
  names and forged push alias declarations remain rejected.
- **Restore cleared** is enabled by an authoritative cleared-row count, with
  an explanatory empty-state notice. It restores original rows in place and
  keeps metadata, media references and individual deletions intact. It neither
  requires a live chat nor resumes paused/stopped collection.
- Future Clear tokens use `clear:`; existing unprefixed Clear tokens are
  recognized from the global undo commands. Unknown old tombstones and deleted
  people are not silently restored.
- Restoration records compact ID groups in the existing `archive` undo stream.
  Undo/redo changes only those IDs and is refused on a different DB path.
  Visibility changes and counter updates are transactional. Failed restore undo
  retains the global index; undo/redo waits while an archive edit is in flight.
- No new SQLite schema, no parallel undo stack, no DB connection change and no
  implicit undelete from normal Collect now/Backfill.

### Verification

```sh
npm ci --prefix tests
REQUIRE_DOM_TESTS=1 QT_QPA_PLATFORM=offscreen \
QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
for test in tests/test_*.js; do node "$test" || exit 1; done
git diff --check
```

- **Python: 865 tests run, 864 passed, one skipped, zero failures** (174.074 s).
  The existing Qt WebEngine layout smoke test is skipped because the sandbox
  lacks `libGL.so.1`. Other legacy tests emit their existing resource/pending-
  coroutine warnings; this is not claimed to be a warning-free run.
- **JavaScript: 335 passed, zero failures across 15 scripts**, including agent
  **49/49** and history-panel integration **43/43**.
- Added **33 tests** in `tests/test_history_identity_restore.py`: 12 pure
  identity cases and 21 DOM/protocol/SQLite/bridge integrations. They cover the
  reported former/current nickname pair, archive-only identity evidence,
  declared config history, historical background/direction changes, stale config
  versus scoped self, new messages, explicit restore, exact metadata/ID/media
  preservation, legacy Clear compatibility, individual deletions, other people,
  repeated restore, undo/redo isolation, wrong-DB refusal, rollback and undo races.
- The reported reproduction now goes from two hidden rows + `group_tab` to two
  hidden rows + verified `no_new`; explicit Restore returns **the same two
  original rows**, not duplicate inserts. Appending a new message afterward and
  undoing Restore keeps that new message visible while re-hiding only the old two.
- A full-suite compatibility check found the existing numeric-counter override;
  it was retained without allowing a third actual author or a mismatched roster.

### Applying / live-data limits

After applying these changes and restarting, confirm **Capture agent v12**.
Open `Катя462` in Person History and use **Restore cleared (2)**. Collect now
continues to respect Clear; Restore is the explicit recovery action. The
collector's known previous names should include `Пошлый01` when it was already
recorded by My Nick/history metadata. If the declaration is genuinely absent,
use the existing My Nick field to declare the previous name and then return to
the current name; do not whitelist an unrelated author.

No live user database/Chrome session was accessed. The tests execute the shipped
expressions through the jsdom/protocol host and real SQLite/bridge logic, not a
live Chrome layout/session. Restoration of the user's actual two messages is
therefore not claimed completed here. Hard-purged rows or missing legacy Clear
provenance require re-extraction/backup recovery rather than guessed undeletes.
