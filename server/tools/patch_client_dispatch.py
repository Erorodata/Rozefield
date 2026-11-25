"""Point ONE copy of the game's dispatch address at this PC (data.unity3d, InitConfigAsset), so it can never fall
through to the official dispatch server while official is still up. Pairs with tools/patch_client_dns.py.

    py tools/patch_client_dispatch.py "H:\\Backup\\OverField"            # keeps data.unity3d.orig
    py tools/patch_client_dispatch.py "H:\\Backup\\OverField" --revert
"""
import os, shutil, struct, sys
import UnityPy

OLD, NEW = b'http://dsp-global-of.inutan.com:18881', b'http://127.0.0.1:18881'


def main(game, revert=False):
    f = os.path.join(game, 'launcher_Data', 'data.unity3d')
    if revert:
        shutil.copy2(f + '.orig', f); print('restored', f); return 0
    if not os.path.exists(f + '.orig'):
        shutil.copy2(f, f + '.orig')
    env = UnityPy.load(f + '.orig'); done = 0
    for obj in env.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        raw = bytearray(obj.get_raw_data()); i = raw.find(OLD)
        if i < 4 or struct.unpack_from('<i', raw, i - 4)[0] != len(OLD):
            continue
        pad = lambda n: (n + 3) & ~3
        raw[i - 4:i + pad(len(OLD))] = struct.pack('<i', len(NEW)) + NEW + b'\0' * (pad(len(NEW)) - len(NEW))
        obj.set_raw_data(bytes(raw)); done += 1
    if not done:
        print('dispatch address not found (already patched, or another build)'); return 1
    open(f, 'wb').write(env.file.save(packer='original'))
    print('patched', f); return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[1], '--revert' in sys.argv))
