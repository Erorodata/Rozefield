"""Game Hall co-op games (Pop Balloons / Attack Balloon and Aerial Adventure / Floating Platform), modelled on the
official 2026-11-25 01:13 capture (5 players, 2 platform rounds, 1 balloon round).

Official flow:
  MPTeamGameModeChangeReq (mode 1001 balloon / 1002 platform) -> MPBeaconActionReq MOVE / PLACE / CALL_IN
  (the beacon shows in the plaza; members walk in) -> MPBeaconCanStartNotice -> MPGameStartReq (costs 1 x item 117)
  -> MPRoomEnterNotice (room layout + gameplay id) -> MPPlayRoomReadyReq -> event 1 (countdown) -> event 2 (start)
  -> MPPlayRoomEventReq / MPPlayRoomEventNotice (the server echoes every step to everyone, 5 times a second)
  -> event 3 (a player reached the top, with time) -> MPPlayRoomSettlementNotice (ranking, 150 x item 121)

Rozefield runs it for the players who are on this server. Official needs at least 3 players; here a team can start
alone, so the games are playable solo.

Room events seen:
  platform: client 5/6/7/8 <row> (stepping on a platform). The server echoes it and adds
            5 k -> 9 k, 6 k -> 11 k, 7 k -> 9 k+1, 8 k -> 11 k+1; reaching the last row ends that player's run
  balloon : client 4 <balloon> -> echoed with the player id; the round lasts about 46 seconds
"""
import asyncio
import random
import time

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
TICKET, COIN = 117, 121
MODES = {1001: 'EMultiplayerPlayMode_DestroyObject', 1002: 'EMultiplayerPlayMode_MagicPlatform'}
# gameplay id -> number of platform rows (seen on official); balloon layout 10010108 has balloons 1..84
PLATFORM_ROWS = {10020108: 17, 10020105: 10}
BALLOON_LAYOUTS = {10010108: 84}
BALLOON_SECONDS = 46
REWARD = 150   # official: 150 x item 121 per round


def _later(delay, fn):
    try:
        asyncio.get_running_loop().call_later(delay, fn)
    except RuntimeError:
        fn()


def register(H, pack, scene_player):
    teams = {}   # team id -> team state (shared by everyone on the server)

    def team_of(ctx):
        return teams.get(ctx.p.s.get('mp_team')) if ctx.p else None

    def mode_info(t):
        return {'mode_id': t['mode'], 'sub_mode_id': t['sub'], 'game_mode': MODES.get(t['mode'], 'EMultiplayerPlayMode_DestroyObject')}

    def sessions(ctx, t):
        out = []
        for pid in t['members']:
            s = ctx.server.sessions.get(pid)
            if s and not s.w.is_closing():
                out.append(s)
        return out

    def push_all(ctx, t, name, body):
        for s in sessions(ctx, t):
            try:
                s.push(name, body)
            except Exception:
                pass

    def member_info(ctx, pid):
        s = ctx.server.sessions.get(pid)
        p = s.p if s else None
        if not p:
            return {'player_id': pid}
        ch = p.s['characters'].get(str(p.s['team'].get('char1')), {})
        return {'player_id': pid, 'player_info': {'character': ch}}

    def detail(ctx, t):
        return {'base': {'mode_info': mode_info(t), 'team_id': t['id'], 'team_name': t['name'],
                         'current_members': len(t['members']), 'max_members': 16},
                'members': {'leader': t['leader'], 'members': {str(pid): member_info(ctx, pid) for pid in t['members']}}}

    def beacon(t, ready=None):
        b = dict(t['beacon'])
        b['members'] = {str(pid): (pid in t['called'] if ready is None else ready) for pid in t['members']}
        b['mode_info'] = mode_info(t)
        return b

    def new_team(ctx, name=None, mode=1002, sub=None):
        p = ctx.p
        tid = p.s['player_id']
        t = teams.get(tid) or {'id': tid, 'leader': tid, 'members': [tid], 'called': set(), 'room': None}
        t.update(name=name or '%s\'s' % p.s['name'], mode=mode, sub=sub or mode * 100 + 1)
        t.setdefault('beacon', {'owner_id': tid, 'name': t['name'], 'status': 'MPBeaconStatus_PLACED', 'position': p.s.get('last_pos') or {},
                                'rotation': {}, 'channel_label': p.s.get('channel_label') or tid, 'scene_id': p.s.get('scene_id', 9999)})
        teams[tid] = t
        p.s['mp_team'] = tid
        return t

    # ---------------- team
    def create(ctx, req):
        t = new_team(ctx, req.get('team_name'), req.get('mode_id') or 1002, req.get('sub_mode_id'))
        ctx.reply({'status': OK, 'team_detail': detail(ctx, t)})
    H['MPTeamCreateReq'] = create

    def info(ctx, req):
        t = teams.get(req.get('team_id')) or team_of(ctx)
        if not t:
            return ctx.reply({'status': FAIL})
        ctx.reply({'status': OK, 'team_detail': detail(ctx, t)})
    H['MPTeamInfoReq'] = info

    def join(ctx, req):
        t = teams.get(req.get('team_id'))
        if not t or len(t['members']) >= 16:
            return ctx.reply({'status': FAIL})
        pid = ctx.p.s['player_id']
        if pid not in t['members']:
            t['members'].append(pid)
        ctx.p.s['mp_team'] = t['id']
        ctx.reply({'status': OK, 'team_detail': detail(ctx, t)})
        push_all(ctx, t, 'MPTeamMemberNotice', {'status': OK, 'team_id': t['id'], 'members': detail(ctx, t)['members']})
    H['MPTeamJoinReq'] = join

    def mode_change(ctx, req):
        t = team_of(ctx) or new_team(ctx)
        t['mode'], t['sub'] = req.get('mode_id', t['mode']), req.get('sub_mode_id') or req.get('mode_id', t['mode']) * 100 + 1
        ctx.reply({'status': OK, 'team_id': t['id'], 'game_mode': mode_info(t)})
    H['MPTeamGameModeChangeReq'] = mode_change

    def rename(ctx, req):
        t = team_of(ctx) or new_team(ctx)
        t['name'] = t['beacon']['name'] = req.get('new_name') or t['name']
        ctx.reply({'status': OK, 'new_name': t['name'], 'team_id': t['id']})
    H['MPTeamRenameReq'] = rename

    def leave(kind):
        def f(ctx, req):
            t = team_of(ctx)
            pid = ctx.p.s['player_id']
            tid = t['id'] if t else 0
            if t:
                if kind == 'dismiss' or pid == t['leader'] and kind == 'quit':
                    for m in t['members']:
                        s = ctx.server.sessions.get(m)
                        if s and s.p:
                            s.p.s.pop('mp_team', None)
                    teams.pop(tid, None)
                elif pid in t['members']:
                    t['members'].remove(pid)
                    ctx.p.s.pop('mp_team', None)
            r = {'status': OK}
            if kind != 'dismiss':
                r['team_id'] = tid
            ctx.reply(r)
        return f
    H['MPTeamDismissReq'] = leave('dismiss')
    H['MPTeamQuitReq'] = leave('quit')

    def kick(ctx, req):
        t = team_of(ctx)
        if t and req.get('target_id') in t['members'] and req.get('target_id') != t['leader']:
            t['members'].remove(req['target_id'])
        ctx.reply({'status': OK, 'target_id': req.get('target_id')})
    H['MPTeamKickMemberReq'] = kick
    H['MPTeamInviteReq'] = lambda ctx, req: ctx.reply({'status': OK})

    def swap(ctx, req):
        ctx.reply({'status': OK, 'new_info': member_info(ctx, ctx.p.s['player_id'])})
    H['MPSwapCharacterReq'] = swap

    # ---------------- beacon in the plaza
    def beacon_action(ctx, req):
        t = team_of(ctx) or new_team(ctx)
        act = req.get('action', 'MPBeaconAction_NONE')
        b = t['beacon']
        if act == 'MPBeaconAction_MOVE':
            b['status'] = 'MPBeaconStatus_MOVING'
            t['called'] = set()
        elif act == 'MPBeaconAction_PLACE':
            b.update(status='MPBeaconStatus_PLACED', position=req.get('position', b.get('position', {})), rotation=req.get('rotation', {}))
        elif act == 'MPBeaconAction_CALL_IN':
            b['status'] = 'MPBeaconStatus_CALLING_IN'
            t['called'] = set(t['members'])     # everyone here is ready at once
        else:
            b['status'] = 'MPBeaconStatus_PLACED'
            t['called'] = set()
        ctx.reply({'status': OK, 'beacon': beacon(t, ready=False if act != 'MPBeaconAction_CALL_IN' else None), 'team_id': t['id']})
        ctx.push('SceneMPBeaconNotice', {'status': OK, 'beacons': {str(t['id']): {k: v for k, v in beacon(t).items()
                                                                                   if k not in ('channel_label', 'scene_id')}}})
        if act == 'MPBeaconAction_CALL_IN':
            b2 = dict(beacon(t), can_start=True)
            push_all(ctx, t, 'MPTeamBeaconNotice', {'status': OK, 'beacon': b2, 'team_id': t['id']})
            push_all(ctx, t, 'MPBeaconCanStartNotice', {'status': OK, 'team_id': t['id'], 'can_start': True})
    H['MPBeaconActionReq'] = beacon_action
    H['MPBeaconPlayerReadyReq'] = lambda ctx, req: ctx.reply({'status': OK})

    # ---------------- the round
    def start(ctx, req):
        p, d = ctx.p, ctx.d
        t = team_of(ctx)
        if not t:
            return ctx.reply({'status': FAIL})
        cost = [TICKET, 1]
        mode_row = d.row('teamgameplay', 'Mode', t['mode']) or {}
        for it in mode_row.get('ModeItems', []):
            if it.get('SubModeId') == t['sub'] and it.get('RoomCost'):
                cost = it['RoomCost']
        paid = p.pay([tuple(cost)]) if p.count(cost[0]) >= cost[1] else []   # free when out of tickets (no way to refill here)
        if t['mode'] == 1002:
            gid = random.choice(list(PLATFORM_ROWS))
            room = {'magic_platform': {'show_platform_list': [PLATFORM_ROWS[gid], 1]}}
        else:
            gid = random.choice(list(BALLOON_LAYOUTS))
            objs = list(range(1, BALLOON_LAYOUTS[gid] + 1))
            random.shuffle(objs)
            room = {'destroy_object': {'remain_object_list': objs}}
        t['room'] = {'gameplay': gid, 'mode': t['mode'], 'ready': set(), 'start': 0, 'done': {}, 'count': {}, 'hit': set(),
                     'over': False, 'rows': PLATFORM_ROWS.get(gid, 0)}
        ctx.reply({'status': OK, 'team_id': t['id']})
        if paid:
            pack(ctx, paid)
        push_all(ctx, t, 'MPRoomEnterNotice', {'status': OK, 'room_info': room,
                                               'game_mode_info': dict(mode_info(t), gameplay_id=gid)})
    H['MPGameStartReq'] = start

    def ready(ctx, req):
        t = team_of(ctx)
        ctx.reply({'status': OK})
        if not t or not t.get('room'):
            return
        room = t['room']
        room['ready'].add(ctx.p.s['player_id'])
        if room.get('counting'):
            return
        room['counting'] = True
        lead = 5.4 if room['mode'] == 1002 else 1.0

        def countdown():
            push_all(ctx, t, 'MPPlayRoomEventNotice', {'status': OK, 'events': [{'event_type': 1, 'time': str(int(lead * 50))}]})

        def go():
            room['start'] = time.time()
            ev = [{'event_type': 2, 'game_start_time': str(int(room['start'] * 1000))}]
            if room['mode'] == 1002:
                ev += [{'event_type': 7, 'id': 1}, {'event_type': 9, 'id': 2}]
            push_all(ctx, t, 'MPPlayRoomEventNotice', {'status': OK, 'events': ev})
            if room['mode'] == 1001:
                _later(BALLOON_SECONDS + 2.8, lambda: settle(ctx, t))
            else:
                _later(180, lambda: settle(ctx, t))   # time limit for a platform round
        _later(0.8, countdown)
        _later(0.8 + lead, go)
    H['MPPlayRoomReadyReq'] = ready

    def events(ctx, req):
        t = team_of(ctx)
        ctx.reply({'status': OK})
        if not t or not t.get('room') or t['room']['over']:
            return
        room, pid = t['room'], ctx.p.s['player_id']
        out = []
        for e in req.get('events', []):
            et, i = e.get('event_type'), e.get('id', 0)
            if room['mode'] == 1001 and et == 4:
                if i in room['hit']:
                    continue
                room['hit'].add(i)
                room['count'][pid] = room['count'].get(pid, 0) + 1
                out.append({'event_type': 4, 'id': i, 'player_id': pid})
            elif room['mode'] == 1002 and et in (5, 6, 7, 8):
                mine = {'event_type': et, 'id': i}
                if et == 6:
                    mine['player_id'] = pid
                out.append(mine)
                out.append({5: {'event_type': 9, 'id': i}, 6: {'event_type': 11, 'id': i},
                            7: {'event_type': 9, 'id': i + 1}, 8: {'event_type': 11, 'id': i + 1}}[et])
                if i >= room['rows'] and pid not in room['done'] and room['start']:
                    ms = int((time.time() - room['start']) * 1000) // 200 * 200
                    room['done'][pid] = ms
                    out.append({'event_type': 3, 'time': str(ms), 'player_id': pid})
            else:
                out.append(dict(e, player_id=pid))
        if out:
            push_all(ctx, t, 'MPPlayRoomEventNotice', {'status': OK, 'events': out})
        if room['mode'] == 1002 and room['done'] and all(m in room['done'] for m in room['ready'] or [pid]):
            _later(0.4, lambda: settle(ctx, t))
    H['MPPlayRoomEventReq'] = events

    def settle(ctx, t):
        room = t.get('room')
        if not room or room['over']:
            return
        room['over'] = True
        took = int((time.time() - room['start']) * 1000) if room['start'] else 0
        if room['mode'] == 1002:
            ranking = [{'player_id': pid, 'time': str(ms)} for pid, ms in sorted(room['done'].items(), key=lambda x: x[1])]
            rank = {'star': 3 if room['done'] else 1, 'magic_platform': ranking}
        else:
            ranking = [{'player_id': pid, 'count': n} for pid, n in sorted(room['count'].items(), key=lambda x: -x[1])]
            rank = {'star': 3 if ranking else 1, 'destroy_object': ranking}
        for s in sessions(ctx, t):
            try:
                got, changed = s.p.add_items([(COIN, REWARD)])
                s.p.dirty = True
                s.push('MPPlayRoomSettlementNotice', {'status': OK, 'rank': rank, 'gameplayId': room['gameplay'], 'rewards': got,
                                                      'total_consume_time': str(took)})
                s.push('PackNotice', {'status': OK, 'items': changed})
            except Exception:
                pass
        t['room'] = None
        t['called'] = set()

    def exit_room(ctx, req):
        t = team_of(ctx)
        ctx.reply({'status': OK, 'team_id': t['id'] if t else 0})
    H['MPPlayRoomExitReq'] = exit_room

    def reward_info(ctx, req):
        ctx.reply({'status': OK, 'score_day_remain': 99, 'score_week_remain': 999, 'extra_bonus_day_remain': 0,
                   'extra_bonus_week_remain': 0, 'extra_mag_day_remain': 0, 'extra_mag_week_remain': 0})
    H['MPPlayRoomRewardInfoReq'] = reward_info
