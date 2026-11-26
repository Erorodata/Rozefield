"""The remaining client requests: purchases, temporary pack, exploration, collection rewards, social actions,
codes, Boss Rush, mini-game rewards, and plain acknowledgements.

Where the game tables hold the numbers (purchase prices, reward pools, exploration areas, pets) they are used;
otherwise the amounts are marked as estimates. Anything that needs other live players (co-op rooms, online
Gomoku, photo sharing) answers politely so the client does not hang.
"""
import json
import os
import random
import time

from game import quests as Q

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
STARSTONE, GOLD = 102, 101
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _day():
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 4 * 3600))


def _ms():
    return str(int(time.time() * 1000))


def _st(p, key, default):
    return p.s.setdefault('misc', {}).setdefault(key, default)


def rec(p, name, req=None, default=None):
    """Mutable copy of an archived info answer (state['records']), so later queries see the change."""
    k = json.dumps(req or {}, sort_keys=True, ensure_ascii=False)
    r = p.s.setdefault('records', {}).setdefault(name, {})
    if k not in r:
        r[k] = dict(default or {'status': OK})
    p.dirty = True
    return r[k]


def _daily(p, key):
    d = _st(p, 'daily', {})
    if d.get('day') != _day():
        d.clear()
        d['day'] = _day()
    d.setdefault(key, 0)
    return d


def register(H, pack):
    def give(ctx, items):
        items = [(i, n) for i, n in items if i and n > 0]
        got, changed = ctx.p.add_items(items) if items else ([], [])
        ctx.p.dirty = True
        return got, changed

    def ack(name, echo=(), extra=None):
        def f(ctx, req):
            r = {'status': OK}
            for k in echo:
                if k in req:
                    r[k] = req[k]
            if extra:
                r.update(extra(ctx, req))
            ctx.reply(r)
        H[name] = f

    # ------------------------------------------------ energy / vitality purchases (globalconfig prices)
    def buy(kind, cfg_key, item, max_key):
        def f(ctx, req):
            p, d = ctx.p, ctx.d
            prices = d.config(cfg_key) or []
            dd = _daily(p, kind)
            n = dd[kind]
            if n >= len(prices):
                return ctx.reply({'status': FAIL})
            cur, cost, amount = (int(x) for x in prices[n].split(':'))
            if kind == 'vitality':
                from game.dungeon import vitality
                vitality(p)
            paid = p.pay([(cur, cost)])
            if paid is None:
                return ctx.reply({'status': FAIL})
            dd[kind] = n + 1
            got, changed = give(ctx, [(item, amount)])
            ctx.reply({'status': OK, kind + 'BuyNum': n + 1, 'items': got})
            pack(ctx, paid + changed)
        return f
    H['PlayerEnergyBuyReq'] = buy('energy', 'Player_Energy_Buy_Times', 11, 'Player_Energy_Max_Count')
    H['PlayerVitalityBuyReq'] = buy('vitality', 'Player_Vitality_Buy_Times', 10, 'Player_Vitality_Max_Count')

    def game_coin(ctx, req):
        p, d = ctx.p, ctx.d
        cur, price, amount = (int(x) for x in (d.config('GameCoinBuy') or ['102', '5', '1']))
        n = max(1, req.get('buy_count', 1))
        paid = p.pay([(cur, price * n)])
        if paid is None:
            return ctx.reply({'status': FAIL})
        got, changed = give(ctx, [(1601, amount * n)])
        ctx.reply({'status': OK, 'itemDetails': got})
        pack(ctx, paid + changed)
    H['BuyGameCoinReq'] = game_coin

    # ------------------------------------------------ temporary pack (overflow when the bag is full)
    def tp(p):
        return _st(p, 'temp_pack', [])

    def tp_msg(p):
        return {'maxSize': 100, 'itemInfos': tp(p)}

    def tp_store(ctx, req):
        p = ctx.p
        items = [(i.get('itemId'), int((i.get('baseItem') or {}).get('num', 1) or 1)) for i in tp(p)]
        p.s['misc']['temp_pack'] = []
        got, changed = give(ctx, items)
        ctx.reply({'status': OK, 'items': got})
        pack(ctx, changed)
    H['TempPackItemStoreReq'] = tp_store

    def tp_drop(ctx, req):
        p = ctx.p
        i = req.get('index', 0)
        if 0 <= i < len(tp(p)):
            tp(p).pop(i)
        ctx.reply({'status': OK, 'tempPack': tp_msg(p)})
    H['TempPackItemDropReq'] = tp_drop
    H['TempPackSortReq'] = lambda ctx, req: ctx.reply({'status': OK, 'tempPack': tp_msg(ctx.p)})
    H['TempPackWearEquipReq'] = lambda ctx, req: ctx.reply({'status': OK, 'tempPack': tp_msg(ctx.p)})

    # ------------------------------------------------ exploration (send a team out; explore.json)
    def ex_list(p):
        return rec(p, 'ExploreInitReq', {}, {'status': OK, 'explore': []}).setdefault('explore', [])

    def ex_get(p, eid):
        for e in ex_list(p):
            if e.get('exploreId') == eid:
                return e
        e = {'exploreId': eid}
        ex_list(p).append(e)
        return e

    def ex_cfg(d, eid):
        return d.row('explore', 'ExploreArea', eid) or d.row('explore', 'ExploreActivity', eid)

    def ex_done(d, e):
        cfg = ex_cfg(d, e['exploreId']) or {}
        return e.get('isQuickFinish') or (e.get('startTime') and time.time() * 1000 - int(e['startTime']) >= cfg.get('NeedTime', 600) * 1000)

    def ex_start(ctx, req):
        p, d = ctx.p, ctx.d
        eid = req.get('exploreId')
        cfg = ex_cfg(d, eid)
        if not cfg:
            return ctx.reply({'status': FAIL})
        paid = []
        if cfg.get('NeedItem') and p.count(cfg['NeedItem']) <= 0:
            return ctx.reply({'status': FAIL})
        e = ex_get(p, eid)
        e.update(startTime=_ms(), isQuickFinish=False, collectReward=False, times=e.get('times', 0) + 1)
        ctx.reply({'status': OK, 'isActivity': req.get('isActivity', False), 'explore': e})
        pack(ctx, paid)
    H['ExploreReq'] = ex_start

    def ex_quick(ctx, req):
        p, d = ctx.p, ctx.d
        cfg = ex_cfg(d, req.get('exploreId')) or {}
        paid = p.pay([(cfg.get('QuickNeedItem', STARSTONE), cfg.get('QuickNeedItemCount', 1))])
        if paid is None:
            return ctx.reply({'status': FAIL})
        e = ex_get(p, req.get('exploreId'))
        e['isQuickFinish'] = True
        ctx.reply({'status': OK, 'isActivity': req.get('isActivity', False), 'explore': e})
        pack(ctx, paid)
    H['ExploreQuickFinishReq'] = ex_quick

    def ex_cancel(ctx, req):
        e = ex_get(ctx.p, req.get('exploreId'))
        for k in ('startTime', 'isQuickFinish'):
            e.pop(k, None)
        ctx.reply({'status': OK, 'exploreId': req.get('exploreId'), 'isActivity': req.get('isActivity', False), 'explore': e})
    H['ExploreCancelReq'] = ex_cancel

    def ex_reward(ctx, req):
        """Rewards are the area's listed items; amounts are estimates (gold 2000-5000, others 1-5)."""
        p, d = ctx.p, ctx.d
        eid = req.get('exploreId')
        e = ex_get(p, eid)
        if not ex_done(d, e):
            return ctx.reply({'status': FAIL})
        cfg = ex_cfg(d, eid) or {}
        hours = max(1, cfg.get('NeedTime', 600) // 3600)
        items = []
        for it in cfg.get('ExploreAreaItem', []) + cfg.get('ExploreActivityItem', []):
            i = it.get('RewarItemID') or it.get('RewardItemID')
            items.append((i, random.randint(2000, 5000) * hours if i == GOLD else random.randint(1, 3) * hours))
        e['collectItemId'] = [i for i, _ in items]
        for k in ('startTime', 'isQuickFinish'):
            e.pop(k, None)
        e['collectReward'] = True
        got, changed = give(ctx, items)
        Q.event(p, Q.C.get('Explore', 0) or 0) if Q.C.get('Explore') else None
        ctx.reply({'status': OK, 'isActivity': req.get('isActivity', False), 'exploreId': eid, 'explore': e, 'rewardItem': got})
        pack(ctx, changed)
    H['ExploreRewardReq'] = ex_reward
    H['ExploreCollectRewardReq'] = ex_reward

    # ------------------------------------------------ interval (team exploration with friends, solo here)
    # rifts (IntervalStart / Quick / Join / Reward): game/extras.py

    # ------------------------------------------------ handbook / collection rewards
    def reward_pool(ctx, pool):
        return ctx.d.reward_items(pool, ctx.p.s.get('level', 1)) if pool else []

    def manual_flag(ctx, flag_id):
        for m in ctx.d.table('manual', 'Manual').values():
            for it in m.get('ManualItems', []):
                if it.get('FlagID') == flag_id:
                    return it
        for m in ctx.d.table('manual', 'ManualDungeon').values():
            for it in m.get('ManualDungeonItems', []):
                if it.get('FlagID') == flag_id:
                    return it
        return None

    def mf_entry(p, fid):
        flags = rec(p, 'ManualListReq', {}, {'status': OK, 'flags': []}).setdefault('flags', [])
        e = next((f for f in flags if f.get('flagId') == fid), None)
        if not e:
            e = {'flagId': fid, 'status': 'Lock', 'dungeonTaskFinishNum': 0}
            flags.append(e)
        return e

    def mf_unlock(ctx, req):
        p = ctx.p
        fid = req.get('flagId')
        e = mf_entry(p, fid)
        if e.get('status') in ('UnLock', 'Unlock', 'Reward'):
            return ctx.reply({'status': OK, 'flag': e})
        e['status'] = 'UnLock'
        ctx.reply({'status': OK, 'flag': e})
    H['ManualFlagUnlockReq'] = mf_unlock

    def mf_reward(ctx, req):
        p = ctx.p
        fid = req.get('flagId')
        e = mf_entry(p, fid)
        if e.get('status') == 'Reward':
            return ctx.reply({'status': FAIL})
        cfg = manual_flag(ctx, fid) or {}
        e['status'] = 'Reward'
        got, changed = give(ctx, reward_pool(ctx, cfg.get('RewardID') or cfg.get('UnLockRewardID')))
        ctx.reply({'status': OK, 'flag': e, 'items': got})
        pack(ctx, changed)
    H['ManualFlagRewardReq'] = mf_reward

    def poster_ill(ctx, req):
        p = ctx.p
        pid = req.get('posterIllustrationId')
        lst = rec(p, 'PosterIllustrationListReq', {}, {'status': OK, 'posterIllustrations': []}).setdefault('posterIllustrations', [])
        e = next((x for x in lst if x.get('posterIllustrationId') == pid), None)
        if e and e.get('status') == 'Reward':
            return ctx.reply({'status': FAIL})
        if not e:
            e = {'posterIllustrationId': pid}
            lst.append(e)
        e['status'] = 'Reward'
        got, changed = give(ctx, [(STARSTONE, 10)])   # official: 10 Starstones (2026-11-26 capture)
        ctx.reply({'status': OK, 'posterIllustration': e, 'items': got})
        pack(ctx, changed)
    H['PosterIllustrationRewardReq'] = poster_ill

    def treasure_achieve(ctx, req):
        p, d = ctx.p, ctx.d
        aid = req.get('achieve_id')
        done = _st(p, 'treasure_achieve', [])
        pool = None
        for r in d.table('archaeologyachieve', 'ArchaeologyAchieve').values():
            for it in r.get('Items', []):
                if it.get('AchieveID') == aid:
                    pool = it.get('RewardID')
        if aid in done or pool is None:
            return ctx.reply({'status': FAIL})
        done.append(aid)
        got, changed = give(ctx, reward_pool(ctx, pool))
        ctx.reply({'status': OK, 'items': got, 'rewarded_achieve_ids': done})
        pack(ctx, changed)
    H['GetTreasureAchieveRewardReq'] = treasure_achieve

    def treasure_ill(ctx, req):
        p = ctx.p
        key = '%s:%s' % (req.get('archaeology_type'), req.get('id'))
        done = _st(p, 'treasure_ill', [])
        if key in done:
            return ctx.reply({'status': FAIL})
        done.append(key)
        got, changed = give(ctx, [(STARSTONE, 20)])   # estimate
        ctx.reply({'status': OK, 'archaeology_type': req.get('archaeology_type'), 'id': req.get('id'), 'rewards': got})
        pack(ctx, changed)
    H['TreasureIllustrationRewardReq'] = treasure_ill

    def badge_page(p, page):
        pages = rec(p, 'AbilityBadgeListReq', {}, {'status': OK, 'abilityBadgePages': []}).setdefault('abilityBadgePages', [])
        e = next((x for x in pages if x.get('page') == page), None)
        if not e:
            e = {'page': page, 'activeBoxIds': []}
            pages.append(e)
        return e

    def badge_box(ctx, req):
        """Astral Atlas: activate one box of a page (moonstone.StoneUnlockData, page = its ID).
        Costs the box's ItemID x ItemCount; pays packs/*/systems/atlas.json box_rewards (official ones known
        from play), else the old Gold estimate."""
        p = ctx.p
        page, b = req.get('page'), req.get('boxId')
        e = badge_page(p, page)
        if b in e.setdefault('activeBoxIds', []):
            return ctx.reply({'status': FAIL})   # official: AbilityBadgeBoxAlreadyActive
        row = p.d.row('moonstone', 'StoneUnlockData', page) or {}
        box = next((x for x in row.get('StoneUnlockDataGroupInfo', []) if x.get('BoxID') == b), None)
        cost = (box or {}).get('ItemID'), (box or {}).get('ItemCount', 0)
        if cost[0] and cost[1]:
            spent = p.remove_item(cost[0], cost[1])
            if spent is None:
                return ctx.reply({'status': FAIL})
            pack(ctx, spent)
        e['activeBoxIds'].append(b)
        from game import packs
        rw = (packs.system('atlas', 'box_rewards', {}) or {}).get(f'{page}:{b}')
        pay = [tuple(x) for x in rw] if rw else [(GOLD, 2000)]   # estimate for boxes not known yet
        got, changed = give(ctx, pay)
        ctx.reply({'status': OK, 'page': page, 'boxId': b, 'items': got})
        pack(ctx, changed)
    H['AbilityBadgePageBoxActiveReq'] = badge_box

    def badge_page_reward(ctx, req):
        e = badge_page(ctx.p, req.get('page'))
        if e.get('isReward'):
            return ctx.reply({'status': FAIL})
        e['isReward'] = True
        got, changed = give(ctx, [(STARSTONE, 50)])   # estimate
        ctx.reply({'status': OK, 'page': req.get('page'), 'items': got})
        pack(ctx, changed)
    H['AbilityBadgePageRewardReq'] = badge_page_reward

    def badge_achieve(ctx, req):
        done = _st(ctx.p, 'badge_achieve', [])
        ids = [a for a in req.get('achieveIds', []) if a not in done]
        done += ids
        # official: 1 moonstone of the achievement's map per achievement (2 ids -> 301 x2, 3 ids -> 301 x3)
        pay = {}
        for a in ids:
            page = int(str(a)[3:5]) if str(a).startswith('501') and len(str(a)) == 8 else 1
            stone = (ctx.d.row('moonstone', 'StoneAreaData', page) or {}).get('ItemID', 301)
            pay[stone] = pay.get(stone, 0) + 1
        got, changed = give(ctx, list(pay.items()))
        ctx.reply({'status': OK, 'achieveIds': ids, 'items': got})
        pack(ctx, changed)
    H['AbilityBadgeAchieveRewardReq'] = badge_achieve

    def ability_up(ctx, req):
        p = ctx.p
        lst = rec(p, 'PlayerAbilityListReq', {}, {'status': OK, 'abilityList': []}).setdefault('abilityList', [])
        aid = req.get('abilityId')
        e = next((x for x in lst if x.get('abilityId') == aid), None)
        if not e:
            e = {'abilityId': aid, 'level': 0}
            lst.append(e)
        if e.get('level', 0) >= 5:
            return ctx.reply({'status': FAIL})
        e['level'] = e.get('level', 0) + 1
        ctx.reply({'status': OK, 'ability': e, 'items': []})
    H['PlayerAbilityLevelUpReq'] = ability_up

    def char_achieve_award(ctx, req):
        p, d = ctx.p, ctx.d
        cid, idx = req.get('characterId'), req.get('rewardIndex')
        cfg = d.row('character', 'CharacterAchieveReward', (d.row('character', 'Character', cid) or {}).get('AchieveRewardID', cid)) or {}
        row = next((x for x in cfg.get('AchieveRewardInfo', []) if x.get('Num') == idx or x.get('UIIndex') == idx), None)
        done = _st(p, 'char_achieve', {}).setdefault(str(cid), [])
        if not row or idx in done:
            return ctx.reply({'status': FAIL})
        done.append(idx)
        got, changed = give(ctx, [(row.get('RewardItemID'), row.get('RewardItemCount', 1))])
        ctx.reply({'status': OK, 'items': got, 'rewardedIndexLst': done, 'characterId': cid})
        pack(ctx, changed)
    H['GetCharacterAchievementAwardReq'] = char_achieve_award

    def char_badge_award(ctx, req):
        p, d = ctx.p, ctx.d
        cid, aid = req.get('characterId'), req.get('achievementId')
        cfg = d.row('character', 'CharacterAchieve', (d.row('character', 'Character', cid) or {}).get('CharacterAchieveID', cid)) or {}
        row = next((x for x in cfg.get('AchieveInfo', []) if x.get('AchieveID') == aid), None)
        done = _st(p, 'char_badge', {}).setdefault(str(cid), [])
        if not row or aid in done:
            return ctx.reply({'status': FAIL})
        done.append(aid)
        got, changed = give(ctx, [(row.get('ItemID'), row.get('ItemCount', 1))])
        ctx.reply({'status': OK, 'updateItems': got, 'achieves': [], 'rewardedAchievementIdLst': done})
        pack(ctx, changed)
    H['GetCharacterAchievementBadgeAwardReq'] = char_badge_award
    H['GetCharacterAchievementUnlockPaymentReq'] = lambda ctx, req: ctx.reply(
        {'status': OK, 'updateItem': [], 'isUnlock': True, 'characterId': req.get('characterId')})

    def dungeon_bonus(kind):
        def f(ctx, req):
            p = ctx.p
            did = req.get('dungeon_id')
            done = _st(p, kind, [])
            if did in done:
                return ctx.reply({'status': FAIL})
            done.append(did)
            got, changed = give(ctx, [(STARSTONE, 20), (GOLD, 2000)] if kind == 'dungeon_star' else [(STARSTONE, 10)])   # estimate
            ctx.reply({'status': OK, 'rewards': got})
            pack(ctx, changed)
        return f
    H['DungeonStarRewardReq'] = dungeon_bonus('dungeon_star')
    H['DungeonTaskFinishRewardReq'] = dungeon_bonus('dungeon_task')

    def area_entry(p, aid):
        return _st(p, 'area_levels', {}).setdefault(str(aid), {'areaId': aid, 'areaState': 'AreaState_Unlock', 'level': 1})

    def area_up(ctx, req):
        e = area_entry(ctx.p, req.get('areaId'))
        e['level'] = e.get('level', 1) + 1
        got, changed = give(ctx, [(STARSTONE, 20)])   # estimate
        ctx.reply({'status': OK, 'area': e, 'items': got, 'achieves': []})
        pack(ctx, changed)
    H['AreaLevelUpReq'] = area_up
    H['AreaCloseReq'] = lambda ctx, req: ctx.reply({'status': OK, 'area': area_entry(ctx.p, req.get('areaId'))})
    def area_achieves(ctx, req):
        """Exploration of one area (Global Search "Exploration n/4"): the official answer from the backup"""
        k = json.dumps({'areaId': req.get('areaId')}, sort_keys=True, ensure_ascii=False)
        off = (ctx.p.s.get('official_answers', {}).get('AreaAchieveListReq') or {}).get(k)
        if off and off.get('status') == OK:
            return ctx.reply(off)
        ctx.reply({'status': OK, 'areaId': req.get('areaId'), 'achieves': []})
    H['AreaAchieveListReq'] = area_achieves

    _ctype = {}

    def collecting(ctx, req):
        """Field collectibles (crystals, files, tapes...). Remembered per scene so the pickup stays collected,
        and added to the handbook list (GetCollectItemIds)."""
        from game.world import W
        p = ctx.p
        iid = req.get('itemId')
        if not _ctype:
            for r in ctx.d.table('collectionitem', 'CollectionItem').values():
                _ctype[r['ID']] = r.get('NewCollectionType', 0)
        ctype = _ctype.get(iid, 0)
        w = W(p, p.s.get('scene_id', 0))
        entry = next((c for c in w['collections'] if c.get('type', 0) == ctype), None)
        if entry is None:
            entry = {'type': ctype, 'itemMap': {}} if ctype else {'itemMap': {}}
            w['collections'].append(entry)
        first = str(iid) not in entry['itemMap'] and iid not in entry['itemMap']
        entry['itemMap'][str(iid)] = {'itemId': iid}
        ids = rec(p, 'GetCollectItemIdsReq').setdefault('itemIds', [])
        if iid not in ids:
            ids.append(iid)
        got, changed = give(ctx, [(iid, 1)]) if first and ctx.d.item(iid) else ([], [])
        p.dirty = True
        ctx.reply({'status': OK, 'collections': [{'type': ctype, 'itemMap': {iid: {'itemId': iid}}}], 'items': got})
        pack(ctx, changed)
    H['CollectingReq'] = collecting

    def collection_reward(ctx, req):
        p = ctx.p
        iid = req.get('itemId')
        done = _st(p, 'collection_reward', [])
        if iid in done:
            return ctx.reply({'status': FAIL})
        done.append(iid)
        cfg = ctx.d.row('collectionitem', 'CollectItemPhotoItem', iid) or {}
        got, changed = give(ctx, reward_pool(ctx, cfg.get('RewardID')) or [(STARSTONE, 10)])
        ctx.reply({'status': OK, 'collectionRewardData': {'itemId': iid, 'status': 'Reward'}, 'items': got})
        pack(ctx, changed)
    H['CollectionRewardReq'] = collection_reward

    # ------------------------------------------------ field extras
    def coin(ctx, req):
        """Yellow Stars (item 106), 1 each (official). Kept per dungeon (its coins list) or per map."""
        p = ctx.p
        i = req.get('coinIndex', 0)
        did = ctx.__dict__.get('dungeon_id')
        if did:
            from game.dungeon import dstate
            done = dstate(p, did).setdefault('coins', [])
        else:
            done = _st(p, 'coins_by_scene', {}).setdefault(str(p.s.get('scene_id')), [])
        if i in done:
            return ctx.reply({'status': FAIL})
        done.append(i)
        got, changed = give(ctx, [(106, 1)])
        ctx.reply({'status': OK, 'coinIndex': i, 'rewards': got})
        pack(ctx, changed)
    H['CollectCoinReq'] = coin

    def dig(ctx, req):
        p, d = ctx.p, ctx.d
        shovel = next(iter(d.table('shovel', 'Shovel').values()), {})
        ok = random.randint(1, 1000) <= shovel.get('SuccessRate', 500)
        got, changed = give(ctx, [(GOLD, random.randint(500, 1500)), (STARSTONE, random.randint(5, 15))]) if ok else ([], [])   # estimate
        ctx.reply({'status': OK, 'treasure_id': req.get('treasure_id'), 'rewards': got, 'success': ok})
        pack(ctx, changed)
    H['TreasureDigReq'] = dig

    def supply(ctx, req):
        p, d = ctx.p, ctx.d
        info = rec(p, 'SupplyBoxInfoReq', {}, {'status': OK, 'nextRewardTime': '0'})
        if int(info.get('nextRewardTime', 0) or 0) > time.time():
            return ctx.reply({'status': FAIL})
        lo, hi = (int(x) for x in (d.config('SupplyBox_Random_Time') or ['10', '30']))
        info['nextRewardTime'] = str(int(time.time()) + random.randint(lo, hi) * 60)
        got, changed = give(ctx, [(STARSTONE, 1), (109, 40), (GOLD, 90)])   # official (2026-11-26 capture)
        ctx.reply({'status': OK, 'nextRewardTime': info['nextRewardTime'], 'items': got})
        pack(ctx, changed)
    H['SupplyBoxRewardReq'] = supply

    def campfire(ctx, req):
        st = _st(ctx.p, 'campfires', {})
        cid = int(time.time()) % 1000000
        fire = {'pos': req.get('pos', {}), 'rot': req.get('rot', {}), 'id': cid, 'playerId': ctx.p.s['player_id'],
                'placeTime': str(int(time.time())), 'actionId': req.get('actionId', 0)}
        st[str(cid)] = fire
        ctx.reply({'status': OK, 'campFire': fire})
    H['PlaceCampFireReq'] = campfire

    def campfire_rm(ctx, req):
        _st(ctx.p, 'campfires', {}).pop(str(req.get('campFireId')), None)
        ctx.reply({'status': OK})
    H['RemoveCampFireReq'] = campfire_rm

    def emotion_moon(ctx, req):
        done = _st(ctx.p, 'emotion_moons', [])
        mid = req.get('emotionMoonId')
        if mid not in done:
            done.append(mid)
        ctx.reply({'status': OK, 'info': {'moonId': mid, 'interacted': True}})
    H['EmotionMoonInteractReq'] = emotion_moon
    ack('PlayMusicNoteReq', ('music_note_id',), lambda ctx, req: {'player_id': ctx.p.s['player_id'], 'start_time': _ms()})
    ack('CollapseFailReq')

    def action_study(ctx, req):
        acts = _st(ctx.p, 'learned_actions', [])
        if req.get('actionId') not in acts:
            acts.append(req.get('actionId'))
        ctx.reply({'status': OK})
    H['ActionStudyReq'] = action_study

    # ------------------------------------------------ bag tools
    def lock_equip(ctx, req):
        p = ctx.p
        iid = str(req.get('instanceId'))
        for key in ('weapons', 'armors', 'posters'):
            inst = p.s.get(key, {}).get(iid)
            if inst is not None:
                inst['isLock'] = not inst.get('isLock', False)
                p.dirty = True
        ctx.reply({'status': OK})
    H['LockEquipReq'] = lock_equip

    def pet_decompose(ctx, req):
        p, d = ctx.p, ctx.d
        items = []
        for iid in req.get('pet_instance_ids', []):
            pet = p.s.get('pets', {}).pop(str(iid), None)
            if not pet:
                continue
            cfg = d.row('pet', 'Pet', pet.get('itemId')) or {}
            for rid in cfg.get('ReleaseReward', [])[:1]:
                rr = d.row('pet', 'ReleaseReward', rid) or {}
                lv = min(max(1, pet.get('level', 1)), len(rr.get('ReleaseRewardItem', [])) or 1)
                row = (rr.get('ReleaseRewardItem') or [{}])[lv - 1]
                items.append((row.get('ReleaseRewardID'), row.get('ReleaseRewardCount', 1)))
        got, changed = give(ctx, items)
        ctx.reply({'status': OK, 'pet_instance_ids': req.get('pet_instance_ids', []), 'items': got})
        pack(ctx, changed)
    H['PetDecomposeReq'] = pet_decompose

    def item_sweep(ctx, req):
        """Use several openable items at once: gift bags expand their reward pool."""
        p, d = ctx.p, ctx.d
        item, n = req.get('item_id'), max(1, req.get('count', 1))
        bag = d.row('giftbag', 'GiftBag', item)
        if not bag or p.count(item) < n:
            return ctx.reply({'status': FAIL})
        paid = p.pay([(item, n)])
        items = []
        for _ in range(n):
            for g in bag.get('GiftBagGroup', []):
                items += reward_pool(ctx, g.get('RewardPoolGroupID'))
        got, changed = give(ctx, items)
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, paid + changed)
    H['ItemSweepReq'] = item_sweep

    def dye_unlock(ctx, req):
        st = _st(ctx.p, 'dye_slots', {}).setdefault(str(req.get('outfitId')), [])
        if req.get('index') not in st:
            st.append(req.get('index'))
        ctx.reply({'status': OK})
    H['OutfitDyeUnlockIndexReq'] = dye_unlock

    def random_color(ctx, req):
        ctx.reply({'status': OK, 'outfitId': req.get('outfitId'),
                   'posColor': {'pos': 1, 'red': random.randint(0, 255), 'green': random.randint(0, 255), 'blue': random.randint(0, 255)}})
    H['OutfitRandomColorReq'] = random_color

    # ------------------------------------------------ codes (save/codes.json: {"CODE": [[item, n], ...]})
    def code_use(field_out):
        def f(ctx, req):
            p = ctx.p
            code = (req.get('code') or '').strip().upper()
            path = os.path.join(HERE, 'save', 'codes.json')
            codes = {}
            if os.path.exists(path):
                codes = {k.upper(): v for k, v in json.load(open(path, encoding='utf-8')).items()}
            used = _st(p, 'codes_used', [])
            if code not in codes or code in used:
                return ctx.reply({'status': FAIL})
            used.append(code)
            got, changed = give(ctx, [tuple(x) for x in codes[code]])
            r = {'status': OK, 'rewards': got}
            if field_out:
                r[field_out] = req.get('code')
            ctx.reply(r)
            pack(ctx, changed)
        return f
    H['UseRedemptionCodeReq'] = code_use('code')
    H['InviteCodeUseReq'] = code_use(None)
    H['RecallCodeUseReq'] = code_use(None)
    H['InheritCodeUseReq'] = code_use('codeStr')

    # ------------------------------------------------ social
    def likes(ctx, req):
        p, d = ctx.p, ctx.d
        dd = _daily(p, 'likes')
        cap = d.config_int('HomeLikesNum', 10)
        if dd['likes'] >= cap:
            return ctx.reply({'status': FAIL, 'leftLikeNums': 0})
        owner = ctx.server.player_by_id(p.s.get('channel_id')) if p.s.get('scene_id') == 9999 else None
        if owner is None or owner is p:          # likes go to someone else's garden
            return ctx.reply({'status': FAIL, 'leftLikeNums': cap - dd['likes']})
        dd['likes'] += 1
        owner.s['garden']['likes'] = owner.s['garden'].get('likes', 0) + 1
        owner.dirty = True
        Q.event(p, Q.C['GardenLike'])
        ctx.reply({'status': OK, 'leftLikeNums': cap - dd['likes'], 'likeNums': str(owner.s['garden']['likes'])})
    H['DoLikesReq'] = likes
    H['GardenLikeRecordReq'] = lambda ctx, req: ctx.reply({'status': OK, 'record': []})
    H['PrivateChatMsgRecordReq'] = lambda ctx, req: ctx.reply({'status': OK, 'msgRecord': _st(ctx.p, 'private_chat', {}).get(str(req.get('targetPlayerId')), [])})
    ack('ChangeChatChannelReq', ('channel_id',))
    ack('SetFriendExtInfoReq', ('playerId', 'data'))

    def hide_type(ctx, req):
        v = {'HideType_None': 0}.get(req.get('hide_type'), 1)
        ctx.p.s['hide_value'] = v
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'hide_value': v})
    H['ChangeHideTypeReq'] = hide_type

    # ------------------------------------------------ recruit options
    def gstate(p, gid):
        return p.s['gacha'].setdefault(str(gid), {'times': 0, 'since_ssr': 0, 'lost5050': False, 'records': []})

    def choose_gacha(ctx, req):
        gstate(ctx.p, req.get('gacha_id'))['choose_pool'] = req.get('choose_gacha_pool')
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'choose_gacha_pool': req.get('choose_gacha_pool'), 'gacha_id': req.get('gacha_id')})
    H['ChooseGachaReq'] = choose_gacha

    def optional_up(ctx, req):
        st = gstate(ctx.p, req.get('gacha_id'))
        st['optional_up'] = req.get('item_id')
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'info': {'gachaId': req.get('gacha_id'), 'gachaTimes': st['times'], 'optionalUpItem': req.get('item_id'),
                                          'guarantee': 70 - st['since_ssr']}})
    H['OptionalUpPoolItemReq'] = optional_up

    def full_pick(ctx, req):
        """Spark: after enough pulls on a banner, pick the featured item once."""
        p = ctx.p
        st = gstate(p, req.get('gachaId'))
        if st.get('full_picked') or st['times'] < 140:
            return ctx.reply({'status': FAIL})
        st['full_picked'] = True
        got, changed = give(ctx, [(req.get('itemId'), 1)])
        ctx.reply({'status': OK, 'item': got})
        pack(ctx, changed)
    H['GachaFullPickReq'] = full_pick

    # ------------------------------------------------ Boss Rush (bossrush.json)
    def br_season(d, sid):
        return d.row('bossrush', 'BossRushSeason', sid) or next(iter(d.table('bossrush', 'BossRushSeason').values()), {})

    def br(p, sid):
        return _st(p, 'bossrush', {}).setdefault(str(sid), {'stages': {}, 'best': 0})

    def br_start(ctx, req):
        sid, si = req.get('season_id'), req.get('stage_index', 0)
        st = br(ctx.p, sid)
        st['current'] = si
        s = st['stages'].setdefault(str(si), {'stage_index': si, 'best_score': '0', 'is_passed': False})
        ctx.reply({'status': OK, 'season_id': sid, 'stage_info': s})
    H['BossRushStartChallengeReq'] = br_start

    def br_enter(ctx, req):
        sid = req.get('season_id')
        st = br(ctx.p, sid)
        si = st.get('current', 0)
        ctx.reply({'status': OK, 'season_id': sid, 'battle_info': {'stage_index': si, 'trigger_id': 1, 'monsters': []}})
    H['BossRushEnterStageReq'] = br_enter

    def br_battle(ctx, req):
        sid = req.get('season_id')
        st = br(ctx.p, sid)
        st['battle_start'] = int(time.time())
        ctx.reply({'status': OK, 'season_id': sid, 'stage_index': st.get('current', 0), 'battle_start_time': str(st['battle_start'])})
    H['BossRushStartBattleReq'] = br_battle

    def br_leave(ctx, req):
        sid = req.get('season_id')
        st = br(ctx.p, sid)
        si = st.get('current', 0)
        s = st['stages'].setdefault(str(si), {'stage_index': si, 'best_score': '0'})
        dmg = int(req.get('total_damage_hp', 0) or 0)
        if dmg > int(s.get('best_score', 0)):
            s['best_score'] = str(dmg)
        if req.get('win'):
            s['is_passed'] = True
        total = sum(int(x.get('best_score', 0)) for x in st['stages'].values())
        st['best'] = max(st['best'], total)
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'stage_best_score': s['best_score'], 'best_total_score': str(st['best']), 'total_rank_ratio': 1})
    H['BossRushLeaveStageReq'] = br_leave
    H['BossRushTerminateChallengeReq'] = lambda ctx, req: ctx.reply({'status': OK, 'season_id': req.get('season_id')})
    H['BossRushFriendRankReq'] = lambda ctx, req: ctx.reply({'status': OK, 'season_id': req.get('season_id'), 'rank_info': []})
    H['BossRushFriendDetailReq'] = lambda ctx, req: ctx.reply({'status': OK, 'player_id': req.get('player_id'), 'details': []})

    def br_quest(ctx, req):
        p, d = ctx.p, ctx.d
        sid, aid = req.get('season_id'), req.get('achieve_id')
        cfg = d.row('bossrush', 'BossRushAchieve', br_season(d, sid).get('SeasonAchieve')) or {}
        row = next((x for x in cfg.get('BossRushAchieveGroupInfo', []) if x.get('AchieveID') == aid), None)
        done = br(p, sid).setdefault('quests', [])
        if not row or aid in done:
            return ctx.reply({'status': FAIL})
        done.append(aid)
        got, changed = give(ctx, reward_pool(ctx, row.get('RewardID')))
        ctx.reply({'status': OK, 'season_id': sid, 'achieve_id': aid, 'rewards': got})
        pack(ctx, changed)
    H['BossRushQuestRewardReq'] = br_quest

    def abyss_quest(ctx, req):
        p, d = ctx.p, ctx.d
        sid, cid = req.get('seasonId'), req.get('conditionId')
        season = d.row('abyss', 'AbyssSeason', sid) or {}
        cfg = d.row('abyss', 'SeasonAchieve', season.get('SeasonAchieve')) or {}
        row = next((x for x in cfg.get('SeasonAchieveGroupInfo', []) if x.get('AchieveID') == cid), None)
        done = _st(p, 'abyss_quests', {}).setdefault(str(sid), [])
        if not row or cid in done:
            return ctx.reply({'status': FAIL})
        done.append(cid)
        got, changed = give(ctx, reward_pool(ctx, row.get('RewardID')))
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, changed)
    H['AbyssQuestRewardReq'] = abyss_quest
    H['AbyssFriendRankReq'] = lambda ctx, req: ctx.reply({'status': OK, 'rankList': []})
    H['AbyssAllServerRankReq'] = lambda ctx, req: ctx.reply({'status': OK, 'rankList': []})

    # ------------------------------------------------ mini-games (solo parts)
    def gomoku(ctx, req):
        win = req.get('self') and _gomoku_winner(req.get('board', []), req.get('lastRow', 0), req.get('lastCol', 0)) == req.get('self')
        got, changed = give(ctx, [(GOLD, 300)] if win else [(GOLD, 50)])   # estimate
        ctx.reply({'status': OK, 'items': got, 'extraRewards': [], 'isSelfWin': bool(win)})
        pack(ctx, changed)
    H['GomokuSinglePlayerRewardReq'] = gomoku

    def play_reward(ctx, req):
        got, changed = give(ctx, reward_pool(ctx, req.get('rewardId')) * max(1, req.get('num', 1)))
        ctx.reply({'status': OK, 'items': got})
        pack(ctx, changed)
    H['GamePlayRewardReq'] = play_reward

    # ------------------------------------------------ activities without their own system yet
    def act_reward(name, echo):
        def f(ctx, req):
            key = '%s:%s' % (name, json.dumps(req, sort_keys=True))
            done = _st(ctx.p, 'activity_claims', [])
            if key in done:
                return ctx.reply({'status': FAIL})
            done.append(key)
            got, changed = give(ctx, [(STARSTONE, 20)])   # estimate
            r = {'status': OK, 'rewards': got}
            for k in echo:
                if k in req:
                    r[k] = req[k]
            ctx.reply(r)
            pack(ctx, changed)
        H[name] = f
    act_reward('ActivityGiftRewardReq', ())

    def act_quest(ctx, req):
        """7-day event quests (official, 2026-11-26 capture): param = the day; each claim pays the next finished,
        unclaimed quest of that day (its items + event points 6001). isProgress: the points track reward at index param."""
        from game.progression import astate
        p, d = ctx.p, ctx.d
        aid = req.get('activityId', 0)
        act = d.row('activityquest', 'ActivityQuest', aid) or {}
        done = _st(p, 'activity_quest_claims', {}).setdefault(str(aid), [])
        day = int(req.get('param', 0) or 0)
        if req.get('isProgress'):
            row = next((x for x in (d.row('activityquest', 'ActivityQuestReward', act.get('ActivityQuestRewardID', aid)) or {})
                        .get('ActivityQuestRewardItem', []) if x.get('Index') == day), None)
            key = 'track:%d' % day
            if not row or key in done or p.count(row.get('ConditionItemID', 6001)) < row.get('ConditionItemNum', 0):
                return ctx.reply({'status': FAIL})
            pay = [(row['RewardItemID'], row.get('RewardItemNum', 1))]
        else:
            cnt = astate(p)['count']
            ach = d.table('achieve', 'Achieve')
            it = next((x for x in act.get('ActivityQuestAchieveItems', []) if x.get('Days') == day
                       and str(x['AchieveID']) not in done
                       and cnt.get(str(x['AchieveID']), 0) >= int((ach.get(x['AchieveID']) or {}).get('CountParam', 1) or 1)), None)
            if not it:
                return ctx.reply({'status': FAIL})
            key = str(it['AchieveID'])
            pay = [(y['ItemID'], y['ItemNum']) for y in it.get('ActivityQuestItem', [])]
        done.append(key)
        got, changed = give(ctx, pay)
        r = {'status': OK, 'param': req.get('param', 0), 'rewardId': len(done), 'rewards': got}
        if req.get('isProgress'):
            r['isProgress'] = True
        ctx.reply(r)
        pack(ctx, changed)
    H['ActivityQuestRewardReq'] = act_quest
    act_reward('ActivityRegularRewardReq', ('param', 'poolType'))
    act_reward('ActivityInviteRewardClaimReq', ('activity_id', 'condition_id'))
    act_reward('ActivityRecallRewardClaimReq', ('activity_id', 'condition_id'))
    act_reward('ActivitySandbagRewardReq', ('activity_id', 'seq_list'))
    ack('ActivityKoiUseItemReq', ('num', 'activity_id'), lambda ctx, req: {'codes': []})
    H['MonthCardRewardReq'] = lambda ctx, req: ctx.reply({'status': FAIL})

    # ------------------------------------------------ plain acknowledgements / features needing other players
    for n, echo in (('ClientLogAuthReq', ()), ('ClientLogMessageReq', ()), ('ReportReq', ()), ('UnfreezePlayerActionReq', ()),
                    ('UploadFGBytesReq', ()), ('PhotoSharePaymentAddUploadGridReq', ()),
                    ('PhotoShareCopyFashionDyeReq', ()), ('OperatePhotoShareReq', ('code',)), ('GenericSceneAReq', ('generic_msg_id', 'params', 'param_map')),
                    ('ChangePhotoShareTitleReq', ('title', 'tag1', 'tag2')), ('MPPlayRoomEventReq', ()), ('MPPlayRoomReadyReq', ()),
                    ('MPBeaconPlayerReadyReq', ()), ('GomokuOnlinePlayerLeaveReq', ()), ('GomokuOnlinePlayerWatchReq', ()),
                    ('MPTeamDismissReq', ()), ('MPTeamInviteReq', ()), ('UploadExpressAddressReq', ('items',))):
        ack(n, echo)
    H['AccountNameBindingCancelReq'] = lambda ctx, req: ctx.reply({'status': OK, 'playerId': ctx.p.s['player_id']})
    # Settings -> "Exit game?" -> Yes: the client asks to go offline and uses the reply's reason as its close reason.
    # LOGOUT (6) makes it return to the login screen (no reason = "Reconnect to the server?" and the same account).
    H['PlayerOfflineReq'] = lambda ctx, req: ctx.reply({'status': OK, 'reason': 'PlayerOfflineReason_LOGOUT'})
    H['SPOperateReq'] = lambda ctx, req: ctx.reply({'status': OK, 'operateType': req.get('operateType'), 'sp_open_status': False, 'sp_check_status': False})
    H['GetExpressAddressReq'] = lambda ctx, req: ctx.reply({'status': OK})
    H['PhotoShareSearchReq'] = lambda ctx, req: ctx.reply({'status': OK, 'photos': [], 'totalNum': 0, 'todayUploadLimit': 0, 'uploadMaxNum': 0})
    H['PhotoShareDetailReq'] = lambda ctx, req: ctx.reply({'status': FAIL})
    H['UploadPhotoShareReq'] = lambda ctx, req: ctx.reply({'status': FAIL})
    H['MPPlayRoomRewardInfoReq'] = lambda ctx, req: ctx.reply({'status': OK})
    for n in ('MPTeamCreateReq', 'MPTeamJoinReq', 'MPTeamInfoReq', 'MPGameStartReq', 'MPTeamGameModeChangeReq', 'MPTeamRenameReq',
              'MPTeamKickMemberReq', 'MPTeamQuitReq', 'MPPlayRoomExitReq', 'MPSwapCharacterReq', 'MPBeaconActionReq',
              'GetGomokuOnlineChessboardReq', 'GomokuOnlinePlayerReadyReq', 'GomokuOnlinePlayerStartPlayReq',
              'GomokuOnlinePlayerPlaceStoneReq', 'WishListBuyReq', 'WishListByShopIdReq', 'GmCodeReq', 'CreatePayOrderReq',
              'RestaurantGameInfoReq', 'RestaurantGameOperateReq', 'RestaurantGameEatReq', 'RestaurantGameQuestRewardReq'):
        H.setdefault(n, lambda ctx, req: ctx.reply({'status': FAIL}))

    # ------------------------------------------------ mailbox (official flow: read -> claim -> delete read)
    KEEP = 'mail_keep'   # mail ids that are never deleted or expired (mementos, e.g. the Farewell Rewards letter)

    def mails(p):
        return p.s.setdefault('mails', [])

    def mail_items(ctx, m):
        if m.get('reward'):
            return [(r['mainItem']['itemId'], int((r['mainItem'].get('baseItem') or {}).get('num', 1) or 1)) for r in m['reward']]
        return [(x['itemId'], int(x.get('num', 1) or 1)) for x in m.get('items', [])]

    def get_mails(ctx, req):
        ctx.reply({'status': OK, 'mails': mails(ctx.p)})
    H['GetMailsReq'] = get_mails

    def operate(ctx, req):
        p = ctx.p
        op, mid = req.get('operate_type', 'MailOperateType_NONE'), req.get('mail_id')
        keep = set(p.s.get(KEEP, []))
        changed_mails, got_all, changed_items, deleted = [], [], [], []
        has_items = lambda m: bool(m.get('items') or m.get('reward'))
        for m in list(mails(p)):
            st = m.get('mail_state', 'MailState_UNREAD')
            if op == 'MailOperateType_READ' and m['mail_id'] == mid:
                if st == 'MailState_UNREAD':
                    m['mail_state'] = 'MailState_UNCLAIM' if has_items(m) else 'MailState_READED'
                changed_mails.append(m)
            elif op in ('MailOperateType_CLAIM', 'MailOperateType_CLAIM_ALL') and (op == 'MailOperateType_CLAIM_ALL' or m['mail_id'] == mid):
                if has_items(m) and st != 'MailState_CLAIMED':
                    got, ch = give(ctx, mail_items(ctx, m))
                    got_all += got
                    changed_items += ch
                    m['mail_state'] = 'MailState_CLAIMED'
                    changed_mails.append(m)
            elif op == 'MailOperateType_DELETE_ALL_READED':
                if m['mail_id'] not in keep and (st == 'MailState_CLAIMED' or (st == 'MailState_READED' and not has_items(m))):
                    mails(p).remove(m)
                    deleted.append(m['mail_id'])
        p.dirty = True
        r = {'status': OK, 'operate_type': op, 'mails': changed_mails}
        if got_all:
            r['claim_result'] = got_all
        if deleted:
            r['deleted_mail_ids'] = deleted
        ctx.reply(r)
        if changed_items:
            pack(ctx, changed_items)
    H['OperateMailsReq'] = operate

    def wish_list(ctx, req):
        st = _st(ctx.p, 'wish_list', [])
        key = [req.get('shopId'), req.get('gridId')]
        if key in st:
            st.remove(key)
        else:
            st.append(key)
        ctx.reply({'status': OK, 'operateType': req.get('operateType'), 'shopId': req.get('shopId'), 'gridId': req.get('gridId')})
    H['WishListOperateReq'] = wish_list


def _gomoku_winner(board, r, c, size=15):
    if r < 0 or c < 0 or len(board) < size * size:
        return 0
    who = board[r * size + c]
    if not who:
        return 0
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        n = 1
        for s in (1, -1):
            rr, cc = r + dr * s, c + dc * s
            while 0 <= rr < size and 0 <= cc < size and board[rr * size + cc] == who:
                n += 1
                rr, cc = rr + dr * s, cc + dc * s
        if n >= 5:
            return who
    return 0
