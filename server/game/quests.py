"""Quest engine: quests progress from what the player does, complete, pay out, and unlock the next one.

Data model (from the client tables):
  Quest[id]            NewType = EQuestType number (1 main, 2 side, 4 daily, 7 random event, 8 delegate, 9 extra),
                       QuestGroup (main quests of one story share the story's first quest id), Reward / FirstReward
                       (reward pools), IsImmedReward (paid out the moment it completes, no Claim button)
  ConditionSetGroup[id].QuestConditionSet[].AchieveConditionID -> Achieve[aid]
  Achieve[aid]         NewAchieveCondition = EAchieveCondition (what to do), Param (which npc/monster/item...),
                       CountParam (how many)
  Story[id]            QuestID = first quest of the story's group, PreStoryUnlock, LvUnlock, Reward (claimed separately)

The client reports actions with ordinary requests (NpcTalkReq for quest talks and story mechanisms, MonsterDeadReq,
FlagBattleStateUpdateReq, CookingFoodReq, ...); handlers call event(). Steps whose exact rule is not modelled
complete when the game reports an action whose id is listed in the step's Param (the owner chose "complete when
reported", so stories never block).
"""
import random
import time

C = {  # EAchieveCondition numbers used by quests
    'KillMonest': 1, 'GetItem': 2, 'OpenBox': 3, 'FinishMission': 4, 'FinishEncounter': 5, 'DungeonPass': 6,
    'CookingNum01': 20, 'CookingSuccessNum0': 22, 'FishingSuccess1': 26, 'FishingSpecialTimesNum12': 28,
    'QuestTalk': 37, 'Gacha': 38, 'GoSomeScene': 39, 'MechanismInteraction': 40, 'AreaUlockNum': 43, 'ItemNum': 44,
    'FinishTheEncounter': 45, 'HandicraftSuccess1': 46, 'MakeSuccess1': 47, 'SpinSuccess1': 48, 'HandicraftProcess1': 49,
    'MakeProcess1': 50, 'SpinProcess1': 51, 'SpinNum01': 57, 'CollectionGloves': 61, 'LoggingAxe': 62, 'MiningHammer': 63,
    'InsectNet': 64, 'WaterBottle': 65, 'Pick': 66, 'CollectionGlovesGains': 67, 'InsectNetGains': 70, 'PickGains': 72,
    'Emotion': 74, 'EatFood': 75, 'CatchTheSea': 76, 'UseEnergy': 81, 'UseVitality': 80, 'DailyQuestNum': 84,
    'UseGoldNum': 85, 'KillMonsterNum': 86, 'SideQuest12': 104, 'SceneExplore': 113, 'OpenBox0': 119, 'Decompose0': 124,
    'WearingFashing0': 127, 'PlacingFurniture0': 129, 'UseInteractiveItemNum': 165, 'CookingNum': 168,
    'GardenLike': 176, 'AddFriend': 177, 'PlayerLv': 36,
}
# condition types the server tracks from real actions (others complete when the game reports the step id)
EVENT_TYPES = {C[k] for k in ('KillMonest', 'GetItem', 'OpenBox', 'FinishMission', 'FinishEncounter', 'QuestTalk', 'Gacha',
                              'GoSomeScene', 'MechanismInteraction', 'AreaUlockNum', 'ItemNum', 'FinishTheEncounter', 'Emotion',
                              'EatFood', 'DailyQuestNum', 'KillMonsterNum', 'SideQuest12', 'OpenBox0', 'Decompose0',
                              'WearingFashing0', 'PlacingFurniture0', 'PlayerLv', 'DungeonPass', 'UseEnergy', 'UseVitality',
                              'UseGoldNum', 'UseInteractiveItemNum', 'GardenLike', 'AddFriend', 'SceneExplore')}
# types that need a system not built yet (life skills, gathering, dungeons, currencies, social): no rule
UNBUILT_TYPES = set()
# life-skill types are tracked by game/life.py
EVENT_TYPES_LIFE = {C[k] for k in ('CookingNum01', 'CookingSuccessNum0', 'FishingSuccess1', 'FishingSpecialTimesNum12',
                                   'HandicraftSuccess1', 'MakeSuccess1', 'SpinSuccess1', 'HandicraftProcess1', 'MakeProcess1',
                                   'SpinProcess1', 'SpinNum01', 'CollectionGloves', 'LoggingAxe', 'MiningHammer', 'InsectNet',
                                   'WaterBottle', 'Pick', 'CollectionGlovesGains', 'InsectNetGains', 'PickGains', 'CatchTheSea',
                                   'CookingNum')}
EVENT_TYPES |= EVENT_TYPES_LIFE
IN_PROGRESS, COMPLETED, FINISH, LOCKED = 'QuestStatus_InProgress', 'QuestStatus_Completed', 'QuestStatus_Finish', 'QuestStatus_Locked'
MAIN, DAILY = 1, 4
# Stories official Global never gave out (cut "Investigator" chapter + two chapter-4 side stories). Rozefield adds them
# back as a chapter (tools/merge_cn_config.py). New Rozefield players get them in the main story; players imported
# from official start them from the story screen themselves and are never pushed into them.
OPTIONAL_STORIES = set(range(1000401, 1000415)) | {1000509, 1000510}
_IDX = {}


# ------------------------------------------------------------------ indexes
def idx(d):
    if id(d) in _IDX:
        return _IDX[id(d)]
    quests = d.table('quest', 'Quest')
    groups = d.table('quest', 'ConditionSetGroup')
    ach = d.table('achieve', 'Achieve')
    stories = sorted(d.table('story', 'Story').values(), key=lambda s: s['ID'])
    chapter_of = {sid: c['ID'] for c in d.table('story', 'StoryChapter').values() for sid in c.get('StoryList', [])}
    by_group = {}
    for q in quests.values():
        by_group.setdefault(q.get('QuestGroup', q['ID']), []).append(q['ID'])
    main_order, story_of, extra_qids = [], {}, set()
    for st in stories:
        if st['ID'] in OPTIONAL_STORIES:
            extra_qids.update(by_group.get(st.get('QuestID'), []))
        for qid in sorted(by_group.get(st.get('QuestID'), [])):
            main_order.append(qid)
            story_of[qid] = st
    res_of = {}   # conditionId -> the scene resource (talk point / mechanism) the client reports for that step
    for g in groups.values():
        for cs in g.get('QuestConditionSet', []):
            for cid, rid in zip(cs.get('AchieveConditionID', []), cs.get('ResourceID', [])):
                if rid:
                    res_of.setdefault(cid, set()).add(rid)
    x = {'res_of': res_of, 'quests': quests, 'groups': groups, 'ach': ach, 'stories': {s['ID']: s for s in stories}, 'story_list': stories,
         'chapter_of': chapter_of, 'by_group': by_group, 'main_order': main_order, 'story_of': story_of, 'extra_qids': extra_qids,
         'daily_pool': sorted(q['ID'] for q in quests.values() if q.get('NewType') == DAILY)}
    _IDX[id(d)] = x
    return x


def conditions_of(d, qid):
    x = idx(d)
    gid = (x['quests'].get(qid) or {}).get('ConditionSetGroupID', qid)
    out = []
    for cs in (x['groups'].get(gid) or {}).get('QuestConditionSet', []):
        out += cs.get('AchieveConditionID', [])
    return out


def qtype(d, qid):
    return (idx(d)['quests'].get(qid) or {}).get('NewType', 0)


# ------------------------------------------------------------------ state helpers
def _changed(p, q):
    p.__dict__.setdefault('_qchanged', {})[str(q.get('questId'))] = q
    p.dirty = True


def accept(p, qid, status=IN_PROGRESS):
    """Give the player quest qid (idempotent). Returns the quest dict."""
    s = p.s
    q = s['quests'].get(str(qid))
    if q and q.get('status') not in (LOCKED,):
        return q
    q = {'questId': qid, 'conditions': [{'conditionId': c, 'status': status} for c in conditions_of(p.d, qid)],
         'status': status, 'bonusTimes': 1}
    s['quests'][str(qid)] = q
    _changed(p, q)
    _check_state_conditions(p, q)
    return q


def _need(p, aid):
    return max(1, int((idx(p.d)['ach'].get(aid) or {}).get('CountParam', 1) or 1))


def _set_progress(p, q, c, value):
    need = _need(p, c['conditionId'])
    c['progress'] = min(value, need)
    if c['progress'] >= need:
        c['status'] = COMPLETED
    _changed(p, q)


def _check_state_conditions(p, q):
    """Conditions that describe a state rather than an action (in a scene, own items, level) can already be true."""
    for c in q.get('conditions', []):
        if c.get('status') != IN_PROGRESS:
            continue
        a = idx(p.d)['ach'].get(c['conditionId']) or {}
        t, par = a.get('NewAchieveCondition'), a.get('Param') or []
        if t == C['GoSomeScene'] and par and p.s.get('scene_id') in par:
            _set_progress(p, q, c, _need(p, c['conditionId']))
        elif t in (C['ItemNum'],) and par:
            _set_progress(p, q, c, p.count(par[0]))
        elif t == C['PlayerLv']:
            _set_progress(p, q, c, p.s.get('level', 1))
    _maybe_complete(p, q)


def _maybe_complete(p, q):
    if q.get('status') != IN_PROGRESS:
        return
    if all(c.get('status') in (COMPLETED, FINISH) for c in q.get('conditions', [])):
        q['status'] = COMPLETED
        _changed(p, q)
        cfg = idx(p.d)['quests'].get(q['questId']) or {}
        if cfg.get('IsImmedReward'):
            finish(p, q)


def quest_rewards(p, q):
    cfg = idx(p.d)['quests'].get(q.get('questId')) or {}
    out = []
    if cfg.get('Reward'):
        out += p.d.reward_items(cfg['Reward'], p.s['level'])
    if cfg.get('FirstReward') and not q.get('completeCount'):
        out += p.d.reward_items(cfg['FirstReward'], p.s['level'])
    return out


def finish(p, q, gained=None):
    """Completed -> Finish: pay the quest reward, unlock what follows. gained collects (item, n) granted."""
    if q.get('status') == FINISH:
        return []
    items = quest_rewards(p, q)
    q['status'] = FINISH
    for c in q.get('conditions', []):
        c['status'] = FINISH
    q['completeCount'] = q.get('completeCount', 0) + 1
    _changed(p, q)
    got, changed = p.add_items(items) if items else ([], [])
    p.__dict__.setdefault('_qpack', []).extend(changed)
    if gained is not None:
        gained.extend(got)
    t = qtype(p.d, q['questId'])
    if t == MAIN:
        advance_main(p)
    if t == DAILY:
        event(p, C['DailyQuestNum'])
    if t == 2:
        event(p, C['SideQuest12'])
    return got


# ------------------------------------------------------------------ main story chain
def story_open(p, st):
    if st.get('LvUnlock', 0) > p.s.get('level', 1):
        return False
    pre = st.get('PreStoryUnlock')
    if pre:
        pst = idx(p.d)['stories'].get(pre)
        if pst and not story_done(p, pst):
            return False
    tu = st.get('TimeUnlock')
    if tu:
        try:
            if time.mktime(time.strptime(tu[:19], '%Y-%m-%d %H:%M:%S')) > time.time():
                return False
        except ValueError:
            pass
    return True


def story_done(p, st):
    qs = idx(p.d)['by_group'].get(st.get('QuestID'), [])
    return bool(qs) and all((p.s['quests'].get(str(q)) or {}).get('status') == FINISH for q in qs)


def is_imported(p):
    """Account came from an official backup (tools/import_archive.py)."""
    return bool(p.s.get('official_player_id') or p.s.get('official_answers') or p.s.get('records'))


def advance_main(p):
    """Keep one main-story quest active: the first unfinished quest of the first story that is open
    (stories open by level, release time and their previous story). Runs after a main quest finishes,
    at login and on level up."""
    x = idx(p.d)
    qs = p.s['quests']
    for k in [k for k in qs if k.isdigit() and int(k) in x['stories'] and int(k) not in x['quests']]:
        del qs[k]    # a story id taken for a quest id by an older build (story screen "Accept Quest")
    imported = is_imported(p)
    if imported and not p.s.get('extra_story_cleanup'):
        # older builds pushed the optional stories on imported players as the main quest; drop unfinished ones once
        for qid in x['extra_qids']:
            q = qs.get(str(qid))
            if q and q.get('status') in (IN_PROGRESS, COMPLETED):
                del qs[str(qid)]
        p.s['extra_story_cleanup'] = 1
    for qid in x['main_order']:
        if (qs.get(str(qid)) or {}).get('status') in (IN_PROGRESS, COMPLETED):
            return qs[str(qid)]
    blocked = set()
    for qid in x['main_order']:
        st = x['story_of'][qid]
        if (qs.get(str(qid)) or {}).get('status') == FINISH or st['ID'] in blocked:
            continue
        if imported and st['ID'] in OPTIONAL_STORIES and not any(
                str(q) in qs for q in x['by_group'].get(st.get('QuestID'), [])):
            continue    # not started from the story screen: leave it alone (a started one carries on to its end)
        if not story_open(p, st):
            blocked.add(st['ID'])
            continue
        return accept(p, qid)
    return None


# ------------------------------------------------------------------ daily quests (5 a day, reset 04:00 UTC+8)
def day_key(t=None):
    t = time.time() if t is None else t
    return time.strftime('%Y-%m-%d', time.gmtime(t + 4 * 3600))   # day starts 04:00 UTC+8 (= 20:00 UTC)


DAILY_UNLOCK_ITEM = 100000030   # PlayerUnlock: EUnlockFunctionType_DailyQuest (granted by a story reward)


def refresh_daily(p):
    k = day_key()
    if p.s.get('daily_day') == k or DAILY_UNLOCK_ITEM not in p.s.get('unlock_functions', []):
        return
    x = idx(p.d)
    pool = [q for q in x['daily_pool'] if conditions_of(p.d, q)]
    for qid in list(p.s['quests']):
        if qtype(p.d, int(qid) if qid.isdigit() else 0) == DAILY:
            del p.s['quests'][qid]
    n = int((p.d.config('DayFiveQuestMaxNum', ['5']) or ['5'])[0])
    for qid in random.sample(pool, min(n, len(pool))):
        accept(p, qid)
    p.s['daily_day'] = k
    p.s['daily_bonus'] = {'bonus1Left': 3, 'bonus2Left': 5, 'bonus3Left': 10}
    p.dirty = True


# ------------------------------------------------------------------ events
def event(p, ctype, key=None, n=1, absolute=None):
    """The player did <ctype> (EAchieveCondition) on <key> (npc/monster/item/... id), n times."""
    from game import progression
    progression.on_event(p, ctype, key, n, absolute)
    for q in list(p.s['quests'].values()):
        if q.get('status') != IN_PROGRESS or not q.get('questId'):   # id-less entries belong to activity systems
            continue
        hit = False
        for c in q.get('conditions', []):
            if c.get('status') != IN_PROGRESS:
                continue
            a = idx(p.d)['ach'].get(c['conditionId']) or {}
            if a.get('NewAchieveCondition') != ctype:
                continue
            par = a.get('Param') or []
            if par and key is not None and key not in par:
                continue
            if par and key is None and ctype not in (C['DailyQuestNum'], C['SideQuest12']):
                continue
            _set_progress(p, q, c, absolute if absolute is not None else c.get('progress', 0) + n)
            hit = True
        if hit:
            _maybe_complete(p, q)


def reported(p, key):
    """The game reports finishing a scripted step (quest talk, story mechanism, mission...) for id <key>:
    complete every active step that lists that id."""
    for q in list(p.s['quests'].values()):
        if q.get('status') != IN_PROGRESS or not q.get('questId'):   # id-less entries belong to activity systems
            continue
        hit = False
        for c in q.get('conditions', []):
            if c.get('status') != IN_PROGRESS:
                continue
            par = (idx(p.d)['ach'].get(c['conditionId']) or {}).get('Param') or []
            if key in par or key == c['conditionId'] or key in idx(p.d)['res_of'].get(c['conditionId'], ()):
                _set_progress(p, q, c, _need(p, c['conditionId']))
                hit = True
        if hit:
            _maybe_complete(p, q)


def on_scene(p, scene_id):
    event(p, C['GoSomeScene'], scene_id, absolute=10 ** 6)


def on_level(p):
    event(p, C['PlayerLv'], absolute=p.s.get('level', 1))
    advance_main(p)


def on_items(p, pairs):
    for iid, n in pairs:
        event(p, C['GetItem'], iid, n)
        event(p, C['ItemNum'], iid, absolute=p.count(iid))


def login(p):
    k = day_key()
    if p.s.get('login_day') != k:
        p.s['login_day'] = k
        p.s['login_days'] = p.s.get('login_days', 0) + 1
    event(p, 82, absolute=p.s['login_days'])            # EAchieveCondition_LoginDays
    event(p, C['PlayerLv'], absolute=p.s.get('level', 1))
    refresh_daily(p)
    advance_main(p)
    for q in list(p.s['quests'].values()):
        if q.get('status') == IN_PROGRESS and q.get('questId'):
            _check_state_conditions(p, q)
    p.__dict__.pop('_qchanged', None)   # main data carries everything at login
    p.__dict__.pop('_achanged', None)


def flush(ctx):
    """After each request: tell the client which quests changed (QuestNotice) and what items quest rewards gave."""
    p = ctx.p
    if p is None:
        return
    if p.__dict__.pop('_leveled', None):
        on_level(p)
    refresh_daily(p)
    ch = p.__dict__.pop('_qchanged', None)
    pk = p.__dict__.pop('_qpack', None)
    if pk:
        ctx.push('PackNotice', {'status': 'StatusCode_OK', 'items': pk})
    ach = p.__dict__.pop('_achanged', None)
    if ach:
        ctx.push('AchieveNotice', {'status': 'StatusCode_OK', 'achieves': ach})
    if ch:
        ctx.push('QuestNotice', {'status': 'StatusCode_OK', 'quests': list(ch.values())})
        try:
            from game.world import story_flags_changed
            story_flags_changed(ctx, {str(q.get('questId')) for q in ch.values()})
        except Exception:
            pass


def quest_detail(p):
    s = p.s
    out = {'quests': list(s['quests'].values()),
           'chapters': [{'chapterId': int(k), 'rewardedStoryIds': v} for k, v in s.get('chapters', {}).items()]}
    # official always sends these sub-messages (empty when unused); a missing one is null to the client
    # (UIMainSystem.UpdateRandomQuest throws on a null randomQuestBonusLeft)
    out['dailyQuestBonusDayLeft'] = s.get('daily_bonus') or {}
    out['dailyQuestBonusWeekLeft'] = s.get('weekly_bonus') or s.get('daily_bonus') or {}
    out['randomQuestBonusLeft'] = s.get('random_bonus') or {}
    return out
