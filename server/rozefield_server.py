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
from game import traffic   # noqa: E402  (counters for the panel's Traffic card)
HERE = os.path.dirname(os.path.abspath(__file__))


START = time.time()


def restart_self():
    """Start the server again in place (used by the panel's Restart from another device)."""
    logging.getLogger('rozefield').info('restarting...')
    logging.shutdown()
    os.execv(sys.executable, [sys.executable] + sys.argv)


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
            self.patch_files = {k: os.path.normpath(os.path.join(HERE, v.replace('\\', os.sep)))   # relative to the server folder
                                for k, v in json.load(open(os.path.join(HERE, 'patch', 'files.json'), encoding='utf-8')).items()}
            cfg.res_version = self.patch['version']
            log.info('resource patch %s active (%d files)', self.patch['version'], len(self.patch_files))

    def ip_for(self, writer):
        """Address the client should use: --public-ip if given, else the address this client reached us on
        (so players on this PC, the LAN and the internet all get a working address at the same time)."""
        if self.cfg.host_ip not in ('', 'auto'):
            return self.cfg.host_ip
        try:
            ip = (writer.get_extra_info('sockname') or ('127.0.0.1',))[0].replace('::ffff:', '')
            peer = (writer.get_extra_info('peername') or ('127.0.0.1',))[0].replace('::ffff:', '')
        except Exception:
            ip = peer = '127.0.0.1'
        if ip in ('0.0.0.0', '::', '::1'):
            return '127.0.0.1'
        # behind a router: a player from the internet reached our home address through port forwarding, so the
        # address we see is the home one; give them the internet address (or the fixed server name's) instead
        import ipaddress
        try:
            if ipaddress.ip_address(ip).is_private and not ipaddress.ip_address(peer).is_private:
                from game import netsvc
                return netsvc.STATUS.get('public_ip') or ip
        except ValueError:
            pass
        return ip

    def gm_config(self, ip=None):
        c = self.cfg
        ip = ip or (c.host_ip if c.host_ip not in ('', 'auto') else '127.0.0.1')
        base = f'http://{ip}:{c.http_port}/Resources'
        return {"status": True, "message": "success", "hotOssUrl": base,
                "currentVersion": f"{c.client_version}_{c.res_version}", "server": "rozefield_local",
                "ssAppId": "", "ssServerUrl": f"http://{ip}:{c.http_port}/ta",
                "open_gm": False, "open_error_log": False, "open_netConnecting_log": False,
                "ipAddress": "127.0.0.1", "payUrl": f"http://{ip}:{c.http_port}/pay",
                "isTestServer": False, "error_log_level": 2, "server_id": "31000", "open_cs": False,
                "serverTime": 0}

    def region_info(self, ip=None):
        c = self.cfg
        ip = ip or (c.host_ip if c.host_ip not in ('', 'auto') else '127.0.0.1')
        return {"status": True, "message": "success", "gate_tcp_ip": ip, "gate_tcp_port": c.gate_port,
                "is_server_open": True, "text": "", "client_log_tcp_ip": ip, "client_log_tcp_port": 21001,
                "currentVersion": f"{c.client_version}_{c.res_version}",
                "photo_share_cdn_url": f"http://{ip}:{c.http_port}/photo"}

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
        bf = os.path.join(HERE, 'save', 'accounts', f"{reg.get('by_uid', {}).get(uid)}.json")
        if os.path.exists(bf) and json.load(open(bf, encoding='utf-8')).get('banned'):
            return 'ERR|This account is banned on this server.'
        key = str(secrets.randbelow(10 ** 18)).zfill(18)
        if self.game:
            self.game.login_keys[uid] = (key, time.time() + 600)
            self.game.save_login_keys()
        return f'OK|{uid}|{name}|{key}'

    def import_backup(self, data, name=None, by='player'):
        from tools.import_player import import_bytes, ImportFailed
        from game import hostdata
        os.makedirs(os.path.join(HERE, 'save', 'imports'), exist_ok=True)
        open(os.path.join(HERE, 'save', 'imports', time.strftime('%Y%m%d_%H%M%S') + '.rzsave'), 'wb').write(data)
        if data[:40].lstrip().startswith(b'{') and b'rzaccount/' in data[:200]:   # an account moved from another server
            try:
                if not name:
                    return 'ERR|choose a log-in name for this account'
                pid, uid, nm = hostdata.import_account(data, name)
            except ImportFailed as e:
                hostdata.log_import({'name': name, 'pid': '', 'kind': 'rozefield account', 'status': 'failed', 'detail': str(e), 'by': by})
                return f'ERR|{e}'
            hostdata.log_import({'name': nm, 'pid': pid, 'kind': 'rozefield account', 'status': 'ok', 'detail': f'log-in name {name}', 'by': by})
            log.info('imported Rozefield account "%s" as %s', nm, uid)
            return f'OK|{uid}|{nm}'
        try:
            from tools.import_player import read_rzsave_bytes
            try:
                meta, msgs = read_rzsave_bytes(data)
            except Exception:
                return 'ERR|this is not a Rozefield backup file (.rzsave)'
            md = next((m['body'] for m in msgs if m['name'] == 'PlayerMainDataRsp'), {}) or {}
            uid = 'rz_' + (name or md.get('player_name') or meta.get('player_name') or '').lower()
            if self.game and any(s.p and s.p.s.get('uid') == uid for s in self.game.sessions.values()):
                return 'ERR|that account is online right now - log out first'
            before = sorted(f for f in os.listdir(os.path.join(HERE, 'save', 'accounts')) if '.before_import_' in f) \
                if os.path.isdir(os.path.join(HERE, 'save', 'accounts')) else []
            path, uid, name = import_bytes(data, name)
            pid = os.path.splitext(os.path.basename(path))[0]
            new_before = [f for f in os.listdir(os.path.dirname(path)) if f.startswith(pid + '.json.before_import_') and f not in before]
            hostdata.log_import({'name': name, 'pid': pid, 'kind': 'official backup', 'status': 'ok', 'by': by,
                                 'detail': 'replaced an earlier import' if new_before else 'new account',
                                 'before': os.path.join(os.path.dirname(path), sorted(new_before)[-1]) if new_before else ''})
        except ImportFailed as e:
            log.warning('import failed: %s', e)
            hostdata.log_import({'name': name or '', 'pid': '', 'kind': 'official backup', 'status': 'failed', 'detail': str(e), 'by': by})
            return f'ERR|{e}'
        except Exception as e:
            log.exception('import error')
            return f'ERR|server error: {e}'
        log.info('imported backup "%s" as %s', name, uid)
        return f'OK|{uid}|{name}'

    def pid_of(self, uid):
        try:
            reg = json.load(open(os.path.join(HERE, 'save', 'accounts', '_registry.json'), encoding='utf-8'))
            return reg['by_uid'].get(uid)
        except Exception:
            return None

    def info(self):
        from game import hostcfg, netsvc
        s = hostcfg.load()
        acc = 0
        try:
            acc = len(json.load(open(os.path.join(HERE, 'save', 'accounts', '_registry.json'), encoding='utf-8'))['by_uid'])
        except Exception:
            pass
        return {'format': 'rozefield-info/1', 'name': s.get('display_name', 'Rozefield'), 'server_name': s.get('server_name', ''),
                'online': len(self.game.sessions) if self.game else 0, 'accounts': acc,
                'version': (self.patch or {}).get('version', self.cfg.res_version), 'lan_ip': netsvc.STATUS.get('lan_ip', ''),
                'http_port': self.cfg.http_port, 'gate_port': self.cfg.gate_port,
                'invite_code': netsvc.invite_code(netsvc.STATUS.get('public_ip', '')) if netsvc.STATUS.get('public_ip') else '',
                'lan_code': netsvc.invite_code(netsvc.STATUS.get('lan_ip', '')) if netsvc.STATUS.get('lan_ip') else ''}

    def download_page(self):
        import html
        from game import hostcfg, hostdata
        s = hostcfg.load()
        name = html.escape(s.get('display_name') or 'Rozefield')
        here = os.path.exists(os.path.join(hostdata.DOWNLOADS, 'Rozefield.zip'))
        size = f' ({os.path.getsize(os.path.join(hostdata.DOWNLOADS, "Rozefield.zip")) >> 20} MB)' if here else ''
        btns = []
        if s.get('download_link'):
            btns.append(f'<a class="b" href="{html.escape(s["download_link"])}">Download Rozefield</a>')
        if here:
            btns.append(f'<a class="{"s" if btns else "b"}" href="/download/Rozefield.zip">'
                        f'{"Download from this server" if btns else "Download Rozefield"}{size}</a>')
        if not btns:
            btns.append('<p class="m">The game package isn\'t ready yet. Ask the server owner.</p>')
        from game import netsvc
        addr = s.get('server_name') or netsvc.invite_code(netsvc.STATUS.get('public_ip', '')) if (s.get('server_name') or netsvc.STATUS.get('public_ip')) else ''
        server_line = f'<p>Server: <b>{html.escape(addr)}</b> (already set in the download)</p>' if addr else ''
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><style>body{{margin:0;background:#F4F6F8;color:#2A2C36;font-family:"Segoe UI",system-ui,sans-serif}}
main{{max-width:560px;margin:8vh auto;padding:28px;background:#fff;border:1px solid #D6DAE2;border-radius:14px}}
h1{{font-family:Bahnschrift,"Segoe UI",sans-serif;font-weight:600;margin:0 0 6px}}.m{{color:#7A7E8E}}
a.b,a.s{{display:block;text-align:center;text-decoration:none;border-radius:22px;padding:12px;margin:12px 0;font-size:17px}}
a.b{{background:#13B5C5;color:#fff}}a.s{{border:1px solid #D6DAE2;color:#2A2C36}}ol{{line-height:1.8}}</style></head>
<body><main><h1>{name}</h1><p class="m">Private OverField server</p>{''.join(btns)}
{server_line}<ol><li>Unzip Rozefield.zip anywhere.</li><li>Open the Overfield folder and start <b>launcher.exe</b>.</li>
<li>In the login window: Create account (or Bring my account with your official backup file), then Enter game.</li></ol>
<p class="m">Saving your official account before 8 Feb 2027? Use Rozefield Backup.</p></main></body></html>'''.encode('utf-8')

    async def host_admin(self, u, method, body, local):
        """Hosting controls for the panel (this PC or another device). -> (bytes, code, content type)"""
        from game import hostcfg, hostdata, netsvc
        loop = asyncio.get_running_loop()
        txt = 'text/plain; charset=utf-8'
        p = u.path[len('/admin/host/'):]
        q = urllib.parse.parse_qs(u.query)
        if p == 'status':
            i = self.info()
            st = dict(i, uptime=int(time.time() - START), name_status=netsvc.STATUS['name'], router=netsvc.STATUS['router'],
                      public_ip=netsvc.STATUS['public_ip'], package=hostdata.package_status(),
                      settings=hostcfg.public_view(), local=local)
            return json.dumps(st, ensure_ascii=False).encode('utf-8'), 200, 'application/json'
        if p == 'settings' and method == 'POST':
            try:
                hostcfg.update(json.loads(body.decode('utf-8')))
            except Exception as e:
                return f'ERR|{e}'.encode(), 200, txt
            loop.run_in_executor(None, netsvc.update_name)
            return b'OK|saved', 200, txt
        if p == 'password' and method == 'POST':
            if not local:
                return b'ERR|the admin password can only be set on the server device itself', 200, txt
            try:
                hostcfg.set_admin_password(body.decode('utf-8').strip('\r\n'))
            except ValueError as e:
                return f'ERR|{e}'.encode(), 200, txt
            return b'OK|admin password set', 200, txt
        if p == 'name' and method == 'POST':
            r = await loop.run_in_executor(None, netsvc.update_name)
            return f'OK|{r}'.encode('utf-8'), 200, txt
        if p == 'router' and method == 'POST':
            r = await loop.run_in_executor(None, netsvc.open_ports, [80, self.cfg.http_port, self.cfg.gate_port])
            netsvc.STATUS['router'] = r
            return f'OK|{r}'.encode('utf-8'), 200, txt
        if p == 'servers.json':
            return netsvc.servers_json().encode('utf-8'), 200, 'application/json'
        if p == 'imports':
            return hostdata.imports_text().encode('utf-8'), 200, txt
        if p == 'traffic':
            return traffic.text().encode('utf-8'), 200, txt
        if p == 'undo_import' and method == 'POST':
            r = hostdata.undo_import(int(body.decode() or 0), lambda pid: bool(self.game and self.game.is_online(pid)))
            return r.encode('utf-8'), 200, txt
        if p == 'export':
            data = await loop.run_in_executor(None, hostdata.export_server)
            return data, 200, 'application/zip'
        if p == 'import' and method == 'POST':
            return (await loop.run_in_executor(None, hostdata.stage_import, body)).encode('utf-8'), 200, txt
        if p == 'package' and method == 'POST':
            s = hostcfg.load()
            addr = s.get('server_name') or netsvc.STATUS.get('public_ip') or netsvc.STATUS.get('lan_ip') or '127.0.0.1'
            return hostdata.build_package({'name': s.get('display_name', 'Rozefield'), 'address': addr}).encode('utf-8'), 200, txt
        if p == 'package':
            return hostdata.package_status().encode('utf-8'), 200, txt
        if p == 'restart' and method == 'POST':
            loop.call_later(1.0, restart_self)
            return b'OK|restarting', 200, txt
        return b'not found', 404, txt

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
                traffic.record('dl', len(chunk))
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
        if u.path.startswith('/admin/'):   # owner control panel: this PC + token only, never logged
            from game import admin
            from game import hostcfg
            peer = (writer.get_extra_info('peername') or ('',))[0]
            local = peer in ('127.0.0.1', '::1') and hdr.get('x-admin-token') == getattr(self, 'admin_token', None)
            ctype = 'text/plain; charset=utf-8'
            if u.path == '/admin/salt':   # public: lets the panel on another device derive its signing key
                out, code = hostcfg.salt_info().encode(), 200
            elif not (local or hostcfg.check_signed(method, path, body, hdr)):
                out, code = b'forbidden', 403
            elif u.path.startswith('/admin/host/'):
                out, code, ctype = await self.host_admin(u, method, body, local)
            elif u.path == '/admin/players':
                out, code = admin.players(self.game).encode('utf-8'), 200
            elif u.path == '/admin/log':
                n, lines = admin.RING.since(int((urllib.parse.parse_qs(u.query).get('since') or ['0'])[0]))
                out, code = (f'{n}\n' + '\n'.join(lines)).encode('utf-8'), 200
            elif u.path == '/admin/do' and method == 'POST':
                out, code = admin.do(self.game, body).encode('utf-8'), 200
            else:
                out, code = b'not found', 404
            writer.write(f'HTTP/1.1 {code} OK\r\nContent-Type: {ctype}\r\nContent-Length: {len(out)}\r\nConnection: close\r\n\r\n'.encode() + out)
            await writer.drain(); writer.close(); return
        shown = b'(hidden)' if u.path in ('/rozefield/login', '/rozefield/register', '/rozefield/import', '/rozefield/export_account', '/admin/host/password') else body[:200]
        log.info('HTTP %s %s host=%s body=%s', method, u.path, hdr.get('host'), shown)
        ctype, out, code = 'application/json', b'', 200
        p = u.path
        if p.endswith('/resolve'):
            q = urllib.parse.parse_qs(u.query)
            out = json.dumps({"host": q.get('domain', [''])[0], "ttl": 600, "ips": [self.ip_for(writer)],
                              "cip": "127.0.0.1", "cl": [3]}).encode()
        elif p == '/dispatch/get_login_url_list':
            out = b''
        elif p == '/dispatch/client_hot_update':
            out = json.dumps(self.gm_config(self.ip_for(writer)), separators=(',', ':')).encode()
        elif p == '/dispatch/region_info':
            out = json.dumps(self.region_info(self.ip_for(writer)), separators=(',', ':')).encode()
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
        elif p == '/rozefield/import' and method == 'POST':  # login window "Import backup": body = .rzsave / .rzaccount
            nm = (urllib.parse.parse_qs(u.query).get('name') or [None])[0]   # the control panel can choose the log-in name
            by = 'host' if hdr.get('x-admin-token') == getattr(self, 'admin_token', None) else 'player'
            out = (await asyncio.get_running_loop().run_in_executor(None, self.import_backup, body, nm, by)).encode('utf-8')
            ctype = 'text/plain; charset=utf-8'
        elif p == '/rozefield/info':   # launcher: what this server is
            out = json.dumps(self.info()).encode('utf-8')
        elif p == '/rozefield/export_account' and method == 'POST':   # "name\npassword" -> the player's own .rzaccount
            r = self.account_login(body, False)
            if r.startswith('OK|'):
                from game import hostdata
                pid = self.pid_of(r.split('|')[1])
                if pid and self.game and self.game.is_online(pid):
                    out, ctype = b'ERR|log out of the game first', 'text/plain; charset=utf-8'
                elif pid and os.path.exists(os.path.join(HERE, 'save', 'accounts', f'{pid}.json')):
                    out, ctype = hostdata.export_account(pid), 'application/json'
                else:
                    out, ctype = b'ERR|this account has not been played yet', 'text/plain; charset=utf-8'
            else:
                out, ctype = r.encode('utf-8'), 'text/plain; charset=utf-8'
        elif p in ('/', '/download', '/download/'):
            out, ctype = self.download_page(), 'text/html; charset=utf-8'
        elif p == '/download/Rozefield.zip':
            from game import hostdata
            f = os.path.join(hostdata.DOWNLOADS, 'Rozefield.zip')
            if os.path.exists(f):
                return await self.send_file(writer, f, hdr.get('range'))
            code, out = 404, b'no game package on this server yet'
        elif p.startswith('/photo/'):   # photo wall pictures: <cdn>/<code> and <cdn>/thumb/<code> (game builds both)
            import base64, re
            m = re.fullmatch(r'/photo/(?:thumb/)?(\d+)(?:\.\w+)?', p)
            f = os.path.join(HERE, 'save', 'photos', f'{m.group(1)}.b64') if m else ''
            if f and os.path.exists(f):
                out = base64.b64decode(open(f).read() or '')
                ctype = 'image/png' if out[:4] == b'\x89PNG' else 'image/jpeg'
            else:
                code = 404
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
        # uid -> (key from the login window, expiry). 10 minutes to log in with it; once used it stays valid for a day
        # so the game can reconnect by itself (e.g. after the server restarts). Kept on disk across restarts.
        self.login_keys = {}
        self.keys_path = os.path.join(HERE, 'save', 'login_keys.json')
        try:
            self.login_keys = {k: tuple(v) for k, v in json.load(open(self.keys_path, encoding='utf-8')).items()
                               if v[1] > time.time()}
        except Exception:
            pass
        self.templates = {}
        tp = os.path.join(HERE, 'data', 'scene_templates.json')
        if os.path.exists(tp):
            self.templates = json.load(open(tp, encoding='utf-8'))

    def save_login_keys(self):
        try:
            json.dump(self.login_keys, open(self.keys_path, 'w', encoding='utf-8'))
        except Exception:
            log.exception('saving login keys')

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
        if sess.p:   # players met nearby this session show in the friend list until the game closes
            for o in others:
                getattr(sess, 'nearby', set()).add(o.p.s['player_id']); getattr(o, 'nearby', set()).add(sess.p.s['player_id'])
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
        if parts[0] in ('resetpw', 'resetpass', 'password'):   # owner: resetpw <name> <new password>  |  resetpw <name> clear
            a = (parts[1] if len(parts) > 1 else '').rsplit(None, 1)
            if len(a) < 2:
                print('usage: resetpw <account or character name> <new password>   (or "clear")'); return
            from tools.reset_password import main as _reset
            _reset([a[0], '--clear' if a[1].lower() == 'clear' else a[1]]); return
        if len(parts) < 2 or not parts[1].startswith('/'):
            print('usage: <player name> /command ...   (e.g.  roze /all outfits)   |  list   |  resetpw <name> <new password>'); return
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
        self.nearby = set()
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
        fr = frame(NAME2ID[name], m.SerializeToString(), packet_id=packet_id, seq_id=self.seq if push else None)
        self.w.write(fr)
        traffic.record('down', len(fr), self.p.s['name'] if self.p else None, 1)
        if name != 'PlayerPingRsp':
            log.info('%s  -> %s%s', self.tag(), name, ' push' if push else '')
        if self.cfg.traffic:
            self.cfg.traffic.write(json.dumps({'t': time.time(), 'dir': 'S2C', 'name': name, 'body': d}, ensure_ascii=False) + '\n')

    def tag(self):
        """[Name] prefix on this player's log lines (the panel's Player filter uses it)"""
        return f'[{self.p.s["name"]}] ' if self.p else ''

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
                n = 0
                for h, body in unframe(buf):
                    self.handle(h, body)
                    n += 1
                traffic.record('up', len(data), self.p.s['name'] if self.p else None, n)
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
            log.info('%s<- %s %s', self.tag(), name, json.dumps(rd, ensure_ascii=False)[:160])
        if name == 'VerifyLoginTokenReq':
            uid, tok = rd.get('sdkUid', ''), rd.get('login_token', '')
            if has_password(uid):   # accounts with a password need the one-time key from the login window
                want = self.server.login_keys.get(uid)
                if not want or split_token(tok)[1] != want[0] or want[1] < time.time():
                    log.warning('login refused for %s (no valid key)', uid)
                    self._send('VerifyLoginTokenRsp', {'status': 'StatusCode_FAIL'}, h.packet_id)
                    return
                self.server.login_keys[uid] = (want[0], max(want[1], time.time() + 86400))   # reconnects for a day
                self.server.save_login_keys()
            from game.player import _registry
            bpid = _registry()['by_uid'].get(uid)
            bf = os.path.join(HERE, 'save', 'accounts', f'{bpid}.json')
            if bpid and os.path.exists(bf) and json.load(open(bf, encoding='utf-8')).get('banned'):
                log.warning('login refused for %s (banned)', uid)
                self._send('VerifyLoginTokenRsp', {'status': 'StatusCode_FAIL'}, h.packet_id)
                return
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
    ap.add_argument('--public-ip', default='auto',
                    help='address clients are told to use; auto = the address each client reached this server on')
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--http-port', type=int, default=18881)
    ap.add_argument('--dns-port', type=int, default=80, help='HTTPDNS port (0 = off)')
    ap.add_argument('--gate-port', type=int, default=11001)
    ap.add_argument('--client-version', default='2026-10-24-12-00-58')
    ap.add_argument('--res-version', default='2026-11-23-15-53-19')
    ap.add_argument('--res-dir', action='append', help='folder(s) holding PackageManifest_* files to serve')
    ap.add_argument('--all-banners', action='store_true', help='show recruit banners whose dates have passed')
    ap.add_argument('--traffic-log', default=os.path.join(HERE, 'traffic.jsonl'))
    ap.add_argument('--set-admin-password', metavar='PASSWORD', help='set the password the control panel uses from another device, then exit')
    a = ap.parse_args()
    if a.set_admin_password:
        from game import hostcfg
        hostcfg.set_admin_password(a.set_admin_password)
        print('admin password set')
        return
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(HERE, 'server.log'), encoding='utf-8')])
    from game import admin
    admin.RING.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%H:%M:%S'))
    logging.getLogger().addHandler(admin.RING)
    from game import hostdata
    hostdata.apply_incoming(log.info)   # a server export imported from the panel switches in here
    cfg = Config(a)
    http = HTTP(cfg)
    game = Server(cfg, a)
    http.game = game
    http.admin_token = admin.token()   # for Rozefield Server.exe (control panel)
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
    from game.player import migrate_local_ids
    migrate_local_ids(log.info)   # Rozefield-made accounts never sit on an official player id
    from game import netsvc
    netsvc.start([80, a.http_port, a.gate_port] if a.dns_port else [a.http_port, a.gate_port], http.info)
    log.info('Rozefield up: dispatch port %s, gate port %s, address %s', a.http_port, a.gate_port, a.public_ip)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
