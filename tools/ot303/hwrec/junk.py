import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
for t in ('t2','t6'):
    x=load(f'{D}/hw/{t}.wav').astype(np.int64); L=x[:,0]; R=x[:,1]
    big=np.nonzero(np.abs(L)>int(0.7*8388608))[0]
    lr=np.nonzero(L!=R)[0]
    print(f'== {t}: samples with |L| > 0.7 FS: {len(big)}; L != R: {len(lr)}; nonzero to sample {np.nonzero(L)[0][-1]}')
    if len(big):
        runs=np.split(big,np.nonzero(np.diff(big)>1)[0]+1)
        print('   runs:',len(runs),'lengths:',np.bincount([min(len(r),40) for r in runs])[1:41])
        print('   first 10 runs (start,len):',[(int(r[0]),len(r)) for r in runs[:10]])
        st=np.array([r[0] for r in runs]); print('   gaps between runs:',np.diff(st)[:20])
    if len(lr):
        runs=np.split(lr,np.nonzero(np.diff(lr)>1)[0]+1)
        print('   L!=R runs:',len(runs),[(int(r[0]),len(r)) for r in runs[:10]])
        r=runs[0]; print('   sample L,R in first:',[(int(L[i]),int(R[i])) for i in r[:6]])
    # second difference outliers (clicks) relative to local signal
    d2=np.abs(np.diff(L,2)); med=np.median(d2)
    clicks=np.nonzero(d2>60*med+1000)[0]
    print(f'   2nd-difference outliers: {len(clicks)}; median d2 {med:.0f}; per second {len(clicks)/8:.0f}')
    if len(clicks):
        print('   positions mod 16 of outliers:', np.bincount(clicks%16,minlength=16))
