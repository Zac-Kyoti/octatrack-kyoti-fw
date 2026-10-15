#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 item 2, the whole chain against Open303 (tools/ot303/chain_check.cpp): renders one acid line
# as Open303, as the approved voice with Open303's note logic (twinv), and as the machine (ours:
# params.c's words, the DSP host's event rules), then compares them (tools/ot303/compare.py's
# metrics: null residual, STFT log-magnitude mean / p95 dB) and per step (the level of each
# 16th, ours against twinv).
#   python3 tools/ot303/chain_check.py
import pathlib, subprocess, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'ot303'))
import compare  # noqa: E402

SRC = ROOT / 'out/ot303/refs/Open303/Source/DSPCode'
OUT = ROOT / 'out/ot303/chain'
CF = ROOT / 'tools/ot303/cf'
STEPS = 5088


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cpps = sorted(str(p) for p in SRC.glob('*.cpp'))
    obj = OUT / 'params.o'
    subprocess.run(['clang', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror', f'-I{CF}', '-c', str(CF / 'params.c'), '-o', str(obj)], check=True)
    exe = OUT / 'chain_check'
    subprocess.run(['clang++', '-O2', '-std=c++17', '-w', f'-I{SRC}', f'-I{CF}', f'-I{ROOT}/tools/ot303', str(ROOT / 'tools/ot303/chain_check.cpp'),
                    str(obj), *cpps, '-o', str(exe)], check=True)
    subprocess.run([str(exe), str(OUT)], check=True)
    ref, tv, ours = (compare.load(OUT / f'{n}.f32') for n in ('open303', 'twinv', 'ours'))

    def metrics(x, r):
        xs, _ = compare.align(x, r)
        null = 20 * np.log10(np.sqrt(np.mean((xs - r) ** 2)) / np.sqrt(np.mean(r ** 2)))
        a, b = compare.stft_db(xs), compare.stft_db(r)
        m = b > b.max() - 60
        d = np.abs(a - b)[m]
        return null, d.mean(), np.percentile(d, 95)
    ok = True
    for name, x, r in (('ours vs twinv', ours, tv), ('twinv vs open303', tv, ref), ('ours vs open303', ours, ref)):
        null, mean, p95 = metrics(x, r)
        print(f'{name:18}: null {null:6.1f} dB, spectrum mean {mean:.2f} dB, p95 {p95:.2f} dB')
        if name == 'ours vs twinv':
            ok &= null < -50 and p95 < 1.0
    # per step: ours against twinv (the event rules), dB of each 16th's RMS
    n = len(tv) // STEPS
    lv = lambda x: np.array([20 * np.log10(np.sqrt(np.mean(x[i * STEPS:(i + 1) * STEPS] ** 2)) + 1e-12) for i in range(n)])
    d = lv(ours) - lv(tv)
    print(f'per 16th, ours - twinv: worst {np.max(np.abs(d)):.3f} dB (step {int(np.argmax(np.abs(d)))})')
    ok &= np.max(np.abs(d)) < 0.5
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
