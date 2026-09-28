#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 11: the DSP virtual sampler against its reference model.

    python3 tools/repitch_dsp_engine_check.py [--wav]

Builds the cave exactly as tools/build_repitch_kyoti.py places it (payload A
and B), runs it inside the real stock voice module on dsp56kEmu with the
firmware's streaming protocol (tools/repitch_dsp_engine_probe.cpp), and runs
tools/repitch_engine_model.py on the same input with the same table. Checks:

  * both modes BIT-EXACT with repitch_engine_model.DspExact, the model's
    integer twin (the DSP's arithmetic, step for step);
  * RPSP within -80 dBFS of the model: the DSP's output filter works in Q23
    with halved coefficients and truncating stores, the model in floats, so
    the last bit or two differ; and a tick position computed in 24.24 fixed
    point can put a 12-bit step on the other side of a 1/2048 boundary now
    and then. Reported as the difference level and the share of samples;
  * r0 untouched, r3 advanced 2 words per output, m-registers restored (probe);
  * instructions per 16-sample pass = the engine's cost, reported per sample.
"""
import math
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import repitch_dsp_check as chk          # noqa: E402  (payload table, stock module reader)
import build_sidechain3 as sc3           # noqa: E402
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


def model_run(mode, src24, rint, rfrac, exact=None):
    """Mirror of the probe's protocol. exact=None: the float design model
    (returns floats); exact=(consts, post, fir_rows): the DSP-exact twin
    (returns 24-bit ints)."""
    inc = (rint << 24) | ((rfrac & ~3) | mode)
    tagged = (rfrac & ~3) | mode
    eng = m.Engine(mode) if exact is None else m.DspExact(mode, *exact)
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
        if exact is None:
            table = [(((pos + i * inc) >> 24) % 64, ((pos + i * inc) & 0xFFFFFF) / float(1 << 24)) for i in range(16)]
            out.append(eng.render(table, inc / float(1 << 24)))
        else:
            table = [(((pos + i * inc) >> 24) % 64, (pos + i * inc) & 0xFFFFFF) for i in range(16)]
            out.append(eng.render(table, rint, tagged))
        pos += 16 * inc
    return np.concatenate(out)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    build_probe()
    img = chk.IMG.read_bytes()
    report = []
    worst_cost = 0
    for tag, va, ln, base, hook, stop in chk.PAYLOADS:
        mod, _ = chk.voice_module(img, va, ln, base)
        (WORK / f"voice_{tag}.bin").write_bytes(mod)
        start = sc3.DSP[tag]["cave_org"]
        n = len(dsrc.assemble(0x1000)[0])
        org = start + sc3.DONOR_WORDS - n
        words, syms, c = dsrc.assemble(org)
        _, sp_half, r9_half, pc = dsrc.constants()
        (WORK / f"cave_{tag}.bin").write_bytes(b"".join(w.to_bytes(3, "little") for w in words))
        b0, b1 = sc3.bsr_long(hook, org)
        print(f"payload {tag}: cave {n} words @P:{org:05x}, hook P:{hook:05x}")
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
                    exact = (c, pc, [[v - (1 << 24) if v & 0x800000 else v for v in row]
                                     for row in (m.fir_q23(mode) & 0xFFFFFF).tolist()])
                    o = WORK / f"{tag}_{sname}_{ratio}_{mname}.raw"
                    cnt = WORK / f"{tag}_{sname}_{ratio}_{mname}.cnt"
                    trk = 0x40 if tag == "A" else 0x20
                    r = subprocess.run([str(PROBE), str(WORK / f"voice_{tag}.bin"), f"{base:x}", f"{hook:x}", f"{stop:x}",
                                        str(WORK / f"cave_{tag}.bin"), f"{org:x}", f"{b0:x}", f"{b1:x}",
                                        f"{mode:x}", f"{rint:x}", f"{rfrac:x}", f"{trk:x}", str(inp), str(o), str(cnt)],
                                       capture_output=True, text=True)
                    if r.returncode:
                        sys.exit(f"probe failed ({tag} {sname} {ratio} {mname}): {r.stdout} {r.stderr}")
                    dsp = np.frombuffer(o.read_bytes(), dtype="<i4").astype(np.int64)
                    twin = model_run(mode, src, rint, rfrac, exact=exact).reshape(-1)
                    flt = np.round(model_run(mode, src, rint, rfrac).reshape(-1) * (1 << 23)).astype(np.int64)
                    k = min(len(dsp), len(twin))
                    d = dsp[:k] - twin[:k]
                    frac = float(np.mean(d != 0))
                    dd = (twin[:k] - flt[:k]).astype(float)
                    design_db = 20 * math.log10(max(np.sqrt(np.mean(dd ** 2)), 1e-9) / (1 << 23))
                    costs = [int(v) for v in cnt.read_text().split()]
                    per = float(np.median(costs[1:])) / 16.0
                    worst_cost = max(worst_cost, max(costs[1:]) / 16.0)
                    ok = frac == 0.0
                    report.append((tag, sname, ratio, mname, ok, design_db, frac, per))
                    print(f"  {'PASS' if ok else 'FAIL'} {sname:9} {ratio:<5} {mname}: DSP vs twin "
                          f"{'bit-exact' if ok else f'{100 * frac:.2f}% differ'}; twin vs float design "
                          f"{design_db:6.1f} dBFS; {per:5.1f} instr/sample")
    fails = [r for r in report if not r[4]]
    print(f"\n{len(report) - len(fails)}/{len(report)} PASS (bit-exact); worst pass "
          f"{worst_cost:.1f} DSP instructions per output sample (the one-time table setup excluded)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
