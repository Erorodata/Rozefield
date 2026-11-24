"""Request handlers. Each handler: def on_<ReqName>(ctx, req) where req is a dict and ctx is the Session.

ctx.p        -> Player (state in ctx.p.s)
ctx.reply(dict)          -> response to the current request (Rsp type inferred)
ctx.push(name, dict)     -> server push (notice)
ctx.d        -> Data tables
"""
import random, time

H = {}


def handler(name):
    def deco(f):
        H[name] = f
        return f
    return deco


OK = 'StatusCode_OK'
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
                                            'furnitureNum': garden_points(ctx, ctx.p), 'furnitureLimitNum': 150000,
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
    ctx.server.broadcast(ctx, 'ChatMsgNotice', {'status': OK, 'type': req.get('type', 'ChatChannelType_None'), 'msg': msg})


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
        if cmd == '/char':
            got, changed = p.add_item(int(a[1]), 1); pack(ctx, changed); p.save()
            return 'character added (relog to see it)'
    except Exception as e:
        return f'error: {e}'
    return 'commands: /give <itemId> [n], /currency [n], /level <n>, /char <characterId>'


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
    ctx.reply({'status': OK, 'items': got, 'info': gacha_info(ctx, gid)})
    pack(ctx, paid + changed)


# ============================================================ garden furniture
def new_furniture_id(p):
    g = p.s['garden']
    fid = p.s['player_id'] * 100000 + g['next_furniture_id']
    g['next_furniture_id'] += 1
    return fid


@handler('HandingFurnitureReq')
def handing(ctx, req):
    p = ctx.p
    if p.count(req.get('itemId')) <= 0:
        return ctx.reply({'status': FAIL})
    fid = new_furniture_id(p)
    p.s.setdefault('handing', {})[str(fid)] = req.get('itemId')
    ctx.reply({'status': OK, 'furnitureId': str(fid)})


@handler('TakeOutHandingFurnitureReq')
def take_handing(ctx, req):
    ctx.p.s.setdefault('handing', {}).pop(str(req.get('furnitureId')), None)
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
    changed = []
    if not fid or fid not in g:
        if p.remove_item(item, 1) is None:
            return ctx.reply({'status': FAIL})
        changed.append({'mainItem': p.item_info(item)})
        fid = fid or str(new_furniture_id(p))
    p.s.setdefault('handing', {}).pop(fid, None)
    info = {'furnitureId': fid, 'furnitureItemId': item, 'pos': req.get('pos', {}), 'rotation': req.get('rot', {})}
    if req.get('layerNum'):
        info['layerNum'] = req['layerNum']
    g[fid] = info
    p.dirty = True
    ctx.reply({'status': OK, 'furnitureDetailsInfo': info})
    ctx.server.broadcast(ctx, 'SceneGardenFurnitureUpdateNotice', {'status': OK, 'furniture_info': info}, include_self=False)
    if changed:
        ctx.push('FurnitureItemChangeNotice', {'status': OK, 'furnitureItemInfo': {'itemId': item, 'num': str(p.count(item))}})


@handler('TakeOutFurnitureReq')
def take_out(ctx, req):
    p = ctx.p
    fid = str(req.get('furnitureId'))
    f = p.s['garden']['furniture'].pop(fid, None)
    if not f:
        return ctx.reply({'status': FAIL})
    got, changed = p.add_item(f['furnitureItemId'], 1)
    p.dirty = True
    ctx.reply({'status': OK, 'furnitureId': fid})
    ctx.push('SceneGardenFurnitureRemoveNotice', {'status': OK, 'furniture_id': fid, 'item_id': f['furnitureItemId'], 'updateItems': changed})
    ctx.push('FurnitureItemChangeNotice', {'status': OK, 'furnitureItemInfo': {'itemId': f['furnitureItemId'], 'num': str(p.count(f['furnitureItemId']))}})


@handler('GardenFurnitureRemoveAllReq')
def remove_all(ctx, req):
    p = ctx.p
    fur = p.s['garden']['furniture']
    for fid, f in list(fur.items()):
        p.add_item(f['furnitureItemId'], 1)
    fur.clear()
    p.dirty = True
    ctx.reply({'status': OK})
    enter_scene(ctx, PUBLIC_SCENE, label=p.s['player_label'])


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
