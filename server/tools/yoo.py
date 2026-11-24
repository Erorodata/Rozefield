"""Read/write YooAsset 2.x binary package manifests (PackageManifest_<pkg>_<ver>.bytes)."""
import hashlib, struct, zlib


class Manifest:
    def __init__(self):
        self.header = {}
        self.assets = []   # dict(address, path, guid, tags, bundle)
        self.bundles = []  # dict(name, unity_crc, hash, crc, size, flag, tags, deps)


def read(path):
    d = open(path, 'rb').read(); p = [0]
    def u16():
        v = struct.unpack_from('<H', d, p[0])[0]; p[0] += 2; return v
    def i32():
        v = struct.unpack_from('<i', d, p[0])[0]; p[0] += 4; return v
    def u32():
        v = struct.unpack_from('<I', d, p[0])[0]; p[0] += 4; return v
    def i64():
        v = struct.unpack_from('<q', d, p[0])[0]; p[0] += 8; return v
    def b():
        v = d[p[0]]; p[0] += 1; return v
    def s():
        n = u16(); v = d[p[0]:p[0] + n].decode('utf8'); p[0] += n; return v
    m = Manifest()
    h = m.header
    h['sign'] = u32(); h['file_version'] = s(); h['addressable'] = b(); h['lower'] = b(); h['guid'] = b()
    h['name_style'] = i32(); h['pipeline'] = s(); h['package'] = s(); h['version'] = s()
    for _ in range(i32()):
        a = {'address': s(), 'path': s(), 'guid': s()}
        a['tags'] = [s() for _ in range(u16())]
        a['bundle'] = i32()
        m.assets.append(a)
    for _ in range(i32()):
        x = {'name': s(), 'unity_crc': u32(), 'hash': s(), 'crc': s(), 'size': i64(), 'flag': b()}
        x['tags'] = [s() for _ in range(u16())]
        x['deps'] = [i32() for _ in range(u16())]
        m.bundles.append(x)
    assert p[0] == len(d), f'manifest parse ended at {p[0]} of {len(d)}'
    return m


def write(m, path):
    out = bytearray()
    def u16(v): out.extend(struct.pack('<H', v))
    def i32(v): out.extend(struct.pack('<i', v))
    def u32(v): out.extend(struct.pack('<I', v))
    def i64(v): out.extend(struct.pack('<q', v))
    def b(v): out.append(v)
    def s(v):
        e = v.encode('utf8'); u16(len(e)); out.extend(e)
    h = m.header
    u32(h['sign']); s(h['file_version']); b(h['addressable']); b(h['lower']); b(h['guid'])
    i32(h['name_style']); s(h['pipeline']); s(h['package']); s(h['version'])
    i32(len(m.assets))
    for a in m.assets:
        s(a['address']); s(a['path']); s(a['guid']); u16(len(a['tags']))
        for t in a['tags']:
            s(t)
        i32(a['bundle'])
    i32(len(m.bundles))
    for x in m.bundles:
        s(x['name']); u32(x['unity_crc']); s(x['hash']); s(x['crc']); i64(x['size']); b(x['flag'])
        u16(len(x['tags']))
        for t in x['tags']:
            s(t)
        u16(len(x['deps']))
        for dd in x['deps']:
            i32(dd)
    open(path, 'wb').write(out)
    return hashlib.md5(out).hexdigest()


def file_hash(data):
    return hashlib.md5(data).hexdigest()


def file_crc(data):
    """YooAsset FileCRC as stored in manifests: CRC32 as little-endian hex."""
    return struct.pack('<I', zlib.crc32(data) & 0xffffffff).hex()
