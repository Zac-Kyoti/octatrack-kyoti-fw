import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
x=load('out/ot303/hwprobe/hw/t2.wav').astype(np.int64); L=x[:,0]; R=x[:,1]
# frames where every sample has its low 16 bits zero (record-like), 16-sample frames: find phase first
lowz=((L & 0xffff)==0)&((R & 0xffff)==0)&((L!=0)|(R!=0))
ph=np.bincount(np.nonzero(lowz)[0]%16,minlength=16); print('record-like samples by position mod 16:', ph)
# group consecutive record-like samples into runs, print the interleaved words of the first few runs
idx=np.nonzero(lowz)[0]
runs=np.split(idx,np.nonzero(np.diff(idx)>1)[0]+1)
print('record-like runs:',len(runs),'length histogram (cap 40):',np.bincount([min(len(r),40) for r in runs])[1:41])
for r in runs[:8]:
    s=r[0]; e=r[-1]+1
    words=[]
    for i in range(max(0,s-1),min(len(L),e+1)): words+= [int(L[i])&0xffffff, int(R[i])&0xffffff]
    print(f'run at {s} len {len(r)}:', ' '.join(f'{w>>16:02x}' if (w&0xffff)==0 else f'[{w:06x}]' for w in words))
