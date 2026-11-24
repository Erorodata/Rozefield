"""Shared OverField protocol helpers: schema loading, framing, (de)compression."""
import json, os
import cramjam
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, json_format

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO_DIR = os.path.join(HERE, 'proto')

_fds = descriptor_pb2.FileDescriptorSet()
_fds.ParseFromString(open(os.path.join(PROTO_DIR, 'overfield.desc'), 'rb').read())
pool = descriptor_pool.DescriptorPool()
_pending, _added = list(_fds.file), set()
while _pending:
    nxt = []
    for f in _pending:
        if all(d in _added for d in f.dependency):
            pool.Add(f); _added.add(f.name)
        else:
            nxt.append(f)
    if len(nxt) == len(_pending):
        raise RuntimeError('unresolved proto deps: %s' % [f.name for f in nxt])
    _pending = nxt

ID2NAME = {int(k): v for k, v in json.load(open(os.path.join(PROTO_DIR, 'msgids.json'))).items()}
NAME2ID = {v: k for k, v in ID2NAME.items()}
_cls = {}


def msg_class(name):
    if name not in _cls:
        _cls[name] = message_factory.GetMessageClass(pool.FindMessageTypeByName('pb.' + name))
    return _cls[name]


def new(name, **kw):
    m = msg_class(name)()
    if kw:
        json_format.ParseDict(kw, m, ignore_unknown_fields=True)
    return m


def from_dict(name, d):
    m = msg_class(name)()
    json_format.ParseDict(d, m, ignore_unknown_fields=True)
    return m


def to_dict(m):
    return json_format.MessageToDict(m, preserving_proto_field_name=True)


def decode(mid, body):
    name = ID2NAME.get(mid)
    if not name:
        return None, None
    m = msg_class(name)()
    m.ParseFromString(body)
    return name, m


Head = msg_class('PacketHead')
COMPRESS_OVER = 4096  # server compresses big bodies (flag=1, raw snappy)


def frame(mid, body, packet_id=None, seq_id=None, compress=True):
    h = Head()
    h.msg_id = mid
    if packet_id:
        h.packet_id = packet_id
    if seq_id:
        h.seq_id = seq_id
    if compress and len(body) > COMPRESS_OVER:
        body = bytes(cramjam.snappy.compress_raw(body))
        h.flag = 1
    if body:
        h.body_len = len(body)
    hb = h.SerializeToString()
    return len(hb).to_bytes(2, 'big') + hb + body


def unframe(buf):
    """Yield (head, body) from a bytearray, consuming complete frames."""
    out = []
    while len(buf) >= 2:
        hl = int.from_bytes(buf[:2], 'big')
        if len(buf) < 2 + hl:
            break
        h = Head(); h.ParseFromString(bytes(buf[2:2 + hl]))
        bl = h.body_len
        if len(buf) < 2 + hl + bl:
            break
        body = bytes(buf[2 + hl:2 + hl + bl])
        del buf[:2 + hl + bl]
        if h.flag == 1:
            body = bytes(cramjam.snappy.decompress_raw(body))
        out.append((h, body))
    return out
