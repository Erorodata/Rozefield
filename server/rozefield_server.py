"""Rozefield — offline / private server for OverField (client 1.0.9, build 2026-10-24-12-00-58).

Runs three services on this PC:
  * dispatch HTTP   :18881  (/dispatch/*  + /resolve HTTPDNS + /Resources/* hot-update files)
  * HTTPDNS         :80     (optional, same handler — answers /resolve?domain=...)
  * game gate TCP   :11001  (protobuf protocol recovered from the client)

Every login name gets its own account (save/accounts/<player id>.json). New accounts start as a
fresh player built from the game's own data tables (data/, extracted from the client).
Game rules live in game/handlers.py; requests with no handler get an empty StatusCode_OK reply.

    python rozefield_server.py
"""
import argparse, asyncio, copy, gzip, json, logging, os, sys, time, urllib.parse
from ofproto import ID2NAME, NAME2ID, decode, frame, from_dict, new, to_dict, unframe, msg_class

log = logging.getLogger('rozefield')
HERE = os.path.dirname(os.path.abspath(__file__))


def now_ms():
    return int(time.time() * 1000)


class Config:
    def __init__(self, a):
        self.host_ip = a.public_ip
        self.http_port = a.http_port
        self.gate_port = a.gate_port
        self.client_version = a.client_version
        self.res_version = a.res_version
        self.res_dirs = a.res_dir or []
        self.traffic = open(a.traffic_log, 'a', encoding='utf-8') if a.traffic_log else None


# ---------------------------------------------------------------- HTTP side
class HTTP:
    def __init__(self, cfg):
        self.cfg = cfg
        self.patch_files, self.patch = {}, None
        self.game = None
        pj = os.path.join(HERE, 'patch', 'patch.json')
        if os.path.exists(pj):
            self.patch = json.load(open(pj))
            self.patch_files = json.load(open(os.path.join(HERE, 'patch', 'files.json'), encoding='utf-8'))
            cfg.res_version = self.patch['version']
            log.info('resource patch %s active (%d files)', self.patch['version'], len(self.patch_files))

    def gm_config(self):
        c = self.cfg
        base = f'http://{c.host_ip}:{c.http_port}/Resources'
        return {"status": True, "message": "success", "hotOssUrl": base,
                "currentVersion": f"{c.client_version}_{c.res_version}", "server": "rozefield_local",
                "ssAppId": "", "ssServerUrl": f"http://{c.host_ip}:{c.http_port}/ta",
                "open_gm": False, "open_error_log": False, "open_netConnecting_log": False,
                "ipAddress": "127.0.0.1", "payUrl": f"http://{c.host_ip}:{c.http_port}/pay",
                "isTestServer": False, "error_log_level": 2, "server_id": "31000", "open_cs": False,
                "serverTime": 0}

    def region_info(self):
        c = self.cfg
        return {"status": True, "message": "success", "gate_tcp_ip": c.host_ip, "gate_tcp_port": c.gate_port,
                "is_server_open": True, "text": "", "client_log_tcp_ip": c.host_ip, "client_log_tcp_port": 21001,
                "currentVersion": f"{c.client_version}_{c.res_version}",
                "photo_share_cdn_url": f"http://{c.host_ip}:{c.http_port}/photo"}

    def account_login(self, body, register):
        import re
        import secrets
        try:
            name, pw = body.decode('utf-8').split('\n', 1)
        except Exception:
            return 'ERR|Enter an account name and a password.'
        name, pw = name.strip(), pw.strip('\r\n')
        if not name or len(name) > 24 or not re.fullmatch(r"[\w .'-]+", name, re.UNICODE):
            return 'ERR|Account names use letters, numbers, spaces, - and _ (24 at most).'
        if len(pw) < 4:
            return 'ERR|Passwords need at least 4 characters.'
        reg_path = os.path.join(HERE, 'save', 'accounts', '_registry.json')
        reg = json.load(open(reg_path, encoding='utf-8')) if os.path.exists(reg_path) else {'by_uid': {}}
        uid = None
        for u, pid in reg.get('by_uid', {}).items():   # match the account name or the character name
            f = os.path.join(HERE, 'save', 'accounts', f'{pid}.json')
            nm = ''
            if os.path.exists(f):
                try:
                    nm = json.load(open(f, encoding='utf-8')).get('name', '')
                except Exception:
                    pass
            if u.lower() == 'rz_' + name.lower() or nm.lower() == name.lower():
                uid = u
                break
        if not uid and has_password('rz_' + name.lower()):   # registered but not played yet
            uid = 'rz_' + name.lower()
        if register:
            if uid or has_password('rz_' + name.lower()):
                return 'ERR|That name is already taken. Try another.'
            uid = 'rz_' + name.lower()
            set_password(uid, pw)
        else:
            if not uid:
                return 'ERR|No account with that name. Create one first.'
            if not check_password(uid, pw):
                return 'ERR|Wrong password. If you forgot it, ask the server owner to reset it.'
        key = str(secrets.randbelow(10 ** 18)).zfill(18)
        if self.game:
            self.game.login_keys[uid] = (key, time.time() + 600)
        return f'OK|{uid}|{name}|{key}'

    def import_backup(self, data):
        from tools.import_player import import_bytes, ImportFailed
        os.makedirs(os.path.join(HERE, 'save', 'imports'), exist_ok=True)
        open(os.path.join(HERE, 'save', 'imports', time.strftime('%Y%m%d_%H%M%S') + '.rzsave'), 'wb').write(data)
        try:
            from tools.import_player import read_rzsave_bytes
            try:
                meta, msgs = read_rzsave_bytes(data)
            except Exception:
                return 'ERR|this is not a Rozefield backup file (.rzsave)'
            md = next((m['body'] for m in msgs if m['name'] == 'PlayerMainDataRsp'), {}) or {}
            uid = 'rz_' + (md.get('player_name') or meta.get('player_name') or '').lower()
            if self.game and any(s.p and s.p.s.get('uid') == uid for s in self.game.sessions.values()):
                return 'ERR|that account is online right now - log out first'
            path, uid, name = import_bytes(data)
        except ImportFailed as e:
            log.warning('import failed: %s', e)
            return f'ERR|{e}'
        except Exception as e:
            log.exception('import error')
            return f'ERR|server error: {e}'
        log.info('imported backup "%s" as %s', name, uid)
        return f'OK|{uid}|{name}'

    def find_resource(self, path):
        name = os.path.basename(urllib.parse.unquote(path))
        if name in self.patch_files and os.path.exists(self.patch_files[name]):
            return self.patch_files[name]
        for d in self.cfg.res_dirs:
            for root, _, files in os.walk(d):
                if name in files:
                    return os.path.join(root, name)
        return None

    async def send_file(self, writer, path, rng=None):
        size = os.path.getsize(path)
        start, end = 0, size - 1
        if rng and rng.startswith('bytes='):
            a, _, b = rng[6:].partition('-')
            start = int(a or 0); end = int(b) if b else size - 1
        status = '206 Partial Content' if rng else '200 OK'
        extra = f'Content-Range: bytes {start}-{end}/{size}\r\n' if rng else ''
        writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/octet-stream\r\nContent-Length: {end - start + 1}\r\n'
                     f'{extra}Accept-Ranges: bytes\r\nConnection: close\r\n\r\n'.encode())
        log.info('  serving %s (%d bytes)', os.path.basename(path), end - start + 1)
        with open(path, 'rb') as f:
            f.seek(start); left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                writer.write(chunk); left -= len(chunk)
                await writer.drain()
        writer.close()

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b'\r\n\r\n')
        except Exception:
            writer.close(); return
        lines = head.decode('latin1').split('\r\n')
        method, path, _ = (lines[0].split(' ') + ['', ''])[:3]
        hdr = {k.strip().lower(): v.strip() for k, v in (l.split(':', 1) for l in lines[1:] if ':' in l)}
        body = b''
        if 'content-length' in hdr:
            body = await reader.readexactly(int(hdr['content-length']))
        u = urllib.parse.urlparse(path)
        log.info('HTTP %s %s host=%s body=%s', method, u.path, hdr.get('host'), body[:200])
        ctype, out, code = 'application/json', b'', 200
        p = u.path
        if p.endswith('/resolve'):
            q = urllib.parse.parse_qs(u.query)
            out = json.dumps({"host": q.get('domain', [''])[0], "ttl": 600, "ips": [self.cfg.host_ip],
                              "cip": "127.0.0.1", "cl": [3]}).encode()
        elif p == '/dispatch/get_login_url_list':
            out = b''
        elif p == '/dispatch/client_hot_update':
            out = json.dumps(self.gm_config(), separators=(',', ':')).encode()
        elif p == '/dispatch/region_info':
            out = json.dumps(self.region_info(), separators=(',', ':')).encode()
        elif p == '/dispatch/get_notice_list':
            out = json.dumps({"status": True, "message": "success", "data": []}).encode()
        elif p == '/dispatch/get_notice_url_list':
            out = json.dumps({"data": []}).encode()
        elif p == '/rozefield/accounts':  # used by the login window: uid|name|level per line
            lines = []
            try:
                reg = json.load(open(os.path.join(HERE, 'save', 'accounts', '_registry.json'), encoding='utf-8'))
                for uid, pid in reg['by_uid'].items():
                    f = os.path.join(HERE, 'save', 'accounts', f'{pid}.json')
                    if os.path.exists(f):
                        st = json.load(open(f, encoding='utf-8'))
                        lines.append(f"{uid}|{st['name']}|{st['level']}|{st.get('last_login', 0)}")
            except Exception as e:
                log.warning('account list: %s', e)
            lines.sort(key=lambda x: -int(x.rsplit('|', 1)[1]))
            out = '\n'.join(l.rsplit('|', 1)[0] for l in lines).encode('utf-8'); ctype = 'text/plain; charset=utf-8'
        elif p in ('/rozefield/login', '/rozefield/register') and method == 'POST':
            # login window: body "name\npassword" -> "OK|uid|name|key" or "ERR|reason"
            out = self.account_login(body, p.endswith('register')).encode('utf-8'); ctype = 'text/plain; charset=utf-8'
        elif p == '/rozefield/import' and method == 'POST':  # login window "Import backup": body = .rzsave
            out = (await asyncio.get_running_loop().run_in_executor(None, self.import_backup, body)).encode('utf-8')
            ctype = 'text/plain; charset=utf-8'
        elif p.startswith('/Resources/'):
            f = self.find_resource(p)
            if f:
                return await self.send_file(writer, f, hdr.get('range'))
            code = 404; log.warning('resource not found: %s', p)
        else:
            out = json.dumps({"status": True, "message": "success", "data": None}).encode()
        reason = {200: 'OK', 404: 'Not Found'}[code]
        writer.write(f'HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(out)}\r\n'
                     f'Connection: close\r\n\r\n'.encode() + out)
        try:
            await writer.drain()
        finally:
            writer.close()


# ---------------------------------------------------------------- gate side
from game.data import Data
from game.player import Player
from game import handlers as G
from game import quests as Q


def split_token(tok):
    """The Rozefield SDK stub puts the name in the token as @NNN@NNN@ bytes, then @0@<digit key>@.
    Digits and @ only: the game refuses tokens with other characters."""
    if '@0@' in tok:
        name, key = tok.split('@0@', 1)
        return name + '@', key.strip('@')
    if '#' in tok:   # older login card
        name, key = tok.split('#', 1)
        return name, key.strip('@')
    return tok, ''


def decode_token(tok):
    try:
        return bytes(int(x) for x in split_token(tok)[0].strip('@').split('@') if x).decode('utf-8')
    except Exception:
        return None


# ------------------------------------------------------------------ account passwords
PW_FILE = os.path.join(HERE, 'save', 'accounts', '_passwords.json')


def _pw_load():
    try:
        return json.load(open(PW_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _pw_hash(pw, salt=None):
    import hashlib
    import secrets
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), 200000).hex()


def set_password(uid, pw):
    d = _pw_load()
    salt, h = _pw_hash(pw)
    d[uid] = {'salt': salt, 'hash': h}
    os.makedirs(os.path.dirname(PW_FILE), exist_ok=True)
    json.dump(d, open(PW_FILE, 'w', encoding='utf-8'))


def check_password(uid, pw):
    """True if right. An account made before passwords existed takes the first password used as its own."""
    import hmac
    rec = _pw_load().get(uid)
    if not rec:
        set_password(uid, pw)
        return True
    return hmac.compare_digest(_pw_hash(pw, rec['salt'])[1], rec['hash'])


def has_password(uid):
    return uid in _pw_load()


class Server:
    def __init__(self, cfg, args):
        self.cfg, self.args = cfg, args
        self.d = Data()
        self.sessions = {}            # player_id -> Session
        self.channels = {}            # (scene, channel) -> set(Session)
        self.pending_names = {}
        self.login_keys = {}   # uid -> (one-time key from the login window, expiry)
        self.templates = {}
        tp = os.path.join(HERE, 'data', 'scene_templates.json')
        if os.path.exists(tp):
            self.templates = json.load(open(tp, encoding='utf-8'))

    def scene_template(self, scene_id):
        return self.templates.get(str(scene_id), {})

    # accounts
    def player_by_id(self, pid):
        if pid in self.sessions:
            return self.sessions[pid].p
        path = os.path.join(HERE, 'save', 'accounts', f'{pid}.json')
        if os.path.exists(path):
            return Player(self.d, json.load(open(path, encoding='utf-8')), path)
        return None

    def player_by_label(self, label):
        return self.player_by_id(label)  # labels are player ids on Rozefield

    def all_player_ids(self):
        d = os.path.join(HERE, 'save', 'accounts')
        return [int(f[:-5]) for f in os.listdir(d) if f[:-5].isdigit()] if os.path.isdir(d) else []

    def is_online(self, pid):
        return pid in self.sessions

    def friend_list(self, ctx):
        out = []
        for pid in self.all_player_ids():
            if pid == ctx.p.s['player_id']:
                continue
            o = self.player_by_id(pid)
            if o:
                s = o.s
                out.append({'info': {'playerId': pid, 'nickName': s['name'], 'level': s['level'], 'head': s['head'],
                                     'sign': s['sign'], 'createTime': s['create_time'], 'playerLabel': s['player_label'],
                                     'isOnline': self.is_online(pid), 'account_type': 16666,
                                     'lastLoginTime': str(s.get('last_login', 0) * 1000)}})
        return out

    # channels
    def join_channel(self, sess, scene, channel):
        """Everyone in the same scene channel sees each other (official: ServerSceneSyncDataNotice ENTER / LEAVE)."""
        self.leave_channel(sess)
        sess.chan = (scene, channel)
        others = [o for o in self.channels.get(sess.chan, set()) if o is not sess and o.p]
        self.channels.setdefault(sess.chan, set()).add(sess)
        if not sess.p:
            return
        sp = self._scene_player(sess.p)
        for o in others:
            try:
                o.push('ServerSceneSyncDataNotice', {'status': 'StatusCode_OK', 'data': [
                    {'player_id': sess.p.s['player_id'], 'serverData': [{'action_type': 'SceneActionType_ENTER', 'player': sp}]}]})
            except Exception:
                pass
        if others:
            sess.push('ServerSceneSyncDataNotice', {'status': 'StatusCode_OK', 'data': [
                {'player_id': o.p.s['player_id'], 'serverData': [{'action_type': 'SceneActionType_ENTER', 'player': self._scene_player(o.p)}]}
                for o in others]})

    def leave_channel(self, sess):
        chan = getattr(sess, 'chan', None)
        if chan in self.channels:
            self.channels[chan].discard(sess)
            if sess.p:
                for o in list(self.channels[chan]):
                    try:
                        o.push('ServerSceneSyncDataNotice', {'status': 'StatusCode_OK', 'data': [
                            {'player_id': sess.p.s['player_id'], 'serverData': [{'action_type': 'SceneActionType_LEAVE'}]}]})
                    except Exception:
                        pass
        sess.chan = None

    @staticmethod
    def _scene_player(p):
        from game.handlers import scene_player
        return scene_player(p)

    def broadcast(self, sess, name, body, include_self=True):
        for o in list(self.channels.get(getattr(sess, 'chan', None), {sess})):
            if o is sess and not include_self:
                continue
            try:
                o.push(name, body)
            except Exception:
                pass

    def broadcast_scene_player(self, sess, action='SceneActionType_UPDATE_TEAM'):
        """Outfit / gear / team changes are shown to the other players in the channel."""
        if not getattr(sess, 'p', None):
            return
        sp = self._scene_player(sess.p)
        self.broadcast(sess, 'ServerSceneSyncDataNotice', {'status': 'StatusCode_OK', 'data': [
            {'player_id': sess.p.s['player_id'], 'serverData': [{'action_type': action, 'player': {'team': sp['team']}}]}]}, include_self=False)

    # ---- server console: type GM commands in the server window, e.g.  roze /all outfits
    def console(self, line):
        parts = line.strip().split(None, 1)
        if not parts:
            return
        if parts[0] in ('list', 'who'):
            for pid in self.all_player_ids():
                o = self.player_by_id(pid)
                print(f'  {pid}  {o.s["name"]:<20} lv{o.s["level"]}  {"ONLINE" if pid in self.sessions else ""}')
            return
        if len(parts) < 2 or not parts[1].startswith('/'):
            print('usage: <player name> /command ...   (e.g.  roze /all outfits)   |  list'); return
        name, cmd = parts
        sess = next((x for x in self.sessions.values() if x.p.s['name'].lower() == name.lower()), None)
        if sess is None:
            print(f'{name} is not online (log in first)'); return
        sess.cur = None
        print('  ' + G.gm_command(sess, cmd))
        try:
            sess.w.write(b'')
        except Exception:
            pass


class Session:
    def __init__(self, server, reader, writer):
        self.server, self.cfg, self.r, self.w = server, server.cfg, reader, writer
        self.d = server.d
        self.seq = 0
        self.p = None
        self.chan = None
        self.cur = None
        self.peer = writer.get_extra_info('peername')

    def login(self, uid, name):
        self.p = Player.load_or_create(self.d, uid, name)
        old = self.server.sessions.get(self.p.s['player_id'])
        if old and old is not self:
            self.p = old.p
            old.w.close()
        self.server.sessions[self.p.s['player_id']] = self
        log.info('login uid=%s -> player %s "%s"', uid, self.p.s['player_id'], self.p.s['name'])

    def _send(self, name, d, packet_id=None, push=False):
        m = from_dict(name, d)
        if push:
            self.seq += 1
        self.w.write(frame(NAME2ID[name], m.SerializeToString(), packet_id=packet_id, seq_id=self.seq if push else None))
        if name != 'PlayerPingRsp':
            log.info('  -> %s%s', name, ' push' if push else '')
        if self.cfg.traffic:
            self.cfg.traffic.write(json.dumps({'t': time.time(), 'dir': 'S2C', 'name': name, 'body': d}, ensure_ascii=False) + '\n')

    def reply(self, d):
        name, pid = self.cur
        self._send(name[:-3] + 'Rsp', d, packet_id=pid)
        self.cur = None

    def push(self, name, d):
        self._send(name, d, push=True)

    async def run(self):
        log.info('gate connection from %s', self.peer)
        buf = bytearray()
        try:
            while True:
                data = await self.r.read(65536)
                if not data:
                    break
                buf += data
                for h, body in unframe(buf):
                    self.handle(h, body)
                await self.w.drain()
                if self.p and self.p.dirty:
                    self.p.save()
        except (ConnectionResetError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            self.server.leave_channel(self)
            if self.p:
                self.p.save()
                if self.server.sessions.get(self.p.s['player_id']) is self:
                    del self.server.sessions[self.p.s['player_id']]
        log.info('gate connection closed %s', self.peer)

    def handle(self, h, body):
        try:
            name, req = decode(h.msg_id, body)
        except Exception as e:
            log.warning('bad body for msg %s: %s', h.msg_id, e); return
        if not name:
            log.warning('unknown msg id %s (%d bytes)', h.msg_id, len(body)); return
        rd = to_dict(req)
        if self.cfg.traffic:
            self.cfg.traffic.write(json.dumps({'t': time.time(), 'dir': 'C2S', 'name': name, 'body': rd}, ensure_ascii=False) + '\n')
        if name not in ('PlayerPingReq', 'PlayerSceneRecordReq'):
            log.info('<- %s %s', name, json.dumps(rd, ensure_ascii=False)[:160])
        if name == 'VerifyLoginTokenReq':
            uid, tok = rd.get('sdkUid', ''), rd.get('login_token', '')
            if has_password(uid):   # accounts with a password need the one-time key from the login window
                want = self.server.login_keys.get(uid)
                if not want or split_token(tok)[1] != want[0] or want[1] < time.time():
                    log.warning('login refused for %s (no valid key)', uid)
                    self._send('VerifyLoginTokenRsp', {'status': 'StatusCode_FAIL'}, h.packet_id)
                    return
                self.server.login_keys.pop(uid, None)   # one use only
            nm = decode_token(tok)
            if nm:
                self.server.pending_names[uid] = nm
        elif self.p is None:
            log.warning('request before login: %s', name); return
        self.cur = (name, h.packet_id or None)
        fn = G.H.get(name)
        try:
            if fn:
                fn(self, rd)
        except Exception:
            log.exception('handler %s failed', name)
            if self.cur:
                self.reply({'status': 'StatusCode_FAIL'})
        if self.cur and name.endswith('Req'):
            rsp = name[:-3] + 'Rsp'
            if rsp in NAME2ID and name != 'PlayerSceneRecordReq':
                if not fn:
                    log.info('  (not implemented: %s -> empty OK)', name)
                self.reply({'status': 'StatusCode_OK'} if 'status' in msg_class(rsp).DESCRIPTOR.fields_by_name else {})
        self.cur = None
        if self.p is not None:
            try:
                Q.flush(self)
            except Exception:
                log.exception('quest update failed')


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--save', default=None, help='(unused, accounts live in save/accounts)')
    ap.add_argument('--public-ip', default='127.0.0.1', help='IP the client should connect to')
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--http-port', type=int, default=18881)
    ap.add_argument('--dns-port', type=int, default=80, help='HTTPDNS port (0 = off)')
    ap.add_argument('--gate-port', type=int, default=11001)
    ap.add_argument('--client-version', default='2026-10-24-12-00-58')
    ap.add_argument('--res-version', default='2026-11-23-15-53-19')
    ap.add_argument('--res-dir', action='append', help='folder(s) holding PackageManifest_* files to serve')
    ap.add_argument('--all-banners', action='store_true', help='show recruit banners whose dates have passed')
    ap.add_argument('--traffic-log', default=os.path.join(HERE, 'traffic.jsonl'))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(HERE, 'server.log'), encoding='utf-8')])
    cfg = Config(a)
    http = HTTP(cfg)
    game = Server(cfg, a)
    http.game = game
    servers = [await asyncio.start_server(http.handle, a.bind, a.http_port),
               await asyncio.start_server(lambda r, w: Session(game, r, w).run(), a.bind, a.gate_port)]
    if a.dns_port:
        try:
            servers.append(await asyncio.start_server(http.handle, a.bind, a.dns_port))
        except OSError as e:
            log.warning('HTTPDNS port %s not available (%s) — fine if Config.txt points at this PC', a.dns_port, e)
    loop = asyncio.get_running_loop()

    def read_console():
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            loop.call_soon_threadsafe(game.console, line)
    import threading
    threading.Thread(target=read_console, daemon=True).start()
    log.info('Type GM commands here, e.g.  <name> /all outfits   or  list')
    log.info('Rozefield up: dispatch http://%s:%s  gate %s:%s', a.public_ip, a.http_port, a.public_ip, a.gate_port)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
