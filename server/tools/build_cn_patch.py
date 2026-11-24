"""Build a Rozefield resource patch that adds the CN-client-only content to the Global (Steam) client.

    py tools\\build_cn_patch.py --global "H:\\SteamLibrary\\steamapps\\common\\OverField\\launcher_Data\\yoo"
                                --cn "H:\\OverField\\OverField Game\\launcher_Data\\yoo"
                                --config patch_src\\pbstaticconfigure.bundle

Writes patch/ (served by rozefield_server.py):
  patch/ManifestFiles/PackageManifest_DefaultPackage_<ver>.bytes/.hash + .version
  patch/files.json  {"<hash>.bundle": "<path of the file on this PC>"}
The Global client then downloads the new files through its own updater. Nothing in the game folder is edited.
"""
import argparse, collections, glob, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from tools import yoo  # noqa: E402

CONFIG_BUNDLE = 'assets_development_excel_scripts_pbstaticconfigure_resbundle_pbstaticconfigure.bundle'


def latest(yoodir):
    md = os.path.join(yoodir, 'DefaultPackage', 'ManifestFiles')
    v = open(os.path.join(md, 'PackageManifest_DefaultPackage.version')).read().strip()
    return yoo.read(os.path.join(md, f'PackageManifest_DefaultPackage_{v}.bytes')), v


def cache_path(yoodir, h):
    return os.path.join(yoodir, 'DefaultPackage', 'CacheFiles', h[:2], h, '__data')


def builtin_path(yoodir, h, name):
    # StreamingAssets copy (built-in files) live next to the game's StreamingAssets/yoo
    sa = os.path.join(os.path.dirname(yoodir), 'StreamingAssets', 'yoo', 'DefaultPackage')
    for c in (os.path.join(sa, h + '.bundle'), os.path.join(sa, name)):
        if os.path.exists(c):
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--global', dest='g', required=True)
    ap.add_argument('--cn', required=True)
    ap.add_argument('--config', required=True, help='merged pbstaticconfigure bundle')
    ap.add_argument('--out', default=os.path.join(HERE, 'patch'))
    ap.add_argument('--version', default=None)
    a = ap.parse_args()

    g, gver = latest(a.g)
    c, cver = latest(a.cn)
    ver = a.version or gver + '-rz-cn'
    print(f'global {gver}: {len(g.assets)} assets / {len(g.bundles)} bundles; cn {cver}: {len(c.assets)} / {len(c.bundles)}')

    gidx = {b['name']: i for i, b in enumerate(g.bundles)}
    cidx = {b['name']: i for i, b in enumerate(c.bundles)}
    gpaths = {x['path'] for x in g.assets}
    ga, ca = collections.defaultdict(set), collections.defaultdict(set)
    for x in g.assets:
        ga[g.bundles[x['bundle']]['name']].add(x['path'])
    for x in c.assets:
        ca[c.bundles[x['bundle']]['name']].add(x['path'])

    def cn_file(name):
        b = c.bundles[cidx[name]]
        p = cache_path(a.cn, b['hash'])
        return p if os.path.exists(p) else builtin_path(a.cn, b['hash'], name)

    new_assets = [x for x in c.assets if x['path'] not in gpaths]
    skipped = collections.Counter()
    take = {}     # bundle name -> source file
    for x in new_assets:
        name = c.bundles[x['bundle']]['name']
        if name == CONFIG_BUNDLE:
            continue
        if name in gidx and not ga[name] <= ca[name]:
            skipped['shared bundle changed differently in Global'] += 1
            continue
        # this bundle + every dependency the Global client does not have
        stack, need, ok = [name], {}, True
        while stack:
            n = stack.pop()
            if n in need or n in take:
                continue
            if n != name and n in gidx:
                continue  # Global already has its own copy of this dependency
            f = cn_file(n)
            if not f:
                ok = False
                break
            need[n] = f
            stack += [c.bundles[d]['name'] for d in c.bundles[cidx[n]]['deps']]
        if not ok:
            skipped['bundle not downloaded in the CN client'] += 1
            continue
        take.update(need)

    m = yoo.read(os.path.join(a.g, 'DefaultPackage', 'ManifestFiles', f'PackageManifest_DefaultPackage_{gver}.bytes'))
    m.header['version'] = ver
    idx = {b['name']: i for i, b in enumerate(m.bundles)}
    files = {}
    for name, src in take.items():
        cb = dict(c.bundles[cidx[name]])
        if name in idx:
            i = idx[name]
        else:
            i = len(m.bundles); idx[name] = i; m.bundles.append(None)
        cb['deps_names'] = [c.bundles[d]['name'] for d in cb['deps']]
        m.bundles[i] = cb
        files[cb['hash'] + '.bundle'] = src
    for name in take:  # remap dependency ids by name
        b = m.bundles[idx[name]]
        b['deps'] = [idx[n] for n in b.pop('deps_names') if n in idx]
    added = 0
    for x in new_assets:
        name = c.bundles[x['bundle']]['name']
        if name in take:
            m.assets.append({**x, 'bundle': idx[name]}); added += 1
    # merged data tables
    data = open(a.config, 'rb').read()
    cb = m.bundles[idx[CONFIG_BUNDLE]]
    cb.update(hash=yoo.file_hash(data), crc=yoo.file_crc(data), size=len(data), unity_crc=0)
    os.makedirs(os.path.join(a.out, 'files'), exist_ok=True)
    cfg_copy = os.path.join(a.out, 'files', cb['hash'] + '.bundle')
    open(cfg_copy, 'wb').write(data)
    files[cb['hash'] + '.bundle'] = cfg_copy

    md = os.path.join(a.out, 'ManifestFiles'); os.makedirs(md, exist_ok=True)
    for f in glob.glob(os.path.join(md, '*')):
        os.remove(f)
    mf = os.path.join(md, f'PackageManifest_DefaultPackage_{ver}.bytes')
    h = yoo.write(m, mf)
    open(os.path.join(md, f'PackageManifest_DefaultPackage_{ver}.hash'), 'w').write(h)
    open(os.path.join(md, 'PackageManifest_DefaultPackage.version'), 'w').write(ver)
    for f in os.listdir(md):
        files[f] = os.path.join(md, f)
    json.dump(files, open(os.path.join(a.out, 'files.json'), 'w', encoding='utf-8'), indent=0, ensure_ascii=False)
    json.dump({'version': ver, 'base': gver, 'cn': cver}, open(os.path.join(a.out, 'patch.json'), 'w'))
    size = sum(os.path.getsize(p) for p in files.values())
    print(f'patch {ver}: {added} new assets in {len(take)} bundles ({size / 1e6:.0f} MB) + merged data tables')
    for k, v in skipped.items():
        print(f'  skipped {v} assets: {k}')


if __name__ == '__main__':
    main()
