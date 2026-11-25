"""Life skills: cooking, sewing (spin), making, handicraft, fishing, gathering.

Rules follow the client tables (official behaviour, failures use up materials):
  * recipes  CookFood / SpinItem / MakeItem / HandicraftItem: level needed, energy cost (NeedItemID 11),
             materials, SuccessfulProbability, product (GetItemID), handbook achievements (<X>AchieveRewards)
  * levels   <X>Level rows: UpgradeLevelByProficiency, level-up cost, and level quests
             (AchieveConditionID, Proficiency per completion, CompleteLimit completions)
  * skills   <X>Spell rows: study cost, study time, level requirement
Every action also feeds the quest engine (cook X dishes, catch a fish, gather with the net...).
State: state['life'][<LifeType>] = {level, prof, skills {id: {lv, start}}, ach {achieveId: count}, rewarded [ids], book {item: n}}
"""
import random
import time

from game import quests as Q

OK, FAIL = 'StatusCode_OK', 'StatusCode_FAIL'
COOK, FISH, MAKE, HANDI, SEW, GATHER = ('LIFE_TYPE_Cooking', 'LIFE_TYPE_Fishing', 'LIFE_TYPE_Making',
                                        'LIFE_TYPE_Handicraft', 'LIFE_TYPE_Sewing', 'LIFE_TYPE_Gathering')
ENERGY = 11

# per crafting skill: table file, recipe sheet, level field, materials field, item/count keys, handbook field,
#                     level sheet, level-quest field, spell sheet, spell items field, spell level key,
#                     condition types (attempt, success, fail, success-with-item, total)
CRAFT = {
    COOK: dict(file='cooking', recipe='CookFood', lvkey='CookLevel', mats='CookFoodItems', mid='FoodItemID', mcnt='FoodItemCount',
               book='CookFoodQuestRewards', level='CookLevel', lq='CookLevelQuest', spell='CookSpell', spitems='CookSpellItems',
               spneed='NeedCookLevel', attempt=None, success=22, fail=23, item=20, total=168),
    SEW: dict(file='spin', recipe='SpinItem', lvkey='SpinLevel', mats='SpinItems', mid='ItemID', mcnt='ItemCount',
              book='SpinAchieveRewards', level='SpinLevel', lq='SpinLevelAchieve', spell='SpinSpell', spitems='SpinSpellItems',
              spneed='NeedSpinLevel', attempt=51, success=48, fail=None, item=57, total=None),
    MAKE: dict(file='make', recipe='MakeItem', lvkey='MakeLevel', mats='MakeItems', mid='ItemID', mcnt='ItemCount',
               book='MakeAchieveRewards', level='MakeLevel', lq='MakeLevelAchieve', spell='MakeSpell', spitems='MakeSpellItems',
               spneed='NeedMakeLevel', attempt=50, success=47, fail=None, item=56, total=None),
    HANDI: dict(file='handicraft', recipe='HandicraftItem', lvkey='HandicraftLevel', mats='HandicraftItems', mid='ItemID',
                mcnt='ItemCount', book='HandicraftAchieveRewards', level='HandicraftLevel', lq='HandicraftLevelAchieve',
                spell='HandicraftSpell', spitems='HandicraftSpellItems', spneed='NeedHandicraftLevel',
                attempt=49, success=46, fail=None, item=55, total=None),
    FISH: dict(file='fishing', level='FishingLevel', lq='FishingLevelQuest', spell='FishingSpell', spitems='FishingSpellItems',
               spneed='NeedFishLevel'),
    GATHER: dict(file='lifegather', level='LifeGather', lq='LifeGatherQuest', spell='LifeGatherSpell',
                 spitems='LifeGatherSpellItems', spneed='NeedGatherLevel'),
}
# gathering tools (EWeaponType) -> (use-count condition, gains condition)
TOOL_COND = {4: (61, 67), 5: (62, 68), 6: (63, 69), 7: (64, 70), 8: (65, 71), 15: (66, 72)}


def L(p, lt):
    life = p.s.setdefault('life', {})
    st = life.get(lt)
    if st is None:
        st = life[lt] = {'level': 1, 'prof': 0, 'skills': {}, 'ach': {}, 'rewarded': [], 'book': {}}
    return st


def migrate(p):
    """Seed life state from the archived official answers (records) the first time."""
    if 'life' in p.s:
        return
    p.s['life'] = {}
    rec = p.s.get('records', {})
    for body in rec.get('GetLifeInfoReq', {}).values():
        b = body.get('lifeBaseInfo', {})
        lt = b.get('lifeType')
        if not lt:
            continue
        st = L(p, lt)
        st['level'] = b.get('level', 1)
        st['prof'] = b.get('proficiencyValue', 0)
        for sk in body.get('lifeSkill', {}).get('lifeSkillInfo', []):
            st['skills'][str(sk['skillId'])] = {'lv': sk.get('lv', 0), 'start': int(sk.get('startStudyTime', -1))}
        la = body.get('lifeAchieve', {})
        for a in la.get('lifeAchieve', []):
            st['ach'][str(a['achieveId'])] = int(a.get('count', 0))
        st['rewarded'] = la.get('rewardedLifeAchieveIdLst', [])
    for k, body in rec.get('GetOneTypeLifePictorialBookCountReq', {}).items():
        import json
        lt = json.loads(k).get('life_type')
        if lt:
            st = L(p, lt)
            for c in body.get('lifeAchieveCountLst', []):
                st['book'][str(c['id'])] = int(c.get('count', 0))
    p.dirty = True


# ------------------------------------------------------------------ tables
def _tbl(p, lt, key):
    c = CRAFT[lt]
    return p.d.table(c['file'], c[key])


def level_row(p, lt, lv=None):
    rows = _tbl(p, lt, 'level')
    st = L(p, lt)
    return rows.get(lv or st['level']) or rows.get(1) or {}


# ------------------------------------------------------------------ progress
def life_event(p, lt, ctype, key=None):
    """Level quests of the current level give proficiency (each up to CompleteLimit times); quests move too."""
    if ctype is None:
        return
    st = L(p, lt)
    c = CRAFT[lt]
    for e in level_row(p, lt).get(c['lq'], []):
        aid = e.get('AchieveConditionID')
        a = Q.idx(p.d)['ach'].get(aid) or {}
        if a.get('NewAchieveCondition') != ctype:
            continue
        par = a.get('Param') or []
        if par and key not in par:
            continue
        n = st['ach'].get(str(aid), 0)
        if n < e.get('CompleteLimit', 1):
            st['ach'][str(aid)] = n + 1
            st['prof'] += e.get('Proficiency', 0)
    Q.event(p, ctype, key)
    p.dirty = True


def book_add(p, lt, item, rewards):
    st = L(p, lt)
    st['book'][str(item)] = st['book'].get(str(item), 0) + 1
    for r in rewards or []:
        aid = str(r.get('AchieveConditionID'))
        st['ach'][aid] = st['ach'].get(aid, 0) + 1


def base_info(p, lt):
    st = L(p, lt)
    return {'lifeType': lt, 'proficiencyValue': st['prof'], 'level': st['level']}


def skills(p, lt):
    st = L(p, lt)
    now = time.time()
    spells = _tbl(p, lt, 'spell')
    out = []
    for sid, sk in st['skills'].items():
        if sk.get('start', -1) > 0:   # studying: finishes after NeedTime
            row = next((x for x in (spells.get(int(sid)) or {}).get(CRAFT[lt]['spitems'], []) if x.get('Level') == sk['lv'] + 1), {})
            if now >= sk['start'] + row.get('NeedTime', 0):
                sk['lv'] += 1; sk['start'] = -1; p.dirty = True
        out.append({'skillId': int(sid), 'lv': sk['lv'], 'startStudyTime': str(int(sk.get('start', -1)))})
    return out


def achieve(p, lt):
    st = L(p, lt)
    return {'lifeType': lt, 'lifeAchieve': [{'achieveId': int(k), 'count': str(v)} for k, v in st['ach'].items()],
            'rewardedLifeAchieveIdLst': st['rewarded']}


# ------------------------------------------------------------------ handlers
def register(H, pack):
    def craft(lt, field):
        def f(ctx, req):
            p, c = ctx.p, CRAFT[lt]
            rid = req.get(field, 0)
            r = _tbl(p, lt, 'recipe').get(rid)
            st = L(p, lt)
            if not r or r.get(c['lvkey'], 1) > st['level']:
                return ctx.reply({'status': FAIL})
            if r.get('NeedFormulaItemID') and p.count(r['NeedFormulaItemID']) <= 0 and \
                    r['NeedFormulaItemID'] not in p.s.get('unlock_functions', []):
                return ctx.reply({'status': FAIL})
            cost = [(m[c['mid']], m.get(c['mcnt'], 1)) for m in r.get(c['mats'], []) if m.get(c['mid'])]
            if r.get('NeedItemID'):
                cost.append((r['NeedItemID'], r.get('NeedItemCount', 1)))
            paid = p.pay(cost)
            if paid is None:
                return ctx.reply({'status': FAIL})
            life_event(p, lt, c['attempt'])
            ok = random.random() < r.get('SuccessfulProbability', 1.0)
            res = {'isSuccess': ok, 'lifeType': lt}
            changed = list(paid)
            if ok:
                got, ch = p.add_items([(r['GetItemID'], 1)])
                res['resultItems'] = got
                changed += ch
                book_add(p, lt, r['GetItemID'], r.get(c['book']))
                life_event(p, lt, c['success'])
                life_event(p, lt, c['item'], r['GetItemID'])
                life_event(p, lt, c['total'])
            else:
                life_event(p, lt, c['fail'])
            ctx.reply({'status': OK, 'lifeCommonResult': res})
            pack(ctx, changed)
        return f

    H['CookingFoodReq'] = craft(COOK, 'food_id')
    H['SewingReq'] = craft(SEW, 'Sewing_id')
    H['MakePropReq'] = craft(MAKE, 'make_id')
    H['HandicraftReq'] = craft(HANDI, 'handicraft_id')

    def fishing(ctx, req):
        """Official flow: FishingRsp at once with the fishing time and the events the minigame plays, then after
        costTime seconds FishingResultNotice with the new bait box / energy / fish totals."""
        p = ctx.p
        pending = ctx.__dict__.pop('fishing', None)
        if pending:
            pending.cancel()
        if req.get('is_cancel'):
            ctx.reply({'status': OK, 'isCancel': True})
            life_event(p, FISH, 27)
            return
        st = L(p, FISH)
        lv = level_row(p, FISH)
        cost = [(lv['NeedItemID'], lv.get('NeedItemCount', 1))] if lv.get('NeedItemID') else []
        box = req.get('fishing_box_id', 0)
        if box and p.count(box) > 0:
            cost.append((box, 1))
        if cost and any(p.count(i) < n for i, n in cost):
            return ctx.reply({'status': FAIL})
        fish = [f for f in p.d.table('fishing', 'FishingInfo').values() if f.get('NeedLevel', 1) <= st['level']]
        pond = p.d.row('fishpond', 'FishPond', req.get('fishing_pond_id', 0)) or {}
        pool = [i for i, _ in p.d.reward_items(int(pond.get('FishPondPool', 0) or 0))] if pond else []
        cand = [f for f in fish if f['ItemID'] in pool] or fish
        catch = random.sample(cand, min(len(cand), 2 if random.random() < 0.15 else 1)) if cand else []
        infos = [{'ID': f['ItemID'], 'length': round(random.uniform(f.get('MinSize', 10), f.get('MaxSize', f.get('MinSize', 10) + 10)), 2)}
                 for f in catch]
        evs = []
        table = list(p.d.table('fishing', 'FishingEvent').values())
        for _ in range(random.choice((0, 1, 1, 2, 3))):
            e = random.choice(table) if table else None
            if e and e.get('FishingEventItems'):
                evs.append({'ID': e['ID'], 'index': random.choice(e['FishingEventItems'])['Index']})
        secs = random.randint(5, 17)
        res = {'costEndurance': random.choice((1, 2, 5, 50)), 'costTime': secs, 'fishInfos': infos}
        if evs:
            res['fishingEventList'] = evs
        ctx.reply({'status': OK, 'fishingEventResult': res})

        def done():
            ctx.__dict__.pop('fishing', None)
            paid = p.pay(cost) if cost else []
            if paid is None:
                return
            changed = list(paid)
            for f in catch:
                got, ch = p.add_items([(f['ItemID'], 1)])
                changed += ch
                book_add(p, FISH, f['ItemID'], f.get('FishAchieveRewards'))
                life_event(p, FISH, 26)
                life_event(p, FISH, 28, f['ItemID'])
                Q.event(p, Q.C['CatchTheSea'])
            try:
                ctx.push('FishingResultNotice', {'status': OK, 'items': changed})
                flush = getattr(ctx, 'flush', None)
                if flush:
                    flush()
            except Exception:
                pass
            p.dirty = True
        try:
            import asyncio
            ctx.__dict__['fishing'] = asyncio.get_running_loop().call_later(secs, done)
        except RuntimeError:
            done()
    H['FishingReq'] = fishing

    gather_tool = {}

    def tool_of(d, reward):
        if not gather_tool:
            for g in d.table('gather', 'Gather').values():
                for gi in g.get('GatherGroupInfo', []):
                    gather_tool.setdefault(gi.get('Reward'), gi.get('NewWeaponType', 15))
        return gather_tool.get(reward, 15)

    def gather(ctx, req):
        p = ctx.p
        gi = req.get('gatherItem', {})
        rw = p.d.row('gather', 'GatherReward', gi.get('Reward', 0)) or {}
        items = [(x['ItemID'], x.get('Count', 1)) for x in rw.get('GatherRewardGroupInfo', []) if x.get('ItemID')]
        got, changed = p.add_items(items) if items else ([], [])
        ctx.reply({'status': OK, 'index': gi.get('Index', 0), 'items': got})
        use, gains = TOOL_COND.get(tool_of(p.d, gi.get('Reward', 0)), TOOL_COND[15])
        life_event(p, GATHER, use)
        lg = p.d.table('lifegather', 'LifeGatherItem')
        for iid, n in items:
            life_event(p, GATHER, gains, iid)
            if iid in lg:
                book_add(p, GATHER, iid, lg[iid].get('LifeGatherAchieveRewards'))
        pack(ctx, changed)
    H['GatherReq'] = gather

    def info(ctx, req):
        lt = req.get('life_type', COOK)
        ctx.reply({'status': OK, 'lifeBaseInfo': base_info(ctx.p, lt), 'lifeSkill': {'lifeType': lt, 'lifeSkillInfo': skills(ctx.p, lt)},
                   'lifeAchieve': achieve(ctx.p, lt)})
    H['GetLifeInfoReq'] = info
    H['GetLifeAchieveReq'] = lambda ctx, req: ctx.reply({'status': OK, 'lifeAchieve': achieve(ctx.p, req.get('life_type', COOK))})
    H['GetLifeSkillReq'] = lambda ctx, req: ctx.reply({'status': OK, 'life_type': req.get('life_type', COOK),
                                                       'skillInfo': skills(ctx.p, req.get('life_type', COOK))})
    H['GetOneTypeLifePictorialBookCountReq'] = lambda ctx, req: ctx.reply(
        {'status': OK, 'lifeAchieveCountLst': [{'id': int(k), 'count': str(v)} for k, v in L(ctx.p, req.get('life_type', COOK))['book'].items()]})

    def level_up(ctx, req):
        p = ctx.p
        lt = req.get('life_type', COOK)
        st = L(p, lt)
        row = level_row(p, lt)
        need = row.get('UpgradeLevelByProficiency', 10 ** 9)
        if st['prof'] < need or not _tbl(p, lt, 'level').get(st['level'] + 1):
            return ctx.reply({'status': FAIL})
        cid = row.get('UpLevelNeedItemID') or row.get('NeedItemID')       # fishing: NeedItemID is the energy per cast
        cnt = row.get('UpLevelNeedItemCount') if row.get('UpLevelNeedItemID') else row.get('NeedItemCount', 0)
        paid = p.pay([(cid, cnt)]) if cid and cnt else []
        if paid is None:
            return ctx.reply({'status': FAIL})
        st['level'] += 1
        st['prof'] -= need
        p.dirty = True
        ctx.reply({'status': OK, 'lifeBaseInfo': base_info(p, lt)})
        pack(ctx, paid)
    H['LifeLeveUpReq'] = level_up

    def skill_up(ctx, req):
        p = ctx.p
        lt = req.get('life_type', COOK)
        st = L(p, lt)
        sid = req.get('skill_id', 0)
        spells = _tbl(p, lt, 'spell')
        sk = st['skills'].setdefault(str(sid), {'lv': 0, 'start': -1})
        skills(p, lt)
        row = next((x for x in (spells.get(sid) or {}).get(CRAFT[lt]['spitems'], []) if x.get('Level') == sk['lv'] + 1), None)
        if not row or row.get(CRAFT[lt]['spneed'], 1) > st['level'] or sk.get('start', -1) > 0 and not req.get('is_force_study'):
            return ctx.reply({'status': FAIL})
        paid = []
        if sk.get('start', -1) <= 0:
            paid = p.pay([(row['NeedCurrencyID'], row.get('NeedCurrencyCount', 0))]) if row.get('NeedCurrencyID') else []
            if paid is None:
                return ctx.reply({'status': FAIL})
            sk['start'] = int(time.time())
        if req.get('is_force_study') or not row.get('NeedTime'):
            sk['lv'] += 1; sk['start'] = -1
        p.dirty = True
        ctx.reply({'status': OK, 'lifeSkills': {'lifeType': lt, 'lifeSkillInfo': skills(p, lt)}, 'items': paid,
                   'is_force_study': req.get('is_force_study', False)})
        pack(ctx, paid)
    H['LifeSkillLevelUpReq'] = skill_up

    def achieve_reward(ctx, req):
        p = ctx.p
        lt = req.get('life_type', COOK)
        st = L(p, lt)
        aid = req.get('achieve_id', 0)
        a = Q.idx(p.d)['ach'].get(aid) or {}
        if aid in st['rewarded'] or st['ach'].get(str(aid), 0) < a.get('CountParam', 1):
            return ctx.reply({'status': FAIL})
        rid = None
        for tbl in ('recipe',) if lt in (COOK, SEW, MAKE, HANDI) else ():
            for r in _tbl(p, lt, tbl).values():
                for x in r.get(CRAFT[lt]['book'], []):
                    if x.get('AchieveConditionID') == aid:
                        rid = x.get('RewardID')
        if lt == FISH:
            for f in p.d.table('fishing', 'FishingInfo').values():
                for x in f.get('FishAchieveRewards', []):
                    if x.get('AchieveConditionID') == aid:
                        rid = x.get('RewardID')
        if lt == GATHER:
            for f in p.d.table('lifegather', 'LifeGatherItem').values():
                for x in f.get('LifeGatherAchieveRewards', []):
                    if x.get('AchieveConditionID') == aid:
                        rid = x.get('RewardID')
        items = p.d.reward_items(rid, p.s['level']) if rid else []
        got, changed = p.add_items(items) if items else ([], [])
        st['rewarded'].append(aid)
        p.dirty = True
        ctx.reply({'status': OK, 'items': got, 'rewarded_achieve_ids': st['rewarded']})
        pack(ctx, changed)
    H['GetLifeAchievementRewardReq'] = achieve_reward


def daily_energy(p):
    """Energy (item 11) is refilled to Player_Energy_Max_Count once a day (04:00 UTC+8)."""
    k = Q.day_key()
    if p.s.get('energy_day') == k:
        return
    p.s['energy_day'] = k
    mx = int((p.d.config('Player_Energy_Max_Count', ['600']) or ['600'])[0])
    if p.count(ENERGY) < mx:
        p.s['items'][str(ENERGY)] = mx
        p.dirty = True
