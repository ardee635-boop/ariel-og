"""One-off: cut RpgManager._dispatch into router/rpg_cmds/*.py (verbatim moves, AST-verified)."""
import ast, os, sys, shutil, textwrap
sys.path.insert(0,'/home/claude/tools')
import rpg_cut_plan as P
ROOT='/home/claude/new/engine/router'
SRC=ROOT+'/rpg.py'
if not os.path.exists('/tmp/rpg_orig.py'): shutil.copy(SRC,'/tmp/rpg_orig.py')
src=open(SRC,encoding='utf-8').read(); L=src.split('\n')
tree=ast.parse(src); fn=P.fn; body=P.body

DOCS={
 "registration":"`.reg`, `.setname`, `.rmenu` (character creation).",
 "reset":"`.rpg reset` / `.rpg delete` and the King-only `.resetworld`.",
 "character":"Known-command gate, session load, `.status`/`.skills`/`.skill`, `.inv`, `.equip`, `.rpg state`.",
 "sim":"`.rpg sim ...` test battles.",
 "fight":"Active real-fight interception (`.rpg <action>` while a battle is running).",
 "trials_setup":"Mage trial (recast / give up), Summoner species picker, Warrior weapon choice.",
 "trials_weapons":"Warrior trial mechanics: fight weapons, shield blocking, bow shooting.",
 "actions":"Pending-class confirmation and the main `.rpg <free text>` turn (movement, item pickup/hold, trial start, combat start).",
}
IMPORTS={
 'RpgSession':'from rpg_session import RpgSession','STARTING_LOCATION':'from rpg_session import STARTING_LOCATION',
 'handle_rpg_action':'from rpg_engine import handle_rpg_action','call_groq':'from rpg_llm import call_groq',
 'npc':'import npc','rpg_sim':'import rpg_sim','rpg_battle':'import rpg_battle','rpg_scene':'import rpg_scene',
 'trials':'import townia_trials as trials','is_king':'from permissions import is_king',
 'json':'import json','re':'import re','time':'import time',
}
HELPERS={'_with_choices','_maybe_fire_mage_delete','NOT_HANDLED','_read_more_pad','_READ_MORE_PAD','_ZERO_WIDTH_SPACE'}
SHARED=['sender','text','quoted_text','group_jid','parts','cmd','rest','db','session','stripped_rest',
        'low_stripped_rest','low_rest','active_battle','active_trial','pending_class','pending_extra']

def analyze(code):
    import symtable, builtins
    st=symtable.symtable(code,'x','exec'); f=st.get_children()[0]
    loads=set(); stores=set()
    def walk(t,top=True):
        for s in t.get_symbols():
            n=s.get_name()
            if s.is_global() and s.is_referenced() and not (s.is_assigned() and top): loads.add(n)
            if s.is_assigned() and top: stores.add(n)
        for c in t.get_children(): walk(c,False)
    walk(f)
    refd=set()
    def walk2(t):
        for s in t.get_symbols():
            if s.is_referenced(): refd.add(s.get_name())
        for c in t.get_children(): walk2(c)
    walk2(f)
    return {n for n in loads if n not in dir(builtins)}, stores, refd

groups=[]
for i,(name,a,b) in enumerate(P.GROUPS):
    s,e=P.group_text(i)
    orig_stmts=[st for st in body if a<=st.lineno and st.end_lineno<=b]
    raw=L[s-1:e]
    # dedent exactly 4 spaces (method body is 8, function body will be 4)
    ded=[(l[4:] if l.startswith('    ') else l) for l in raw]
    groups.append(dict(name=name,a=a,b=b,s=s,e=e,stmts=orig_stmts,text='\n'.join(ded)))

# which top-level names does each group assign unconditionally (statement-level Assign)?
for g in groups:
    g['top_assigned']={t.id for st in g['stmts'] if isinstance(st,ast.Assign) for t in st.targets if isinstance(t,ast.Name)}
# downstream reads
for i,g in enumerate(groups):
    probe="def f(self, ctx):\n"+textwrap.indent(g['text'],'    ')+"\n"
    loads,stores,refd=analyze(probe)
    g['loads']=loads; g['stores']=stores; g['refd']=refd
for i,g in enumerate(groups):
    later=set().union(*[h['loads'] for h in groups[i+1:]]) if i+1<len(groups) else set()
    g['writeback']=sorted(n for n in g['top_assigned'] if n in SHARED and n in later)
    g['unpack']=[n for n in SHARED if n in g['refd']]

os.makedirs(ROOT+'/rpg_cmds',exist_ok=True)
for g in groups:
    imps=[]; helper_imports=[]
    for n in sorted(g['loads']):
        if n in IMPORTS: imps.append(IMPORTS[n])
        elif n in HELPERS: helper_imports.append(n)
    helper_imports=sorted(set(helper_imports)|{'NOT_HANDLED'})
    # merge 'from rpg_session import A' lines
    merged={}
    plain=[]
    for l in imps:
        if l.startswith('from '):
            mod,names=l[5:].split(' import ')
            merged.setdefault(mod,[]).extend(names.split(', '))
        else: plain.append(l)
    imp_lines=sorted(plain)+[f"from {m} import {', '.join(sorted(set(n)))}" for m,n in sorted(merged.items())]
    out=[f'"""',f"router/rpg_cmds/{g['name']}.py - {DOCS[g['name']]}",'',
         f"Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines {g['s']}-{g['e']}).",
         "`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the",
         "reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.",
         '"""','']
    out+=imp_lines
    out.append(f"from ._common import {', '.join(helper_imports)}")
    out+=['','','def handle(self, ctx):']
    if g['unpack']:
        out.append('    '+', '.join(g['unpack'])+' = '+', '.join('ctx.'+n for n in g['unpack']))
    out.append(g['text'].rstrip('\n'))
    for n in g['writeback']: out.append(f"    ctx.{n} = {n}")
    out.append('    return NOT_HANDLED')
    code='\n'.join(out)+'\n'
    # ---- AST verification: moved statements identical to the originals ----
    gen=ast.parse(code)
    f=[n for n in gen.body if isinstance(n,ast.FunctionDef) and n.name=='handle'][0]
    new_stmts=f.body
    k=1 if g['unpack'] else 0
    new_core=new_stmts[k:len(new_stmts)-1-len(g['writeback'])]
    a=[ast.dump(x) for x in g['stmts']]; b=[ast.dump(x) for x in new_core]
    assert a==b, f"AST mismatch in {g['name']}: {len(a)} vs {len(b)}"
    open(f"{ROOT}/rpg_cmds/{g['name']}.py",'w',encoding='utf-8').write(code)
    print(f"{g['name']:15s} unpack={g['unpack']} writeback={g['writeback']} imports={imp_lines+helper_imports}")

# ---- _common.py : lines 35..127 of the original (NOT_HANDLED, read-more pad, _with_choices, _maybe_fire_mage_delete)
start=[i for i,l in enumerate(L) if l.startswith('NOT_HANDLED = object()')][0]
end=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_maybe_fire_mage_delete'][0].end_lineno
common_body='\n'.join(L[start:end])
common='''"""
router/rpg_cmds/_common.py - pieces shared by RpgManager and the handler modules.

Moved verbatim out of router/rpg.py (NOT_HANDLED, the "Read more" padding,
_with_choices, _maybe_fire_mage_delete) plus DispatchContext, the small bag of
locals the old 1,000-line _dispatch kept in function scope.
router/rpg.py re-exports all of these, so existing imports keep working.
"""
import time


class DispatchContext:
    """Locals that used to live in RpgManager._dispatch's scope, shared by the handler blocks."""
    def __init__(self, sender, text, quoted_text, group_jid, parts, cmd, rest, db):
        self.sender, self.text = sender, text
        self.quoted_text, self.group_jid = quoted_text, group_jid
        self.parts, self.cmd, self.rest, self.db = parts, cmd, rest, db
        # assigned by earlier blocks, read by later ones (same order as the old if-chain)
        self.session = None
        self.stripped_rest = self.low_stripped_rest = self.low_rest = None
        self.active_battle = self.active_trial = None
        self.pending_class = self.pending_extra = None


'''+common_body+'\n'
open(ROOT+'/rpg_cmds/_common.py','w',encoding='utf-8').write(common)

init='"""RpgManager._dispatch handler blocks, in dispatch order (see router/rpg.py)."""\n'
init+='from . import '+', '.join(g['name'] for g in groups)+'\n\n'
init+='HANDLERS = (\n'+''.join(f"    {g['name']}.handle,\n" for g in groups)+')\n'
open(ROOT+'/rpg_cmds/__init__.py','w',encoding='utf-8').write(init)

# ---- rewrite rpg.py
skeleton='''    def _dispatch(self, sender, text, quoted_text, group_jid):
        parts = text.split(maxsplit=1)
        if not parts:
            return None
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        db = self.router.db
        ctx = DispatchContext(sender, text, quoted_text, group_jid, parts, cmd, rest, db)

        # The old if-chain, one block per file in router/rpg_cmds/, in the same order.
        # A block returns the reply (None ends dispatch) or NOT_HANDLED to fall through.
        for handle in HANDLERS:
            result = handle(self, ctx)
            if result is not NOT_HANDLED:
                return result

        # Not one of ours \u2014 let it fall through to the rest of
        # handle() same as AmongUsManager does for unrecognized text
        # while in Among Us mode.
        return None
'''
new=L[:start]
new+=['from .rpg_cmds import HANDLERS',
      'from .rpg_cmds._common import (NOT_HANDLED, DispatchContext, _ZERO_WIDTH_SPACE, _READ_MORE_PAD,',
      '                               _read_more_pad, _with_choices, _maybe_fire_mage_delete)','']
new+=L[end:fn.lineno-1]
new+=skeleton.rstrip('\n').split('\n')
new+=L[fn.end_lineno:]
open(SRC,'w',encoding='utf-8').write('\n'.join(new))
print("rpg.py:",len(L),"->",len(new),"lines")
