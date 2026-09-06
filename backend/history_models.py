"""Value objects shared by the message archive.

The fingerprint is the identity of a chat line. It has to be computed in two
places — in the page (backend/js/chat_agent.js, JavaScript) and here — so the
hash is defined over UTF-16 code units, exactly what JavaScript's
`charCodeAt()` yields, and both implementations are pinned by tests to the
same constants.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# FNV-1a parameters (32 bit), applied twice to get a 64-bit-wide hex id.
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
_MASK = 0xFFFFFFFF
SEP = "\u001f"          # unit separator — cannot occur in chat text


def _utf16_units(text: str):
    """Iterate the UTF-16 code units of `text` (what JS strings are made of)."""
    raw = text.encode("utf-16-le", "surrogatepass")
    for i in range(0, len(raw), 2):
        yield raw[i] | (raw[i + 1] << 8)


def _fnv1a(text: str, seed: int) -> int:
    h = seed & _MASK
    for unit in _utf16_units(text):
        h = ((h ^ unit) * _FNV_PRIME) & _MASK
    return h


def fingerprint(direction: str, from_nick: str, ts_display: str, kind: str,
                payload: str, occ: int = 0) -> str:
    """Stable identity of one chat line.

    `payload` is the message text, or the media URL for an image/GIF.
    `occ` distinguishes literally identical lines in the same minute.
    """
    joined = SEP.join([str(direction or ""), str(from_nick or ""),
                       str(ts_display or ""), str(kind or "text"),
                       str(payload or ""), str(int(occ or 0))])
    return "%08x%08x" % (_fnv1a(joined, _FNV_OFFSET),
                         _fnv1a(joined + "\u0001", _FNV_PRIME))


@dataclass
class MessageRecord:
    """One parsed chat line, as it leaves the parser and enters the archive."""

    fp: str = ""
    direction: str = "in"           # "in" (partner) | "out" (me)
    from_nick: str = ""
    kind: str = "text"              # text | image | gif
    text: str = ""
    media_url: str = ""
    media_kind: str = ""
    ts_display: str = ""            # HH:MM as the site shows it
    occ: int = 0
    idx: int = 0                    # position in the DOM at parse time

    @property
    def payload(self) -> str:
        return self.media_url or self.text

    def ensure_fp(self) -> str:
        if not self.fp:
            self.fp = fingerprint(self.direction, self.from_nick,
                                  self.ts_display, self.kind, self.payload,
                                  self.occ)
        return self.fp

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MessageRecord":
        """Build a record from the JSON the in-page agent produces."""
        data = data or {}
        media = data.get("media") or {}
        rec = cls(
            fp=str(data.get("fp", "")),
            direction=str(data.get("dir") or data.get("direction") or "in"),
            from_nick=str(data.get("from") or data.get("from_nick") or ""),
            kind=str(data.get("kind") or "text"),
            text=str(data.get("text") or ""),
            media_url=str(media.get("url") or data.get("media_url") or ""),
            media_kind=str(media.get("kind") or data.get("media_kind") or ""),
            ts_display=str(data.get("time") or data.get("ts_display") or ""),
            occ=int(data.get("occ") or 0),
            idx=int(data.get("idx") or 0),
        )
        rec.ensure_fp()
        return rec


@dataclass
class AppendResult:
    """What one `HistoryRepo.append()` did."""

    added: int = 0
    skipped: int = 0
    gap: bool = False
    first_ord: int = 0
    last_ord: int = 0
    total: int = 0
    person_id: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Alignment:
    """Where a freshly parsed batch continues the stored conversation."""

    start: int = 0          # first index of the batch that is new
    gap: bool = False
    reason: str = ""
    overlap: int = 0
    matched: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SyncResult:
    """Outcome of one conversation sync (parser → archive)."""

    ok: bool = False
    reason: str = ""
    added: int = 0
    scanned: int = 0
    stopped: bool = False
    gap: bool = False
    total: int = 0
    nick: str = ""
    my_nick: str = ""
    chunks: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
