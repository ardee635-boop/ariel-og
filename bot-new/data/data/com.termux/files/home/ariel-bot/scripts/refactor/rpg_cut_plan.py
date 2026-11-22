import ast, symtable, builtins, sys, textwrap
SRC='/home/claude/new/engine/router/rpg.py'
src=open(SRC,encoding='utf-8').read(); L=src.split('\n')
tree=ast.parse(src)
cls=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RpgManager'][0]
fn=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_dispatch'][0]
body=fn.body
# group = (name, first stmt lineno, last stmt end_lineno)
GROUPS=[("registration",288,400),("reset",408,458),("character",468,527),("sim",537,602),
        ("fight",604,650),("trials_setup",654,886),("trials_weapons",889,1058),("actions",1068,1327)]
SHARED=['sender','text','quoted_text','group_jid','parts','cmd','rest','db','session','stripped_rest',
        'low_stripped_rest','low_rest','active_battle','active_trial','pending_class','pending_extra']
modnames={}
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.ClassDef)): modnames[n.name]='def'
    elif isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name): modnames[t.id]='const'
    elif isinstance(n,(ast.Import,ast.ImportFrom)):
        for a in n.names: modnames[(a.asname or a.name).split('.')[0]]='import'
def group_text(i):
    name,a,b=GROUPS[i]
    # include leading comment lines: start right after previous statement end
    stmts=[s for s in body]
    prev_end=max([s.end_lineno for s in stmts if s.end_lineno<a] or [fn.lineno])
    return prev_end+1,b
if __name__=='__main__':
    # verify groups tile the statement list exactly
    starts={s.lineno for s in body}; ends={s.end_lineno for s in body}
    for name,a,b in GROUPS:
        assert a in starts and b in ends,(name,a,b)
    for i,(name,a,b) in enumerate(GROUPS):
        s,e=group_text(i)
        code="def f(self, ctx):\n"+textwrap.indent(textwrap.dedent('\n'.join(L[s-1:e])),'    ')+"\n"
        st=symtable.symtable(code,'x','exec')
        f=[c for c in st.get_children()][0]
        loads=set(); stores=set()
        def walk(t,top=True):
            for sym in t.get_symbols():
                n=sym.get_name()
                if sym.is_global() and sym.is_referenced() and not (sym.is_assigned() and top): loads.add(n)
                if sym.is_assigned() and top: stores.add(n)
            for c in t.get_children(): walk(c,False)
        walk(f)
        stores={x for x in stores}
        free=sorted(n for n in loads if n not in dir(builtins))
        print(f"\n## {name}  lines {s}-{e}  ({e-s+1} lines)")
        print("  shared read :",[n for n in free if n in SHARED])
        print("  shared set  :",[n for n in SHARED if n in stores])
        print("  module names:",[(n,modnames[n]) for n in free if n in modnames])
        print("  UNKNOWN     :",[n for n in free if n not in SHARED and n not in modnames])
