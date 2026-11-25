"""Point ONE copy of the game at Rozefield by patching its il2cpp metadata (the Steam copy is untouched).

The client resolves its dispatch domain through a hard-coded HTTPDNS server (8.134.240.36). While the official
servers are up, that answer sends the game to official even with Config.txt pointing here. This swaps the HTTPDNS
address for 127.0.0.1, so the Rozefield server (HTTPDNS on port 80) answers instead.

    python tools/patch_client_dns.py "H:\\Backup\\OverField"            # patch (keeps global-metadata.dat.orig)
    python tools/patch_client_dns.py "H:\\Backup\\OverField" 192.168.1.5   # server on another PC (12 characters at most)
    python tools/patch_client_dns.py "H:\\Backup\\OverField" --revert

The address must fit in the original 12 characters. For a longer one use a short name, e.g. "rozefield",
and add a line "<server ip> rozefield" to that PC's hosts file.
"""
import os
import shutil
import struct
import sys

OLD, NEW = b'8.134.240.36', b'127.0.0.1'


def main(game, revert=False, target='127.0.0.1'):
    f = os.path.join(game, 'launcher_Data', 'il2cpp_data', 'Metadata', 'global-metadata.dat')
    if revert:
        shutil.copy2(f + '.orig', f); print('restored', f); return 0
    new = target.encode('ascii')
    if len(new) > len(OLD):
        print(f'"{target}" is longer than {len(OLD)} characters: use a short name and a hosts-file line instead'); return 1
    if os.path.exists(f + '.orig'):       # always patch from the original, so the address can be changed later
        shutil.copy2(f + '.orig', f)
    d = bytearray(open(f, 'rb').read())
    _, ver, lo, ls, ldo, _ = struct.unpack_from('<IiIIII', d, 0)
    pos = d.find(OLD, ldo) - ldo
    if pos < 0:
        print('already patched (or unknown build)'); return 1
    hit = [i for i in range(ls // 8) if struct.unpack_from('<Ii', d, lo + i * 8) == (len(OLD), pos)]
    if len(hit) != 1:
        print('string literal not found; build not supported'); return 1
    if not os.path.exists(f + '.orig'):
        shutil.copy2(f, f + '.orig')
    d[ldo + pos:ldo + pos + len(new)] = new
    struct.pack_into('<I', d, lo + hit[0] * 8, len(new))
    open(f, 'wb').write(d)
    print('patched', f, '-> %s (metadata v%d)' % (target, ver)); return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    rest = [x for x in sys.argv[2:] if not x.startswith('--')]
    sys.exit(main(sys.argv[1], '--revert' in sys.argv, rest[0] if rest else '127.0.0.1'))
