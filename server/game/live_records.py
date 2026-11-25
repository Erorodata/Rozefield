"""Info screens that used to only replay the archived official answer now also follow new play.

Each answer starts from what was archived from official (if any) and adds what happened on Rozefield:
  TreasureIllustrationInfoReq     treasure handbook rewards claimed here
  GetCharacterAchievementListReq  character achievement rewards claimed here
  WorldLevelAchieveListReq        world levels unlocked here
  BossRushInfoReq                 Boss Rush stages, scores and best total played here
  ChallengeFriendRankReq          your and your friends' best challenge times on this server
"""
import json

OK = 'StatusCode_OK'
ARCH_FIELD = {'EArchaeologyType_Book': 'book_reward', 'EArchaeologyType_Utensil': 'utensil_reward',
              'EArchaeologyType_TreasureMap': 'treasure_reward', 'EArchaeologyType_Shovel': 'shovel_reward'}


def _archived(p, name, req):
    from game.handlers import record_key, _record_default
    body = p.s.get('records', {}).get(name, {}).get(record_key(req))
    return dict(body) if body else None


def _add(lst, values):
    for v in values:
        if v not in lst:
            lst.append(v)
    return lst


def register(H, server_brief):
    from game.handlers import _record_default

    def base(ctx, name, req):
        return _archived(ctx.p, name, req) or _record_default(ctx, name, req)

    def treasure(ctx, req):
        r = base(ctx, 'TreasureIllustrationInfoReq', req)
        for key in ctx.p.s.get('misc', {}).get('treasure_ill', []):
            kind, _, i = key.partition(':')
            f = ARCH_FIELD.get(kind)
            if f and i.isdigit():
                r[f] = _add(list(r.get(f, [])), [int(i)])
        ctx.reply(r)
    H['TreasureIllustrationInfoReq'] = treasure

    def char_ach(ctx, req):
        r = base(ctx, 'GetCharacterAchievementListReq', req)
        cid = req.get('characterId', 0)
        done = ctx.p.s.get('misc', {}).get('char_achieve', {}).get(str(cid), [])
        r['characterId'] = cid
        r['rewardedIdLst'] = _add(list(r.get('rewardedIdLst', [])), done)
        ctx.reply(r)
    H['GetCharacterAchievementListReq'] = char_ach

    def world_level(ctx, req):
        r = base(ctx, 'WorldLevelAchieveListReq', req)
        wl = ctx.p.s.get('world_level', 1) or 1
        r['unlockWorldLevels'] = sorted(set(r.get('unlockWorldLevels', [])) | set(range(1, wl + 1)))
        ctx.reply(r)
    H['WorldLevelAchieveListReq'] = world_level

    def boss_rush(ctx, req):
        r = base(ctx, 'BossRushInfoReq', req)
        info = dict(r.get('info') or {})
        for sid, st in ctx.p.s.get('misc', {}).get('bossrush', {}).items():
            if info.get('season_id') and str(info['season_id']) != sid:
                continue
            info['season_id'] = int(sid)
            info['best_total_score'] = str(max(int(info.get('best_total_score', 0) or 0), st.get('best', 0)))
            stages = {s.get('stage_index', 0): s for s in info.get('stage_infos', [])}
            for s in st.get('stages', {}).values():
                old = stages.get(s['stage_index'], {})
                merged = dict(old)
                merged.update(s)
                merged['best_score'] = str(max(int(old.get('best_score', 0) or 0), int(s.get('best_score', 0) or 0)))
                merged['is_passed'] = bool(old.get('is_passed') or s.get('is_passed'))
                stages[s['stage_index']] = merged
            info['stage_infos'] = [stages[k] for k in sorted(stages)]
        if info:
            r['info'] = info
        ctx.reply(r)
    H['BossRushInfoReq'] = boss_rush

    def times(st):
        best = {}
        for w in st.get('world', {}).values():
            for c in w.get('challenges', []):
                t = c.get('useTime')
                if t and (c['challengeId'] not in best or t < best[c['challengeId']]):
                    best[c['challengeId']] = t
        return [{'challenge_id': k, 'use_time': v} for k, v in sorted(best.items())]

    def challenge_rank(ctx, req):
        p = ctx.p
        rank = []
        for pid in list(p.s.get('social', {}).get('friends', {})):
            o = ctx.server.player_by_id(int(pid))
            if not o:
                continue
            b = server_brief(ctx.server, int(pid))
            if b:
                rank.append({'playerInfo': b, 'challenge': {'player_id': int(pid), 'challenge_infos': times(o.s)}})
        ctx.reply({'status': OK, 'rankInfo': rank,
                   'selfChallenge': {'player_id': p.s['player_id'], 'challenge_infos': times(p.s)}})
    H['ChallengeFriendRankReq'] = challenge_rank


# ------------------------------------------------------------------ wish list (friends buy you items from it)
def register_wishlist(H, pack):
    import time
    from game.friends import edit, brief
    from game.handlers import shop_grids, shop_pool_entry

    def lst(st):
        return st.setdefault('misc', {}).setdefault('wish_list', [])

    def week():
        return time.strftime('%Y-W%W')

    def sent(p):
        w = p.s.setdefault('misc', {}).setdefault('wish_sent', {})
        if w.get('week') != week():
            w.clear(); w.update(week=week(), n=0)
        return w

    def info(e):
        return {'shopId': e[0], 'gridId': e[1], 'poolId': e[2] if len(e) > 2 else 0, 'createTime': str(e[3] if len(e) > 3 else 0)}

    def operate(ctx, req):
        p = ctx.p
        sid, gid = req.get('shopId'), req.get('gridId')
        cur = lst(p.s)
        g = next((x for x in shop_grids(ctx, sid) if x['GridID'] == gid), None)
        if not g:
            return ctx.reply({'status': 'StatusCode_FAIL'})
        old = next((e for e in cur if e[0] == sid and e[1] == gid), None)
        if req.get('operateType') == 'WishListOperateType_Add':
            if old is None:
                if len(cur) >= ctx.d.config_int('WishListsMaximumNumber', 30):
                    return ctx.reply({'status': 'StatusCode_FAIL'})
                cur.append([sid, gid, g['ShopPoolID'], int(time.time())])
        elif old is not None:
            cur.remove(old)
        p.dirty = True
        ctx.reply({'status': OK, 'operateType': req.get('operateType'), 'shopId': sid, 'gridId': gid, 'poolId': g['ShopPoolID']})
    H['WishListOperateReq'] = operate

    def by_friend(ctx, req):
        pid = req.get('playerId') or ctx.p.s['player_id']
        o = ctx.server.player_by_id(pid)
        ctx.reply({'status': OK, 'playerId': pid, 'wishList': [info(e) for e in lst(o.s)] if o else [],
                   'weekSendCount': sent(ctx.p)['n']})
    H['WishListByFriendIdReq'] = by_friend

    def by_shop(ctx, req):
        sid, gid = req.get('shopId'), req.get('gridId')
        out = []
        for fid in ctx.p.s.get('social', {}).get('friends', {}):
            o = ctx.server.player_by_id(int(fid))
            if o and any(e[0] == sid and e[1] == gid for e in lst(o.s)):
                b = brief(ctx.server, int(fid))
                if b:
                    out.append({'info': b})
        ctx.reply({'status': OK, 'info': out, 'weekSendCount': sent(ctx.p)['n']})
    H['WishListByShopIdReq'] = by_shop

    def buy(ctx, req):
        """The buyer pays the shop price; the friend gets the item by mail and loses the wish."""
        p, d = ctx.p, ctx.d
        tid, wi = req.get('playerId'), req.get('info') or {}
        sid, gid = wi.get('shopId'), wi.get('gridId')
        o = ctx.server.player_by_id(tid)
        s = sent(p)
        if not o or str(tid) not in p.s.get('social', {}).get('friends', {}) or s['n'] >= d.config_int('CommodityGiftLimitNumber', 3):
            return ctx.reply({'status': 'StatusCode_FAIL'})
        g = next((x for x in shop_grids(ctx, sid) if x['GridID'] == gid), None)
        entry = shop_pool_entry(ctx, sid, g) if g else None
        if not entry or g.get('GoodsID'):                     # real-money items can't be gifted here
            return ctx.reply({'status': 'StatusCode_FAIL'})
        costs = [(c['CurrencyID'], int(c.get('Price', 0) * entry.get('Discount', 1.0))) for c in entry.get('ShopCurrencyItem', [])
                 if c.get('CurrencyID')]
        paid = p.pay(costs)
        if paid is None:
            return ctx.reply({'status': 'StatusCode_FAIL'})
        s['n'] += 1
        items = [{'itemId': entry['ItemID'], 'num': str(entry.get('ItemNum', 1))}]

        def give(st):
            lst(st)[:] = [e for e in lst(st) if not (e[0] == sid and e[1] == gid)]
            mails = st.setdefault('mails', [])
            m = {'mail_id': max([x.get('mail_id', 0) for x in mails] + [1232]) + 1, 'mail_state': 'MailState_UNCLAIM',
                 'sender': p.s['name'], 'content_type': 'MailContentType_TEXT', 'title': 'A gift from your wish list',
                 'content': f"{p.s['name']} sent you a gift from your wish list.", 'overdueDay': 30,
                 'send_time': str(int(time.time())), 'items': items}
            mails.insert(0, m)
            box['m'] = m
        box = {}
        edit(ctx.server, tid, give)
        sess = ctx.server.sessions.get(tid)
        if sess and box.get('m'):
            try:
                sess.push('ReceiveMailNotice', {'status': OK, 'mail': box['m']})
            except Exception:
                pass
        p.dirty = True
        ctx.reply({'status': OK, 'playerId': tid, 'info': wi, 'weekSendCount': s['n']})
        pack(ctx, paid)
    H['WishListBuyReq'] = buy
