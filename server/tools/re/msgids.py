from google.protobuf import descriptor_pb2
import json,sys
s=descriptor_pb2.FileDescriptorSet(); s.ParseFromString(open('/home/claude/protodesc/overfield.desc','rb').read())
def varint(b,i):
    r=0;sh=0
    while True:
        c=b[i];i+=1;r|=(c&0x7f)<<sh;sh+=7
        if c<0x80: return r,i
def optfields(raw):
    i=0;o={}
    while i<len(raw):
        t,i=varint(raw,i); f,w=t>>3,t&7
        if w==0: v,i=varint(raw,i)
        elif w==2: l,i=varint(raw,i); v=raw[i:i+l]; i+=l
        elif w==5: v=raw[i:i+4]; i+=4
        elif w==1: v=raw[i:i+8]; i+=8
        o.setdefault(f,[]).append(v)
    return o
ids={}; fieldsets=set()
for f in s.file:
    if f.package!='pb': continue
    for m in f.message_type:
        o=optfields(m.options.SerializeToString())
        fieldsets|=set(o)
        if 10001 in o: ids[o[10001][0]]=(f.name,m.name,{k:v for k,v in o.items() if k!=10001})
print('option fields',fieldsets,'ids',len(ids))
fo=optfields(s.file[[x.name for x in s.file].index('player.proto')].options.SerializeToString()); print('file opts',fo)
json.dump({k:v[1] for k,v in sorted(ids.items())},open('/home/claude/protodesc/msgids.json','w'),indent=0)
for k in [1001,1002,1003,1004,1005,1006,1007,1008,1206,51,52]:
    print(k,ids.get(k))
