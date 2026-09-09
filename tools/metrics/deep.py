#!/usr/bin/env python3
"""God-class / LCOM / CC hotspots + duplication for Chat-V-bot."""
import ast, os, json, sys
from collections import defaultdict

ROOT="/home/user/Chat-V-bot"
PKGS=["core","actions","backend","bridge","services","stores","app"]

def files():
    out=[]
    for p in PKGS:
        for base,dirs,fs in os.walk(os.path.join(ROOT,p)):
            dirs[:] = [d for d in dirs if d!="__pycache__"]
            for f in fs:
                if f.endswith(".py"): out.append(os.path.join(base,f))
    out.append(os.path.join(ROOT,"main.py"))
    return sorted(out)

def cc_of(node):
    c=1
    for n in ast.walk(node):
        if isinstance(n,(ast.If,ast.For,ast.AsyncFor,ast.While,ast.ExceptHandler,ast.With,ast.AsyncWith,ast.Assert,ast.IfExp)): c+=1
        elif isinstance(n,ast.BoolOp): c+=len(n.values)-1
        elif isinstance(n,ast.comprehension): c+=1+len(n.ifs)
        elif isinstance(n,ast.Match): c+=len(n.cases)
    return c

def nesting(node, depth=0):
    best=depth
    for n in ast.iter_child_nodes(node):
        d=depth
        if isinstance(n,(ast.If,ast.For,ast.AsyncFor,ast.While,ast.With,ast.AsyncWith,ast.Try)):
            d=best+1
        best=max(best, nesting(n,d))
    return best

def cognitive(node, depth=0):
    """Sonar-style cognitive complexity (simplified)."""
    total=0
    for n in ast.iter_child_nodes(node):
        if isinstance(n,(ast.If,ast.IfExp,ast.For,ast.AsyncFor,ast.While,ast.ExceptHandler,ast.With,ast.AsyncWith,ast.Assert)):
            iselse = False
            total += 1 + depth
            total += cognitive(n, depth+1)
        elif isinstance(n, ast.BoolOp):
            total += (len(n.values)-1) + depth
            total += cognitive(n, depth)
        elif isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)):
            total += cognitive(n, depth+1)
        else:
            total += cognitive(n, depth)
    return total

def self_fields(fn):
    s=set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id=="self":
            s.add(n.attr)
    return s

rows=[]
for f in files():
    src=open(f,encoding="utf-8",errors="replace").read()
    try: tree=ast.parse(src)
    except SyntaxError: continue
    rel=os.path.relpath(f,ROOT)
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            end=getattr(node,"end_lineno",node.lineno)
            np_=len(node.args.args)+len(node.args.posonlyargs)+len(node.args.kwonlyargs)
            rows.append(dict(file=rel,name=node.name,line=node.lineno,loc=end-node.lineno+1,
                             cc=cc_of(node),cog=cognitive(node),nest=nesting(node),params=np_))
        if isinstance(node,ast.ClassDef):
            end=getattr(node,"end_lineno",node.lineno)
            methods=[m for m in node.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef))]
            fields=set()
            for m in methods:
                for n in ast.walk(m):
                    if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=="self":
                        fields.add(n.attr)
            # LCOM4: connected components over methods sharing self fields
            parent={x:x for x in fields}
            def find(x):
                while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
                return x
            def union(a,b):
                ra,rb=find(a),find(b)
                if ra!=rb: parent[ra]=rb
            nmeth=0
            for m in methods:
                fs=[x for x in self_fields(m) if not x.startswith("__")]
                if not fs: continue
                nmeth+=1
                first=fs[0]
                for o in fs[1:]: union(first,o)
            comps=len({find(x) for x in fields}) if fields else 0
            # LCOM* Henderson-Sellers
            m=len(methods); a=len(fields)
            if m>0 and a>0:
                sums=sum(len([x for x in self_fields(mt) if not x.startswith('__')]) for mt in methods)
                lcom_star = (m - sums/a)/(m-1) if m>1 else 0.0
            else:
                lcom_star=0.0
            rows.append(dict(file=rel,name="class "+node.name,line=node.lineno,loc=end-node.lineno+1,
                             cc=0,cog=0,nest=0,params=0,is_class=True,methods=len(methods),
                             fields=a,lcom4=comps,lcom_star=round(lcom_star,2)))
json.dump(rows, open("/home/user/analysis/deep.json","w"), indent=1)

print("=== WORST FUNCTIONS by CC ===")
print(f"{'CC':>4} {'cog':>4} {'LOC':>4} {'nest':>4} {'par':>4}  function")
for r in sorted([r for r in rows if not r.get("is_class")], key=lambda r:-r["cc"])[:25]:
    print(f"{r['cc']:4} {r['cog']:4} {r['loc']:4} {r['nest']:4} {r['params']:4}  {r['file']}:{r['line']} {r['name']}")

print()
print("=== GOD CLASSES (methods >= 12) ===")
print(f"{'methods':>7} {'LOC':>5} {'fields':>6} {'LCOM4':>5} {'LCOM*':>5}  class")
for r in sorted([r for r in rows if r.get("is_class") and r["methods"]>=12], key=lambda r:-r["methods"]):
    print(f"{r['methods']:7} {r['loc']:5} {r['fields']:6} {r['lcom4']:5} {r['lcom_star']:5}  {r['file']}:{r['line']} {r['name']}")

print()
print("=== LONGEST FUNCTIONS (>40 LOC) ===")
for r in sorted([r for r in rows if not r.get("is_class") and r["loc"]>40], key=lambda r:-r["loc"])[:20]:
    print(f"{r['loc']:5}  cc={r['cc']:3}  {r['file']}:{r['line']} {r['name']}")

print()
print("=== LONGEST PARAM LISTS (>5) ===")
for r in sorted([r for r in rows if r["params"]>5], key=lambda r:-r["params"])[:15]:
    print(f"{r['params']:3}  {r['file']}:{r['line']} {r['name']}")
