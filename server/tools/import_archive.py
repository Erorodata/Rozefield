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
from game.player import Player, INSTANCE_TAGS, SAVE_DIR, _registry, _save_registry  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='login name to attach the archived account to')
    ap.add_argument('captures', nargs='+')
    a = ap.parse_args()
    md = None; pack = []; lists = {'weapons': {}, 'armors': {}, 'posters': {}, 'pets': {}}; garden = {}
    for cap in a.captures:
        print('reading', cap)
        for port, msgs in streams(cap).items():
            for ts, d, h, body in msgs:
                if d != 'S2C':
                    continue
                try:
                    name, m = decode(h.msg_id, body)
                except Exception:
                    continue
                if name == 'PlayerMainDataRsp':
                    md = to_dict(m)
                elif name == 'PackNotice':
                    pack.append(to_dict(m))
                elif name in ('GetWeaponRsp', 'GetArmorRsp', 'GetPosterRsp', 'GetPetRsp'):
                    k = name[3:-3].lower() + 's'
                    for inst in to_dict(m).get(k, []):
                        lists[k][str(inst.get('instanceId') or inst.get('instance_id'))] = inst
                elif name == 'SceneDataNotice' and md:
                    sd = to_dict(m).get('data', {})
                    if sd.get('channelId') == md.get('player_id'):
                        garden = sd.get('sceneGardenData', {}).get('gardenFurnitureInfoMap', garden)
    if not md:
        sys.exit('no PlayerMainDataRsp found in these captures')
    d = Data()
    uid = 'rz_' + a.name.lower()
    reg = _registry()
    pid = reg['by_uid'].get(uid) or md['player_id']
    reg['by_uid'][uid] = pid
    st = Player.new_state(d, uid, pid, md.get('player_name', a.name))
    for k in ('level', 'exp', 'world_level', 'head', 'sign', 'phone_background', 'phone_case', 'birthday'):
        if k in md:
            st[k] = md[k]
    st['create_time'] = md.get('create_time', st['create_time'])
    st['unlock_functions'] = md.get('unlockFunctions', [])
    st['characters'] = {str(c['characterId']): c for c in md.get('characters', [])}
    st['team'] = md.get('team', {})
    st['placed_characters'] = md.get('placed_characters', [])
    st['appearance'] = md.get('appearance', {})
    st['quests'] = {str(q.get('questId', i)): q for i, q in enumerate(md.get('quest_detail', {}).get('quests', []))}
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
    os.makedirs(SAVE_DIR, exist_ok=True)
    reg['next_player_id'] = max(reg['next_player_id'], pid + 1) if pid < 2000000 else reg['next_player_id']
    _save_registry(reg)
    path = os.path.join(SAVE_DIR, f'{pid}.json')
    json.dump(st, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'imported "{st["name"]}" as player {pid}: {len(st["characters"])} characters, {len(st["items"])} item types, '
          f'{sum(len(v) for v in lists.values())} weapons/armors/posters/pets, {len(garden)} garden furniture')
    print(f'log in with the name: {a.name}')


if __name__ == '__main__':
    main()
