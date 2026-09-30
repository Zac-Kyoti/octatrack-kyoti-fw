#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 14: the DSP virtual sampler against its reference model.

    python3 tools/repitch_dsp_engine_check.py

Builds the cave exactly as tools/build_repitch_repeat98_kyoti.py places it (payload A
and B), runs it inside the real stock voice module on dsp56kEmu with the
firmware's streaming protocol (tools/repitch_dsp_engine_probe.cpp; ring frames
the firmware would not have delivered yet are POISONED), and runs
tools/repitch_engine_model.py on the same input with the same table. Checks:

  * both modes BIT-EXACT with repitch_engine_model.DspExact, the model's
    integer twin (the DSP's arithmetic, step for step), driven the way the
    firmware drives it since rev 14: two hook visits per frame (split k /
    16-k), a trig every TRIG_EVERY frames at a varying offset (the per-voice
    flag word, bit 12 -- the frame's second pass (LC = 1) zeroes the ring
    history, RPSP starts clean; an empty pass is mode 0, as on the unit;
    trig offsets include 0, the case rev 14 first missed), and an AMP level that jumps at each trig and decays
    (channel 1/2's input);
  * the twin against the float design, reported as a difference level (a
    tick position computed in 24.24 fixed point can put a 12-bit step on the
    other side of a 1/2048 boundary now and then);
  * MODE SWITCH away and back (RK_MODE_SWITCH): passes N..2N-1 run in RPCH,
    as a user turning TSTR to RPCH and back; the engine's passes stay
    bit-exact with a twin that simply skipped those passes, and the RPCH
    passes are the stock interpolator's output (not ours);
  * r0 untouched, r3 advanced 2 words per output, m-registers restored (probe);
  * instructions per 16-sample pass = the engine's cost, reported per sample;
  * the virtual-ADC response tables against rev 12's targets.
"""
import os
import math
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import repitch_dsp_check as chk          # noqa: E402  (payload table, stock module reader)
import build_sidechain_compressor as sc3           # noqa: E402
import repitch_dsp_src as dsrc           # noqa: E402
import repitch_engine_model as m         # noqa: E402

VEND = ROOT / "vendor/dsp56300"
PROBE = ROOT / "out/repitch_dsp_engine_probe"
WORK = ROOT / "out/repitch_engine_check"
SR = 44100


def build_probe():
    inc = [f"-I{VEND}/source", f"-I{VEND}/source/asmjit/src", "-DDSP56300_DEBUGGER=0", "-DASMJIT_STATIC"]
    libs = [f"{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a",
            f"{VEND}/build/source/dsp56kBase/libdsp56kBase.a",
            f"{VEND}/build/source/asmjit/libasmjit.a"]
    r = subprocess.run(["c++", "-std=c++17", "-O2", *inc, str(ROOT / "tools/repitch_dsp_engine_probe.cpp"),
                        *libs, "-o", str(PROBE)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"probe build failed:\n{r.stderr[-3000:]}")


def as24(x):
    return (np.clip(np.round(x * 32767), -32768, 32767).astype(np.int64) << 8)


def signals(n):
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    sweep = 0.7 * np.sin(2 * np.pi * (50 * t + (15000 - 50) / (2 * t[-1]) * t * t))
    noise = 0.3 * rng.standard_normal(n)
    drum = np.zeros(n)
    for s in range(0, n, SR // 4):
        e = min(n, s + SR // 8)
        tt = np.arange(e - s) / SR
        drum[s:e] += 0.8 * np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-tt * 30)) / SR) * np.exp(-tt * 12)
        drum[s:e] += 0.3 * rng.standard_normal(e - s) * np.exp(-tt * 40)
    loud = np.clip(1.2 * np.sin(2 * np.pi * 440 * t), -0.999, 0.999)       # full scale: the limiter path
    return {"sweep": (sweep, np.roll(sweep, 17)), "noise": (noise, np.roll(noise, 5)),
            "drum": (drum, np.roll(drum, 9)), "fullscale": (loud, -loud)}


TRIG_EVERY = 37


def schedule(nframes):
    """Per frame (k, flags, level): a trig every TRIG_EVERY frames at offset
    k = 5 x (trig number) mod 16, k kept afterwards (the firmware keeps a
    mid-frame start's split, measured); level = 0.95 at each trig, falling
    linearly to 0 over 50 frames (the OT's AMP stage ramps linearly)."""
    out, k, lev = [], 0, 0.0
    for f in range(nframes):
        trig = f % TRIG_EVERY == 3
        if trig:
            k = (5 * (f // TRIG_EVERY)) % 16
            lev = 0.95
        else:
            lev = max(0.0, lev - 0.95 / 50)
        out.append((k, (0x1000 if trig else 0) | (k << 8), int(round(lev * (1 << 23)))))
    return out


def model_run(mode, src24, rint, rfrac, exact=None, skip=(), sched=None):
    """Mirror of the probe's protocol. exact=None: the float design model
    (returns floats); exact=(consts, fir_rows): the DSP-exact twin (returns
    24-bit ints). Frames in `skip` are not rendered (the track is in RPCH):
    they come back as zeros and leave the engine's state alone."""
    inc = (rint << 24) | ((rfrac & ~3) | mode)
    tagged = (rfrac & ~3) | mode
    eng = m.Engine(mode, ch12=dsrc.CH12) if exact is None else m.DspExact(mode, *exact, ch12=dsrc.CH12)
    frames = len(src24) // 2
    x = np.stack([src24[0::2], src24[1::2]], 1)
    if exact is None:
        x = x / float(1 << 23)
    out, pos, written = [], 0, 0
    while True:
        last = pos + 15 * inc                        # as the probe
        need = (last >> 24) + 1 + (1 if last & 0xFFFFFF else 0)
        if need + 1 > frames:
            break
        if need > written:
            eng.fill(written, x[written:need])
            written = need
        f = len(out)
        k, flags, level = sched[f] if sched and f < len(sched) else (0, 0, 0)
        if f in skip:
            out.append(np.zeros((16, 2), dtype=np.int64))
        else:
            parts = []
            for (i0, i1), lc in (((0, k), 2), ((k, 16), 1)):
                if i1 == i0:
                    continue                          # an empty pass is mode 0 on the unit: stock
                if exact is None:
                    table = [(((pos + i * inc) >> 24) % 64, ((pos + i * inc) & 0xFFFFFF) / float(1 << 24))
                             for i in range(i0, i1)]
                    parts.append(eng.render(table, inc / float(1 << 24), bool(flags & 0x1000),
                                            level / float(1 << 23), lc))
                else:
                    table = [(((pos + i * inc) >> 24) % 64, (pos + i * inc) & 0xFFFFFF) for i in range(i0, i1)]
                    parts.append(eng.render(table, rint, tagged, flags, level, lc))
            out.append(np.concatenate(parts))
        pos += 16 * inc
    return np.concatenate(out)


def run_probe(tag, base, hook, stop, org, b0, b1, mode, rint, rfrac, inp, o, cnt, env=None):
    trk = 0x40 if tag == "A" else 0x20
    e = dict(os.environ if env is None else env, RK_XDATA=str(WORK / f"xdata_{tag}.txt"),
             RK_SCHED=str(WORK / "sched.txt"))
    r = subprocess.run([str(PROBE), str(WORK / f"voice_{tag}.bin"), f"{base:x}", f"{hook:x}", f"{stop:x}",
                        str(WORK / f"cave_{tag}.bin"), f"{org:x}", f"{b0:x}", f"{b1:x}",
                        f"{mode:x}", f"{rint:x}", f"{rfrac:x}", f"{trk:x}", str(inp), str(o), str(cnt)],
                       capture_output=True, text=True, env=e)
    if r.returncode:
        sys.exit(f"probe failed ({o.name}): {r.stdout} {r.stderr}")
    return np.frombuffer(o.read_bytes(), dtype="<i4").astype(np.int64)


SCHED = None


def exact_for(mode, c):
    return (c, [[v - (1 << 24) if v & 0x800000 else v for v in row]
                for row in (m.fir_q23(mode) & 0xFFFFFF).tolist()])


def switch_check(tag, base, hook, stop, org, b0, b1, c, src):
    """Away (RPCH) and back: N passes in the mode, N in RPCH, the rest in the
    mode again. Returns [(label, ok, detail)]."""
    N = 40
    res = []
    x = src / float(1 << 23)
    for ratio in (0.75, 1.5):
        inc = int(round(ratio * (1 << 24)))
        rint, rfrac = inc >> 24, inc & 0xFFFFFF
        for mode, mname in ((1, "RPS9"), (2, "RPSP")):
            o = WORK / f"{tag}_switch_{ratio}_{mname}.raw"
            dsp = run_probe(tag, base, hook, stop, org, b0, b1, mode, rint, rfrac, WORK / "drum.raw", o,
                            WORK / "switch.cnt", env={**os.environ, "RK_MODE_SWITCH": str(N)})
            twin = model_run(mode, src, rint, rfrac, exact=exact_for(mode, c),
                             skip=range(N, 2 * N), sched=SCHED).reshape(-1, 16, 2)
            dsp = dsp.reshape(-1, 16, 2)
            k = min(len(dsp), len(twin))
            eng = [i for i in range(k) if not N <= i < 2 * N]
            same = all(np.array_equal(dsp[i], twin[i]) for i in eng)
            # RPCH passes: the stock 2-tap interpolator at the same positions (not our
            # engine, which would be c+1 frames late and 12-bit): within a few LSBs
            tagged = (rint << 24) | ((rfrac & ~3) | mode)
            err = 0.0
            for i in range(N, 2 * N):
                for j in range(16):
                    p = (i * 16 + j) * tagged
                    kf, fr = p >> 24, (p & 0xFFFFFF) / float(1 << 24)
                    want = x[2 * kf:2 * kf + 2] * (1 - fr) + x[2 * kf + 2:2 * kf + 4] * fr
                    err = max(err, float(np.max(np.abs(dsp[i, j] / float(1 << 23) - want))))
            ok = same and err < 2 ** -14
            res.append((f"{tag} drum {ratio} {mname}", ok,
                        f"engine passes {'bit-exact' if same else 'DIFFER'} across the switch; "
                        f"RPCH passes vs a 2-tap interpolator max {20 * math.log10(max(err, 1e-12)):.0f} dBFS"))
    return res


def main():
    global SCHED
    WORK.mkdir(parents=True, exist_ok=True)
    build_probe()
    SCHED = schedule(4000)
    (WORK / "sched.txt").write_text("".join(f"{k:x} {f:x} {lv:x}\n" for k, f, lv in SCHED))
    img = chk.IMG.read_bytes()
    report = []
    switches = []
    cost = {"RPS9": [], "RPSP": []}
    worst_cost = 0
    for tag, va, ln, base, hook, stop in chk.PAYLOADS:
        mod, _ = chk.voice_module(img, va, ln, base)
        (WORK / f"voice_{tag}.bin").write_bytes(mod)
        n = len(dsrc.assemble(0x1000, tag)[0])
        org = dsrc.cave_org(tag, n)
        words, syms, c = dsrc.assemble(org, tag)
        (WORK / f"cave_{tag}.bin").write_bytes(b"".join(w.to_bytes(3, "little") for w in words))
        (WORK / f"xdata_{tag}.txt").write_text("".join(f"{a:x} {w:x}\n" for a, w in sorted(dsrc.x_data(tag).items())))
        b0, b1 = sc3.bsr_long(hook, org)
        print(f"payload {tag}: cave {n} words @P:{org:05x} (ends below DARK REV's routine), hook P:{hook:05x}")
        n_frames = int(1.0 * SR)
        for sname, (L, R) in signals(n_frames).items():
            src = np.empty(2 * n_frames, dtype=np.int64)
            src[0::2], src[1::2] = as24(L), as24(R)
            inp = WORK / f"{sname}.raw"
            inp.write_bytes(src.astype("<i4").tobytes())
            for ratio in (1.0, 0.75, 1.5, 0.5, 1.99):
                inc = int(round(ratio * (1 << 24)))
                rint, rfrac = inc >> 24, inc & 0xFFFFFF
                for mode, mname in ((1, "RPS9"), (2, "RPSP")):
                    exact = exact_for(mode, c)
                    o = WORK / f"{tag}_{sname}_{ratio}_{mname}.raw"
                    cnt = WORK / f"{tag}_{sname}_{ratio}_{mname}.cnt"
                    dsp = run_probe(tag, base, hook, stop, org, b0, b1, mode, rint, rfrac, inp, o, cnt)
                    twin = model_run(mode, src, rint, rfrac, exact=exact, sched=SCHED).reshape(-1)
                    flt = np.round(model_run(mode, src, rint, rfrac, sched=SCHED).reshape(-1) * (1 << 23)).astype(np.int64)
                    k = min(len(dsp), len(twin))
                    d = dsp[:k] - twin[:k]
                    frac = float(np.mean(d != 0))
                    dd = (twin[:k] - flt[:k]).astype(float)
                    design_db = 20 * math.log10(max(np.sqrt(np.mean(dd ** 2)), 1e-9) / (1 << 23))
                    costs = [int(v) for v in cnt.read_text().split()]
                    per = float(np.median(costs[1:])) / 16.0
                    worst_cost = max(worst_cost, max(costs[1:]) / 16.0)
                    cost[mname].append(per)
                    ok = frac == 0.0
                    report.append((tag, sname, ratio, mname, ok, design_db, frac, per))
                    print(f"  {'PASS' if ok else 'FAIL'} {sname:9} {ratio:<5} {mname}: DSP vs twin "
                          f"{'bit-exact' if ok else f'{100 * frac:.2f}% differ'}; twin vs float design "
                          f"{design_db:6.1f} dBFS; {per:5.1f} instr/sample")
        src = np.empty(2 * n_frames, dtype=np.int64)
        L, R = signals(n_frames)["drum"]
        src[0::2], src[1::2] = as24(L), as24(R)
        for label, ok, detail in switch_check(tag, base, hook, stop, org, b0, b1, c, src):
            switches.append(ok)
            print(f"  {'PASS' if ok else 'FAIL'} mode switch away/back, {label}: {detail}")
    fails = [r for r in report if not r[4]]
    print(f"\n{len(report) - len(fails)}/{len(report)} PASS (bit-exact); mode switch "
          f"{sum(switches)}/{len(switches)} PASS; worst pass {worst_cost:.1f} DSP instructions per "
          f"output sample (the one-time table setup excluded)")
    for k, v in cost.items():
        print(f"  {k}: median {np.median(v):.1f} instr/sample, range {min(v):.1f}-{max(v):.1f} over the 40 cases")
    print("\nvirtual-ADC responses (the Q23 tables as the DSP holds them):")
    print(m.response_report())
    sys.exit(1 if fails or not all(switches) else 0)


if __name__ == "__main__":
    main()
