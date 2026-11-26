"""Rozefield player data export ("relay recorder").

Run this while the official OverField server is still online. It sits between YOUR game and the official server,
passes everything through untouched, and records what the server tells your game about your account. When you are
done you get  <name>_<date>.rzsave  which Rozefield can import as your own account later:

    py tools\\import_player.py <file>.rzsave        (on the Rozefield server)

What it changes on your PC while running (all restored when you close it):
  * launcher_Data\\StreamingAssets\\Config.txt  -> UseCustomConfig = TRUE, RemoteServerIP = 127.0.0.1
  * if a Rozefield login window was installed, the original QuickSDK PCSDKUI.exe is put back for the official login

It never sends anything of its own to the official server; it only listens. Your login token is not saved.
"""
import argparse, asyncio, base64, json, os, shutil, sys, time, urllib.request, zipfile
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')   # the server folder (dev tools live in devtools/)
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # devtools package
from ofproto import ID2NAME, decode, to_dict  # noqa: E402

OFFICIAL_DISPATCH = 'dsp-global-of.inutan.com'
DISPATCH_PORT = 18881
DISPATCH_UP = 18881
HTTPDNS = 'http://8.134.240.36/resolve?domain='
GATE_PORT = 11001
NO_RECORD = {'VerifyLoginTokenReq'}  # holds the login token

# what to open in game so the export is complete: (label, request name, how to trigger it in game)
CHECKLIST = [
    ('Account, characters, bag, quests, story', 'PlayerMainDataRsp', 'log in'),
    ('Plaza (garden) layout', 'SceneDataNotice', 'go to your own Garden Plaza'),
    ('Achievements', 'GetAchieveOneGroupRsp', 'Manual > Achievements: open every tab'),
    ('Life skills', 'GetLifeInfoRsp', 'Life (生活): open each life skill'),
    ('Life collection book', 'GetOneTypeLifePictorialBookCountRsp', 'Life: open each collection book'),
    ('Exploration manual', 'ManualListRsp', 'open the Manual'),
    ('Poster album', 'PosterIllustrationListRsp', 'open the Poster album'),
    ('Character achievements', 'GetCharacterAchievementListRsp', 'Characters: open each character\'s badge/achievement page'),
    ('Friends', 'FriendRsp', 'open the Friends list'),
    ('Plaza presets', 'GardenFurnitureSchemeRsp', 'in decorate mode open Preset Decor'),
    ('Mail', 'GetMailsRsp', 'open the Mailbox'),
]


def resolve(host):
    import socket
    try:
        return socket.gethostbyname(host)
    except OSError:
        r = json.load(urllib.request.urlopen(HTTPDNS + host, timeout=10))
        return r['ips'][0]


class Recorder:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.frames = []
        self.http = []
        self.name = None
        self.seen = set()
        self.gate = None  # real (ip, port)
        self.last_save = 0
        self.conns = 0
        self.prev_path = None
        self.on_dispatch = None

    def add(self, direction, head, body, conn=0):
        name = ID2NAME.get(head.msg_id, str(head.msg_id))
        if name in NO_RECORD:
            body = b''
        self.frames.append({'t': time.time(), 'conn': conn, 'dir': direction, 'msg_id': head.msg_id, 'packet_id': head.packet_id,
                            'seq_id': head.seq_id, 'name': name, 'body': base64.b64encode(body).decode()})
        if name == 'PlayerMainDataRsp' and not self.name:
            try:
                self.name = to_dict(decode(head.msg_id, body)[1]).get('player_name')
                print(f'\n  logged in as {self.name}. Keep playing; open the menus below so they get saved too.')
            except Exception:
                pass
        if direction == 'S2C' and name not in self.seen:
            self.seen.add(name)
            for label, rsp, how in CHECKLIST:
                if rsp == name:
                    print(f'  [saved] {label}')
        if time.time() - self.last_save > 30:
            self.save()

    def save(self):
        if not self.frames:
            return None
        self.last_save = time.time()
        safe = ''.join(c for c in (self.name or 'player') if c.isalnum() or c in '-_') or 'player'
        path = os.path.join(self.out_dir, f'{safe}_{time.strftime("%Y%m%d")}.rzsave')
        tmp = path + '.tmp'
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('meta.json', json.dumps({'format': 'rzsave/1', 'player_name': self.name, 'saved': time.time(),
                                                'frames': len(self.frames)}, ensure_ascii=False))
            z.writestr('gate.json', json.dumps(self.frames, ensure_ascii=False))
            z.writestr('dispatch.json', json.dumps(self.http, ensure_ascii=False))
        os.replace(tmp, path)
        if self.prev_path and self.prev_path != path and os.path.exists(self.prev_path):
            os.remove(self.prev_path)
        self.prev_path = path
        return path

    def missing(self):
        return [(l, how) for l, rsp, how in CHECKLIST if rsp not in self.seen]


def split_frames(buf):
    """Complete frames in buf -> [(raw_bytes, head, body)], consuming them."""
    from ofproto import Head
    import cramjam
    out = []
    while len(buf) >= 2:
        hl = int.from_bytes(buf[:2], 'big')
        if len(buf) < 2 + hl:
            break
        h = Head(); h.ParseFromString(bytes(buf[2:2 + hl]))
        if len(buf) < 2 + hl + h.body_len:
            break
        raw = bytes(buf[:2 + hl + h.body_len]); del buf[:2 + hl + h.body_len]
        body = raw[2 + hl:]
        if h.flag == 1:
            try:
                body = bytes(cramjam.snappy.decompress_raw(body))
            except Exception:
                pass
        out.append((raw, h, body))
    return out


async def pump(reader, writer, rec, direction, conn):
    buf = bytearray()
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)  # forwarded unchanged
            await writer.drain()
            buf.extend(data)
            for raw, h, body in split_frames(buf):
                rec.add(direction, h, body, conn)
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def gate_conn(rec, creader, cwriter):
    if not rec.gate:
        cwriter.close(); return
    rec.conns += 1
    sreader, swriter = await asyncio.open_connection(*rec.gate)
    await asyncio.gather(pump(creader, swriter, rec, 'C2S', rec.conns), pump(sreader, cwriter, rec, 'S2C', rec.conns))
    p = rec.save()
    print(f'\n  connection closed - saved {p}')


async def http_conn(rec, upstream_ip, reader, writer):
    try:
        head = await reader.readuntil(b'\r\n\r\n')
        lines = head.decode('latin1').split('\r\n')
        method, path, _ = (lines[0].split(' ') + ['', ''])[:3]
        hdr = {k.strip().lower(): v.strip() for k, v in (l.split(':', 1) for l in lines[1:] if ':' in l)}
        body = await reader.readexactly(int(hdr['content-length'])) if 'content-length' in hdr else b''
        if path.startswith('/resolve'):  # HTTPDNS: answer with ourselves
            out = json.dumps({'host': OFFICIAL_DISPATCH, 'ttl': 600, 'ips': ['127.0.0.1'], 'cip': '127.0.0.1', 'cl': [3]}).encode()
        else:
            req = urllib.request.Request(f'http://{upstream_ip}:{DISPATCH_UP}{path}', data=body or None, method=method,
                                         headers={'Host': f'{OFFICIAL_DISPATCH}:{DISPATCH_PORT}',
                                                  'Content-Type': hdr.get('content-type', 'application/x-www-form-urlencoded')})
            out = await asyncio.get_running_loop().run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=20).read())
            rec.http.append({'path': path.split('?')[0], 'response': out.decode('utf-8', 'replace')})
            if path.startswith('/dispatch/region_info'):
                j = json.loads(out)
                rec.gate = (j['gate_tcp_ip'], j['gate_tcp_port'])
                j['gate_tcp_ip'], j['gate_tcp_port'] = '127.0.0.1', GATE_PORT
                out = json.dumps(j, separators=(',', ':')).encode()
                print(f'  official game server {rec.gate[0]}:{rec.gate[1]} (relayed)')
                if rec.on_dispatch:  # the game has read Config.txt by now: put the original back straight away
                    rec.on_dispatch()
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(out)}\r\n'
                     f'Connection: close\r\n\r\n'.encode() + out)
        await writer.drain()
    except Exception as e:
        print('  dispatch error:', e)
        writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
    finally:
        writer.close()


# ---------------------------------------------------------------- client setup / restore
def patch_client(game):
    sa = os.path.join(game, 'launcher_Data', 'StreamingAssets', 'Config.txt')
    bak = sa + '.rzexport'
    shutil.copy(sa, bak)
    t = open(sa, encoding='utf-8-sig').read()
    import re
    t = re.sub(r'UseCustomConfig\s*=\s*\w+', 'UseCustomConfig = TRUE', t)
    t = re.sub(r'RemoteServerIP\s*=\s*[^\r\n]*', 'RemoteServerIP = 127.0.0.1', t)
    open(sa, 'w', encoding='utf-8').write(t)
    sdk = os.path.join(game, 'launcher_Data', 'Plugins', 'Win', 'PCSDK_release', 'PCSDKUI.exe')
    swapped = False
    if os.path.exists(sdk + '.orig'):  # Rozefield login window installed: use the official login for the export
        shutil.copy(sdk, sdk + '.rozefield'); shutil.copy(sdk + '.orig', sdk); swapped = True
    return sa, bak, sdk, swapped


def restore_client(sa, bak, sdk, swapped=True):
    if os.path.exists(bak):
        shutil.copy(bak, sa); os.remove(bak)
    if os.path.exists(sdk + '.rozefield'):
        try:
            shutil.copy(sdk + '.rozefield', sdk); os.remove(sdk + '.rozefield')
        except OSError:
            print('  (login window still in use; it is restored next time you run this)')


def restore_leftovers(game):
    """Undo a previous run that was closed without Ctrl+C."""
    sa = os.path.join(game, 'launcher_Data', 'StreamingAssets', 'Config.txt')
    restore_client(sa, sa + '.rzexport', os.path.join(game, 'launcher_Data', 'Plugins', 'Win', 'PCSDK_release', 'PCSDKUI.exe'))


async def main_async(a, rec):
    global DISPATCH_UP
    if a.upstream:
        ip, DISPATCH_UP = a.upstream.split(':')[0], int(a.upstream.split(':')[1])
    else:
        ip = await asyncio.get_running_loop().run_in_executor(None, resolve, OFFICIAL_DISPATCH)
    print(f'official dispatch {OFFICIAL_DISPATCH} = {ip}')
    await asyncio.start_server(lambda r, w: http_conn(rec, ip, r, w), '127.0.0.1', DISPATCH_PORT)
    await asyncio.start_server(lambda r, w: gate_conn(rec, r, w), '127.0.0.1', GATE_PORT)
    if a.http_dns:
        try:
            await asyncio.start_server(lambda r, w: http_conn(rec, ip, r, w), '127.0.0.1', 80)
        except OSError:
            pass
    print('\nReady. Start OverField now (directly from launcher.exe or Steam) and log in with your official account.')
    print('Open these in game so they are saved too:')
    for label, rsp, how in CHECKLIST:
        print(f'   - {label:<40} {how}')
    print('\nWhen finished, close the game, then press Ctrl+C here.\n')
    while True:
        await asyncio.sleep(3600)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', required=True, help='OverField install folder (holds launcher.exe)')
    ap.add_argument('--out', default=os.path.join(HERE, 'exports'))
    ap.add_argument('--http-dns', action='store_true', help='also answer HTTPDNS on port 80')
    ap.add_argument('--restore', action='store_true', help='only undo leftovers of an interrupted run')
    ap.add_argument('--upstream', default=None, help=argparse.SUPPRESS)  # testing: host:port of another dispatch
    a = ap.parse_args()
    ap_restore = a.restore
    restore_leftovers(a.game)
    if ap_restore:
        return
    os.makedirs(a.out, exist_ok=True)
    state = patch_client(a.game)
    rec = Recorder(a.out)
    rec.on_dispatch = lambda: restore_client(state[0], state[1], state[2], False)
    try:
        asyncio.run(main_async(a, rec))
    except KeyboardInterrupt:
        pass
    finally:
        restore_client(*state)
        print('\ngame settings restored.')
        for r in (rec,):
            p = r.save()
            if p:
                print(f'YOUR SAVE: {p}  ({len(r.frames)} messages)')
                miss = r.missing()
                if miss:
                    print('not captured (run again and open these if you want them kept):')
                    for l, how in miss:
                        print(f'   - {l}: {how}')
            else:
                print('nothing was recorded - did the game connect? (start this before the game)')


if __name__ == '__main__':
    main()
