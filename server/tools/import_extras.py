"""Parts of an official backup that live outside PlayerMainData: the login notices (stickers, actions, events,
wishing tree, sign-in) and the world progress of every scene whose SceneDataNotice is in the backup.

Used by tools/import_archive.build() for new imports, and by the server once for accounts imported before this
existed (backfill_from_backup).
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def apply(st, msgs):
    """Copy the extras from decoded official messages ([{'dir','name','body'}]) into save state st."""
    un = st.setdefault('unlocks', {})
    ev = st.setdefault('events', {})
    for m in msgs:
        if m.get('dir') != 'S2C':
            continue
        n, b = m.get('name'), m.get('body') or {}
        if n == 'ChatUnLockExpressionNotice':
            un['expressions'] = sorted(set(un.get('expressions', [])) | set(b.get('expressionId', [])))
        elif n == 'AchieveActionUnLockNotice':
            un['actions'] = sorted(set(un.get('actions', [])) | set(b.get('actionIdLst', [])))
            un['study_actions'] = {**un.get('study_actions', {}), **b.get('studyAction', {})}
        elif n == 'ActivityQuestDataNotice':
            ev['activity_quest'] = b.get('info', [])
        elif n == 'ActivityRegularDataNotice':
            ev['activity_regular'] = b.get('info', [])
        elif n == 'PetWarehouseLimitNotice' and b.get('warehouse_limit'):
            st['pet_warehouse_limit'] = b['warehouse_limit']
        elif n == 'SceneDataNotice':
            sd = b.get('data') or {}
            sid = sd.get('sceneId')
            if sid is None:
                continue
            w = st.setdefault('world', {}).setdefault(str(sid), {})
            boxes = {str(x.get('index', 0)): {'refresh': int(x.get('nextRefreshTime', 0) or 0)}
                     for x in sd.get('treasureBoxes', []) if x.get('state') == 'TreasureBoxState_Open'}
            if boxes:
                w['boxes'] = boxes
            for k in ('riddles', 'flags', 'challenges', 'areas', 'collections', 'flagIds'):
                if sd.get(k):
                    w[k] = sd[k]
            if sd.get('gatherLimits'):
                w['gatherLimits'] = sd['gatherLimits']
            for dd in sd.get('dungeons', []):
                st.setdefault('dungeons', {})[str(dd['dungeonId'])] = dd
    from tools.import_events import apply as apply_events
    apply_events(msgs, st)
    st['extras_imported'] = 1
    return st


def backfill_from_backup(st, log=None):
    """Accounts imported before the extras existed: find their newest backup in save/imports and copy the extras.
    Only fills what is missing (never overwrites progress made on Rozefield)."""
    if st.get('extras_imported') or not st.get('official_player_id'):
        return False
    from tools.import_player import read_rzsave_bytes
    best = None
    for f in sorted(glob.glob(os.path.join(HERE, 'save', 'imports', '*.rzsave')), reverse=True):
        try:
            _, msgs = read_rzsave_bytes(open(f, 'rb').read())
        except Exception:
            continue
        md = next((m['body'] for m in msgs if m['name'] == 'PlayerMainDataRsp'), {}) or {}
        if md.get('player_id') == st['official_player_id']:
            best = msgs
            break
    if not best:
        st['extras_imported'] = 1    # nothing to fill from; don't look again
        return False
    fresh = apply({'events': {}, 'world': {}}, best)
    un = st.setdefault('unlocks', {})
    for k, v in fresh.get('unlocks', {}).items():
        un.setdefault(k, v)
    ev = st.setdefault('events', {})
    for k, v in fresh.get('events', {}).items():
        if not ev.get(k):
            ev[k] = v
        elif k == 'bless':                      # trees unlocked: union
            for tid, trees in v.items():
                ev[k][tid] = sorted(set(ev[k].get(tid, [])) | set(trees))
        elif k in ('signin', 'battlepass') and isinstance(v, dict):
            num = 'days' if k == 'signin' else 'totalExp'
            for aid, x in v.items():          # the official progress wins unless Rozefield's is already further
                if int((ev[k].get(aid) or {}).get(num, 0) or 0) < int(x.get(num, 0) or 0):
                    ev[k][aid] = x
    for sid, fw in fresh.get('world', {}).items():
        w = st.setdefault('world', {}).setdefault(sid, {})
        for k, v in fw.items():
            if k in ('boxes',):
                w[k] = {**v, **w.get(k, {})}
            elif isinstance(v, list) and k != 'gatherLimits':
                key = {'flagIds': None, 'areas': 'areaId', 'collections': 'itemId', 'riddles': 'riddleId',
                       'flags': 'flagId', 'challenges': 'challengeId'}.get(k)
                have = w.get(k, [])
                seen = {json.dumps(x, sort_keys=True) if key is None or not isinstance(x, dict) else x.get(key) for x in have}
                for x in v:
                    kk = json.dumps(x, sort_keys=True) if key is None or not isinstance(x, dict) else x.get(key)
                    if kk not in seen:
                        have.append(x)
                w[k] = have
            else:
                w.setdefault(k, v)
    for k, v in fresh.get('dungeons', {}).items():
        st.setdefault('dungeons', {}).setdefault(k, v)
    if fresh.get('pet_warehouse_limit'):
        st.setdefault('pet_warehouse_limit', fresh['pet_warehouse_limit'])
    st['extras_imported'] = 1
    if log:
        log('filled stickers, actions, events and world progress for %s from their backup' % st.get('name'))
    return True
