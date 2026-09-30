#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti: render the same material through RPCH, RPS9 and RPSP on the
emulated DSP, measure what each mode changes, and write WAVs to listen to.

    python3 tools/repitch_dsp_listen.py [out/mainos_repitch_repeat98_kyoti.bin]

Rev 11: the cave is read out of the BUILT image (the bytes you would flash) and
checked against the source; every mode runs through the real stock voice
module with the firmware's streaming protocol (tools/repitch_dsp_engine_probe.cpp).
RPCH is the stock kernel itself. Output: out/listen/*.wav + REPORT.txt.
"""
import pathlib, subprocess, sys, wave
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import repitch_dsp_check as chk   # noqa: E402
import build_sidechain_compressor as sc3    # noqa: E402

SR = 44100
OUTDIR = ROOT / "out/listen"
RENDER = ROOT / "out/repitch_dsp_render"
VEND = ROOT / "vendor/dsp56300"


def build_render():
    import repitch_dsp_engine_check as ck
    ck.build_probe()
    return ck.PROBE


# ---- test material: 16-bit sources, as a sample on a CF card would be -------
def as16(x):
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int32)


def tone_decay(n):
    """A bright 220 Hz tone decaying from -1 to -60 dBFS: the tail is where
    12-bit truncation lives."""
    t = np.arange(n) / SR
    env = 10 ** ((-1 - 59 * t / t[-1]) / 20)
    sig = sum(np.sin(2 * np.pi * 220 * k * t) / k for k in range(1, 13))
    sig /= np.max(np.abs(sig))
    L = sig * env
    R = np.roll(sig, 37) * env
    return as16(L), as16(R)


def drum_loop(n):
    """Two bars at 120 BPM: kick, snare, closed hats."""
    rng = np.random.default_rng(7)
    out = np.zeros(n)
    beat = SR // 2
    def put(at, x):
        e = min(n, at + len(x)); out[at:e] += x[:e - at]
    tk = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 105 * np.exp(-tk * 25)) / SR) * np.exp(-tk * 9)
    ts = np.arange(int(0.2 * SR)) / SR
    snare = (0.7 * rng.standard_normal(len(ts)) + 0.5 * np.sin(2 * np.pi * 180 * ts)) * np.exp(-ts * 18)
    th = np.arange(int(0.05 * SR)) / SR
    hn = rng.standard_normal(len(th) + 1)
    hat = np.diff(hn) * 0.45 * np.exp(-th * 70)
    for b in range(n // beat + 1):
        at = b * beat
        if at >= n: break
        put(at, kick if b % 2 == 0 else snare)
        put(at, hat); put(at + beat // 2, hat)
    out /= np.max(np.abs(out)) * 1.12
    return as16(out), as16(np.roll(out, 11))


def quiet_pad(n):
    """A sustained A-major chord at -30 dBFS: quiet material is where 12 bits
    stop being transparent."""
    t = np.arange(n) / SR
    sig = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) for f in (220, 277.18, 329.63))
    sig *= 10 ** (-30 / 20) / np.max(np.abs(sig))
    return as16(sig), as16(np.roll(sig, 53))


def hats(n):
    """Bright noise bursts and a ride-like tone cluster: where the three
    machines differ most (band limit, aliasing, output filter)."""
    rng = np.random.default_rng(11)
    t = np.arange(n) / SR
    out = np.zeros(n)
    step = SR // 8
    for s in range(0, n, step):
        e = min(n, s + step)
        tt = np.arange(e - s) / SR
        out[s:e] += 0.5 * rng.standard_normal(e - s) * np.exp(-tt * 60)
    ride = sum(np.sin(2 * np.pi * f * t) for f in (3150, 4730, 6300, 8410, 10530)) * 0.08
    out += ride * (0.6 + 0.4 * np.cos(2 * np.pi * 2 * t))
    out /= np.max(np.abs(out)) * 1.1
    return as16(out), as16(np.roll(out, 23))


SIGNALS = {"tone_decay": tone_decay, "drum_loop": drum_loop, "quiet_pad": quiet_pad, "hats": hats}
RATIOS = {"1x": 1.0, "0.75x": 0.75, "1.5x": 1.5}
MODES = {"RPCH": 0, "RPS9": 1, "RPSP": 2}


def write_wav(path, stereo24):
    x = np.clip(stereo24, -(1 << 23), (1 << 23) - 1).astype(np.int32)
    b = x.astype("<i4").tobytes()
    raw = b"".join(b[i:i + 3] for i in range(0, len(b), 4))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(3); w.setframerate(SR); w.writeframes(raw)


def db(x):
    return 20 * np.log10(max(x, 1e-12))


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2))) / (1 << 23)


def hf_share(x, cut=12000):
    """Fraction of energy above `cut` Hz, both channels."""
    mono = (x[0::2] + x[1::2]).astype(np.float64)
    sp = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    f = np.fft.rfftfreq(len(mono), 1 / SR)
    return float(sp[f >= cut].sum() / max(sp.sum(), 1e-30))


def main():
    import repitch_dsp_engine_check as ck
    import repitch_dsp_src as dsrc
    built = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "out/mainos_repitch_repeat98_kyoti.bin")
    img, stock = built.read_bytes(), chk.IMG.read_bytes()
    tag, va, ln, base, hook, stop = chk.PAYLOADS[0]            # payload A
    mod, _ = chk.voice_module(stock, va, ln, base)
    n = len(dsrc.assemble(0x1000)[0])
    org = sc3.DSP[tag]["cave_org"] + sc3.DONOR_WORDS - n
    cave = chk.module_words(img, va, ln, org, n)
    want = b"".join(w.to_bytes(3, "little") for w in dsrc.assemble(org)[0])
    if cave != want:
        sys.exit(f"{built.name}: the DSP cave is not this source's (rebuild the image)")
    hw = chk.module_words(img, va, ln, hook, 2)
    b0, b1 = (int.from_bytes(hw[i:i + 3], "little") for i in (0, 3))
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "voice.bin").write_bytes(mod)
    (OUTDIR / "cave.bin").write_bytes(cave)
    probe = build_render()
    print(f"cave: payload {tag}, {n} words @P:{org:05x}, read from {built.name} (matches the source)\n")

    frames = int(4.0 * SR)
    report = []
    for sname, gen in SIGNALS.items():
        L, R = gen(frames)
        src = np.empty(2 * frames, dtype=np.int32)
        src[0::2], src[1::2] = L << 8, R << 8                # 16-bit -> MSB-aligned 24
        inp = OUTDIR / f"{sname}.in.raw"
        inp.write_bytes(src.astype("<i4").tobytes())
        for rname, ratio in RATIOS.items():
            inc = int(round(ratio * (1 << 24)))
            outs = {}
            for mname, mode in MODES.items():
                o = OUTDIR / f"{sname}_{rname}_{mname}.raw"
                r = subprocess.run([str(probe), str(OUTDIR / "voice.bin"), f"{base:x}", f"{hook:x}", f"{stop:x}",
                                    str(OUTDIR / "cave.bin"), f"{org:x}", f"{b0:x}", f"{b1:x}",
                                    f"{mode:x}", f"{inc >> 24:x}", f"{inc & 0xFFFFFF:x}", "0", str(inp), str(o)],
                                   capture_output=True, text=True)
                if r.returncode:
                    sys.exit(f"render failed ({sname} {rname} {mname}):\n{r.stdout[-800:]}")
                outs[mname] = np.frombuffer(o.read_bytes(), dtype="<i4").astype(np.int64)
                write_wav(OUTDIR / f"{sname}_{rname}_{mname}.wav", outs[mname])
            ref = outs["RPCH"]
            m = min(len(v) for v in outs.values())
            sig = rms(ref[:m])
            row = {"signal": sname, "ratio": rname, "sig_dbfs": db(sig)}
            for mname in ("RPS9", "RPSP"):
                d = outs[mname][:m] - ref[:m]
                row[f"{mname}_diff_dbfs"] = db(rms(d))
                row[f"{mname}_diff_rel"] = db(rms(d)) - db(sig)
                row[f"{mname}_identical"] = bool(np.all(d == 0))
            for mname in MODES:
                row[f"{mname}_hf"] = hf_share(outs[mname][:m])
            report.append(row)

    lines = ["signal      ratio  level    RPS9 vs RPCH        RPSP vs RPCH        energy >12 kHz",
             "                   dBFS     dBFS   rel.dB       dBFS   rel.dB       RPCH    RPS9    RPSP",
             "(RPS9/RPSP run a few samples behind RPCH by design, so the difference includes that",
             " small time offset; the >12 kHz column is the clean measure of what each mode does)"]
    for r in report:
        def cell(mn):
            return ("   identical     " if r[f"{mn}_identical"]
                    else f"{r[f'{mn}_diff_dbfs']:7.1f} {r[f'{mn}_diff_rel']:7.1f}  ")
        lines.append(f"{r['signal']:<11} {r['ratio']:<6} {r['sig_dbfs']:6.1f}  {cell('RPS9')}  {cell('RPSP')}"
                     f"  {100*r['RPCH_hf']:5.2f}%  {100*r['RPS9_hf']:5.2f}%  {100*r['RPSP_hf']:5.2f}%")
    text = "\n".join(lines)
    print(text)
    (OUTDIR / "REPORT.txt").write_text(text + "\n")
    print(f"\nWAVs in {OUTDIR}/  ({{signal}}_{{ratio}}_{{mode}}.wav)")


if __name__ == "__main__":
    main()
