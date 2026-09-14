#!/usr/bin/env python3
"""JavaScript size / shape measurement (Round H, step H-A1).

Why this exists: RULE 16 gates the Python side only (2026-09-14 audit §1c).
The 30 frontend files of `ui/js/**` + `backend/js/**` sat outside every size
denominator — that is how SashGrid grew to 1,331 LOC / 69 methods. This tool
is the JS analogue of the AST walker RULE 18 §18.6 points at: it parses by
brace matching (the audit's `/tmp/jsfn.js` prototype, made a repo artefact)
and reports, per file:

  * total physical lines (same convention as js_coverage.py: newlines + 1);
  * every function / method / arrow with its inclusive LOC span — the
    counting rule §16.1 already defines (first line of the signature
    through the last line of the body; nested functions counted separately);
  * every object literal with its LOC span and its method count (function
    members only — data keys are not methods); "gated" objects have >= 1
    method.

The gate (tools/metrics/js_gate.py) compares fresh runs against
reports/js_size_baseline.json; a human reads the stdout table.

Reproduce:
    .venv/bin/python tools/metrics/js_size.py            # table to stdout
    .venv/bin/python tools/metrics/js_size.py --json P   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS_DIRS = ("ui", os.path.join("backend", "js"))

REGEXP_ALLOWED_KW = {
    "return", "case", "typeof", "instanceof", "in", "of", "new", "delete",
    "void", "throw", "do", "else", "yield", "await",
}
MULTI_PUNCT = (
    "...", "=>", "===", "!==", "==", "!=", "<=", ">=", "&&", "||", "??",
    "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "**",
)
KEYWORDS = {
    "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally",
    "for", "function", "if", "import", "in", "instanceof", "let", "new",
    "return", "super", "switch", "this", "throw", "try", "typeof", "var",
    "void", "while", "with", "yield", "async", "await", "static", "get",
    "set", "of", "null", "true", "false",
}
CONTROL_BLOCK_KW = {"if", "for", "while", "switch", "with", "do", "try",
                    "catch", "class", "function", "else"}
# Previous token types that make '{' an object literal (not a block).
OBJECT_OK_PREV = {
    "=", ",", ":", "(", "[", "!", "&", "|", "^", "~", "?",
    "&&", "||", "??", "==", "===", "!==", "!=", "<=", ">=",
    "+", "-", "*", "%", "**",
    "return", "case", "typeof", "instanceof", "in", "of",
    "new", "delete", "void", "throw",
}


def js_files(root: str) -> list:
    out = []
    for base in JS_DIRS:
        for dirpath, _d, filenames in os.walk(os.path.join(root, base)):
            for name in sorted(filenames):
                if name.endswith(".js"):
                    full = os.path.join(dirpath, name)
                    out.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return sorted(out)


def physical_lines(content: str) -> int:
    """Same convention as js_coverage.py: number of newlines + 1."""
    return content.count("\n") + 1


class Token:
    __slots__ = ("text", "line")

    def __init__(self, text: str, line: int) -> None:
        self.text = text
        self.line = line

    @property
    def is_kw(self) -> bool:
        return self.text in KEYWORDS

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "T(%r,%d)" % (self.text, self.line)


def tokenize(src: str) -> list:
    """A small JS tokenizer: identifiers/keywords, numbers, strings,
    templates, regexps, punctuation. Comments are dropped. Enough for shape
    analysis — deliberately not a parser."""
    toks: list = []
    i, n, line = 0, len(src), 1

    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r\f\v":
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            end = n if j < 0 else j + 2
            line += src.count("\n", i, end)
            i = end
            continue
        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            toks.append(Token(src[i:j], line))
            i = j
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_xX"
                             or (src[j] == "." and j + 1 < n
                                 and src[j + 1].isdigit())):
                j += 1
            toks.append(Token(src[i:j], line))
            i = j
            continue
        if ch in "'\"":
            quote, j = ch, i + 1
            while j < n:
                if src[j] == "\\":
                    line += 1 if src[j + 1:j + 2] == "\n" else 0
                    j += 2
                    continue
                if src[j] == quote:
                    j += 1
                    break
                line += 1 if src[j] == "\n" else 0
                j += 1
            toks.append(Token(src[i:min(j, n)], line))
            i = j
            continue
        if ch == "`":
            j = _skip_template(src, i)
            toks.append(Token(src[i:min(j, n)], line))
            line = _line_of(src, min(j, n))
            i = j
            continue
        if ch == "/":
            if _regex_allowed(toks):
                j = i + 1
                in_class = False
                while j < n and src[j] != "\n":
                    c = src[j]
                    if c == "\\":
                        j += 2
                        continue
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "/" and not in_class:
                        j += 1
                        break
                    j += 1
                while j < n and (src[j].isalpha() or src[j] in "_$"):
                    j += 1
                toks.append(Token(src[i:min(j, n)], line))
                i = j
                continue
            toks.append(Token("/", line))
            i += 1
            continue
        matched = None
        for cand in MULTI_PUNCT:
            if src.startswith(cand, i):
                matched = cand
                break
        toks.append(Token(matched or ch, line))
        i += len(matched or ch)
    return toks


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def _skip_template(src: str, start: int) -> int:
    """Skip a template literal starting at src[start] == '`'; ${...}
    expressions are skipped whole (not tokenised)."""
    i, n = start + 1, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if c == "$" and i + 1 < n and src[i + 1] == "{":
            depth, i = 1, i + 2
            while i < n and depth:
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                i += 1
            continue
        i += 1
    return n


def _regex_allowed(toks: list) -> bool:
    if not toks:
        return True
    last = toks[-1]
    if last.text in (")", "]"):
        return False
    if last.text in (".",) and len(toks) >= 2 and not toks[-2].is_kw:
        return False  # member access on an expression
    if last.text in KEYWORDS:
        return last.text in REGEXP_ALLOWED_KW
    if last.text.isalpha() or last.text[:1] in "_$":
        return False  # identifier (division, or a member base)
    return True


def _match(toks: list, i: int, open_t: str, close_t: str) -> int:
    """Index of the token matching opener toks[i], or -1."""
    depth = 0
    while i < len(toks):
        t = toks[i]
        if t.text == open_t:
            depth += 1
        elif t.text == close_t:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _match_rev(toks: list, close_idx: int, open_t: str, close_t: str) -> int:
    depth = 0
    i = close_idx
    while i >= 0:
        t = toks[i]
        if t.text == close_t:
            depth += 1
        elif t.text == open_t:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return close_idx


def top_level_function_names(src: str) -> set:
    """Names bound to a function at the top level of the file. Used to
    recognise shorthand method bindings (`foo,`) inside object literals."""
    toks = tokenize(src)
    names = set()
    depth = 0
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t.text in "({[":
            depth += 1
        elif t.text in ")}]":
            depth -= 1
        elif depth == 0 and t.text == "function" and i + 1 < n \
                and not toks[i + 1].is_kw:
            names.add(toks[i + 1].text)
        elif depth == 0 and t.text in ("const", "let", "var") \
                and i + 3 < n and toks[i + 1].text not in KEYWORDS \
                and toks[i + 2].text == "=":
            k = i + 3
            arrow = False
            while k < n and toks[k].text not in (",", ";"):
                if toks[k].text == "=>":
                    arrow = True
                    break
                if toks[k].text in "({[":
                    break
                k += 1
            if toks[i + 3].text == "function" or arrow:
                names.add(toks[i + 1].text)
        i += 1
    return names


def _is_ident(tok: Token) -> bool:
    return tok.text.isalpha() or tok.text[:1] in "_$"


def _is_method_position(toks: list, i: int) -> bool:
    """True when toks[i] (an identifier) is an object-literal method
    definition: preceded by '{' or ',' (or 'get'/'set' after those)."""
    if i == 0:
        return False
    prev = toks[i - 1]
    if prev.text in ("{", ","):
        return True
    if prev.text in ("get", "set") and i >= 2 \
            and toks[i - 2].text in ("{", ","):
        return True
    return False


def analyze_file(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    toks = tokenize(src)
    total = physical_lines(src)
    fn_names = top_level_function_names(src)

    functions: list = []
    objects: list = []

    def record(name: str, start: int, end: int) -> None:
        functions.append({"name": name, "line": start, "end": end,
                          "loc": end - start + 1})

    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t.text == "function":
            j = i + 1
            name = None
            if j < n and _is_ident(toks[j]) and not toks[j].is_kw:
                name = toks[j].text
                j += 1
            k = j
            while k < n and toks[k].text != "(":
                k += 1
            close = _match(toks, k, "(", ")")
            if close + 1 < n and toks[close + 1].text == "{":
                brace_end = _match(toks, close + 1, "{", "}")
                record(name or "(anonymous)", t.line, toks[brace_end].line)
            i += 1
            continue
        if t.text == "=>":
            name, start_tok = _arrow_start(toks, i)
            if i + 1 < n and toks[i + 1].text == "{":
                brace_end = _match(toks, i + 1, "{", "}")
                if brace_end > i + 1 and start_tok is not None:
                    record(name or "(arrow)", start_tok.line,
                           toks[brace_end].line)
            elif name is not None and start_tok is not None:
                record(name, start_tok.line, t.line)
            i += 1
            continue
        if _is_ident(t) and not t.is_kw and i + 1 < n \
                and toks[i + 1].text == "(" and _is_method_position(toks, i):
            close = _match(toks, i + 1, "(", ")")
            if close + 1 < n and toks[close + 1].text == "{":
                brace_end = _match(toks, close + 1, "{", "}")
                prefix = ""
                if i >= 1 and toks[i - 1].text in ("get", "set") \
                        and i >= 2 and toks[i - 2].text in ("{", ","):
                    prefix = toks[i - 1].text + " "
                record(prefix + t.text, t.line, toks[brace_end].line)
            i += 1
            continue
        if t.text == "{" and _is_object_literal(toks, i):
            brace_end = _match(toks, i, "{", "}")
            if brace_end > i:
                methods, _ = _object_members(toks, i, brace_end, fn_names)
                objects.append({"line": t.line, "end": toks[brace_end].line,
                                "loc": toks[brace_end].line - t.line + 1,
                                "methods": methods, "gated": methods > 0})
            i += 1
            continue
        i += 1

    functions.sort(key=lambda f: (-f["loc"], f["line"], f["name"]))
    objects.sort(key=lambda o: (-o["loc"], o["line"]))
    return {
        "file": os.path.relpath(path, ROOT).replace(os.sep, "/"),
        "lines": total,
        "functions": functions,
        "objects": objects,
        "summary": {
            "functions": len(functions),
            "over_30": sum(1 for f in functions if f["loc"] > 30),
            "over_60": sum(1 for f in functions if f["loc"] > 60),
            "over_100": sum(1 for f in functions if f["loc"] > 100),
            "max_object_loc": max((o["loc"] for o in objects), default=0),
            "max_object_methods": max((o["methods"] for o in objects),
                                      default=0),
        },
    }


def _arrow_start(toks: list, arrow_idx: int):
    """(start token, name) for the arrow at toks[arrow_idx]."""
    j = arrow_idx - 1
    if j < 0:
        return None, None
    if toks[j].text == ")":
        open_idx = _match_rev(toks, j, "(", ")")
        return _arrow_name_before(toks, open_idx - 1), toks[open_idx]
    if toks[j].text in KEYWORDS:
        return None, toks[j]
    return _arrow_name_before(toks, j - 1), toks[j]


def _arrow_name_before(toks: list, idx: int):
    """'const f = (' → f · 'foo: (' → foo · anything else → None."""
    if idx < 0:
        return None
    t = toks[idx]
    if t.text == "=" and idx >= 1 and not toks[idx - 1].is_kw:
        return toks[idx - 1].text
    if t.text == ":" and idx >= 1 and not toks[idx - 1].is_kw:
        return toks[idx - 1].text
    return None


def _is_object_literal(toks: list, brace_idx: int) -> bool:
    if brace_idx == 0:
        return False
    prev = toks[brace_idx - 1]
    if prev.text in (")", "}", ";", "else"):
        return False
    if prev.text in KEYWORDS:
        return prev.text in OBJECT_OK_PREV
    if prev.text in ("true", "false", "null", "this"):
        return False
    if prev.text.isalpha() or prev.text[:1] in "_$":
        return False  # class body / member base
    return prev.text in OBJECT_OK_PREV


def _object_members(toks: list, open_idx: int, close_idx: int,
                    fn_names: set):
    """Count method members of the object literal spanning
    toks[open_idx..close_idx]. Returns (method_count, member_count)."""
    methods = 0
    members = 0
    i = open_idx + 1
    while i < close_idx:
        t = toks[i]
        if t.text == "...":
            i += 2
            continue
        if t.text in ("true", "false", "null") or t.is_kw \
                or t.text[:1].isdigit():
            i += 1
            continue
        if t.text.isalpha() or t.text[:1] in "_$":
            if t.text in ("get", "set") and i + 2 < close_idx \
                    and not toks[i + 1].is_kw and toks[i + 2].text == "(":
                methods += 1
                members += 1
                i = _skip_method_body(toks, i + 2)
                continue
            if i + 1 < close_idx and toks[i + 1].text == "(":
                methods += 1
                members += 1
                i = _skip_method_body(toks, i + 1)
                continue
            if i + 1 < close_idx and toks[i + 1].text == ":":
                members += 1
                if i + 2 < close_idx and _value_is_function(toks, i + 2):
                    methods += 1
                i = _skip_value(toks, i + 2)
                continue
            members += 1  # shorthand property
            if t.text in fn_names:
                methods += 1
            i += 1
            continue
        i += 1
    return methods, members


def _value_is_function(toks: list, idx: int) -> bool:
    if idx >= len(toks):
        return False
    t = toks[idx]
    if t.text == "function":
        return True
    if t.text == "(":
        return True  # parenthesised arrow params
    if t.text == "async":
        return idx + 1 < len(toks) and toks[idx + 1].text == "function"
    if t.text.isalpha() or t.text[:1] in "_$":
        # lone identifier: an arrow param (`f: x => …`) or a data reference
        j = idx
        while j < len(toks) and toks[j].text not in (",", ")", "}", ";"):
            if toks[j].text == "=>":
                return True
            if toks[j].text in "([{" and toks[j].text != "(":
                return False
            j += 1
        return False
    return False


def _skip_value(toks: list, i: int) -> int:
    """Skip a property value expression starting at toks[i]; returns the
    index of the following top-level ',' (or the closing '}')."""
    depth = 0
    while i < len(toks):
        t = toks[i]
        if t.text in "([{":
            depth += 1
        elif t.text in ")]}":
            if depth == 0 and t.text == "}":
                return i
            depth -= 1
        elif t.text == "," and depth == 0:
            return i + 1
        i += 1
    return i


def _skip_method_body(toks: list, paren_idx: int) -> int:
    close = _match(toks, paren_idx, "(", ")")
    i = close + 1
    while i < len(toks) and toks[i].text != "{":
        i += 1
    return _match(toks, i, "{", "}") + 1


def run(root: str) -> dict:
    files = [analyze_file(os.path.join(root, rel)) for rel in js_files(root)]
    return {
        "files": files,
        "totals": {
            "files": len(files),
            "lines": sum(f["lines"] for f in files),
            "functions": sum(f["summary"]["functions"] for f in files),
            "over_30": sum(f["summary"]["over_30"] for f in files),
            "over_60": sum(f["summary"]["over_60"] for f in files),
            "over_100": sum(f["summary"]["over_100"] for f in files),
        },
    }


def print_report(report: dict) -> None:
    print("%-32s %6s %6s %8s %8s %5s %5s"
          % ("file", "lines", "funcs", "objLoc", "objMeth", ">30", ">60"))
    for f in report["files"]:
        s = f["summary"]
        print("%-32s %6d %6d %8d %8d %5d %5d"
              % (f["file"], f["lines"], s["functions"], s["max_object_loc"],
                 s["max_object_methods"], s["over_30"], s["over_60"]))
    t = report["totals"]
    print("%-32s %6d %6d" % ("TOTAL (%d files)" % t["files"], t["lines"],
                             t["functions"]))
    print("functions over 30 LOC: %d · over 60: %d · over 100: %d"
          % (t["over_30"], t["over_60"], t["over_100"]))
    print()
    print("longest functions (the tail the gate watches):")
    over = sorted((dict(f2, file=f["file"]) for f in report["files"]
                   for f2 in f["functions"] if f2["loc"] > 30),
                  key=lambda f: (-f["loc"], f["file"], f["line"]))
    for f in over[:20]:
        print("  %4d  %s::%s  (line %d)" % (f["loc"], f["file"], f["name"],
                                            f["line"]))
    print()
    print("largest gated objects (function-bearing object literals):")
    objs = sorted(((f["file"], o) for f in report["files"]
                   for o in f["objects"] if o["gated"]),
                  key=lambda fo: (-fo[1]["loc"], fo[0], fo[1]["line"]))
    for name, o in objs[:10]:
        print("  %4d loc, %3d methods  %-28s line %d"
              % (o["loc"], o["methods"], name, o["line"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write the machine-readable report here")
    args = ap.parse_args(argv)

    report = run(ROOT)
    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
        print("wrote " + args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
