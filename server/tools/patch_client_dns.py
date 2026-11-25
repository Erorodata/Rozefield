"""Point ONE copy of the game at Rozefield by patching its il2cpp metadata (the Steam copy is untouched).

The client resolves its dispatch domain through a hard-coded HTTPDNS server (8.134.240.36). While the official
servers are up, that answer sends the game to official even with Config.txt pointing here. This swaps the HTTPDNS
address for 127.0.0.1, so the Rozefield server (HTTPDNS on port 80) answers instead.

    python tools/patch_client_dns.py "H:\\Backup\\OverField"            # patch (keeps global-metadata.dat.orig)
    python tools/patch_client_dns.py "H:\\Backup\\OverField" --revert
"""
import os
import shutil
import struct
import sys

OLD, NEW = b'8.134.240.36', b'127.0.0.1'


def main(game, revert=False):
    f = os.path.join(game, 'launcher_Data', 'il2cpp_data', 'Metadata', 'global-metadata.dat')
    if revert:
        shutil.copy2(f + '.orig', f); print('restored', f); return 0
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
    d[ldo + pos:ldo + pos + len(NEW)] = NEW
    struct.pack_into('<I', d, lo + hit[0] * 8, len(NEW))
    open(f, 'wb').write(d)
    print('patched', f, '(metadata v%d)' % ver); return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[1], '--revert' in sys.argv))
