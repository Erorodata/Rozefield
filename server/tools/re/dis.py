import pickle,struct,pefile,capstone,sys
md=open('/mnt/user-data/uploads/OverField/launcher_Data/il2cpp_data/Metadata/global-metadata.dat','rb').read()
_,_,slOff,slSize,sldOff,_=struct.unpack_from('<Iiiiii',md,0)
lits=[]
for i in range(slSize//8):
    ln,idx=struct.unpack_from('<Ii',md,slOff+i*8); lits.append(md[sldOff+idx:sldOff+idx+ln])
gl,refs=pickle.load(open('/home/claude/litxref.pkl','rb'))
img=open('/mnt/user-data/uploads/OverField/GameAssembly.dll','rb').read()
p=pefile.PE(data=img,fast_load=True)
cs=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); cs.detail=True
a=int(sys.argv[1],16); n=int(sys.argv[2])
off=p.get_offset_from_rva(a)
for ins in cs.disasm(img[off:off+n*8],a):
    s=''
    for o in ins.operands:
        if o.type==3 and o.mem.base==capstone.x86_const.X86_REG_RIP:
            t=ins.address+ins.size+o.mem.disp
            if t in gl: s=' ; "'+lits[gl[t]][:70].decode('utf8','replace')+'"'
    print(hex(ins.address),ins.mnemonic,ins.op_str,s)
    n-=1
    if n<=0: break
