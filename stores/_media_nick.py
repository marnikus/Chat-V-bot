"""Media nick helpers — extracted from MediaStore (AREA B, SLOC reduction)."""

from __future__ import annotations

import hashlib
import os
from urllib.parse import urlparse

IMAGE_EXT = {
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".webp": "image", ".bmp": "image", ".gif": "gif"
}
MIME_EXT = {
    "image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg",
    "image/webp": ".webp", "image/bmp": ".bmp"
}

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
    f"{stem}{i}" for stem in ("com", "lpt") for i in range(1, 10)
}

def slugify_nick(nick: str) -> str:
    """A Latin, filesystem-safe folder name for a person."""
    raw = " ".join(str(nick or "").split())
    if not raw:
        return "unknown"
    out, lossy = [], False
    for ch in raw:
        low = ch.lower()
        if ch in SAFE_CHARS or ch in "._-":
            out.append(ch)
        elif ch.isspace():
            out.append("_")
        elif low in TRANSLIT:
            mapped = TRANSLIT[low]
            out.append(mapped.capitalize() if (ch != low and mapped) else mapped)
        else:
            lossy = True
            out.append("_")
    slug = "".join(out).strip("._ ")
    if "__" not in raw:
        while "__" in slug:
            slug = slug.replace("__", "_")
    if not slug or set(slug) <= {"_"}:
        slug, lossy = "user", True
    if slug.lower() in RESERVED:
        slug, lossy = slug + "_", True
    if lossy:
        slug += "_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:4]
    return slug[:64]

def infer_kind(url: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    return IMAGE_EXT.get(ext, "image")

def _extension(url: str, mime: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    if ext in IMAGE_EXT:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip(), ".bin")
