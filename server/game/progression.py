"""Character growth, posters, profile, presets, pets, travel to friends, world level, achievements.

All costs and caps come from the client tables:
  * character level   Character.GrowthLevelID -> Level.LevelInfo (NeedExp, ExpToCoin gold per exp, NeedPlayerLevel);
                      exp books 190/191/192 give Item.RelateID exp each; capped by the character's maxLevel
  * level break       LevelRule[RuleID].LevelRuleInfo: at TopLevel pay RuleNeedItem -> maxLevel = TopMaxLevel
  * star up           CharacterStar[charId].StarInfo[star+1]: ItemID x ItemNum (the character's fragments)
  * skill up          SpellInfo[skill].SpellConfigureItems[level].CostID -> SpellLevelUpInfo (ItemID[], Num[])
  * achievements      AchieveQuestGroup (manual "Achievements" tabs): counted from the same actions as quests,
                      each claimable once for its RewardID; a group's reward (AchieveQuest) once all are claimed
"""
import json

from game import quests as Q
from ofproto import pool

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
from game import packs as _packs
EXP_BOOKS = tuple(_packs.system('progression', 'exp_books', [190, 191, 192]))
EN = {v.name[len('EAchieveCondition_'):]: v.number for v in pool.FindEnumTypeByName('pb.EAchieveCondition').values}


def ach_event(p, name, key=None, n=1, absolute=None):
    if name in EN:
        Q.event(p, EN[name], key, n, absolute)


# ------------------------------------------------------------------ achievements (manual tabs)
_AIDX = {}


def aidx(d):
    if id(d) not in _AIDX:
        groups = {g['ID']: [i['AchieveConditionID'] for i in g.get('AchieveQuestGroupInfo', [])]
                  for g in d.table('achievequest', 'AchieveQuestGroup').values()}
        reward = {i['AchieveConditionID']: i.get('RewardID') for g in d.table('achievequest', 'AchieveQuestGroup').values()
                  for i in g.get('AchieveQuestGroupInfo', [])}
        group_reward = {q['AchieveGroupID']: q.get('RewardID') for q in d.table('achievequest', 'AchieveQuest').values()}
        by_type = {}
        ach = d.table('achieve', 'Achieve')
        for aid in reward:
            t = (ach.get(aid) or {}).get('NewAchieveCondition')
            by_type.setdefault(t, []).append(aid)
        _AIDX[id(d)] = {'groups': groups, 'reward': reward, 'group_reward': group_reward, 'by_type': by_type, 'ach': ach}
    return _AIDX[id(d)]


def astate(p):
    a = p.s.get('achievements')
    if a is None:
        a = p.s['achievements'] = {'count': {}, 'rewarded': [], 'groups': [], 'finish': {}}
        for body in p.s.get('records', {}).get('GetAchieveOneGroupReq', {}).values():   # archived official progress
            g = body.get('currentGroupAchieveInfo', {})
            for x in g.get('achieveLst', []):
                a['count'][str(x['achieveId'])] = int(x.get('count', 0))
            a['rewarded'] += [i for i in g.get('rewardedAchieveIdLst', []) if i not in a['rewarded']]
            for f in g.get('finishAchieveLst', []):
                a['finish'][str(f['achieveId'])] = f.get('finishTime', '0')
        for body in p.s.get('records', {}).get('GetAchieveGroupListReq', {}).values():
            a['groups'] = body.get('rewardedGroupIdLst', [])
        p.dirty = True
    return a


def on_event(p, ctype, key, n, absolute):
    """Called by the quest engine for every action: move the manual achievements of that type."""
    ix = aidx(p.d)
    aids = ix['by_type'].get(ctype)
    if not aids:
        return
    a = astate(p)
    changed = []
    for aid in aids:
        cfg = ix['ach'].get(aid) or {}
        par = cfg.get('Param') or []
        if par and key is not None and key not in par:
            continue
        if par and key is None:
            continue
        need = int(cfg.get('CountParam', 1) or 1)
        cur = a['count'].get(str(aid), 0)
        if cur >= need:
            continue
        new = min(need, absolute if absolute is not None else cur + n)
        if new != cur:
            a['count'][str(aid)] = new
            if new >= need:
                import time
                a['finish'][str(aid)] = str(int(time.time()))
            changed.append({'achieveId': aid, 'count': str(new)})
    if changed:
        p.__dict__.setdefault('_achanged', []).extend(changed)
        p.dirty = True


def group_info(p, gid):
    a = astate(p)
    aids = aidx(p.d)['groups'].get(gid, [])
    return {'groupId': gid,
            'rewardedAchieveIdLst': [i for i in a['rewarded'] if i in aids],
            'achieveLst': [{'achieveId': i, 'count': str(a['count'][str(i)])} for i in aids if a['count'].get(str(i))],
            'finishAchieveLst': [{'achieveId': i, 'finishTime': a['finish'][str(i)]} for i in aids if str(i) in a['finish']]}


# ------------------------------------------------------------------ helpers
def ch_of(p, cid):
    return p.s['characters'].get(str(cid))


def level_rows(p, ch):
    c = p.d.row('character', 'Character', ch['characterId']) or {}
    lv = p.d.row('character', 'Level', c.get('GrowthLevelID', 1)) or {}
    return {r['Level']: r for r in lv.get('LevelInfo', [])}


def register(H, pack, enter_scene, PUBLIC_SCENE):
    d_ok = lambda ctx, extra=None: ctx.reply(dict({'status': OK}, **(extra or {})))

    def level_up(ctx, req):
        p = ctx.p
        ch = ch_of(p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        nums = [int(x) for x in req.get('nums', [])]
        books = [(b, nums[i]) for i, b in enumerate(EXP_BOOKS) if i < len(nums) and nums[i] > 0]
        gain = sum((p.d.row('item', 'Item', b) or {}).get('RelateID', 0) * n for b, n in books)
        rows = level_rows(p, ch)
        if ch.get('level', 1) >= ch.get('maxLevel', 20):   # at the cap: needs a level break first, keep the books
            return ctx.reply({'status': FAIL})
        cost_gold = int(gain * (rows.get(ch.get('level', 1)) or {}).get('ExpToCoin', 0))
        paid = p.pay(books + ([(101, cost_gold)] if cost_gold else []))
        if paid is None or not gain:
            return ctx.reply({'status': FAIL})
        lvl, exp, cap = ch.get('level', 1), ch.get('exp', 0) + gain, ch.get('maxLevel', 20)
        while lvl < cap and exp >= (rows.get(lvl) or {}).get('NeedExp', 10 ** 12) and \
                (rows.get(lvl + 1) or {}).get('NeedPlayerLevel', 1) <= p.s['level']:
            exp -= rows[lvl]['NeedExp']
            lvl += 1
        if lvl >= cap:
            exp = min(exp, max(0, (rows.get(lvl) or {}).get('NeedExp', 1) - 1))
        ch['level'], ch['exp'] = lvl, exp
        p.dirty = True
        ctx.reply({'status': OK, 'charId': ch['characterId'], 'level': lvl, 'exp': exp})
        pack(ctx, paid)
        ach_event(p, 'CharacterLv', ch['characterId'], absolute=lvl)
    H['CharacterLevelUpReq'] = level_up

    def level_break(ctx, req):
        p = ctx.p
        ch = ch_of(p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        c = p.d.row('character', 'Character', ch['characterId']) or {}
        rule = next((r for r in (p.d.row('character', 'LevelRule', c.get('RuleID')) or {}).get('LevelRuleInfo', [])
                     if r.get('TopLevel') == ch.get('maxLevel', 20)), None)
        if not rule or ch.get('level', 1) < ch.get('maxLevel', 20):
            return ctx.reply({'status': FAIL})
        paid = p.pay([(x['NeedItemID'], x.get('NeedItemCount', 1)) for x in rule.get('RuleNeedItem', [])])
        if paid is None:
            return ctx.reply({'status': FAIL})
        ch['maxLevel'] = rule['TopMaxLevel']
        p.dirty = True
        ctx.reply({'status': OK, 'charId': ch['characterId'], 'level': ch['level'], 'exp': ch.get('exp', 0), 'maxLevel': ch['maxLevel']})
        pack(ctx, paid)
        ach_event(p, 'CharacterLvBreak', ch['characterId'])
        ach_event(p, 'CharacterBreakNum')
    H['CharacterLevelBreakReq'] = level_break

    def star_up(ctx, req):
        p = ctx.p
        ch = ch_of(p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        row = next((x for x in (p.d.row('character', 'CharacterStar', ch['characterId']) or {}).get('StarInfo', [])
                    if x.get('Star') == ch.get('star', 1) + 1), None)
        if not row:
            return ctx.reply({'status': FAIL})
        frag = row.get('ItemID') or (p.d.row('character', 'Character', ch['characterId']) or {}).get('RepeatItemID')
        paid = p.pay([(frag, row.get('ItemNum', 1))])
        if paid is None:
            return ctx.reply({'status': FAIL})
        ch['star'] = ch.get('star', 1) + 1
        p.dirty = True
        ctx.reply({'status': OK, 'charId': ch['characterId'], 'star': ch['star'], 'items': paid})
        pack(ctx, paid)
        ach_event(p, 'CharacterStar', ch['characterId'], absolute=ch['star'])
    H['CharacterStarUpReq'] = star_up

    def skill_up(ctx, req):
        p = ctx.p
        ch = ch_of(p, req.get('char_id'))
        sid = req.get('skill_id', 0)
        if not ch:
            return ctx.reply({'status': FAIL})
        skills = ch.setdefault('characterSkillList', [])
        sk = next((s for s in skills if s.get('skillId') == sid), None)
        if sk is None:
            sk = {'skillId': sid, 'skillLevel': 1}
            skills.append(sk)
        items = (p.d.row('spell', 'SpellInfo', sid) or {}).get('SpellConfigureItems', [])
        cur = next((x for x in items if x.get('Level') == sk['skillLevel']), None)
        if not cur or not any(x.get('Level') == sk['skillLevel'] + 1 for x in items):
            return ctx.reply({'status': FAIL})
        cost = []
        for c in (p.d.row('spell', 'SpellLevelUpInfo', cur.get('CostID')) or {}).get('SpellLevelUpInfoItem', []):
            cost += list(zip(c.get('ItemID', []), c.get('Num', [])))
        paid = p.pay(cost)
        if paid is None:
            return ctx.reply({'status': FAIL})
        sk['skillLevel'] += 1
        p.dirty = True
        ctx.reply({'status': OK, 'char_id': ch['characterId'], 'items': paid, 'skill': sk})
        pack(ctx, paid)
        ach_event(p, 'CharacterSkillUp0')
    H['CharacterSkillLevelUpReq'] = skill_up

    def poster_star(ctx, req):
        p = ctx.p
        po = p.s['posters'].get(str(req.get('posterInstanceId')))
        costs = [str(i) for i in req.get('costPosterInstanceId', [])]
        if not po or not costs or any(c not in p.s['posters'] or c == str(po['instanceId']) for c in costs):
            return ctx.reply({'status': FAIL})
        for c in costs:
            del p.s['posters'][c]
        po['star'] = min(5, po.get('star', 1) + len(costs))
        p.dirty = True
        ctx.reply({'status': OK, 'posterInstanceId': po['instanceId'], 'costPosterInstanceId': [int(c) for c in costs], 'star': po['star']})
        ach_event(p, 'PosterStarUPNum')
    H['PosterStarUpReq'] = poster_star

    def level_reward(ctx, req):
        p = ctx.p
        lv = req.get('level', 0)
        got_lv = p.s.setdefault('level_rewards', [])
        row = p.d.row('level', 'PlayerLevel', lv) or {}
        if lv > p.s['level'] or lv in got_lv:
            return ctx.reply({'status': FAIL})
        items = p.d.reward_items(row['RewardID'], p.s['level']) if row.get('RewardID') and row['RewardID'] < 999999999 else []
        got, changed = p.add_items(items) if items else ([], [])
        got_lv.append(lv)
        p.dirty = True
        ctx.reply({'status': OK, 'level': lv, 'items': got})
        pack(ctx, changed)
    H['PlayerLevelRewardReq'] = level_reward

    # ---- profile
    def setter(field, key, req_key=None, rsp_key=None):
        def f(ctx, req):
            v = req.get(req_key or key)
            ctx.p.s[field] = v
            ctx.p.dirty = True
            ctx.reply({'status': OK, rsp_key or key: v})
        return f
    H['ChangeHeadReq'] = setter('head', 'head')
    H['ChangeSignReq'] = setter('sign', 'sign')
    H['ChangePhoneBackgroundReq'] = setter('phone_background', 'phoneBackground')
    H['ChangePhoneCaseReq'] = setter('phone_case', 'phoneCase')
    H['ChangePlayerSexReq'] = setter('sex', 'sex')

    def hide_bday(ctx, req):
        ctx.p.s['hide_birthday'] = not ctx.p.s.get('hide_birthday', False)
        ctx.p.dirty = True
        d_ok(ctx)
    H['ChangeIsHideBirthdayReq'] = hide_bday

    # ---- presets
    def outfit_switch(ctx, req):
        ch = ch_of(ctx.p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        ch['inUseOutfitPresetIndex'] = req.get('usePresetIndex', 0)
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'charId': ch['characterId'], 'usePresetIndex': ch['inUseOutfitPresetIndex']})
    H['OutfitPresetSwitchReq'] = outfit_switch

    def outfit_hide(ctx, req):
        ch = ch_of(ctx.p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        i = ch.get('inUseOutfitPresetIndex', 0)
        pres = ch.setdefault('outfitPresets', [])
        while len(pres) <= i:
            pres.append({'presetIndex': len(pres)})
        pres[i]['outfitHideInfo'] = req.get('hideInfo', {})
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'charId': ch['characterId'], 'hideInfo': req.get('hideInfo', {})})
    H['OutfitHideSwitchReq'] = outfit_hide

    def equip_switch(ctx, req):
        ch = ch_of(ctx.p, req.get('charId'))
        if not ch:
            return ctx.reply({'status': FAIL})
        ch['inUseEquipmentPresetIndex'] = req.get('presetIndex', 0)
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'presetIndex': ch['inUseEquipmentPresetIndex']})
    H['CharacterEquipPresetSwitchReq'] = equip_switch

    # ---- pets
    def change_pet(ctx, req):
        ctx.p.s['pet_instance_id'] = req.get('pet_instance_id', 0)
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'pet_instance_id': ctx.p.s['pet_instance_id']})
    H['ChangePetReq'] = change_pet

    def rename_pet(ctx, req):
        pet = ctx.p.s['pets'].get(str(req.get('pet_instance_id')))
        if not pet:
            return ctx.reply({'status': FAIL})
        pet['name'] = req.get('name', '')
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'pet_instance_id': req.get('pet_instance_id'), 'name': pet['name']})
    H['PetRenameReq'] = rename_pet

    def capture_pet(ctx, req):
        p = ctx.p
        m = p.d.row('monster', 'MonsterCharacterData', req.get('monster_id', 0)) or {}
        pid = m.get('PetID')
        if not pid:
            return ctx.reply({'status': OK, 'success': False})
        hp, mx = req.get('hp', 1), max(1, req.get('max_hp', 1))
        import random
        ok = random.random() < max(0.2, 1 - hp / mx)
        if not ok:
            return ctx.reply({'status': OK, 'success': False})
        got, changed = p.add_items([(pid, 1)])
        ctx.reply({'status': OK, 'success': True, 'items': got})
        pack(ctx, changed)
    H['PetCaptureReq'] = capture_pet

    # ---- travel to a friend's garden (Friends list -> Visit)
    def visit(field, rsp_label):
        def f(ctx, req):
            o = ctx.server.player_by_id(req.get(field))
            if not o:
                return ctx.reply({'status': FAIL})

            def before(c, l):
                body = {'status': OK, 'scene_id': PUBLIC_SCENE, 'channel_id': c}
                if rsp_label:
                    body['channel_label'] = l
                ctx.reply(body)
            if enter_scene(ctx, PUBLIC_SCENE, target_label=o.s['player_label'], before_push=before) is None:
                ctx.reply({'status': FAIL})
        return f
    H['SceneTransmitReq'] = visit('player_id', True)
    H['TransmitSceneReq'] = visit('friend_id', False)

    # ---- friends (everyone on this server is listed as a friend)
    H['FriendAddReq'] = lambda ctx, req: d_ok(ctx)
    H['FriendHandleReq'] = lambda ctx, req: d_ok(ctx)
    H['FriendDelReq'] = lambda ctx, req: d_ok(ctx)
    H['FriendBlackReq'] = lambda ctx, req: d_ok(ctx)

    def search(ctx, req):
        q = (req.get('searchArgs') or '').strip().lower()
        for pid in ctx.server.all_player_ids():
            o = ctx.server.player_by_id(pid)
            if o and (str(o.s['player_label']) == q or str(pid) == q or o.s['name'].lower() == q):
                s = o.s
                return ctx.reply({'status': OK, 'data': {'playerId': pid, 'nickName': s['name'], 'level': s['level'], 'head': s['head'],
                                                         'sign': s['sign'], 'createTime': s['create_time'], 'playerLabel': s['player_label'],
                                                         'isOnline': ctx.server.is_online(pid), 'account_type': 16666},
                                  'friendStatus': 'FriendStatus_FRIEND'})
        ctx.reply({'status': FAIL})
    H['FriendSearchReq'] = search

    # ---- world level, misc
    def world(field):
        def f(ctx, req):
            ctx.p.s['world_level'] = req.get('world_level', ctx.p.s.get('world_level', 1))
            ctx.p.dirty = True
            ctx.reply({'status': OK, 'world_level': ctx.p.s['world_level']})
        return f
    H['UnlockWorldLevelReq'] = world('unlock')
    H['ChangeWorldLevelReq'] = world('change')
    H['CharacterDeadReq'] = lambda ctx, req: d_ok(ctx)
    H['CharacterReviveReq'] = lambda ctx, req: d_ok(ctx)

    def insc_remove(ctx, req):
        w = ctx.p.s['weapons'].get(str(req.get('weaponInstanceId')))
        if not w:
            return ctx.reply({'status': FAIL})
        w.pop('inscription1', None)
        ctx.p.dirty = True
        ctx.reply({'status': OK, 'weaponInstanceId': req.get('weaponInstanceId')})
    H['WeaponInscriptionRemoveReq'] = insc_remove

    def mails(ctx, req):
        ctx.reply({'status': OK, 'operate_type': req.get('operate_type'), 'mails': []})
    H['OperateMailsReq'] = mails

    # ---- achievements (manual tabs)
    H['GetAchieveOneGroupReq'] = lambda ctx, req: ctx.reply(
        {'status': OK, 'currentGroupAchieveInfo': group_info(ctx.p, req.get('groupId', 0)),
         'isReward': req.get('groupId', 0) in astate(ctx.p)['groups']})
    H['GetAchieveGroupListReq'] = lambda ctx, req: ctx.reply({'status': OK, 'rewardedGroupIdLst': astate(ctx.p)['groups']})

    def one_award(ctx, req):
        p = ctx.p
        aid = req.get('achieveId', 0)
        a, ix = astate(p), aidx(p.d)
        need = int((ix['ach'].get(aid) or {}).get('CountParam', 1) or 1)
        if aid not in ix['reward'] or aid in a['rewarded'] or a['count'].get(str(aid), 0) < need:
            return ctx.reply({'status': FAIL})
        items = p.d.reward_items(ix['reward'][aid], p.s['level']) if ix['reward'][aid] else []
        got, changed = p.add_items(items) if items else ([], [])
        a['rewarded'].append(aid)
        p.dirty = True
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, changed)
    H['GetOneAchieveAwardReq'] = one_award

    def group_award(ctx, req):
        p = ctx.p
        gid = req.get('groupId', 0)
        a, ix = astate(p), aidx(p.d)
        aids = ix['groups'].get(gid, [])
        if not aids or gid in a['groups'] or any(i not in a['rewarded'] for i in aids):
            return ctx.reply({'status': FAIL})
        rid = ix['group_reward'].get(gid)
        items = p.d.reward_items(rid, p.s['level']) if rid else []
        got, changed = p.add_items(items) if items else ([], [])
        a['groups'].append(gid)
        p.dirty = True
        ctx.reply({'status': OK, 'rewards': got})
        pack(ctx, changed)
    H['GetAchieveGroupAwardReq'] = group_award


FRIEND_STATUS = set()
try:
    import ofproto as _o
    FRIEND_STATUS = {v.name for v in _o.msg_class('FriendSearchRsp').DESCRIPTOR.fields_by_name['friendStatus'].enum_type.values}
except Exception:
    pass
