"""Import a player's backup (.rzsave, made with Rozefield Backup.exe or export_my_data.bat while the official server
was online) as their own Rozefield account. Everything they had done carries over; logging in with a name that was
never imported starts a fresh account as usual. Players can also import from the Rozefield login window.

    py tools\\import_player.py <file.rzsave> [--name <login name>]
"""
import argparse, base64, io, json, os, struct, sys, zipfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from ofproto import decode, to_dict, Head  # noqa: E402
from tools.import_archive import build, ImportFailed  # noqa: E402

MAGIC2 = b'RZSAVE2\n'


# login and device details (account SDK id, device id/model, analytics id, log-server token, client logs): never kept,
# even from backups made before Rozefield Backup left them out
PRIVATE = {'VerifyLoginTokenReq', 'VerifyLoginTokenRsp', 'PlayerLoginReq', 'PlayerLoginRsp', 'ClientLogAuthReq', 'ClientLogMessageReq'}


def _msg(t, direction, conn, mid, pid, body):
    try:
        name, m = decode(mid, body)
        b = to_dict(m) if m is not None else {}
    except Exception:
        return None
    if not name:
        return None
    if name in PRIVATE:
        b = {}
    return {'t': t, 'dir': direction, 'port': conn, 'name': name, 'head': {'packet_id': pid, 'msg_id': mid}, 'body': b}


def read_rzsave_bytes(data):
    """-> (meta, [decoded messages]). Supports the zip format (export_my_data.bat) and RZSAVE2 (Rozefield Backup.exe)."""
    msgs = []
    if data.startswith(MAGIC2):
        import cramjam
        nl = data.index(b'\n', len(MAGIC2))
        meta = json.loads(data[len(MAGIC2):nl])
        off = nl + 1
        while off + 15 <= len(data):
            direction, conn, t, ln = struct.unpack_from('<BHdI', data, off); off += 15
            raw = data[off:off + ln]; off += ln
            if len(raw) < 2:
                continue
            hl = int.from_bytes(raw[:2], 'big')
            h = Head(); h.ParseFromString(raw[2:2 + hl])
            body = raw[2 + hl:]
            if h.flag == 1 and body:
                try:
                    body = bytes(cramjam.snappy.decompress_raw(body))
                except Exception:
                    continue
            m = _msg(t, 'S2C' if direction else 'C2S', conn, h.msg_id, h.packet_id, body)
            if m:
                msgs.append(m)
        return meta, msgs
    z = zipfile.ZipFile(io.BytesIO(data))
    meta = json.loads(z.read('meta.json'))
    for f in json.loads(z.read('gate.json')):
        m = _msg(f['t'], f['dir'], f.get('conn', 0), f['msg_id'], f.get('packet_id', 0), base64.b64decode(f['body']))
        if m:
            msgs.append(m)
    return meta, msgs


def import_bytes(data, name=None):
    """Import one backup. Returns (save path, uid, in-game name). Raises ImportFailed with a player-readable reason."""
    try:
        meta, msgs = read_rzsave_bytes(data)
    except ImportFailed:
        raise
    except Exception as e:
        raise ImportFailed(f'this is not a Rozefield backup file ({e.__class__.__name__})')
    md = next((m['body'] for m in msgs if m['name'] == 'PlayerMainDataRsp'), None)
    name = name or (md or {}).get('player_name') or meta.get('player_name') or 'player'
    return build(name, msgs, keep_player_id=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rzsave')
    ap.add_argument('--name', help='login name (default: the in-game name)')
    a = ap.parse_args()
    try:
        path, uid, nm = import_bytes(open(a.rzsave, 'rb').read(), a.name)
    except ImportFailed as e:
        sys.exit(f'import failed: {e}')
    print(f'OK: "{nm}" -> {path}')


if __name__ == '__main__':
    main()
