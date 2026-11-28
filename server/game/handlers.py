"""Request handlers. Each handler: def on_<ReqName>(ctx, req) where req is a dict and ctx is the Session.

ctx.p        -> Player (state in ctx.p.s)
ctx.reply(dict)          -> response to the current request (Rsp type inferred)
ctx.push(name, dict)     -> server push (notice)
ctx.d        -> Data tables
"""
import random, time
from game import quests as Q
from game import chatlog

H = {}


def _world_mod():
    from game import world
    return world


def _life_mod():
    from game import life
    return life


def handler(name):
    def deco(f):
        H[name] = f
        return f
    return deco


OK = 'StatusCode_OK'
GARDEN_LIMIT = 500000  # ornament placement points (official: 150000)
FAIL = 'StatusCode_FAIL'


def now_ms():
    return int(time.time() * 1000)


def pack(ctx, items):
    if items:
        ctx.push('PackNotice', {'status': OK, 'items': items})


# ============================================================ login
@handler('VerifyLoginTokenReq')
def verify(ctx, req):
    ctx.login(req.get('sdkUid') or '0', ctx.server.pending_names.get(req.get('sdkUid', ''), None))
    ctx.reply({'status': OK, 'user_id': ctx.p.s['player_id'], 'account_type': req.get('account_type', 16666),
               'sdkUid': req.get('sdkUid'), 'is_server_open': True, 'time_left': 4294967295,
               'device_uuid': req.get('device_uuid', '')})


@handler('PlayerLoginReq')
def login(ctx, req):
    s = ctx.p.s
    if s['scene_id'] != TUTORIAL_SCENE and not req.get('is_reconnect'):
        # every login starts in your own Rota Garden Plaza (official), not on the map where you logged out
        s['scene_id'], s['channel_id'], s['channel_label'] = PUBLIC_SCENE, s['player_id'], s['player_label']
        set_pos(s, dict(PLAZA_SPAWN))   # official: every fresh login starts at the Rota Plaza spawn point
    ctx.reply({'status': OK, 'server_time_ms': str(now_ms()), 'region_name': 'rozefield_local',
               'register_time': s['create_time'], 'analysis_account_id': str(s['player_id']),
               'server_time_zone': 28800, 'player_name': s['name'], 'scene_id': s['scene_id'],
               'channel_id': s['channel_id'] or s['player_id'],
               **({'is_reconnect': True, 'reconnect_success': _can_resume(ctx)} if req.get('is_reconnect') else {})})


def _can_resume(ctx):
    """A game reconnecting after a network blip resumes; after a server restart (nothing kept in memory) it is told
    the session is gone, so it goes back to the login screen instead of hanging."""
    seen = ctx.server.__dict__.setdefault('seen_players', set())
    return ctx.p.s['player_id'] in seen


@handler('PlayerMainDataReq')
def main_data(ctx, req):
    p = ctx.p
    ctx.server.__dict__.setdefault('seen_players', set()).add(p.s['player_id'])
    Q.login(p)
    _life_mod().daily_energy(p)
    ctx.reply(p.main_data())
    p.s['last_login'] = int(time.time())
    ctx.push('PackNotice', {'status': OK, 'items': p.pack_items()})
    ctx.push('ShopInitNotice', {'status': OK})
    buffs = buff_list(p)
    if buffs:
        ctx.push('PlayerBuffNotice', {'status': OK, 'player_buffs': buffs})
    # the official login notices, in the official order. The client finishes its login set-up (achievement
    # groups, exploration, handbook, collected items, ...) only after receiving these.
    un = p.s.get('unlocks', {})
    ev = p.s.get('events', {})
    ctx.push('ChatUnLockExpressionNotice', {'status': OK, 'expressionId': un.get('expressions', [])})
    ctx.push('PrivateChatOfflineNotice', {'status': OK})
    ctx.push('AchieveActionUnLockNotice', {'status': OK, 'actionIdLst': un.get('actions', []),
                                           'studyAction': un.get('study_actions', {})})
    for f in LOGIN_HOOKS:          # events: sign-in, pass, gashapon, wishing tree, daily tasks, gifts
        try:
            f(ctx)
        except Exception:
            import logging
            logging.getLogger('rozefield').exception('login notices')
    for n in ('ActivityRecallNotice', 'ActivitySandbagNotice', 'ActivityKoiNotice'):
        ctx.push(n, {'status': OK})
    ctx.push('ActivityQuestDataNotice', {'status': OK, 'info': ev.get('activity_quest', [])})
    ctx.push('ActivityRegularDataNotice', {'status': OK, 'info': ev.get('activity_regular', [])})
    ctx.push('AbyssServerRankNotice', {'status': OK})
    ctx.push('PetWarehouseLimitNotice', {'status': OK, 'warehouse_limit': p.s.get('pet_warehouse_limit', 100)})
    ctx.push('ModuleCloseNotice', {'status': OK})
    ctx.push('GMRecommendChannelNotice', {'status': OK})
    ctx.push('ChatMsgRecordInitNotice', {'status': OK, 'type': 'ChatChannel_ChatRoom', 'msg': chatlog.world()})
    enter_scene(ctx, p.s['scene_id'], label=p.s.get('channel_label'))   # also sends the channel's chat history
    p.save()


LOGIN_HOOKS = []          # f(ctx) run during PlayerMainDataReq, before the scene (game/events.py adds its notices)
import collections as _collections
WORLD_CHAT = _collections.deque(maxlen=50)   # recent world chat, sent to players as they log in


@handler('PlayerPingReq')
def ping(ctx, req):
    ctx.reply({'status': OK, 'client_time_ms': str(req.get('client_time_ms', 0)), 'server_time_ms': str(now_ms())})


@handler('PlayerSceneRecordReq')
def scene_record(ctx, req):
    pos = req.get('pos') or req.get('Pos')
    data = req.get('data') or {}
    if not pos:
        for c in data.get('charRecorderDataLst', []):
            for x in c.get('dataLst', []):
                if x.get('pos'):
                    pos = x['pos']
    if pos:
        set_pos(ctx.p.s, pos)
    if data and len(ctx.server.channels.get(getattr(ctx, 'chan', None), ())) > 1:   # movement seen by the others here
        ctx.server.broadcast(ctx, 'PlayerSceneSyncDataNotice', {'status': OK, 'data': [{'player_id': ctx.p.s['player_id'], 'data': [data]}]},
                             include_self=False)
    return None  # no answer


@handler('TutorialReq')
def tutorial(ctx, req):
    t = req.get('tutorial_id', 0)
    if t and t not in ctx.p.s['tutorials']:
        ctx.p.s['tutorials'].append(t); ctx.p.dirty = True
    ctx.reply({'status': OK})


@handler('ChangeNickNameReq')
def rename(ctx, req):
    if req.get('nickName'):
        ctx.p.s['name'] = req['nickName'][:20]
    if req.get('birthday'):
        ctx.p.s['birthday'] = req['birthday']
    ctx.p.dirty = True
    ctx.reply({'status': OK, 'nickName': ctx.p.s['name'], 'items': []})


# ============================================================ scenes / channels
PUBLIC_SCENE = 9999
# official entry point of each map when travelling there from the world map (no teleport target); same every time
from game import packs as _packs   # rules live in packs/official/systems/world.json
MAP_ENTRY = _packs.int_keys(_packs.system('world', 'map_entry'))
PLAZA_SPAWN = _packs.system('world', 'plaza_spawn')   # Rota Plaza spawn point (official login position, all captures)
TUTORIAL_SCENE = _packs.system('world', 'tutorial_scene', 100)   # new players stay there until the prologue is done


def pos_key(s, scene_id=None, channel_id=None):
    """Where a position belongs: each map, and each garden (scene 9999 is every garden, told apart by channel)"""
    sid = s['scene_id'] if scene_id is None else scene_id
    ch = s.get('channel_id') if channel_id is None else channel_id
    return f'{sid}:{ch}' if sid == PUBLIC_SCENE else str(sid)


def set_pos(s, pos, scene_id=None, channel_id=None):
    s['last_pos'] = pos
    s.setdefault('pos_by_scene', {})[pos_key(s, scene_id, channel_id)] = pos


def scene_player(p):
    s = p.s
    team = {}
    for slot in ('char1', 'char2', 'char3'):
        cid = s['team'].get(slot)
        ch = s['characters'].get(str(cid)) if cid else None
        if not ch:
            continue
        op = ch['outfitPresets'][ch.get('inUseOutfitPresetIndex', 0)] if ch.get('outfitPresets') else {}
        ep = ch['equipmentPresets'][ch.get('inUseEquipmentPresetIndex', 0)] if ch.get('equipmentPresets') else {}
        w = s['weapons'].get(str(ep.get('weapon', 0)), {})
        sc = {'char_id': cid, 'charLv': ch.get('level', 1), 'charStar': ch.get('star', 1), 'charBreakLv': ch.get('maxLevel', 20),
              'characterAppearance': ch.get('characterAppearance', {}),
              'outfitPreset': scene_outfit(op, s.get('outfits')),
              'weaponId': w.get('weaponId', 0), 'weaponStar': w.get('star', 1)}
        pos = s.get('pos_by_scene', {}).get(pos_key(s))   # only a position on this map (never another map's)
        if pos:
            sc['Pos'] = pos
        team[slot] = sc
    return {'player_id': s['player_id'], 'player_name': s['name'], 'team': team,
            'avatar_frame': s.get('appearance', {}).get('avatar_frame', 0), 'phone_case': s.get('phone_case', 0),
            'foodBuffIds': [int(b) for b, e in s.get('buffs', {}).items() if e > time.time()]}


DYE_OF = {'hat': 'hatDyeScheme', 'hair': 'hairDyeScheme', 'clothes': 'clothDyeScheme', 'ornament': 'ornDyeScheme'}
DYE_IDX = {'hat': 'hatDyeSchemeIndex', 'hair': 'hairDyeSchemeIndex', 'clothes': 'clothesDyeSchemeIndex', 'ornament': 'ornamentDyeSchemeIndex'}


def scene_outfit(op, outfits=None):
    """SceneCharacterOutfitPreset as official sends it: every worn piece with its actual saved dye scheme, plus hideInfo
    (the plaza's HomeCharacterOutfit.ParseFrom throws on a preset without them)."""
    out = {'hideInfo': op.get('outfitHideInfo') or op.get('hideInfo') or {}}
    outfits = outfits or {}

    def _scheme(oid, idx):
        o = outfits.get(str(oid)) or {}
        sc = next((dict(x) for x in o.get('dyeSchemes', []) if x.get('schemeIndex', 0) == idx), None)
        if sc is None:
            sc = {'isUnLock': True}
            if idx:
                sc['schemeIndex'] = idx
        else:
            sc.setdefault('isUnLock', True)
            if idx:
                sc['schemeIndex'] = idx
        return sc

    for k, v in op.items():
        if k in DYE_OF and v:
            out[k] = v
            out[DYE_OF[k]] = _scheme(v, op.get(DYE_IDX[k], 0))
        elif k.startswith('pend') and not k.endswith('Index') and not k.endswith('Scheme') and v:
            out[k] = v
            out[k + 'DyeScheme'] = _scheme(v, op.get(k + 'DyeSchemeIndex', 0))
    return out


def placed_characters(owner):
    """Characters sitting on the owner's furniture (official: character_id, outfitPreset, furniture_id)."""
    s, out = owner.s, []
    for cid in s.get('placed_characters', []):
        where = s.get('placed_where', {}).get(str(cid))
        if not where or not where.get('furniture_id'):
            continue
        ch = s['characters'].get(str(cid)) or {}
        op = ch['outfitPresets'][ch.get('inUseOutfitPresetIndex', 0)] if ch.get('outfitPresets') else {}
        e = {'character_id': cid, 'furniture_id': str(where['furniture_id']),
             'outfitPreset': scene_outfit(op, s.get('outfits'))}
        if where.get('seat_id'):
            e['seat_id'] = where['seat_id']
        out.append(e)
    return out


def garden_data(ctx, owner):
    g = owner.s['garden']
    return {'gardenFurnitureInfoMap': {str(k): v for k, v in g['furniture'].items()},
            'likesNum': str(g.get('likes', 0)), 'accessPlayerNum': str(g.get('access', 0)),
            'gardenName': owner.s['name'], 'furnitureCurrentPointNum': garden_points(ctx, owner)}


def garden_points(ctx, owner):
    tot = 0
    for f in owner.s['garden']['furniture'].values():
        r = ctx.d.row('homeitem', 'HomeItem', f['furnitureItemId'])
        tot += (r or {}).get('HomeItemPointNum', 0)
    return tot


def enter_scene(ctx, scene_id, label=None, target_label=None, before_push=None):
    """Move the player and push SceneDataNotice. Gardens are scene 9999 with channel = owner's player id."""
    p = ctx.p
    s = p.s
    owner = None
    if target_label:
        owner = ctx.server.player_by_label(target_label)
        scene_id = PUBLIC_SCENE
        if owner is None:
            return None
    elif scene_id == PUBLIC_SCENE and label in (None, 0, s['player_label']):
        owner = p
    if owner is not None:
        channel_id, chan_label = owner.s['player_id'], owner.s['player_label']
    else:
        chan_label = label or 1
        channel_id = chan_label
    s['scene_id'], s['channel_id'], s['channel_label'] = scene_id, channel_id, chan_label
    p.dirty = True
    data = {'sceneId': scene_id, 'channelId': channel_id, 'channel_label': chan_label,
            'tod_time': int(time.time()) % 86400 // 4, 'players': [scene_player(p)]}
    tpl = ctx.server.scene_template(scene_id)
    for k in ('chairInfoList', 'networkEvent', 'regionVoices', 'bonFires', 'monsters', 'treasureBoxes',
              'riddles', 'dungeons', 'flagIds', 'moonSpots', 'vehicleInfoList', 'campFires'):
        if tpl.get(k):
            data[k] = tpl[k]
    if scene_id != PUBLIC_SCENE:
        data.update(_world_mod().scene_fields(p, scene_id))
    else:   # gardens / plaza: gather spots need gatherLimits to spawn; your own garden also shows what you collected
        W = _world_mod()
        mine = W.W(p, PUBLIC_SCENE)
        from game.life import scene_gather_limits, temp_store
        data['gatherLimits'] = scene_gather_limits(p, PUBLIC_SCENE)
        stored = temp_store(p)          # back in the plaza: the field haul goes into the bag (official)
        if stored:
            ctx.push('PackNotice', {'status': OK, 'items': stored})
        if owner is p and mine.get('collections'):
            data['collections'] = mine['collections']
    if owner is not None:
        data['sceneGardenData'] = garden_data(ctx, owner)
        data['placedCharacters'] = placed_characters(owner)
    elif scene_id == PUBLIC_SCENE:
        data['sceneGardenData'] = {}    # official: a public channel sends an empty garden, which clears the last plaza's decorations
    from game import extras as _ex
    _ex.add_scene(ctx, data, owner)   # moon spots, voice regions, room decor
    if before_push:
        before_push(channel_id, chan_label)
    ctx.push('SceneDataNotice', {'status': OK, 'data': data})
    ctx.push('ChatMsgRecordInitNotice', {'status': OK, 'msg': chatlog.channel(scene_id, channel_id)})   # official order
    ctx.server.join_channel(ctx, scene_id, channel_id)
    Q.on_scene(p, scene_id)
    return channel_id, chan_label


@handler('ChangeSceneChannelReq')
def change_scene(ctx, req):
    sid = req.get('scene_id') or PUBLIC_SCENE
    key = pos_key(ctx.p.s, sid, ctx.p.s['player_id'] if sid == PUBLIC_SCENE else None)
    if sid == PUBLIC_SCENE:
        # plaza: switching channel / plaza keeps your position; coming from anywhere else is a fresh spawn
        if ctx.p.s.get('scene_id') != PUBLIC_SCENE:
            ctx.p.s.setdefault('pos_by_scene', {})[key] = dict(PLAZA_SPAWN)
        elif req.get('pos'):
            ctx.p.s.setdefault('pos_by_scene', {})[key] = req['pos']
    elif req.get('pos') and not req.get('target_player_label'):    # teleport target on the new map
        ctx.p.s.setdefault('pos_by_scene', {})[key] = req['pos']
    elif not req.get('target_player_label'):
        # map travel without a target: official always puts you at the map's entry point, never where you left
        if MAP_ENTRY.get(sid):
            ctx.p.s.setdefault('pos_by_scene', {})[key] = dict(MAP_ENTRY[sid])
        else:
            ctx.p.s.setdefault('pos_by_scene', {}).pop(key, None)
    r = enter_scene(ctx, sid, label=req.get('channel_label'), target_label=req.get('target_player_label'),
                    before_push=lambda c, l: ctx.reply({'status': OK, 'scene_id': ctx.p.s['scene_id'], 'channel_id': c, 'channel_label': l}))
    if r is None:
        ctx.reply({'status': 'StatusCode_SCENE_CHANNEL_NOT_EXIST'})


@handler('GetGardenInfoReq')
def garden_info(ctx, req):
    g = ctx.p.s['garden']
    ctx.reply({'status': OK, 'gardenInfo': {'likesNum': str(g.get('likes', 0)), 'accessNum': str(g.get('access', 0)),
                                            'furnitureNum': garden_points(ctx, ctx.p), 'furnitureLimitNum': GARDEN_LIMIT,
                                            'isOpen': g.get('open', True)}})


@handler('SceneSitChairReq')
def sit(ctx, req):
    r = {'status': OK, 'playerId': ctx.p.s['player_id'], 'chairId': req.get('chairId', 0),
         'seatId': req.get('seatId', 0), 'isSit': req.get('isSit', False)}
    ctx.reply(r)
    ctx.server.broadcast(ctx, 'SceneSitChairRsp', r, include_self=False)   # official: others get the same answer


# ============================================================ chat
@handler('SendChatMsgReq')
def chat(ctx, req):
    text = req.get('text', '')
    ctx.reply({'status': OK, 'text': text})
    # Snakes & Ladders plaza minigame commands (/sl ...) are open to all players
    if text.strip().lower().startswith('/sl'):
        from game import snakes_ladders
        if snakes_ladders.handle_command(ctx, text, pack):
            return
    # GM commands are not taken from in-game chat (anyone could type them): use the server panel (GM commands) or
    # the server console instead; a line starting with "/" is ordinary chat
    s = ctx.p.s
    from game import admin
    admin.CHAT.append((time.time(), s['player_id'], s['name'], req.get('type', ''), text))
    import logging
    logging.getLogger('rozefield').info('[chat] %s%s: %s', s['name'], ' (muted)' if s.get('muted') else '', text)
    if s.get('muted'):   # muted by the owner: only they see their own line
        return
    msg = {'playerId': s['player_id'], 'head': s['head'], 'name': s['name'], 'text': text,
           'expression': req.get('expression', 0), 'sendTime': str(now_ms()),
           'avatarFrame': s.get('appearance', {}).get('avatar_frame', 0)}
    # the sender's client already shows its own line from SendChatMsgRsp (official server never echoes it back)
    kind = req.get('type', 'ChatChannel_Default')
    note = {'status': OK, 'type': kind, 'msg': msg}
    if kind == 'ChatChannel_ChatRoom':            # world chat: everyone online
        chatlog.add_world(msg)
        for o in list(ctx.server.sessions.values()):
            if o is not ctx and o.p:
                try:
                    o.push('ChatMsgNotice', note)
                except Exception:
                    pass
    elif kind == 'ChatChannel_Private':           # private chat: the target, kept in both players' history
        tid = req.get('playerId')
        for pl in (ctx.p, ctx.server.player_by_id(tid)):
            if pl:
                other = tid if pl is ctx.p else s['player_id']
                h = pl.s.setdefault('misc', {}).setdefault('private_chat', {}).setdefault(str(other), [])
                h.append(dict(msg, toPlayerId=tid) if False else msg)
                del h[:-100]
                pl.dirty = True
        o = ctx.server.sessions.get(tid)
        if o and o is not ctx:
            o.push('ChatMsgNotice', note)
    else:                                         # nearby: same scene channel, kept for whoever comes later
        chatlog.add_channel(s['scene_id'], s['channel_id'], msg)
        ctx.server.broadcast(ctx, 'ChatMsgNotice', note, include_self=False)


GM_ITEMS = {
    'gold': 101, 'starstone': 102, 'rhombite': 102, 'ticket': 104, 'crystal': 107,
    'feline': 109, 'vitality': 10, 'stamina': 10, 'energy': 11, 'moon': 124, 'wish': 125,
}


def _gm_iid(tok):
    return GM_ITEMS.get(tok.lower()) or int(tok)


def gm_command(ctx, text):
    a = text.split()
    cmd = a[0].lower()
    p = ctx.p
    try:
        if cmd == '/give' and len(a) >= 2:
            iid, n = _gm_iid(a[1]), int(a[2]) if len(a) > 2 else 1
            got, changed = p.add_item(iid, n); pack(ctx, changed); p.save()
            return f'gave {n} x {iid} ({ctx.d.item_tag(iid)})'
        if cmd == '/take' and len(a) >= 2:
            iid, n = _gm_iid(a[1]), int(a[2]) if len(a) > 2 else 1
            have = p.count(iid)
            rm = min(have, max(0, n))
            if rm:
                changed = p.remove_item(iid, rm) or []
                pack(ctx, changed); p.save()
            return f'removed {rm} x {iid} (now {p.count(iid)})'
        if cmd == '/set' and len(a) >= 3:
            iid, want = _gm_iid(a[1]), max(0, int(a[2]))
            have = p.count(iid)
            changed = []
            if want > have:
                changed = p.add_item(iid, want - have)[1]
            elif want < have:
                changed = p.remove_item(iid, have - want) or []
            if changed:
                pack(ctx, changed)
            p.save()
            return f'set {iid} to {p.count(iid)}'
        if cmd == '/currency':
            n = int(a[1]) if len(a) > 1 else 10000
            ch = []
            for iid in (101, 102, 104, 107, 108, 109, 110, 111, 112, 11):
                ch += p.add_item(iid, n)[1]
            pack(ctx, ch); p.save()
            return f'added {n} of every currency'
        if cmd == '/level':
            p.s['level'] = max(1, min(50, int(a[1]))); p.save()
            return f'level set to {p.s["level"]} (relog to apply)'
        if cmd == '/all':
            cat = a[1].lower() if len(a) > 1 else 'help'
            n = int(a[2]) if len(a) > 2 else 99
            tags = set()
            for c in (ALL_GROUPS if cat == 'everything' else [cat]):
                tags |= ALL_GROUPS.get(c, set())
            if not tags:
                return 'usage: /all <' + '|'.join(list(ALL_GROUPS) + ['everything']) + '> [count]'
            changed, k = [], 0
            for iid, row in ctx.d.table('item', 'Item').items():
                tag = ctx.d.item_tag(iid)
                if tag not in tags:
                    continue
                want = 1 if tag in ONE_ONLY else n
                if p.count(iid) >= want:
                    continue
                changed += p.add_item(iid, want - p.count(iid))[1]; k += 1
            p.save()
            ctx.push('PackNotice', {'status': OK, 'items': changed})
            return f'added {k} item types ({cat})'
        if cmd == '/char':
            got, changed = p.add_item(int(a[1]), 1); pack(ctx, changed); p.save()
            return 'character added (relog to see it)'
    except Exception as e:
        return f'error: {e}'
    return 'commands: /give <itemId|name> [n], /take <itemId|name> [n], /set <itemId|name> <n>, /all <materials|outfits|consumables|furniture|everything> [n], /currency [n], /level <n>, /char <characterId>'


ALL_GROUPS = {
    'materials': {'EBagItemTag_Material', 'EBagItemTag_StrengthStone', 'EBagItemTag_ExpBook', 'EBagItemTag_Fragment',
                  'EBagItemTag_DyeStuff', 'EBagItemTag_Agentia', 'EBagItemTag_Catcher', 'EBagItemTag_Baitbox',
                  'EBagItemTag_MoonStone', 'EBagItemTag_PetMmaterials', 'EBagItemTag_Fish', 'EBagItemTag_Inscription',
                  'EBagItemTag_AbilityItem', 'EBagItemTag_Collection'},
    'outfits': {'EBagItemTag_Fashion', 'EBagItemTag_Pendant', 'EBagItemTag_Head', 'EBagItemTag_AvatarFrame',
                'EBagItemTag_PhoneCase', 'EBagItemTag_Umbrella', 'EBagItemTag_Badge', 'EBagItemTag_CharacterBadge',
                'EBagItemTag_Expression', 'EBagItemTag_WallPaper', 'EBagItemTag_Vehicle'},
    'consumables': {'EBagItemTag_Food', 'EBagItemTag_Item', 'EBagItemTag_Gift', 'EBagItemTag_Energy', 'EBagItemTag_Vitality',
                    'EBagItemTag_IntimacyGift', 'EBagItemTag_TeleportKey', 'EBagItemTag_MusicNote', 'EBagItemTag_Recipe',
                    'EBagItemTag_SeasonalMiniGamesItem'},
    'furniture': {'EBagItemTag_Furniture'},
}
ONE_ONLY = {'EBagItemTag_Fashion', 'EBagItemTag_Pendant', 'EBagItemTag_Head', 'EBagItemTag_AvatarFrame', 'EBagItemTag_PhoneCase',
            'EBagItemTag_Umbrella', 'EBagItemTag_Badge', 'EBagItemTag_CharacterBadge', 'EBagItemTag_Expression',
            'EBagItemTag_WallPaper', 'EBagItemTag_Vehicle', 'EBagItemTag_Recipe', 'EBagItemTag_Collection'}


# ============================================================ characters, outfits, equipment
def char(ctx, cid):
    return ctx.p.s['characters'].get(str(cid))


@handler('OutfitPresetUpdateReq')
def outfit(ctx, req):
    ch = char(ctx, req.get('charId'))
    if not ch:
        return ctx.reply({'status': FAIL})
    pre = req.get('preset', {})
    i = pre.get('presetIndex', 0)
    while len(ch['outfitPresets']) <= i:
        ch['outfitPresets'].append({'presetIndex': len(ch['outfitPresets'])})
    ch['outfitPresets'][i] = pre
    ch['inUseOutfitPresetIndex'] = i
    ctx.p.dirty = True
    ctx.reply({'status': OK, 'charId': req.get('charId'), 'preset': pre})
    Q.event(ctx.p, Q.C['WearingFashing0'])
    ctx.server.broadcast_scene_player(ctx)
    cid = req.get('charId')
    if cid in ctx.p.s.get('placed_characters', []):   # keep placed plaza NPC in sync with the character's new outfit
        entry = next((e for e in placed_characters(ctx.p) if e['character_id'] == cid), None)
        if entry:
            ctx.server.broadcast(ctx, 'GardenPlaceCharacterNotice', {'status': OK, 'character': entry})


@handler('CharacterEquipUpdateReq')
def equip(ctx, req):
    p = ctx.p
    cid = req.get('charId')
    ch = char(ctx, cid)
    if not ch:
        return ctx.reply({'status': FAIL})
    pre = req.get('equipmentPreset', {})
    i = pre.get('presetIndex', 0)
    old = ch['equipmentPresets'][i] if i < len(ch['equipmentPresets']) else {}
    changed = []
    # unset old wearers, set new ones
    def wear(kind, key, iid, who):
        inst = p.s[kind].get(str(iid))
        if inst is None:
            return
        if who:
            inst['wearerId'] = who
        else:
            inst.pop('wearerId', None)
        changed.append({'mainItem': p.instance_info({'weapons': 'EBagItemTag_Weapon', 'armors': 'EBagItemTag_Armor',
                                                     'posters': 'EBagItemTag_Poster'}[kind], inst)})
    if old.get('weapon') != pre.get('weapon'):
        wear('weapons', 'weapon', old.get('weapon'), 0); wear('weapons', 'weapon', pre.get('weapon'), cid)
    oa = {a.get('armorId') for a in old.get('armors', [])}; na = {a.get('armorId') for a in pre.get('armors', [])}
    for x in oa - na:
        wear('armors', 'armor', x, 0)
    for x in na - oa:
        wear('armors', 'armor', x, cid)
    op = {a.get('posterId') for a in old.get('posters', [])}; np_ = {a.get('posterId') for a in pre.get('posters', [])}
    for x in op - np_:
        wear('posters', 'poster', x, 0)
    for x in np_ - op:
        wear('posters', 'poster', x, cid)
    while len(ch['equipmentPresets']) <= i:
        ch['equipmentPresets'].append({'presetIndex': len(ch['equipmentPresets'])})
    ch['equipmentPresets'][i] = pre
    p.dirty = True
    ctx.reply({'status': OK, 'character': [ch], 'items': changed})


@handler('UpdateTeamReq')
def team(ctx, req):
    ctx.p.s['team'] = {k: v for k, v in req.items() if k in ('char1', 'char2', 'char3') and v}
    ctx.p.dirty = True
    ctx.reply({'status': OK})
    ctx.server.broadcast_scene_player(ctx)


@handler('CharacterGatherWeaponUpdateReq')
def gather_weapon(ctx, req):
    ch = char(ctx, req.get('character_id'))
    if ch is not None:
        ch['gatherWeapon'] = req.get('weapon_id', 0); ctx.p.dirty = True
    ctx.reply({'status': OK})


@handler('GardenPlaceCharacterReq')
def place_char(ctx, req):
    """Official: GardenPlaceCharacterNotice (to everyone in the garden) spawns / removes the character, then the Rsp."""
    s = ctx.p.s
    pc, where = s['placed_characters'], s.setdefault('placed_where', {})
    cid = req.get('character_id')
    echo = {k: req[k] for k in ('character_id', 'furniture_id', 'seat_id', 'is_remove') if k in req}
    if req.get('is_remove'):
        if cid not in pc:
            return ctx.reply({'status': 'StatusCode_BAD_REQ', **echo})
        pc.remove(cid)
        where.pop(str(cid), None)
        ctx.p.dirty = True
        ctx.server.broadcast(ctx, 'GardenPlaceCharacterNotice', {'status': OK, 'remove_character_id': cid})
        return ctx.reply({'status': OK, **echo})
    if cid not in pc:
        pc.append(cid)
    where[str(cid)] = {k: req[k] for k in ('furniture_id', 'seat_id') if k in req}   # wears the current outfit
    ctx.p.dirty = True
    entry = next((e for e in placed_characters(ctx.p) if e['character_id'] == cid), None)
    if entry:
        ctx.server.broadcast(ctx, 'GardenPlaceCharacterNotice', {'status': OK, 'character': entry})
    ctx.reply({'status': OK, **echo})


def _list(ctx, req, kind, field, filt=None):
    insts = list(ctx.p.s[kind].values())
    if filt:
        insts = [x for x in insts if filt(x)]
    ctx.reply({'status': OK, field: insts, 'totalNum': len(insts), 'endIndex': req.get('endIndex', len(insts))})


def weapon_system(ctx, weapon_id):
    return (ctx.d.row('weapon', 'Weapon', weapon_id) or {}).get('NewWeaponSystemType', 0)


@handler('GetWeaponReq')
def get_weapons(ctx, req):
    from ofproto import pool
    ws = req.get('weaponSystemType')
    num = pool.FindEnumTypeByName('pb.EWeaponSystemType').values_by_name[ws].number if ws else 0
    _list(ctx, req, 'weapons', 'weapons', (lambda w: weapon_system(ctx, w['weaponId']) == num) if num else None)


@handler('GetArmorReq')
def get_armors(ctx, req):
    _list(ctx, req, 'armors', 'armors')


@handler('GetPosterReq')
def get_posters(ctx, req):
    _list(ctx, req, 'posters', 'posters')


@handler('GetPetReq')
def get_pets(ctx, req):
    _list(ctx, req, 'pets', 'pets')


@handler('GetAllCharacterEquipReq')
def all_equip(ctx, req):
    p = ctx.p
    items = []
    for kind, tag in (('weapons', 'EBagItemTag_Weapon'), ('armors', 'EBagItemTag_Armor'), ('posters', 'EBagItemTag_Poster')):
        for inst in p.s[kind].values():
            if inst.get('wearerId'):
                items.append({'mainItem': p.instance_info(tag, inst)})
    ctx.reply({'status': OK, 'items': items})


# ============================================================ upgrades
@handler('WeaponStrengthReq')
def weapon_strength(ctx, req):
    p = ctx.p
    w = p.s['weapons'].get(str(req.get('weaponInstanceId')))
    if not w:
        return ctx.reply({'status': FAIL})
    grp = p.weapon_group(w['weaponId'], w.get('level', 1)) or {}
    st = ctx.d.row('weapon', 'WeaponStrengthen', grp.get('StrengthenID', 0))
    lvl = w.get('strengthLevel', 0) + 1
    costs = []
    if st:
        g = [x for x in st['WeaponStrengthenGroupInfo'] if x.get('Level') == lvl]
        if not g:
            return ctx.reply({'status': FAIL})
        costs = [(c['NeedItemID'], c['NeedItemCount']) for c in g[0].get('WeaponStrengthNeedItem', [])]
    paid = p.pay(costs)
    if paid is None:
        return ctx.reply({'status': 'StatusCode_ITEM_NOT_ENOUGH'} if 'StatusCode_ITEM_NOT_ENOUGH' in STATUS else {'status': FAIL})
    w['strengthLevel'] = lvl
    p.dirty = True
    ctx.reply({'status': OK, 'weaponInstanceId': w['instanceId'], 'strengthLevel': lvl})
    pack(ctx, paid + [{'mainItem': p.instance_info('EBagItemTag_Weapon', w)}])


@handler('ArmorStrengthReq')
def armor_strength(ctx, req):
    p = ctx.p
    a = p.s['armors'].get(str(req.get('armorInstanceId')))
    if not a:
        return ctx.reply({'status': FAIL})
    a['strengthLevel'] = a.get('strengthLevel', 0) + 1
    p.dirty = True
    ctx.reply({'status': OK, 'armorInstanceId': a['instanceId'], 'strengthLevel': a['strengthLevel']})
    pack(ctx, [{'mainItem': p.instance_info('EBagItemTag_Armor', a)}])


@handler('WeaponInscriptionInlaidReq')
def inscription(ctx, req):
    p = ctx.p
    w = p.s['weapons'].get(str(req.get('weaponInstanceId')))
    if not w:
        return ctx.reply({'status': FAIL})
    w['inscription1'] = req.get('inscriptionId', 0)
    p.dirty = True
    ctx.reply({'status': OK, 'weaponInstances': [w]})


# ============================================================ items, food, gifts
@handler('ItemUseReq')
def item_use(ctx, req):
    p, d = ctx.p, ctx.d
    iid, n = req.get('itemId', 0), max(1, req.get('num', 1))
    paid = p.remove_item(iid, n)
    if paid is None:
        return ctx.reply({'status': FAIL})
    got, changed = [], list(paid)
    tag = d.item_tag(iid)
    if tag == 'EBagItemTag_Food':
        aff = d.row('cooking', 'CookAffect', iid)
        if aff:
            dur = aff.get('FoodEffectTypeParam', 600) * n
            cur = max(time.time(), p.s['buffs'].get(str(aff.get('BuffID', iid)), 0))
            p.s['buffs'][str(aff.get('BuffID', iid))] = cur + dur
            ctx.push('PlayerBuffNotice', {'status': OK, 'player_buffs': buff_list(p)})
        Q.event(p, Q.C['EatFood'], iid, n)
    gb = d.row('giftbag', 'GiftBag', iid)
    if gb:
        for _ in range(n):
            for g in gb.get('GiftBagGroup', []):
                a, b = p.add_items(d.reward_items(g.get('RewardPoolGroupID'), p.s['level']))
                got += a; changed += b
    if tag == 'EBagItemTag_Vitality':   # Stamina Potion 30 / 60 / 120 ml: RelateID = Stamina restored (official)
        a, b = p.add_items([(10, (d.item(iid) or {}).get('RelateID', 30) * n)]); got += a; changed += b
    choose = req.get('chooseItemId')
    if choose:
        a, b = p.add_item(choose, n); got += a; changed += b
    p.dirty = True
    ctx.reply({'status': OK, 'items': got})
    pack(ctx, changed)


def buff_list(p):
    now = time.time()
    lst = [{'buffId': int(b), 'endTime': str(int(e))} for b, e in p.s.get('buffs', {}).items() if e > now]
    return [{'systemType': 'BuffSystemType_LIFE', 'buffLst': lst}] if lst else []


# ============================================================ shop
def shop_grids(ctx, shop_id):
    info = ctx.d.row('shop', 'Info', shop_id)
    grid = ctx.d.row('shop', 'Grid', (info or {}).get('GridID', shop_id))
    items = list((grid or {}).get('Items', []))
    rm = set((_packs.system('shops', 'remove_grids', {}) or {}).get(str(shop_id), []))
    if rm:
        items = [g for g in items if g.get('GridID') not in rm]
    add = (_packs.system('shops', 'add_grids', {}) or {}).get(str(shop_id), [])
    if add:
        have = {g.get('GridID') for g in items}
        items += [g for g in add if g.get('GridID') not in have]
    return items


def shop_period(g):
    """Refresh period of a grid: buy counts and the item picked from a multi-item pool reset with it."""
    t = time.localtime()
    kind = g.get('NewShopRefreshType')
    if kind == 2:
        return time.strftime('%Y-%m-%d', t)          # daily
    if kind == 3:
        return time.strftime('%Y-W%W', t)            # weekly
    if kind == 4:
        return time.strftime('%Y-%m', t)             # monthly
    return ''                                        # never resets


def shop_pool_entry(ctx, sid, g):
    """The pool item a grid shows. Official: poolIndex is the pool item's own Index (not the grid's); a pool with
    several items shows one of them, picked for the current refresh period, within the player's level and dates."""
    extra = (_packs.system('shops', 'extra_pools', {}) or {}).get(str(g['ShopPoolID']))
    pool = extra or ctx.d.row('shop', 'Pool', g['ShopPoolID']) or {'Items': []}
    lv, now = ctx.p.s.get('level', 1), time.strftime('%Y-%m-%d %H:%M:%S')
    ok = [x for x in pool['Items'] if x.get('MinLevel', 1) <= lv <= x.get('MaxLevel', 999)
          and x.get('OpeningTime', '') <= now and (not x.get('ClosingTime') or now <= x['ClosingTime'])] or pool['Items']
    if not ok:
        return None
    if len(ok) == 1:
        return ok[0]
    picks = ctx.p.s['shop'].setdefault(str(sid), {}).setdefault('_pick', {})
    per = shop_period(g)
    cur = picks.get(str(g['GridID']))
    if not cur or cur[0] != per or not any(x['Index'] == cur[1] for x in ok):
        cur = [per, random.choice(ok)['Index']]
        picks[str(g['GridID'])] = cur
        ctx.p.dirty = True
    return next(x for x in ok if x['Index'] == cur[1])


def shop_bought(ctx, sid, g):
    rec = ctx.p.s['shop'].setdefault(str(sid), {})
    v = rec.get(str(g['GridID']), 0)
    if isinstance(v, int):                           # old saves: plain count, never reset
        v = [shop_period(g), v] if g.get('NewShopRefreshType') else ['', v]
    if v[0] != shop_period(g):
        v = [shop_period(g), 0]
    rec[str(g['GridID'])] = v
    return v


@handler('ShopInfoReq')
def shop_info(ctx, req):
    sid = req.get('shopId')
    grids = []
    for g in shop_grids(ctx, sid):
        e = shop_pool_entry(ctx, sid, g)
        if not e:
            continue
        grids.append({'id': sid, 'gridId': g['GridID'], 'poolId': g['ShopPoolID'], 'poolIndex': e['Index'],
                      'buyTimes': shop_bought(ctx, sid, g)[1]})
    ctx.reply({'status': OK, 'shopId': sid, 'grids': grids})


@handler('ShopBuyReq')
def shop_buy(ctx, req):
    p, d = ctx.p, ctx.d
    sid, gid, times = req.get('shopId'), req.get('gridId'), max(1, req.get('buyTimes', 1))
    g = next((x for x in shop_grids(ctx, sid) if x['GridID'] == gid), None)
    if not g:
        return ctx.reply({'status': FAIL})
    rec = shop_bought(ctx, sid, g)
    have = rec[1]
    if g.get('BuyMaxCount', -1) > 0 and have + times > g['BuyMaxCount']:
        return ctx.reply({'status': FAIL})
    entry = shop_pool_entry(ctx, sid, g)
    if not entry:
        return ctx.reply({'status': FAIL})
    costs = []
    for c in entry.get('ShopCurrencyItem', []):
        price = c.get('Price', 0)
        if c.get('IncreasingID'):
            inc = d.row('shop', 'Increasing', c['IncreasingID'])
            if inc:
                price = inc['Items'][min(have, len(inc['Items']) - 1)].get('Price', price)
        if c.get('CurrencyID'):
            costs.append((c['CurrencyID'], int(price * entry.get('Discount', 1.0)) * times))
    if g.get('GoodsID'):
        return ctx.reply({'status': FAIL})  # real-money item
    paid = p.pay(costs)
    if paid is None:
        return ctx.reply({'status': FAIL})
    got, changed = p.add_item(entry['ItemID'], entry.get('ItemNum', 1) * times)
    if entry.get('AddItemID'):
        a, b = p.add_item(entry['AddItemID'], entry.get('AddItemNum', 1) * times); got += a; changed += b
    rec[1] = have + times
    p.dirty = True
    ctx.reply({'status': OK, 'shopId': sid, 'grids': {'id': sid, 'gridId': gid, 'poolId': g['ShopPoolID'],
                                                      'poolIndex': entry['Index'], 'buyTimes': have + times}, 'items': got})
    pack(ctx, paid + changed)


# ============================================================ gacha (recruit)
SSR_RATE, SSR_PITY, SR_CHAR_RATE, SSR_POSTER_RATE = 0.01, 70, 0.06, 0.008


def gacha_state(p, gid):
    return p.s['gacha'].setdefault(str(gid), {'times': 0, 'since_ssr': 0, 'lost5050': False, 'records': []})


def gacha_info(ctx, gid):
    st = gacha_state(ctx.p, gid)
    return {'gachaId': gid, 'gachaTimes': st['times'], 'guarantee': SSR_PITY - st['since_ssr']}


@handler('GachaListReq')
def gacha_list(ctx, req):
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    out = []
    for gid, r in ctx.d.table('gacha', 'Info').items():
        if r.get('ClosingTime') and r['ClosingTime'] < now and not ctx.server.args.all_banners:
            continue
        out.append(gacha_info(ctx, gid))
    ctx.reply({'status': OK, 'gachas': out})


@handler('GachaRecordReq')
def gacha_record(ctx, req):
    st = gacha_state(ctx.p, req.get('gachaId'))
    page = max(1, req.get('page', 1))
    recs = st['records'][::-1]
    per = 5
    ctx.reply({'status': OK, 'gachaId': req.get('gachaId'), 'page': page, 'totalPage': max(1, (len(recs) + per - 1) // per),
               'records': recs[(page - 1) * per: page * per]})


def _pool_items(ctx, pool_id):
    return [x['ItemID'] for x in (ctx.d.row('gacha', 'RewardPool', pool_id) or {}).get('Items', [])]


@handler('GachaReq')
def gacha(ctx, req):
    p, d = ctx.p, ctx.d
    gid = req.get('gachaId')
    info = d.row('gacha', 'Info', gid)
    if not info:
        return ctx.reply({'status': FAIL})
    single = req.get('isSingle', False)
    n = info.get('Method1Count', 1) if single else info.get('Method2Count', 10)
    cur = info.get('ConsumeItem1ID') if single else info.get('ConsumeItem2ID')
    cost = info.get('ConsumeItem1Num') if single else info.get('ConsumeItem2Num')
    paid = p.pay([(cur, cost)]) if cur else []
    if paid is None:
        return ctx.reply({'status': FAIL})
    pools = [x['FreeGachaPoolID'] for x in (d.row('gacha', 'Pool', info.get('Method1ID', gid)) or {}).get('Items', [])]
    tiers = {pid: _pool_items(ctx, pid) for pid in pools}
    limited = info.get('BigGuaranteePoolID')
    if limited and limited not in (400, 500):   # official: limited banners never give the newer imprints (180 pulls, 2026-11-26)
        lo, hi = (_packs.system('gacha', 'limited_banner_excludes', [11210, 11450]) + [0, 0])[:2]
        for t in (100, 200):
            if tiers.get(t):
                tiers[t] = [i for i in tiers[t] if not lo <= i <= hi] or tiers[t]
    st = gacha_state(p, gid)
    results = []
    got_sr = False
    for k in range(n):
        st['since_ssr'] += 1; st['times'] += 1
        r = random.random()
        pity = SSR_RATE if st['since_ssr'] < SSR_PITY else 1.0
        if 100 not in tiers:  # non-standard banner (e.g. Rota Featured): uniform over its pools
            pick = random.choice([x for v in tiers.values() for x in v] or [101])
        elif r < pity:
            st['since_ssr'] = 0
            lim = tiers.get(limited) if limited and limited != 400 else None
            if lim and (st['lost5050'] or random.random() < 0.5):
                pick = random.choice(lim); st['lost5050'] = False
            else:
                pick = random.choice(tiers.get(400) or tiers.get(500) or [101]); st['lost5050'] = bool(lim)
        elif r < pity + SR_CHAR_RATE or (k == n - 1 and n >= 10 and not got_sr):
            pick = random.choice(tiers.get(300) or [101]); got_sr = True
        elif r < pity + SR_CHAR_RATE + SSR_POSTER_RATE:
            pick = random.choice(tiers.get(200) or tiers.get(100))
        else:
            pick = random.choice(tiers.get(100))
        if d.item_tag(pick) == 'EBagItemTag_Card':
            got_sr = True
        results.append(pick)
        st['records'].append({'gachaId': gid, 'itemId': pick, 'gachaTime': str(int(time.time()))})
    # a new player's first recruit always guarantees Shiika (102001) so the story & team tutorial match official
    owned = {int(c) for c in p.s['characters']}
    if len(owned) < 2 and 102001 not in owned:
        results[-1] = 102001
        st['records'][-1]['itemId'] = 102001
    got, changed = p.add_items([(x, 1) for x in results])
    p.dirty = True
    Q.event(p, Q.C['Gacha'], n=len(results))
    ctx.reply({'status': OK, 'items': got, 'info': gacha_info(ctx, gid)})
    pack(ctx, paid + changed)


# ============================================================ garden furniture
def new_furniture_id(p):
    g = p.s['garden']
    fid = p.s['player_id'] * 100000 + g['next_furniture_id']
    g['next_furniture_id'] += 1
    return fid


def _handing(p):
    """furniture held in the hand while decorating: fid -> {'itemId', 'lifted'} ('lifted' = picked up from the plaza,
    so its item was never returned to the bag)."""
    h = p.s.setdefault('handing', {})
    for k, v in list(h.items()):
        if not isinstance(v, dict):
            h[k] = {'itemId': v, 'lifted': False}
    return h


def furniture_used(p):
    """Official model: the bag keeps every piece owned; furnitureItemInfo = pieces in use. The decorate panel shows used/owned."""
    return p.furniture_used()


def furniture_free(p, item):
    return p.count(item) - furniture_used(p).get(item, 0)


def _furniture_notice(ctx, item, used_delta):
    """The client does used[item] -= num (BagsSystem.OnFurnitureItemChangeNotice): num is the change of the pieces
    left in the bag, -1 when one is placed and +1 when one goes back."""
    ctx.push('FurnitureItemChangeNotice', {'status': OK, 'furnitureItemInfo': {'itemId': item, 'num': str(-used_delta)}})


@handler('HandingFurnitureReq')
def handing(ctx, req):
    p = ctx.p
    if furniture_free(p, req.get('itemId')) <= 0:
        return ctx.reply({'status': FAIL})
    fid = new_furniture_id(p)
    _handing(p)[str(fid)] = {'itemId': req.get('itemId'), 'lifted': False}
    ctx.reply({'status': OK, 'furnitureId': str(fid)})


@handler('TakeOutHandingFurnitureReq')
def take_handing(ctx, req):
    """Put the held piece away: a piece lifted from the plaza goes back to the bag."""
    p = ctx.p
    h = _handing(p).pop(str(req.get('furnitureId')), None)
    p.dirty = True
    if h and h.get('lifted'):   # official: the lifted piece is removed from the plaza, then the Rsp
        ctx.server.broadcast(ctx, 'SceneGardenFurnitureRemoveNotice',
                             {'status': OK, 'furniture_id': str(req.get('furnitureId')), 'item_id': h['itemId']})
    ctx.reply({'status': OK, 'furnitureId': req.get('furnitureId')})


def garden_owner(ctx):
    p = ctx.p
    if p.s['scene_id'] == PUBLIC_SCENE and p.s['channel_id'] == p.s['player_id']:
        return p
    return None


@handler('PlaceFurnitureReq')
def place(ctx, req):
    p = ctx.p
    if garden_owner(ctx) is None:
        return ctx.reply({'status': FAIL})
    g = p.s['garden']['furniture']
    fid = req.get('furnitureId') and str(req['furnitureId'])
    item = req.get('furnitureItemId')
    held = _handing(p).get(fid) if fid else None
    consume = not (fid and fid in g) and not (held and held.get('lifted'))
    if consume and furniture_free(p, item) <= 0:  # a new piece from the bag
        return ctx.reply({'status': FAIL})
    if fid:
        _handing(p).pop(fid, None)
    fid = fid or str(new_furniture_id(p))
    info = {'furnitureId': fid, 'furnitureItemId': item, 'pos': req.get('pos', {}), 'rotation': req.get('rot', {})}
    if req.get('layerNum'):
        info['layerNum'] = req['layerNum']
    g[fid] = info
    p.dirty = True
    # official: UpdateNotice (to everyone, you included) then the Rsp; no FurnitureItemChangeNotice, the client
    # counts the pieces itself when one is taken in hand / put away (sending one too counted every piece twice)
    ctx.server.broadcast(ctx, 'SceneGardenFurnitureUpdateNotice', {'status': OK, 'furniture_info': info})
    ctx.reply({'status': OK, 'furnitureDetailsInfo': info})
    Q.event(p, Q.C['PlacingFurniture0'])


@handler('TakeOutFurnitureReq')
def take_out(ctx, req):
    """isPutInPackage=true: store it in the bag. false: the player lifted it to move it (it stays in hand)."""
    p = ctx.p
    fid = str(req.get('furnitureId'))
    f = p.s['garden']['furniture'].pop(fid, None)
    if not f:
        return ctx.reply({'status': FAIL})
    p.dirty = True
    ctx.reply({'status': OK, 'furnitureId': fid})
    if not req.get('isPutInPackage'):
        _handing(p)[fid] = {'itemId': f['furnitureItemId'], 'lifted': True}
        ctx.server.broadcast(ctx, 'SceneGardenFurnitureRemoveNotice', {'status': OK, 'furniture_id': fid, 'item_id': f['furnitureItemId']},
                             include_self=False)
        return
    ctx.server.broadcast(ctx, 'SceneGardenFurnitureRemoveNotice', {'status': OK, 'furniture_id': fid, 'item_id': f['furnitureItemId']})


def _clear_garden(p):
    """Everything back to the bag (the bag already counts it, so only the in-use list empties)."""
    p.s['garden']['furniture'].clear()
    p.s['handing'] = {}


@handler('GardenFurnitureRemoveAllReq')
def remove_all(ctx, req):
    p = ctx.p
    _clear_garden(p)
    p.dirty = True
    ctx.reply({'status': OK})
    enter_scene(ctx, PUBLIC_SCENE, label=p.s['player_label'])


# ---- saved layouts ("Preset Decor"): 3 slots, unlocked by UnLockHomeSet<n>_Item
SCHEME_SLOTS = (1, 2, 3)


def _schemes(p):
    return p.s['garden'].setdefault('schemes', {})


@handler('GardenFurnitureSchemeReq')
def schemes(ctx, req):
    sc = _schemes(ctx.p)
    ctx.reply({'status': OK, 'schemes': {str(i): sc.get(str(i), {}).get('name', '') for i in SCHEME_SLOTS}})


@handler('GardenFurnitureSaveReq')
def scheme_save(ctx, req):
    p = ctx.p
    sid = str(req.get('scheme_id', 0))
    sc = _schemes(p)
    old = sc.get(sid, {})
    sc[sid] = {'name': old.get('name', ''), 'furniture': json_copy(p.s['garden']['furniture'])}
    p.dirty = True
    ctx.reply({'status': OK, 'scheme_id': req.get('scheme_id', 0)})


@handler('GardenFurnitureSchemeSetNameReq')
def scheme_name(ctx, req):
    p = ctx.p
    _schemes(p).setdefault(str(req.get('scheme_id', 0)), {'furniture': {}})['name'] = req.get('name', '')
    p.dirty = True
    ctx.reply({'status': OK, 'scheme_id': req.get('scheme_id', 0), 'name': req.get('name', '')})


@handler('GardenSchemeFurnitureListReq')
def scheme_list(ctx, req):
    """Pieces of the layout the player is missing (bag + plaza)."""
    p = ctx.p
    sc = _schemes(p).get(str(req.get('scheme_id', 0)), {}).get('furniture', {})
    need = {}
    for f in sc.values():
        need[f['furnitureItemId']] = need.get(f['furnitureItemId'], 0) + 1
    missing = [i for i, n in need.items() if p.count(i) < n]
    ctx.reply({'status': OK, 'scheme_id': req.get('scheme_id', 0), 'furnitureItemId': missing})


@handler('GardenFurnitureApplySchemeReq')
def scheme_apply(ctx, req):
    p = ctx.p
    sc = _schemes(p).get(str(req.get('scheme_id', 0)), {}).get('furniture', {})
    _clear_garden(p)
    fur = p.s['garden']['furniture']
    left = {}
    for fid, f in sc.items():
        i = f['furnitureItemId']
        left.setdefault(i, p.count(i))
        if left[i] > 0:
            left[i] -= 1
            fur[fid] = json_copy(f)
    p.dirty = True
    ctx.reply({'status': OK, 'scheme_id': req.get('scheme_id', 0)})
    ctx.push('PackNotice', {'status': OK, 'items': p.pack_items()})
    enter_scene(ctx, PUBLIC_SCENE, label=p.s['player_label'])


@handler('SwitchGardenStatusReq')
def garden_status(ctx, req):
    g = ctx.p.s['garden']
    g['open'] = req.get('isOpen', False)
    ctx.p.dirty = True
    ctx.reply({'status': OK, 'isOpen': g['open'], 'password': req.get('password', '')})


def json_copy(x):
    import json
    return json.loads(json.dumps(x))


# ============================================================ appearance (umbrella, badge, tools / avatar frame)
@handler('UpdateCharacterAppearanceReq')
def char_appearance(ctx, req):
    p = ctx.p
    cid = req.get('charId', 0)
    ch = p.s['characters'].get(str(cid))
    if not ch:
        return ctx.reply({'status': FAIL})
    sent = req.get('appearance', {})
    ap = ch.setdefault('characterAppearance', {})
    ap.update(sent)
    for k in [k for k, v in ap.items() if not v]:
        ap.pop(k)
    umb_ch = p.sync_umbrella_tool(ch)
    if isinstance(umb_ch, list) and umb_ch:
        pack(ctx, umb_ch)
    p.dirty = True
    # Return only the changed field(s) so the client fires 1 toast instead of 1 per appearance slot
    ctx.reply({'status': OK, 'charId': cid, 'appearance': sent or ap})


@handler('UpdatePlayerAppearanceReq')
def player_appearance(ctx, req):
    p = ctx.p
    ap = p.s.setdefault('appearance', {})
    ap.update(req.get('appearance', {}))
    p.dirty = True
    ctx.reply({'status': OK, 'appearance': ap})


# ============================================================ quests / story
@handler('AcceptQuestReq')
def accept_quest(ctx, req):
    qid = req.get('questId', 0)
    x = Q.idx(ctx.p.d)
    st = x['stories'].get(qid)
    if st and qid not in x['quests']:    # story screen "Accept Quest" sends the story id: start that story's next quest
        group = x['by_group'].get(st.get('QuestID'), [])
        qs = ctx.p.s['quests']
        nxt = next((g for g in group if (qs.get(str(g)) or {}).get('status') != Q.FINISH), None)
        if nxt is None or not Q.story_open(ctx.p, st):
            return ctx.reply({'status': 'StatusCode_FAIL'})
        qid = nxt
    q = Q.accept(ctx.p, qid)
    ctx.reply({'status': OK, 'quest': q})
    ctx.p.__dict__.get('_qchanged', {}).pop(str(q['questId']), None)   # already in the reply


def _claim_story(ctx, sid):
    """Story screen "Claim reward": the story's quests are all done -> chapter reward."""
    p = ctx.p
    st = Q.idx(p.d)['stories'].get(sid)
    if not st or not Q.story_done(p, st):
        return ctx.reply({'status': FAIL})
    ch = p.s.setdefault('chapters', {}).setdefault(str(Q.idx(p.d)['chapter_of'].get(sid, 0)), [])
    got = []
    if sid not in ch:
        ch.append(sid)
        items = ctx.d.reward_items(st['Reward'], p.s['level']) if st.get('Reward') else []
        got, changed = p.add_items(items) if items else ([], [])
        pack(ctx, changed)
    p.dirty = True
    # the client looks quest.questId up in its quest table (a story id there throws "QuestConfigure ... 1000001"
    # and the reward popup never opens): answer with the story's last quest, finished
    qids = sorted(Q.idx(p.d)['by_group'].get(st.get('QuestID'), [])) or [st.get('QuestID')]
    last = p.s['quests'].get(str(qids[-1])) or {'questId': qids[-1], 'status': 'QuestStatus_Finish', 'completeCount': 1}
    ctx.reply({'status': OK, 'quest': last, 'items': got})


@handler('ClaimQuestRewardReq')
def claim_quest(ctx, req):
    p = ctx.p
    qid = req.get('questId', 0)
    if qid in Q.idx(p.d)['stories']:
        return _claim_story(ctx, qid)
    q = p.s['quests'].get(str(qid))
    if not q or q.get('status') != 'QuestStatus_Completed':
        return ctx.reply({'status': FAIL})
    got = []
    Q.finish(p, q, got)
    ctx.reply({'status': OK, 'quest': q, 'items': got})


# ---- actions that move quests along
def _ok_event(name, fn):
    def f(ctx, req):
        ctx.reply({'status': OK})
        fn(ctx.p, req)
    H[name] = f


_ok_event('NpcTalkReq', lambda p, r: (Q.event(p, Q.C['QuestTalk'], r.get('id')),
                                      Q.event(p, Q.C['MechanismInteraction'], r.get('id')), Q.reported(p, r.get('id'))))
_ok_event('TreasureBoxOpenReq', lambda p, r: (Q.event(p, Q.C['OpenBox']), Q.event(p, Q.C['OpenBox0'])))


@handler('MonsterDeadReq')
def monster_dead(ctx, req):
    ctx.reply({'status': OK, 'monsterIndex': req.get('monsterIndex', 0)})
    Q.event(ctx.p, Q.C['KillMonest'], req.get('monsterId'))
    Q.event(ctx.p, Q.C['KillMonsterNum'])


@handler('FlagBattleStateUpdateReq')
def flag_battle(ctx, req):
    bid = req.get('battle_id', 0)
    ctx.reply({'status': OK, 'battle_data': {}})
    if req.get('battle_state') == 'Finish':
        Q.event(ctx.p, Q.C['FinishMission'], bid)
        Q.reported(ctx.p, bid)


@handler('BattleEncounterStateUpdateReq')
def encounter(ctx, req):
    ctx.reply({'status': OK})
    if req.get('battleState') == 'Finish':
        Q.event(ctx.p, Q.C['FinishEncounter'])
        Q.event(ctx.p, Q.C['FinishTheEncounter'], req.get('encounter_id'))


@handler('AreaUnlockReq')
def area_unlock(ctx, req):
    p = ctx.p
    aid = req.get('areaId', 0)
    areas = p.s.setdefault('areas', [])
    if aid not in areas:
        areas.append(aid)
        Q.event(p, Q.C['AreaUlockNum'], absolute=len(areas))
    ctx.reply({'status': OK, 'area': {'areaId': aid, 'level': 1}})


# ============================================================ per-player records (achievements, life skills, manual, ...)
# Read-only info queries. Their answers are the player's own progress, imported from the official server
# (archive import / player export tool) into state['records'][<Req>][<request json>]; new players get defaults.
RECORD_QUERIES = (
    'AbilityBadgeListReq', 'BossRushInfoReq', 'ExploreInitReq', 'FriendIntervalInitReq', 'SelfIntervalInitReq',
    'GetAchieveGroupListReq', 'GetAchieveOneGroupReq', 'GetArchiveInfoReq', 'GetCollectItemIdsReq', 'GetCollectMoonInfoReq',
    'GetLifeInfoReq', 'GetOneTypeLifePictorialBookCountReq', 'ManualListReq', 'PlayerAbilityListReq', 'PlayerVitalityReq',
    'PosterIllustrationListReq', 'SceneProcessListReq', 'SupplyBoxInfoReq', 'TreasureIllustrationInfoReq',
    'WorldLevelAchieveListReq', 'GetCharacterAchievementListReq', 'WishListByFriendIdReq', 'GenericSceneBReq',
    'GenericGameBReq', 'ChallengeFriendRankReq',
)


def record_key(req):
    import json
    return json.dumps(req or {}, sort_keys=True, ensure_ascii=False)


def _record_default(ctx, name, req):
    r = {'status': OK}
    if name == 'GetLifeInfoReq':
        lt = req.get('life_type', 'LIFE_TYPE_NONE')
        r.update({'lifeBaseInfo': {'lifeType': lt, 'level': 1}, 'lifeSkill': {'lifeType': lt}, 'lifeAchieve': {'lifeType': lt}})
    elif name == 'GetAchieveOneGroupReq':
        r['currentGroupAchieveInfo'] = {'groupId': req.get('groupId', 0)}
    elif name == 'GetArchiveInfoReq':
        r['key'] = req.get('key', '')
        r['value'] = ''
    elif name == 'GetCharacterAchievementListReq':
        r['characterId'] = req.get('characterId', 0)
    elif name in ('GenericSceneBReq', 'GenericGameBReq'):
        r['generic_msg_id'] = req.get('generic_msg_id', 0)
        if name == 'GenericGameBReq' and req.get('generic_msg_id') == 6:   # official answer before a co-op game
            r['params'] = [{'int_value': '1'}]
    return r


def _make_record_handler(name):
    def f(ctx, req):
        rec = ctx.p.s.get('records', {}).get(name, {})
        body = rec.get(record_key(req))
        ctx.reply(dict(body) if body else _record_default(ctx, name, req))
    H[name] = f


for _n in RECORD_QUERIES:
    _make_record_handler(_n)


@handler('SetArchiveInfoReq')
def set_archive(ctx, req):
    """Client-side flags (tutorial pictures shown, camera mode...)."""
    k = record_key({'key': req.get('key', '')})
    ctx.p.s.setdefault('records', {}).setdefault('GetArchiveInfoReq', {})[k] = {'status': OK, 'key': req.get('key', ''),
                                                                             'value': req.get('value', '')}
    ctx.p.dirty = True
    ctx.reply({'status': OK, 'key': req.get('key', ''), 'value': req.get('value', '')})


# ============================================================ perform / emotes / mini games
@handler('SendActionReq')
def send_action(ctx, req):
    ctx.reply({'status': OK})
    aid = req.get('actionId', 0)
    if aid >= 10000:   # group action (high five, hug...): nearby players get an invite icon above this player
        ctx.server.broadcast(ctx, 'SendMultipleActionNotice', {'status': OK, 'actionId': aid, 'fromPlayerId': ctx.p.s['player_id'],
                                                               'endTime': str(int(time.time()) + 30)}, include_self=False)
    else:
        ctx.server.broadcast(ctx, 'SendActionNotice', {'status': OK, 'actionId': aid, 'fromPlayerId': ctx.p.s['player_id'],
                                                       'fromPlayerName': ctx.p.s['name']}, include_self=False)
    Q.event(ctx.p, Q.C['Emotion'])
    if (ctx.d.row('action', 'ActionInfo', aid) or {}).get('NewActionType') == 1:   # campfire: an interaction item
        Q.event(ctx.p, Q.C['UseInteractiveItemNum'])


@handler('ChangeMusicalItemReq')
def musical_item(ctx, req):
    iid = req.get('musical_item_instance_id', '0')
    p = ctx.p
    item_id = int(iid) if p.count(int(iid or 0)) > 0 else 0
    if req.get('source') == 'MusicalItemSource_Furniture':
        # an instrument placed in a plaza: the instance is the furniture piece, the item is its furniture item
        # (sending 0 here hides the client's Play button)
        owner = p if p.s.get('channel_id') == p.s['player_id'] else ctx.server.player_by_id(p.s.get('channel_id'))
        f = (owner.s['garden']['furniture'] if owner else {}).get(str(iid)) or {}
        item_id = f.get('furnitureItemId', 0)
    p.s['musical_item'] = {'source': req.get('source', 'MusicalItemSource_Self'), 'id': item_id}
    ctx.reply({'status': OK, 'source': req.get('source', 'MusicalItemSource_Self'), 'musical_item_instance_id': iid,
               'musical_item_id': item_id})


@handler('GenericGameAReq')
def generic_game_a(ctx, req):
    ctx.reply({'status': OK, 'generic_msg_id': req.get('generic_msg_id', 0), 'params': req.get('params') or [{}]})


# ============================================================ scrap (disassemble weapons / armor)
def _disassemble_items(ctx, kind, inst):
    d = ctx.d
    if kind == 'weapon':
        cfg = d.row('weapon', 'Weapon', inst.get('weaponId')) or {}
        prop = d.row('weapon', 'WeaponProperty', cfg.get('WeaponPropertyID')) or {}
        groups, table, field = prop.get('WeaponPropertyGroupInfo', []), ('weapon', 'WeaponDisassemble'), 'WeaponDisassembleItem'
    else:
        cfg = d.row('armor', 'Armor', inst.get('armorId')) or {}
        prop = d.row('armor', 'ArmorProperty', cfg.get('ArmorPropertyID')) or {}
        groups, table, field = prop.get('ArmorPropertyGroupInfo', []), ('armor', 'ArmorDisassemble'), 'ArmorDisassembleItem'
    lvl = inst.get('level', 1)
    g = next((g for g in groups if g.get('MinLevel', 1) <= lvl <= g.get('MaxLevel', 999)), groups[-1] if groups else {})
    out = []
    for it in (d.row(*table, g.get('DisassembleID', 101)) or {}).get(field, []):
        if random.random() <= it.get('ItemRate', 1.0):
            n = random.randint(it.get('ItemMinCount', 1), max(it.get('ItemMinCount', 1), it.get('ItemMaxCount', 1)))
            if n > 0:
                out.append((it['ItemID'], n))
    return out


@handler('EquipDisassembleReq')
def disassemble(ctx, req):
    p = ctx.p
    gain, done_w, done_a = [], [], []
    for kind, ids, store, done in (('weapon', req.get('weaponIds', []), 'weapons', done_w), ('armor', req.get('armorIds', []), 'armors', done_a)):
        for iid in ids:
            inst = p.s[store].get(str(iid))
            if not inst or inst.get('wearerId') or inst.get('isLock'):
                continue
            gain += _disassemble_items(ctx, kind, inst)
            del p.s[store][str(iid)]
            done.append(iid)
    got, changed = p.add_items(gain) if gain else ([], [])
    p.dirty = True
    ctx.reply({'status': OK, 'items': got, 'weaponIds': done_w, 'armorIds': done_a})
    if done_w or done_a:
        Q.event(p, Q.C['Decompose0'], n=len(done_w) + len(done_a))
    pack(ctx, changed)


# ============================================================ dye
@handler('OutfitColorantSelectReq')
def colorant_select(ctx, req):
    ctx.p.s.setdefault('dye_colorant', {})[str(req.get('outfitId', 0))] = req.get('colorantItemId', 0)
    ctx.reply({'status': OK, 'param': {'pictureId': req.get('colorantItemId', 0), 'isDye': True}})


@handler('OutfitDyeReq')
def outfit_dye(ctx, req):
    p = ctx.p
    oid = req.get('outfitId', 0)
    si = req.get('schemeIndex', 0)
    if si == 0:   # QOL: dye slot 0 is reserved for the original outfit colors (selectable, cannot be dyed over)
        return ctx.reply({'status': FAIL})
    # official: every dye uses 1 of the colorant picked for this outfit (OutfitColorantSelectReq), then a PackNotice
    colorant = p.s.get('dye_colorant', {}).get(str(oid)) or 401
    paid = p.remove_item(colorant, 1)
    if paid is None:
        return ctx.reply({'status': FAIL})
    col = req.get('specifyColor') or {'red': random.randint(0, 255), 'green': random.randint(0, 255), 'blue': random.randint(0, 255)}
    col = dict(col, pos=req.get('pos', 0))
    p.s.setdefault('dye_pending', {})[str(oid)] = {'schemeIndex': si, 'color': col}
    p.s['dye_total'] = p.s.get('dye_total', 0) + 1
    p.dirty = True
    ctx.reply({'status': OK, 'outfitId': oid, 'posColor': col, 'totalGuaranteeDyeNum': p.s['dye_total']})
    pack(ctx, paid)


@handler('OutFitDyeSaveReq')
def outfit_dye_save(ctx, req):
    p = ctx.p
    oid = str(req.get('outfitId', 0))
    pend = p.s.setdefault('dye_pending', {}).pop(oid, None)
    si = req.get('schemeIndex', pend['schemeIndex'] if pend else 0)
    col = pend['color'] if pend else {'pos': req.get('pos', 0)}
    if pend and si != 0 and req.get('isSaveDyeResult', True):
        o = p.s['outfits'].setdefault(oid, {'outfitId': int(oid)})
        schemes = o.setdefault('dyeSchemes', [{'schemeIndex': 0, 'isUnLock': True}])
        sc = next((x for x in schemes if x.get('schemeIndex', 0) == si), None)
        if sc is None:
            sc = {'schemeIndex': si, 'isUnLock': True}
            schemes.append(sc)
        sc['colors'] = [c for c in sc.get('colors', []) if c.get('pos', 0) != col.get('pos', 0)] + [col]
    p.dirty = True
    ctx.reply({'status': OK, 'schemeIndex': si, 'posColor': col, 'isSaveDyeResult': req.get('isSaveDyeResult', False)})


# ============================================================ status replies (restored)
@handler('SceneInterActionPlayStatusReq')
def interaction_status(ctx, req):
    ctx.reply({'status': OK})
    ctx.server.broadcast(ctx, 'SceneInterActionPlayStatusNotice', {'status': OK, 'actionStatus': req.get('actionStatus', {}),
                                                                   'pushType': req.get('pushType', 'Immediately'),
                                                                   'playerId': ctx.p.s['player_id']}, include_self=False)


# ============================================================ simple status replies built from state
@handler('PlayerEnergyInfoReq')
def energy(ctx, req):
    ctx.reply({'status': OK, 'energyItem': {'mainItem': ctx.p.item_info(11)}})


@handler('UnlockHeadListReq')
def heads(ctx, req):
    p = ctx.p
    ctx.reply({'status': OK, 'heads': [int(k) for k, v in p.s['items'].items() if v > 0 and ctx.d.item_tag(int(k)) == 'EBagItemTag_Head']})


@handler('GetMailsReq')
def mails(ctx, req):
    ctx.reply({'status': OK, 'mails': ctx.p.s.get('mails', [])})


@handler('FriendReq')
def friends(ctx, req):
    ctx.reply({'status': OK, 'info': ctx.server.friend_list(ctx)})


@handler('OtherPlayerInfoReq')
def other_info(ctx, req):
    o = ctx.server.player_by_id(req.get('playerId'))
    if not o:
        return ctx.reply({'status': FAIL})
    s = o.s
    ctx.reply({'status': OK, 'otherInfo': {'playerId': s['player_id'], 'nickName': s['name'], 'level': s['level'],
                                           'head': s['head'], 'isOnline': ctx.server.is_online(s['player_id']),
                                           'sign': s['sign'], 'createTime': s['create_time'], 'playerLabel': s['player_label'],
                                           'gardenLikeNum': str(s['garden'].get('likes', 0)), 'account_type': 16666}})


STATUS = set()
try:
    from ofproto import pool as _pool
    STATUS = {v.name for v in _pool.FindEnumTypeByName('pb.StatusCode').values}
except Exception:
    pass


# life skills (cooking, sewing, making, handicraft, fishing, gathering) override the archived-record answers
from game import life as _life  # noqa: E402
_life.register(H, pack)

# dungeons, vitality, monster drops
from game import dungeon as _dungeon  # noqa: E402
_dungeon.register(H, pack, enter_scene, scene_player)

# character growth, profile, presets, pets, visits, achievements
from game import progression as _prog  # noqa: E402
_prog.register(H, pack, enter_scene, PUBLIC_SCENE)

# open world: chests, riddles, flags, challenges, encounters, areas, moons, field drops, dungeon chest
from game import world as _world  # noqa: E402
_world.register(H, pack, scene_player)

# everything else: purchases, temp pack, exploration, collection rewards, codes, Boss Rush, mini-games, acks
from game import misc as _misc  # noqa: E402
_misc.register(H, pack)

# rifts with friends, moon spots, voice regions, room decor, emoji / clap / vehicle seen by others, event sandbag + wish text
from game import extras as _extras  # noqa: E402
_extras.register(H, pack)

# Game Hall co-op games (balloons, floating platforms), playable solo or with others on this server
from game import coop as _coop  # noqa: E402
_coop.register(H, pack, scene_player)

# online Gomoku, photo wall, rankings, restaurant mini-game
from game import social2 as _social2  # noqa: E402
_social2.register(H, pack)
from game import friends as _friends  # noqa: E402
_friends.register(H, pack)


# events (pass, gashapon, wishing tree, sign-in), abyss, group emotes, dice, friend gifts, recruit extras
from game import events as _events  # noqa: E402
_events.register(H, pack, scene_player)

# field completion (SceneProcessListReq live + "map completion N%" quest steps)
from game import scene_progress as _scene_progress  # noqa: E402
_scene_progress.register(H)

# info screens that follow new play (treasure / character achievements / world level / Boss Rush / challenge ranks)
from game import live_records as _live_records  # noqa: E402
_live_records.register(H, _friends.brief)
_live_records.register_wishlist(H, pack)
