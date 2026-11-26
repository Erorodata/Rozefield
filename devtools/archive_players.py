"""Collect every other player the captures saw into one archive file (kept private, never shipped).

    py tools\\archive_players.py capture1.pcapng [...] -o archive\\players_archive.json

Per player id: names seen, profile (OtherPlayerInfo / friend list), last scene look (team, outfits,
weapons), chat lines, and their garden furniture if you visited it.
"""
import argparse, json, os, sys
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # devtools package
from tools.make_save import streams  # noqa: E402
from ofproto import decode, to_dict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('captures', nargs='+')
    ap.add_argument('-o', '--out', default=os.path.join(HERE, 'archive', 'players_archive.json'))
    ap.add_argument('--self-id', type=int, default=0, help='your own player id (excluded)')
    a = ap.parse_args()
    P = {}

    def pl(pid):
        return P.setdefault(str(pid), {'player_id': pid, 'names': [], 'profile': {}, 'look': {}, 'chat': [], 'garden': {}, 'seen': []})

    for cap in a.captures:
        print('reading', cap)
        for port, msgs in streams(cap).items():
            for ts, d, h, body in msgs:
                if d != 'S2C':
                    continue
                try:
                    name, m = decode(h.msg_id, body)
                except Exception:
                    continue
                if name not in ('SceneDataNotice', 'OtherPlayerInfoRsp', 'FriendRsp', 'ChatMsgNotice', 'ChatMsgRecordInitNotice'):
                    continue
                x = to_dict(m)
                if name == 'SceneDataNotice':
                    sd = x.get('data', {})
                    for sp in sd.get('players', []):
                        r = pl(sp['player_id'])
                        if sp.get('player_name') and sp['player_name'] not in r['names']:
                            r['names'].append(sp['player_name'])
                        r['look'] = sp
                        r['seen'].append({'t': int(ts), 'scene': sd.get('sceneId'), 'channel': sd.get('channelId')})
                    ch = sd.get('channelId')
                    if ch and ch > 1000000 and sd.get('sceneGardenData'):
                        pl(ch)['garden'] = sd['sceneGardenData']
                elif name == 'OtherPlayerInfoRsp':
                    o = x.get('otherInfo', {})
                    if o.get('playerId'):
                        pl(o['playerId'])['profile'] = o
                elif name == 'FriendRsp':
                    for f in x.get('info', []):
                        o = f.get('info', {})
                        if o.get('playerId'):
                            pl(o['playerId'])['profile'].update(o)
                else:
                    msgs_ = x.get('msg', [])
                    for c in msgs_ if isinstance(msgs_, list) else [msgs_]:
                        if c.get('playerId'):
                            r = pl(c['playerId'])
                            line = {'t': c.get('sendTime'), 'text': c.get('text'), 'expression': c.get('expression')}
                            if line not in r['chat']:
                                r['chat'].append(line)
                            if c.get('name') and c['name'] not in r['names']:
                                r['names'].append(c['name'])
    P.pop(str(a.self_id), None)
    for r in P.values():
        r['seen'] = r['seen'][:1] + r['seen'][-1:] if len(r['seen']) > 2 else r['seen']
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(P, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(P)} players archived -> {a.out}  '
          f'({sum(1 for r in P.values() if r["garden"])} gardens, {sum(len(r["chat"]) for r in P.values())} chat lines)')


if __name__ == '__main__':
    main()
