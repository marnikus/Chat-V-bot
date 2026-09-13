"""Person folders and file names for the media cache.

The naming half of `stores/media_store.py`: a nick becomes a Latin,
filesystem-safe folder (the 2026-09-07 bug report asked for a name you can
type in Explorer), one folder per person stays stable across restarts
through a `_nick.txt` marker, and each save gets the next dated name. The
pure helpers the downloader needs — the extension/MIME tables,
`slugify_nick`, `infer_kind`, the timestamp — live here too, since they are
all about how a byte blob is named and classified.

No state: the nick → folder claim map (`_dirs`) and the clock (`now`, patched
by tests) stay on `MediaStore` and are read at call time, so
`media.cache_dir = …` mid-run still redirects every write.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

log = logging.getLogger("chatbot")

IMAGE_EXT = {".jpg": "image", ".jpeg": "image", ".png": "image",
             ".webp": "image", ".bmp": "image", ".gif": "gif"}
MIME_EXT = {"image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg",
            "image/webp": ".webp", "image/bmp": ".bmp"}

#: Cyrillic → Latin, so `Хорошо Все` becomes a folder anybody can type,
#: open in Explorer and paste into a path. Latin-only was an explicit
#: requirement of the 2026-09-07 bug report.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}
SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESERVED = {"con", "prn", "aux", "nul", "clock$"} | {
    f"{stem}{i}" for stem in ("com", "lpt") for i in range(1, 10)}


def _transliterate(raw: str) -> tuple[str, bool]:
    """Per-character map to a filesystem-safe slug; True when lossy."""
    out, lossy = [], False
    for ch in raw:
        low = ch.lower()
        if ch in SAFE_CHARS or ch in "._-":
            out.append(ch)
        elif ch.isspace():
            out.append("_")
        elif low in TRANSLIT:
            mapped = TRANSLIT[low]
            out.append(mapped.capitalize() if (ch != low and mapped)
                       else mapped)
        else:
            lossy = True
            out.append("_")
    return "".join(out).strip("._ "), lossy


def _collapse_underscores(slug: str) -> str:
    """`__` runs folded, unless the raw nick carried them deliberately."""
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


def slugify_nick(nick: str) -> str:
    """A Latin, filesystem-safe folder name for a person.

    `Хорошо Все` → `Horosho_Vse`, `Lizalo4ka` → `Lizalo4ka`. A short hash is
    appended only when the nick cannot be transliterated faithfully (emoji,
    CJK, punctuation), so the common case stays readable.
    """
    raw = " ".join(str(nick or "").split())
    if not raw:
        return "unknown"
    slug, lossy = _transliterate(raw)
    if "__" not in raw:
        slug = _collapse_underscores(slug)
    if not slug or set(slug) <= {"_"}:
        slug, lossy = "user", True
    if slug.lower() in RESERVED:
        slug, lossy = slug + "_", True
    if lossy:
        slug += "_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:4]
    return slug[:64]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def infer_kind(url: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    return IMAGE_EXT.get(ext, "image")


def _extension(url: str, mime: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    if ext in IMAGE_EXT:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip(), ".bin")


class MediaLayout:
    """Person folders and file names for the media cache."""

    def __init__(self, owner):
        """`owner` is the `MediaStore` this part borrows state from."""
        self._owner = owner

    def folder_for(self, nick: str, kind: str = "") -> str:
        """`<cache_dir>/<Latin nick>[/images|/gifs]`, absolute."""
        parts = [self._person_dir(nick)]
        if kind:
            parts.append("gifs" if kind == "gif" else "images")
        return os.path.join(*parts)

    def _person_dir(self, nick: str) -> str:
        """One folder per person, kept stable across restarts.

        Two different nicks can transliterate to the same Latin name
        (`Ански` and `Anski`); the folder therefore carries a `_nick.txt`
        marker naming its owner, and a late-comer gets a hashed variant.
        """
        key = " ".join(str(nick or "").split())
        cached = self._owner._dirs.get(key)
        if cached:
            return cached
        root = os.path.abspath(self._owner.cache_dir)
        slug = slugify_nick(key)
        folder = os.path.join(root, slug)
        owner = self._marker(folder)
        claimed = any(path == folder for other, path in self._owner._dirs.items()
                      if other != key)
        if (owner and owner != key) or (not owner and claimed):
            # A late-comer gets a hashed variant — via the on-disk marker
            # once bytes have landed, or via the in-process claim map
            # before the first write (MED-04). The digest is per-nick, so
            # the mapping is stable across restarts for a fixed ask order.
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
            folder = os.path.join(root, f"{slug}_{digest}")
        self._owner._dirs[key] = folder
        return folder

    def _marker(self, folder: str) -> str:
        try:
            with open(os.path.join(folder, self._owner.NICK_MARKER),
                      encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def _write_marker(self, folder: str, nick: str) -> None:
        path = os.path.join(folder, self._owner.NICK_MARKER)
        if os.path.exists(path):
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(" ".join(str(nick or "").split()) or "unknown")
        except OSError as e:                         # noqa: BLE001
            log.debug("cannot write the nick marker in %s: %s", folder, e)

    def _free_name(self, folder: str, day: str, ext: str) -> str:
        """`YYYY-MM-DD_007.gif` — short, dated, sorted, unique."""
        used = 0
        try:
            for name in os.listdir(folder):
                if not name.startswith(day + "_"):
                    continue
                stem = os.path.splitext(name)[0][len(day) + 1:]
                if stem.isdigit():
                    used = max(used, int(stem))
        except OSError:
            pass
        return os.path.join(folder, f"{day}_{used + 1:03d}{ext}")

    def _target_path(self, nick: str, kind: str, day: str, ext: str) -> str:
        person = self._person_dir(nick)
        folder = os.path.join(person, "gifs" if kind == "gif" else "images")
        os.makedirs(folder, exist_ok=True)
        self._write_marker(person, nick)
        return self._free_name(folder, day, ext)

    def _day(self, value=None) -> str:
        text = str(value or "")[:10]
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return text
        return self._owner.now().strftime("%Y-%m-%d")
