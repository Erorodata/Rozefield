"""Find answers whose SHAPE differs from official: fields official sends that Rozefield leaves out, and notices
official pushes after a request that Rozefield doesn't (or the other way round).

  py devtools/compare_shapes.py <account id> <decoded capture .json> [more captures ...]

Only requests where both sides answered OK are compared (so missing state on the test account doesn't count).
"""
import collections, copy, json, os, sys
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server')
sys.path.insert(0, HERE); os.chdir(HERE)
import logging; logging.disable(50)
from game.data import Data
from game.player import Player
from game import handlers as Hm, quests as Q

pid, caps = sys.argv[1], sys.argv[2:]
d = Data()
base = json.load(open(os.path.join('save', 'accounts', f'{pid}.json'), encoding='utf-8'))
SKIP = {'PlayerSceneRecordReq', 'PlayerPingReq', 'PlayerLoginReq', 'VerifyLoginTokenReq', 'PlayerMainDataReq', 'SendChatMsgReq',
        'FriendAddReq', 'GmCodeReq', 'CreatePayOrderReq'}
NOISE = {'PlayerSceneSyncDataNotice', 'ServerSceneSyncDataNotice', 'SystemNotice', 'SendActionNotice', 'SceneInterActionPlayStatusNotice',
         'AchieveNotice', 'QuestNotice', 'PackNotice', 'ChatMsgNotice', 'PlayerPingRsp', 'UpdateNotice', 'GameNotice', 'ReceiveMailNotice',
         'MoonQuestGamePlayRewardNotice', 'SceneDataNotice'}


class Srv:
    sessions, channels = {}, {}
    def broadcast(self, sess, name, body, include_self=True):
        if include_self:
            sess.push(name, body)
    def is_online(self, pid): return False
    def player_by_id(self, pid): return None
    def join_channel(self, *a, **k): pass
    def scene_template(self, sid): return {}
    def player_by_label(self, l): return None


missing = collections.defaultdict(collections.Counter)
extra_notice = collections.defaultdict(collections.Counter)
miss_notice = collections.defaultdict(collections.Counter)
seen = collections.Counter()
for cap in caps:
    msgs = [m for m in json.load(open(cap, encoding='utf-8')) if isinstance(m, dict)]
    for i, m in enumerate(msgs):
        rq = m.get('name', '')
        if not rq.endswith('Req') or rq in SKIP or rq not in Hm.H or m.get('dir') != 'C2S':
            continue
        rsp, notes = None, []
        for x in msgs[i + 1:i + 40]:
            if x.get('dir') == 'C2S':
                if rsp is not None:
                    break
                continue
            if x['name'] == rq[:-3] + 'Rsp' and rsp is None:
                rsp = x['body']
            elif x['name'].endswith('Notice') and x['name'] not in NOISE and x['t'] - m['t'] < 1.0:
                notes.append(x['name'])
        if not rsp or rsp.get('status', 'StatusCode_OK') != 'StatusCode_OK':
            continue
        p = Player.__new__(Player); p.d = d; p.s = copy.deepcopy(base); p.dirty = False
        class C: pass
        c = C(); c.p, c.d, c.server, c.chan, out, pushes = p, d, Srv(), None, [], []
        c.out = out
        c.reply = lambda r: out.append(r); c.push = lambda n, r: pushes.append(n)
        try:
            Hm.H[rq](c, copy.deepcopy(m['body'])); Q.flush(c)
        except Exception as e:
            continue
        mine = out[0] if out else {}
        if mine.get('status', 'StatusCode_OK') != 'StatusCode_OK':
            continue
        seen[rq] += 1
        for k in rsp:
            if k not in mine:
                missing[rq][k] += 1
        mp = {n for n in pushes if n.endswith('Notice') and n not in NOISE}
        for n in set(notes) - mp:
            miss_notice[rq][n] += 1
        for n in mp - set(notes):
            extra_notice[rq][n] += 1

def common(counter, n):   # only what happens on at least half of the requests (others are other players / timers)
    return {k: v for k, v in counter.items() if v * 2 >= n}


for rq in sorted(seen):
    missing[rq] = common(missing[rq], seen[rq]); miss_notice[rq] = common(miss_notice[rq], seen[rq])
    extra_notice[rq] = common(extra_notice[rq], seen[rq])
    probs = []
    if missing[rq]:
        probs.append('fields missing: ' + ', '.join(f'{k} ({n}/{seen[rq]})' for k, n in missing[rq].items()))
    if miss_notice[rq]:
        probs.append('notices missing: ' + ', '.join(f'{k} ({n})' for k, n in miss_notice[rq].items()))
    if extra_notice[rq]:
        probs.append('notices official never sends: ' + ', '.join(f'{k} ({n})' for k, n in extra_notice[rq].items()))
    if probs:
        print(f'{rq} [{seen[rq]}]: ' + ' | '.join(probs))
