"""Field completion (Scene / SceneProgress tables), like the official server.

Official SceneProcessListRsp gives per map the number of things done; the map's SceneProgress row lists, per kind,
how many there are (an archived account at 100% gets exactly the row's total). Quest step "<map> completion
reached N%" (EAchieveCondition SceneExplore, Param = map, CountParam = N * 100) counts done / total in 1/10000.
Checked against the archived account: computed values equal the official ones on all 7 maps.
"""
from game import quests as Q

# eUISceneProgressType -> what counts in the player's per-map world state
COLLECT = {6: 1, 1: 2, 7: 3, 8: 4, 9: 5, 5: 6, 4: 7, 3: 8, 13: 9}   # progress type -> ECollectionType
# flags without a type are normal battles (EMissionType_NormalBattle = 0)
FLAG = {0: 'EMissionType_ScenicSpot', 2: 'EMissionType_NormalBattle', 10: 'EMissionType_WeaponBattle',
        11: 'EMissionType_GuideBattle'}


def totals(d, scene_id):
    sc = d.row('scene', 'Scene', scene_id) or {}
    row = d.row('scene', 'SceneProgress', sc.get('ProgressID') or 0) or {}
    return {x.get('NewProgressType', 0): x.get('Total', 0) for x in row.get('SceneProgressInfo', []) if x.get('Total')}


def done(p, scene_id):
    from game.world import W
    d = p.d
    w = W(p, scene_id)
    tot = totals(d, scene_id)
    out = 0
    coll = {c.get('type', 0): len(c.get('itemMap', {})) for c in w.get('collections', [])}
    for kind, total in tot.items():
        n = 0
        if kind in COLLECT:
            n = coll.get(COLLECT[kind], 0)
        elif kind in FLAG:
            n = sum(1 for f in w.get('flags', []) if f.get('state') == 'Finish' and (f.get('type') or 'EMissionType_NormalBattle') == FLAG[kind])
        elif kind == 12:
            n = sum(1 for a in w.get('areas', []) if a.get('areaState', 'Unlock') == 'Unlock')
        elif kind == 14:
            ch = d.table('challenge', 'Challenge')
            n = sum(1 for c in w.get('challenges', []) if (ch.get(c.get('challengeId')) or {}).get('SceneID') == int(scene_id))
        elif kind == 15:
            n = sum(1 for r in w.get('riddles', []) if r.get('isWin'))
        out += min(n, total)
    return out


def process_list(p):
    """Every map with a progress row: the better of what was archived from official and what was done here."""
    archived = {}
    for body in p.s.get('records', {}).get('SceneProcessListReq', {}).values():
        for x in body.get('sceneProcessList', []):
            archived[x['sceneId']] = max(archived.get(x['sceneId'], 0), x.get('process', 0))
    out = []
    for sc in p.d.table('scene', 'Scene').values():
        if not sc.get('ProgressID') or not totals(p.d, sc['ID']):
            continue
        n = max(archived.get(sc['ID'], 0), done(p, sc['ID']))
        if n or str(sc['ID']) in p.s.get('world', {}):   # official lists the maps you have been to
            out.append({'sceneId': sc['ID'], 'process': n})
    return out


def check(p):
    """Quest steps 'map completion reached N%' (ratio in 1/10000)."""
    for x in process_list(p):
        total = sum(totals(p.d, x['sceneId']).values())
        if total:
            Q.event(p, Q.C['SceneExplore'], x['sceneId'], absolute=x['process'] * 10000 // total)


def register(H):
    H['SceneProcessListReq'] = lambda ctx, req: ctx.reply({'status': 'StatusCode_OK', 'sceneProcessList': process_list(ctx.p)})
    for name in ('CollectingReq', 'FlagBattleStateUpdateReq', 'AreaUnlockReq', 'ChallengeStateUpdateReq', 'RiddleStateUpdateReq'):
        orig = H.get(name)
        if not orig:
            continue

        def wrapped(ctx, req, _orig=orig):
            _orig(ctx, req)
            try:
                check(ctx.p)
            except Exception:
                import logging
                logging.getLogger('rozefield').exception('scene progress')
        H[name] = wrapped
