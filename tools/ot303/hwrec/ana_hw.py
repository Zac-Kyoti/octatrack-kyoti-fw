import wave, numpy as np, sys
D='out/ot303/hwprobe'
def load(p):
    w=wave.open(p); ch=w.getnchannels(); n=w.getnframes(); b=np.frombuffer(w.readframes(n),dtype=np.uint8).reshape(-1,3).astype(np.int32)
    v=b[:,0]|(b[:,1]<<8)|(b[:,2]<<16); v=np.where(v>=1<<23,v-(1<<24),v); return v.reshape(-1,ch)
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608   # bench, 24-bit units
bar=16*5088
for t in ('t6','t2'):
    x=load(f'{D}/hw/{t}.wav'); L=x[:,0].astype(np.float64); R=x[:,1].astype(np.float64)
    print(f'== {t}: {len(L)} samples, L==R {np.mean(L==R)*100:.1f}%, peak {np.max(np.abs(L)):.0f} ({20*np.log10(np.max(np.abs(L))/8388608):.1f} dBFS), rms {np.sqrt(np.mean(L**2)):.0f}')
    # align a 20000-sample window of the recording against one bar of the reference (bar 2 onward: steady state)
    seg=L[20000:60000]; r=ref[bar:3*bar]
    n=1<<int(np.ceil(np.log2(len(r)+len(seg))))
    c=np.fft.irfft(np.fft.rfft(r,n)*np.conj(np.fft.rfft(seg,n)),n)
    lag=int(np.argmax(c[:len(r)-len(seg)]))
    rr=r[lag:lag+len(seg)]; g=(seg@rr)/(rr@rr); res=seg-g*rr
    print(f'   best match at bar offset {lag} (of {bar}), gain {g:.5f}, residual/signal power {np.sum(res**2)/np.sum(seg**2):.2e}')
    # exactness and error structure over the whole recording, mapped by the same offset
    start=bar+lag-20000
    idx=np.arange(len(L))+start
    ok=(idx>=0)&(idx<len(ref)); RR=np.zeros(len(L)); RR[ok]=ref[idx[ok]]
    d=L-np.round(g*RR)
    bad=np.nonzero(np.abs(d)>max(2,abs(g-1)*1e6))[0]
    print(f'   samples differing (>2 LSB): {len(bad)} of {len(L)}; exact (d==0): {np.mean(d==0)*100:.1f}%')
    if len(bad):
        ph=(bad+start)%16
        print('   position within the 16-sample frame of differing samples (histogram):', np.bincount(ph,minlength=16))
        print('   first differing at', bad[:10], 'max |d|', np.max(np.abs(d)))
    np.save(f'{D}/hw/{t}_d.npy', d)
