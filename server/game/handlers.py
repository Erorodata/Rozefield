"""Request handlers. Each handler: def on_<ReqName>(ctx, req) where req is a dict and ctx is the Session.

ctx.p        -> Player (state in ctx.p.s)
ctx.reply(dict)          -> response to the current request (Rsp type inferred)
ctx.push(name, dict)     -> server push (notice)
ctx.d        -> Data tables
"""
import random, time
from game import quests as Q

H = {}


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
    ctx.reply({'status': OK, 'server_time_ms': str(now_ms()), 'region_name': 'rozefield_local',
               'register_time': s['create_time'], 'analysis_account_id': str(s['player_id']),
               'server_time_zone': 28800, 'player_name': s['name'], 'scene_id': s['scene_id'],
               'channel_id': s['channel_id'] or s['player_id']})


@handler('PlayerMainDataReq')
def main_data(ctx, req):
    p = ctx.p
    Q.login(p)
    ctx.reply(p.main_data())
    p.s['last_login'] = int(time.time())
    ctx.push('PackNotice', {'status': OK, 'items': p.pack_items()})
    ctx.push('ShopInitNotice', {'status': OK})
    buffs = buff_list(p)
    if buffs:
        ctx.push('PlayerBuffNotice', {'status': OK, 'player_buffs': buffs})
    enter_scene(ctx, p.s['scene_id'], label=p.s.get('channel_label'))
    p.save()


@handler('PlayerPingReq')
def ping(ctx, req):
    ctx.reply({'status': OK, 'client_time_ms': str(req.get('client_time_ms', 0)), 'server_time_ms': str(now_ms())})


@handler('PlayerSceneRecordReq')
def scene_record(ctx, req):
    pos = req.get('pos') or req.get('Pos')
    if pos:
        ctx.p.s['last_pos'] = pos
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
    ctx.reply({'status': OK, 'nickName': ctx.p.s['name']})


# ============================================================ scenes / channels
PUBLIC_SCENE = 9999


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
              'outfitPreset': {k: v for k, v in op.items() if k in ('hat', 'hair', 'clothes', 'ornament') or k.startswith('pend') and not k.endswith('Index')},
              'weaponId': w.get('weaponId', 0), 'weaponStar': w.get('star', 1)}
        if s.get('last_pos'):
            sc['Pos'] = s['last_pos']
        team[slot] = sc
    return {'player_id': s['player_id'], 'player_name': s['name'], 'team': team,
            'avatar_frame': s.get('appearance', {}).get('avatar_frame', 0), 'phone_case': s.get('phone_case', 0),
            'foodBuffIds': [int(b) for b, e in s.get('buffs', {}).items() if e > time.time()]}


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
    if owner is not None:
        data['sceneGardenData'] = garden_data(ctx, owner)
        data['placedCharacters'] = [{'characterId': c} for c in owner.s.get('placed_characters', [])][:0]
    if before_push:
        before_push(channel_id, chan_label)
    ctx.push('SceneDataNotice', {'status': OK, 'data': data})
    ctx.server.join_channel(ctx, scene_id, channel_id)
    Q.on_scene(p, scene_id)
    return channel_id, chan_label


@handler('ChangeSceneChannelReq')
def change_scene(ctx, req):
    if req.get('pos'):
        ctx.p.s['last_pos'] = req['pos']
    sid = req.get('scene_id') or PUBLIC_SCENE
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
    ctx.reply({'status': OK, 'playerId': ctx.p.s['player_id'], 'chairId': req.get('chairId', 0),
               'seatId': req.get('seatId', 0), 'isSit': req.get('isSit', False)})


# ============================================================ chat (+ GM commands)
@handler('SendChatMsgReq')
def chat(ctx, req):
    text = req.get('text', '')
    ctx.reply({'status': OK, 'text': text})
    if text.startswith('/') and ctx.p.s.get('gm'):
        out = gm_command(ctx, text)
        ctx.push('ChatMsgNotice', {'status': OK, 'type': req.get('type', 'ChatChannelType_None'),
                                   'msg': {'playerId': 0, 'name': 'Rozefield', 'text': out, 'sendTime': str(now_ms())}})
        return
    s = ctx.p.s
    msg = {'playerId': s['player_id'], 'head': s['head'], 'name': s['name'], 'text': text,
           'expression': req.get('expression', 0), 'sendTime': str(now_ms()),
           'avatarFrame': s.get('appearance', {}).get('avatar_frame', 0)}
    # the sender's client already shows its own line from SendChatMsgRsp (official server never echoes it back)
    ctx.server.broadcast(ctx, 'ChatMsgNotice', {'status': OK, 'type': req.get('type', 'ChatChannelType_None'), 'msg': msg},
                         include_self=False)


def gm_command(ctx, text):
    a = text.split()
    cmd = a[0].lower()
    p = ctx.p
    try:
        if cmd == '/give' and len(a) >= 2:
            iid, n = int(a[1]), int(a[2]) if len(a) > 2 else 1
            got, changed = p.add_item(iid, n); pack(ctx, changed); p.save()
            return f'gave {n} x {iid} ({ctx.d.item_tag(iid)})'
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
    return 'commands: /give <itemId> [n], /all <materials|outfits|consumables|furniture|everything> [n], /currency [n], /level <n>, /char <characterId>'


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
    pc = ctx.p.s['placed_characters']
    cid = req.get('character_id')
    if req.get('is_remove'):
        if cid in pc:
            pc.remove(cid)
    elif cid not in pc:
        pc.append(cid)
    ctx.p.dirty = True
    ctx.reply({'status': OK, **{k: req[k] for k in ('character_id', 'furniture_id', 'seat_id', 'is_remove') if k in req}})


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
    return (grid or {}).get('Items', [])


@handler('ShopInfoReq')
def shop_info(ctx, req):
    sid = req.get('shopId')
    bought = ctx.p.s['shop'].get(str(sid), {})
    grids = []
    for g in shop_grids(ctx, sid):
        grids.append({'id': sid, 'gridId': g['GridID'], 'poolId': g['ShopPoolID'], 'poolIndex': g.get('Index', g['GridID']),
                      'buyTimes': bought.get(str(g['GridID']), 0)})
    ctx.reply({'status': OK, 'shopId': sid, 'grids': grids})


@handler('ShopBuyReq')
def shop_buy(ctx, req):
    p, d = ctx.p, ctx.d
    sid, gid, times = req.get('shopId'), req.get('gridId'), max(1, req.get('buyTimes', 1))
    g = next((x for x in shop_grids(ctx, sid) if x['GridID'] == gid), None)
    if not g:
        return ctx.reply({'status': FAIL})
    bought = p.s['shop'].setdefault(str(sid), {})
    have = bought.get(str(gid), 0)
    if g.get('BuyMaxCount', -1) > 0 and have + times > g['BuyMaxCount']:
        return ctx.reply({'status': FAIL})
    pool = d.row('shop', 'Pool', g['ShopPoolID']) or {'Items': []}
    entry = next((x for x in pool['Items'] if not req.get('itemId') or x.get('ItemID') == req['itemId']), None)
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
    bought[str(gid)] = have + times
    p.dirty = True
    ctx.reply({'status': OK, 'shopId': sid, 'grids': {'id': sid, 'gridId': gid, 'poolId': g['ShopPoolID'],
                                                      'poolIndex': g.get('Index', gid), 'buyTimes': have + times}, 'items': got})
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


def _furniture_notice(ctx, item):
    ctx.push('FurnitureItemChangeNotice', {'status': OK, 'furnitureItemInfo': {'itemId': item, 'num': str(ctx.p.count(item))}})


@handler('HandingFurnitureReq')
def handing(ctx, req):
    p = ctx.p
    if p.count(req.get('itemId')) <= 0:
        return ctx.reply({'status': FAIL})
    fid = new_furniture_id(p)
    _handing(p)[str(fid)] = {'itemId': req.get('itemId'), 'lifted': False}
    ctx.reply({'status': OK, 'furnitureId': str(fid)})


@handler('TakeOutHandingFurnitureReq')
def take_handing(ctx, req):
    """Put the held piece away: a piece lifted from the plaza goes back to the bag."""
    p = ctx.p
    h = _handing(p).pop(str(req.get('furnitureId')), None)
    if h and h.get('lifted'):
        p.add_item(h['itemId'], 1)
        _furniture_notice(ctx, h['itemId'])
    p.dirty = True
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
    if consume:  # a new piece from the bag
        if p.remove_item(item, 1) is None:
            return ctx.reply({'status': FAIL})
    if fid:
        _handing(p).pop(fid, None)
    fid = fid or str(new_furniture_id(p))
    info = {'furnitureId': fid, 'furnitureItemId': item, 'pos': req.get('pos', {}), 'rotation': req.get('rot', {})}
    if req.get('layerNum'):
        info['layerNum'] = req['layerNum']
    g[fid] = info
    p.dirty = True
    ctx.reply({'status': OK, 'furnitureDetailsInfo': info})
    Q.event(p, Q.C['PlacingFurniture0'])
    ctx.server.broadcast(ctx, 'SceneGardenFurnitureUpdateNotice', {'status': OK, 'furniture_info': info}, include_self=False)
    if consume:
        _furniture_notice(ctx, item)


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
    got, changed = p.add_item(f['furnitureItemId'], 1)
    ctx.server.broadcast(ctx, 'SceneGardenFurnitureRemoveNotice', {'status': OK, 'furniture_id': fid, 'item_id': f['furnitureItemId'],
                                                                   'updateItems': changed})
    _furniture_notice(ctx, f['furnitureItemId'])


def _clear_garden(p):
    fur = p.s['garden']['furniture']
    for fid, f in list(fur.items()):
        p.add_item(f['furnitureItemId'], 1)
    fur.clear()
    for h in _handing(p).values():
        if h.get('lifted'):
            p.add_item(h['itemId'], 1)
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
    have = {}
    for f in p.s['garden']['furniture'].values():
        have[f['furnitureItemId']] = have.get(f['furnitureItemId'], 0) + 1
    missing = [i for i, n in need.items() if p.count(i) + have.get(i, 0) < n]
    ctx.reply({'status': OK, 'scheme_id': req.get('scheme_id', 0), 'furnitureItemId': missing})


@handler('GardenFurnitureApplySchemeReq')
def scheme_apply(ctx, req):
    p = ctx.p
    sc = _schemes(p).get(str(req.get('scheme_id', 0)), {}).get('furniture', {})
    _clear_garden(p)
    fur = p.s['garden']['furniture']
    for fid, f in sc.items():
        if p.remove_item(f['furnitureItemId'], 1) is not None:
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
    ap = ch.setdefault('characterAppearance', {})
    ap.update(req.get('appearance', {}))
    for k in [k for k, v in ap.items() if not v]:
        ap.pop(k)
    p.dirty = True
    ctx.reply({'status': OK, 'charId': cid, 'appearance': ap})


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
    q = Q.accept(ctx.p, req.get('questId', 0))
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
    ctx.reply({'status': OK, 'quest': {'questId': sid, 'status': 'QuestStatus_Finish', 'completeCount': 1}, 'items': got})


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
    elif name == 'GetCharacterAchievementListReq':
        r['characterId'] = req.get('characterId', 0)
    elif name in ('GenericSceneBReq', 'GenericGameBReq'):
        r['generic_msg_id'] = req.get('generic_msg_id', 0)
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
    Q.event(ctx.p, Q.C['Emotion'])


@handler('ChangeMusicalItemReq')
def musical_item(ctx, req):
    iid = req.get('musical_item_instance_id', '0')
    p = ctx.p
    item_id = int(iid) if p.count(int(iid or 0)) > 0 else 0
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
    col = req.get('specifyColor') or {'red': random.randint(0, 255), 'green': random.randint(0, 255), 'blue': random.randint(0, 255)}
    col = dict(col, pos=req.get('pos', 0))
    p.s.setdefault('dye_pending', {})[str(oid)] = {'schemeIndex': req.get('schemeIndex', 0), 'color': col}
    p.s['dye_total'] = p.s.get('dye_total', 0) + 1
    p.dirty = True
    ctx.reply({'status': OK, 'outfitId': oid, 'posColor': col, 'totalGuaranteeDyeNum': p.s['dye_total']})


@handler('OutFitDyeSaveReq')
def outfit_dye_save(ctx, req):
    p = ctx.p
    oid = str(req.get('outfitId', 0))
    pend = p.s.setdefault('dye_pending', {}).pop(oid, None)
    si = req.get('schemeIndex', 0)
    col = pend['color'] if pend else {'pos': req.get('pos', 0)}
    if pend and req.get('isSaveDyeResult', True):
        o = p.s['outfits'].setdefault(oid, {'outfitId': int(oid)})
        schemes = o.setdefault('dyeSchemes', [])
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
