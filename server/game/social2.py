"""Systems that involve other players on this server: online Gomoku, the photo wall, rankings, and the
restaurant mini-game (single player, from restaurantgame.json).

Gomoku: a board is identified by the furniture id the players sit at (request field 'id'). Two players
ready up, the first to sit starts, the server checks five in a row and sends the result to both.
Photo wall: uploads are kept in save/photos/ (index.json + one .b64 file per photo).
"""
import base64
import json
import os
import random
import threading
import time

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO_DIR = os.path.join(HERE, 'save', 'photos')
SIZE = 15
TURN = 60          # seconds per move
_lock = threading.Lock()


def brief(server, pid):
    o = server.player_by_id(pid)
    if not o:
        return {'playerId': pid}
    s = o.s
    return {'playerId': pid, 'nickName': s['name'], 'level': s.get('level', 1), 'head': s.get('head', 0),
            'isOnline': server.is_online(pid), 'sign': s.get('sign', ''), 'playerLabel': s.get('player_label', 0),
            'characterId': s.get('team', {}).get('char1', 0), 'createTime': s.get('create_time', 0)}


def _five(board, r, c, who):
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        n = 1
        for sgn in (1, -1):
            rr, cc = r + dr * sgn, c + dc * sgn
            while 0 <= rr < SIZE and 0 <= cc < SIZE and board[rr * SIZE + cc] == who:
                n += 1
                rr, cc = rr + dr * sgn, cc + dc * sgn
        if n >= 5:
            return True
    return False


def register(H, pack):
    boards = {}   # furniture id -> board state

    def gb(i):
        return boards.setdefault(str(i), {'id': i, 'players': [], 'watch': [], 'board': [0] * SIZE * SIZE, 'state': 'EGomokuChessBoardStatus_None',
                                          'next': 0, 'deadline': 0, 'ready': set()})

    def tell(ctx, b, name, body):
        for pid in b['players'] + b['watch']:
            s = ctx.server.sessions.get(pid)
            if s:
                try:
                    s.push(name, body)
                except Exception:
                    pass

    def board_info(ctx, req):
        b = gb(req.get('id'))
        ctx.reply({'status': OK, 'boardState': b['state'], 'chest_players': [brief(ctx.server, x) for x in b['players']],
                   'watch_players': [brief(ctx.server, x) for x in b['watch']], 'next_player_id': b['next'],
                   'turn_deadline': str(b['deadline']), 'board': b['board']})
    H['GetGomokuOnlineChessboardReq'] = board_info

    def ready(ctx, req):
        b = gb(req.get('id'))
        pid = ctx.p.s['player_id']
        if pid not in b['players']:
            if len(b['players']) >= 2:
                return ctx.reply({'status': FAIL})
            b['players'].append(pid)
        b['ready'].add(pid)
        if b['state'] in ('EGomokuChessBoardStatus_None', 'EGomokuChessBoardStatus_Over'):
            b.update(board=[0] * SIZE * SIZE, state='EGomokuChessBoardStatus_Start')
        ctx.reply({'status': OK})
        if len(b['players']) == 2:
            tell(ctx, b, 'GomokuOnlinePlayerNotice', {'status': OK, 'first_player_id': str(b['players'][0]),
                                                      'player1_id': str(b['players'][0]), 'player2_id': str(b['players'][1])})
    H['GomokuOnlinePlayerReadyReq'] = ready

    def start(ctx, req):
        b = gb(req.get('id'))
        if len(b['players']) < 2:
            return ctx.reply({'status': FAIL})
        b.update(state='EGomokuChessBoardStatus_Playing', next=b['players'][0], deadline=int(time.time()) + TURN)
        ctx.reply({'status': OK, 'turn_deadline': str(b['deadline'])})
        tell(ctx, b, 'GomokuOnlinePlayerStartPlayNotice', {'status': OK, 'id': str(b['id']), 'first_player_id': b['next'],
                                                           'turn_deadline': str(b['deadline'])})
    H['GomokuOnlinePlayerStartPlayReq'] = start

    def place(ctx, req):
        b = gb(req.get('id'))
        pid = ctx.p.s['player_id']
        r, c = req.get('row', 0), req.get('col', 0)
        if b['state'] != 'EGomokuChessBoardStatus_Playing' or pid != b['next'] or not (0 <= r < SIZE and 0 <= c < SIZE) or b['board'][r * SIZE + c]:
            return ctx.reply({'status': FAIL})
        who = 1 if pid == b['players'][0] else 2
        b['board'][r * SIZE + c] = who
        win = _five(b['board'], r, c, who)
        other = [x for x in b['players'] if x != pid]
        b['next'] = 0 if win else (other[0] if other else pid)
        b['deadline'] = int(time.time()) + TURN
        ctx.reply({'status': OK, 'is_win': win, 'next_player_id': b['next'], 'turn_deadline': str(b['deadline'])})
        tell(ctx, b, 'GomokuOnlinePlayerPlaceStoneNotice', {'status': OK, 'id': str(b['id']), 'row': r, 'col': c, 'chess': who,
                                                            'next_player_id': b['next'], 'turn_deadline': str(b['deadline']), 'is_win': win})
        if win:
            over(ctx, b, pid, 'EGomokuOverReason_Win')
    H['GomokuOnlinePlayerPlaceStoneReq'] = place

    def over(ctx, b, winner, reason):
        b['state'] = 'EGomokuChessBoardStatus_Over'
        for pid in b['players']:
            s = ctx.server.sessions.get(pid)
            if not s or not s.p:
                continue
            won = pid == winner
            got, changed = s.p.add_items([(101, 300 if won else 100)])   # estimate
            s.p.dirty = True
            try:
                s.push('GomokuOnlineSettlementNotice', {'status': OK, 'id': str(b['id']), 'is_win': won, 'over_reason': reason, 'items': got})
                s.push('PackNotice', {'status': OK, 'items': changed})
            except Exception:
                pass
        tell(ctx, b, 'GomokuOnlinePlayerRemoveNotice', {'status': OK, 'id': str(b['id']), 'winner_id': str(winner), 'over_reason': reason})
        b['ready'] = set()

    def leave(ctx, req):
        b = gb(req.get('id'))
        pid = ctx.p.s['player_id']
        ctx.reply({'status': OK})
        playing = b['state'] == 'EGomokuChessBoardStatus_Playing' and pid in b['players']
        tell(ctx, b, 'GomokuOnlinePlayerLeaveNotice', {'status': OK, 'id': str(b['id']), 'player_id': pid, 'is_player': pid in b['players']})
        if playing:
            other = [x for x in b['players'] if x != pid]
            over(ctx, b, other[0] if other else 0, 'EGomokuOverReason_Leave')
        for k in ('players', 'watch'):
            if pid in b[k]:
                b[k].remove(pid)
        if not b['players']:
            boards.pop(str(b['id']), None)
    H['GomokuOnlinePlayerLeaveReq'] = leave

    def watch(ctx, req):
        b = gb(req.get('id'))
        pid = ctx.p.s['player_id']
        if pid not in b['watch'] and pid not in b['players']:
            b['watch'].append(pid)
        ctx.reply({'status': OK})
        tell(ctx, b, 'GomokuOnlinePlayerWatchNotice', {'status': OK, 'id': str(b['id']), 'player_id': pid})
    H['GomokuOnlinePlayerWatchReq'] = watch

    # ---------------------------------------------------------------- photo wall
    def idx():
        os.makedirs(PHOTO_DIR, exist_ok=True)
        p = os.path.join(PHOTO_DIR, 'index.json')
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {'next': 100001, 'photos': {}}

    def save_idx(x):
        json.dump(x, open(os.path.join(PHOTO_DIR, 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False)

    def preview(ctx, ph):
        me = str(ctx.p.s['player_id'])
        return {'code': str(ph['code']), 'player_label': ph.get('player_label', 0), 'player_id': ph['player_id'], 'player_name': ph['player_name'],
                'head': ph.get('head', 0), 'title': ph.get('title', ''), 'likes_total': len(ph.get('likes', [])),
                'likes_status': me in ph.get('likes', []), 'status': 'AuditStatus_SUCCESS'}

    def detail(ctx, ph):
        me = str(ctx.p.s['player_id'])
        d = dict(preview(ctx, ph), upload_time=str(ph.get('time', 0)), tag1=ph.get('tag1', ''), tag2=ph.get('tag2', ''), tag3=ph.get('tag3', ''),
                 favorite_total=len(ph.get('fav', [])), favorite_status=me in ph.get('fav', []),
                 character_id=ph.get('character_id', 0), weaponId=ph.get('weaponId', 0))
        if ph.get('camera_param'):
            d['camera_param'] = ph['camera_param']
        return d

    def upload(ctx, req):
        p = ctx.p
        with _lock:
            x = idx()
            code = x['next']
            x['next'] += 1
            ph = {'code': code, 'player_id': p.s['player_id'], 'player_label': p.s.get('player_label', 0), 'player_name': p.s['name'],
                  'head': p.s.get('head', 0), 'title': req.get('title', ''), 'tag1': req.get('tag1', ''), 'tag2': req.get('tag2', ''),
                  'tag3': req.get('tag3', ''), 'time': int(time.time()), 'likes': [], 'fav': [],
                  'character_id': p.s.get('team', {}).get('char1', 0), 'camera_param': req.get('camera_param')}
            data = req.get('file', '')
            if isinstance(data, (bytes, bytearray)):
                data = base64.b64encode(data).decode()
            open(os.path.join(PHOTO_DIR, '%d.b64' % code), 'w').write(data or '')
            x['photos'][str(code)] = ph
            save_idx(x)
        ctx.reply({'status': OK, 'info': detail(ctx, ph)})
    H['UploadPhotoShareReq'] = upload

    def search(ctx, req):
        x = idx()
        me = ctx.p.s['player_id']
        lst = list(x['photos'].values())
        st, text = req.get('search_type', 'PhotoSearchType_NEW'), (req.get('text') or '').strip()
        if st == 'PhotoSearchType_MY_SHARE':
            lst = [p for p in lst if p['player_id'] == me]
        elif st == 'PhotoSearchType_MY_FAVORITE':
            lst = [p for p in lst if str(me) in p.get('fav', [])]
        elif st in ('PhotoSearchType_SEARCH', 'PhotoSearchType_SEARCH_PAGE') and text:
            lst = [p for p in lst if text in str(p['code']) or text.lower() in p.get('title', '').lower() or text == str(p.get('player_label'))]
        if st in ('PhotoSearchType_TODAY', 'PhotoSearchType_TOTAL'):
            lst.sort(key=lambda p: -len(p.get('likes', [])))
        else:
            lst.sort(key=lambda p: -p.get('time', 0))
        a, b = req.get('startIndex', 0), req.get('endIndex', 0) or 20
        page = lst[a:b + 1]
        ctx.reply({'status': OK, 'photos': [preview(ctx, p) for p in page], 'totalNum': len(lst), 'endIndex': a + len(page),
                   'todayUploadLimit': 10, 'uploadMaxNum': 50})
    H['PhotoShareSearchReq'] = search

    def get_detail(ctx, req):
        ph = idx()['photos'].get(str(req.get('code')))
        if not ph:
            return ctx.reply({'status': FAIL})
        ctx.reply({'status': OK, 'info': detail(ctx, ph)})
    H['PhotoShareDetailReq'] = get_detail

    def operate(ctx, req):
        me = str(ctx.p.s['player_id'])
        op = req.get('operate_type')
        with _lock:
            x = idx()
            ph = x['photos'].get(str(req.get('code')))
            if not ph:
                return ctx.reply({'status': FAIL})
            for name, key in (('LIKE', 'likes'), ('FAVORITE', 'fav')):
                if op == 'PhotoOperateType_%s' % name and me not in ph[key]:
                    ph[key].append(me)
                if op == 'PhotoOperateType_%s_CANCEL' % name and me in ph[key]:
                    ph[key].remove(me)
            if op == 'PhotoOperateType_DEL' and ph['player_id'] == ctx.p.s['player_id']:
                x['photos'].pop(str(ph['code']))
            save_idx(x)
        ctx.reply({'status': OK, 'code': str(req.get('code'))})
    H['OperatePhotoShareReq'] = operate

    def retitle(ctx, req):
        with _lock:
            x = idx()
            ph = x['photos'].get(str(req.get('code')))
            if ph and ph['player_id'] == ctx.p.s['player_id']:
                ph.update(title=req.get('title', ''), tag1=req.get('tag1', ''), tag2=req.get('tag2', ''))
                save_idx(x)
        ctx.reply({'status': OK, 'title': req.get('title', ''), 'tag1': req.get('tag1', ''), 'tag2': req.get('tag2', '')})
    H['ChangePhotoShareTitleReq'] = retitle

    # ---------------------------------------------------------------- rankings (everyone on this server)
    def all_players(ctx):
        out = []
        for pid in ctx.server.all_player_ids():
            o = ctx.server.player_by_id(pid)
            if o:
                out.append(o)
        return out

    def abyss_best(o, sid):
        dg = o.s.get('events', {}).get('abyss', {}).get(str(sid), {})
        times = [v.get('finishTime', 0) for v in dg.values() if isinstance(v, dict) and v.get('finishTime')]
        return sum(times), dg

    def abyss_friends(ctx, req):
        sid = req.get('seasonId')
        rows = []
        for o in all_players(ctx):
            tot, dg = abyss_best(o, sid)
            if tot:
                rows.append((tot, {'playerInfo': brief(ctx.server, o.s['player_id']), 'abyssInfo': {'seasonId': sid, 'dungeonInfo': dg}}))
        ctx.reply({'status': OK, 'rankList': [r for _, r in sorted(rows, key=lambda x: x[0])]})
    H['AbyssFriendRankReq'] = abyss_friends

    def abyss_all(ctx, req):
        sid = req.get('seasonId')
        rows = []
        for o in all_players(ctx):
            tot, _ = abyss_best(o, sid)
            if tot:
                rows.append({'seasonId': sid, 'totalTime': tot, 'playerInfo': brief(ctx.server, o.s['player_id'])})
        ctx.reply({'status': OK, 'rankList': sorted(rows, key=lambda r: r['totalTime'])[:100]})
    H['AbyssAllServerRankReq'] = abyss_all

    def bossrush_friends(ctx, req):
        sid = req.get('season_id')
        rows = []
        for o in all_players(ctx):
            best = o.s.get('misc', {}).get('bossrush', {}).get(str(sid), {}).get('best', 0)
            if best:
                rows.append({'player_info': brief(ctx.server, o.s['player_id']),
                             'rank_info': {'player_id': o.s['player_id'], 'score': str(best), 'rank_ratio': 0}})
        rows.sort(key=lambda r: -int(r['rank_info']['score']))
        for i, r in enumerate(rows):
            r['rank_info']['rank_ratio'] = int(100 * (i + 1) / len(rows))
        ctx.reply({'status': OK, 'season_id': sid, 'rank_info': rows})
    H['BossRushFriendRankReq'] = bossrush_friends

    def bossrush_detail(ctx, req):
        o = ctx.server.player_by_id(req.get('player_id'))
        out = []
        if o:
            for sid, st in o.s.get('misc', {}).get('bossrush', {}).items():
                out.append({'season_id': int(sid), 'stages': list(st.get('stages', {}).values())})
        ctx.reply({'status': OK, 'player_id': req.get('player_id'), 'details': out})
    H['BossRushFriendDetailReq'] = bossrush_detail

    # ---------------------------------------------------------------- restaurant mini-game (merge coffee / cakes)
    def rg_cfg(d, aid):
        def first(sheet):
            t = d.table('restaurantgame', sheet)
            return t.get(aid) or next(iter(t.values()), {})
        return first('RestaurantGameFood'), first('RestaurantDeskBag'), first('RestaurantGameQuest')

    def rg(p, aid):
        st = p.s.setdefault('misc', {}).setdefault('restaurant', {}).setdefault(str(aid), {})
        if 'grid' not in st:
            st.update(grid={}, dungeon=None, quests={}, served=0)
        return st

    def foods(d, aid):
        return {f['FoodID']: f for f in rg_cfg(d, aid)[0].get('RestaurantGameFoodGroupInfo', [])}

    def dungeon_for(d, aid, st):
        rows = sorted((r for r in d.table('restaurantgame', 'RestaurantDungeon').values() if r.get('ActivityID') == aid),
                      key=lambda r: r['ID'])
        if not rows:
            rows = sorted(d.table('restaurantgame', 'RestaurantDungeon').values(), key=lambda r: r['ID'])
        cleared = st.setdefault('cleared', [])
        row = next((r for r in rows if r['ID'] not in cleared), rows[-1])
        fd = foods(d, aid)
        cust = []
        for i, g in enumerate(row.get('RestaurantDungeonGroupInfo', []), 1):
            cand = [f['FoodID'] for f in fd.values() if f.get('FoodType') == g.get('FoodType') and f.get('FoodLevel') == g.get('FoodLevel')]
            cust.append({'customer_index': i, 'food': random.choice(cand) if cand else 1, 'status': False})
        return {'dungeon_id': row['ID'], 'customer_list': cust}

    def grid_list(d, aid, st):
        bags = rg_cfg(d, aid)[1].get('RestaurantDeskBagGroupInfo', [])
        cleared = st.get('cleared', [])
        out = []
        for b in bags:
            unlocked = not b.get('UnlockDungonID') or b['UnlockDungonID'] in cleared or b['UnlockDungonID'] in [x - 0 for x in cleared]
            out.append({'index': b['BagID'], 'food': st['grid'].get(str(b['BagID']), 0), 'isUnLock': bool(unlocked)})
        return out

    def rg_info(ctx, req):
        p, d = ctx.p, ctx.d
        aid = req.get('activity_id', 12000)
        st = rg(p, aid)
        if not st['dungeon']:
            st['dungeon'] = dungeon_for(d, aid, st)
        p.dirty = True
        ctx.reply({'status': OK, 'activity_id': aid, 'grid_list': grid_list(d, aid, st), 'dungeon_info': st['dungeon']})
    H['RestaurantGameInfoReq'] = rg_info

    def rg_operate(ctx, req):
        p, d = ctx.p, ctx.d
        aid = req.get('activity_id', 12000)
        st = rg(p, aid)
        fd = foods(d, aid)
        op, grids = req.get('type'), req.get('grid', [])
        free = [g['index'] for g in grid_list(d, aid, st) if g['isUnLock'] and not g['food']]
        items, changed, touched = [], [], []
        if op == 'RestaurantGameOperateType_Buy':
            pool = d.row('restaurantgame', 'RestaurantRandomPool', req.get('buy_pool_id')) or \
                next((r for r in d.table('restaurantgame', 'RestaurantRandomPool').values() if r.get('ActivityID') == aid), {})
            cost = pool.get('RateMin', 3)
            if not free or p.count(1601) < cost:
                return ctx.reply({'status': FAIL})
            paid = p.pay([(1601, cost)])
            food = random.choice([x['FoodId'] for x in pool.get('RestaurantRandomPoolGroupInfo', [])] or [1])
            st['grid'][str(free[0])] = food
            touched.append(free[0])
            changed += paid or []
        elif op == 'RestaurantGameOperateType_Mix' and len(grids) >= 2:
            a, b = str(grids[0]), str(grids[1])
            fa, fb = st['grid'].get(a, 0), st['grid'].get(b, 0)
            if not fa or fa != fb or not fd.get(fa, {}).get('SyntheticTarget'):
                return ctx.reply({'status': FAIL})
            st['grid'][a] = 0
            st['grid'][b] = fd[fa]['SyntheticTarget']
            touched += [int(a), int(b)]
        elif op == 'RestaurantGameOperateType_Recycle' and grids:
            g = str(grids[0])
            f = fd.get(st['grid'].get(g, 0))
            if not f:
                return ctx.reply({'status': FAIL})
            st['grid'][g] = 0
            got, ch = p.add_items([(1601, random.randint(f.get('RecyclingPriceMin', 1), f.get('RecyclingPriceMax', 1)))])
            items += got
            changed += ch
            touched.append(int(g))
        else:
            return ctx.reply({'status': FAIL})
        p.dirty = True
        gl = {g['index']: g for g in grid_list(d, aid, st)}
        ctx.reply({'status': OK, 'activity_id': aid, 'grid': [gl[i] for i in touched if i in gl], 'itemDetails': items})
        if changed:
            pack(ctx, changed)
    H['RestaurantGameOperateReq'] = rg_operate

    def rg_eat(ctx, req):
        p, d = ctx.p, ctx.d
        aid = req.get('activity_id', 12000)
        st = rg(p, aid)
        dg = st.get('dungeon') or dungeon_for(d, aid, st)
        g = str(req.get('grid', 0))
        cust = next((c for c in dg['customer_list'] if c['customer_index'] == req.get('customer_index')), None)
        if not cust or cust.get('status') or st['grid'].get(g, 0) != cust['food']:
            return ctx.reply({'status': FAIL})
        st['grid'][g] = 0
        cust['status'] = True
        if all(c.get('status') for c in dg['customer_list']):
            st.setdefault('cleared', []).append(dg['dungeon_id'])
            st['dungeon'] = dungeon_for(d, aid, st)
        else:
            st['dungeon'] = dg
        p.dirty = True
        gl = {x['index']: x for x in grid_list(d, aid, st)}
        ctx.reply({'status': OK, 'customer_index': req.get('customer_index'), 'grid': [gl.get(int(g), {'index': int(g)})],
                   'dungeon_info': st['dungeon'], 'activity_id': aid})
    H['RestaurantGameEatReq'] = rg_eat

    def rg_quest(ctx, req):
        p, d = ctx.p, ctx.d
        aid = req.get('activity_id', 12000)
        st = rg(p, aid)
        q = next((x for x in rg_cfg(d, aid)[2].get('RestaurantGameQuestGroupInfo', []) if x.get('GameQuestID') == req.get('quest_id')), None)
        if not q or str(q['GameQuestID']) in st['quests'] or q.get('Param') not in st.get('cleared', []):
            return ctx.reply({'status': FAIL})
        st['quests'][str(q['GameQuestID'])] = True
        got, changed = p.add_items([(q.get('GameCoinID', 1601), q.get('GameCoin', 100)), (q.get('GameIntegralItem', 1600), q.get('GameIntegral', 1))])
        p.dirty = True
        ctx.reply({'status': OK, 'quest': {'quest_id': q['GameQuestID'], 'status': 'QuestStatus_Finish'}, 'itemDetails': got, 'activity_id': aid})
        pack(ctx, changed)
    H['RestaurantGameQuestRewardReq'] = rg_quest
