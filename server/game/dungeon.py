"""Dungeons (story, resource, abyss...), vitality, and monster drops.

Flow seen on the official server: DungeonEnterReq -> DungeonEnterRsp(team, dungeon_data); DungeonOperateReq START;
MonsterDeadReq...; DungeonOperateReq END -> consumeTime; DungeonFinishReq -> rewards + dungeon_data;
DungeonExitReq -> scene_id, then the player is put back in the world (ChangeSceneChannelRsp + SceneDataNotice).

Rewards: Dungeon.RewardID (story dungeons, reward pool) or ManualShowReward[ShowRewardID] (resource dungeons:
the items the dungeon screen shows, ShowNum each). Resource dungeons cost ItemID/ItemNum (vitality, item 10),
charged when the reward is paid. Vitality regenerates 1 per Player_Recover_Vitality_Second up to the max.
"""
import random
import time

from game import quests as Q

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
VITALITY = 10


def vitality(p):
    """Lazy regen of vitality (item 10)."""
    d = p.d
    mx = int((d.config('Player_Vitality_Max_Count', ['100']) or ['100'])[0])
    step = int((d.config('Player_Recover_Vitality_Second', ['600']) or ['600'])[0]) or 600
    now = int(time.time())
    last = p.s.get('vit_t')
    if last is None:
        p.s['vit_t'] = now
        if p.count(VITALITY) < mx and not p.s.get('vit_init'):
            p.s['items'][str(VITALITY)] = mx
        p.s['vit_init'] = True
        p.dirty = True
        return p.count(VITALITY)
    gain = (now - last) // step
    if gain > 0:
        have = p.count(VITALITY)
        if have < mx:
            p.s['items'][str(VITALITY)] = min(mx, have + gain)
        p.s['vit_t'] = last + gain * step
        p.dirty = True
    return p.count(VITALITY)


def dstate(p, did):
    return p.s.setdefault('dungeons', {}).setdefault(str(did), {'dungeonId': did, 'enterTimes': 0, 'exitTimes': 0, 'finishTimes': 0})


def rewards_of(p, cfg):
    d = p.d
    if cfg.get('RewardID'):
        return d.reward_items(cfg['RewardID'], p.s['level'])
    show = d.row('manual', 'ManualShowReward', cfg.get('ShowRewardID', 0)) or {}
    out = []
    for it in show.get('ManualRewardItems', []):
        if it.get('ItemID'):
            out.append((it['ItemID'], it.get('ShowNum') or random.randint(1, 3)))
    return out


import json as _json, os as _os
try:
    DUNGEON_STARTS = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'dungeon_starts.json'), encoding='utf-8'))
except OSError:
    DUNGEON_STARTS = {}   # start points recorded from official DungeonEnterRsp (dungeon id -> char slot -> Pos/Rot)


def register(H, pack, enter_scene, scene_player):
    def enter(ctx, req, repeat=False):
        p = ctx.p
        did = ctx.__dict__.get('dungeon_id') if repeat else req.get('dungeon_id', 0)
        cfg = p.d.row('dungeon', 'Dungeon', did)
        if not cfg or cfg.get('NeedPlayerLevel', 1) > p.s['level']:
            return ctx.reply({'status': FAIL})
        if cfg.get('ItemID') and cfg.get('ItemNum') and (vitality(p) if cfg['ItemID'] == VITALITY else p.count(cfg['ItemID'])) < cfg['ItemNum']:
            return ctx.reply({'status': FAIL})
        ds = dstate(p, did)
        ds['enterTimes'] += 1
        ds['lastEnterTime'] = str(int(time.time()))
        chars = {k: req.get(k) for k in ('char1', 'char2', 'char3') if req.get(k)} or \
            {k: v for k, v in p.s['team'].items() if k in ('char1', 'char2', 'char3') and v}
        if not repeat:
            ctx.__dict__['dungeon_return'] = (p.s['scene_id'], p.s.get('channel_label'), req.get('Pos'), req.get('Rot'))
        ctx.__dict__.update(dungeon_id=did, dungeon_start=time.time(), dungeon_kills=0, dungeon_time=0, dungeon_box_open=False)
        team = {}
        start = DUNGEON_STARTS.get(str(did), {})
        for slot, cid in chars.items():
            sc = {'char_id': cid}
            # official: each member starts at the dungeon's own start point (never where you stood outside);
            # without a recorded start point the game uses the dungeon's born point
            if start.get(slot):
                sc.update(start[slot])
            team[slot] = sc
            ds[slot] = cid
        if req.get('Pos'):
            ds['pos'] = req['Pos']
        if req.get('Rot'):
            ds['rot'] = req['Rot']
        p.dirty = True
        ctx.reply({'status': OK, 'team': team, 'dungeon_data': dict(ds, monsters=[0])})
    H['DungeonEnterReq'] = enter
    H['DungeonRepeatEnterReq'] = lambda ctx, req: enter(ctx, req, repeat=True)

    def operate(ctx, req):
        if req.get('operateType') == 'END':
            took = int((time.time() - ctx.__dict__.get('dungeon_start', time.time())) * 1000)
            ctx.__dict__['dungeon_time'] = took
            cfg = ctx.d.row('dungeon', 'Dungeon', ctx.__dict__.get('dungeon_id', 0)) or {}
            star = 1 + sum(1 for k in ('StarTimer2', 'StarTimer3') if cfg.get(k) and took / 1000 <= cfg[k])
            ctx.__dict__['dungeon_star'] = star
            return ctx.reply({'status': OK, 'consumeTime': str(took), 'star': star})
        ctx.__dict__['dungeon_start'] = time.time()
        ctx.reply({'status': OK})
    H['DungeonOperateReq'] = operate

    def finish(ctx, req):
        p = ctx.p
        did = ctx.__dict__.get('dungeon_id')
        cfg = p.d.row('dungeon', 'Dungeon', did or 0)
        if not cfg:
            return ctx.reply({'status': FAIL})
        ds = dstate(p, did)          # rewards: the final chest (world.box_open, loc DUNGEON), as on the official server
        ds['finishTimes'] += 1
        ds['lastFinishTime'] = str(ctx.__dict__.get('dungeon_time', 0))
        ds['allTaskFinished'] = True
        ret = ctx.__dict__.get('dungeon_return') or (p.s['scene_id'], None, None, None)
        Q.event(p, Q.C['DungeonPass'], did)
        Q.reported(p, did)
        p.dirty = True
        ctx.reply({'status': OK, 'scene_id': ret[0], 'dungeon_data': dict(ds, monsters=[0])})
        if req.get('is_success', True):
            try:
                from game.events import moon_reward
                moon_reward(ctx, 1119, 5)
            except Exception:
                pass
    H['DungeonFinishReq'] = finish

    def exit_(ctx, req):
        p = ctx.p
        did = ctx.__dict__.pop('dungeon_id', None)
        if did:
            dstate(p, did)['exitTimes'] += 1
        ret = ctx.__dict__.pop('dungeon_return', None) or (p.s['scene_id'], p.s.get('channel_label'), None, None)
        if ret[2]:
            from game.handlers import set_pos, PUBLIC_SCENE
            set_pos(p.s, ret[2], ret[0], p.s['player_id'] if ret[0] == PUBLIC_SCENE else None)
        ctx.__dict__['temp_storage'] = []
        ctx.reply({'status': OK, 'scene_id': ret[0]})
        r = enter_scene(ctx, ret[0], label=ret[1])
        if r:
            ctx.push('ChangeSceneChannelRsp', {'status': OK, 'scene_id': ret[0], 'channel_id': r[0], 'channel_label': r[1]})
    H['DungeonExitReq'] = exit_

    def view(ctx, req):
        did = req.get('dungeon_id', 0)
        ctx.reply({'status': OK, 'dungeon_data': dict(dstate(ctx.p, did), monsters=[0])})
    H['DungeonViewReq'] = view

    def sweep(ctx, req):
        p = ctx.p
        did = req.get('dungeon_id', 0)
        cfg = p.d.row('dungeon', 'Dungeon', did)
        ds = dstate(p, did)
        if not cfg or not cfg.get('IsCanSweep') or not ds['finishTimes']:
            return ctx.reply({'status': FAIL})
        paid = []
        if cfg.get('ItemID') and cfg.get('ItemNum'):
            if cfg['ItemID'] == VITALITY:
                vitality(p)
            paid = p.pay([(cfg['ItemID'], cfg['ItemNum'])])
            if paid is None:
                return ctx.reply({'status': FAIL})
        got, changed = p.add_items(rewards_of(p, cfg))
        ds['finishTimes'] += 1
        Q.event(p, Q.C['DungeonPass'], did)
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, paid + changed)
    H['DungeonSweepReq'] = sweep

    def vit(ctx, req):
        vitality(ctx.p)
        ctx.reply({'status': OK, 'vitalityBuyNum': ctx.p.s.get('vit_buy', 0), 'items': [{'mainItem': ctx.p.item_info(VITALITY)}]})
    H['PlayerVitalityReq'] = vit

    # ---- monster drops: MonsterCharacterData.RewardPoolID, shown on the ground, picked up with PickupReq
    def monster_dead(ctx, req):
        p = ctx.p
        mid = req.get('monsterId', 0)
        m = p.d.row('monster', 'MonsterCharacterData', mid) or {}
        rsp = {'status': OK}
        if not ctx.__dict__.get('dungeon_id'):
            ctx.__dict__['kills_since_drop'] = ctx.__dict__.get('kills_since_drop', 0) + 1
        if m.get('RewardPoolID'):
            items = p.d.reward_items(m['RewardPoolID'], p.s['level'])
            if items:
                drops = ctx.__dict__.setdefault('drops', {})
                idx = len(drops) + 1
                drops[idx] = items
                rsp['dropItem'] = {'index': idx, 'items': [{'mainItem': p.item_info(i, n)} for i, n in items]}
                ctx.__dict__['kills_since_drop'] = 0
        ctx.reply(rsp)
        if not ctx.__dict__.get('dungeon_id') and random.random() < 0.25:   # field kill Moon Points (official id 1101)
            try:
                from game.events import moon_reward
                moon_reward(ctx, 1101, 5)
            except Exception:
                pass
        ctx.__dict__['dungeon_kills'] = ctx.__dict__.get('dungeon_kills', 0) + 1
        Q.event(p, Q.C['KillMonest'], mid)
        Q.event(p, Q.C['KillMonsterNum'])
    H['MonsterDeadReq'] = monster_dead

    def pickup(ctx, req):
        p = ctx.p
        items = ctx.__dict__.setdefault('drops', {}).pop(req.get('dropItemIndex', 0), None)
        if not items:
            return ctx.reply({'status': OK})
        got, changed = p.add_items(items)
        ctx.reply({'status': OK, 'items': got})
        pack(ctx, changed)
    H['PickupReq'] = pickup
