"""Copy a player's read-only progress answers (achievements, life skills, manual, archive flags, ...) from a decoded
official capture into their Rozefield save, so the server can answer those queries offline.

    py tools/import_records.py <capture_decoded.json> <save/accounts/<pid>.json>
"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from game.handlers import RECORD_QUERIES, record_key


def pairs(packets, every=False):
    """Req -> Rsp answers. every=False: only the read-only queries the server replays (RECORD_QUERIES)."""
    pend, out = {}, {}
    for p in packets:
        n, h = p.get('name', ''), p.get('head', {})
        if p['dir'] == 'C2S':
            pend[(p.get('port'), h.get('packet_id'))] = p
        elif n.endswith('Rsp'):
            q = pend.pop((p.get('port'), h.get('packet_id')), None)
            if q and q['name'][:-3] == n[:-3] and (every or q['name'] in RECORD_QUERIES):
                out.setdefault(q['name'], {})[record_key(q.get('body'))] = p.get('body') or {}
    return out


def main():
    cap, save = sys.argv[1:3]
    rec = pairs(json.load(open(cap, encoding='utf-8')))
    s = json.load(open(save, encoding='utf-8'))
    r = s.setdefault('records', {})
    for k, v in rec.items():
        r.setdefault(k, {}).update(v)
    json.dump(s, open(save, 'w', encoding='utf-8'), ensure_ascii=False)
    print({k: len(v) for k, v in rec.items()})


if __name__ == '__main__':
    main()
