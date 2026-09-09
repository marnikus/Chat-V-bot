#!/usr/bin/env python3
"""Static metrics for Chat-V-bot: LOC, SLOC, coupling (Ca/Ce), classes, methods, CC."""
from __future__ import annotations
import ast, os, sys, json
from collections import defaultdict

ROOT = "/home/user/Chat-V-bot"
PKGS = ["core", "actions", "backend", "bridge", "services", "stores", "app"]

def py_files(pkg_root):
    out = []
    for base, dirs, files in os.walk(pkg_root):
        dirs[:] = [d for d in dirs if d != "__pycache__" and d != ".git"]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(base, f))
    return sorted(out)

def modname(path, root):
    rel = os.path.relpath(path, root)
    parts = rel[:-3].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)

# ---- collect files
files = []
for p in PKGS:
    files += py_files(os.path.join(ROOT, p))
files.append(os.path.join(ROOT, "main.py"))

trees = {}
raw = {}
for f in files:
    src = open(f, encoding="utf-8", errors="replace").read()
    raw[f] = src
    try:
        trees[f] = ast.parse(src)
    except SyntaxError as e:
        print(f"SYNTAX ERROR {f}: {e}", file=sys.stderr)

def sloc(src):
    n = 0
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        n += 1
    return n

# ---- module set
modnames = {f: modname(f, ROOT) for f in files}
modset = set(modnames.values())
# add external-ish prefixes we track
EXTERNAL = {"PySide6", "qasync", "websockets", "aiohttp", "aiosqlite", "sqlite3",
            "asyncio", "json", "os", "sys", "re", "time", "logging", "pathlib",
            "dataclasses", "typing", "collections", "shutil", "tempfile", "hashlib",
            "base64", "urllib", "http", "enum", "abc", "functools", "itertools",
            "datetime", "contextlib", "copy", "math", "random", "subprocess",
            "threading", "traceback", "uuid", "weakref", "importlib", "types",
            "inspect", "warnings", "unittest", "pytest", "secrets", "platform",
            "glob", "string", "textwrap", "unicodedata", "zipfile", "io", "csv",
            "struct", "socket", "ssl", "signal", "shlex", "stat", "errno",
            "mimetypes", "xml", "html", "pickle", "ctypes", "array", "bisect"}

def resolve(mod_node_name, level, cur_mod):
    """Return dotted module string for an import, or None if unresolvable."""
    if level:
        parts = cur_mod.split(".")
        if level > 1:
            parts = parts[: -(level - 1)]
        base = ".".join(parts) if level > 1 else ".".join(parts[:-1])
        if mod_node_name:
            base = base + "." + mod_node_name if base else mod_node_name
        return base
    return mod_node_name

def owner_module(target, modset):
    """map a dotted name to the longest known module prefix"""
    while target:
        if target in modset:
            return target
        # package init
        if target + ".__init__" in modset:
            return target + ".__init__"
        parts = target.split(".")
        if len(parts) == 1:
            return None
        target = ".".join(parts[:-1])
    return None

ce = defaultdict(set)   # module -> set of modules it imports (internal)
ce_full = defaultdict(list)  # module -> all import targets (raw)
import_count = defaultdict(int)
for f, tree in trees.items():
    m = modnames[f]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                import_count[m] += 1
                ce_full[m].append(a.name)
                t = owner_module(a.name, modset)
                if t and t != m:
                    ce[m].add(t)
        elif isinstance(node, ast.ImportFrom):
            import_count[m] += 1
            target = resolve(node.module or "", node.level, m)
            ce_full[m].append(("." * node.level) + (node.module or ""))
            if target:
                t = owner_module(target, modset)
                if t and t != m:
                    ce[m].add(t)

ca = defaultdict(set)
for m, deps in ce.items():
    for d in deps:
        ca[d].add(m)

# ---- classes / methods / functions / CC
class FuncInfo:
    pass

records = []
class ClassRec:
    def __init__(self, name, lineno):
        self.name = name; self.lineno = lineno; self.methods = []

def cc_of(node):
    """cyclomatic complexity (radon-like: 1 + decision points)"""
    c = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                          ast.With, ast.AsyncWith, ast.Assert, ast.IfExp)):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
        elif isinstance(n, ast.Match):
            c += len(n.cases)
    return c

file_stats = {}
for f, tree in trees.items():
    m = modnames[f]
    src = raw[f]
    lines = src.splitlines()
    st = {
        "module": m,
        "file": os.path.relpath(f, ROOT),
        "loc": len(lines),
        "sloc": sloc(src),
        "imports_out": len(ce[m]),
        "imports_in": len(ca[m]),
        "import_stmts": import_count[m],
        "classes": [],
        "functions": [],
        "max_cc": 0,
        "max_cc_fn": "",
        "long_fns": 0,
        "cc_gt10": 0,
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            cc = cc_of(node)
            nparams = len(node.args.args) + len(node.args.posonlyargs) + len(node.args.kwonlyargs)
            length = end - node.lineno + 1
            st["functions"].append({"name": node.name, "line": node.lineno, "cc": cc,
                                    "loc": length, "params": nparams})
        elif isinstance(node, ast.ClassDef):
            end = getattr(node, "end_lineno", node.lineno)
            crec = {"name": node.name, "line": node.lineno, "loc": end - node.lineno + 1,
                    "methods": []}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    send = getattr(sub, "end_lineno", sub.lineno)
                    cc = cc_of(sub)
                    nparams = len(sub.args.args) + len(sub.args.posonlyargs) + len(sub.args.kwonlyargs)
                    crec["methods"].append({"name": sub.name, "line": sub.lineno, "cc": cc,
                                            "loc": send - sub.lineno + 1, "params": nparams})
            st["classes"].append(crec)
    allfns = st["functions"] + [mm for c in st["classes"] for mm in c["methods"]]
    st["n_functions"] = len(st["functions"])
    st["n_classes"] = len(st["classes"])
    st["n_methods"] = sum(len(c["methods"]) for c in st["classes"])
    if allfns:
        worst = max(allfns, key=lambda x: x["cc"])
        st["max_cc"] = worst["cc"]; st["max_cc_fn"] = worst["name"]
    st["long_fns"] = sum(1 for x in allfns if x["loc"] > 30)
    st["cc_gt10"] = sum(1 for x in allfns if x["cc"] > 10)
    st["fn_list"] = allfns
    file_stats[m] = st

json.dump({k: {kk: vv for kk, vv in v.items() if kk != "fn_list"} for k, v in file_stats.items()},
          open("/home/user/analysis/file_stats.json", "w"), indent=1)
json.dump({"ce": {k: sorted(v) for k, v in ce.items()}, "ca": {k: sorted(v) for k, v in ca.items()}},
          open("/home/user/analysis/coupling.json", "w"), indent=1)

# ---- print table
rows = sorted(file_stats.values(), key=lambda r: -r["sloc"])
print(f"{'file':52} {'LOC':>5} {'SLOC':>5} {'imp':>4} {'Ce':>3} {'Ca':>3} {'cls':>4} {'mth':>4} {'fn':>4} {'maxcc':>5} {'>10':>4} {'>30L':>4}")
for r in rows:
    print(f"{r['file']:52} {r['loc']:5} {r['sloc']:5} {r['import_stmts']:4} {r['imports_out']:3} {r['imports_in']:3} {r['n_classes']:4} {r['n_methods']:4} {r['n_functions']:4} {r['max_cc']:5} {r['cc_gt10']:4} {r['long_fns']:4}")
print()
print("TOTALS files=%d LOC=%d SLOC=%d classes=%d methods=%d functions=%d" % (
    len(rows), sum(r["loc"] for r in rows), sum(r["sloc"] for r in rows),
    sum(r["n_classes"] for r in rows), sum(r["n_methods"] for r in rows),
    sum(r["n_functions"] for r in rows)))
print()
print("=== files > 200 SLOC ===")
for r in rows:
    if r["sloc"] > 200:
        print(f"  {r['sloc']:5}  {r['file']}")
print()
print("=== top Ca (most depended upon) ===")
for r in sorted(rows, key=lambda r: -r["imports_in"])[:20]:
    print(f"  Ca={r['imports_in']:3} Ce={r['imports_out']:3}  {r['file']}")
print()
print("=== top Ce (most dependent) ===")
for r in sorted(rows, key=lambda r: -r["imports_out"])[:20]:
    print(f"  Ce={r['imports_out']:3} Ca={r['imports_in']:3}  {r['file']}")
print()
print("=== top import statement count (coupling surface) ===")
for r in sorted(rows, key=lambda r: -r["import_stmts"])[:20]:
    print(f"  {r['import_stmts']:3}  {r['file']}")
