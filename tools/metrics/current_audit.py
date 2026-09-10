"""Reproducible Python audit; pip install radon cognitive-complexity.
Run from any directory: python tools/metrics/current_audit.py > audit.json
No application imports. LOC includes docstrings/embedded JS; SLOC is Radon's.
"""
import ast
import copy
import json
from pathlib import Path
from statistics import mean
from radon.raw import analyze
from radon.complexity import cc_visit_ast
from radon.metrics import mi_visit
from cognitive_complexity.api import get_cognitive_complexity

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('core', 'actions', 'backend', 'bridge', 'services', 'stores', 'app')
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)
BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)


def depth(node, level=0):
    """Maximum path depth, not accumulated sibling depths; nested defs separate."""
    values = [level]
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*FUNCTION, ast.ClassDef, ast.Lambda)):
            continue
        values.append(depth(child, level + isinstance(child, BLOCK)))
    return max(values)


class StripNested(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        return ast.copy_location(ast.Pass(), node)
    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def isolated(node):
    result = copy.deepcopy(node)
    result.body = [StripNested().visit(child) for child in result.body]
    return result


def module(path):
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def run():
    paths = sorted(p for pkg in PACKAGES for p in (ROOT / pkg).rglob('*.py')) + [ROOT / 'main.py']
    modules = {module(p) for p in paths}
    files, functions, classes, edges = [], [], [], {}
    clones = {}
    for path in paths:
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        rel, mod = str(path.relative_to(ROOT)), module(path)
        raw = analyze(text)
        files.append(dict(file=rel, loc=len(text.splitlines()), sloc=raw.sloc, mi=mi_visit(text, multi=True)))
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                else:
                    package = mod if path.stem == '__init__' else mod.rpartition('.')[0]
                    base = '.'.join(package.split('.')[:len(package.split('.'))-node.level+1]) if node.level else ''
                    base = '.'.join(x for x in (base, node.module) if x)
                    targets = [base] + [base + '.' + a.name for a in node.names]
                for target in targets:
                    while target and target not in modules:
                        target = target.rpartition('.')[0]
                    if target and target != mod:
                        deps.add(target)
            if isinstance(node, ast.stmt) and node.end_lineno - node.lineno >= 5:
                key = ast.dump(node, include_attributes=False)
                clones.setdefault(key, []).append((rel, node.lineno, node.end_lineno))
            if isinstance(node, FUNCTION):
                fn = isolated(node)
                cc = cc_visit_ast(ast.Module(body=[fn], type_ignores=[]))[0].complexity
                args = node.args
                params = len(args.posonlyargs + args.args + args.kwonlyargs) + bool(args.vararg) + bool(args.kwarg)
                positional = args.posonlyargs + args.args
                params -= bool(positional and positional[0].arg in ('self', 'cls'))
                functions.append(dict(file=rel, name=node.name, line=node.lineno,
                    loc=node.end_lineno-node.lineno+1, cc=cc,
                    cognitive=get_cognitive_complexity(fn), nesting=depth(node), params=params))
            if isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, FUNCTION)]
                method_names = {m.name for m in methods}
                fields = [{n.attr for n in ast.walk(isolated(m)) if isinstance(n, ast.Attribute)
                           and isinstance(n.value, ast.Name) and n.value.id == 'self'
                           and n.attr not in method_names} for m in methods]
                union = set().union(*fields) if fields else set()
                m, a = len(methods), len(union)
                lcom = (m - sum(map(len, fields))/a)/(m-1) if m > 1 and a else None
                classes.append(dict(file=rel, name=node.name, line=node.lineno,
                    loc=node.end_lineno-node.lineno+1, methods=m, lcom_star=lcom))
        edges[mod] = deps
    coupling = [dict(module=m, ca=sum(m in d for d in edges.values()), ce=len(deps),
                     instability=len(deps)/(len(deps)+sum(m in d for d in edges.values()))
                     if len(deps)+sum(m in d for d in edges.values()) else None) for m,deps in edges.items()]
    duplicate_lines = {}
    groups = 0
    for hits in clones.values():
        if len({h[0] for h in hits}) < 2:
            continue
        groups += 1
        for file, lo, hi in hits:
            duplicate_lines.setdefault(file, set()).update(range(lo, hi+1))
    tests = list((ROOT/'tests').rglob('*.py'))
    return dict(files=files, functions=functions, classes=classes, coupling=coupling,
        exact_clone_groups=groups, duplicated_physical_lines=sum(map(len, duplicate_lines.values())),
        test_nonblank_noncomment=sum(sum(bool(s.strip()) and not s.lstrip().startswith('#') for s in p.read_text().splitlines()) for p in tests), test_files=len(tests),
        production_nonblank_noncomment=sum(sum(bool(s.strip()) and not s.lstrip().startswith('#') for s in p.read_text().splitlines()) for p in paths),
        mean_mi=mean(f['mi'] for f in files),
        frontend_js_files=len(list((ROOT/'ui/js').rglob('*.js'))),
        frontend_js_loc=sum(len(p.read_text().splitlines()) for p in (ROOT/'ui/js').rglob('*.js')))


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
