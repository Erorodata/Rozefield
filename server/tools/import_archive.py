"""Turn an archived account (from your own packet captures) into a playable Rozefield account.

    py tools\\import_archive.py --name Player capture1.pcapng [capture2.pcapng ...]

Then log in with that name in the Rozefield login box. Without this step every name starts as a new player.
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from tools.make_save import streams          # noqa: E402
from ofproto import decode, to_dict          # noqa: E402
from game.data import Data                   # noqa: E402
from game.player import Player, INSTANCE_TAGS, SAVE_DIR, _registry, _save_registry, new_local_id  # noqa: E402


class ImportFailed(Exception):
    pass


def pcap_messages(captures):
    """[{'dir','name','head','body'}] from pcap captures, in order."""
    out = []
    for cap in captures:
        print('reading', cap)
        for port, msgs in streams(cap).items():
            for ts, d, h, body in msgs:
                try:
                    name, m = decode(h.msg_id, body)
                except Exception:
                    continue
                if name:
                    out.append({'t': ts, 'dir': d, 'port': port, 'name': name,
                                'head': {'packet_id': h.packet_id, 'msg_id': h.msg_id}, 'body': to_dict(m)})
    out.sort(key=lambda x: x['t'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='login name to attach the archived account to')
    ap.add_argument('captures', nargs='+')
    a = ap.parse_args()
    try:
        build(a.name, pcap_messages(a.captures))
    except ImportFailed as e:
        sys.exit(str(e))


def build(login_name, msgs, keep_player_id=True):
    """Make a Rozefield account for <login_name> from decoded official messages. Returns the save path."""
    from tools.import_records import pairs
    md = None; pack = []; lists = {'weapons': {}, 'armors': {}, 'posters': {}, 'pets': {}}; garden = {}; schemes = None
    for msg in msgs:
        if msg['dir'] != 'S2C':
            continue
        name, b = msg['name'], msg['body'] or {}
        if name == 'PlayerMainDataRsp':
            md = b
        elif name == 'PackNotice':
            pack.append(b)
        elif name in ('GetWeaponRsp', 'GetArmorRsp', 'GetPosterRsp', 'GetPetRsp'):
            k = name[3:-3].lower() + 's'
            for inst in b.get(k, []):
                lists[k][str(inst.get('instanceId') or inst.get('instance_id'))] = inst
        elif name == 'SceneDataNotice' and md:
            sd = b.get('data', {})
            if sd.get('channelId') == md.get('player_id'):
                garden = sd.get('sceneGardenData', {}).get('gardenFurnitureInfoMap', garden)
        elif name == 'GardenFurnitureSchemeRsp':
            schemes = b.get('schemes', {})
    if not md:
        raise ImportFailed('this backup has no login in it - open the game and log in while the backup window runs')
    d = Data()
    uid = 'rz_' + login_name.lower()
    reg = _registry()
    old = reg['by_uid'].get(uid)
    if old and os.path.exists(os.path.join(SAVE_DIR, f'{old}.json')):
        prev = json.load(open(os.path.join(SAVE_DIR, f'{old}.json'), encoding='utf-8'))
        if prev.get('official_player_id', old) != md.get('player_id'):
            raise ImportFailed(f'the name "{login_name}" is already used by another account on this server')
    # one official account = one Rozefield account, under its official id. Ids below LOCAL_ID_START are official
    # ones (older Rozefield-made accounts are moved out of that range first).
    from game.player import migrate_local_ids, LOCAL_ID_START
    migrate_local_ids()
    reg = _registry()
    off = md.get('player_id')
    for u, p in reg['by_uid'].items():
        f = os.path.join(SAVE_DIR, f'{p}.json')
        if u == uid or not os.path.exists(f):
            continue
        other = json.load(open(f, encoding='utf-8'))
        if off and other.get('official_player_id', p if p < LOCAL_ID_START else None) == off:
            raise ImportFailed(f'this account is already on this server as "{other.get("name")}" - log in with that name')
    pid = reg['by_uid'].get(uid) or (off if keep_player_id and off and off < LOCAL_ID_START else None)
    if not pid:
        pid = new_local_id(reg)
    reg['by_uid'][uid] = pid
    st = Player.new_state(d, uid, pid, md.get('player_name', login_name))
    for k in ('level', 'exp', 'world_level', 'head', 'sign', 'phone_background', 'phone_case', 'birthday', 'player_label'):
        if k in md:
            st[k] = md[k]
    st['create_time'] = md.get('create_time', st['create_time'])
    st['official_player_id'] = md.get('player_id')
    st['unlock_functions'] = md.get('unlockFunctions', [])
    st['characters'] = {str(c['characterId']): c for c in md.get('characters', [])}
    st['team'] = md.get('team', {})
    st['placed_characters'] = md.get('placed_characters', [])
    st['appearance'] = md.get('appearance', {})
    st['quests'] = {str(q.get('questId', i)): q for i, q in enumerate(md.get('quest_detail', {}).get('quests', []))}
    st['chapters'] = {str(c['chapterId']): c.get('rewardedStoryIds', []) for c in md.get('quest_detail', {}).get('chapters', [])}
    st['scene_id'], st['channel_id'] = 9999, pid
    for pn in pack:  # PackNotice holds running totals, later ones win
        for it in pn.get('items', []):
            mi = it.get('mainItem', {})
            tag = mi.get('itemTag')
            if tag in INSTANCE_TAGS:
                inst = mi.get({'EBagItemTag_Weapon': 'weapon', 'EBagItemTag_Armor': 'armor', 'EBagItemTag_Poster': 'poster',
                               'EBagItemTag_Pet': 'pet'}[tag])
                if inst:
                    lists[INSTANCE_TAGS[tag]].setdefault(str(inst.get('instanceId') or inst.get('instance_id') or mi['itemId']), inst)
            elif 'outfit' in mi:
                st['outfits'][str(mi['itemId'])] = mi['outfit']; st['items'][str(mi['itemId'])] = 1
            elif 'baseItem' in mi:
                st['items'][str(mi['itemId'])] = int(mi['baseItem'].get('num', 0) or 0)
    for k, v in lists.items():
        st[k] = v
    ids = [int(x) for k in lists for x in lists[k]] + [0]
    st['next_instance'] = max(ids) + 1
    st['garden']['furniture'] = {str(k): v for k, v in garden.items()}
    st['garden']['next_furniture_id'] = 1
    if schemes:
        st['garden']['schemes'] = {str(k): {'name': v, 'furniture': {}} for k, v in schemes.items()}
    st['records'] = pairs(msgs)
    # every official answer in the backup (shops, recruit history, life skills, friends, mail, ...), kept as-is so
    # nothing the backup window collected is lost, even where the server doesn't use it yet
    st['official_answers'] = pairs(msgs, every=True)
    from game.friends import import_friends
    import_friends(st, st['official_answers'].get('FriendReq'))
    from tools.import_extras import apply as apply_extras   # stickers, actions, events, wishing tree, world progress
    apply_extras(st, msgs)
    os.makedirs(SAVE_DIR, exist_ok=True)
    _save_registry(reg)
    path = os.path.join(SAVE_DIR, f'{pid}.json')
    if os.path.exists(path):  # re-import over an existing account: keep the old save next to it
        import shutil, time as _t
        shutil.copy(path, path + _t.strftime('.before_import_%Y%m%d_%H%M%S'))
    json.dump(st, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'imported "{st["name"]}" as player {pid}: {len(st["characters"])} characters, {len(st["items"])} item types, '
          f'{sum(len(v) for v in lists.values())} weapons/armors/posters/pets, {len(garden)} garden furniture')
    print(f'log in with the name: {login_name}')
    return path, uid, st['name']


if __name__ == '__main__':
    main()
