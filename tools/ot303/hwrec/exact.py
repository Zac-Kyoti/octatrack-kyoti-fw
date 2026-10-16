import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.int64)
ref=np.round(np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608).astype(np.int64)
for t,s0 in (('t6',101489),('t2',169441)):
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.int64)
    best=None
    for d in range(-200,201):
        s=s0+d; i=np.arange(30000,40000)
        e=np.mean(x[i]==ref[i+s])
        if best is None or e>best[0]: best=(e,s)
    e,s=best
    idx=np.arange(len(x))+s; ok=idx<len(ref)
    diff=x[ok]-ref[idx[ok]]
    print(f'{t}: best offset {s}: exact over the window {e*100:.1f}%; whole file exact {np.mean(diff==0)*100:.2f}%  (|diff|<=1: {np.mean(np.abs(diff)<=1)*100:.2f}%)')
    bad=np.nonzero(diff!=0)[0]
    if len(bad):
        print('   first non-exact', bad[:8], 'values', diff[bad[:8]])
        # runs of bad samples
        runs=np.split(bad,np.nonzero(np.diff(bad)>1)[0]+1)
        lens=np.array([len(r) for r in runs])
        print(f'   {len(runs)} runs; length histogram:', {int(k):int(v) for k,v in zip(*np.unique(np.minimum(lens,64),return_counts=True))})
        print('   run starts mod 16:', np.bincount(np.array([r[0] for r in runs]+[0])[:-1]%16 if len(runs) else [0],minlength=16) if False else np.bincount((np.array([r[0] for r in runs])+s)%16,minlength=16))
        print('   first runs (start, len, max|d|):', [(int(r[0]),len(r),int(np.max(np.abs(diff[r])))) for r in runs[:12]])

print()
for t,s in (('t6',101485),('t2',169444)):
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.int64)
    idx=np.arange(len(x))+s; ok=idx<len(ref); diff=np.zeros(len(x),dtype=np.int64); diff[ok]=x[ok]-ref[idx[ok]]
    blk=4410
    print(t, 'max|diff| per 0.1 s:', ' '.join(f'{int(np.max(np.abs(diff[i:i+blk]))):d}' for i in range(0,len(x),blk)))
