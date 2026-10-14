# KYOTI + BLACKPYRAMIDS_303 — scope (2026-10-14)

Can BLACKPYRAMIDS_303 join KYOTI V1.4? Yes, but not as it stands: it collides with
SIDECHAIN_COMPRESSOR in DSP memory, and the fix needs a decision from the author (§3). Nothing
else blocks it.

## 1. What was checked

- **Byte overlap, image against image** (each FINAL standalone image's delta vs stock, against
  BLACKPYRAMIDS_303's): zero bytes shared with MUTE_MODES, QUANTIZE_LIVE_REC_TOGGLE,
  ERASE_EMPTY_TRIGLESS_LOCKS, RELOAD_FROM_PROJECT, DIRECT_JUMP_KYOTI, REC_TRIG_MUTE and the
  three BATCH_BUGFIXES. **2,020 bytes shared with SIDECHAIN_COMPRESSOR**: SPRING REVERB's FX
  chooser entries (both remove SPRING, the same intent) and SPRING's DSP program module, which
  each of them fills with its own code.
- **ColdFire space:** BLACKPYRAMIDS_303 uses none of the classic cave (`0x400d6500..0x400d7c3c`).
  Its code is a DRAM runtime with its own appended loader and a 16-page arena reserve. KYOTI V1.4
  is ROM-only and carries no loader, so the two do not compete. The KYOTI sandbox would run
  `build_blackpyramids_303.py` unchanged (it has no relocatable caves).
- **BUG_BP303** (the feature with all three bug fixes) is built, pinned and emulator-verified,
  which settles the bug fixes.

## 2. The collision: SPRING REVERB's DSP space, and internal Y

| | SIDECHAIN_COMPRESSOR | BLACKPYRAMIDS_303 |
|---|---|---|
| DSP P, each payload | 388 words in SPRING's module | 1,027 words in SPRING's module (+ DARK REV's 35-word helper moved) |
| SPRING's module | 1,063 words | |
| internal Y | key bus `$800–$9ff` + MON `$7f0` | `$7a5–$feb` (tables and voice state) |
| internal X | — | `$7b24–$7bfb` |
| external | shared window, last `$200` of the FX2 slot (A `$33e00`, B `$3be00`) | — |

- **P:** 388 + 1,027 + 35 = 1,450 words, against SPRING's 1,063, so about 390 words short on
  each core.
- **Y:** the key bus lies inside the voice's Y. Stock Y is free from `$795`, and the voice takes
  almost all of it: only `$f03–$f3f` (61 words) is left, against the key bus's 528.

## 3. Options (the author's call)

1. **Give up a second effect for SIDE-CHAIN's code (lowest risk).** Only DARK REV (1,067),
   FILTER (727), PLATE (594) and LO-FI (537) are big enough on their own; LO-FI or PLATE are
   the realistic donors. SIDE-CHAIN takes the donor's P run the way it takes SPRING's today
   (null dispatch, a NONE page for old projects). Its key bus moves to external Y, into the
   free tail of the second FX2 slot (~605 words from `slot+$3da3`, never written by stock;
   NOTES S115): one wait state per access, a few cycles per track per frame.
2. **Keep every effect: SIDE-CHAIN's code into the FX2-slot tails.** About 605 words per slot,
   two slots per core, and the shared window already takes `$200` of one. Code 388 + key bus 528
   + window 512 = 1,428 against ~1,210 per core, so the key bus must also shrink (stride `$40`
   to `$20`?). The DSP's boot clear at `P:0x40` zeroes the window after upload and has to be
   patched to skip the code. Every P fetch costs a wait state. This is new ground: none of our
   code has run from external P yet.
3. **Two images instead of one:** KYOTI as it is (no BLACKPYRAMIDS_303), plus a KYOTI-303
   flavour without SIDE-CHAIN. No DSP work, but two images to keep pinned.

Whichever option is picked, SIDE-CHAIN's DSP changes inside KYOTI, so KYOTI needs a hardware
test of SIDE-CHAIN again (cross-core keys, MON) as well as of the voice.

## 4. Needed whatever option is picked

- **ERASE_EMPTY_TRIGLESS_LOCKS must skip BLACKPYRAMIDS_303 tracks:** an empty trigless lock is
  a tie there. In KYOTI, ERASE's cave gets the signature test (`'O','T',1` in the track's
  NEIGHBOR bytes, `control.c signed_track`), a few dozen bytes in the proven cave.
- **CPU, core 0:** SIDE-CHAIN's tap runs for every track every frame. Under the heaviest legal FX
  stack a square-wave voice on T5–T8 was already estimated at −75 to −130 cycles a sample
  (`reference/BLACKPYRAMIDS_303.md` §4). Measure SIDE-CHAIN's per-frame cost with the voice in
  the emulator before promising anything beyond the README's existing limit.
- **SPRING's FX-chooser edits:** both features remove SPRING and write identical bytes there;
  KYOTI's SHARED_OK list must allow that pair.

## 5. Estimate

Option 1: a day of DSP and builder work plus emulator checks (SIDE-CHAIN's cross-core bench
`tools/dsp56300_xcore/`, `verify_ot303.py`), then one hardware session. Option 2: about twice
that, with more hardware risk. Option 3: half a day.
