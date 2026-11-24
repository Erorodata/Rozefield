"""Open-world state per scene: treasure chests, riddles, flags, challenges, encounters, areas, collections,
moons, field drops, and the dungeon reward chest. Modelled on the official 2026-11-24 capture:

  * SceneDataNotice of a field carries the scene's chests (index -> boxId, type) with the player's open state,
    and the player's riddles / flags / challenges / areas / collections / dungeons
  * DungeonFinishRsp carries no rewards: the client opens the dungeon chest (TreasureBoxOpenReq loc DUNGEON),
    the server answers the rewards in the temporary storage area, spends the vitality, and pushes
    DungeonOpenFinalBoxNotice; TreasureBoxPickupReq(pickIndex -1) moves them into the bag
  * Encounters / riddles / challenges: the Finish update answers a dynamic chest (boxId, index) that is then
    opened with TreasureBoxOpenReq(boxType DYNAMIC, treasureBoxIndex)
  * Field monster drops are picked up with PickupReq; the official server rolled gear + materials
  * Moons (CollectMoonReq) give 5 Moon currency (item 124)
Scene layouts (chest index -> boxId) come from data/scene_layout.json, built from the captures.
"""
import json
import os
import random
import time

from game import quests as Q

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
VITALITY, GOLD, MOON = 10, 101, 124
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAYOUT = None
_OBSERVED = None
_GEAR = {}


def layout():
    global _LAYOUT
    if _LAYOUT is None:
        p = os.path.join(HERE, 'data', 'scene_layout.json')
        _LAYOUT = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return _LAYOUT


def observed():
    """Dungeon chest contents seen on the official server (dungeonId -> [[item, n], ...])."""
    global _OBSERVED
    if _OBSERVED is None:
        p = os.path.join(HERE, 'data', 'dungeon_rewards_observed.json')
        _OBSERVED = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return _OBSERVED


def W(p, sid):
    w = p.s.setdefault('world', {}).setdefault(str(sid), {})
    for k, v in (('boxes', {}), ('riddles', []), ('flags', []), ('challenges', []), ('areas', []), ('collections', []),
                 ('flagIds', []), ('moons', []), ('encounters', {})):
        w.setdefault(k, v)
    return w


def scene_fields(p, sid):
    """Extra SceneData fields for a field scene: layout chests + this player's progress."""
    lay = layout().get(str(sid), {})
    w = W(p, sid)
    out = {}
    boxes = []
    now = int(time.time())
    for b in lay.get('treasureBoxes', []):
        st = w['boxes'].get(str(b['index']))
        e = {'index': b['index'], 'boxId': b['boxId'], 'type': b.get('type', 'ETreasureBoxType_Normal')}
        if st and (not st.get('refresh') or st['refresh'] > now):
            e['state'] = 'TreasureBoxState_Open'
            if st.get('refresh'):
                e['nextRefreshTime'] = str(st['refresh'])
        boxes.append(e)
    if boxes:
        out['treasureBoxes'] = boxes
    for k in ('riddles', 'flags', 'challenges', 'areas', 'collections', 'flagIds'):
        if w[k]:
            out[k] = w[k]
    for k in ('gatherLimits', 'chairInfoList', 'vehicleInfoList', 'campFires'):
        if lay.get(k):
            out[k] = lay[k]
    ds = [dict(v, monsters=v.get('monsters', [0])) for v in p.s.get('dungeons', {}).values()]
    if ds and str(sid) != '9999':
        out['dungeons'] = ds
    return out


# ------------------------------------------------------------------ reward rolls
def gear_pool(d):
    if not _GEAR:
        _GEAR['weapon'] = [i for i in d.table('weapon', 'Weapon') if 1100000 < i < 1500000]
        _GEAR['armor'] = [i for i in d.table('armor', 'Armor') if 2100000 < i < 2500000]
    return _GEAR


def roll_gear(d, n):
    g = gear_pool(d)
    out = []
    for _ in range(n):
        pool = g['weapon'] if random.random() < 0.35 else g['armor']
        if pool:
            out.append((random.choice(pool), 1))
    return out


def dungeon_chest(p, cfg, ds):
    """Contents of a dungeon's final chest."""
    did = str(cfg['ID'])
    if ds['finishTimes'] == 1 and cfg.get('RewardID'):          # first clear: the dungeon's own reward pool
        return p.d.reward_items(cfg['RewardID'], p.s['level'])
    obs = observed().get(did)
    if obs:
        return [(i, max(1, n + (random.randint(-2, 2) if i in (190, 191, 192) and n > 3 else 0))) for i, n in obs]
    show = p.d.row('manual', 'ManualShowReward', cfg.get('ShowRewardID', 0)) or {}
    items = [x for x in show.get('ManualRewardItems', []) if x.get('ItemID')]
    gear = [x['ItemID'] for x in items if 1100000 < x['ItemID'] < 2500000]
    out = []
    if gear:
        out += [(random.choice(gear), 1) for _ in range(random.randint(4, 6))]
    out += [(x['ItemID'], x.get('ShowNum') or random.randint(1, 2)) for x in items
            if not (1100000 < x['ItemID'] < 2500000) and x['ItemID'] != 1]
    if not out:   # story dungeon repeat clear (official: 500 gold, 3-6 small + 1 medium exp book)
        out = [(GOLD, 500), (190, random.randint(3, 6)), (191, 1)]
    out.append((1, 300 if cfg.get('NewMissionType') != 7 or gear else 200))
    return out


def register(H, pack, scene_player):
    def temp(ctx):
        return ctx.__dict__.setdefault('temp_storage', [])

    def give(ctx, items, store=True):
        """Grant now, answer as temporary storage (picked up by TreasureBoxPickupReq)."""
        p = ctx.p
        got, changed = p.add_items(items) if items else ([], [])
        if store:
            temp(ctx).extend(got)
        return [dict(g, packType='PackType_TempStorageArea') for g in got], changed

    def box_open(ctx, req):
        p = ctx.p
        loc, btype = req.get('loc_type'), req.get('boxType')
        if loc == 'TreasureBoxLocType_DUNGEON':
            did = ctx.__dict__.get('dungeon_id')
            cfg = p.d.row('dungeon', 'Dungeon', did or 0)
            if not cfg or ctx.__dict__.get('dungeon_box_open'):
                return ctx.reply({'status': FAIL})
            ds = p.s.setdefault('dungeons', {}).get(str(did)) or {'finishTimes': 1}
            paid = []
            if cfg.get('ItemID') and cfg.get('ItemNum'):
                from game.dungeon import vitality
                if cfg['ItemID'] == VITALITY:
                    vitality(p)
                paid = p.pay([(cfg['ItemID'], cfg['ItemNum'])])
                if paid is None:
                    return ctx.reply({'status': FAIL})
            ctx.__dict__['dungeon_box_open'] = True
            items, changed = give(ctx, dungeon_chest(p, cfg, ds))
            ctx.push('DungeonOpenFinalBoxNotice', {'status': OK, 'dungeonId': did})
            ctx.reply({'status': OK, 'items': items})
            pack(ctx, paid + changed)
            Q.event(p, Q.C['OpenBox'])
            return
        if btype == 'TREASURE_BOX_TYPE_DYNAMIC':
            dyn = ctx.__dict__.setdefault('dynamic_boxes', {}).pop(req.get('treasureBoxIndex', 0), None)
            if dyn is None:
                return ctx.reply({'status': FAIL})
            items, changed = give(ctx, [(GOLD, random.randint(60, 120))] + roll_gear(p.d, random.randint(2, 3)))
            ctx.reply({'status': OK, 'items': items})
            pack(ctx, changed)
            Q.event(p, Q.C['OpenBox'])
            return
        # static chest in the field
        idx = req.get('treasureBoxIndex', 0)
        sid = p.s['scene_id']
        w = W(p, sid)
        box = next((b for b in layout().get(str(sid), {}).get('treasureBoxes', []) if b['index'] == idx), None)
        st = w['boxes'].get(str(idx))
        if st and (not st.get('refresh') or st['refresh'] > time.time()):
            return ctx.reply({'status': FAIL})
        cfg = (p.d.row('treasurebox', 'TreasureBox', box['boxId']) or {}) if box else {}
        refresh = 0
        try:
            coll = p.d.table('treasurebox', 'CollectionTreasureBox')
        except Exception:
            coll = {}
        if box and box['boxId'] in coll:
            refresh = int(time.time()) + 3 * 86400
        w['boxes'][str(idx)] = {'refresh': refresh}
        p.dirty = True
        big = cfg.get('NewTreasureBoxRewardShowType', 1) >= 3
        items = [(GOLD, random.randint(300, 600) if big else random.randint(80, 200)), (190, random.randint(2, 4) if big else 1)]
        if big:
            items += roll_gear(p.d, 1) + [(102, 10)]
        items, changed = give(ctx, items)
        ctx.reply({'status': OK, 'items': items})
        pack(ctx, changed)
        Q.event(p, Q.C['OpenBox'])
        Q.event(p, Q.C['OpenBox0'])
    H['TreasureBoxOpenReq'] = box_open

    def box_pickup(ctx, req):
        items = temp(ctx)
        ctx.__dict__['temp_storage'] = []
        ctx.reply({'status': OK, 'items': [{k: v for k, v in i.items() if k != 'packType'} for i in items]})
    H['TreasureBoxPickupReq'] = box_pickup

    def dyn_box(ctx, box_id=300000):
        n = ctx.__dict__.get('dyn_index', 600) + 1
        ctx.__dict__['dyn_index'] = n
        ctx.__dict__.setdefault('dynamic_boxes', {})[n] = box_id
        return {'boxId': box_id, 'index': n}

    def encounter(ctx, req):
        p = ctx.p
        eid = req.get('encounter_id', 0)
        w = W(p, p.s['scene_id'])
        if req.get('battleState') == 'Finish':
            w['encounters'][str(eid)] = int(time.time())
            p.dirty = True
            ctx.reply({'status': OK, 'encounter': {'battleId': eid, 'state': 'Finish'}, 'dynamicTreasureBoxBaseInfo': dyn_box(ctx)})
            Q.event(p, Q.C['FinishEncounter'])
            Q.event(p, Q.C['FinishTheEncounter'], eid)
            return
        ctx.reply({'status': OK, 'encounter': {'battleId': eid, 'boxId': 300000}})
    H['BattleEncounterStateUpdateReq'] = encounter

    def encounter_info(ctx, req):
        p = ctx.p
        w = W(p, p.s['scene_id'])
        out = []
        for eid in req.get('encounter_ids', []):
            cd = (p.d.row('battleencounter', 'BattleEncounter', eid) or {}).get('CD', 600)
            done = w['encounters'].get(str(eid), 0)
            out.append({'battleId': eid, 'state': 'Finish' if time.time() - done < cd else 'Close'})
        ctx.reply({'status': OK, 'encounters': out})
    H['BattleEncounterInfoReq'] = encounter_info

    def riddle(ctx, req):
        p = ctx.p
        rid = req.get('riddle_id', 0)
        w = W(p, p.s['scene_id'])
        r = next((x for x in w['riddles'] if x.get('riddleId') == rid), None)
        if r is None:
            r = {'riddleId': rid}
            w['riddles'].append(r)
        rsp = {'status': OK, 'riddle_data': r}
        if req.get('battle_state') == 'Finish' and req.get('is_win') and not r.get('isWin'):
            r['isWin'] = True
            rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx)
            from game.progression import ach_event
            ach_event(p, 'Riddle0')
            ach_event(p, 'Riddle12', rid)
        p.dirty = True
        ctx.reply(rsp)
        Q.reported(p, rid)
    H['RiddleStateUpdateReq'] = riddle

    def challenge(ctx, req):
        p = ctx.p
        cid = req.get('challenge_id', 0)
        w = W(p, p.s['scene_id'])
        c = next((x for x in w['challenges'] if x.get('challengeId') == cid), None)
        rsp = {'status': OK}
        if req.get('battle_state') == 'Finish':
            first = c is None
            if c is None:
                c = {'challengeId': cid}
                w['challenges'].append(c)
            if req.get('use_time') and (not c.get('useTime') or req['use_time'] < c['useTime']):
                c['useTime'] = req['use_time']
            if first:
                rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx)
                from game.progression import ach_event
                ach_event(p, 'Challenge12', cid)
            p.dirty = True
        rsp['challenge_data'] = c or {'challengeId': cid}
        ctx.reply(rsp)
        Q.reported(p, cid)
    H['ChallengeStateUpdateReq'] = challenge

    def flag(ctx, req):
        p = ctx.p
        bid = req.get('battle_id', 0)
        w = W(p, p.s['scene_id'])
        f = next((x for x in w['flags'] if x.get('battleId') == bid), None)
        rsp = {'status': OK}
        if req.get('battle_state') == 'Finish':
            first = f is None or f.get('state') != 'Finish'
            if f is None:
                f = {'battleId': bid}
                w['flags'].append(f)
            f['state'] = 'Finish'
            f['finishTimes'] = f.get('finishTimes', 0) + 1
            if req.get('mission_type'):
                f['type'] = req['mission_type']
            if first:
                rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx)
            p.dirty = True
            Q.event(p, Q.C['FinishMission'], bid)
            Q.reported(p, bid)
        rsp['battle_data'] = f or {'battleId': bid}
        ctx.reply(rsp)
    H['FlagBattleStateUpdateReq'] = flag

    def area_unlock(ctx, req):
        p = ctx.p
        aid = req.get('areaId', 0)
        w = W(p, p.s['scene_id'])
        a = next((x for x in w['areas'] if x.get('areaId') == aid), None)
        if a is None:
            a = {'areaId': aid, 'areaState': 'Unlock', 'level': 1}
            w['areas'].append(a)
            p.dirty = True
            Q.event(p, Q.C['AreaUlockNum'], absolute=sum(len(W(p, s)['areas']) for s in p.s['world']))
        ctx.reply({'status': OK, 'area': a})
    H['AreaUnlockReq'] = area_unlock

    # ---- moons
    def moon(ctx, req):
        p = ctx.p
        mid = req.get('moonId', 0)
        w = W(p, p.s['scene_id'])
        if mid in w['moons']:
            return ctx.reply({'status': FAIL})
        w['moons'].append(mid)
        got, changed = p.add_items([(MOON, 5)])
        ctx.reply({'status': OK, 'moonId': mid, 'rewards': got})
        pack(ctx, changed)
    H['CollectMoonReq'] = moon
    H['GetCollectMoonInfoReq'] = lambda ctx, req: ctx.reply(
        {'status': OK, 'sceneId': req.get('sceneId', 0), 'collectedMoonIds': W(ctx.p, req.get('sceneId', 0))['moons']})

    # ---- field drops (PickupReq): the official server rolled 3-5 pieces of gear, sometimes a material
    def pickup(ctx, req):
        p = ctx.p
        items = ctx.__dict__.setdefault('drops', {}).pop(req.get('dropItemIndex', 0), None)
        if items is None:
            kills = ctx.__dict__.pop('kills_since_drop', 0)
            if not kills:
                return ctx.reply({'status': OK})
            items = roll_gear(p.d, random.randint(3, 5))
            if random.random() < 0.3:
                items.append((random.choice((1030, 1032, 1020, 1022, 1010, 1012, 1000, 1002)), random.randint(1, 4)))
        got, changed = p.add_items(items)
        ctx.reply({'status': OK, 'items': got})
        pack(ctx, changed)
    H['PickupReq'] = pickup

    H['PlayerVitalityReq'] = lambda ctx, req: (__import__('game.dungeon', fromlist=['x']).vitality(ctx.p), ctx.reply({'status': OK}))
