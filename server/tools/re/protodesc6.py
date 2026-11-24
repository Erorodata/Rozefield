import pickle,struct,pefile,capstone,base64,re,sys,os
from capstone import x86_const as X
from google.protobuf import descriptor_pb2
md=open(sys.argv[1],'rb').read(); img=open(sys.argv[2],'rb').read(); out=sys.argv[3]
_,_,slOff,slSize,sldOff,_=struct.unpack_from('<Iiiiii',md,0)
lits=[]
for i in range(slSize//8):
    ln,idx=struct.unpack_from('<Ii',md,slOff+i*8); lits.append(md[sldOff+idx:sldOff+idx+ln])
gl,refs=pickle.load(open('/home/claude/litxref.pkl','rb'))
inv={v:k for k,v in gl.items()}
p=pefile.PE(data=img,fast_load=True)
cs=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); cs.detail=True
b64=re.compile(rb'^[A-Za-z0-9+/=]+$')
def startname(s):
    if not re.match(rb'^C[g-j]',s) or len(s)<8 or not b64.match(s): return None
    try: h=base64.b64decode(s[:len(s)//4*4][:200])
    except Exception: return None
    if len(h)>2 and h[0]==10 and len(h)>=2+h[1]:
        nm=h[2:2+h[1]]
        if nm.endswith(b'.proto'): return nm.decode('latin1')
res={}; fails=[]
for li,l in enumerate(lits):
    nm=startname(l)
    if not nm or li not in inv: continue
    got=None
    for p0 in sorted(refs[inv[li]],reverse=True):
        start=p0-3
        off=p.get_offset_from_rva(start)
        arr={}; r8=None; cnt=0; miss=0
        for ins in cs.disasm(img[off:off+3_000_000],start):
            cnt+=1
            if ins.mnemonic=='ret' or cnt>400000: break
            if ins.mnemonic=='mov' and len(ins.operands)==2:
                a,b=ins.operands
                if a.type==X.X86_OP_REG and b.type==X.X86_OP_MEM and b.mem.base==X.X86_REG_RIP:
                    t=ins.address+ins.size+b.mem.disp
                    if t in gl and a.reg in (X.X86_REG_R8,): r8=gl[t]
                elif a.type==X.X86_OP_REG and a.reg==X.X86_REG_EDX and b.type==X.X86_OP_IMM and r8 is not None:
                    if b.imm!=len(arr): break
                    arr[b.imm]=r8; r8=None
            elif ins.mnemonic=='xor' and ins.op_str=='edx, edx' and r8 is not None:
                if arr: break
                arr[0]=r8; r8=None
        if 0 not in arr or arr[0]!=li: continue
        buf=b''
        for i in range(len(arr)):
            if i not in arr: break
            buf+=lits[arr[i]]
        for cut in range(len(buf)//4*4, 0, -4):
            try:
                raw=base64.b64decode(buf[:cut]); f=descriptor_pb2.FileDescriptorProto(); f.ParseFromString(raw)
                if f.name==nm and f.SerializeToString()==raw: got=f; break
            except Exception: pass
            if len(buf)-cut>200: break
        if got: break
    if got: res[(nm,got.package)]=got
    else: fails.append(nm)
print('fails',fails)
fds=descriptor_pb2.FileDescriptorSet(); fds.file.extend(res.values())
os.makedirs(out,exist_ok=True); open(os.path.join(out,'overfield.desc'),'wb').write(fds.SerializeToString())
print('files',len(res),'msgs',sum(len(f.message_type) for f in res.values()))
for f in res.values():
    if f.package=='pb': print(f.name,len(f.message_type),len(f.enum_type))
