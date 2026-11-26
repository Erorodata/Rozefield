"""Server data jobs: the imported-accounts list (with undo), moving the whole server to another device
(export / import), building the player game package, and players moving their own account between servers.
"""
import io
import json
import logging
import os
import shutil
import threading
import time
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE = os.path.join(HERE, 'save')
ACC = os.path.join(SAVE, 'accounts')
IMPORTS = os.path.join(SAVE, 'imports.json')
INCOMING = os.path.join(HERE, 'save_incoming')
DOWNLOADS = os.path.join(HERE, 'downloads')
log = logging.getLogger('rozefield')
_lock = threading.Lock()


# ---------------------------------------------------------------- imported accounts
def _imports():
    try:
        return json.load(open(IMPORTS, encoding='utf-8'))
    except Exception:
        return []


def log_import(entry):
    with _lock:
        lst = _imports()
        entry = dict(entry, id=(max([e.get('id', 0) for e in lst] + [0]) + 1), time=int(time.time()))
        lst.append(entry)
        os.makedirs(SAVE, exist_ok=True)
        json.dump(lst[-500:], open(IMPORTS, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        return entry


def imports_text():
    """One line per import, newest first: id|time|name|pid|kind|status|detail"""
    out = []
    for e in reversed(_imports()):
        out.append('|'.join(str(e.get(k, '')).replace('|', '/') for k in ('id', 'time', 'name', 'pid', 'kind', 'status', 'detail')))
    return '\n'.join(out)


def undo_import(iid, online):
    """Put the account back the way it was before import <iid>: the earlier save if there was one, otherwise the
    account is set aside (save/removed/) and its name freed. Returns a message."""
    from game.player import _registry, _save_registry
    with _lock:
        lst = _imports()
        e = next((x for x in lst if x.get('id') == iid), None)
        if not e or e.get('status') != 'ok':
            return 'ERR|that import is not in the list (or did not go through)'
        if e.get('undone'):
            return 'ERR|already undone'
        pid = int(e['pid'])
        if online(pid):
            return 'ERR|the player is online - kick them first'
        path = os.path.join(ACC, f'{pid}.json')
        before = e.get('before')
        if before and os.path.exists(before):
            shutil.copy(before, path)
            msg = f'restored "{e.get("name")}" to before the import'
        else:
            os.makedirs(os.path.join(SAVE, 'removed'), exist_ok=True)
            if os.path.exists(path):
                shutil.move(path, os.path.join(SAVE, 'removed', f'{pid}_{time.strftime("%Y%m%d_%H%M%S")}.json'))
            reg = _registry()
            reg['by_uid'] = {u: p for u, p in reg['by_uid'].items() if p != pid}
            _save_registry(reg)
            msg = f'removed "{e.get("name")}" (kept in save/removed)'
        e['undone'] = int(time.time())
        json.dump(lst, open(IMPORTS, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    log.info('import %s undone: %s', iid, msg)
    return 'OK|' + msg


# ---------------------------------------------------------------- whole server: export / import
SERVER_PARTS = ('save', 'patch')


def export_server():
    """Zip of everything that makes this server: accounts, chat, photos, settings, the game update. -> bytes"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('rozefield_server_export.json', json.dumps({'format': 'rozefield-server/1', 'time': int(time.time())}))
        for part in SERVER_PARTS:
            base = os.path.join(HERE, part)
            for root, _, files in os.walk(base):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, HERE).replace(os.sep, '/')
                    if rel in ('save/admin_token.txt',) or f.endswith('.tmp'):
                        continue
                    z.write(full, rel)
    return buf.getvalue()


def stage_import(data):
    """Unpack an export next to the server; it replaces save/ and patch/ when the server starts next."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(z.read('rozefield_server_export.json'))
    except Exception:
        return 'ERR|this is not a Rozefield server export'
    if meta.get('format') != 'rozefield-server/1':
        return 'ERR|unknown export format'
    for n in z.namelist():
        if n.startswith('/') or '..' in n.split('/') or not (n.split('/')[0] in SERVER_PARTS or n == 'rozefield_server_export.json'):
            return f'ERR|unexpected file in the export: {n}'
    if os.path.exists(INCOMING):
        shutil.rmtree(INCOMING)
    z.extractall(INCOMING)
    n = sum(1 for x in z.namelist() if x.startswith('save/accounts/') and x.endswith('.json') and not x.endswith('_registry.json'))
    return f'OK|server export ready ({n} accounts). Restart the server to switch to it; the current data is kept as save_before_import.'


def apply_incoming(say=print):
    """At start-up: if a staged export is waiting, swap it in (the old data is kept)."""
    if not os.path.isdir(INCOMING):
        return
    stamp = time.strftime('%Y%m%d_%H%M%S')
    for part in SERVER_PARTS:
        new = os.path.join(INCOMING, part)
        if not os.path.isdir(new):
            continue
        cur = os.path.join(HERE, part)
        if os.path.exists(cur):
            shutil.move(cur, os.path.join(HERE, f'{part}_before_import_{stamp}'))
        shutil.move(new, cur)
    shutil.rmtree(INCOMING, ignore_errors=True)
    say(f'switched to the imported server data (previous data kept as *_before_import_{stamp})')


# ---------------------------------------------------------------- game package (Rozefield.zip)
PACKAGE = {'state': 'idle', 'done': 0, 'total': 0, 'file': '', 'error': ''}
SKIP_EXT = ('.orig', '.rzbackup', '.log', '.tmp')


def game_folder():
    p = os.path.join(HERE, 'game_path.txt')
    if os.path.exists(p):
        g = open(p, encoding='utf-8').read().strip()
        if g:
            return g
    return os.path.normpath(os.path.join(HERE, '..', 'Overfield'))


def _point_package(game, address):
    """Config.txt (RemoteServerIP) and the address lookup in the packaged game, set to the default server."""
    import socket
    import struct
    out = {}
    try:
        ip = socket.gethostbyname(address)
    except OSError:
        ip = address
    cfg = os.path.join(game, 'launcher_Data', 'StreamingAssets', 'Config.txt')
    if os.path.exists(cfg):
        lines, seen = [], set()
        for ln in open(cfg, encoding='utf-8-sig').read().splitlines():
            k = ln.split('=')[0].strip()
            if k == 'UseCustomConfig':
                ln = 'UseCustomConfig = TRUE'
            elif k == 'RemoteServerIP':
                ln = f'RemoteServerIP = {ip}'
            seen.add(k)
            lines.append(ln)
        lines += [x for k, x in (('UseCustomConfig', 'UseCustomConfig = TRUE'), ('RemoteServerIP', f'RemoteServerIP = {ip}')) if k not in seen]
        out['launcher_Data/StreamingAssets/Config.txt'] = ('\r\n'.join(lines) + '\r\n').encode('utf-8')
    meta = os.path.join(game, 'launcher_Data', 'il2cpp_data', 'Metadata', 'global-metadata.dat')
    src = meta + '.orig' if os.path.exists(meta + '.orig') else meta
    target = (ip if len(ip) <= 12 else '127.0.0.1').encode()
    try:
        d = bytearray(open(src, 'rb').read())
        _, _, lo, ls, ldo, _ = struct.unpack_from('<IiIIII', d, 0)
        pos = d.find(b'8.134.240.36', ldo) - ldo
        hit = [lo + i * 8 for i in range(ls // 8) if pos >= 0 and struct.unpack_from('<Ii', d, lo + i * 8) == (12, pos)]
        if len(hit) == 1:
            d[ldo + pos:ldo + pos + len(target)] = target
            struct.pack_into('<I', d, hit[0], len(target))
            out['launcher_Data/il2cpp_data/Metadata/global-metadata.dat'] = bytes(d)
    except Exception:
        log.exception('could not set the address lookup in the package')
    return out


def package_status():
    p = PACKAGE
    return f"{p['state']}|{p['done']}|{p['total']}|{p['file']}|{p['error']}"


def build_package(default_server):
    """Zip the game folder into downloads/Rozefield.zip in the background, with this server set as the default."""
    if PACKAGE['state'] == 'building':
        return 'ERR|a package is already being built'
    game = game_folder()
    if not os.path.exists(os.path.join(game, 'launcher.exe')):
        return f'ERR|no game found at {game} (put the Overfield folder next to the Server folder, or set game_path.txt)'

    def job():
        os.makedirs(DOWNLOADS, exist_ok=True)
        tmp = os.path.join(DOWNLOADS, 'Rozefield.zip.tmp')
        files = []
        for root, dirs, fs in os.walk(game):
            dirs[:] = [d for d in dirs if d not in ('_archive', 'Claude outputs')]
            for f in fs:
                if not f.lower().endswith(SKIP_EXT) and f.lower() not in ('rozefield.exe', 'rozefield_launcher.ini', 'rozefield_sdk.ini', 'rozefield_sdk.log', 'player.log', 'player-prev.log'):
                    files.append(os.path.join(root, f))
        PACKAGE.update(state='building', done=0, total=sum(os.path.getsize(f) for f in files), file='', error='')
        override = _point_package(game, default_server['address'])   # the game in the zip goes to this server
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
                for f in files:
                    rel = os.path.relpath(f, game).replace(os.sep, '/')
                    if rel in override:
                        z.writestr('Overfield/' + rel, override[rel])
                    else:
                        z.write(f, 'Overfield/' + rel)
                    PACKAGE['done'] += os.path.getsize(f)
                z.writestr('Overfield/rozefield_servers.json', json.dumps(
                    {'format': 'rozefield-servers/1', 'default': default_server['address'], 'servers': [default_server]},
                    ensure_ascii=False, indent=1))
            out = os.path.join(DOWNLOADS, 'Rozefield.zip')
            os.replace(tmp, out)
            PACKAGE.update(state='done', file=out)
            log.info('game package ready: %s (%d MB)', out, os.path.getsize(out) >> 20)
        except Exception as e:
            PACKAGE.update(state='failed', error=str(e))
            log.exception('game package failed')
    threading.Thread(target=job, daemon=True).start()
    return 'OK|building the game package in the background'


# ---------------------------------------------------------------- a player's own account between servers
def export_account(pid):
    st = json.load(open(os.path.join(ACC, f'{pid}.json'), encoding='utf-8'))
    for k in ('banned', 'muted', 'last_login', 'admin'):
        st.pop(k, None)
    return json.dumps({'format': 'rzaccount/1', 'exported': int(time.time()), 'state': st}, ensure_ascii=False).encode('utf-8')


def import_account(data, login_name):
    """A .rzaccount from another Rozefield server becomes a new account here. -> (pid, uid, in-game name)"""
    from game.player import _registry, _save_registry, new_local_id, LOCAL_ID_START
    from tools.import_archive import ImportFailed
    try:
        d = json.loads(data.decode('utf-8'))
        st = d['state']
        assert d.get('format') == 'rzaccount/1' and isinstance(st, dict)
    except Exception:
        raise ImportFailed('this is not a Rozefield account file (.rzaccount)')
    uid = 'rz_' + login_name.lower()
    reg = _registry()
    if uid in reg['by_uid']:
        raise ImportFailed(f'the name "{login_name}" is already used on this server - choose another')
    off = st.get('official_player_id')
    for u, p in reg['by_uid'].items():
        f = os.path.join(ACC, f'{p}.json')
        if off and os.path.exists(f) and json.load(open(f, encoding='utf-8')).get('official_player_id') == off:
            raise ImportFailed('this account is already on this server - log in with its name')
    used = set(reg['by_uid'].values())
    pid = off if off and off < LOCAL_ID_START and off not in used else new_local_id(reg)
    st['uid'], st['player_id'], st['player_label'] = uid, pid, pid
    st['scene_id'], st['channel_id'] = 9999, pid
    reg['by_uid'][uid] = pid
    os.makedirs(ACC, exist_ok=True)
    json.dump(st, open(os.path.join(ACC, f'{pid}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    _save_registry(reg)
    return pid, uid, st.get('name', login_name)
