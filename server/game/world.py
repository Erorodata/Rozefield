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


_BOX_ITEMS = None


def _secs(t):
    """Chest refresh times: imported official values are milliseconds, Rozefield's own are seconds."""
    t = int(t or 0)
    return t // 1000 if t > 10 ** 11 else t


def box_items():
    """Official contents of dungeon chests along the way (boxId -> [[item, n], ...]), from captures."""
    global _BOX_ITEMS
    if _BOX_ITEMS is None:
        try:
            _BOX_ITEMS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dungeon_box_items.json'), encoding='utf-8'))
        except OSError:
            _BOX_ITEMS = {}
    return _BOX_ITEMS


def W(p, sid):
    w = p.s.setdefault('world', {}).setdefault(str(sid), {})
    for k, v in (('boxes', {}), ('riddles', []), ('flags', []), ('challenges', []), ('areas', []), ('collections', []),
                 ('flagIds', []), ('moons', []), ('encounters', {})):
        w.setdefault(k, v)
    return w


_FLAGS = {}


def map_flags(d):
    """Main game data, from the game's own tables (the same for every player): per map, the entrances that show on
    it - landmarks, Aberrant Fields, Sequence Fields. Returns {scene: [(flagId, questId or None)]}: an entrance whose
    dungeon is a main-story quest step only shows once that quest is given to the player.
    (Checked against the official captures: a fully explored account had exactly these.)"""
    if id(d) in _FLAGS:
        return _FLAGS[id(d)]
    flags = d.table('flag', 'Flag')
    global_flags = set()
    try:   # entrances only exist in maps the Global client has (CN-only ones have no object in the map)
        gp = os.path.join(HERE, 'data', 'flag.json')
        global_flags = {r['ID'] for r in json.load(open(gp, encoding='utf-8'))['Flag']['datas']}
    except (OSError, ValueError, KeyError):
        global_flags = set(flags)
    dungeons = d.table('dungeon', 'Dungeon')
    from game import quests as Q
    x = Q.idx(d)
    quest_of_dungeon, quest_of_battle = {}, {}
    for qid in x['quests']:
        for c in Q.conditions_of(d, qid):
            a = x['ach'].get(c) or {}
            if a.get('NewAchieveCondition') == 6:      # "finish dungeon X" step of a quest
                for prm in a.get('Param') or []:
                    quest_of_dungeon.setdefault(prm, qid)
            elif a.get('NewAchieveCondition') == 4:    # "finish mission X" (story battle, e.g. Eliminate Ashen Creatures)
                for prm in a.get('Param') or []:
                    quest_of_battle.setdefault(prm, qid)
    out = {}
    for f in flags.values():
        g = (f.get('FlagGroupInfo') or [{}])[0]
        t = g.get('NewMissionType')
        if f['ID'] not in global_flags or not g.get('IsItemUnlock'):
            continue
        if t == 1:
            out.setdefault(f.get('SceneID'), []).append((f['ID'], None))
        elif t in (5, 7):
            dg = dungeons.get(g.get('RelationID')) or {}
            if dg.get('WorldID') == f.get('SceneID'):
                out.setdefault(f.get('SceneID'), []).append((f['ID'], quest_of_dungeon.get(g.get('RelationID'))))
        elif not t and g.get('RelationID') in quest_of_battle:
            # story battle marker: shown only while its quest step is in progress (official removes it with
            # FlagUnLockRemoveNotice when the battle is won)
            out.setdefault(f.get('SceneID'), []).append((f['ID'], -quest_of_battle[g['RelationID']]))
    _FLAGS[id(d)] = out
    return out


def flag_shown(p, q):
    """q None: always; q > 0: once that quest was given; q < 0: only while quest -q is in progress."""
    qs = p.s.get('quests', {})
    if q is None:
        return True
    if q > 0:
        return str(q) in qs
    st = (qs.get(str(-q)) or {}).get('status')
    return st == 'QuestStatus_InProgress'


def story_flags_changed(ctx, changed_qids):
    """A story battle step started or ended while the player is on that map: add / remove its marker live."""
    p = ctx.p
    sid = p.s.get('scene_id')
    add, rem = [], []
    for fid, q in map_flags(p.d).get(int(sid or 0), []):
        if q is not None and q < 0 and str(-q) in changed_qids:
            (add if flag_shown(p, q) else rem).append(fid)
    if add:
        ctx.push('FlagUnlockAddNotice', {'status': 'StatusCode_OK', 'flagIds': add})
    if rem:
        ctx.push('FlagUnLockRemoveNotice', {'status': 'StatusCode_OK', 'flagIds': rem})


def scene_fields(p, sid):
    """Extra SceneData fields for a field scene: layout chests + this player's progress."""
    lay = layout().get(str(sid), {})
    w = W(p, sid)
    out = {}
    boxes = []
    now = int(time.time())
    seen_idx = set()
    for b in lay.get('treasureBoxes', []):
        seen_idx.add(str(b['index']))
        st = w['boxes'].get(str(b['index']))
        e = {'index': b['index'], 'boxId': b['boxId'], 'type': b.get('type', 'ETreasureBoxType_Normal')}
        if st and (not st.get('refresh') or _secs(st['refresh']) > now):
            e['state'] = 'TreasureBoxState_Open'
            if st.get('refresh'):
                e['nextRefreshTime'] = str(_secs(st['refresh']) * 1000)   # official: milliseconds
        boxes.append(e)
    for k, st in w['boxes'].items():
        if k in seen_idx or not k.isdigit():
            continue
        if not st.get('refresh') or _secs(st['refresh']) > now:
            e = {'index': int(k), 'type': st.get('type', 'ETreasureBoxType_Normal'), 'state': 'TreasureBoxState_Open'}
            if st.get('boxId'):
                e['boxId'] = st['boxId']
            if st.get('refresh'):
                e['nextRefreshTime'] = str(_secs(st['refresh']) * 1000)
            boxes.append(e)
    if boxes:
        out['treasureBoxes'] = boxes
    for k in ('riddles', 'flags', 'challenges', 'areas', 'collections', 'flagIds'):
        if w[k]:
            out[k] = w[k]
    ids = {fid for fid, q in map_flags(p.d).get(int(sid), []) if flag_shown(p, q)}
    ids |= set(w['flagIds'])          # anything the player's own save already has
    ids -= set(w.get('flags_removed', []))   # battles won on Rozefield (official removes the marker)
    if ids:
        out['flagIds'] = sorted(ids)
    for k in ('chairInfoList', 'vehicleInfoList', 'campFires'):
        if lay.get(k):
            out[k] = lay[k]
    from game.life import scene_gather_limits   # the player's own counts (imported from their backup, then kept here)
    out['gatherLimits'] = scene_gather_limits(p, sid)
    dt = p.d.table('dungeon', 'Dungeon')   # official sends each map only its own dungeons (by WorldID)
    mine = {int(k): v for k, v in p.s.get('dungeons', {}).items()}
    ds = [dict({k: x for k, x in v.items() if k not in ('openedBoxes', 'tasks')}, monsters=v.get('monsters', [0])) for v in mine.values()
          if (dt.get(int(v.get('dungeonId', 0))) or {}).get('WorldID') == int(sid)]
    if ds and str(sid) != '9999':
        out['dungeons'] = ds
    return out


# ------------------------------------------------------------------ reward rolls
def gear_pool(d):
    if not _GEAR:
        _GEAR['weapon'] = [i for i in d.table('weapon', 'Weapon') if 1100000 < i < 1500000]
        _GEAR['armor'] = [i for i in d.table('armor', 'Armor') if 2100000 < i < 2500000]
    return _GEAR


from game import packs as _packs
QUALITY_WEIGHTS = tuple(_packs.system('world', 'drop_quality_weights', [30, 30, 25, 12, 3]))  # base weights at World Level 0
WORLD_LEVELS = _packs.int_keys(_packs.system('world', 'world_levels', {}))


def world_level_cfg(wl):
    """Official World Level 0-5 scaling (gold_mult, epic_bonus_pct, max_gear_lv) from world.json."""
    wl = max(0, min(5, int(wl or 0)))
    return WORLD_LEVELS.get(wl) or {'gold_mult': 1.0 + 0.25 * wl, 'epic_bonus_pct': 0, 'max_gear_lv': 39 + wl * 12}


def _gear_key(i):
    """(quality 1-5, tier 1-10) from the id: weapon 1TSSQTT (Q at [4], tier [5:]), armor 2SPQTTT (Q at [3], tier [4:])."""
    s = str(i)
    return (int(s[4]), int(s[5:])) if s[0] == '1' else (int(s[3]), int(s[4:]))


def roll_gear(d, n, world_level=None):
    """Field / chest gear. Tier follows world level; Epic+ (quality 4-5) rate scales by official World Level bonus
    (+0% / +19% / +36% / +52% / +67% / +80% for WL 0-5)."""
    g = gear_pool(d)
    out = []
    wl = 0 if world_level is None else max(0, min(5, int(world_level)))
    bonus = 1.0 + world_level_cfg(wl).get('epic_bonus_pct', 0) / 100.0
    weights = (QUALITY_WEIGHTS[0], QUALITY_WEIGHTS[1], QUALITY_WEIGHTS[2],
               QUALITY_WEIGHTS[3] * bonus, QUALITY_WEIGHTS[4] * bonus)
    for _ in range(n):
        pool = g['weapon'] if random.random() < 0.35 else g['armor']
        if not pool:
            continue
        if world_level is not None:
            tier = max(1, min(10, max(1, wl) + random.choice((-1, 0, 0, 1))))
            q = random.choices((1, 2, 3, 4, 5), weights=weights)[0]
            pick = [i for i in pool if _gear_key(i) == (q, tier)] or [i for i in pool if _gear_key(i)[1] == tier] or pool
            out.append((random.choice(pick), 1))
        else:
            out.append((random.choice(pool), 1))
    return out


def dungeon_chest(p, cfg, ds):
    """Contents of a dungeon's final chest."""
    did = str(cfg['ID'])
    # (RewardID is the dungeon's task reward, paid by DungeonTaskFinishRewardReq, not chest contents)
    obs = observed().get(did)
    if obs:
        return [(i, max(1, n + (random.randint(-1, 1) if i in (190, 191, 192) and n > 3 else 0))) for i, n in obs]
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


def _moon(ctx, gid, n):
    try:
        from game.events import moon_reward
        moon_reward(ctx, gid, n)
    except Exception:
        pass


def _moon_update(ctx):
    try:
        from game import events
        before = events._ev(ctx.p).get('daily_task', {}).get('left', 0)
        dt = events._daily_task(ctx.p)
        if dt['exchange_times_left'] != before:
            ctx.push('DailyTaskUpdateNotice', dict(status=OK, **dt))
    except Exception:
        pass


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
            if not cfg:
                return ctx.reply({'status': FAIL})
            from game.dungeon import dungeon_boxes, is_final_box, dstate
            idx = req.get('treasureBoxIndex', 0)
            box = next((b for b in dungeon_boxes(p, did) if b.get('index', 0) == idx), None)
            if box and not is_final_box(p, did, box['boxId']):
                # a chest along the way (official: no final-chest notice, never refills)
                ds = dstate(p, did)
                if idx in ds.setdefault('openedBoxes', []):
                    return ctx.reply({'status': FAIL})
                ds['openedBoxes'].append(idx)
                p.dirty = True
                seen = box_items().get(str(box['boxId']))
                if seen:
                    loot = [tuple(x) for x in seen]
                elif (p.d.row('treasurebox', 'TreasureBox', box['boxId']) or {}).get('NewTreasureBoxRewardType') == 4:
                    loot = []
                if (p.d.row('treasurebox', 'TreasureBox', box['boxId']) or {}).get('NewTreasureBoxRewardType') == 4:
                    ds['isOpenSecretBox'] = True   # hidden chest: the map's dungeon list shows it as found (official)
                else:
                    loot = [(1102, 3)] if random.random() < 0.5 else roll_gear(p.d, 1, p.s.get('world_level', 1))
                items, changed = give(ctx, loot)
                ctx.reply({'status': OK, 'items': items})
                pack(ctx, changed)
                Q.event(p, Q.C['OpenBox'], p.s.get('scene_id', 0))
                from game.dungeon import task_event, TASK_CHEST
                task_event(ctx, TASK_CHEST)
                return
            if ctx.__dict__.get('dungeon_box_open'):
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
            if not str(did).startswith(('111', '511')):   # official: resource dungeons only, never Sequences
                ctx.push('DungeonOpenFinalBoxNotice', {'status': OK, 'dungeonId': did})
            ctx.reply({'status': OK, 'items': items})
            pack(ctx, paid + changed)
            Q.event(p, Q.C['OpenBox'], p.s.get('scene_id', 0))
            return
        if btype == 'TREASURE_BOX_TYPE_DYNAMIC':
            dyn = ctx.__dict__.setdefault('dynamic_boxes', {}).pop(req.get('treasureBoxIndex', 0), None)
            if dyn is None:
                return ctx.reply({'status': FAIL})
            items, changed = give(ctx, [(GOLD, random.randint(60, 120))] + roll_gear(p.d, random.randint(2, 3), p.s.get('world_level', 1)))
            if random.random() < 0.5:     # field chest Moon Points (official id 1120)
                _moon(ctx, 1120, 5)
            ctx.reply({'status': OK, 'items': items})
            pack(ctx, changed)
            Q.event(p, Q.C['OpenBox'], p.s.get('scene_id', 0))
            return
        # static chest in the field
        idx = req.get('treasureBoxIndex', 0)
        sid = p.s['scene_id']
        w = W(p, sid)
        box = next((b for b in layout().get(str(sid), {}).get('treasureBoxes', []) if b['index'] == idx), None)
        st = w['boxes'].get(str(idx))
        if st and (not st.get('refresh') or _secs(st['refresh']) > time.time()):
            return ctx.reply({'status': FAIL})
        cfg = (p.d.row('treasurebox', 'TreasureBox', box['boxId']) or {}) if box else {}
        refresh = 0
        try:
            coll = p.d.table('treasurebox', 'CollectionTreasureBox')
        except Exception:
            coll = {}
        if box and box['boxId'] in coll:
            # official: the chest's own RefreshTime (field chests 14400 s = 4 h); 0 = one-time permanent
            secs = (coll[box['boxId']].get('RefreshTime') or [0])[0]
            refresh = int(time.time()) + secs if secs else 0
        else:
            # unindexed field chest: default 4 h countdown so claimed status -> inactive -> active at 0
            refresh = int(time.time()) + 14400
        w['boxes'][str(idx)] = {
            'refresh': refresh,
            'boxId': box['boxId'] if box else 0,
            'type': (box or {}).get('type', 'ETreasureBoxType_Normal'),
        }
        p.dirty = True
        wl = p.s.get('world_level', 0)
        gmult = world_level_cfg(wl).get('gold_mult', 1.0)
        tr_rate = p.drop_rate_info()['treasureDropRate']
        tmult = tr_rate / 100.0
        big = cfg.get('NewTreasureBoxRewardShowType', 1) >= 3
        if big:
            n_gear = 2 if (tr_rate >= 50 or random.random() < tmult) else 1
            items = roll_gear(p.d, n_gear, wl) + [(102, max(2, int(round(20 * tmult)))), (GOLD, max(10, int(random.randint(400, 800) * gmult * tmult)))]
        else:
            items = [(GOLD, max(10, int(random.randint(80, 200) * gmult * tmult))), (190, 1)]
        items, changed = give(ctx, items)
        if random.random() < 0.5 * tmult:   # field chest Moon Points (official id 1120)
            _moon(ctx, 1120, 5)
        rsp = {'status': OK, 'items': items}
        if refresh:
            rsp['nextRefreshTime'] = str(refresh * 1000)   # official: milliseconds
        ctx.reply(rsp)
        pack(ctx, changed)
        new_rates = p.record_fatigue('chests', 1)
        if new_rates['treasureDropRate'] != tr_rate:
            ctx.push('PlayerTiredDropNotice', {'status': OK, 'dropRateInfo': new_rates})
        Q.event(p, Q.C['OpenBox'], sid)
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
            _moon(ctx, 1119, 5)
            from game.progression import team_exp
            team_exp(ctx, _packs.system('battle', 'team_exp', {}).get('encounter', 300))
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
        if req.get('battle_state') == 'Finish' and req.get('is_win'):
            first = not r.get('isWin')
            r['isWin'] = True
            r['state'] = 'Finish'                              # official (2026-11-27 capture): client waits for state='Finish'
            rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx, box_id=2002)   # official capture: boxId 2002 present box
            if first:
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
            first = c is None or c.get('state') != 'Finish'
            if c is None:
                c = {'challengeId': cid}
                w['challenges'].append(c)
            c['state'] = 'Finish'                                  # official: client waits for state='Finish' to end the challenge
            c['star'] = max(int(c.get('star', 0) or 0), 3)
            if req.get('use_time') and (not c.get('useTime') or req['use_time'] < c['useTime']):
                c['useTime'] = req['use_time']
            rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx, box_id=2002)   # official capture: boxId 2002 on finish
            if first:
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
        is_scenic = req.get('mission_type') == 'EMissionType_ScenicSpot'
        if req.get('battle_state') == 'Finish' or is_scenic:
            first = f is None or f.get('state') != 'Finish'
            if f is None:
                f = {'battleId': bid}
                w['flags'].append(f)
            f['state'] = 'Finish'
            f['finishTimes'] = f.get('finishTimes', 0) + 1
            if req.get('mission_type'):
                f['type'] = req['mission_type']
            if first and not is_scenic:
                rsp['dynamicTreasureBoxBaseInfo'] = dyn_box(ctx)
            p.dirty = True
            if is_scenic:
                Q.event(p, 96, p.s.get('scene_id', 0))   # CollectScenic12 (Star Sigil / scenic spots; never triggers combat FinishMission)
            else:
                Q.event(p, Q.C['FinishMission'], bid)
                Q.reported(p, bid)
        rsp['battle_data'] = f or {'battleId': bid}
        ctx.reply(rsp)
        if req.get('battle_state') == 'Finish' and first and not is_scenic:
            # official: the battle's map marker (flag id = battle id / 10) goes away when it is first won,
            # and the team gets character EXP
            fid = bid // 10
            if p.d.row('flag', 'Flag', fid):
                rem = w.setdefault('flags_removed', [])
                if fid not in rem:
                    rem.append(fid)
                ctx.push('FlagUnLockRemoveNotice', {'status': OK, 'flagIds': [fid]})
            from game.progression import team_exp
            team_exp(ctx, _packs.system('battle', 'team_exp', {}).get('flag_battle', 337))
    H['FlagBattleStateUpdateReq'] = flag

    def area_unlock(ctx, req):
        p = ctx.p
        aid = req.get('areaId', 0)
        w = W(p, p.s['scene_id'])
        a = next((x for x in w['areas'] if x.get('areaId') == aid), None)
        if a is None:
            a = {'areaId': aid, 'areaState': 'Unlock', 'level': 1}
            w['areas'].append(a)
            term_exp = int(_packs.system('world', 'area_terminal_exp', 100) or 100)
            if term_exp > 0:
                p.add_exp(term_exp)
            p.dirty = True
        # every visit counts, so a terminal opened before the quest asked for it still completes "Access Area Terminal"
        sid = p.s['scene_id']
        Q.event(p, Q.C['AreaUlockNum'], sid, absolute=Q.areas_unlocked(p, sid))
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

    def moon_info(ctx, req):
        sid = req.get('sceneId', 0)
        r = {'status': OK, 'sceneId': sid, 'collectedMoonIds': W(ctx.p, sid)['moons']}
        # official: emotionMoons carries the scene's emotion moons (from archive + any interacted on Rozefield)
        rec = (ctx.p.s.get('records', {}).get('GetCollectMoonInfoReq') or {}).get(
            json.dumps({'sceneId': sid}, sort_keys=True, ensure_ascii=False)) or {}
        em = [dict(x) for x in rec.get('emotionMoons', [])]
        done = set(ctx.p.s.get('misc', {}).get('emotion_moons', []))
        seen_ids = {x.get('moonId') for x in em}
        for x in em:
            if x.get('moonId') in done:
                x['interacted'] = True
        for mid in sorted(done):
            if mid not in seen_ids and sid and str(mid).startswith(str(sid)):
                em.append({'moonId': mid, 'interacted': True})
        if em:
            r['emotionMoons'] = em
        ctx.reply(r)
    H['GetCollectMoonInfoReq'] = moon_info

    # ---- field drops (PickupReq): the official server rolled 3-5 pieces of gear, sometimes a material
    def pickup(ctx, req):
        p = ctx.p
        items = ctx.__dict__.setdefault('drops', {}).pop(req.get('dropItemIndex', 0), None)
        kills = 0
        if items is None:
            kills = ctx.__dict__.pop('kills_since_drop', 0)
            if not kills:
                return ctx.reply({'status': OK})
            kr_rate = p.drop_rate_info()['killDropRate']
            kmult = kr_rate / 100.0
            cutoff = p._fatigue_cfg()['kill_mat_cutoff']
            n_gear = max(1, int(round(random.randint(3, 5) * kmult)))
            items = roll_gear(p.d, n_gear, p.s.get('world_level', 1))
            if kr_rate > cutoff and random.random() < 0.3 * kmult:
                items.append((random.choice((1030, 1032, 1020, 1022, 1010, 1012, 1000, 1002)), max(1, int(round(random.randint(1, 4) * kmult)))))
            new_rates = p.record_fatigue('kills', kills)
            if new_rates['killDropRate'] != kr_rate:
                ctx.push('PlayerTiredDropNotice', {'status': OK, 'dropRateInfo': new_rates})
        got, changed = p.add_items(items)
        ctx.reply({'status': OK, 'items': got})
        pack(ctx, changed)
    H['PickupReq'] = pickup

    H['PlayerVitalityReq'] = lambda ctx, req: (__import__('game.dungeon', fromlist=['x']).vitality(ctx.p), ctx.reply({'status': OK}))
