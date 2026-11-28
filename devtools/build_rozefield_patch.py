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


def apply_umbrella_weapons(g, umbrellas):
    """Add/update Parasol Etiquette weapons (1070000 + umbrella_id) with dedicated NewWeaponType=23
    (unused type so zero conflict with Bug Net 7 or Shovel 22; RozefieldPlugin maps 23->7 during equip)."""
    rows = g.get('Weapon', {}).get('datas', [])
    by_id = {int(r.get('ID', 0)): r for r in rows}
    changed = 0
    for u in umbrellas:
        uid = int(u.get('ID', 0))
        asset = u.get('AssetFullName')
        if not uid or not asset:
            continue
        tid = 1070000 + uid
        want = {
            'ID': tid,
            'ItemID': tid,
            'Durability': 100,
            'WeaponPropertyID': 1001001,
            'BaseScore': 1,
            'RollSpellGroupID': 100400,
            'NormalSpellID': 1004000,       # Bug Net over-the-shoulder idle holding pose
            'AssetFullName': asset,
            'NewWeaponSystemType': 6,
            'NewStrikeCorrectionType': 4,   # Matches Bug Net (1004001)
            'NewWeaponType': 23,            # Dedicated Parasol Etiquette type (no conflict with 7 or 22)
        }
        cur = by_id.get(tid)
        if cur is None:
            rows.append(want)
            by_id[tid] = want
            changed += 1
        elif cur != want:
            cur.clear()
            cur.update(want)
            changed += 1
    return changed


def apply_umbrella_items(g, umbrellas):
    """Add matching Item rows (1070000 + umbrella_id) with each umbrella's icon & name."""
    rows = g.get('Item', {}).get('datas', [])
    existing = {int(r.get('ID', 0)) for r in rows}
    added = 0
    for u in umbrellas:
        uid = int(u.get('ID', 0))
        if not uid:
            continue
        tid = 1070000 + uid
        if tid in existing:
            continue
        rows.append({
            'ID': tid,
            'TextID': uid,
            'IconID': uid,
            'RelateID': tid,
            'Quality': 3,
            'NewBagItemTag': 2,         # EBagItemTag_Weapon
        })
        existing.add(tid)
        added += 1
    return added


def apply_missing_rod_icons(g):
    """Point Practical Fishing Rod (1006004, whose icon_caijidaoju_yugan_04 PNG is absent from the client manifest)
    to icon_caijidaoju_yugan_01 so it renders and equips cleanly in storage and Fitting Room."""
    n = 0
    for r in g.get('Icon', {}).get('datas', []):
        if int(r.get('ID', 0)) == 1006004:
            want = [
                'Texture/Item/Weapon/icon_caijidaoju_yugan_01',
                'Texture/Item/Weapon/icon_caijidaoju_yugan_01_1024',
                'Texture/Item/Weapon/icon_caijidaoju_yugan_01_512',
            ]
            if r.get('AssetFullName') != want:
                r['AssetFullName'] = want
                n += 1
    return n


def apply_dye_slot_count(g):
    """Set Fashion_ColoringPlan_Count = 11 (1 Default slot 0 + 10 Dye slots 1..10)."""
    n = 0
    for r in g.get('Config', {}).get('datas', []):
        if r.get('Key') == 'Fashion_ColoringPlan_Count':
            if r.get('Values') != ['11']:
                r['Values'] = ['11']
                n += 1
    return n


def apply_umbrella_tool_expression(g):
    """Restore Shovel entry (ID 2008) to its original IconID 2008, and add dedicated
    Tools bar entry ID 2009 ('Parasol Etiquette', IconID 4000, NewExpressionType=3)."""
    rows = g.get('Expression', {}).get('datas', [])
    n = 0
    has_2009 = False
    for r in rows:
        rid = int(r.get('ID', 0))
        if rid == 2008 and int(r.get('IconID', 0)) != 2008:
            r['IconID'] = 2008
            n += 1
        elif rid == 2009:
            has_2009 = True
            if int(r.get('IconID', 0)) != 4000:
                r['IconID'] = 4000
                n += 1
    if not has_2009:
        rows.append({
            'ID': 2009,
            'TextID': 2009,
            'IconID': 4000,
            'ExpressionGroupInfo': [{'Index': 1, 'IsShow': True}],
            'NewExpressionType': 3,
        })
        n += 1
    return n


def apply_umbrella_tool_string(g):
    """Restore StringExpression ID 2008 to 'Shovel', add StringExpression ID 2009
    ('Parasol Etiquette'), and update any Fishing Rod text referencing Sherry -> Chang."""
    n = 0
    se_rows = g.get('StringExpression', {}).get('datas', [])
    has_2009 = False
    for r in se_rows:
        rid = int(r.get('ID', 0))
        if rid == 2008:
            txt = r.get('Text', [])
            if txt and txt[0] != 'Shovel':
                txt[0] = 'Shovel'
                r['Text'] = txt
                n += 1
        elif rid == 2009:
            has_2009 = True
            txt = r.get('Text', [])
            if not txt or txt[0] != 'Parasol Etiquette':
                r['Text'] = ['Parasol Etiquette', '', '', '']
                n += 1
    if not has_2009:
        se_rows.append({'ID': 2009, 'Text': ['Parasol Etiquette', '', '', '']})
        n += 1
    for tbl in g.values():
        if not isinstance(tbl, dict) or 'datas' not in tbl:
            continue
        for r in tbl['datas']:
            txts = r.get('Text')
            if not isinstance(txts, list):
                continue
            for i, t in enumerate(txts):
                if isinstance(t, str) and 'sherry' in t.lower() and ('fishing rod' in t.lower() or 'fishingrod' in t.lower()):
                    nt = t.replace("Sherry's General Store", "Chang's Lifestyle Store").replace("Sherry's", "Chang's").replace('Sherry', 'Chang')
                    if nt != t:
                        txts[i] = nt
                        n += 1
    return n


def apply_remove_outfit_gender(g):
    """QOL: remove gender & character restrictions (NewSexType / OnlyCharacterID) on outfits."""
    n = 0
    for r in g.get('FashionInfo', {}).get('datas', []):
        changed = False
        if r.pop('NewSexType', None):
            changed = True
        if r.pop('OnlyCharacterID', None):
            changed = True
        if changed:
            n += 1
    return n


def patch_config_bundle(src_bytes, shops_cfg, min_players):
    env = UnityPy.load(src_bytes)
    report = {}
    by_base = {os.path.basename(p): obj for p, obj in env.container.items()}

    # Read umbrella list first so weapon.bytes & item.bytes can register all 240 Shovel-slot Umbrella Tools
    umbrellas = []
    if 'umbrella.bytes' in by_base:
        t = by_base['umbrella.bytes'].read()
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName('protocol.AllUmbrellaDatas'))
        m = cls()
        m.ParseFromString(t.m_Script.encode('utf-8', 'surrogateescape'))
        ug = json_format.MessageToDict(m, preserving_proto_field_name=True)
        umbrellas = ug.get('Umbrella', {}).get('datas', [])

    if 'scene.bytes' in by_base:
        report['scene_themes_off'] = _patch_table(by_base['scene.bytes'], 'protocol.AllSceneDatas', clear_event_themes)
    if 'shop.bytes' in by_base:
        report['shop'] = _patch_table(by_base['shop.bytes'], 'protocol.AllShopDatas', lambda g: apply_shop_overrides(g, shops_cfg))
    if 'teamgameplay.bytes' in by_base:
        report['coop_min_updated'] = _patch_table(by_base['teamgameplay.bytes'], 'protocol.AllTeamGameplayDatas', lambda g: apply_coop_min_players(g, min_players))
    if umbrellas and 'weapon.bytes' in by_base:
        report['umbrella_weapons_added'] = _patch_table(by_base['weapon.bytes'], 'protocol.AllWeaponDatas', lambda g: apply_umbrella_weapons(g, umbrellas))
    if umbrellas and 'item.bytes' in by_base:
        report['umbrella_items_added'] = _patch_table(by_base['item.bytes'], 'protocol.AllItemDatas', lambda g: apply_umbrella_items(g, umbrellas))
    if 'ui.bytes' in by_base:
        report['rod_icons_fixed'] = _patch_table(by_base['ui.bytes'], 'protocol.AllUIDatas', apply_missing_rod_icons)
    if 'globalconfig.bytes' in by_base:
        report['dye_slots_11'] = _patch_table(by_base['globalconfig.bytes'], 'protocol.AllGlobalConfigDatas', apply_dye_slot_count)
    if 'expression.bytes' in by_base:
        report['umbrella_tool_icon'] = _patch_table(by_base['expression.bytes'], 'protocol.AllExpressionDatas', apply_umbrella_tool_expression)
    if 'string_english.bytes' in by_base:
        report['umbrella_tool_label'] = _patch_table(by_base['string_english.bytes'], 'protocol.AllStringDatas', apply_umbrella_tool_string)
    if 'fashion.bytes' in by_base:
        report['outfit_gender_unlocked'] = _patch_table(by_base['fashion.bytes'], 'protocol.AllFashionDatas', apply_remove_outfit_gender)
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
        'Umbrella Tool in temporary Shovel slot 22 (weapon + item config)',
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
