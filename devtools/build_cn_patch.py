"""Build a Rozefield resource patch that adds the CN-client-only content to the Global (Steam) client.

    py tools\\build_cn_patch.py --global "H:\\SteamLibrary\\steamapps\\common\\OverField\\launcher_Data\\yoo"
                                --cn "H:\\OverField\\OverField Game\\launcher_Data\\yoo"
                                --config patch_src\\pbstaticconfigure.bundle

Writes patch/ (served by rozefield_server.py):
  patch/ManifestFiles/PackageManifest_DefaultPackage_<ver>.bytes/.hash + .version
  patch/files.json  {"<hash>.bundle": "<path, relative to the server folder when inside it>"}
The Global client then downloads the new files through its own updater. Nothing in the game folder is edited.
"""
import argparse, collections, glob, json, os, sys
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # devtools package
from devtools import yoo  # noqa: E402

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

    new_assets = [x for x in c.assets if x['path'] not in gpaths and not x['path'].endswith('.unity')]
    skipped = collections.Counter(scene=sum(1 for x in c.assets if x['path'] not in gpaths and x['path'].endswith('.unity')))
    holders = {c.bundles[x['bundle']]['name'] for x in new_assets} - {CONFIG_BUNDLE}
    clone = {n for n in holders if n in gidx}          # Global has a bundle with this name: ship a renamed copy
    take = {}                                          # CN bundle name -> source file
    for name in sorted(holders):
        stack, need, ok = [name], {}, True
        while stack:
            n = stack.pop()
            if n in need or n in take:
                continue
            if n in gidx and n not in clone:
                continue                               # use the Global client's own copy of this dependency
            f = cn_file(n)
            if not f:
                ok = False; break
            need[n] = f
            stack += [c.bundles[d]['name'] for d in c.bundles[cidx[n]]['deps']]
        if ok:
            take.update(need)
        else:
            skipped['bundle not downloaded in the CN client'] += len(ca[name] - gpaths)
    clone &= set(take)
    from devtools import bundlefix
    print(f'{len(take)} bundles ({len(clone)} renamed copies); reading internal names...')
    cab_map = {}
    for n in clone:
        out_name = 'rzcn_' + n
        for cab in bundlefix.cab_names(take[n]):
            cab_map[cab] = bundlefix.new_cab(cab, out_name)
    out_dir = os.path.join(a.out, 'files'); os.makedirs(out_dir, exist_ok=True)

    m = yoo.read(os.path.join(a.g, 'DefaultPackage', 'ManifestFiles', f'PackageManifest_DefaultPackage_{gver}.bytes'))
    m.header['version'] = ver
    idx = {b['name']: i for i, b in enumerate(m.bundles)}
    files = {}
    out_of = {n: ('rzcn_' + n if n in clone else n) for n in take}
    for n in take:
        idx[out_of[n]] = len(m.bundles); m.bundles.append(None)
    for k, (n, src) in enumerate(sorted(take.items())):
        cb = dict(c.bundles[cidx[n]])
        dep_names = [c.bundles[d]['name'] for d in cb['deps']]
        touches = n in clone or any(d in clone for d in dep_names)
        if touches:
            tmp = os.path.join(out_dir, 'tmp.bundle')
            data = bundlefix.process(src, tmp, cab_map, rename_to=out_of[n] if n in clone else None)
            h = yoo.file_hash(data)
            dst = os.path.join(out_dir, h + '.bundle')
            os.replace(tmp, dst)
            cb.update(hash=h, crc=yoo.file_crc(data), size=len(data), unity_crc=0)
            src = dst
        cb['name'] = out_of[n]
        cb['deps'] = [idx[out_of[d]] if d in take else idx[d] for d in dep_names if d in take or d in idx]
        m.bundles[idx[out_of[n]]] = cb
        files[cb['hash'] + '.bundle'] = src
        if (k + 1) % 25 == 0:
            print(f'  {k + 1}/{len(take)} bundles')
    added = 0
    for x in new_assets:
        n = c.bundles[x['bundle']]['name']
        if n in take:
            m.assets.append({**x, 'bundle': idx[out_of[n]]}); added += 1
    # merged data tables
    data = open(a.config, 'rb').read()
    cb = m.bundles[idx[CONFIG_BUNDLE]]
    cb.update(hash=yoo.file_hash(data), crc=yoo.file_crc(data), size=len(data), unity_crc=0)
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
    here = HERE   # paths inside the server folder are kept relative
    files = {k: (os.path.relpath(os.path.abspath(v), here) if os.path.abspath(v).startswith(here + os.sep) else v) for k, v in files.items()}
    json.dump(files, open(os.path.join(a.out, 'files.json'), 'w', encoding='utf-8'), indent=0, ensure_ascii=False)
    json.dump({'version': ver, 'base': gver, 'cn': cver}, open(os.path.join(a.out, 'patch.json'), 'w'))
    size = sum(os.path.getsize(p) for p in files.values())
    print(f'patch {ver}: {added} new assets in {len(take)} bundles, {len(clone)} of them renamed copies ({size / 1e6:.0f} MB) + merged data tables')
    for k, v in skipped.items():
        print(f'  skipped {v} assets: {k}')


if __name__ == '__main__':
    main()
