"""Gameplay that only had a placeholder before (2026-11-26):

  rifts (ExploreInterval: start, quick finish, friends join, rewards)  IntervalStart/Quick/Join/Reward, Self/FriendIntervalInit
  moon spots placed in the world (shown to everyone in the channel)     PlaceMoonSpotReq -> PlaceMoonSpotNotice, SceneData.moonSpots
  voice regions collected per map                                     CollectVoiceRegionReq -> SceneData.regionVoices
  room decor (kept, shown to visitors)                                SetRoomDecorReq -> RoomDecorNotice, SceneData.roomDecorList
  pop emoji / clap / vehicle seats seen by other players              PopEmojiNotice, ClapResultNotice, SceneSitVehicleRsp
  event sandbag hits and wish text kept                               ActivitySandbagHitReq, ActivityUploadWishTxtReq

Shapes come from the game's protocol and tables; rift timings from a recorded official FriendIntervalInitRsp
(createTime -> finishTime = the rift's Time). Values the official server never showed are marked 'from the table'.
"""
import random
import time

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'


def _ms():
    return int(time.time() * 1000)


def _misc(s):
    return s.setdefault('misc', {})


# ------------------------------------------------------------------ live state per (scene, channel)
LIVE = {}   # (scene, channel) -> {'moonSpots': {instance: MoonSpotData}, 'claps': [(t, pid, movement, pos)]}


def _live(ctx):
    s = ctx.p.s
    return LIVE.setdefault((s.get('scene_id'), s.get('channel_id')), {'moonSpots': {}, 'claps': []})


def add_scene(ctx, data, owner):
    """Called by enter_scene: what this player / channel adds to SceneDataNotice."""
    s = ctx.p.s
    sid = str(data.get('sceneId'))
    voices = (_misc(s).get('voices') or {}).get(sid)
    if voices:
        data['regionVoices'] = sorted(set(data.get('regionVoices', [])) | set(voices))
    st = LIVE.get((data.get('sceneId'), data.get('channelId')))
    if st and st['moonSpots']:
        data['moonSpots'] = list(data.get('moonSpots', [])) + list(st['moonSpots'].values())
    if owner is not None and _misc(owner.s).get('room_decor'):
        data['roomDecorList'] = _misc(owner.s)['room_decor']


def _peek(server, pid):
    """Another player's save, read only (online or not)."""
    import json, os
    sess = server.sessions.get(pid)
    if sess and sess.p:
        return sess.p.s
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'save', 'accounts', f'{pid}.json')
    try:
        return json.load(open(f, encoding='utf-8'))
    except (OSError, ValueError):
        return None


def register(H, pack):
    # ---------------------------------------------------------------- rifts (exploration break)
    def rift_cfg(d, rid):
        return d.row('explore', 'ExploreInterval', rid) or {}

    def mine(p):
        return _misc(p.s).setdefault('rift', {})

    def info(owner_s, r):
        return {'intervalId': r['id'], 'finishTime': str(r['finish']), 'playerId': owner_s['player_id'],
                'createTime': str(r['create']), 'member': [dict(m) for m in r.get('members', [])]}

    def member_of(s):
        return {'playerId': s['player_id'], 'nickName': s['name'], 'head': s.get('head', 0), 'joinTime': str(_ms())}

    def self_init(ctx, req):
        r = mine(ctx.p)
        if not r:
            return ctx.reply({'status': OK})
        ctx.reply({'status': OK, 'intervalId': r['id'], 'endTime': str(r['finish']), 'isStart': True,
                   'interval': info(ctx.p.s, r)})
    H['SelfIntervalInitReq'] = self_init

    def friend_init(ctx, req):
        p = ctx.p
        out, joined = [], []
        now = _ms()
        for fid in list((p.s.get('social') or {}).get('friends', {})):
            st = _peek(ctx.server, int(fid))
            r = (_misc(st).get('rift') if st else None) or {}
            if not r or now > r['finish'] + rift_cfg(ctx.d, r['id']).get('RetentionTime', 172800) * 1000:
                continue
            e = info(st, r)
            (joined if any(m['playerId'] == p.s['player_id'] for m in r.get('members', [])) else out).append(e)
        ctx.reply({'status': OK, 'friendInfos': out, 'joinInfos': joined})
    H['FriendIntervalInitReq'] = friend_init

    def start(ctx, req):
        p, d = ctx.p, ctx.d
        r = mine(p)
        if r and not r.get('rewarded'):
            return ctx.reply({'status': FAIL})
        rows = list(d.table('explore', 'ExploreInterval').values())
        if not rows:
            return ctx.reply({'status': FAIL})
        cfg = random.choice(rows)                      # which rift opens: Torii / Shopping Street / Izakaya
        now = _ms()
        p.s['misc']['rift'] = r = {'id': cfg['ID'], 'create': now, 'finish': now + cfg.get('Time', 14400) * 1000,
                                   'members': [member_of(p.s)]}   # official lists the captain as the first member
        p.dirty = True
        ctx.reply({'status': OK, 'exploreId': r['id'], 'finishTime': str(r['finish'])})
    H['IntervalStartReq'] = start

    def quick(ctx, req):
        p = ctx.p
        r = mine(p)
        if not r or r.get('rewarded'):
            return ctx.reply({'status': FAIL})
        cfg = rift_cfg(ctx.d, r['id'])
        paid = p.pay([(cfg.get('QuickNeedItem', 102), cfg.get('QuickNeedItemCount', 10))])
        if paid is None:
            return ctx.reply({'status': FAIL})
        r['finish'] = _ms()
        p.dirty = True
        ctx.reply({'status': OK, 'exploreId': r['id'], 'finishTime': str(r['finish'])})
        pack(ctx, paid)
    H['IntervalQuickReq'] = quick

    def join(ctx, req):
        from game.friends import edit
        p = ctx.p
        fid = int(req.get('friendId') or 0)
        if not fid or str(fid) not in (p.s.get('social') or {}).get('friends', {}):
            return ctx.reply({'status': FAIL})
        res = {}

        def add(st):
            r = _misc(st).get('rift') or {}
            if not r or _ms() >= r['finish'] or r.get('rewarded'):
                return
            if not any(m['playerId'] == p.s['player_id'] for m in r['members']):
                r['members'].append(member_of(p.s))
            res.update(id=r['id'], finish=r['finish'])
        edit(ctx.server, fid, add)
        if not res:
            return ctx.reply({'status': FAIL})
        ctx.reply({'status': OK, 'friendId': str(fid), 'exploreId': res['id'], 'finishTime': str(res['finish'])})
    H['IntervalJoinReq'] = join

    def reward(ctx, req):
        from game.friends import edit
        p, d = ctx.p, ctx.d
        fid = int(req.get('friendId') or 0)
        res = {}
        if not fid or fid == p.s['player_id']:          # captain: own rift, once it has finished
            r = mine(p)
            if not r or r.get('rewarded') or _ms() < r['finish']:
                return ctx.reply({'status': FAIL})
            r['rewarded'] = True
            res.update(id=r['id'], captain=True)
        else:                                          # member: a friend's rift you joined
            def take(st):
                r = _misc(st).get('rift') or {}
                m = next((m for m in r.get('members', []) if m['playerId'] == p.s['player_id']), None)
                if m and not m.get('isReward') and _ms() >= r['finish']:
                    m['isReward'] = True
                    res.update(id=r['id'], captain=False)
            edit(ctx.server, fid, take)
            if not res:
                return ctx.reply({'status': FAIL})
        cfg = rift_cfg(d, res['id'])
        n = cfg.get('CaptainCount' if res['captain'] else 'MemberCount', 10)   # from the table (ExploreInterval)
        got, changed = p.add_items([(cfg.get('NeedItemID', 10), n)])
        p.dirty = True
        ctx.reply({'status': OK, 'friendId': fid, 'exploreId': res['id'], 'rewards': got})
        pack(ctx, changed)
    H['IntervalRewardReq'] = reward

    # ---------------------------------------------------------------- moon spots, voice regions, room decor
    def moon_spot(ctx, req):
        st = _live(ctx)['moonSpots']
        op, data = req.get('operate'), dict(req.get('data') or {})
        if op == 'OperateType_Place':
            data['instance_id'] = data.get('instance_id') or (max([int(k) for k in st] or [0]) + 1)
            data['create_time'] = str(_ms())
            st[str(data['instance_id'])] = data
        elif op == 'OperateType_Move' and str(data.get('instance_id')) in st:
            st[str(data['instance_id'])].update({k: v for k, v in data.items() if k in ('pos', 'rot')})
            data = st[str(data['instance_id'])]
        elif op == 'OperateType_Remove':
            data = st.pop(str(data.get('instance_id')), data)
        else:
            return ctx.reply({'status': FAIL})
        ctx.reply({'status': OK})
        ctx.server.broadcast(ctx, 'PlaceMoonSpotNotice', {'status': OK, 'operate': op, 'data': data,
                                                          'player_id': ctx.p.s['player_id']})
    H['PlaceMoonSpotReq'] = moon_spot

    def voice(ctx, req):
        s = ctx.p.s
        vid = req.get('voiceId')
        lst = _misc(s).setdefault('voices', {}).setdefault(str(s.get('scene_id')), [])
        if vid and vid not in lst:
            lst.append(vid)
            ctx.p.dirty = True
        ctx.reply({'status': OK, 'voiceId': vid})
    H['CollectVoiceRegionReq'] = voice

    def room_decor(ctx, req):
        p = ctx.p
        lst = [dict(x) for x in req.get('decor_list', [])]
        _misc(p.s)['room_decor'] = lst
        p.dirty = True
        ctx.reply({'status': OK})
        ctx.server.broadcast(ctx, 'RoomDecorNotice', {'status': OK, 'decor_list': lst}, include_self=False)
    H['SetRoomDecorReq'] = room_decor

    # ---------------------------------------------------------------- seen by other players
    def pop_emoji(ctx, req):
        ctx.reply({'status': OK})
        ctx.server.broadcast(ctx, 'PopEmojiNotice', {'status': OK, 'emojiId': req.get('emojiId', 0),
                                                     'fromPlayerId': ctx.p.s['player_id']}, include_self=False)
    H['PopEmojiReq'] = pop_emoji

    def clap(ctx, req):
        """Two players clapping the same move near each other at the same time are matched (high five)."""
        mid, me = req.get('movementId', 0), ctx.p.s['player_id']
        ctx.reply({'status': OK, 'movementId': mid, 'isCancel': req.get('isCancel', False)})
        live = _live(ctx)
        now = time.time()
        live['claps'] = [c for c in live['claps'] if now - c[0] < 5 and c[1] != me]
        if req.get('isCancel'):
            return
        pos = req.get('position') or {}

        def near(a, b):
            return sum((float(a.get(k, 0)) - float(b.get(k, 0))) ** 2 for k in 'xyz') <= 400 ** 2
        other = next((c for c in live['claps'] if c[2] == mid and near(c[3], pos)), None)
        if other:
            live['claps'].remove(other)
            body = {'status': OK, 'matchedPlayerIdLst': [other[1], me], 'movementId': mid}
            for sess in list(ctx.server.channels.get(getattr(ctx, 'chan', None), ())):
                if sess.p and sess.p.s['player_id'] in (other[1], me):
                    sess.push('ClapResultNotice', body)
        else:
            live['claps'].append((now, me, mid, pos))
    H['ClapReq'] = clap

    def sit_vehicle(ctx, req):
        r = {'status': OK, 'playerId': ctx.p.s['player_id'], 'chairId': req.get('chairId', 0),
             'seatId': req.get('seatId', 0), 'isSit': req.get('isSit', False)}
        ctx.reply(r)
        ctx.server.broadcast(ctx, 'SceneSitVehicleRsp', r, include_self=False)   # same as chairs: others get the answer
    H['SceneSitVehicleReq'] = sit_vehicle

    # ---------------------------------------------------------------- events
    def sandbag_hit(ctx, req):
        p = ctx.p
        aid = req.get('activity_id', 0)
        st = _misc(p.s).setdefault('sandbag', {}).setdefault(str(aid), {'hits': 0})
        st['hits'] += max(0, int(req.get('hit_count', 0) or 0))
        p.dirty = True
        ctx.reply({'status': OK, 'activity_id': aid, 'npc_id': req.get('npc_id', 0), 'hit_count': req.get('hit_count', 0)})
    H['ActivitySandbagHitReq'] = sandbag_hit

    def wish_txt(ctx, req):
        p = ctx.p
        _misc(p.s).setdefault('wish_txt', {})[str(req.get('activity_id', 0))] = str(req.get('txt', ''))[:200]
        p.dirty = True
        ctx.reply({'status': OK, 'txt': req.get('txt', ''), 'activity_id': req.get('activity_id', 0)})
    H['ActivityUploadWishTxtReq'] = wish_txt
