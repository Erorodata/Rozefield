"""Replay the requests of a decoded official capture against Rozefield and compare the items each side gives.

  py devtools/compare_capture.py <decoded capture .json> <account id to test on> [Req name ...]

Works on a copy of the account (nothing is saved). Prints, per request type: same / different (official vs Rozefield items).
"""
import collections, copy, json, os, sys
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server')
sys.path.insert(0, HERE); os.chdir(HERE)
import logging; logging.disable(50)
from game.data import Data
from game.player import Player
from game import handlers as Hm, quests as Q

cap, pid = sys.argv[1], sys.argv[2]
only = set(sys.argv[3:])
msgs = json.load(open(cap, encoding='utf-8'))
d = Data()
base = json.load(open(os.path.join('save', 'accounts', f'{pid}.json'), encoding='utf-8'))


def items(body):
    out = collections.Counter()
    for k in ('items', 'rewards', 'updateItems', 'rewardItems'):
        for it in body.get(k) or []:
            m = it.get('mainItem', it)
            out[m.get('itemId')] += int((m.get('baseItem') or {}).get('num', 1) or 1)
    return dict(out)


class Srv:
    sessions, channels = {}, {}
    def broadcast(self, *a, **k): pass
    def is_online(self, pid): return False
    def player_by_id(self, pid): return None


rows = collections.defaultdict(list)
pending = {}
for m in msgs:
    n = m['name']
    if n.endswith('Req'):
        pending[n[:-3]] = m['body']
    elif n.endswith('Rsp') and n[:-3] in pending:
        req = pending.pop(n[:-3])
        rq = n[:-3] + 'Req'
        if (only and rq not in only) or rq not in Hm.H:
            continue
        p = Player.__new__(Player); p.d = d; p.s = copy.deepcopy(base); p.dirty = False
        class C:
            pass
        c = C(); c.p, c.d, c.server, c.chan, c.out = p, d, Srv(), None, []
        c.reply = lambda x, c=c: c.out.append(x); c.push = lambda nm, x: None
        try:
            Hm.H[rq](c, req)
        except Exception as e:
            c.out.append({'status': 'EXC ' + type(e).__name__})
        mine = c.out[0] if c.out else {}
        rows[rq].append((req, items(m['body']), items(mine), mine.get('status')))

for rq, lst in sorted(rows.items()):
    same = sum(1 for _, a, b, _ in lst if a == b)
    print(f'{rq}: {same}/{len(lst)} same')
    for req, a, b, st in lst:
        if a != b:
            print(f'   req {json.dumps(req)[:90]}  official {a}  rozefield {b} ({st})')
