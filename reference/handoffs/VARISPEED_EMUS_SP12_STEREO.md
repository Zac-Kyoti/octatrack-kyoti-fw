# VARISPEED_EMUS: SP12 (RPSP) in full stereo

Branch `vem-dsp`. Not flashed, not promoted, not pushed. On 2026-10-15 the user decided to move
SP12 from mid/side back to full stereo. The mid/side design is kept at the tag
`ref/sp12-midside-vem7`, described in `SP12_MIDSIDE_REFERENCE.md`. S950 (RPS9) and the OT path
are **bit-identical** to before.

**Test build:** `KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py 140C_VEM8D` →
`out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx`, sha256
`ba4b1c449f2142f1b14ab3c78781107e7e780e055b985c71b9707d1f2d1d877a` (OS VERSION `140C_VEM8D`;
`mainos_varispeed_emus.bin` `3587a757…`). It is a test label and is **not flashed**. Its
ColdFire half is whatever this branch has, so it tests the DSP change only. The load guard's
`VG_SP12` in it is still 218 (see "The guard" below).

## The design

**Each channel, L and R, goes through the whole SP-1200 path on its own:**
- the 8-tap virtual ADC on the SP's 26.04 kHz grid, with the same per-tick truncating read
  shift (`PSP_LAG × phi`);
- 12 bits;
- the band-limited 10-tap render to 44.1 kHz;
- raw, as outputs 7/8, with no channel filter.

**What both channels share:**
- one SP clock and one tick schedule (`tau`, `phi`);
- one trig handling: the 16 ring frames behind a new sound become silence, and the slot starts
  clean at a trig or on first use (tag `$5A5A0A`).

**All of the mid/side machinery is gone from the kernel and the twin:**
- the mid sum;
- the side's clean read and its interpolation;
- `MS_SIDE_DELAY`, `KD`, `SIDEC`;
- `LS`, `LSSH`, `LSMUL`;
- the side average;
- `MS_OUT`'s branches.

**One detail of the design changed:** a tick now reads from the *current* output's position less
one increment, `p_i − (1 − u)·r`, instead of from a stored "previous output" position. In exact
arithmetic `p_i − r` is `p_{i−1}`. So:
- no previous position is kept, and none can go stale;
- the per-pass resync (a jump of more than 2 frames) is gone;
- the only place the result can differ from before is the first tick after a clean start. That
  tick now reads one increment before the sound, which is silence after the trig clear.

Measured against the old model's rev-16 stereo path (`Engine(ms=False)` at `2c87392`), over the
engine check's signals and trig schedule:
- at 0.5, 0.75, 1.5 and 1.99× the outputs are identical (−318 dBFS);
- at 1.0× they differ by −90 to −97 dBFS RMS (that first tick).

**The render in "full form" (the kernel's main saving).** A ring slot holds what its output will
be, ÷ 4:
- the held step at the time the slot was last read, plus every later tick's share;
- an output is 4 × its slot; the slot is then reset to the current held step ÷ 4;
- each tick adds `step/2 × (1 − Gc)/2` through the table `T' = T + 1/2`.

This is the rev-13 render (held + residuals) to the bit:
- `held/4` is exact, since the steps are 12-bit;
- `(T + 1/2)·dh >> 23 = (T·dh >> 23) + dh/2` exactly, since `dh = step/2` is a multiple of 2^11.

The output therefore needs no add of the held step, and the out block shrinks from 25
instructions to 7.

**One rounding is finer than before.** A tick's share of its *own* output (tap 0) is never
stored. The kernel keeps the slot plus that share in the accumulator for the out block, for both
channels alike. So it is not floored to the slot's ¼ scale: the output is
`lim(4·slot + (w·dh >> 21))`.

## Layout

**P:** 396 words, down from 429. They end right below DARK REV's routine:
- payload A: `P:0x13fa..0x1585`;
- payload B: `P:0x11ba..0x1345`.

The first run has 432 words with SIDECHAIN's 388 kept free, so **36 words are spare**. The
builder asserts every placement, unchanged.

| part | words (before) |
|---|---|
| `zqrp` / `zqtok` / trig | 40 (40) |
| RPS9 | 60 (60), unchanged |
| RPSP | 198 (231) |
| `zqboot` | 22 (22) |
| `zqinit` | 76 (76) |

SPRING's ~208 free words after DARK REV's routine are still unused. `zqboot` and `zqinit` did
not need to move.

**X:** 465 words, the same size and runs as before:
- run 1 (A `X:0x89a4`, B `X:0x8464`) now holds `T'[0..80]`;
- run 2 is unchanged: RPSP's half-rows, then RPS9's, tap-major.

**Y:** the range is still `$A00–$FFF`. Y layout is now 7, `TAGVAL` `$F2E5C5`, `TAGSP`
`$5A5A0A`. Each RPSP slot (`STBASE + x:$418`, `$20` words) holds:

| offset | contents |
|---|---|
| `$00–$13` | the stereo ring: 2 × 10 words, L and R interleaved. Modulo 20 (`m7 = 19`) in the pass, on a 32-aligned base. |
| `$14` RF | frac(r), Q24, with the mode tag (this pass's) |
| `$15` PHI | the SP's accumulator fraction, Q24 |
| `$16` RH | r × 2^23, unsigned (this pass's) |
| `$17` H4L, `$18` H4R | the held steps ÷ 4 |
| `$19` TAU | tau − 1, Q23 mod 2^24: bit 23 set = a tick in this interval |
| `$1A` RW | the next output's slot address |
| `$1B` TAG | |
| `$1C–$1E` | free; track 3's `$1F` is `TABTAG` |

`SPTAB`, `R9TAB` and `BTAB` sit where they were.

**BTAB's rows** now hold the ten `(T', D)` pairs in the order a tick applies them. Pair `i` is tap
`9 − i`, segment `iR + j`. A tick walks the row up with `r1` and the ring down with `r7`.
- The row address is `((u − 1) >> 14) & $FE0`, which equals `$E00 + 32j`.
- This is asserted in `repitch_dsp_src.constants`: `BTAB = $E00`, 32-word rows, `R = 16`.

`tau` is Q23 (−1) instead of Q20. `PSPQ23` is `PSPQ20 << 3`, so the tick schedule is the same
as before to the bit.

## The kernel (`tools/patch_repitch_dsp.asm`, RPSP)

**Per output, 7 instructions:**
- `jclr`;
- `asl` ×4, which carry:
  - both slot resets;
  - out L with the next L read ahead;
  - `tau −= 1`;
- an XY move: out R with the next R read ahead;
- `(r5)+`.

**Per tick, 121 instructions:**

| part | instructions |
|---|---|
| tick time / phi / `(u − 1)·r` (`mpysu`) / read shift / position | 14 |
| address and phase, with the first sample and coefficient | 12 |
| ADC, both channels | 16 |
| steps (12-bit, ÷ 4, stored, `dh`), row and fraction, `tau += PSP` | 18 |
| render prologue | 3 |
| render: 9 taps × 6, then tap 0's 4 | 58 |

The render's 6 instructions per tap is the Y-bus bound: `T'`, `D`, and the read and write of L
and of R, all in Y. The weight register is reused for `D`, so `fr`, `dhL` and `dhR` stay in
registers.

**Disciplines kept from the last pass:**
- parallel moves on every 1-word ALU op that has a move to do;
- no displaced access in the hot loop. `r6` walks the state cyclically and ends with
  `(r6)−n6`, `n6 = 3`;
- everything unrolled;
- no address register used right after it is loaded.

The ADC and the render both reuse registers that the stall check covers.

## Gates (all pass)

| gate | result |
|---|---|
| `python3 tools/repitch_dsp_engine_check.py` | 80/80 bit-exact with the new `DspExact`; mode switch 8/8 |
| `python3 tools/repitch_dsp_octabam_check.py` | 264/264; octabam's own `dsp_asm` assembles the generated `rpk_dsp.asm` to the same 396 words |
| `python3 tools/repitch_dsp_boot_check.py out/mainos_varispeed_emus.bin` | PASS, fresh `140C_VEM8D` build: +3,598 boot instructions, memory outside `Y:$A00–$FFF` identical, tables and tag as the model |
| `python3 tools/repitch_dsp_stall_check.py` | PASS |
| `python3 tools/repitch_dsp_octabam.py --check` | current |

**S950 (RPS9) is unchanged:**
- In the engine check, all 40 RPS9 cases are bit-exact with the same twin code as before.
- **Before/after run:** all 44 RPS9 DSP output files of the engine check, saved at `2c87392`
  (40 cases plus the 4 RPS9 mode-switch runs), are byte-identical after the change.
- Its prices are unchanged: 47.00 / 50.00 instructions per sample, 52.00 / 56.25 cycles,
  `~hw` 98.9.

**Twin against the float design:** −117.5 to −126.3 dBFS RMS on all 20 cases. Mid/side ranged
from −57 to −138.

The engine check now limits the design's output to the 24-bit word the DSP writes. Unlimited,
the render's overshoot on the full-scale and drum signals (up to 7 % of full scale) reads −50 to
−71 dBFS. That is the DAC word clipping, not an arithmetic difference. Mid/side never showed it:
its mid of the anti-phase full-scale signal was zero.

## Costs, before (mid/side, VEM7) and after (stereo)

`tools/repitch_dsp_cost.py`: both payloads; the four signals × 0.5, 0.75, 1, 1.5, 1.99×; a trig
every 37 frames. Prices are in-cave, per output sample.

| SP12 per voice | mid/side | stereo | change |
|---|---|---|---|
| instructions, median | 92.06 | **81.06** | −11.9 % |
| instructions, worst frame | 109.50 | **101.12** | −7.7 % |
| datasheet cycles, median | 114.00 | **96.56** | −15.3 % |
| datasheet cycles, worst frame | 135.75 | **120.19** | −11.5 % |
| profile `~hw`, worst of 0.5–1.99× and payloads A/B | 217.2 | **186.4** | −14.2 % |
| worst frame, in-cave | 1752 instr, 2172 cyc | **1618 instr, 1923 cyc** | |
| worst frame + the two hook `bsr`s | 2182 cyc | **1933 cyc** (120.8 a sample) | −11.4 % |

**Notes on these figures:**
- **`~hw` by ratio** (drum, the same for A and B): 184.0 at 0.5×, 186.3 at 0.75×, 186.4 at
  1.0×, 186.3 at 1.5×, 186.4 at 1.99×.
- **The engine check's own figure**, which counts the stock tail of each pass too: 81.8
  instructions per sample median, worst pass 101.9. Mid/side's was 92.8 and 110.2.
- **The octabam form prices the same** (`--form octabam`).
- **The RPCH / stock exit is unchanged:** 6 instructions, 14 cycles in the cave per pass;
  19 with the `bsr`.
- **The worst frame is now also the structural bound.** Mid/side's structural bound was 2198,
  because it had a resync path the suite could not combine with a trig frame. Stereo has no
  resync. The worst frame is a split trig frame with ten ticks and the clean-slot clear, and the
  suite contains it. The one-time `zqinit` is excluded, as before: `zqboot` runs it at boot.

**Where the time goes (profile, drum, A, per output sample):**
- the tick block, 74.5 instructions (121 a tick, 0.59 ticks a sample, plus the pass's own words in that region);
- the out block plus the tick test, 8 (7 instructions, `jclr` priced as 2);
- pass overhead, about 2.

## The guard

**The new `~hw` price is 186.4 per sample, so `VG_SP12` = 187** (was 218, from 217.2). The
per-voice worst frame is 1933 datasheet cycles (was 2182). S950's 910 and RPCH's 38 are
unchanged.

`VG_SP12` lives in `octabam-modules/varispeed-emus/varispeed_emus.s`, which the ColdFire session
owns. **It has not been changed here.** The 140C_VEM8D build still uses 218, which is
conservative (it refuses earlier than needed).

## What changed in the model and the twin

**`tools/repitch_engine_model.py`:**
- `Engine`'s default is `ms=False`. RPSP's stereo path ticks from `p_i − (1 − u)·r`; the
  `prev` / resync is gone.
- `Engine(ms=True)` (`render_ms`, `MS_*`, `side_avg`) is kept only so the old listening-pack
  tools (`repitch_ab_pack.py`, `repitch_ab_speeds.py`) still run. Nothing in the kernel, the
  twin or the gates uses it, and it can be deleted with those tools.

**`DspExact`, rewritten for stereo RPSP:**
- `tau` in Q23 (+= `PSPQ23`, −= 2^23);
- `phi`, and the read shift as before;
- `(u − 1)·r` by `mpysu`, floored;
- per-channel ADC, 12 bits;
- held steps ÷ 4;
- the full-form ring;
- taps applied L−1 first;
- the unfloored tap-0 share.

The mid/side twin, its channel-filter / channel 1/2 code and `cutoff` / `dyn_coef` are gone.

**`tools/repitch_dsp_src.py`:**
- `render_tp()`; `render_half()` is now `T'`;
- constants: `PSPQ23`, `RINGN` / `RINGM1` (20 / 19), `BTSTEP`;
- removed: `SIDEC`, `KD`, `LS0`, `LSSH`, `PSPQ20`, `PSPM1`, `TTAP0`, `BTNEG`, `variant_text`,
  `ms_filter`, `dyn_consts`, `CHB`, `VARIANTS`;
- `Y_LAYOUT` 7, `TAGSP` `$5A5A0A`;
- new asserts for the slot and the row trick.

**`zqinit`:**
- builds `T'`: the mirror is `1/2 − T'`, from `y0 = $400000`;
- builds the rows in application order (`k = iR + j`, step `R − 1`).

**Tools:**
- `tools/repitch_dsp_engine_check.py`: the 24-bit limit on the design's output for the
  comparison; work directory `out/repitch_engine_check_sp12st`.
- `tools/repitch_dsp_boot_check.py`: the expected `BTAB`.
- `tools/repitch_dsp_profile.py`: `--ratios`.
- `tools/repitch_dsp_octabam.py`: no `variant_text`; the substitution's new comment.
- `tools/dsp_xasm.py`: an XY dual move with an ALU op may now write X memory, as in
  `asl b a,x:(r3)+ y:(r7)+,a`. Before, only X reads were recognised. octabam's `dsp_asm` encodes
  the same words.

## Next

1. Flash `140C_VEM8D` and listen. Stereo width now comes from two full SP paths. Panned treble
   aliases on its own side, where mid/side kept it clean.
2. If it stays, set `VG_SP12` to 187 on the ColdFire side and rebuild.
3. If it goes back: `SP12_MIDSIDE_REFERENCE.md`, "To restore it".
