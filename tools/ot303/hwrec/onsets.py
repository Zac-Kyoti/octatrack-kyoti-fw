import numpy as np, sys
exec(open('out/ot303/hwprobe/hw/ana_hw.py').read().split("ref=np.fromfile")[0])
D='out/ot303/hwprobe'
ref=np.fromfile(f'{D}/B/out_40.f32',dtype=np.float32).astype(np.float64)*8388608
def onsets(x, name):
    e=np.abs(x); k=64; env=np.convolve(e,np.ones(k)/k,mode='same')
    # onset = env rises above 3x its value 300 samples earlier and above 5% of max
    on=[]; thr=0.05*np.max(env)
    i=600
    while i<len(env):
        if env[i]>thr and env[i]>3*env[i-300]+1:
            on.append(i); i+=1500
        else: i+=1
    on=np.array(on); print(name,'onsets',len(on),'spacings',np.diff(on)[:24])
    return on
for t in ('t6','t2'):
    x=load(f'{D}/hw/{t}.wav')[:,0].astype(np.float64); onsets(x,t)
onsets(ref[:352800],'bench')
