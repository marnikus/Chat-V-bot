# Clickable partner in the Collector → Person History + DB highlight

Date: 2026-09-07

## Goal

In the **Chat Message Collector** window the *Partner* nick becomes clickable.
One click:

1. opens the **Person History** window for that partner, and
2. brings the **Full User Database** window into view and highlights that
   partner's row there.

## Why

The user has just confirmed that the archive now saves messages. The natural
next step when the collector shows a partner is to jump straight to the
conversation and confirm it is in the database — without hunting through the
two archive windows.

## Behaviour

| Action | Result |
|---|---|
| Hover `Partner` | underline + brightens (cursor pointer) |
| Click `Partner` | History window shown and `HistoryStore.openPerson(nick)`, User DB window shown, DB filtered to `nick`, matching row flashed green |

## Implementation

### `ui/js/collector-panel.js`

* `renderRows` draws `Partner` with `.collector-nick-link` (a `<span>` — no
  navigation, no page reload) carrying `data-nick`.
* A delegated click listener on `#collectorRows` calls `openPartner(nick)`.
* `openPartner(nick)`:
  1. `SashGrid.showWindow('history')` and `showWindow('userdb')` (un-hide a
     hidden window without touching layout);
  2. `HistoryStore.openPerson(nick)` — existing lazy-loaded history;
  3. `HistoryDb.highlightNick(nick)` — filter the database and flash the row;
  4. logs a one-line message in the Log Console.

### `ui/js/sash-grid.js`

New `showWindow(winId)` un-hides a panel and calls `_syncHidden()`. It is the
existing "show a hidden window" operation, extracted so other windows can
request it (Block Config uses its own toggling code).

### `ui/js/history-db.js`

`highlightNick(nick)`:

* sets the database search box + `this.query` to the nick (so the row is
  guaranteed at the top after reload);
* remembers `_flashNick`;
* `render()` flashes the matching `.userdb-row` with the existing
  `row-flash` animation after the page arrives.

### `ui/css/history.css`

`.collector-nick-link` — accent colour, pointer cursor, dotted underline.
Database reuse: `tr.row-flash` (already in `table.css`).

## Tests

`tests/test_history_panels_boot.js`

* `the partner name is a clickable link to its history` — the link exists,
  a click shows both windows, calls `history_open`, and reloads the DB with
  the nick as query.
* `the highlighted person is flashed in the database row` — the page answer
  renders a `.userdb-row` with `row-flash`.
