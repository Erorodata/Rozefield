"""Updates pushed from the owner's PC to this server (panel > Push update), and rolling them back.

Package format (RZUP1): b"RZUP1\\n" then entries: u32 path length, path (UTF-8, '/' separators, relative to the
server folder), u64 size, bytes. Only these parts are accepted; save/ (accounts, chat, photos) and settings never are.
Every file that gets replaced is kept first in update_backup_<time>/ (with a list of files that were new), so
Roll back can put the previous version back.
"""
import json
import os
import shutil
import struct
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = {
    'code': ('rozefield_server.py', 'ofproto.py', 'requirements.txt', 'game/', 'tools/', 'proto/', 'start_server.bat',
             'start_server.sh', 'install_linux.sh', 'setup_python.bat', 'allow_friends.bat', 'README.md', 'Hosting guide.md', 'packs/'),
    'data': ('data/', 'data-merged/', 'data-merged.zip'),
    'patch': ('patch/',),
    'panel': ('Overfield Server.exe',),
    'stub': ('sdk_stub/PCSDKUI.exe', 'link_relay/winhttp.dll'),   # login window + the Rozefield link for game packages
}
SKIP = ('__pycache__', '.pyc', '.tmp', '.log')


def part_of(rel):
    for name, prefixes in PARTS.items():
        for p in prefixes:
            if rel == p or (p.endswith('/') and rel.startswith(p)):
                return name
    return None


def _files(part):
    for p in PARTS[part]:
        full = os.path.join(HERE, p)
        if os.path.isfile(full):
            yield p, full
        elif p.endswith('/') and os.path.isdir(full):
            for root, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for f in files:
                    if not f.endswith(SKIP):
                        fp = os.path.join(root, f)
                        yield os.path.relpath(fp, HERE).replace(os.sep, '/'), fp


def versions():
    """part -> {newest: unix time, files, bytes}"""
    out = {}
    for part in PARTS:
        newest = n = size = 0
        for _, fp in _files(part):
            st = os.stat(fp)
            newest = max(newest, int(st.st_mtime)); n += 1; size += st.st_size
        out[part] = {'newest': newest, 'files': n, 'bytes': size}
    return out


def versions_text():
    """one line per part: part|newest|files|bytes  (easy for the panel to read)"""
    return '\n'.join(f'{k}|{v["newest"]}|{v["files"]}|{v["bytes"]}' for k, v in versions().items())


def read_package(data):
    if not data.startswith(b'RZUP1\n'):
        raise ValueError('not an update package')
    o, out = 6, []
    while o < len(data):
        (pl,) = struct.unpack_from('<I', data, o); o += 4
        rel = data[o:o + pl].decode('utf-8').replace('\\', '/'); o += pl
        (sz,) = struct.unpack_from('<Q', data, o); o += 8
        if o + sz > len(data):
            raise ValueError('the package is cut short')
        if rel.startswith('/') or ':' in rel or '..' in rel.split('/') or not part_of(rel):
            raise ValueError(f'not allowed in an update: {rel}')
        out.append((rel, data[o:o + sz])); o += sz
    return out


def apply(data):
    """-> message. Keeps the replaced files in update_backup_<time>/."""
    files = read_package(data)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bdir = os.path.join(HERE, f'update_backup_{stamp}')
    new, parts = [], set()
    for rel, blob in files:
        dst = os.path.join(HERE, *rel.split('/'))
        parts.add(part_of(rel))
        if os.path.exists(dst):
            if open(dst, 'rb').read() == blob:
                continue
            b = os.path.join(bdir, *rel.split('/'))
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(dst, b)
        else:
            new.append(rel)
        os.makedirs(os.path.dirname(dst) or HERE, exist_ok=True)
        if rel.lower().endswith('.exe') and os.path.exists(dst):
            # a running exe can't be overwritten but can be renamed: the new one is used from the next start
            old = dst + '.old'
            try:
                if os.path.exists(old):
                    os.remove(old)
            except OSError:
                pass
            os.replace(dst, old)
        tmp = dst + '.part'
        open(tmp, 'wb').write(blob)
        os.replace(tmp, dst)
    os.makedirs(bdir, exist_ok=True)
    json.dump({'time': stamp, 'new': new, 'parts': sorted(p for p in parts if p)}, open(os.path.join(bdir, 'update.json'), 'w'))
    return f'{len(files)} files ({", ".join(sorted(p for p in parts if p))}); previous version kept in update_backup_{stamp}'


def rollback():
    """Put back the files from the newest update_backup_* and remove the files that update added. -> message"""
    backups = sorted(d for d in os.listdir(HERE) if d.startswith('update_backup_') and os.path.isdir(os.path.join(HERE, d)))
    if not backups:
        raise ValueError('no earlier version to go back to')
    bdir = os.path.join(HERE, backups[-1])
    meta = json.load(open(os.path.join(bdir, 'update.json')))
    n = 0
    for root, _, fs in os.walk(bdir):
        for f in fs:
            if f == 'update.json':
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(src, bdir)
            dst = os.path.join(HERE, rel)
            if dst.lower().endswith('.exe') and os.path.exists(dst):
                try:
                    os.replace(dst, dst + '.old')
                except OSError:
                    pass
            shutil.copy2(src, dst); n += 1
    for rel in meta.get('new', []):
        p = os.path.join(HERE, *rel.split('/'))
        if os.path.exists(p):
            os.remove(p); n += 1
    shutil.move(bdir, bdir.replace('update_backup_', 'update_rolledback_'))
    return f'went back to the version before {meta["time"]} ({n} files)'
