"""Content packs: everything a host can add or change without touching code.

    packs/official/        ships with the server: the rules that used to be written in the code (systems/*.json)
    packs/<any name>/      a host's own pack (made by hand from packs/_templates, or by Overfield Builder)

A pack folder:

    pack.json              {"name", "version", "author", "order", "enabled", "game_version"}
    systems/<name>.json    rules (map entry points, drop weights, part-time slots...): later packs override keys
    quests/*.json          quests            -> quest.Quest + quest.ConditionSetGroup + achieve.Achieve + quest text
    story/*.json           story chapters    -> story.StoryChapter + story.Story + story text
    npcs/*.json            NPCs              -> npc.Info (+ TalkInfo, NpcShop) + npc text
    dialogue/*.json        conversations     -> dialog.Dialog + dialogue text (the .asset is built by Overfield Builder)
    areas/*.json           field areas       -> kept for the Builder (spawns, chests, triggers, entry points)
    tables/<file>.json     anything else: {"Sheet": [rows]} merged into that game table by ID

Packs load official first, then by "order" (then folder name). A row with the same ID as an official row replaces
it only when the pack says "override": true (in pack.json or on the row); otherwise it is skipped with a warning,
so a pack can never break official content by accident. A row {"ID": n, "_delete": true} removes row n.

Text fields take a plain string (used for every language) or {"en": "...", "cn": "...", "tc": "...", "ja": "...",
"ko": "..."}; missing languages fall back to English.
"""
import glob
import json
import logging
import os
import zlib

log = logging.getLogger('rozefield')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_DIR = os.path.join(HERE, 'packs')
LANG = {'en': 'string_english', 'cn': 'string_simplified', 'tc': 'string_traditional', 'ja': 'string_japanese', 'ko': 'string_korea'}
QUEST_TYPE = {'main': 1, 'side': 2, 'daily': 4, 'event': 7, 'delegate': 8, 'extra': 9}
NPC_FUNC = {'talk': 5, 'shop': 4, 'quest_board': 9, 'commission': 12}   # ENewNPCFunction numbers seen in official npc.Info
STEP = {   # "do" in a quest step -> (EAchieveCondition, field holding the target id)
    'talk': ('QuestTalk', 'npc'), 'kill': ('KillMonest', 'monster'), 'collect': ('GetItem', 'item'),
    'have': ('ItemNum', 'item'), 'go_scene': ('GoSomeScene', 'scene'), 'unlock_area': ('AreaUlockNum', 'scene'),
    'open_box': ('OpenBox', 'box'), 'mechanism': ('MechanismInteraction', 'mechanism'), 'dungeon': ('DungeonPass', 'dungeon'),
    'encounter': ('FinishTheEncounter', 'encounter'), 'level': ('PlayerLv', None), 'emote': ('Emotion', 'emote'),
    'eat': ('EatFood', 'item'), 'cook': ('CookingNum01', 'item'),
}

_state = None


def _read(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception as e:
        log.warning('[packs] %s: %s (skipped)', os.path.relpath(path, HERE), e)
        return None


def packs():
    """[(folder, pack.json)] in load order, enabled packs only."""
    out = []
    for d in sorted(glob.glob(os.path.join(PACK_DIR, '*', ''))):
        name = os.path.basename(d.rstrip('/\\'))
        if name.startswith(('_', '.')):
            continue
        meta = _read(os.path.join(d, 'pack.json')) if os.path.exists(os.path.join(d, 'pack.json')) else {}
        if meta is None or meta.get('enabled', True) is False:
            continue
        meta.setdefault('name', name)
        out.append((d, meta))
    out.sort(key=lambda x: (os.path.basename(x[0].rstrip('/\\')) != 'official', x[1].get('order', 100), x[0]))
    return out


def _files(d, sub):
    for f in sorted(glob.glob(os.path.join(d, sub, '*.json'))):
        j = _read(f)
        if j is None:
            continue
        for item in (j if isinstance(j, list) else [j]):
            if isinstance(item, dict):
                yield f, item


class _Out:
    """Rows a pack adds, per (table file, sheet)."""
    def __init__(self, pack, override):
        self.pack, self.override, self.rows = pack, override, {}

    def add(self, f, sheet, row, override=None):
        if override or (override is None and self.override):
            row = dict(row, _override=True)
        self.rows.setdefault((f, sheet), []).append(row)

    def text(self, sheet, id_, parts, key=None):
        """parts: one text value per column (each a string or a {lang: string} dict)."""
        for lang, f in LANG.items():
            cols = []
            for t in parts:
                if isinstance(t, dict):
                    cols.append(t.get(lang, t.get('en', '')))
                else:
                    cols.append(t or '')
            row = {'ID': id_, 'Text': cols} if key is None else {'ID': id_, 'Key': key, 'Title': cols[0], 'Content': cols[1]}
            self.add(f, sheet, row, override=True)   # text for a new id never clashes; for an old id it is a translation fix


def text_id(key):
    """Stable id for a dialogue line key (the game's own ids look hashed too)."""
    return zlib.crc32(key.encode('utf-8')) & 0x7fffffff


def _quest(o, q, src):
    qid = q['ID'] if 'ID' in q else q['id']
    steps, cond, res = q.get('steps', []), [], []
    for i, s in enumerate(steps, 1):
        cid = s.get('condition_id') or qid * 10 + i
        if s.get('do') == 'raw':
            ach = {'ID': cid, 'NewAchieveCondition': s['condition'] if isinstance(s['condition'], int) else _cond(s['condition']),
                   'Param': s.get('param', []), 'CountParam': s.get('count', 1)}
        else:
            if s.get('do') not in STEP:
                raise ValueError(f'step {i}: unknown "do": {s.get("do")} (use one of {", ".join(STEP)} or raw)')
            cname, field = STEP[s['do']]
            ach = {'ID': cid, 'NewAchieveCondition': _cond(cname), 'Param': [s[field]] if field and field in s else s.get('param', []),
                   'CountParam': s.get('count', 1)}
        o.add('achieve', 'Achieve', ach)
        if s.get('text'):
            o.text('StringAchieve', cid, [s['text'], ''])
        cond.append(cid); res.append(s.get('resource', 0))
    row = {'ID': qid, 'QuestGroup': q.get('group', qid), 'Name': qid, 'LimitNum': q.get('limit', 1),
           'IsImmedReward': q.get('instant_reward', True), 'ConditionSetGroupID': qid,
           'NewType': QUEST_TYPE.get(q.get('type', 'side'), q.get('type')) if not isinstance(q.get('type'), int) else q['type']}
    for k, col in (('reward', 'Reward'), ('first_reward', 'FirstReward'), ('start_dialogue', 'ReceiveQuestDialogID'),
                   ('end_dialogue', 'FinishQuestDialogID'), ('icon', 'IconID'), ('npc_picture', 'NpcPicID')):
        if q.get(k) is not None:
            row[col] = q[k]
    o.add('quest', 'Quest', row, q.get('override'))
    sets = [{'AchieveConditionID': cond, 'ResourceID': res}] if not q.get('one_step_at_a_time') else \
        [{'AchieveConditionID': [c], 'ResourceID': [r]} for c, r in zip(cond, res)]
    o.add('quest', 'ConditionSetGroup', {'ID': qid, 'QuestConditionSet': sets}, q.get('override'))
    o.text('StringQuestText', qid, [q.get('name', ''), q.get('description', '')])
    o.text('StringQuestResourceText', qid, [q.get('name', ''), ''])


def _story(o, c, src):
    cid = c['ID'] if 'ID' in c else c['id']
    stories = c.get('stories', [])
    row = {'ID': cid, 'Name': cid, 'IconID': c.get('icon', cid), 'StoryList': [s['id'] for s in stories]}
    if c.get('after_chapter'):
        row['PreChapterUnlock'] = c['after_chapter']
    if c.get('map_completion'):
        row['MapCompletionUnlock'] = c['map_completion']
    o.add('story', 'StoryChapter', row, c.get('override'))
    o.text('StringStory', cid, [c.get('name', ''), c.get('description', '')])
    prev = c.get('after_story')
    for s in stories:
        r = {'ID': s['id'], 'LvUnlock': s.get('level', 1), 'QuestID': s['first_quest'], 'ReviewID': s['id']}
        if s.get('after_story', prev):
            r['PreStoryUnlock'] = s.get('after_story', prev)
        if s.get('reward'):
            r['Reward'] = s['reward']
        o.add('story', 'Story', r, c.get('override'))
        if s.get('review_dialogues'):
            o.add('story', 'StoryReview', {'ID': s['id'], 'StoryReviewSet': [{'Name': d, 'DialogID': d} for d in s['review_dialogues']]})
        prev = s['id']


def _npc(o, n, src):
    nid = n['ID'] if 'ID' in n else n['id']
    funcs = []
    for f in n.get('functions', ['talk']):
        f = f if isinstance(f, dict) else {'type': f}
        e = {'NewNPCFunction': NPC_FUNC.get(f['type'], f['type'])}
        if f.get('id') or f['type'] in ('talk', 'shop'):
            e['SubMeterID'] = f.get('id', nid)
        funcs.append(e)
    o.add('npc', 'Info', {'ID': nid, 'Funcs': funcs}, n.get('override'))
    if n.get('talk'):
        o.add('npc', 'TalkInfo', {'ID': nid, 'TalkInfoGroupInfo': [{'ContentID': d} for d in n['talk']]})
    if n.get('shops'):
        o.add('npc', 'NpcShop', {'ID': nid, 'NpcShopGroupInfo': [{'ShopID': s} for s in n['shops']]})
    o.text('StringNpc', nid, [n.get('name', ''), n.get('title', ''), n.get('commission_new', ''), n.get('commission_done', ''), ''])


def _dialogue(o, dlg, src, pack):
    did = dlg['ID'] if 'ID' in dlg else dlg['id']
    name = dlg.get('asset_name') or f'Rozefield_{did}_Chat'
    asset = dlg.get('asset') or f'Assets/ResBundle/QuestAssets/Rozefield/{pack}/{name}.asset'
    o.add('dialog', 'Dialog', {'ID': did, 'AssetFullName': asset}, dlg.get('override'))
    for i, ln in enumerate(dlg.get('lines', [])):
        key = f'{name}_{i}'
        o.text('StringDialogText', text_id(key), [ln.get('speaker', ''), ln.get('text', '')], key=key)
        for j, ch in enumerate(ln.get('choices', [])):
            k2 = f'{name}_{i}_c{j}'
            o.text('StringDialogText', text_id(k2), ['', ch.get('text', '')], key=k2)


def _cond(name):
    from game.quests import C
    if name in C:
        return C[name]
    from ofproto import pool
    return pool.FindEnumTypeByName('pb.EAchieveCondition').values_by_name['EAchieveCondition_' + name].number


def _build():
    st = {'systems': {}, 'rows': {}, 'areas': {}, 'dialogues': {}, 'packs': [], 'problems': []}
    for d, meta in packs():
        name = os.path.basename(d.rstrip('/\\'))
        o = _Out(name, meta.get('override', name == 'official'))
        for f in sorted(glob.glob(os.path.join(d, 'systems', '*.json'))):
            j = _read(f)
            if isinstance(j, dict):
                st['systems'].setdefault(os.path.basename(f)[:-5], {}).update({k: v for k, v in j.items() if not k.startswith('_')})
        for sub, fn in (('quests', _quest), ('story', _story), ('npcs', _npc)):
            for f, item in _files(d, sub):
                try:
                    fn(o, item, f)
                except Exception as e:
                    st['problems'].append(f'{name}/{sub}/{os.path.basename(f)}: {e}')
        for f, item in _files(d, 'dialogue'):
            try:
                _dialogue(o, item, f, name)
                st['dialogues'][item.get('ID', item.get('id'))] = dict(item, _pack=name)
            except Exception as e:
                st['problems'].append(f'{name}/dialogue/{os.path.basename(f)}: {e}')
        for f, item in _files(d, 'areas'):
            st['areas'][item.get('ID', item.get('id'))] = dict(item, _pack=name)
        for f in sorted(glob.glob(os.path.join(d, 'tables', '*.json'))):
            j = _read(f)
            for sheet, rows in (j or {}).items():
                for r in rows if isinstance(rows, list) else []:
                    o.add(os.path.basename(f)[:-5], sheet, r)
        for k, rows in o.rows.items():
            st['rows'].setdefault(k, []).extend((name, r) for r in rows)
        st['packs'].append((name, meta.get('version', ''), sum(len(r) for r in o.rows.values())))
    for p in st['problems']:
        log.warning('[packs] %s', p)
    return st


def state():
    global _state
    if _state is None:
        _state = _build()
        extra = [p for p in _state['packs'] if p[0] != 'official']
        if extra:
            log.info('[packs] loaded: %s', ', '.join(f'{n} {v} ({c} rows)' for n, v, c in extra))
    return _state


def reload():
    global _state
    _state = None
    return state()


def system(name, key, default=None):
    """A rule from packs/*/systems/<name>.json (later packs win)."""
    return state()['systems'].get(name, {}).get(key, default)


def int_keys(d):
    return {int(k): v for k, v in (d or {}).items()}


def apply(f, raw):
    """Merge every pack's rows for table file f into the loaded official table (in place)."""
    rows = state()['rows']
    for (tf, sheet), items in rows.items():
        if tf != f:
            continue
        datas = raw.setdefault(sheet, {}).setdefault('datas', [])
        at = {r.get('ID'): i for i, r in enumerate(datas)}
        for pack, r in items:
            r = dict(r); ovr = r.pop('_override', False)
            rid = r.get('ID')
            if r.pop('_delete', False):
                if rid in at and not ovr:
                    log.warning('[packs] %s: deleting official %s.%s id %s needs "override": true', pack, f, sheet, rid)
                elif rid in at:
                    datas[at.pop(rid)] = None
                continue
            if rid in at:
                if not ovr:
                    log.warning('[packs] %s: %s.%s id %s is official content; add "override": true to replace it',
                                pack, f, sheet, rid)
                    continue
                datas[at[rid]] = r
            else:
                at[rid] = len(datas); datas.append(r)
        raw[sheet]['datas'] = [r for r in datas if r is not None]
    return raw
