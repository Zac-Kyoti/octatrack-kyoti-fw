# KYOTI + BLACKPYRAMIDS_303 — scope (2026-10-14)

Can BLACKPYRAMIDS_303 join KYOTI V1.4? Yes, but not as it stands: it collides with
SIDECHAIN_COMPRESSOR in DSP memory. The author chose (2026-10-14) to move SIDE-CHAIN's DSP code and
key bus out of the way and keep every effect (§3). Nothing else blocks it.

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

## 3. The plan (the author's choice, 2026-10-14): SIDE-CHAIN's DSP out of SPRING, every effect kept

The first draft of this section counted only the shared-window tails and concluded that the key
bus could not fit beside the code. It missed the two **internal** FX2 slots per core. Octabam's
hardware sweeps (`docs/firmware/CHIP.md`) give these facts:
- Y `$4000–$BFFF` holds two 16K-word FX2 slots, and stock never writes past `+$3DA2` in one
  (`stock.SLOT_EXTENT`, DARK REV the highest).
- The shared window `$30000–$3FFFF` aliases P, X and Y. As X or Y it costs no wait states; as P,
  one per fetch.
- Code at `P:$2000+` has run on a unit (octabam's CHORUS relocation).

Each slot's tail, `+$3DA3..+$3FFF`, is 605 words. Per core:

| tail | space | free for us |
|---|---|---|
| `Y:$7DA3–$7FFF` | internal Y, 0 wait | 605 |
| `Y:$BDA3–$BFFF` | internal Y, 0 wait | 605 |
| shared slot 1 (A `$33DA3..`, B `$3BDA3..`) | P/X/Y, 1 wait as P | 93 (SIDE-CHAIN's window takes the last `$200`) |
| shared slot 2 (A `$37DA3..`, B `$3FDA3..`) | P/X/Y, 1 wait as P | 605 (octabam's mailbox sits at `$37F00` in octabam images only) |

The moves:
1. **Key bus and MON** (528 words): Y `$7F0–$9FF` → an internal Y tail, e.g. `Y:$7E00–$7FFF` +
   MON. This costs nothing per access.
2. **SIDE-CHAIN's code** (388 words: sctap, scdet, moncommit and two tables) → shared slot 2's
   tail.
   - The boot clears zero that memory after the upload (A `P:$040` clears `$30000–$37FFF`; B
     clears `$37F00–$3FFFF`). So the code ships as data, in an X record or a pre-boot upload
     (octabam's DRAM-sourced upload), and a boot hook copies it into place after the clear, as
     REPITCH's `zqboot` did.
   - The three `bsr`s that reach it become `jsr`s to the new address.
3. **Cost to measure before building:** one wait state per instruction fetch in sctap (every track,
   every frame) and scdet, on core 0 especially, beside the voice's estimate in
   `reference/BLACKPYRAMIDS_303.md` §4. The tool is SIDE-CHAIN's cross-core bench
   (`tools/dsp56300_xcore/`) with the code at its new address.

What this buys:
- **KYOTI with every feature:** only SPRING REV is given up, by BLACKPYRAMIDS_303. Its voice
  (1,027 words) stays in SPRING's module.
  - The voice cannot move to the shared window: about 300 words per core would be left after
    SIDE-CHAIN's code, and the voice is the hot loop (~400 instructions a sample), so a wait per
    fetch would add roughly 60–80 %.
  - SPRING with BLACKPYRAMIDS_303 is possible only by giving up a different effect for the voice:
    DARK REV (1,067 words, the only other module big enough), or two smaller ones with the voice
    split.
- **SPRING back where BLACKPYRAMIDS_303 is absent:** KYOTI V1.4 and the standalone
  SIDECHAIN_COMPRESSOR lose SPRING today only because SIDE-CHAIN's code is in it.

The other levers, not taken:
- Give up LO-FI or PLATE for SIDE-CHAIN's code: lower risk, but it loses an effect.
- Two KYOTI images.
- Switch the DSP's memory map to 16K of P (OMR `MS`/`MSW`): untested, and it removes Y
  `$A000–$BFFF`, inside the second internal FX2 slot.

Whichever route is taken, SIDE-CHAIN's DSP changes, so it needs a hardware re-test (cross-core
keys, MON), in KYOTI and in its standalone build.

### 3a. Measured on the unit (DIAGW, 2026-10-14): the shared window's P costs a wait state

DIAGW (branch `ot303-diag15`, `140C_303DW`): DIAG8's timer METER, with each loop run from internal P
and from the shared window's P at SIDE-CHAIN's planned tail (A `$37DA3`, B `$3FDA3`). Track
recordings, T2 (core 1) and T6 (core 0), decoded with `tools/ot303/hwrec/meter.py`. In cycles per
sample, 32 loop iterations a sample:

| loop (3 instructions an iteration) | core 1 | core 0 |
|---|---|---|
| nops, internal | 98.2 | 96.9 |
| nops, shared | 195.1 | 193.6 |
| `movem p:` reads of internal P, code internal | 258.2 | 256.9 |
| `movem p:` reads of the shared window, code internal | 290.2 | 288.9 |
| SIDE-CHAIN's copy loop, internal | 98.2 | 96.9 |
| the copy loop, shared | 194.7 | 193.2 |
| `movem p:` of the shared window, code shared | 419.1 | 417.6 |

What this settles:
- Every instruction word fetched from the shared window costs **one extra cycle**, on both cores.
- Every `p:` read of it costs one more. Shared code reading shared P costs about one more again.
- §3's estimate stands: §3's move would add about **+47 cycles/sample per core, always on**
  (`sctap` +43, `moncommit` +3.8), and +18 to +46 per keyed compressor. Every feature without DSP
  code, and BLACKPYRAMIDS_303's voice, add 0.
- (A 417–419 reading between the steps in both recordings matches the mode at 120 and is not
  analysed further.)

### 3b. 2026-10-15: what was done instead

The author chose KYOTI V1.5 = V1.4 + VARISPEED + SIDECHAIN_COMPRESSOR, with only SPRING REV given up
and no BLACKPYRAMIDS_303. SIDE-CHAIN's keybus and MON words moved anyway (WIP), from Y:`$7f0–$9ff`
to Y:`$7df0–$7fff`, the tail of the first internal FX2 slot (§3's move 1, at no cost per access).
The Y collision in §2 is therefore gone; the P collision (both in SPRING's words) stays.

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

§3's plan: DSP relocation, the boot copy hook, the key bus move and the emulator checks (the
cross-core bench, `verify_ot303.py`, SIDE-CHAIN's own checks) take about two days, then one
hardware session for SIDE-CHAIN and the voice together.
