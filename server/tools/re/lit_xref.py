import pefile,struct,sys,pickle,re,numpy as np
p=pefile.PE(sys.argv[1],fast_load=True); img=open(sys.argv[1],'rb').read()
md=open(sys.argv[2],'rb').read()
_,_,slOff,slSize,sldOff,_=struct.unpack_from('<Iiiiii',md,0)
N=slSize//8
sec={s.Name.rstrip(b'\0'):s for s in p.sections}
D=sec[b'.data']; dat=np.frombuffer(img[D.PointerToRawData:D.PointerToRawData+D.SizeOfRawData//8*8],dtype='<u8')
tok=dat; m=((tok>>29)==5)&((tok&1)==1)&(tok< (6<<29))
idx=np.nonzero(m)[0]
gl={}  # rva -> literal index
for i in idx:
    li=int((tok[i]&((1<<29)-1))>>1)
    if li<N: gl[D.VirtualAddress+int(i)*8]=li
print('string literal globals',len(gl))
# scan code for rip-relative refs
refs={}
for nm in (b'.text',b'il2cpp'):
    S=sec[nm]; code=img[S.PointerToRawData:S.PointerToRawData+S.SizeOfRawData]
    a=np.frombuffer(code[:len(code)//4*4+0],dtype=np.uint8)
    # disp at every offset k: int32 code[k:k+4]; target = S.VA + k+4 + disp
    L=len(code)-4
    b=np.frombuffer(code,dtype=np.uint8).astype(np.int64)
    disp=(b[0:L]|(b[1:L+1]<<8)|(b[2:L+2]<<16)|(b[3:L+3]<<24))
    disp=np.where(disp>=2**31,disp-2**32,disp)
    tgt=S.VirtualAddress+np.arange(L)+4+disp
    keys=np.array(sorted(gl),dtype=np.int64)
    hit=np.isin(tgt,keys)
    for k in np.nonzero(hit)[0]:
        refs.setdefault(int(tgt[k]),[]).append(S.VirtualAddress+int(k))
print('globals referenced',len(refs))
pickle.dump((gl,refs),open('/home/claude/litxref.pkl','wb'))
