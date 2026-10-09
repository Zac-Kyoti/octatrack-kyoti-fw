#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 DIAG8 METER: decode a recording of a track whose 303 knob sat in the METER band (64-127).
# Each render writes ticks << 7 (timer 0, CLK/2) in its first sample and -(KCNT << 16) in the rest
# (tools/ot303/hwprobe_ev.asm, hq_meng). The ratio is gain-proof: cycles/sample = 2 * ticks / KCNT.
# Prints, per stretch of the recording (the knob held at one mode), the median and the low 10 %.
#   python3 tools/ot303/hwrec/meter.py REC.wav [--win SECONDS]
import sys, wave
import numpy as np


def load(path):
    w = wave.open(path)
    n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    raw = w.readframes(n); w.close()
    if sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int64)
        x = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(x >= 1 << 23, x - (1 << 24), x)
    elif sw == 2:
        x = np.frombuffer(raw, np.int16).astype(np.int64) << 8
    else:
        x = np.frombuffer(raw, np.int32).astype(np.int64) >> 8
    return x.reshape(-1, ch), sr


def renders(x):
    """-> [(sample index, cycles/sample)] for each render whose ruler reads true"""
    out = []
    pos = np.nonzero(x > 0)[0]
    for k, i in enumerate(pos):
        j = pos[k + 1] if k + 1 < len(pos) else len(x)
        n = j - i
        rest = x[i + 1:j]
        if n > 16 or (n > 1 and not np.all(rest == rest[0])):
            continue
        if n > 1:
            g = -rest[0] / (n << 16)              # the ruler: the path's gain (1.0 = bit-exact)
            if not 0.2 < g < 5:
                continue
        else:
            g = 1.0
        out.append((i, 2.0 * (x[i] / g) / 128.0 / n))
    return out


def main():
    path = sys.argv[1]
    win = float(sys.argv[sys.argv.index('--win') + 1]) if '--win' in sys.argv else 0.5
    x, sr = load(path)
    for c in range(x.shape[1]):
        r = renders(x[:, c])
        print(f'channel {c}: {len(r)} renders decoded')
        if not r:
            continue
        idx = np.array([a for a, _ in r]); cyc = np.array([b for _, b in r])
        step = int(win * sr)
        last = None
        for t0 in range(0, len(x), step):
            m = (idx >= t0) & (idx < t0 + step)
            if m.sum() < 20:
                continue
            v = np.sort(cyc[m])
            med, low = v[len(v) // 2], v[len(v) // 10]
            line = f'  {t0 / sr:7.2f} s  n {m.sum():5d}  median {med:8.1f}  low10% {low:8.1f}  max {v[-1]:9.1f}'
            if last is None or abs(med - last) > 0.02 * max(med, 1):
                print(line)
            last = med


if __name__ == '__main__':
    main()
