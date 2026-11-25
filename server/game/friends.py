"""Real friend lists.

State per player (p.s['social']):
  friends   {pid: {'since': t, 'alias': str}}      both sides hold the entry
  apply     {pid: t}                                requests waiting for this player
  black     [pid]
  profiles  {pid: PlayerBriefInfo}                  friends' official profiles from the player's backup
Imported players get their official friend list (FriendRsp in the backup). Friends who have not imported yet show
greyed out (offline) from those saved profiles and link up by themselves when they import, because imported accounts
keep their official ids. Players met nearby this session are listed too, until the game closes (they live on the
session, never in the save). No friend limit on Rozefield.
"""
import json
import os
import time

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'


def S(st):
    soc = st.setdefault('social', {})
    for k, v in (('friends', {}), ('apply', {}), ('black', []), ('profiles', {})):
        soc.setdefault(k, v)
    return soc


def edit(server, pid, fn):
    """Change another player's save, online or not."""
    if pid in server.sessions:
        p = server.sessions[pid].p
        fn(p.s); p.dirty = True
        return True
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'save', 'accounts', f'{pid}.json')
    if not os.path.exists(path):
        return False
    st = json.load(open(path, encoding='utf-8'))
    fn(st)
    json.dump(st, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    return True


def brief(server, pid, st=None):
    st = st or (server.player_by_id(pid).s if server.player_by_id(pid) else None)
    if not st:
        return None
    last = st.get('last_login', 0) * 1000
    return {'playerId': pid, 'nickName': st['name'], 'level': st['level'], 'head': st['head'], 'sign': st.get('sign', ''),
            'createTime': st.get('create_time', 0), 'playerLabel': st.get('player_label', pid),
            'isOnline': server.is_online(pid), 'account_type': 16666, 'lastLoginTime': str(last),
            'phoneBackground': st.get('phone_background', 0), 'phone_case': st.get('phone_case', 0),
            'birthday': st.get('birthday', '')}


def import_friends(st, answers):
    """From a backup's FriendReq answers (official_answers['FriendReq'])."""
    soc = S(st)
    now = int(time.time())
    for key, rsp in (answers or {}).items():
        t = json.loads(key).get('type', '')
        for e in rsp.get('info', []) or []:
            info = e.get('info') or {}
            pid = info.get('playerId')
            if not pid:
                continue
            soc['profiles'][str(pid)] = dict(info, isOnline=False)
            if e.get('friend_intimacy'):   # friendship points (hearts), shared by both friends
                st.setdefault('events', {}).setdefault('intimacy', {})[str(pid)] = e['friend_intimacy']
            if t == 'FriendListType_FRIEND':
                soc['friends'][str(pid)] = {'since': now, 'alias': e.get('alias', '')}
            elif t == 'FriendListType_APPLY':
                soc['apply'][str(pid)] = now
            elif t == 'FriendListType_BLACK' and pid not in soc['black']:
                soc['black'].append(pid)
    return soc


def register(H, pack):
    def entry(ctx, pid, f=None):
        b = brief(ctx.server, pid)
        if b is None:   # not on this server yet: their saved official profile, offline (greyed out)
            b = S(ctx.p.s)['profiles'].get(str(pid))
            if not b:
                return None
            b = dict(b, isOnline=False)
        e = {'info': b}
        if f and f.get('alias'):
            e['alias'] = f['alias']
        return e

    def friend_list(ctx, req):
        t = req.get('type', 'FriendListType_FRIEND')
        soc = S(ctx.p.s); out = []
        if t == 'FriendListType_APPLY':
            out = [x for x in (entry(ctx, int(pid)) for pid in soc['apply']) if x]
        elif t == 'FriendListType_BLACK':
            out = [x for x in (entry(ctx, int(pid)) for pid in soc['black']) if x]
        else:
            out = [x for x in (entry(ctx, int(pid), f) for pid, f in soc['friends'].items()) if x]
            me = ctx.p.s['player_id']
            for pid in list(getattr(ctx, 'nearby', ())):   # met this session, gone when the game closes
                if str(pid) not in soc['friends'] and pid != me and pid not in soc['black']:
                    b = brief(ctx.server, pid)
                    if b:
                        out.append({'info': b, 'alias': '(nearby) ' + b['nickName']})
        ctx.reply({'status': OK, 'info': out})
    H['FriendReq'] = friend_list

    def notice(ctx, pid, typ, about):
        s = ctx.server.sessions.get(pid)
        if s:
            try:
                s.push('FriendHandleNotice', {'status': OK, 'type': typ, 'targetPlayerId': about})
            except Exception:
                pass

    def befriend(ctx, a, b):
        now = int(time.time())
        edit(ctx.server, a, lambda st: (S(st)['friends'].setdefault(str(b), {'since': now, 'alias': ''}), S(st)['apply'].pop(str(b), None)))
        edit(ctx.server, b, lambda st: (S(st)['friends'].setdefault(str(a), {'since': now, 'alias': ''}), S(st)['apply'].pop(str(a), None)))

    def add(ctx, req):
        me, pid = ctx.p.s['player_id'], req.get('player_id', 0)
        if not pid or pid == me or ctx.server.player_by_id(pid) is None:
            return ctx.reply({'status': FAIL})
        tgt = ctx.server.player_by_id(pid)
        if me in S(tgt.s)['black']:
            return ctx.reply({'status': FAIL})
        if str(pid) in S(ctx.p.s)['apply']:   # they asked first: friends now
            befriend(ctx, me, pid); notice(ctx, pid, 'FriendHandleType_ADD', me)
        else:
            edit(ctx.server, pid, lambda st: S(st)['apply'].__setitem__(str(me), int(time.time())))
            notice(ctx, pid, 'FriendHandleType_APPLY', me)
        ctx.reply({'status': OK})
    H['FriendAddReq'] = add

    def handle(ctx, req):
        me, pid = ctx.p.s['player_id'], req.get('player_id', 0)
        soc = S(ctx.p.s)
        if req.get('isAgree'):
            befriend(ctx, me, pid); notice(ctx, pid, 'FriendHandleType_ADD', me)
        else:
            soc['apply'].pop(str(pid), None); ctx.p.dirty = True
        ctx.reply({'status': OK})
    H['FriendHandleReq'] = handle

    def delete(ctx, req):
        me, pid = ctx.p.s['player_id'], req.get('player_id', 0)
        S(ctx.p.s)['friends'].pop(str(pid), None); ctx.p.dirty = True
        edit(ctx.server, pid, lambda st: S(st)['friends'].pop(str(me), None))
        notice(ctx, pid, 'FriendHandleType_DEL', me)
        ctx.reply({'status': OK})
    H['FriendDelReq'] = delete

    def black(ctx, req):
        me, pid = ctx.p.s['player_id'], req.get('player_id', 0)
        soc = S(ctx.p.s)
        if req.get('isRemove'):
            if pid in soc['black']:
                soc['black'].remove(pid)
        else:
            if pid not in soc['black']:
                soc['black'].append(pid)
            soc['friends'].pop(str(pid), None); soc['apply'].pop(str(pid), None)
            edit(ctx.server, pid, lambda st: S(st)['friends'].pop(str(me), None))
        ctx.p.dirty = True
        ctx.reply({'status': OK})
    H['FriendBlackReq'] = black

    def ext(ctx, req):   # friend alias (remark name)
        pid, data = str(req.get('playerId', 0)), req.get('data') or {}
        f = S(ctx.p.s)['friends'].get(pid)
        if f is not None and 'value' in data:
            f['alias'] = data['value']; ctx.p.dirty = True
        ctx.reply({'status': OK})
    H['SetFriendExtInfoReq'] = ext

    def search(ctx, req):
        q = (req.get('searchArgs') or '').strip().lower()
        soc = S(ctx.p.s)
        for pid in ctx.server.all_player_ids():
            if pid == ctx.p.s['player_id']:
                continue
            o = ctx.server.player_by_id(pid)
            if o and q in (str(o.s.get('player_label')), str(pid), o.s['name'].lower()):
                st = ('FriendStatus_FRIEND' if str(pid) in soc['friends'] else 'FriendStatus_BLACK' if pid in soc['black']
                      else 'FriendStatus_APPLY' if str(ctx.p.s['player_id']) in S(o.s)['apply'] else 'FriendStatus_NONE')
                return ctx.reply({'status': OK, 'data': brief(ctx.server, pid, o.s), 'friendStatus': st})
        ctx.reply({'status': FAIL})
    H['FriendSearchReq'] = search
