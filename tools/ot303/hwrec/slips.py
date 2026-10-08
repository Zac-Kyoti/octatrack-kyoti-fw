import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.round(np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608).astype(np.int64)
for t,s0 in (('t6',101485),('t2',169444)):
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.int64)
    out=[]
    s=s0
    for i in range(0,len(x)-1024,2205):
        a=x[i:i+1024]
        best=None
        for d in range(-400,401):
            j=i+s+d
            if j<0 or j+1024>len(ref): continue
            m=np.mean(np.abs(a-ref[j:j+1024])<=4)
            if best is None or m>best[0]: best=(m,d)
        m,d=best
        if m>0.9: s=s+d
        out.append((i, s-s0 if m>0.9 else None, round(m,2)))
    print(t, ' '.join(f'{o[1] if o[1] is not None else "--"}' for o in out))
    print('   match:', ' '.join(f'{o[2]:.2f}' for o in out[:60]))
