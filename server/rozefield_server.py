"""Rozefield — offline / private server for OverField (client 1.0.9, build 2026-10-24-12-00-58).

Runs three services on this PC:
  * dispatch HTTP   :18881  (/dispatch/*  + /resolve HTTPDNS + /Resources/* hot-update files)
  * HTTPDNS         :80     (optional, same handler — answers /resolve?domain=...)
  * game gate TCP   :11001  (protobuf protocol recovered from the client)

The gate answers login with your saved account (tools/make_save.py), replays a
captured response for every request it has seen before, and for anything new
returns an empty "StatusCode_OK" response of the right type so the client keeps going.

    python rozefield_server.py --save save/save.json
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
        self.save = json.load(open(a.save, encoding='utf-8')) if a.save and os.path.exists(a.save) else None
        self.traffic = open(a.traffic_log, 'a', encoding='utf-8') if a.traffic_log else None


# ---------------------------------------------------------------- HTTP side
class HTTP:
    def __init__(self, cfg):
        self.cfg = cfg

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

    def find_resource(self, path):
        name = os.path.basename(urllib.parse.unquote(path))
        for d in self.cfg.res_dirs:
            for root, _, files in os.walk(d):
                if name in files:
                    return os.path.join(root, name)
        return None

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
        elif p.startswith('/Resources/'):
            f = self.find_resource(p)
            if f:
                out = open(f, 'rb').read(); ctype = 'application/octet-stream'
            else:
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
class Session:
    def __init__(self, cfg, reader, writer):
        self.cfg, self.r, self.w = cfg, reader, writer
        self.seq = 0
        self.save = cfg.save or {}
        self.peer = writer.get_extra_info('peername')

    def send(self, name, msg, packet_id=None, push=False):
        if push:
            self.seq += 1
        body = msg.SerializeToString()
        self.w.write(frame(NAME2ID[name], body, packet_id=packet_id, seq_id=self.seq if push else None))
        if name not in ('PlayerPingRsp',):
            log.info('  -> %s (%d bytes)%s', name, len(body), ' push' if push else '')
        self.trace('S2C', name, msg)

    def trace(self, d, name, msg):
        if self.cfg.traffic:
            self.cfg.traffic.write(json.dumps({'t': time.time(), 'dir': d, 'name': name, 'body': to_dict(msg)},
                                              ensure_ascii=False) + '\n')

    def empty_rsp(self, req_name):
        rsp = req_name[:-3] + 'Rsp'
        if rsp not in NAME2ID:
            return None, None
        m = new(rsp)
        if 'status' in m.DESCRIPTOR.fields_by_name:
            m.status = 1 if m.DESCRIPTOR.fields_by_name['status'].enum_type else 0
            try:
                m.status = m.DESCRIPTOR.fields_by_name['status'].enum_type.values_by_name['StatusCode_OK'].number
            except Exception:
                pass
        return rsp, m

    def replay(self, req_name, req):
        lst = self.save.get('responses', {}).get(req_name)
        if not lst:
            return None
        rd = to_dict(req)
        for e in reversed(lst):
            if e['req'] == rd:
                return e
        return lst[-1]

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
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        log.info('gate connection closed %s', self.peer)

    def handle(self, h, body):
        try:
            name, req = decode(h.msg_id, body)
        except Exception as e:
            log.warning('bad body for msg %s: %s', h.msg_id, e); return
        if not name:
            log.warning('unknown msg id %s (%d bytes)', h.msg_id, len(body)); return
        self.trace('C2S', name, req)
        pid = h.packet_id or None
        if name == 'PlayerSceneRecordReq':
            return  # position upload, server never answers
        if name not in ('PlayerPingReq',):
            log.info('<- %s %s', name, json.dumps(to_dict(req), ensure_ascii=False)[:160])
        fn = getattr(self, 'on_' + name, None)
        if fn:
            return fn(req, pid)
        e = self.replay(name, req)
        if e:
            self.send(e['rsp_name'], from_dict(e['rsp_name'], e['rsp']), pid)
            for n, b in e.get('followups', []):
                self.send(n, from_dict(n, b), push=True)
            return
        rsp, m = self.empty_rsp(name)
        if rsp:
            log.info('  (no saved answer for %s, sending empty OK)', name)
            self.send(rsp, m, pid)

    # --- login flow
    def on_VerifyLoginTokenReq(self, req, pid):
        acc = self.save.get('account', {})
        self.send('VerifyLoginTokenRsp', new('VerifyLoginTokenRsp', status='StatusCode_OK',
                  user_id=acc.get('user_id', 1), account_type=req.account_type, sdkUid=req.sdkUid,
                  is_server_open=True, time_left=4294967295, device_uuid=req.device_uuid), pid)

    def on_PlayerLoginReq(self, req, pid):
        d = copy.deepcopy(self.save.get('login_rsp') or {'status': 'StatusCode_OK', 'player_name': 'Rozefield',
                                                          'scene_id': 9999, 'channel_id': 1})
        d['server_time_ms'] = str(now_ms())
        d['region_name'] = 'rozefield_local'
        self.send('PlayerLoginRsp', from_dict('PlayerLoginRsp', d), pid)

    def on_PlayerMainDataReq(self, req, pid):
        md = self.save.get('main_data')
        if md is None:
            _, m = self.empty_rsp('PlayerMainDataReq')
        else:
            m = from_dict('PlayerMainDataRsp', md)
        self.send('PlayerMainDataRsp', m, pid)
        for n, b in self.save.get('login_notices', []):
            self.send(n, from_dict(n, b), push=True)

    def on_PlayerPingReq(self, req, pid):
        self.send('PlayerPingRsp', new('PlayerPingRsp', status='StatusCode_OK',
                  client_time_ms=str(req.client_time_ms), server_time_ms=str(now_ms())), pid)


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--save', default=os.path.join(HERE, 'save', 'save.json'))
    ap.add_argument('--public-ip', default='127.0.0.1', help='IP the client should connect to')
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--http-port', type=int, default=18881)
    ap.add_argument('--dns-port', type=int, default=80, help='HTTPDNS port (0 = off)')
    ap.add_argument('--gate-port', type=int, default=11001)
    ap.add_argument('--client-version', default='2026-10-24-12-00-58')
    ap.add_argument('--res-version', default='2026-11-23-15-53-19')
    ap.add_argument('--res-dir', action='append', help='folder(s) holding PackageManifest_* files to serve')
    ap.add_argument('--traffic-log', default=os.path.join(HERE, 'traffic.jsonl'))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(HERE, 'server.log'), encoding='utf-8')])
    cfg = Config(a)
    if not cfg.save:
        log.warning('no save file at %s — logging in with an empty account', a.save)
    http = HTTP(cfg)
    servers = [await asyncio.start_server(http.handle, a.bind, a.http_port),
               await asyncio.start_server(lambda r, w: Session(cfg, r, w).run(), a.bind, a.gate_port)]
    if a.dns_port:
        try:
            servers.append(await asyncio.start_server(http.handle, a.bind, a.dns_port))
        except OSError as e:
            log.warning('HTTPDNS port %s not available (%s) — fine if Config.txt points at this PC', a.dns_port, e)
    log.info('Rozefield up: dispatch http://%s:%s  gate %s:%s', a.public_ip, a.http_port, a.public_ip, a.gate_port)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
