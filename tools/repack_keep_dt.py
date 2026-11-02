# Usage: python3 repack_keep_dt.py <stock boot.img> <donor.img | ramdisk.gz> <out.img>
# Keeps stock kernel + Spreadtrum DT. Donor .img: take its ramdisk+cmdline.
# Raw gzipped ramdisk: use it with the stock cmdline.
import struct,hashlib,sys
orig=open(sys.argv[1],'rb').read(); donor=open(sys.argv[2],'rb').read()
def parse(d):
    h=struct.unpack('<8s10I',d[:48]); ps=h[8]; p=lambda n:(n+ps-1)//ps*ps
    ks,rs,ss,dt=h[1],h[3],h[5],h[9]
    ko=ps; ro=ko+p(ks); so=ro+p(rs); do=so+p(ss)
    return h,ps,p,d[ko:ko+ks],d[ro:ro+rs],d[do:do+dt],d[64:576]
h,ps,p,kern,_,dtb,_=parse(orig)
if donor[:8]==b'ANDROID!': _,_,_,_,ram,_,cmd=parse(donor)
else: ram=donor; cmd=orig[64:576]
assert dtb[:4]==b'SPRD' and len(dtb)==215040
sha=hashlib.sha1()
for blob in (kern,ram,b''): sha.update(blob); sha.update(struct.pack('<I',len(blob)))
sha.update(dtb); sha.update(struct.pack('<I',len(dtb)))
hdr=struct.pack('<8s10I',h[0],len(kern),h[2],len(ram),h[4],0,h[6],h[7],ps,len(dtb),h[10])
hdr+=orig[48:64]+cmd+sha.digest()+b'\0'*12
pad=lambda b:b+b'\0'*(p(len(b))-len(b))
out=pad(hdr)+pad(kern)+pad(ram)+pad(dtb)
open(sys.argv[3],'wb').write(out); print('wrote',len(out))
