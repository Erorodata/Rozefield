import cramjam, sys, dpkt, socket, collections, json, bisect
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, json_format
fds=descriptor_pb2.FileDescriptorSet(); fds.ParseFromString(open('/home/claude/protodesc/overfield.desc','rb').read())
pool=descriptor_pool.DescriptorPool()
pend=list(fds.file); added=set()
while pend:
    nxt=[]
    for f in pend:
        if all(d in added for d in f.dependency):
            pool.Add(f); added.add(f.name)
        else: nxt.append(f)
    if len(nxt)==len(pend): raise SystemExit('dep loop '+str([f.name for f in nxt]))
    pend=nxt
ids={int(k):v for k,v in json.load(open('/home/claude/protodesc/msgids.json')).items()}
def cls(mid):
    n=ids.get(mid); 
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('pb.'+n)) if n else None
Head=message_factory.GetMessageClass(pool.FindMessageTypeByName('pb.PacketHead'))
r=dpkt.pcapng.Reader(open(sys.argv[1],'rb'))
segs=collections.defaultdict(dict)
for ts,buf in r:
    try:
        ip=dpkt.ethernet.Ethernet(buf).data; t=ip.data
        if not isinstance(t,dpkt.tcp.TCP) or not t.data: continue
    except Exception: continue
    if 11001 not in (t.sport,t.dport): continue
    k='C2S' if t.dport==11001 else 'S2C'
    segs[(k,t.sport if k=='C2S' else t.dport)].setdefault(t.seq,(ts,bytes(t.data)))
out=[]; unk=collections.Counter(); err=collections.Counter()
for (k,port),sd in segs.items():
    items=sorted(sd.items()); data=b''; offs=[]; tss=[]
    for s,(ts,b) in items: offs.append(len(data)); tss.append(ts); data+=b
    i=0
    while i+2<=len(data):
        hl=int.from_bytes(data[i:i+2],'big'); h=Head(); 
        try: h.ParseFromString(data[i+2:i+2+hl])
        except Exception: break
        hd=json_format.MessageToDict(h,preserving_proto_field_name=True)
        bl=h.body_len if hasattr(h,'body_len') else 0
        body=data[i+2+hl:i+2+hl+bl]
        if h.flag==1: body=bytes(cramjam.snappy.decompress_raw(body))
        ts=tss[bisect.bisect_right(offs,i)-1]
        mid=h.msg_id if hasattr(h,'msg_id') else None
        rec={'t':round(ts,3),'dir':k,'port':port,'head':hd,'name':ids.get(mid),'len':bl}
        C=cls(mid)
        if C:
            try:
                m=C(); m.ParseFromString(body); rec['body']=json_format.MessageToDict(m,preserving_proto_field_name=True)
            except Exception as e: err[mid]+=1; rec['raw']=body.hex()
        else: unk[mid]+=1; rec['raw']=body.hex()
        out.append(rec); i+=2+hl+bl
out.sort(key=lambda r:r['t'])
json.dump(out,open(sys.argv[2],'w'),ensure_ascii=False)
print('msgs',len(out),'unknown ids',dict(unk),'parse errors',dict(err))
