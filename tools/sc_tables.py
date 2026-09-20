#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Side-chain step-3 DSP coefficient tables -- shared by build_sidechain3.py and
emu_sc_dsp3.py so the two never drift.

Both tables are 24-bit words appended to the assembled cave (patch_sc_dsp3.asm)
by the build; the .asm reads them with `move p:(r1+n1),x1` at @GTAB@ / @FTAB@.

KEY GAIN  (16 entries, index = KGAIN >> 3, KGAIN 0..127, 64 = unity)
  stored value = (gain / 64) in Q23, so the cave does  mpy ; asl #6  -> * gain.
  gain law: dB = (KGAIN - 64) * (24 / 64)  ->  ~ +/-24 dB, ~3 dB per index step.

KEY FLT  (32 entries, exp-spaced cutoff FC_LO..FC_HI)
  stored value = a = 1 - exp(-2*pi*fc/FS)  in Q23 (Session 76 continued,
  3rd pass -- one-pole EMA tracker: tracker += a*(in-tracker); LP output =
  tracker, HP output = in-tracker. Replaces the old 2-pole Chamberlin SVF --
  see patch_sc_dsp3.asm's KEY FLT header for why: a one-pole's feedback is
  coefficient-weighted, so it can reach genuine near-unity at LP's edge with
  no q/stability ceiling, unlike the old SVF).
  LP: index = KFLT >> 1            (KFLT 0..63  -> fc FC_LO..FC_HI, 0 = tightest)
  HP: index = (KFLT - 64) >> 1     (KFLT 65..127 -> fc FC_LO..FC_HI)

KEY FLT edge overrides (not table entries -- literals patched into the .asm
via @LPEDGE@/@HPEDGE@, checked once per call, before the loop): FTAB[31]
(2200 Hz) is also HP's own deepest setting and FTAB[0] (40 Hz) is also LP's
own deepest setting -- shared table, can't push either toward "transparent"
without detuning the other mode's tuned end. So the LP/HP step closest to
OFF (idx 31 / idx 0) skips the FTAB fetch entirely and uses these instead:
  LP_EDGE = Q23 ceiling (~unity, closest this format allows to a true
            identity tracker -- always stable for a one-pole, no ceiling).
  HP_EDGE = a at ~8 Hz (near-DC; a highpass can't reach true identity even
            at its most transparent -- it must always track something to
            subtract -- but this is slow/small enough that reusing stale
            tracker state decays gently rather than snapping).
"""
import math

FS = 44100.0
FC_LO = 40.0
FC_HI = 2200.0
FC_HP_EDGE = 8.0
Q23 = 1 << 23
GAIN_N = 16
FLT_N = 32


def _q23(x):
    v = int(round(x * Q23))
    return max(-Q23, min(Q23 - 1, v)) & 0xFFFFFF


def gain_table():
    t = []
    for idx in range(GAIN_N):
        kgain = idx * 8                      # bucket base (KGAIN >> 3 == idx)
        db = (kgain - 64) * (24.0 / 64.0)
        g = 10.0 ** (db / 20.0)
        t.append(_q23(g / 64.0))
    return t


def _one_pole_a(fc):
    return 1.0 - math.exp(-2.0 * math.pi * fc / FS)


def flt_table():
    t = []
    for idx in range(FLT_N):
        fc = flt_cutoff_hz(idx)
        t.append(_q23(_one_pole_a(fc)))
    return t


def flt_cutoff_hz(idx):
    return FC_LO * (FC_HI / FC_LO) ** (idx / (FLT_N - 1))


def lp_edge():
    return Q23 - 1


def hp_edge():
    return _q23(_one_pole_a(FC_HP_EDGE))


if __name__ == "__main__":
    g, f = gain_table(), flt_table()
    print("KEY GAIN table (16):")
    for i, v in enumerate(g):
        db = (i * 8 - 64) * (24.0 / 64.0)
        print(f"  [{i:2d}] KGAIN~{i*8:3d}  {db:+6.1f} dB   0x{v:06x}")
    print("\nKEY FLT table (32, one-pole 'a'):")
    for i, v in enumerate(f):
        print(f"  [{i:2d}] fc {flt_cutoff_hz(i):7.1f} Hz   a=0x{v:06x} ({v / Q23:.6f})")
    print(f"\nLP_EDGE  = 0x{lp_edge():06x} (~unity)")
    print(f"HP_EDGE  = 0x{hp_edge():06x} (fc {FC_HP_EDGE:.1f} Hz, a={hp_edge()/Q23:.6f})")
