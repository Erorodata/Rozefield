"""Pictures for the backup window, taken from YOUR OverField install (nothing from the game is shipped with Rozefield):
the phone-menu icons for the checklist and the World Selection pictures for the maps.

    py tools\\extract_backup_assets.py "<game folder>"      (e.g. H:\\SteamLibrary\\steamapps\\common\\OverField)

Writes backup_tool\\assets\\icon_<name>.png and map_<scene>.png. The backup window works without them (plain drawing).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

MAIN = 'Assets/ResBundle/UI/UI_Root_Main/Processed/'
ICONS = {   # checklist item -> phone menu icon (UI_Root_Main sprite)
    'account': '4e8b6ee9f9804474bad392906996f41c',      # Inventory
    'achieve': '7da89b4108dd3d34d9c3b0cfc54fffc1',      # Achievement
    'life': '41d82a206d06e8d46ac4467bb1fc78d9',         # Life Skills
    'lifebook': 'bc8c6157c1605da43baad52dd081c227',     # life collection (fish & plants)
    'explore': 'ac1845a73290b9349873f19ab8205de9',      # Gap
    'poster': 'cb7fcf2552ae7b24a96e6cb2c42f3dee',       # poster
    'friend': '0cbe761161b840742a56e3ed3d6ebb2a',       # Friend
    'g_mail': 'ff0f2a734bf30d6459fb289777db1148',       # mail (white glyph, drawn on colour)
    'g_plaza': '496b2f126508a485084fd22a6a8cc206',      # decoration (white glyph)
    'preset': '4102c5e9c2ebb2745af9c5123817afe1',       # presets
    'charach': '30d29f1061178ed44b64a6f545ef2b86',      # Salvager
    'g_fields': '097587dd1d6e93c4999fabb9e21f01ef',     # Sequence / Aberrant Fields (white glyph)
}
MAPS = {s: 'shijie_01_xiaotu_%s' % s for s in ('01', '02', '03', '04', '05', '06', '1001', '1002', '1003', '9999')}


def bundle_file(yoodir, b):
    from tools.build_cn_patch import cache_path, builtin_path
    p = cache_path(yoodir, b['hash'])
    if os.path.exists(p):
        return p
    return builtin_path(yoodir, b['hash'], b['name'])


def main():
    import UnityPy
    from tools.build_cn_patch import latest
    game = sys.argv[1] if len(sys.argv) > 1 else r'H:\SteamLibrary\steamapps\common\OverField'
    yoodir = os.path.join(game, 'launcher_Data', 'yoo')
    m, _ = latest(yoodir)
    by_path = {a['path']: m.bundles[a['bundle']] for a in m.assets}
    out = os.path.join(HERE, 'backup_tool', 'assets')
    os.makedirs(out, exist_ok=True)
    wanted = {MAIN + h + '.png': 'icon_' + k for k, h in ICONS.items()}
    for s, nm in MAPS.items():   # English pictures (US atlas) if this install has them, else the default ones
        cands = [p for p in by_path if p.endswith('/Texture/Background/' + nm + '.png')]
        cands.sort(key=lambda p: (0 if '/Atlas/US/' in p else 1 if '/Atlas/CN/' in p else 2))
        for p in cands:
            f = bundle_file(yoodir, by_path[p])
            if f and os.path.exists(f):
                wanted[p] = 'map_' + str(int(s))
                break
    done = 0
    for bundle in {by_path[p]['name']: by_path[p] for p in wanted if p in by_path}.values():
        f = bundle_file(yoodir, bundle)
        if not f or not os.path.exists(f):
            print('missing bundle', bundle['name']); continue
        env = UnityPy.load(f)
        for path, o in env.container.items():
            key = wanted.get(path) or {k.lower(): v for k, v in wanted.items()}.get(path.lower())
            if not key or o.type.name not in ('Sprite', 'Texture2D'):
                continue
            im = o.read().image
            if key.startswith('map_') and im.height > im.width * 1.1:
                im = im.crop((0, 0, im.width, int(im.height * 0.78)))   # leave out the caption strip
            im.save(os.path.join(out, key + '.png'))
            done += 1
    print(done, 'pictures ->', out)


if __name__ == '__main__':
    main()
