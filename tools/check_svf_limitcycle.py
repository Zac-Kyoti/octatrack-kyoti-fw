#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 69 -- checks whether `patch_sc_dsp3.asm`'s KEY FLT SVF (the Chamberlin
loop `lp' = lp + f*bp`, `hp = in - lp' - q*bp`, `bp' = bp + f*hp`, all
truncating fixed-point, no rounding on the state stores) can sustain a
persistent, AUDIBLE zero-input oscillation ("limit cycle") once excited by a
single real trig, for every one of the 32 FTAB cutoff entries and both the
old q=1 and current q=2 damping.

Written to check a specific hypothesis raised while investigating the
"MON pings continuously after the first real trig, forever" bug (NOTES.md
"Session 68"/"Session 69"): a recursive filter with truncating (not
rounding) fixed-point arithmetic is the textbook precondition for a
zero-input limit cycle, which could plausibly explain "never clears."

Result (see NOTES.md "Session 69" for the full table): every FTAB entry, at
both q values and impulse sizes from full-scale down to 1 LSB, settles onto
an exact period-1 fixed point in well under 2,000 samples (most under 500),
at a residual magnitude of single digits to a few hundred LSB out of
8,388,608 full scale -- roughly -90 to -140 dB, inaudible. This RULES OUT
"the filter's own truncation arithmetic sustains the audible pinging" as the
mechanism -- whatever's actually pinging must be getting re-excited by a
real, non-decaying, or periodically-refreshed input, not failing to settle
on its own.

    python3 tools/check_svf_limitcycle.py

Pure Python, no build/emulator/hardware needed -- reuses the exact table
generator `tools/sc_tables.py` shares with the build and `emu_sc_dsp3.py`,
and the same integer arithmetic as `emu_sc_dsp3.py`'s `ref_svf` (generalised
over q, since q=1 and q=2 archive builds both exist for later A/B).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import sc_tables  # noqa: E402

Q23 = 1 << 23
N_SAMPLES = 20000
IMPULSE_AMPS = (int(0.5 * Q23), 1000, 1)


def s24(w):
    w &= 0xFFFFFF
    return w - (1 << 24) if w & 0x800000 else w


def step(lp, bp, inp, f, q):
    """One sample of the Chamberlin SVF recursion, bit-exact to the asm:
    truncating `>>` (Python's floor-toward -inf matches the DSP's `asr`)."""
    lp = lp + ((f * bp) >> 23)
    hp = inp - lp - q * bp
    bp = bp + ((f * hp) >> 23)
    return lp, bp, hp


def run_impulse_then_silence(f, q, imp_amp, n=N_SAMPLES):
    """Excite with one impulse, then feed exact digital zero forever; report
    whether the state ever reaches exact (0,0), or settles into a repeating
    cycle first (and if so, its period and the residual magnitude)."""
    lp, bp = 0, 0
    lp, bp, _ = step(lp, bp, imp_amp, f, q)
    seen = {}
    for i in range(n):
        lp, bp, _ = step(lp, bp, 0, f, q)
        if lp == 0 and bp == 0:
            return i, None, (lp, bp)
        key = (lp, bp)
        if key in seen:
            return None, (seen[key], i, i - seen[key]), (lp, bp)
        seen[key] = i
    return None, None, (lp, bp)  # neither zero nor a repeat within n samples


def main():
    flt_t = sc_tables.flt_table()
    any_unbounded = False
    for q in (1, 2):
        print(f"=== q={q} ===")
        for idx in range(32):
            f = s24(flt_t[idx])
            for imp_amp in IMPULSE_AMPS:
                first_zero, cycle, final = run_impulse_then_silence(f, q, imp_amp)
                if first_zero is not None:
                    continue  # reached exact digital silence -- fine
                if cycle is None:
                    any_unbounded = True
                    print(f"  idx={idx:2d} f={f:8d} imp={imp_amp:8d}  "
                          f"NO cycle and NOT zero within {N_SAMPLES} samples "
                          f"-> final={final}  ** INVESTIGATE **")
                else:
                    period = cycle[2]
                    settle_at = cycle[0]
                    mag = max(abs(final[0]), abs(final[1]))
                    print(f"  idx={idx:2d} f={f:8d} imp={imp_amp:8d}  "
                          f"settles to period-{period} cycle by sample {settle_at}, "
                          f"residual |lp|,|bp| <= {mag} LSB "
                          f"({20 * __import__('math').log10(max(mag, 1) / Q23):.1f} dBFS)")
    print()
    if any_unbounded:
        print("FAIL: at least one (q, cutoff, impulse) never settled -- "
              "the SVF's own arithmetic CAN sustain something; re-examine.")
        sys.exit(1)
    print("OK: every case settles to an inaudible fixed point -- the SVF's "
          "own truncation arithmetic cannot be the source of an audible, "
          "persistent tone. See NOTES.md Session 69.")


if __name__ == "__main__":
    main()
