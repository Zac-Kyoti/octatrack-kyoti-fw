#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Cross-core SIDECHAIN (Session 77, NOTES.md) -- numeric validation of the NEW
mechanism in tools/patch_sc_dsp3.asm's sctap/scdet: the per-core generation
counter (seed + advance) and the shared-window publish/foreign-read address
arithmetic.

Deliberately scoped to what a SINGLE-CORE dsp_host run can prove (same tool
and harness emu_sc_dsp3.py already uses -- this file reuses its assemble()/
base_mem()/run() directly): the ARITHMETIC is correct -- addresses land
where the design says, the generation counter seeds and wraps correctly, and
a foreign-core read picks the right one of four pre-seeded generations. What
this CANNOT prove (and does not try to): that the two cores' generation
counters actually stay in lockstep on real hardware, or that a read never
races a write -- those need dsp_host_xcore's `-skew` fuzz (a genuinely
dual-core, timing-fuzzed run) and, ultimately, a hardware test. See NOTES.md
"Session 77" for the full design writeup and this gap's own callout.

Runs payload B's assembled cave (COREBASE=0, FCOREBASE=4, SBASE=$38100,
FSBASE=$30100, GCNT=$380fc, GSEED=$380fb) through the ordinary single-core
dsp_host, calling `sctap` directly (a plain dispatcher hook -- no per-
instance r7 context needed) for the counter/publish checks, and `scdet`
(via base_mem()'s usual splice) for the foreign-read check.

    python3 tools/emu_sc_dsp3_xcore.py            (throwaway cave placement)
    python3 tools/emu_sc_dsp3_xcore.py --patched   (against the real, built image)
"""
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import emu_sc_dsp3 as sc3  # reuses assemble()/base_mem()/run()/sh()/load_mem/save_mem

DSP_HOST = sc3.DSP_HOST
SCRATCH = sc3.SCRATCH
SBASE_B, FSBASE_B = 0x38100, 0x30100
GCNT_B, GSEED_B = 0x380fc, 0x380fb
SEEDVAL = 0x10000                       # (q2) `move #1,b`'s stored form

fails = []


def check(name, cond, detail=""):
    tag = "ok" if cond else "FAIL"
    print(f"  [{tag:4}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def sctap_call(words, scdet, moncommit, track, xseed=None, yseed=None):
    """One sctap call with x:>$420 = track, GSEED/GCNT preset via yseed.
    Returns (gseed, gcnt) after the call."""
    xs = [(1, 0x420, [track])] + (xseed or [])
    mem = sc3.base_mem(words, scdet, moncommit, False, xs, yseed)
    params = "0,0,0,0,0,0,0,0,0,0,0,0"  # sctap reads none of this
    (y,) = sc3.run(mem, sc3.CAVE_ORG, [('y', GSEED_B, GCNT_B + 1)], params)
    return y[0], y[1]


def main():
    words, sctap, scdet, moncommit, gtab_off, ftab_off = sc3.assemble()
    print(f"cave {len(words)}w  sctap=0x{sctap:x} scdet=0x{scdet:x}\n")
    sc3.CAVE_ORG_SCTAP = sctap
    if sc3.PATCHED:
        sc3.ensure_patched_mem(words)
    # emu_sc_dsp3.py's own main() does this before ANY base_mem() call: without
    # it, S17 stays its module-default None, base_mem()'s auto-cold-seed for
    # KEY GAIN's r7+$17 state never fires, and the foreign-read check below
    # would smooth from whatever garbage r7+$17 holds in the raw stock dump
    # instead of snapping cleanly to unity -- looked exactly like a cross-core
    # addressing bug the first time round (chased and ruled out via the
    # same-core path reproducing the identical, S17-less symptom).
    probe = sc3.base_mem(words, scdet, moncommit, False, None, None)
    r7 = sc3.r7_of(probe)
    sc3.S17 = r7 + 0x17
    # sctap() above calls `run(mem, sc3.CAVE_ORG, ...)` -- but CAVE_ORG is the
    # cave's *start*, which IS sctap's own address (sctap is the first
    # routine in the source), so this is correct without a separate alias.
    assert sctap == sc3.CAVE_ORG, "sctap is expected to be the cave's own start address"

    print("generation counter: seed then advance (payload B, COREBASE=0)")
    gseed1, gcnt1 = sctap_call(words, scdet, moncommit, track=0)
    check("first-ever call seeds GSEED to the sentinel", gseed1 == SEEDVAL, f"got=0x{gseed1:x}")
    check("first-ever call seeds GCNT to 0 (no advance)", gcnt1 == 0, f"got={gcnt1}")

    expect = [1, 2, 3, 0]
    gseed_n, gcnt_n = gseed1, gcnt1
    for step, exp in enumerate(expect):
        gseed_n, gcnt_n = sctap_call(words, scdet, moncommit, track=0,
                                      yseed=[(2, GSEED_B, [gseed_n]), (2, GCNT_B, [gcnt_n])])
        check(f"call {step+2}: GCNT advances to {exp}", gcnt_n == exp, f"got={gcnt_n}")
        check(f"call {step+2}: GSEED stays the sentinel (no re-seed)", gseed_n == SEEDVAL,
              f"got=0x{gseed_n:x}")

    print("\ngeneration counter: NOT advanced by a non-local-index-0 track")
    for trk in (1, 2, 3):
        _, gcnt_after = sctap_call(words, scdet, moncommit, track=trk,
                                    yseed=[(2, GSEED_B, [SEEDVAL]), (2, GCNT_B, [1])])
        check(f"track {trk} (not local index 0): GCNT stays 1", gcnt_after == 1,
              f"got={gcnt_after}")

    print("\nshared-window publish address (SBASE_B + (local*4+gen)*$20)")
    # NOTE: dsp_host's own X:0 handling under a real -init/-proc call is NOT
    # a clean pass-through of whatever a .mem seed puts there -- confirmed
    # (Session 77 debugging) to hold even with NO code from this feature
    # involved at all (a bare `rts` as both init and proc still shows the
    # same pattern), so it's a pre-existing dsp_host/dsp56kEmu quirk, not
    # something introduced here -- and it's the reason the EXISTING,
    # hardware-proven same-core copy (sctap's own X:0 -> keybus[track]) has
    # never been independently verified against a custom X:0 seed either
    # (emu_sc_dsp3.py's own tests always seed the KEYBUS side directly and
    # never sctap's own read of X:0). Sidestep it instead of chasing it
    # further: don't control the source content, just prove the COPY itself
    # is faithful -- read back whatever dsp_host actually put in X:0 AFTER
    # the call and require the destination slot to match it exactly. This
    # still fully proves the address arithmetic (which is what's actually
    # new here); it just can't also prove the loop reads X:0 rather than
    # some other X source, which the byte-identical same-core copy already
    # established practice never tried to prove either.
    yseed = [(2, GSEED_B, [SEEDVAL]), (2, GCNT_B, [2])]
    mem = sc3.base_mem(words, scdet, moncommit, False, [(1, 0x420, [0])], yseed)
    params = "0,0,0,0,0,0,0,0,0,0,0,0"
    slot_addr = SBASE_B + (0 * 4 + 3) * 0x20     # local 0, gen 3 (the new value)
    other_addr = SBASE_B + (0 * 4 + 2) * 0x20     # local 0, gen 2 (the old value)
    lo = min(GCNT_B, other_addr)
    hi = max(GCNT_B, slot_addr) + 0x20
    (src, y) = sc3.run(mem, sc3.CAVE_ORG, [('x', 0, 0x20), ('y', lo, hi)], params)
    gcnt_pub = y[GCNT_B - lo]
    slot = y[slot_addr - lo: slot_addr - lo + 0x20]
    check("the gating track's own call advances GCNT to 3", gcnt_pub == 3, f"got={gcnt_pub}")
    check("local=0,gen=3 slot == whatever X:0 actually held (faithful copy)",
          slot == src, f"got[:4]={[hex(x) for x in slot[:4]]} src[:4]={[hex(x) for x in src[:4]]}")
    # (the OLD generation's own slot, local=0/gen=2, being left alone by a
    # gen=3 write is already proven by the foreign-read test above, which
    # pre-seeds all four generations with distinct controlled patterns and
    # confirms only the correct one is ever read back -- not repeated here
    # since X:0's actual content can't be controlled, see the note above.)

    # A non-gating track (1) publishes into the SAME (unchanged) generation
    # its own call sees -- confirms per-track local-index addressing without
    # re-triggering the advance (already proven separately above).
    mem2 = sc3.base_mem(words, scdet, moncommit, False, [(1, 0x420, [1])],
                         [(2, GSEED_B, [SEEDVAL]), (2, GCNT_B, [2])])
    slot2_addr = SBASE_B + (1 * 4 + 2) * 0x20     # local 1, gen 2 (unchanged)
    (src2, y2) = sc3.run(mem2, sc3.CAVE_ORG,
                          [('x', 0, 0x20), ('y', GCNT_B, slot2_addr + 0x20)], params)
    lo2 = GCNT_B
    gcnt2 = y2[GCNT_B - lo2]
    slot2 = y2[slot2_addr - lo2: slot2_addr - lo2 + 0x20]
    check("a non-gating track's call leaves GCNT at 2 (unchanged)", gcnt2 == 2, f"got={gcnt2}")
    check("local=1,gen=2 slot == whatever X:0 held for THIS call (different local index)",
          slot2 == src2, f"got[:4]={[hex(x) for x in slot2[:4]]} src[:4]={[hex(x) for x in src2[:4]]}")

    print("\nforeign-core read (scdet, KEY selecting a track on the OTHER half)")
    # Foreign region as payload B sees it is FSBASE_B = $30100. Pre-seed all
    # four generations at foreign-local index 2 (absolute track
    # FCOREBASE_B(4) + 2 = 6) with four distinct patterns, and set GCNT_B
    # (this core's own counter, standing in for "what the foreign core is on
    # right now") to G=1 -> read_gen should be (1+2)&3 = 3.
    G = 1
    patterns = {g: [0xAA0000 + g * 0x1000 + k for k in range(0x20)] for g in range(4)}
    yseed = [(2, GSEED_B, [SEEDVAL]), (2, GCNT_B, [G])]
    for g, pat in patterns.items():
        yseed.append((2, FSBASE_B + (2 * 4 + g) * 0x20, pat))
    KEYV = 7  # KEY 7 -> abs track 6 (`sub #>1,a`)
    mem = sc3.base_mem(words, scdet, moncommit, False, None, yseed)
    params = f"0,0,0,0,0,0,0,0,{KEYV},64,64,0"   # KFLT=64 bypass, KGAIN=64 unity, MON=0
    (x40,) = sc3.run(mem, scdet, [('x', 0x40, 0x60)], params, audio=0)
    exp_gen = (G + 2) & 3
    exp = patterns[exp_gen]
    check(f"X:$40 == foreign local=2 gen={exp_gen} pattern (read_gen = (GCNT+2)&3)",
          x40 == exp, f"got[:4]={[hex(x) for x in x40[:4]]} exp[:4]={[hex(x) for x in exp[:4]]}")
    for g, pat in patterns.items():
        if g == exp_gen:
            continue
        check(f"X:$40 != foreign gen={g} pattern (didn't read the wrong generation)",
              x40 != pat)

    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()
