"""Build a Rozefield save file from your own OverField packet captures.

    python tools/make_save.py capture1.pcapng [capture2.pcapng ...] -o save/save.json

Reads every game-gate (TCP 11001) conversation in the captures, decodes it with
the recovered schema, and keeps:
  * your login / main-data responses (your account, characters, items, home)
  * the notices the server pushed right after login
  * one sample response per distinct request (+ the notices that followed it)
Later captures override earlier ones, so pass them oldest -> newest.
The save contains your own account data: keep it private.
"""
import argparse, collections, json, os, socket, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dpkt
from ofproto import decode, to_dict

GATE_PORT = 11001
NOISE = {'PlayerSceneSyncDataNotice', 'PlayerPingRsp', 'SendActionNotice', 'ChatMsgNotice',
         'ServerSceneSyncDataNotice', 'SendActionAddNotice', 'SystemNotice'}
BACKGROUND_REQ = {'PlayerSceneRecordReq', 'PlayerPingReq'}
MAX_VARIANTS = 40


def streams(path):
    rd = dpkt.pcapng.Reader(open(path, 'rb')) if path.endswith('ng') else dpkt.pcap.Reader(open(path, 'rb'))
    segs = collections.defaultdict(dict)
    for ts, buf in rd:
        try:
            ip = dpkt.ethernet.Ethernet(buf).data
            t = ip.data
            if not isinstance(t, dpkt.tcp.TCP) or not t.data:
                continue
        except Exception:
            continue
        if GATE_PORT not in (t.sport, t.dport):
            continue
        d = 'C2S' if t.dport == GATE_PORT else 'S2C'
        port = t.sport if d == 'C2S' else t.dport
        segs[(port, d)].setdefault(t.seq, (ts, bytes(t.data)))  # dedupe pktmon layers
    conns = collections.defaultdict(list)
    for (port, d), sd in segs.items():
        buf = bytearray(); marks = []
        for _, (ts, b) in sorted(sd.items()):
            marks.append((len(buf), ts)); buf += b
        mi = 0; pos = 0
        while True:
            before = len(buf)
            fr = unframe_one(buf)
            if fr is None:
                break
            while mi + 1 < len(marks) and marks[mi + 1][0] <= pos:
                mi += 1
            conns[port].append((marks[mi][1], d, fr[0], fr[1]))
            pos += before - len(buf)
    for port in conns:
        conns[port].sort(key=lambda x: (x[0], 0 if x[1] == 'C2S' else 1))
    return conns


def unframe_one(buf):
    from ofproto import Head
    import cramjam
    if len(buf) < 2:
        return None
    hl = int.from_bytes(buf[:2], 'big')
    if len(buf) < 2 + hl:
        return None
    h = Head(); h.ParseFromString(bytes(buf[2:2 + hl]))
    if len(buf) < 2 + hl + h.body_len:
        return None
    body = bytes(buf[2 + hl:2 + hl + h.body_len])
    del buf[:2 + hl + h.body_len]
    if h.flag == 1:
        body = bytes(cramjam.snappy.decompress_raw(body))
    return h, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('captures', nargs='+')
    ap.add_argument('-o', '--out', default='save/save.json')
    a = ap.parse_args()
    save = {'account': {}, 'login_rsp': None, 'main_data': None, 'login_notices': [], 'responses': {}}
    for cap in a.captures:
        print('reading', cap)
        for port, msgs in streams(cap).items():
            ev = []
            for ts, d, h, body in msgs:
                try:
                    name, m = decode(h.msg_id, body)
                except Exception as e:
                    print('  decode error', h.msg_id, e); continue
                if name:
                    ev.append((ts, d, h, name, to_dict(m)))
            pending = {}
            last_rsp = None
            in_login = False
            for ts, d, h, name, body in ev:
                if d == 'C2S':
                    if name == 'VerifyLoginTokenReq':
                        save['account'] = {'sdkUid': body.get('sdkUid'), 'account_type': body.get('account_type')}
                    if name not in BACKGROUND_REQ:
                        in_login = False; last_rsp = None
                    pending[(h.packet_id, name[:-3])] = body
                    continue
                if name == 'VerifyLoginTokenRsp':
                    save['account']['user_id'] = body.get('user_id')
                elif name == 'PlayerLoginRsp':
                    save['login_rsp'] = body
                elif name == 'PlayerMainDataRsp':
                    save['main_data'] = body; save['login_notices'] = []; in_login = True
                    continue
                if in_login and not h.packet_id:
                    if name not in NOISE:
                        save['login_notices'].append([name, body])
                    continue
                if name.endswith('Rsp') and (h.packet_id, name[:-3]) in pending:
                    req = pending.pop((h.packet_id, name[:-3]))
                    rq = name[:-3] + 'Req'
                    lst = save['responses'].setdefault(rq, [])
                    entry = {'req': req, 'rsp_name': name, 'rsp': body, 'followups': []}
                    lst[:] = [x for x in lst if x['req'] != req]
                    lst.append(entry); del lst[:-MAX_VARIANTS]
                    last_rsp = entry
                elif last_rsp is not None and not h.packet_id and name not in NOISE:
                    last_rsp['followups'].append([name, body])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(save, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('save written:', a.out)
    print('  account', save['account'])
    print('  login notices', len(save['login_notices']), ' request types', len(save['responses']))


if __name__ == '__main__':
    main()
