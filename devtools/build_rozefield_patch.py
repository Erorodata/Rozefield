"""Build the Rozefield client resource patch (H:\\Backup\\Server\\patch\\).

Applies Rozefield's client-side resource tweaks to copies of the two patched bundles
(never touching Steam or Bilibili installs) and regenerates the YooAsset manifest:
  1. assets_scenes_home_scene.bundle:
     - Disables "活动家具" (seasonal event furniture) so Rota Plaza keeps its default look.
     - Disables "包围盒v1" (plaza perimeter invisible wall MeshCollider) so players can walk behind the park area.
  2. pbstaticconfigure.bundle:
     - scene.bytes: clears seasonal event theme dates (default stage).
     - shop.bytes: applies packs/official/systems/shops.json (removes rod from Sherry 15000, adds all 10 rods + 3 Feline Token pools to Chang 16000).
     - teamgameplay.bytes: sets Co-op PlayerMin to packs/official/systems/coop.json min_players (2).

Usage:
    py -3.13 devtools\\build_rozefield_patch.py <patch_dir> [new_version]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, 'server')
sys.path.insert(0, SERVER_DIR)
sys.path.insert(1, ROOT)

import UnityPy
from google.protobuf import json_format, message_factory
from devtools import yoo
from devtools.default_stage import clear_event_themes
from ofproto import pool

SCENE_DISABLE_GROUPS = ('活动家具', '包围盒v1')


def patch_home_scene(src_bytes):
    env = UnityPy.load(src_bytes)
    changed = {}
    for o in env.objects:
        if o.type.name == 'GameObject':
            g = o.read()
            if g.m_Name in SCENE_DISABLE_GROUPS:
                if g.m_IsActive:
                    g.m_IsActive = False
                    g.save()
                    changed[g.m_Name] = changed.get(g.m_Name, 0) + 1
                else:
                    changed.setdefault(g.m_Name, 0)
    return env.file.save(packer='lz4'), changed


def _patch_table(obj, proto_name, fn):
    t = obj.read()
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(proto_name))
    m = cls()
    m.ParseFromString(t.m_Script.encode('utf-8', 'surrogateescape'))
    g = json_format.MessageToDict(m, preserving_proto_field_name=True)
    info = fn(g)
    m2 = cls()
    json_format.ParseDict(g, m2, ignore_unknown_fields=True)
    t.m_Script = m2.SerializeToString().decode('utf-8', 'surrogateescape')
    t.save()
    return info


def apply_shop_overrides(g, shops_cfg):
    removed, added_grids, added_pools = 0, 0, 0
    rm_map = {int(k): set(v) for k, v in (shops_cfg.get('remove_grids') or {}).items()}
    add_map = {int(k): v for k, v in (shops_cfg.get('add_grids') or {}).items()}
    for row in g.get('Grid', {}).get('datas', []):
        sid = int(row.get('ID', 0))
        items = row.get('Items', [])
        if sid in rm_map:
            before = len(items)
            items = [it for it in items if int(it.get('GridID', 0)) not in rm_map[sid]]
            removed += before - len(items)
        if sid in add_map:
            existing = {int(it.get('GridID', 0)) for it in items}
            for extra in add_map[sid]:
                gid = int(extra['GridID'])
                if gid not in existing:
                    entry = dict(extra)
                    entry.setdefault('Index', gid)
                    items.append(entry)
                    existing.add(gid)
                    added_grids += 1
        row['Items'] = items

    pools = g.get('Pool', {}).get('datas', [])
    existing_pools = {int(p.get('ID', 0)) for p in pools}
    for pid_s, pdata in (shops_cfg.get('extra_pools') or {}).items():
        pid = int(pid_s)
        if pid in existing_pools:
            continue
        p_copy = {'ID': pid, 'Items': []}
        for it in pdata.get('Items', []):
            item_row = dict(it)
            item_row.setdefault('MinLevel', 1)
            item_row.setdefault('MaxLevel', 100)
            item_row.setdefault('Discount', 1.0)
            item_row.setdefault('ShowDiscount', 1.0)
            item_row.setdefault('IsHideInBag', True)
            p_copy['Items'].append(item_row)
        pools.append(p_copy)
        existing_pools.add(pid)
        added_pools += 1
    return {'removed_grids': removed, 'added_grids': added_grids, 'added_pools': added_pools}


def apply_coop_min_players(g, min_players):
    n = 0
    for mode in g.get('Mode', {}).get('datas', []):
        for item in mode.get('ModeItems', []):
            if int(item.get('PlayerMin', 0)) > min_players:
                item['PlayerMin'] = min_players
                n += 1
    return n


def patch_config_bundle(src_bytes, shops_cfg, min_players):
    env = UnityPy.load(src_bytes)
    report = {}
    for p, obj in env.container.items():
        base = os.path.basename(p)
        if base == 'scene.bytes':
            report['scene_themes_off'] = _patch_table(obj, 'protocol.AllSceneDatas', clear_event_themes)
        elif base == 'shop.bytes':
            report['shop'] = _patch_table(obj, 'protocol.AllShopDatas', lambda g: apply_shop_overrides(g, shops_cfg))
        elif base == 'teamgameplay.bytes':
            report['coop_min_updated'] = _patch_table(obj, 'protocol.AllTeamGameplayDatas', lambda g: apply_coop_min_players(g, min_players))
    return env.file.save(packer='lz4'), report


def build_patch(patch_dir, new_version='2026-11-28-07-45-00-rz-park'):
    patch_meta_path = os.path.join(patch_dir, 'patch.json')
    files_json_path = os.path.join(patch_dir, 'files.json')
    manifest_dir = os.path.join(patch_dir, 'ManifestFiles')
    files_dir = os.path.join(patch_dir, 'files')

    meta = json.load(open(patch_meta_path, encoding='utf-8'))
    old_version = meta['version']
    old_manifest_path = os.path.join(manifest_dir, f'PackageManifest_DefaultPackage_{old_version}.bytes')
    m = yoo.read(old_manifest_path)

    # Identify home_scene and pbstaticconfigure bundle entries in the manifest
    home_b = next(b for b in m.bundles if 'assets_scenes_home_scene' in b['name'])
    cfg_b = next(b for b in m.bundles if 'pbstaticconfigure' in b['name'])

    old_home_file = os.path.join(files_dir, f"{home_b['hash']}.bundle")
    old_cfg_file = os.path.join(files_dir, f"{cfg_b['hash']}.bundle")

    shops_cfg = json.load(open(os.path.join(SERVER_DIR, 'packs', 'official', 'systems', 'shops.json'), encoding='utf-8'))
    coop_cfg = json.load(open(os.path.join(SERVER_DIR, 'packs', 'official', 'systems', 'coop.json'), encoding='utf-8'))
    min_players = int(coop_cfg.get('min_players', 2))

    home_bytes, scene_report = patch_home_scene(open(old_home_file, 'rb').read())
    cfg_bytes, cfg_report = patch_config_bundle(open(old_cfg_file, 'rb').read(), shops_cfg, min_players)

    new_home_hash = yoo.file_hash(home_bytes)
    new_cfg_hash = yoo.file_hash(cfg_bytes)

    home_b['hash'] = new_home_hash
    home_b['crc'] = yoo.file_crc(home_bytes)
    home_b['size'] = len(home_bytes)
    home_b['unity_crc'] = 0

    cfg_b['hash'] = new_cfg_hash
    cfg_b['crc'] = yoo.file_crc(cfg_bytes)
    cfg_b['size'] = len(cfg_bytes)
    cfg_b['unity_crc'] = 0

    m.header['version'] = new_version

    # Write new bundles
    new_home_file = os.path.join(files_dir, f'{new_home_hash}.bundle')
    new_cfg_file = os.path.join(files_dir, f'{new_cfg_hash}.bundle')
    open(new_home_file, 'wb').write(home_bytes)
    open(new_cfg_file, 'wb').write(cfg_bytes)

    # Remove old superseded bundles if hashes changed
    for old_f, new_f in ((old_home_file, new_home_file), (old_cfg_file, new_cfg_file)):
        if os.path.normcase(old_f) != os.path.normcase(new_f) and os.path.exists(old_f):
            os.remove(old_f)

    # Write new manifest, hash, version
    new_manifest_name = f'PackageManifest_DefaultPackage_{new_version}.bytes'
    new_hash_name = f'PackageManifest_DefaultPackage_{new_version}.hash'
    new_manifest_path = os.path.join(manifest_dir, new_manifest_name)
    new_hash_path = os.path.join(manifest_dir, new_hash_name)
    version_path = os.path.join(manifest_dir, 'PackageManifest_DefaultPackage.version')

    m_md5 = yoo.write(m, new_manifest_path)
    open(new_hash_path, 'w', encoding='utf-8').write(m_md5)
    open(version_path, 'w', encoding='utf-8').write(new_version)

    # Remove old manifest & hash if version changed
    if old_version != new_version:
        for ext in ('bytes', 'hash'):
            p = os.path.join(manifest_dir, f'PackageManifest_DefaultPackage_{old_version}.{ext}')
            if os.path.exists(p):
                os.remove(p)

    # Update files.json and patch.json
    files_map = {
        f'{new_home_hash}.bundle': f'patch\\files\\{new_home_hash}.bundle',
        f'{new_cfg_hash}.bundle': f'patch\\files\\{new_cfg_hash}.bundle',
        'PackageManifest_DefaultPackage.version': 'patch\\ManifestFiles\\PackageManifest_DefaultPackage.version',
        new_manifest_name: f'patch\\ManifestFiles\\{new_manifest_name}',
        new_hash_name: f'patch\\ManifestFiles\\{new_hash_name}',
    }
    open(files_json_path, 'w', encoding='utf-8').write(json.dumps(files_map, indent=0))

    meta['version'] = new_version
    meta['changes'] = [
        'default plaza stage (config)',
        'plaza event furniture off (home scene)',
        'plaza park invisible wall off (包围盒v1)',
        'Chang store fishing rods & Sherry cleanup (shop config)',
        'Co-op min players 2 (teamgameplay config)',
    ]
    open(patch_meta_path, 'w', encoding='utf-8').write(json.dumps(meta, ensure_ascii=False))

    print('Patched OK:', new_version)
    print('  home_scene:', new_home_hash, len(home_bytes), scene_report)
    print('  config    :', new_cfg_hash, len(cfg_bytes), cfg_report)
    print('  manifest  :', m_md5)


if __name__ == '__main__':
    pdir = sys.argv[1] if len(sys.argv) > 1 else r'H:\Backup\Server\patch'
    ver = sys.argv[2] if len(sys.argv) > 2 else '2026-11-28-07-45-00-rz-park'
    build_patch(pdir, ver)
