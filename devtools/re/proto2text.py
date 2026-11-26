import sys,os
from google.protobuf import descriptor_pb2 as D
fds=D.FileDescriptorSet(); fds.ParseFromString(open(sys.argv[1],'rb').read()); out=sys.argv[2]
T={1:'double',2:'float',3:'int64',4:'uint64',5:'int32',6:'fixed64',7:'fixed32',8:'bool',9:'string',12:'bytes',13:'uint32',15:'sfixed32',16:'sfixed64',17:'sint32',18:'sint64'}
def varint(b,i):
    r=s=0
    while True:
        c=b[i];i+=1;r|=(c&0x7f)<<s;s+=7
        if c<0x80:return r,i
def opts(m):
    raw=m.options.SerializeToString();i=0;o={}
    while i<len(raw):
        t,i=varint(raw,i)
        if t&7==0: v,i=varint(raw,i); o[t>>3]=v
        else: return o
    return o
def ftype(f):
    return f.type_name.lstrip('.') if f.type in (11,14) else T[f.type]
def msg(m,ind,syntax3,mapentries):
    s=[]
    p='  '*ind
    o=opts(m)
    note=f'  // msg_id {o[10001]}' if 10001 in o else ''
    s.append(f'{p}message {m.name} {{{note}')
    me={n.name:n for n in m.nested_type if n.options.map_entry}
    for e in m.enum_type: s+=enum(e,ind+1)
    for n in m.nested_type:
        if not n.options.map_entry: s+=msg(n,ind+1,syntax3,mapentries)
    oneofs={}
    for f in m.field:
        if f.HasField('oneof_index') and not f.proto3_optional: oneofs.setdefault(f.oneof_index,[]).append(f)
    done=set()
    for f in m.field:
        if f.HasField('oneof_index') and not f.proto3_optional:
            if f.oneof_index in done: continue
            done.add(f.oneof_index)
            s.append(f'{p}  oneof {m.oneof_decl[f.oneof_index].name} {{')
            for g in oneofs[f.oneof_index]: s.append(f'{p}    {ftype(g)} {g.name} = {g.number};')
            s.append(f'{p}  }}'); continue
        short=f.type_name.split('.')[-1]
        if f.label==3 and f.type==11 and short in me:
            k,v=me[short].field
            s.append(f'{p}  map<{ftype(k)}, {ftype(v)}> {f.name} = {f.number};'); continue
        lab='repeated ' if f.label==3 else ('optional ' if f.proto3_optional or not syntax3 and f.label==1 else ('required ' if f.label==2 else ''))
        s.append(f'{p}  {lab}{ftype(f)} {f.name} = {f.number};')
    s.append(f'{p}}}')
    return s
def enum(e,ind):
    p='  '*ind; s=[f'{p}enum {e.name} {{']
    if e.options.allow_alias: s.append(f'{p}  option allow_alias = true;')
    s+= [f'{p}  {v.name} = {v.number};' for v in e.value]; s.append(f'{p}}}'); return s
for f in fds.file:
    if f.name.startswith('google/'): continue
    syn3=f.syntax=='proto3'
    L=[f'// Recovered from OverField client (global-metadata.dat) — do not edit by hand','syntax = "%s";'%(f.syntax or 'proto2')]
    if f.package: L.append(f'package {f.package};')
    for d in f.dependency: L.append(f'import "{d}";')
    if f.options.csharp_namespace: L.append(f'option csharp_namespace = "{f.options.csharp_namespace}";')
    L.append('')
    for e in f.enum_type: L+=enum(e,0)
    for m in f.message_type: L+=msg(m,0,syn3,None)
    sub='net' if f.package=='pb' else 'config'
    os.makedirs(os.path.join(out,sub),exist_ok=True)
    open(os.path.join(out,sub,f.name.replace('/','_')),'w').write('\n'.join(L)+'\n')
print('ok')
