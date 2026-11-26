"""Build the open-world data from a decoded official capture (tools/re/gatedecode.py output):

  data/scene_layout.json             per scene: chests (index -> boxId, type), gather limits, chairs, vehicles
  data/dungeon_rewards_observed.json dungeon final-chest contents seen on the official server
and, with --save, copy the captured player's own world progress (opened chests, riddles, flags, challenges,
areas, collections, dungeons) into that Rozefield save.

    py tools/import_world.py capture_decoded.json [--save save/accounts/<pid>.json]
"""
import argparse, json, os, sys
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('decoded', nargs='+')
    ap.add_argument('--save')
    a = ap.parse_args()
    lay_p = os.path.join(HERE, 'data', 'scene_layout.json')
    obs_p = os.path.join(HERE, 'data', 'dungeon_rewards_observed.json')
    lay = json.load(open(lay_p, encoding='utf-8')) if os.path.exists(lay_p) else {}
    obs = json.load(open(obs_p, encoding='utf-8')) if os.path.exists(obs_p) else {}
    last_scene = {}
    for f in a.decoded:
        d = json.load(open(f, encoding='utf-8'))
        pend, cur = {}, None
        for p in d:
            n, b = p.get('name'), p.get('body') or {}
            if n == 'SceneDataNotice':
                sd = b.get('data', {})
                sid = str(sd.get('sceneId'))
                L = lay.setdefault(sid, {})
                boxes = {x.get('index', 0): x for x in L.get('treasureBoxes', [])}
                for x in sd.get('treasureBoxes', []):
                    boxes[x.get('index', 0)] = {'index': x.get('index', 0), 'boxId': x.get('boxId', 0), 'type': x.get('type', 'ETreasureBoxType_Normal')}
                if boxes:
                    L['treasureBoxes'] = sorted(boxes.values(), key=lambda x: x.get('index', 0))
                for k in ('chairInfoList', 'vehicleInfoList', 'campFires'):
                    if sd.get(k) and sid != '9999':
                        L[k] = sd[k]
                if sd.get('gatherLimits'):
                    L['gatherLimits'] = sd['gatherLimits']
                if sid != '9999':
                    last_scene[sid] = sd
            if p.get('dir') == 'C2S':
                pend[(p.get('port'), (p.get('head') or {}).get('packet_id'))] = p
                if n == 'DungeonEnterReq':
                    cur = b.get('dungeon_id')
            elif n == 'TreasureBoxOpenRsp':
                q = pend.get((p.get('port'), (p.get('head') or {}).get('packet_id')))
                if q and (q.get('body') or {}).get('loc_type') == 'TreasureBoxLocType_DUNGEON' and cur:
                    obs[str(cur)] = [[x['mainItem']['itemId'], int((x['mainItem'].get('baseItem') or {}).get('num', 1))]
                                     for x in b.get('items', [])]
    os.makedirs(os.path.dirname(lay_p), exist_ok=True)
    json.dump(lay, open(lay_p, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(obs, open(obs_p, 'w', encoding='utf-8'), ensure_ascii=False)
    print('scenes', sorted(lay, key=int), 'chests', sum(len(v.get('treasureBoxes', [])) for v in lay.values()), 'dungeons observed', len(obs))
    if a.save:
        s = json.load(open(a.save, encoding='utf-8'))
        world = s.setdefault('world', {})
        for sid, sd in last_scene.items():
            w = world.setdefault(sid, {})
            w['boxes'] = {str(x.get('index', 0)): {'refresh': int(x.get('nextRefreshTime', 0) or 0)}
                          for x in sd.get('treasureBoxes', []) if x.get('state') == 'TreasureBoxState_Open'}
            for k in ('riddles', 'flags', 'challenges', 'areas', 'collections', 'flagIds'):
                w[k] = sd.get(k, [])
            for dd in sd.get('dungeons', []):
                s.setdefault('dungeons', {})[str(dd['dungeonId'])] = dd
        json.dump(s, open(a.save, 'w', encoding='utf-8'), ensure_ascii=False)
        print('world progress imported into', a.save, {k: len(v.get('boxes', {})) for k, v in world.items()})


if __name__ == '__main__':
    main()
