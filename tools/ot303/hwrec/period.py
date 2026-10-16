import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608
def env(x,k=256):
    e=np.abs(x); n=len(e)//k; return e[:n*k].reshape(n,k).mean(1)
for name,x in (('bench',ref[:352800]),('t6',load(f'{D}/hw/t6.wav')[:,0].astype(np.float64)),('t2',load(f'{D}/hw/t2.wav')[:,0].astype(np.float64))):
    e=env(x); e=e-e.mean()
    best=max(range(70000//256,95000//256),key=lambda L: (e[:-L]@e[L:])/np.sqrt((e[:-L]@e[:-L])*(e[L:]@e[L:])))
    cc=(e[:-best]@e[best:])/np.sqrt((e[:-best]@e[:-best])*(e[best:]@e[best:]))
    # fine: sample-level around best*256
    print(f'{name}: bar period ~{best*256} samples (corr {cc:.3f}); expected 81408')
    # pitch: zero-crossing based fundamental of the loudest 0.3 s
    seg=x[:]
    sp=np.abs(np.fft.rfft(seg*np.hanning(len(seg)))); f=np.fft.rfftfreq(len(seg),1/44100)
    m=(f>30)&(f<400); print('   strongest low partials (Hz):', np.round(f[m][np.argsort(sp[m])[-5:]],1))
