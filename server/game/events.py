"""Events and social systems, modelled on the official 2026-11-24 23:23 capture:

  * login notices: ActivityBattlePassInfoNotice, ActivityTurntableDataNotice, ActivitySignInDataNotice,
    BlessTreeNotice, DailyTaskUpdateNotice, IntimacyGiftDayCountNotice
  * Pass: GetActivityBattlePassQuestRewardReq (quest exp), ActivityBattlePassBuyExpReq (50 Starstone -> 1000 exp),
    GetActivityBattlePassLevelRewardReq (all unclaimed free-track levels)
  * Gashapon (turntable): ActivityTurntableDrawReq; a prize with a limit is checked off once it has been drawn
  * Wishing tree: BlessTreeUnlockReq (pay Wish Stones for a node), DailyTaskExchangeReq (collect earned Wish Stones)
  * Sign-in: ActivitySignInReq
  * Abyss: AbyssInfoReq, AbyssTeamUpdateReq, AbyssTeamSwitchReq (team 2 takes over mid-run)
  * Social: MultipleActionAcceptReq (group emote), ThrowDiceReq, UseItemFriendIntimacyReq (gift candy/chocolate)
  * Recruit results carry 'extras' (bonus items per result) and 'extraQuality' (item quality); the official
    client waits for them before it lets you leave the result screen
"""
import random
import time

from game import quests as Q

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
STARSTONE, WISH_STONE, GACHA_COIN, RHOMBITE = 102, 125, 126, 102
PASS_EXP_PRICE, PASS_EXP_AMOUNT = 50, 1000           # official: 50 Starstone -> 1000 Pass EXP


def _ms(ts):
    """Table times are UTC+8."""
    import calendar
    return str((calendar.timegm(time.strptime(ts, '%Y-%m-%d %H:%M:%S')) - 8 * 3600) * 1000) if ts else '0'


def _ev(p):
    return p.s.setdefault('events', {})


def _activities(d, kind):
    """Activity rows of one NewActivityType that are open now; after the shutdown (nothing open) the latest
    one of that type stays available so the feature keeps working."""
    rows = [r for r in d.table('activity', 'Activity').values() if r.get('NewActivityType') == kind]
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() + 8 * 3600))
    live = [r for r in rows if (not r.get('OpeningTime') or r['OpeningTime'] <= now) and (not r.get('ClosingTime') or now <= r['ClosingTime'])]
    if live:
        return live
    dated = sorted([r for r in rows if r.get('OpeningTime')], key=lambda r: r['OpeningTime'])
    return dated[-1:] or rows[:1]


def _day(t=None):
    return time.strftime('%Y-%m-%d', time.gmtime((t or time.time()) + 4 * 3600))


# ------------------------------------------------------------------ pass
def _bp_cfg(d, act):
    return d.row('battlepass', 'BattlePass', act.get('ActivityID'))


def _bp(p, act_id):
    return _ev(p).setdefault('battlepass', {}).setdefault(str(act_id), {'totalExp': 0, 'weekExp': 0, 'week': '',
                                                                      'free': [], 'daily': [], 'weekly': [], 'season': [], 'day': ''})


def _bp_level(cfg, total):
    lv, need = 0, 0
    for row in cfg.get('BattlePassLevelUps', []):
        need += row.get('Exp', 1000)
        if total >= need:
            lv = row['Level']
        else:
            return lv, total - (need - row.get('Exp', 1000))
    return lv, total - need


def _bp_info(d, p, act):
    cfg = _bp_cfg(d, act) or {}
    st = _bp(p, act['ID'])
    if st['day'] != _day():
        st['day'], st['daily'] = _day(), []
    wk = time.strftime('%Y-%W', time.gmtime(time.time() + 4 * 3600))
    if st['week'] != wk:
        st['week'], st['weekly'], st['weekExp'] = wk, [], 0
    lv, cur = _bp_level(cfg, st['totalExp'])
    return {'activityId': act['ID'], 'openTime': _ms(act.get('OpeningTime')), 'closeTime': _ms(act.get('ClosingTime')),
            'dailyAchieveRewardLst': st['daily'], 'weeklyAchieveRewardLst': st['weekly'], 'seasonAchieveRewardLst': st['season'],
            'level': lv, 'totalExp': str(st['totalExp']), 'weekExp': st['weekExp'], 'freeLvRewardLst': st['free'], 'currentExp': cur}


def _bp_add(d, p, act, exp, weekly=True):
    cfg = _bp_cfg(d, act) or {}
    st = _bp(p, act['ID'])
    if weekly:
        room = max(0, cfg.get('MaxExp', 15000) - st['weekExp'])
        exp = min(exp, room)
        st['weekExp'] += exp
    st['totalExp'] += exp
    p.dirty = True
    return exp


# ------------------------------------------------------------------ turntable (gashapon)
def _tt(p, act_id):
    return _ev(p).setdefault('turntable', {}).setdefault(str(act_id), {'drawn': {}, 'draws': 0})


def _tt_items(d, p, act):
    cfg = d.row('activityturntable', 'ActivityTurntable', act.get('ActivityID')) or {}
    pool = d.row('activityturntable', 'TurntablePool', cfg.get('TurntablePoolID')) or {}
    st = _tt(p, act['ID'])
    if 'remain' in st:   # imported snapshot of the official remaining counts
        for it in pool.get('TurntablePoolItem', []):
            r = st['remain'].get(str(it['Index']))
            if it.get('LimitNum') and r is not None:
                st['drawn'][str(it['Index'])] = it['LimitNum'] - r
        del st['remain']
    out = {}
    for it in pool.get('TurntablePoolItem', []):
        e = {'index': it['Index'], 'itemId': it['ItemID'], 'itemNum': it.get('ItemNum', 1)}
        if it.get('LimitNum'):
            e['remainCount'] = max(0, it['LimitNum'] - st['drawn'].get(str(it['Index']), 0))
        if it.get('IsSpecial'):
            e['isSpecial'] = True
        out[str(it['Index'])] = e
    return cfg, pool, out


def register(H, pack, scene_player):
    orig_main = H.get('PlayerMainDataReq')

    def main_data(ctx, req):
        orig_main(ctx, req)
        p, d = ctx.p, ctx.d
        try:
            ctx.push('ActivityBattlePassInfoNotice', {'status': OK, 'info': [_bp_info(d, p, a) for a in _activities(d, 3)]})
            acts = []
            for a in _activities(d, 6):
                _, _, items = _tt_items(d, p, a)
                acts.append({'activityId': a['ID'], 'openTime': _ms(a.get('OpeningTime')), 'closeTime': _ms(a.get('ClosingTime')), 'items': items})
            ctx.push('ActivityTurntableDataNotice', {'status': OK, 'activities': acts})
            ctx.push('ActivitySignInDataNotice', {'status': OK, 'info': [_sign_info(d, p, a) for a in _activities(d, 1)]})
            ctx.push('BlessTreeNotice', {'status': OK, 'tress': {k: {'treeIds': v} for k, v in _ev(p).get('bless', {}).items()}})
            ctx.push('DailyTaskUpdateNotice', dict(status=OK, **_daily_task(p)))
            ctx.push('IntimacyGiftDayCountNotice', {'status': OK, 'count': _ev(p).get('gift_day', {}).get(_day(), 0)})
        except Exception:
            import logging
            logging.exception('event login notices')
    H['PlayerMainDataReq'] = main_data

    # ---------------- pass
    def act_of(ctx, aid):
        a = ctx.d.row('activity', 'Activity', aid)
        return a if a and _bp_cfg(ctx.d, a) else None

    def bp_quest(ctx, req):
        p, d = ctx.p, ctx.d
        a = act_of(ctx, req.get('activityBattlePassId'))
        aid = req.get('achieveId')
        if not a:
            return ctx.reply({'status': FAIL})
        cfg = _bp_cfg(d, a)
        st = _bp(p, a['ID'])
        _bp_info(d, p, a)   # roll the day / week
        exp, kind = 0, None
        for qid, k in ((cfg.get('DayQuestID'), 'daily'), (cfg.get('WeekQuestID'), 'weekly'), (cfg.get('SeasonQuestID'), 'season')):
            for q in (d.row('battlepass', 'BattlePassQueset', qid) or {}).get('BattlePassQuesetItem', []):
                if q.get('AchieveID') == aid:
                    exp, kind = q.get('Exp', 0), k
        if not kind or aid in st[kind]:
            return ctx.reply({'status': FAIL})
        st[kind].append(aid)
        add = _bp_add(d, p, a, exp)
        lv, cur = _bp_level(cfg, st['totalExp'])
        ctx.reply({'status': OK, 'addExp': add, 'currentLv': lv, 'currentWeekExp': st['weekExp'],
                   'currentTotalExp': str(st['totalExp']), 'currentExp': cur})
    H['GetActivityBattlePassQuestRewardReq'] = bp_quest

    def bp_buy(ctx, req):
        p, d = ctx.p, ctx.d
        a = act_of(ctx, req.get('activityBattlePassId'))
        if not a:
            return ctx.reply({'status': FAIL})
        paid = p.pay([(STARSTONE, PASS_EXP_PRICE)])
        if paid is None:
            return ctx.reply({'status': FAIL})
        cfg, st = _bp_cfg(d, a), _bp(p, a['ID'])
        _bp_add(d, p, a, PASS_EXP_AMOUNT, weekly=False)
        lv, cur = _bp_level(cfg, st['totalExp'])
        ctx.reply({'status': OK, 'activityBattlePassId': a['ID'], 'battlePassLv': lv, 'totalExp': str(st['totalExp']), 'currentExp': cur})
        pack(ctx, paid)
    H['ActivityBattlePassBuyExpReq'] = bp_buy

    def bp_levels(ctx, req):
        p, d = ctx.p, ctx.d
        a = act_of(ctx, req.get('activityBattlePassId'))
        if not a:
            return ctx.reply({'status': FAIL})
        cfg, st = _bp_cfg(d, a), _bp(p, a['ID'])
        lv, _ = _bp_level(cfg, st['totalExp'])
        items = []
        for row in cfg.get('BattlePassLevelUps', []):
            if row['Level'] <= lv and row['Level'] not in st['free']:
                st['free'].append(row['Level'])
                items += [(x['ItemID'], x.get('ItemNum', 1)) for x in row.get('BattlePassReward', [])]
        got, changed = p.add_items(items) if items else ([], [])
        p.dirty = True
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, changed)
    H['GetActivityBattlePassLevelRewardReq'] = bp_levels

    # ---------------- turntable
    def tt_draw(ctx, req):
        p, d = ctx.p, ctx.d
        a = d.row('activity', 'Activity', req.get('activity_id'))
        if not a:
            return ctx.reply({'status': FAIL})
        cfg, pool, items = _tt_items(d, p, a)
        st = _tt(p, a['ID'])
        times = max(1, req.get('draw_times', 1))
        cost_item = cfg.get('CostItemID', GACHA_COIN)
        need = sum((cfg.get('FirstOneNeedItemNum', 1) if st['draws'] + k == 0 else cfg.get('OneNeedItemNum', 1)) for k in range(times))
        have = p.count(cost_item)
        paid = []
        if have < need:   # official: "Not enough Gacha Coin. Use 60 Rhombite to make up the difference?"
            paid = p.pay([(cost_item, have), (RHOMBITE, 60 * (need - have))] if have else [(RHOMBITE, 60 * (need - have))])
        else:
            paid = p.pay([(cost_item, need)])
        if paid is None:
            return ctx.reply({'status': FAIL})
        idx, rewards = [], []
        for _ in range(times):
            cand = [it for it in pool.get('TurntablePoolItem', [])
                    if not it.get('LimitNum') or st['drawn'].get(str(it['Index']), 0) < it['LimitNum']]
            if not cand:
                break
            pick = random.choices(cand, weights=[max(1, it.get('Weight', 1)) for it in cand])[0]
            st['drawn'][str(pick['Index'])] = st['drawn'].get(str(pick['Index']), 0) + 1
            st['draws'] += 1
            idx.append(pick['Index'])
            st.setdefault('records', []).append({'index': pick['Index'], 'itemId': pick['ItemID'], 'itemNum': pick.get('ItemNum', 1),
                                                 'drawTime': str(int(time.time()))})
            rewards.append((pick['ItemID'], pick.get('ItemNum', 1)))
        got, changed = p.add_items(rewards) if rewards else ([], [])
        p.dirty = True
        ctx.reply({'status': OK, 'activity_id': a['ID'], 'rewardIndexes': idx, 'rewards': got})
        pack(ctx, paid + changed)
    H['ActivityTurntableDrawReq'] = tt_draw

    # ---------------- wishing tree
    def bless_unlock(ctx, req):
        p, d = ctx.p, ctx.d
        tree, box = req.get('defId'), req.get('treeId')
        info = d.row('blessingtree', 'BlessingTreeInfo', (d.row('blessingtree', 'BlessingTree', tree) or {}).get('BlessingTreeInfoID', tree))
        node = next((x for x in (info or {}).get('BlessingTreeInfoGroupInfo', []) if x.get('BoxID') == box), None)
        done = _ev(p).setdefault('bless', {}).setdefault(str(tree), [])
        if not node or box in done or (node.get('RelateBoxID') and node['RelateBoxID'] not in done):
            return ctx.reply({'status': FAIL})
        paid = p.pay([(node.get('ItemID', WISH_STONE), node.get('ItemCount', 0))])
        if paid is None:
            return ctx.reply({'status': FAIL})
        done.append(box)
        got, changed = p.add_items([(node['RewardItemID'], node.get('RewardItemCount', 1))])
        p.dirty = True
        ctx.reply({'status': OK, 'defId': tree, 'treeId': box, 'rewards': got})
        pack(ctx, paid + changed)
    H['BlessTreeUnlockReq'] = bless_unlock

    def bless_info(ctx, req):
        tree = req.get('defId')
        ctx.reply({'status': OK, 'defId': tree, 'tress': {'treeIds': _ev(ctx.p).get('bless', {}).get(str(tree), [])}})
    H['BlessTreeReq'] = bless_info

    def tt_record(ctx, req):
        recs = _tt(ctx.p, req.get('activity_id'))
        recs = recs.get('records', [])[::-1]
        page, per = max(1, req.get('page', 1)), 10
        ctx.reply({'status': OK, 'activity_id': req.get('activity_id'), 'page': page,
                   'totalPage': max(1, (len(recs) + per - 1) // per), 'records': recs[(page - 1) * per: page * per]})
    H['ActivityTurntableRecordReq'] = tt_record

    def daily_exchange(ctx, req):
        p = ctx.p
        dt = _daily_task(p)
        n = dt['exchange_times_left']
        if n <= 0:
            return ctx.reply({'status': FAIL})
        _ev(p)['daily_task']['left'] = 0
        got, changed = p.add_items([(WISH_STONE, n)])
        p.dirty = True
        ctx.reply({'status': OK, 'rewards': got, 'today_converted': dt['today_converted']})
        pack(ctx, changed)
    H['DailyTaskExchangeReq'] = daily_exchange

    # ---------------- sign-in
    def sign_in(ctx, req):
        """rewardId is a bit mask of the claimed days (bit n = day n); loginDay is how many days can be claimed."""
        p, d = ctx.p, ctx.d
        a = d.row('activity', 'Activity', req.get('activityId'))
        cfg = d.row('activitysign', 'ActivitySign', (a or {}).get('ActivityID')) if a else None
        st = _sign(p, req.get('activityId'))
        day = req.get('day') or next((k for k in range(1, 400) if not st['mask'] >> k & 1), 1)
        row = next((x for x in (cfg or {}).get('ActivitySignItem', []) if x.get('Days') == day), None)
        if not row or st['mask'] >> day & 1 or day > _sign_days(st):
            return ctx.reply({'status': FAIL})
        st['mask'] |= 1 << day
        got, changed = p.add_items([(x['ItemID'], x.get('ItemNum', 1)) for x in row.get('ActivitySignRewardItem', [])])
        p.dirty = True
        ctx.reply({'status': OK, 'day': day, 'rewardId': st['mask'], 'rewards': got})
        pack(ctx, changed)
    H['ActivitySignInReq'] = sign_in

    # ---------------- abyss
    def abyss_season(d):
        now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() + 8 * 3600))
        rows = [r for r in d.table('abyss', 'AbyssSeason').values() if r.get('StartTime')]
        live = [r for r in rows if r['StartTime'] <= now <= r['EndTime']]
        return (live or sorted(rows, key=lambda r: r['StartTime'])[-1:] or [{'ID': 0}])[0]['ID']

    def abyss_state(p):
        return _ev(p).setdefault('abyss', {})

    def abyss_info(ctx, req):
        p, d = ctx.p, ctx.d
        cur = abyss_season(d)
        seasons = abyss_state(p)
        seasons.setdefault('9000001', {})
        seasons.setdefault(str(cur), {})
        info = {k: {'seasonId': int(k), 'dungeonInfo': v} if v else {} for k, v in seasons.items()}
        ctx.reply({'status': OK, 'abyssInfo': {'seasonInfo': info, 'inProgressSeasonId': cur}})
    H['AbyssInfoReq'] = abyss_info

    def abyss_season_of(d, dungeon_id):
        for r in d.table('abyss', 'AbyssSeason').values():
            st = d.row('abyss', 'AbyssStage', r.get('SeasonStage'))
            if st and any(x.get('DungeonID') == dungeon_id for x in st.get('AbyssStageGroupInfo', [])):
                return r['ID']
        return abyss_season(d)

    def abyss_team(ctx, req):
        p, d = ctx.p, ctx.d
        did = req.get('dungeonId')
        team = {k: v for k, v in (req.get('abyssTeam') or {}).items() if k.startswith('char')}
        sid = str(abyss_season_of(d, did))
        dg = abyss_state(p).setdefault(sid, {}).setdefault(str(did), {'dungeonId': did, 'abyssTeams': []})
        i = req.get('teamIndex', 0)
        while len(dg['abyssTeams']) <= i:
            dg['abyssTeams'].append({})
        dg['abyssTeams'][i] = team
        p.dirty = True
        ctx.reply({'status': OK})
    H['AbyssTeamUpdateReq'] = abyss_team

    def abyss_switch(ctx, req):
        """Second team takes over in the middle of an Aberration Area run."""
        p, d = ctx.p, ctx.d
        did = ctx.__dict__.get('dungeon_id')
        sid = str(abyss_season_of(d, did))
        teams = abyss_state(p).get(sid, {}).get(str(did), {}).get('abyssTeams', [])
        if len(teams) < 2:
            return ctx.reply({'status': FAIL})
        saved = dict(p.s['team'])
        p.s['team'] = dict(teams[1])
        try:
            team = scene_player(p)['team']
        finally:
            p.s['team'] = saved
        ctx.reply({'status': OK, 'team': team})
    H['AbyssTeamSwitchReq'] = abyss_switch

    orig_finish = H.get('DungeonFinishReq')

    def finish(ctx, req):
        did = req.get('dungeon_id') or ctx.__dict__.get('dungeon_id')
        start = ctx.__dict__.get('dungeon_start')
        orig_finish(ctx, req)
        if did and 99030000 <= did < 99100000 and req.get('is_success') and start:
            p, d = ctx.p, ctx.d
            ms = int((time.time() - start) * 1000)
            dg = abyss_state(p).setdefault(str(abyss_season_of(d, did)), {}).setdefault(str(did), {'dungeonId': did, 'abyssTeams': []})
            if not dg.get('finishTime') or ms < dg['finishTime']:
                dg['finishTime'] = ms
            p.dirty = True
    if orig_finish:
        H['DungeonFinishReq'] = finish

    # ---------------- social
    def multi_accept(ctx, req):
        ctx.reply({'status': OK})
        note = {'status': OK, 'actionId': req.get('actionId'), 'fromPlayerId': req.get('fromPlayerId'),
                'actionPlayerIds': [req.get('fromPlayerId'), ctx.p.s['player_id']]}
        ctx.server.broadcast(ctx, 'SendMultipleActionCompleteNotice', note)   # both players (and onlookers) play it
    H['MultipleActionAcceptReq'] = multi_accept

    def dice(ctx, req):
        """The throw (with pips) spends one Dice (item 2020); the follow-up report without pips is just acknowledged."""
        p = ctx.p
        paid = []
        if req.get('pips') and p.count(2020) > 0:
            paid = p.pay([(2020, 1)]) or []
        ctx.reply({'status': OK})
        if paid:
            pack(ctx, paid)
    H['ThrowDiceReq'] = dice

    def gift(ctx, req):
        p, d = ctx.p, ctx.d
        item, fid = req.get('item_id'), req.get('friend_id')
        value = (d.item(item) or {}).get('RelateID', 0)
        if not value or d.item_tag(item) != 'EBagItemTag_IntimacyGift':
            return ctx.reply({'status': FAIL})
        paid = p.pay([(item, 1)])
        if paid is None:
            return ctx.reply({'status': FAIL})
        im = _ev(p).setdefault('intimacy', {})
        im[str(fid)] = im.get(str(fid), 0) + value
        gd = _ev(p).setdefault('gift_day', {})
        gd = {_day(): gd.get(_day(), 0) + 1}
        _ev(p)['gift_day'] = gd
        from game.friends import edit   # intimacy is shared by both friends (saved even if they're offline)
        me, val = str(p.s['player_id']), im[str(fid)]
        edit(ctx.server, fid, lambda st: st.setdefault('events', {}).setdefault('intimacy', {}).__setitem__(me, val))
        p.dirty = True
        ctx.reply({'status': OK, 'friend_id': fid, 'intimacy': im[str(fid)]})
        pack(ctx, paid)
    H['UseItemFriendIntimacyReq'] = gift

    orig_friends = H.get('FriendReq')

    def friends(ctx, req):
        """Add the friendship points (hearts) to the friend list."""
        out = []
        real = ctx.reply
        ctx.reply = lambda m: out.append(m)
        try:
            orig_friends(ctx, req)
        finally:
            ctx.reply = real
        m = out[0] if out else {'status': OK, 'info': []}
        im = _ev(ctx.p).get('intimacy', {})
        for f in m.get('info', []):
            pid = str((f.get('info') or {}).get('playerId', ''))
            if pid in im:
                f['friend_intimacy'] = im[pid]
        real(m)
    if orig_friends:
        H['FriendReq'] = friends

    # ---------------- recruit result extras
    orig_gacha = H.get('GachaReq')

    def gacha(ctx, req):
        out = []
        real = ctx.reply
        ctx.reply = lambda m: out.append(m)
        try:
            orig_gacha(ctx, req)
        finally:
            ctx.reply = real
        if not out:
            return
        m = out[0]
        p, d = ctx.p, ctx.d
        extra_items = []
        for it in m.get('items', []):
            main = it.get('mainItem', {})
            iid = main.get('itemId')
            if main.get('itemTag') == 'EBagItemTag_Poster':
                iid = (main.get('poster') or {}).get('posterId', iid)
                main['itemId'] = iid          # official recruit results name the imprint, not the bag instance
            elif main.get('itemTag') == 'EBagItemTag_Character' or main.get('character'):
                iid = (main.get('character') or {}).get('characterId', iid)
            q = (d.item(iid) or {}).get('Quality', 3)
            it['extraQuality'] = q
            ex = gacha_extras(main, q)
            it['extras'] = [{'itemId': i, 'itemTag': d.item_tag(i), 'baseItem': {'itemId': i, 'num': str(n)}} for i, n in ex]
            extra_items += ex
        if extra_items:
            _, changed = p.add_items(extra_items)
            p.dirty = True
        real(m)
        if extra_items:
            pack(ctx, changed)
    if orig_gacha:
        H['GachaReq'] = gacha


def gacha_extras(main, quality):
    """Bonus items per recruit result. Seen on official (SR): imprint -> 112 x15 + 107 x50,
    salvager -> 111 x12 + 107 x500. SSR and R amounts are estimates."""
    salvager = bool(main.get('character')) or main.get('itemTag') in ('EBagItemTag_Character', 'EBagItemTag_Card')
    if salvager:
        return [(111, 40 if quality >= 4 else 12), (107, 2000 if quality >= 4 else 500)]
    if quality >= 4:
        return [(112, 40), (107, 200)]
    if quality == 3:
        return [(112, 15), (107, 50)]
    return [(113, 5), (107, 10)]


def _sign(p, act_id):
    st = _ev(p).setdefault('signin', {}).setdefault(str(act_id), {'mask': 0, 'first': int(time.time()), 'days': 0, 'day': ''})
    if 'rewardDay' in st:   # older format
        st['mask'] = st.pop('rewardDay')
    st.setdefault('days', bin(st['mask']).count('1'))
    st.setdefault('day', '')
    if st['day'] != _day():   # one more claimable day for every day the player logs in
        st['day'] = _day()
        st['days'] += 1
        p.dirty = True
    return st


def _sign_days(st):
    return st['days']


def _sign_info(d, p, act):
    st = _sign(p, act['ID'])
    e = {'activityId': act['ID'], 'loginDay': _sign_days(st), 'rewardId': st['mask'], 'initTime': str(st['first'])}
    if act.get('OpeningTime'):
        e['openTime'], e['closeTime'] = _ms(act['OpeningTime']), _ms(act.get('ClosingTime'))
    return e


MOON_POINT = 124
PARTTIME_SLOTS = (521, 522, 523, None)    # official: one task from each of these groups + one more
TICKET, TICKET_DAILY = 117, 6             # co-op game tickets, official list showed 6/6


def _daily_task(p):
    """Official system: Moon Points (item 124) from part-time tasks and activities are converted into Wish Stones in
    steps (dailytask.json DailyTaskReward: 60, 60, 60, 60, 80 ... 5000 points per step, 21 steps a day); the
    converted stones wait until they are collected with DailyTaskExchangeReq."""
    st = _ev(p).setdefault('daily_task', {'day': '', 'left': 0, 'converted': 0, 'tasks': {}})
    st.setdefault('tasks', {})
    if st['day'] != _day():
        st.update(day=_day(), converted=0, tasks={})
        st.pop('paid_done', None)
        _new_parttime(p, st)
        if p.count(TICKET) < TICKET_DAILY:
            p.add_items([(TICKET, TICKET_DAILY - p.count(TICKET))])
        p.dirty = True
    _convert(p, st)
    return {'tasks': {k: v for k, v in st['tasks'].items()}, 'today_converted': st['converted'], 'exchange_times_left': st['left']}


def _new_parttime(p, st):
    from game import quests as Q2
    pool = {}
    for q in p.d.table('quest', 'Quest').values():
        if q.get('NewType') == 7 and 520000 <= q['ID'] < 530000:
            pool.setdefault(q['ID'] // 1000, []).append(q['ID'])
    for qid in list(p.s.get('quests', {})):   # yesterday's part-time tasks go away
        if qid.isdigit() and 520000 <= int(qid) < 530000:
            del p.s['quests'][qid]
    used = set()
    for slot, grp in enumerate(PARTTIME_SLOTS, 1):
        cand = [q for q in (pool.get(grp) if grp else [x for v in pool.values() for x in v]) if q not in used]
        if not cand:
            continue
        qid = random.choice(cand)
        used.add(qid)
        st['tasks'][str(slot)] = qid
        Q2.accept(p, qid)


def _convert(p, st):
    steps = sorted(p.d.table('dailytask', 'DailyTaskReward').values(), key=lambda r: r['ID'])
    while st['converted'] < len(steps):
        row = steps[st['converted']]
        if p.count(row.get('CostItemID', MOON_POINT)) < row.get('CostItemNum', 60):
            break
        if p.pay([(row.get('CostItemID', MOON_POINT), row.get('CostItemNum', 60))]) is None:
            break
        st['converted'] += 1
        st['left'] += 1
        p.dirty = True


def moon_reward(ctx, gameplay_id, n):
    """Moon Points for playing (official MoonQuestGamePlayRewardNotice, seen: 5 and 25 points)."""
    p = ctx.p
    got, changed = p.add_items([(MOON_POINT, n)])
    p.dirty = True
    try:
        ctx.push('MoonQuestGamePlayRewardNotice', {'status': OK, 'id': gameplay_id, 'rewards': got})
        ctx.push('PackNotice', {'status': OK, 'items': changed})
        before = _ev(p).get('daily_task', {}).get('left', 0)
        dt = _daily_task(p)
        if dt['exchange_times_left'] != before:
            ctx.push('DailyTaskUpdateNotice', dict(status=OK, **dt))
    except Exception:
        pass
