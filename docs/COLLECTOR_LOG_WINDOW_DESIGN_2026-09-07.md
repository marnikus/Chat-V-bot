# Collector-local History Log window

Date: 2026-09-07

## Goal

Add a small **log block inside the Chat Message Collector window** that shows
only history/parsing attempts for that window: what the collector saw, which
partner it tried, whether it detected My Nick, gate refusals, archiving
results, backfill attempts. It must not be mixed into the global Log Console.

## Layout

Inside `#winCollector` after `.collector-rows`:

```
<div class="collector-log-head">
  History log          [Clear]
</div>
<div class="collector-log" id="collectorLog"></div>
```

`#collectorLog` scrolls independently and is capped at 400 lines in the UI.
It is part of the same sash window, so it is dragged/resized with it.

## Backend → UI

* `Collector.collector_log` signal (JSON): `{ts, level, message, nick}`.
* `Bridge.collector_log` re-emits it; `attach_history()` connects the signal.
* `app.js` connects `b.collector_log → CollectorPanel.onLog(json)`.
* `Collector._log()` emits a line. It is **not** the general `logging` module
  — these are UI-level, user-facing attempts.

### When lines are written

| Event | level | example |
|---|---|---|
| Agent old/absent, re-installed | info | `Re-installed the in-page agent (v8)` |
| Active tab not private | warn | `Active tab is "room", not private` |
| Refused: group tab | warn | `Refused: 17 participants, not a private chat` |
| No partner nick | warn | `No partner nick in the active tab` |
| My Nick auto-detected | info | `Detected My Nick as "Хорошо Все"` |
| Partner remembered | info | `Partner "ники": archive_only / known / new` |
| Gate refused | warn | `Private-chat gate refused "ники" (strangers)` |
| Archived new lines | success | `Archived 7 new message(s) (total 7)` |
| Sync failed | error | `Sync failed for "ники" (…)` |
| No new messages | info | `No new messages (unchanged_cursor, page count 7, added 0)` |
| Manual backfill | info | `Manual backfill requested for "ники"` |

## Tests

* `tests/test_history_panels_boot.js` — `the collector keeps its own parsing
  log in this window`: renders a log line, Clear empties it.
* `tests/test_collector_state.py` — `test_the_window_gets_parser_and_nick_
  attempt_entries` and `test_refusals_are_logged_too`.
