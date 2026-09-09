"""Command-side, per-person undo snapshots. Never a collection/seen registry.

Snapshots live outside the active archive, have a non-archive identity, and are
opened only by explicit reset/undo or startup legacy conversion. They are never
ATTACHed to the collection connection. Cached bytes are copied, not hardlinked.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from backend.db_paths import canonical_path, same_database

log = logging.getLogger("chatbot")
UNDO_APPLICATION_ID = 0x43564255  # CVBU, not CVBH
UNDO_KIND = "history_reset_undo"
TABLES = ("schema_meta", "persons", "media", "messages", "cursors", "gaps")


def within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        return os.path.commonpath([canonical_path(path), canonical_path(root)]) == canonical_path(root)
    except (OSError, ValueError):
        return False


def _insert(conn, table, rows):
    if not rows:
        return
    columns = list(rows[0])
    sql = f'INSERT INTO {table} (' + ','.join('"' + c + '"' for c in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
    conn.executemany(sql, [tuple(r[c] for c in columns) for r in rows])


class HistoryUndoStore:
    """No active DB reference is retained, and no collector receives this object."""

    @staticmethod
    def root_for(db_path: str) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(db_path)), "db_trash", "history_undo")

    async def capture(self, db, nick: str, cache_dir: str, *, message_ids=None,
                      legacy_tokens=()) -> str:
        person = await db.fetchone("SELECT * FROM persons WHERE nick=?", (nick,))
        if not person:
            return ""
        person = dict(person)
        pid = int(person["id"])
        messages = await db.fetchdicts("SELECT * FROM messages WHERE person_id=? ORDER BY ord,id", (pid,))
        if message_ids is not None:
            wanted = {int(i) for i in message_ids}
            messages = [r for r in messages if int(r["id"]) in wanted]
        mids = sorted({int(r["media_id"]) for r in messages if r.get("media_id") is not None})
        media = []
        for at in range(0, len(mids), 400):
            batch = mids[at:at + 400]
            media += await db.fetchdicts("SELECT * FROM media WHERE id IN (" + ','.join('?' for _ in batch) + ')', batch)
        ddl = []
        for table in TABLES:
            ddl.append(await db.scalar("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,), ""))
        payload = {
            "persons": [dict(person)], "messages": messages, "media": media,
            "cursors": await db.fetchdicts("SELECT * FROM cursors WHERE person_id=?", (pid,)),
            "gaps": await db.fetchdicts("SELECT * FROM gaps WHERE person_id=?", (pid,)),
        }
        directory = os.path.join(self.root_for(db.path), uuid.uuid4().hex)
        meta = {"storage_kind": UNDO_KIND, "undo_version": "1", "source_db": canonical_path(db.path),
                "nick": nick, "legacy_tokens": json.dumps(list(legacy_tokens)),
                "deleted_person_token": str(person.get("deleted_at") or "")}
        return await asyncio.to_thread(self._write, directory, ddl, payload, meta, cache_dir)

    @staticmethod
    def _write(directory, ddl, payload, meta, cache_dir):
        os.makedirs(directory, exist_ok=False)
        stage = os.path.join(directory, "staging.db")
        conn = None
        try:
            conn = sqlite3.connect(stage)
            conn.execute("PRAGMA foreign_keys=ON")
            for sql in ddl:
                if not sql:
                    raise ValueError("Missing archive table definition for undo snapshot")
                conn.execute(sql)
            conn.execute("CREATE TABLE undo_assets(media_id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL)")
            for table in ("persons", "media", "messages", "cursors", "gaps"):
                _insert(conn, table, payload[table])
            copied = {}
            for row in payload["media"]:
                source = row.get("cache_path") or ""
                if not within(source, cache_dir) or not os.path.isfile(source):
                    continue
                if source not in copied:
                    name = hashlib.sha256(source.encode('utf-8')).hexdigest() + (Path(source).suffix or '.bin')
                    relative = os.path.join("assets", name)
                    os.makedirs(os.path.join(directory, "assets"), exist_ok=True)
                    shutil.copy2(source, os.path.join(directory, relative))
                    copied[source] = relative
                conn.execute("INSERT INTO undo_assets VALUES(?,?)", (row["id"], copied[source]))
            conn.executemany("INSERT INTO schema_meta(key,value) VALUES(?,?)", meta.items())
            conn.execute(f"PRAGMA application_id={UNDO_APPLICATION_ID}")
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)] or conn.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Undo snapshot validation failed")
            conn.commit()
            conn.close()
            conn = None
            destination = os.path.join(directory, "state.db")
            os.replace(stage, destination)
            return destination
        except BaseException:
            if conn is not None:
                conn.close()
            shutil.rmtree(directory, ignore_errors=True)  # only this freshly allocated UUID directory
            raise

    @staticmethod
    def _read(path, db_path, nick):
        if not within(path, HistoryUndoStore.root_for(db_path)):
            raise ValueError("Undo snapshot is outside this archive's undo store")
        conn = sqlite3.connect(Path(os.path.abspath(path)).as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute("PRAGMA application_id").fetchone()[0] != UNDO_APPLICATION_ID:
                raise ValueError("Not a history undo snapshot")
            meta = dict(conn.execute("SELECT key,value FROM schema_meta"))
            if (meta.get("storage_kind") != UNDO_KIND or meta.get("undo_version") != "1" or
                    meta.get("nick") != nick or not same_database(meta.get("source_db", ""), db_path)):
                raise ValueError("Undo snapshot does not belong to this person/database")
            if [tuple(r) for r in conn.execute("PRAGMA quick_check")] != [("ok",)]:
                raise ValueError("Undo snapshot is damaged")
            data = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in ("persons", "messages", "media")}
            if (len(data["persons"]) != 1 or data["persons"][0].get("nick") != nick or
                    any(r.get("person_id") != data["persons"][0]["id"] for r in data["messages"]) or
                    conn.execute("PRAGMA foreign_key_check").fetchall()):
                raise ValueError("Undo snapshot contains inconsistent person/message references")
            data["assets"] = {int(r[0]): r[1] for r in conn.execute("SELECT media_id,relative_path FROM undo_assets")}
            data["meta"] = meta
            return data
        finally:
            conn.close()

    async def read(self, path, db_path, nick):
        return await asyncio.to_thread(self._read, path, db_path, nick)

    @staticmethod
    async def _insert_active(db, table, values):
        columns = list(values)
        return await db.execute(f'INSERT INTO {table} (' + ','.join('"' + c + '"' for c in columns) +
                                ') VALUES (' + ','.join('?' for _ in columns) + ')', tuple(values.values()))

    async def restore(self, repo, media_store, path: str, nick: str, *, legacy_token: str = "",
                      legacy_person: bool = False, only_ids=None) -> dict:
        """Merge explicit undo into CURRENT data; never restore old resume pointers.

        Re-collected duplicates retain their newer payload/deletion state. Original
        message IDs are reused only when free, preserving old undo references without
        replacing unrelated rows. No snapshot IDs are used by normal collection.
        """
        db = repo.db
        data = await self.read(path, db.path, nick)  # validate BEFORE active writes
        person_before = data["persons"][0]
        selected = data["messages"]
        wanted = {int(i) for i in only_ids} if only_ids is not None else None
        bulk_tokens = set(json.loads(data["meta"].get("legacy_tokens") or '[]'))
        for row in selected:
            token = row.get("deleted_at") or ""
            if token.startswith('clear:'):
                bulk_tokens.add(token)
        if legacy_token:
            selected = [r for r in selected if r.get("deleted_at") == legacy_token or
                        (legacy_person and (not r.get("deleted_at") or r.get("deleted_at") not in bulk_tokens))]
        elif wanted is None:
            # Undo never reinstates the obsolete bulk-deletion denylist.
            selected = [r for r in selected if (r.get("deleted_at") or "") not in bulk_tokens]
        if wanted is not None:
            selected = [r for r in selected if int(r["id"]) in wanted]
        current = await repo.get_person(nick)
        if not current:
            values = dict(person_before)
            if await db.scalar("SELECT 1 FROM persons WHERE id=?", (values["id"],), 0):
                values.pop('id')
            values.update(deleted_at=None, message_count=0, in_count=0, out_count=0, media_count=0,
                          last_ord=0, first_seen=None, last_seen=None)
            cur = await self._insert_active(db, "persons", values)
            pid = int(values.get('id') or cur.lastrowid)
        else:
            pid = int(current['id'])
            previous_names = json.loads(person_before.get('my_nicks') or '[]')
            names = list(dict.fromkeys(list(current.get('my_nicks') or []) + list(previous_names)))
            await db.execute("UPDATE persons SET deleted_at=NULL, my_nicks=?, note=CASE WHEN note='' THEN ? ELSE note END WHERE id=?",
                             (json.dumps(names, ensure_ascii=False), person_before.get('note') or '', pid))
        media_by_id = {int(r['id']): r for r in data['media']}
        mids = {}
        restored, reused, mapping = 0, 0, {}
        for original in selected:
            row = dict(original)
            row['person_id'] = pid
            row['media_scan_at'] = ''
            row['text_scan_at'] = ''
            if legacy_token and row.get('deleted_at') == legacy_token or wanted is not None:
                row['deleted_at'] = ''
            mid = row.get('media_id')
            if mid is not None:
                mid = int(mid)
                if mid not in mids:
                    source = dict(media_by_id[mid])
                    active = await db.fetchone("SELECT * FROM media WHERE url=?", (source['url'],))
                    relative = data['assets'].get(mid)
                    asset = os.path.join(os.path.dirname(path), relative) if relative else ''
                    if active:
                        mids[mid] = int(active['id'])
                        cached = active['cache_path'] or ''
                        if (not cached or not os.path.isfile(cached)) and asset and within(asset, os.path.dirname(path)) and os.path.isfile(asset):
                            target = media_store._target_path(nick, source['kind'], source.get('day') or row['day'],
                                                              Path(asset).suffix or '.bin')
                            await asyncio.to_thread(shutil.copy2, asset, target)
                            await db.execute("UPDATE media SET cache_path=?,state='cached',bytes=?,sha256=?,fail_reason='' WHERE id=?",
                                             (target, source.get('bytes') or 0, source.get('sha256'), active['id']))
                    else:
                        source.update(ref_count=0, owner=nick, cache_path='', state='pending', fail_reason='',
                                      recovery_attempts=0, recovered_at='')
                        if asset and within(asset, os.path.dirname(path)) and os.path.isfile(asset):
                            target = media_store._target_path(nick, source['kind'], source.get('day') or row['day'],
                                                              Path(asset).suffix or '.bin')
                            await asyncio.to_thread(shutil.copy2, asset, target)
                            source.update(cache_path=target, state='cached')
                        if await db.scalar("SELECT 1 FROM media WHERE id=?", (source['id'],), 0):
                            source.pop('id')
                        cur = await self._insert_active(db, 'media', source)
                        mids[mid] = int(source.get('id') or cur.lastrowid)
                row['media_id'] = mids[mid]
            duplicate = await db.fetchone("SELECT * FROM messages WHERE person_id=? AND (dup_key=? OR (fp=? AND day=?)) LIMIT 1",
                                           (pid, row['dup_key'], row['fp'], row['day']))
            if duplicate:
                existing = dict(duplicate)
                if existing.get('media_id') is None and row.get('media_id') is not None:
                    existing['media_id'] = row['media_id']
                    await db.execute("UPDATE messages SET media_id=? WHERE id=?", (row['media_id'], existing['id']))
                # Prefer live, potentially more completely captured content.
                original_id = int(row['id'])
                if existing['id'] != original_id and not await db.scalar("SELECT 1 FROM messages WHERE id=?", (original_id,), 0):
                    await db.execute("DELETE FROM messages WHERE id=?", (existing['id'],))
                    existing['id'] = original_id
                    await self._insert_active(db, 'messages', existing)
                mapping[original_id] = int(existing['id'])
                reused += 1
                continue
            original_id = int(row['id'])
            if await db.scalar("SELECT 1 FROM messages WHERE id=?", (original_id,), 0):
                row.pop('id')
            cur = await self._insert_active(db, 'messages', row)
            mapping[original_id] = int(row.get('id') or cur.lastrowid)
            restored += 1
        # Derive all active state from active rows. Snapshot cursors/gaps are not read.
        ordered = await db.fetchall("SELECT id FROM messages WHERE person_id=? ORDER BY day,ts_display,ord,id", (pid,))
        for ordinal, (rid,) in enumerate(ordered, 1):
            await db.execute("UPDATE messages SET ord=? WHERE id=?", (ordinal, rid))
        await db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
        await db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
        await db.execute("UPDATE media SET ref_count=(SELECT COUNT(*) FROM messages WHERE media_id=media.id) "
                         "WHERE id IN (SELECT media_id FROM messages WHERE person_id=?)", (pid,))
        await repo._recount(pid, commit=False)
        return {"restored": restored, "reused": reused, "ids": mapping}

    async def discard(self, path: str, db_path: str) -> None:
        """Remove only a newly created, unreferenced operation directory."""
        directory = Path(path).parent
        if (Path(path).name != "state.db" or len(directory.name) != 32 or
                any(c not in '0123456789abcdef' for c in directory.name) or
                not within(path, self.root_for(db_path))):
            raise ValueError("Unsafe undo snapshot cleanup path")
        await asyncio.to_thread(shutil.rmtree, str(directory), True)

    async def cleanup_files(self, db, paths, cache_dir):
        """Post-commit cache cleanup; it never adds/removes message tracking."""
        for path in set(paths or []):
            if not within(path, cache_dir):
                continue
            if await db.scalar("SELECT 1 FROM media WHERE cache_path=? LIMIT 1", (path,), 0):
                continue
            try:
                await asyncio.to_thread(os.unlink, path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("History reset completed; unreferenced cache file could not be removed: %s", exc)
