"""Extract the game's data tables from your installed client into server/data/*.json.

    py -m pip install UnityPy
    py tools\\extract_config.py "H:\\SteamLibrary\\steamapps\\common\\OverField\\launcher_Data\\yoo"

Finds the newest DefaultPackage manifest, locates the PBStaticConfigure bundle in the cache, and
decodes every table with the schemas in proto/overfield.desc.
"""
import glob, json, os, struct, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def read_manifest(path):
    d = open(path, 'rb').read(); p = [0]
    def u16():
        v = struct.unpack_from('<H', d, p[0])[0]; p[0] += 2; return v
    def i32():
        v = struct.unpack_from('<i', d, p[0])[0]; p[0] += 4; return v
    def s():
        n = u16(); v = d[p[0]:p[0] + n].decode('utf8'); p[0] += n; return v
    p[0] = 4; s(); p[0] += 7; s(); s(); s()
    assets = []
    for _ in range(i32()):
        s(); path_ = s(); s(); [s() for _ in range(u16())]; assets.append((path_, i32()))
    bundles = []
    for _ in range(i32()):
        name = s(); p[0] += 4; fh = s(); s(); p[0] += 9; [s() for _ in range(u16())]; [i32() for _ in range(u16())]
        bundles.append((name, fh))
    return assets, bundles


def main():
    import UnityPy
    from google.protobuf import descriptor_pb2, message_factory, json_format
    from ofproto import pool
    yoo = sys.argv[1]
    man = sorted(glob.glob(os.path.join(yoo, 'DefaultPackage', 'ManifestFiles', 'PackageManifest_DefaultPackage_*.bytes')))[-1]
    assets, bundles = read_manifest(man)
    bid = next(b for a, b in assets if 'PBStaticConfigure/' in a)
    fh = bundles[bid][1]
    data = os.path.join(yoo, 'DefaultPackage', 'CacheFiles', fh[:2], fh, '__data')
    print('manifest', os.path.basename(man), '-> bundle', bundles[bid][0])
    fds = descriptor_pb2.FileDescriptorSet(); fds.ParseFromString(open(os.path.join(HERE, 'proto', 'overfield.desc'), 'rb').read())
    tops = {m.name[3:-5].lower(): fd.package + '.' + m.name for fd in fds.file for m in fd.message_type
            if m.name.startswith('All') and m.name.endswith('Datas')}
    out = os.path.join(HERE, 'data'); os.makedirs(out, exist_ok=True)
    env = UnityPy.load(data); n = 0
    for path_, obj in env.container.items():
        if obj.type.name != 'TextAsset':
            continue
        t = obj.read(); raw = t.m_Script.encode('utf-8', 'surrogateescape') if isinstance(t.m_Script, str) else bytes(t.m_Script)
        base = os.path.basename(path_)[:-6]
        name = tops.get(base.replace('_', '')) or tops.get(base.lower()) or tops.get(base.split('_')[0])
        if not name:
            continue
        m = message_factory.GetMessageClass(pool.FindMessageTypeByName(name))(); m.ParseFromString(raw)
        json.dump(json_format.MessageToDict(m, preserving_proto_field_name=True), open(os.path.join(out, base + '.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        n += 1
    print(n, 'tables written to', out)


if __name__ == '__main__':
    main()
