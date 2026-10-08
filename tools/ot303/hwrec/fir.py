import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608
bar=81408
def align(x):
    seg=x[20000:60000]; r=ref[bar:3*bar]
    n=1<<int(np.ceil(np.log2(len(r)+len(seg))))
    c=np.fft.irfft(np.fft.rfft(r,n)*np.conj(np.fft.rfft(seg,n)),n)
    lag=int(np.argmax(c[:len(r)-len(seg)])); return bar+lag-20000
for t in ('t6','t2'):
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.float64)
    s=align(x); K=96; half=K//2
    # fit x[n] = sum_k h[k] ref[s+n-k+half] over a 60000-sample window (least squares)
    N0,N1=30000,90000
    A=np.stack([ref[s+np.arange(N0,N1)-k+half] for k in range(K)],1)
    y=x[N0:N1]
    h,*_=np.linalg.lstsq(A,y,rcond=None)
    res=y-A@h
    print(f'{t}: start {s}; FIR fit residual/signal {np.sum(res**2)/np.sum(y**2):.2e}; h peak at tap {np.argmax(np.abs(h))} value {h[np.argmax(np.abs(h))]:.4f}; sum(h) {h.sum():.4f}')
    # apply over the whole file and report residual per 1/4 s block
    idx=np.arange(len(x))+s
    ok=(idx-half-K>0)&(idx+half<len(ref))
    yy=np.zeros(len(x))
    for k in range(K): yy[ok]+=h[k]*ref[idx[ok]-k+half]
    r=x-yy
    blk=11025
    print('   residual/signal per 1/4 s:', ' '.join(f'{np.sum(r[i:i+blk]**2)/max(np.sum(x[i:i+blk]**2),1):.0e}' for i in range(0,len(x)-blk,blk)))
    np.save(f'{D}/hw/{t}_res.npy', r); np.save(f'{D}/hw/{t}_h.npy', h)
