# Area A — CDP & Browser Boundary Port

Source design dated **2026-09-16**, supplied as code/text by the owner and
integrated **2026-09-19**. This is the reconstructed, repository-adapted design
record, not a claim that this checkout ran the source author's measurements
on September 16. Source workstream label: `seam/cdp-browser-boundary`.
Actual integration branch: `arena/01a0bac1-chat-v-bot`.

**Local decisions, corrections and measured results:**
[Area A transfer record](../2026-09-19-area-a-integration/AREA_A_TRANSFER_2026-09-19.md).
The six-area roadmap remains
[Round I](../2026-09-19-round-i-seams/ROUND_I_DESIGN_2026-09-19.md).
No Areas B–F are implemented by this transfer.

## 1. Intent and safety

Harden the browser boundary without features, schema changes or wire-format
changes. Keep the backend public API snapshot, QObject constructor, command
ordering, event fan-out and collector statuses. Preserve the only private-gate
entry point, `backend.chat_parser.verify_private`, used by tick, push and
explicit collection. The supplied malformed-author hardening is an explicit
behavior change: unreadable author lists now refuse rather than crash or
accidentally permit an archive write. Valid-state judgments remain unchanged.

## 2. Five seams

### 2.1 CdpWire — acquisition separated from protocol policy

`backend/cdp_transport.py` defines structural `CdpConnection`, `CdpConnector`
and `TabDiscovery` protocols and frozen `CdpWire(connector, discovery)`.
Production uses `WebSocketConnector`, `WebSocketConnection` and
`HttpTabDiscovery`. Network-library imports are deferred, scoped to this
**backend** module. HTTP in services/stores is outside this browser boundary.
The connection adapter converts library-specific peer closure into EOF;
cancellation and unrelated errors still propagate.

`cdp_client_transport.py` continues to own framing, pending IDs, domain enables
and lifecycle policy, now over `client.wire`. `CDPClient.with_wire` is additive;
adding a constructor parameter would violate the frozen signature. Round I's
existing `client_with_transport` remains supported through a combined-port
adapter. This integration does not delete that previously shipped helper.

The scripted fake returns a dict reply, raw malformed frame, or None (hangup).
The local version uses a queue instead of busy-polling and wakes on close.
Keep the historical `_ws`/`send` testing seams. Peer hangup still leaves pending
requests registered until timeout/close; failure of pending futures on close
is a separate lifecycle change, not hidden in this extraction.

### 2.2 Typed private gate

`probe_results.py` decodes `TabState`, `PaneAuthors` and `ScrollPos` values.
`private_gate.py` judges them. The public dict-signature door decodes once;
non-dicts still mean absent state even when a string contains valid JSON.
Refusal precedence remains not_private → no_partner → title_mismatch →
self_chat → no_author_data → strangers. Empty title still falls back to the
partner, and valid empty author lists retain the old behavior.

The transferred decoder rejects malformed present lists. Integration also
handles non-finite numeric metadata instead of allowing it to crash a gate.
`PrivateCheck` and `title_matches` retain their public module identity for API
inspection/serialization. No second copy of the gate is maintained.

Deferred: full typing of sync/scroll state consumers. Do not introduce unused
`ScrollSlice` types merely to check a planning box.

### 2.3 Selector registry and standalone mirror

`backend/selectors.py` owns 20 fixed collector/scroll selectors. The agent has
an identical mapping between marker comments; Python scroll probes use named
JSON substitutions. A mirror keeps the JS source directly executable in the
page, in Node and via navigation injection, without a build step.

Parity checks include exact registry/doc-table equality, canonical mirror
format, known `SEL` references, and the supplied grandfathered Python-site
inventory. The five remaining sites are criteria_engine, media_handler,
message_injector_field, message_injector_send and scroll_parser_model. This is
not yet centralization of every site selector or configurable user selector.

### 2.4 Golden DOM scenarios

Eight synthetic `tests/dom_stub.js` fixtures: private two-nick, room, third
author, emoji/quoted nicks, image/GIF, trimmed head, hidden stale pane and empty
pane. Run the real agent; freeze state and all slice records including
fingerprints. Local pre-transfer observations matched all supplied fingerprint
sequences before selector migration; post-migration approvals remain identical.

No live authenticated captures were supplied. These canaries detect local
regressions against modeled page shapes, not remote site drift or real-browser
layout behavior. Approvals must not be refreshed to conceal a regression.

### 2.5 Shim retirement ladder

`legacy_shims.SHIMS` inventories 12 compatibility paths and replacement homes.
Each warns with `DeprecationWarning`; exports remain intact. Production importer
inventory permits the existing `app/bootstrap.py → backend.bridge` edge only.
The integration uses AST inspection rather than a regex that can miss import
aliases or multiline syntax, and validates replacement targets as well as names.

Actual deletion needs separately approved compatibility retirement and snapshot
review. It is not automatically authorized after other areas merge.

## 3. Characterization and phase status

The supplied design reports 768 oracle cells and 14,076 comparison judgments.
The local oracle retains 768 cells; a separate local valid-input differential
run compared 5,760 judgments with zero differences. These are distinct runs,
not additive claims about one test. Source-reported measurement is not treated
as freshly verified evidence. See the transfer record for all local results.

| Phase | Integrated evidence / remaining work |
|---|---|
| P0 | Selector/shim inventory and synthetic corpus present; real captures pending |
| P1 | Existing suites run before edits, 768-cell oracle, golden approvals, wire replay; gate branch coverage measured locally |
| P2 | CdpWire, typed gate boundary and fixed-selector mirror; frozen snapshot unchanged |
| P3 | Error/cancel/EOF coverage; real adapter tests added locally; gate/decoder mutation measured, other parser/command scopes pending |
| P4 | Gate extracted; shims deprecate/inventory only; sync/scroll typing pending |
| P5–6 | Parity/golden canaries added to staged CI template; activation and continuous ratchets still pending |

## 4. Quality and rejected shortcuts

No snapshot refresh to hide removed public symbols. No pre-evaluated guard
list replacing early refusal ordering. Do not strip the `tab` value: accepting
`" private "` would loosen the gate. Do not replace production HTTP-adapter
tests with a discovery fake that already knows a non-200 response is empty.
Do not label synthetic fixtures captures or the staged workflow active CI.

New code follows RULE 16 limits, with registered measurements in the existing
gate; small protocol/selector leaves are intentionally below RULE 18's preferred
file band rather than padded. Authoritative measured metrics and remaining
baseline failures are in `reports/AREA_A_TRANSFER_2026-09-19.md`.
