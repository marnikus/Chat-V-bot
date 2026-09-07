# Bug #2 — failed media cannot be recovered via backfill: ROOT CAUSE — 2026-09-07

Date: 2026-09-07
Status: **RESEARCH (reproduced) — then implemented in the same turn**

> Live report (5th attempt): in a private chat with `глубокаясосуха`
> (My nick `Хорошо Все`) the **sent** webp image at 16:22 was saved to
> History correctly, but the **two received GIFs** (16:24, 16:28) were not.
> Clicking **⬆ Backfill older** changes nothing. This document is the
> audit: every claim below was reproduced against the real pipeline
> (`Collector` → `ChatParser` → `HistoryRepo` → `MediaStore`) before any
> code changed.

---

## 1. Reproduction rig

`tests/repro_bug2.py` drives the *real* collector/repo/media objects with a
CDP-shaped fake that mirrors the user's saved HTML conversation (27 messages,
3 media: 1 outbound webp + 2 inbound GIFs, the exact URLs from the report).

Baseline (downloads succeed): all 3 media cache into
`saved_media/<person>/images|gifs/`. When the GIF downloads fail, the rows
stay `state='failed'` — and the backfill click leaves them exactly there.

## 2. Root causes (each one reproduced)

| # | Root cause | Reproduced as | Why "Backfill older" cannot fix it today |
|---|---|---|---|
| **RC1** | **The per-file size cap is 2 MB.** `HISTORY_DEFAULTS.media.max_file_mb = 2`. Ordinary chat GIFs are 2–15 MB, so every received GIF is downloaded and then permanently `state='skipped'` ("too large"). The small sent webp passes — exactly the reported asymmetry. | 3 MB GIF → `skipped: too large (3145734 bytes, cap 2097152)`; the same file with a 25 MB cap → `cached`. | `recover_media` *does* re-queue `skipped` rows, but the downloader applies the same 2 MB cap and skips them again — forever. The retry works; the policy makes it pointless. |
| **RC2** | **A media line parsed before Angular renders `app-chat-image` is stored as an empty text row** (`kind='text'`, `text=''`, `media_id NULL`). The MutationObserver push fires ~120 ms after the container is added; if the `<img>` is not in the DOM yet, `parseNode` finds neither image nor text. | A saved row `{'kind':'text','text':'','media_id':None}` + a DOM record with the GIF URL → `recover_media` returns **0**, row untouched. | `recover_media`'s candidate query filters `m.kind IN ('image','gif')` — an empty `text` row is invisible to recovery. Worse: when the URL-bearing record is appended later (next push/full read), the **dedupe key differs** (payload ''→URL), so a *second* row is inserted — the user sees the empty slot AND a duplicate. |
| **RC3** | **Recovery links a message to an already-failed media row without re-queuing it.** The same GIF seen before (forwarded gallery file) is `state='failed'`; `recover_media` calls `media.register(url)` (which keeps the old state) and just sets `messages.media_id`. | Message attached to media id=1, `recover_media` reports `changed=1`, media stays `failed`, `recovery_attempts=0`. | The message now points at a dead row; `process_pending` only works on `pending`, so nothing retries until the *next* backfill click happens to match it again. |
| **RC4** | **Recovery only runs inside the scroll-to-top read**, i.e. on the records that pass by during that read — and only when `backfill_older=True`. The *newest* messages (where failed media usually is) are dropped from the DOM by the virtualiser while the pane is scrolled to the top; idle ticks repair nothing at all (`unchanged` shortcut / delta reads start at `dom_count`). | by_key during the top pass lacks the bottom records; the tail records are only in the DOM after `restoreScroll`, which happens *after* all recovery calls. | The rows the user cares about (the last messages of the chat) never meet their DOM record during the recovery pass. |
| **RC5** | **Silence.** The backfill status says "No new messages (…)"; nothing in the Collector window or the status payload reports what media recovery did. | `sync_reason: no_new` while 2 GIFs stayed failed. | The user cannot distinguish "recovered" from "attempted and failed" from "did not even try" — the report literally says "does not attempt". |

## 3. The fix (what changed)

| # | Change | File(s) |
|---|---|---|
| F-1 | **Per-file cap 2 MB → 25 MB** (the in-page transfer limit), plus a stored-config migration: any configured `max_file_mb ≤ 2` (the old default, which made GIF saving impossible) is raised to 25. | `backend/history_service.py` |
| F-2 | **Empty rows become upgradeable slots.** `append`/`_prepend` look for a payload-less row (same person, direction, author, HH:MM) when a payload-bearing record arrives: the slot is **updated in place** (kind, media_id, text, dup_key) instead of inserting a duplicate; if the record's dup_key already exists elsewhere the empty slot is removed as a parse artefact. | `backend/history_repo.py` |
| F-3 | **`recover_media` sees every broken shape.** Candidates now include `media_id IS NULL AND (kind IN ('image','gif') OR text='')`; after `register()` the row is **re-queued** when it exists in `failed`/`skipped` state; returns a dict `{repaired, requeued, scanned}`. A `requeue_failed` flag separates the cheap automatic pass (repair never-registered rows only) from the manual backfill (also re-queue failed/skipped downloads). | `backend/history_repo.py` |
| F-4 | **A tail-window repair pass on every sync.** After the main read (and after the viewport is restored), if the person still has repairable rows, the newest DOM window (`slice(count-chunk, count)`) is read and fed to `recover_media` — this is what covers the newest messages that the scroll-to-top pass lost, and it also runs on ordinary ticks, so a media line that rendered late is repaired within one heartbeat. | `backend/chat_parser.py` |
| F-5 | **Recovery is visible.** `SyncResult` carries `media_repaired`/`media_requeued`; the Collector window logs "Media recovery: repaired N, re-queued M for download" and shows a `Media` row in the panel; `backfill_older()` without a partner nick logs an explicit "open the private chat first" instead of silently doing nothing. | `backend/history_models.py`, `backend/collector.py`, `ui/js/collector-panel.js` |

## 4. Not changed (and why)

* The dedupe identity (`dup_key` = direction+author+HH:MM+kind+payload) stays.
  The empty→URL upgrade rewrites the slot's `dup_key`, so the fix composes
  with dedupe instead of weakening it.
* `media` rows keep `failed`/`skipped` states and `fail_reason` (honest
  diagnostics); the History window's "click to restore" marker keeps working
  and now succeeds for ordinary GIFs because of F-1.
* No schema change: `messages.media_scan_at` / `media_recovered_at` and
  `media.recovered_at` / `recovery_attempts` already exist (schema 3).

## 5. Regression cover

* `tests/test_media_recovery.py` — unit cases for every root cause above
  (empty-text row, re-queue after register, `requeue_failed=False` scope).
* `tests/test_media_recovery_e2e.py` — the user's exact conversation through
  the real Collector: oversize GIF saving, backfill re-queue + successful
  re-download, live push upgrading an empty slot without duplicates, and the
  tail-window repair of the newest messages.

## 6. Implementation record (2026-09-07, later the same day)

All five fixes landed; every suite from the baseline re-run green
(`test_media_recovery` 3→3, `test_media_recovery_e2e` new 12, all other
Python suites and all JS suites OK). Three defects were found *while*
implementing and are part of the change:

| # | Defect | Resolution |
|---|---|---|
| D-1 | The first draft of the slot lookup compared `lower(from_nick)=?` inside SQL. SQLite's `lower()` folds ASCII only, so a Cyrillic nick like `Хорошо Все` never matched its own row — the exact bug class the user hit. | `_empty_slot_rows()` fetches the person's empty rows once and matching happens in Python (`_slot_key`/`_slot_row_key`), where `.lower()` is Unicode-aware. |
| D-2 | The chunked top pass and the tail pass of one backfill can run inside the same clock second; both wrote the same `media_scan_at` stamp, so the tail pass's candidate filter (`media_scan_at<>?`) excluded exactly the rows the top pass had scanned — re-opening the RC4 hole. | Every `recover_media` call now stamps a unique marker (`"<stamp>.<seq>"`); `media_recovered_at` keeps the plain timestamp. |
| D-3 | On an *unchanged* tick (idle conversation) `Collector._tick` returned before `media.process_pending()`, so a re-queued backlog (25 downloads per pass) stalled until the partner wrote something new. | The unchanged branch drains the queue (`process_pending` + `evict_if_needed`) before returning `no_new`. |

Additional detail worth remembering:

* The slot key includes the resolved calendar **day** (not just the on-screen
  HH:MM, which repeats every day): a NEW GIF sent at 16:24 must never fill an
  empty slot left by yesterday's 16:24 — covered by
  `test_a_new_gif_cannot_fill_yesterdays_slot`.
* `has_repairable_media(person, include_failed)` gates the tail pass. The
  automatic pass honours a 10-minute grace period on rows the DOM could not
  supply a URL for (`media_scan_at` cutoff), so a deleted message cannot make
  every heartbeat re-read the newest window; the manual backfill ignores the
  grace period (a row the top pass just scanned may only match after the
  viewport is restored — the same-sync case D-2 covers).
* `MediaStore`'s bare constructor default moved from 1 MB to 25 MB to match;
  `HistoryService` always passes the configured value.
* `tests/repro_bug2.py` stays as the reproduction rig: it replays the user's
  exact 27-line conversation (partner `глубокаясосуха`, me `Хорошо Все`,
  sent webp + two received GIF URLs) through the real pipeline with a
  no-network CDP fake, scenario B demonstrating the recovery path end-to-end.
