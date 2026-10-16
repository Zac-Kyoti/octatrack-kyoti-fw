import numpy as np
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608
starts={'t6':101489,'t2':169441}
# a 2048-sample window starting 200 samples after each accented step-0 onset of a bar: bench bar k*81408
for t,s in starts.items():
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.float64)
    # bar starts in recording index: n such that (n+s) % 81408 == 0
    n0=(-s)%81408
    print(f'== {t}: bar starts at recording sample {n0}, {n0+81408}, ...')
    for step,off in ((0,0),(2,2*5088),(4,4*5088)):
        i=n0+off+300
        if i+2048>len(x): continue
        a=x[i:i+2048]; b=ref[(i+s):(i+s)+2048]
        A=np.abs(np.fft.rfft(a*np.hanning(2048))); B=np.abs(np.fft.rfft(b*np.hanning(2048))); f=np.fft.rfftfreq(2048,1/44100)
        bands=[(30,150),(150,500),(500,1500),(1500,4000),(4000,10000),(10000,20000)]
        def db(S,lo,hi): m=(f>=lo)&(f<hi); return 10*np.log10(np.sum(S[m]**2)+1)
        print(f'  step {step}: rms rec {np.sqrt(np.mean(a**2)):9.0f} bench {np.sqrt(np.mean(b**2)):9.0f} | band dB rec-bench: '+' '.join(f'{lo}-{hi}:{db(A,lo,hi)-db(B,lo,hi):+5.1f}' for lo,hi in bands))
