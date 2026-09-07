"""Reproduce BUG #2 — the user's exact live scenario (fixed 2026-09-07).

Private chat: partner `глубокаясосуха`, me `Хорошо Все`.
- sent webp at 16:22  (saved fine per the user)
- received GIF at 16:24 (NOT saved)
- received GIF at 16:28 (NOT saved)
Then "Backfill older" is clicked. Does the media come back?

Scenario A — everything downloads (baseline).
Scenario B — the GIF fetches keep failing: the backfill must still re-queue
             them (visible in the collector log and `recovery_attempts`)
             instead of silently doing nothing.
Scenario C — the GIF fetches fail at first, the host recovers, and one
             backfill saves both files.

Run:  python3 tests/repro_bug2.py
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chat_parser import ChatParser  # noqa: E402
from backend.collector import Collector  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from backend.media_store import MediaStore  # noqa: E402

NOW = datetime(2026, 9, 7, 16, 30, 0)
ME = "Хорошо Все"
PARTNER = "глубокаясосуха"
SENT_WEBP = ("https://images.virt-chat.com/images/"
             "m_%D0%A5%D0%BE%D1%80%D0%BE%D1%88%D0%BE%20%D0%92%D1%81%D0%B5_"
             "c3a35f75bfe75dd1cb7592b35482441fa6634139ba181b8dcf3c243cf71fe19a_.webp")
GIF1 = ("https://images.virt-chat.com/images/"
        "m_%D0%93%D0%BB%D0%BE%D1%82%D0%BA%D0%BE%D0%B4%D0%B5%D1%80_"
        "e911e361ff5f37b25facf729aa6e85273cf3b9d981712ad40e1fd7cdec66f124_.gif")
GIF2 = ("https://images.virt-chat.com/images/"
        "m_%D0%9F%D0%B8%D1%82%D0%B5%D1%802%D0%BA7_"
        "7a861cc1fd9d3221978be53b760dd62ee96a05f059d1bdb2b9c3c61793320cf1_.gif")


def raw(text="", direction="in", from_nick=PARTNER, time="16:22",
        kind="text", media=None, occ=0, idx=0):
    payload = media["url"] if media else text
    return {"fp": fingerprint(direction, from_nick, time, kind, payload, occ),
            "dir": direction, "from": from_nick, "kind": kind, "text": text,
            "media": media, "time": time, "occ": occ, "idx": idx}


class FakePage:
    """CDP-shaped fake mirroring the user's saved HTML conversation."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.tab, self.partner, self.me = "private", PARTNER, ME
        self.title = PARTNER
        self.participants = 2
        self.is_connected = True

    async def evaluate(self, expression):
        if "/*CVB_STATE*/" in expression:
            ins, outs = [], []
            for m in self.messages:
                nick = m["from"]
                if m["dir"] == "out":
                    if nick not in outs:
                        outs.append(nick)
                elif nick not in ins:
                    ins.append(nick)
            fps = [m["fp"] for m in self.messages]
            return json.dumps({
                "ok": True, "agent": 9, "tab": self.tab,
                "partner": self.partner, "me": self.me, "title": self.title,
                "participants": self.participants,
                "in_authors": ins, "out_authors": outs, "authors": ins + outs,
                "count": len(self.messages),
                "head": fps[:5], "tail": fps[-25:],
                "pending": 0,
                "scroll": {"top": 0, "height": 1000, "client": 600,
                           "atTop": True, "atBottom": True},
            })
        if "/*CVB_SLICE*/" in expression:
            payload = json.loads(expression.split("/*ARGS:")[1].split("*/")[0])
            return json.dumps({"ok": True, "from": payload["from"],
                               "to": payload["to"],
                               "items": self.messages[payload["from"]:
                                                      payload["to"]]})
        if "/*CVB_FETCH_MEDIA*/" in expression:
            # in-page fetch fails: CORS blocked on images.virt-chat.com
            return json.dumps({"ok": False, "error": "Failed to fetch"})
        return None


class NoNetworkCDP(FakePage):
    """CDP where the GIF downloads always fail (CORS + host rejects)."""

    def __init__(self, messages, ok_urls=()):
        super().__init__(messages)
        self.ok_urls = set(ok_urls)

    async def get_cookies(self, url=""):
        return "sid=test"

    async def evaluate(self, expression):
        if "/*CVB_FETCH_MEDIA*/" in expression:
            url = json.loads(expression.split("/*ARGS:")[1]
                             .split("*/")[0])["url"]
            if url in self.ok_urls:
                data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400
                return json.dumps({"ok": True, "mime": "image/png",
                                   "b64": base64.b64encode(data).decode(),
                                   "bytes": len(data)})
            return json.dumps({"ok": False, "error": "Failed to fetch"})
        return await super().evaluate(expression)


def build_page():
    return [
        raw("приветик", "out", ME, "16:22", idx=0),
        raw("членоприемничек )", "out", ME, "16:22", idx=1),
        raw("привет", "in", PARTNER, "16:22", idx=2),
        raw("", "out", ME, "16:22", "image",
            {"url": SENT_WEBP, "kind": "image"}, idx=3),
        raw("кайф поглубже мм", "in", PARTNER, "16:22", idx=4),
        raw("хочу пораздвигать твои милый губки", "out", ME, "16:23", idx=5),
        raw("горлышко раздвинь", "in", PARTNER, "16:23", idx=6),
        raw("толстеньким)", "out", ME, "16:23", idx=7),
        raw("да сладко", "in", PARTNER, "16:23", idx=8),
        raw("достаточно глубокий...", "out", ME, "16:24", idx=9),
        raw("буду неспеша хлюпать....мм", "out", ME, "16:24", idx=10),
        raw("", "in", PARTNER, "16:24", "gif",
            {"url": GIF1, "kind": "gif"}, idx=11),
        raw("да сладенько", "in", PARTNER, "16:24", idx=12),
        raw("ммм... с яками?)", "out", ME, "16:24", idx=13),
        raw("да", "in", PARTNER, "16:24", idx=14),
        raw("яйками*", "out", ME, "16:25", idx=15),
        raw("мм мощно", "out", ME, "16:25", idx=16),
        raw("круто если осилишь)", "out", ME, "16:25", idx=17),
        raw("люблю так", "in", PARTNER, "16:25", idx=18),
        raw("ммм...) уже завелся", "out", ME, "16:26", idx=19),
        raw("положил бы тебя вверх тормашками...", "out", ME, "16:27", idx=20),
        raw("горлотрах)", "in", PARTNER, "16:28", idx=21),
        raw("уфф... даа.... он самый", "out", ME, "16:28", idx=22),
        raw("мой член прям уже в руке...)", "out", ME, "16:28", idx=23),
        raw("", "in", PARTNER, "16:28", "gif",
            {"url": GIF2, "kind": "gif"}, idx=24),
        raw("ага это я и видел от тебя)", "out", ME, "16:29", idx=25),
        raw("классно трахаются в рот", "in", PARTNER, "16:29", idx=26),
    ]


async def dump(db, label):
    rows = await db.fetchdicts(
        "SELECT m.ord, m.direction, m.from_nick, m.kind, m.text, "
        "m.media_id, m.ts_display, md.url AS url, md.state AS mstate, "
        "md.fail_reason, md.recovery_attempts, md.cache_path "
        "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
        "WHERE m.kind IN ('image','gif') OR m.media_id IS NOT NULL "
        "ORDER BY m.ord")
    print(f"── media rows ({label}) ──────────────────────────────")
    for r in rows:
        url = (r["url"] or "")[-40:]
        print(f"  ord={r['ord']:>3} {r['direction']} {r['from_nick'][:12]:<12}"
              f" {r['kind']:<5} {r['ts_display']} media_id={r['media_id']} "
              f"state={r['mstate']!r} tries={r['recovery_attempts']} "
              f"file={os.path.basename(r['cache_path'] or '')}"
              f" reason={r['fail_reason'][:40]!r} …{url}")


async def scenario(name, cdp, host_recovers=False, cap_mb=25):
    print(f"\n══════════ {name} ══════════")
    tmp = tempfile.mkdtemp()
    db = HistoryDB(os.path.join(tmp, "history.db"))
    await db.init()
    store = MediaStore(db, cdp=cdp, cache_dir=os.path.join(tmp, "saved_media"),
                       max_file_mb=cap_mb, max_cache_mb=200)
    repo = HistoryRepo(db, media=store, session_id="repro")
    parser = ChatParser(cdp, chunk_size=80, chunk_pause_ms=0)
    col = Collector(cdp=cdp, repo=repo, parser=parser, media=store,
                    settings={"my_nick": ME, "auto_backfill": False})
    col.now = lambda: NOW
    logs = []
    col.collector_log.connect(lambda p: logs.append(json.loads(p)))

    state = await col.tick()
    print("tick 1:", state, col.state_payload()["text"])
    await dump(db, "after initial tick")

    if host_recovers:              # the host/CORS problem goes away
        cdp.ok_urls |= {GIF1, GIF2}

    print("\n>>> user clicks “Backfill older”")
    state = await col.backfill_older()
    payload = col.state_payload()
    print("backfill:", state, payload["text"],
          "reason:", payload["sync_reason"],
          "media repaired:", payload["media_repaired"],
          "re-queued:", payload["media_requeued"])
    for entry in logs:
        if "Media recovery" in entry["message"]:
            print("collector log:", entry["message"])
    await dump(db, "after backfill")

    await db.close()
    return db


async def main():
    # Scenario A: all downloads succeed → baseline sanity
    page = NoNetworkCDP(build_page(), ok_urls={SENT_WEBP, GIF1, GIF2})
    await scenario("A: all downloads succeed (baseline)", page)

    # Scenario B: GIF downloads keep failing (CORS / host) — the fix must
    # retry them (re-queued, recovery_attempts) and stay honest about the
    # failure instead of silently reporting "no new"
    page = NoNetworkCDP(build_page(), ok_urls={SENT_WEBP})
    await scenario("B: GIFs fail, and keep failing after backfill", page)

    # Scenario C: the live report's happy path after the fix — GIFs failed
    # during the first tick, the host recovers, one backfill saves them
    page = NoNetworkCDP(build_page(), ok_urls={SENT_WEBP})
    await scenario("C: GIFs fail, host recovers, backfill saves them", page,
                   host_recovers=True)


if __name__ == "__main__":
    asyncio.run(main())
