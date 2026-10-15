# VARISPEED_EMUS: the S950 / SP12 DSP kernel, optimised (bit-identical)

Branch `vem-dsp`, commits `1be8556`, `7f00d78`, `4d1ee66` (+ this report). Not flashed, not
promoted, not pushed. The goal was fewer DSP cycles per voice with **no change of output of
any kind**. Every gate passes on the final kernel:

| gate | result |
|---|---|
| `python3 tools/repitch_dsp_engine_check.py` | 80/80 bit-exact with `DspExact`, mode switch 8/8 |
| `python3 tools/repitch_dsp_octabam_check.py` | 264/264; octabam's own `dsp_asm` assembles the generated `rpk_dsp.asm` to the same 429 words |
| `python3 tools/repitch_dsp_boot_check.py out/mainos_varispeed_emus.bin` | PASS (fresh `140C_VEM4D` build) |
| `python3 tools/repitch_dsp_octabam.py --check` | current |
| `python3 tools/repitch_dsp_stall_check.py` (new) | PASS: no address register is used right after it is loaded |

The twin (`tools/repitch_engine_model.py`, `DspExact`) and the tables' contents are untouched.

**Build:** `KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py 140C_VEM4D` →
`out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx`, sha256
`1fae1e0a1e1a8eac3aa7b2bb52e891f13e5f87b1455473c89264a3b6e6af2bc7` (OS VERSION reads
`140C_VEM4D`; `mainos_varispeed_emus.bin` `be4eb1a8…`). A test label; **not flashed**. Its
ColdFire half is whatever this branch has (VEM3's), so it tests the DSP change only.

## How it is measured

`tools/repitch_dsp_cost.py` (new) runs the kernel inside the stock voice module on dsp56kEmu
with the engine check's protocol (two hook visits a frame, a trig every 37 frames at every
split, four signals × five ratios, both payloads: 121,272 frames per engine) and counts, per
16-output frame, the instructions executed **inside the cave** and their datasheet cycles
(the emulator's `opcodecycles` table, the same unit as `repitch_dsp_profile.py`; the probe's
new `RK_FRAMECYC`). Frame 0 (the table copy, which `zqboot` does at boot) is left out. Prices
are per output sample (frame / 16) unless marked.

Model caveats, both directions:
* dsp56kEmu prices **no pipeline stalls**. The kernel has none of the address-register kind
  (`repitch_dsp_stall_check.py`; the baseline had none either).
* dsp56kEmu charges +1 for **every** `(Rn)±Nn` in a single (non-XY) move: its "pre-update"
  class lumps post-update-by-Nn with `(Rn+Nn)`. The 56300 manual's pre-update modes are only
  `(Rn+Nn)` and `-(Rn)`, and octabam's `cycle_count.py` prices by words. So the model is, if
  anything, pessimistic where the kernel uses `(r6)+n6` (once an output). The design avoids
  single-move `(Rn)±Nn` everywhere else (see "didn't pay", 1).
* The baseline standalone used `rep #32` for the trig clear; the probe counts a REP'd move
  once, so its **worst** frame was under-counted by 32. The baseline worst figures below
  are the octabam form's (a DO, counted in full), i.e. the true ones.

`~hw` is `repitch_dsp_profile.py`'s estimate (2 × words, + 2 for a `(rN+disp)` access):
drum at 0.75 / 1 / 1.5 / 1.99, payload A.

## Before / after

| per output sample | baseline (2fa0ec2) | now | change |
|---|---|---|---|
| **RPS9** median, instructions | 51.50 | **47.00** | −8.7 % |
| RPS9 median, modelled cycles | 57.25 | **52.00** | −9.2 % |
| RPS9 worst frame, instructions | 54.69 (875 / frame) | **50.00** (800) | −8.6 % |
| RPS9 worst frame, modelled cycles | 61.31 (981 / frame) | **56.25** (900) | −8.3 % |
| RPS9 `~hw` | 108.5 | 98.9 | −8.8 % |
| **RPSP** median, instructions | 112.06 | **92.06** | −17.8 % |
| RPSP median, modelled cycles | 142.62 | **114.00** | −20.1 % |
| RPSP worst frame, instructions | 132.06 (2113 / frame) | **109.50** (1752) | −17.1 % |
| RPSP worst frame, modelled cycles | 167.38 (2678 / frame) | **135.75** (2172) | −18.9 % |
| RPSP `~hw` | 269.7 | 217.1 | −19.5 % |

Cycles per instruction: RPS9 1.11 → 1.11, RPSP 1.27 → 1.24. (The engine check's own
figure, which counts the stock tail of each pass too: RPS9 52.2 → 47.8, RPSP 112.8 → 92.8
instr/sample; worst 132.8 → 110.2.) The standalone and the octabam form now price the same.

Where it went (modelled cycles per output sample; a tick is 1/PSP = 0.59 per output):

| RPSP | before | after |
|---|---|---|
| every output (tick test + out block) | 43.0 (36 instr) | 30.0 (25 instr) |
| every tick (tick block + ADC + render), per tick | 143.7 | 119.7 |
| … per output sample | 85.1 | 70.8 |
| every pass (≈ 8.3 outputs), per output sample | 17.9 | 15.9 |

| RPS9 | before | after |
|---|---|---|
| every output | 49 (48 instr) | 45 (44 instr) |
| every pass, per output sample | 8.0 | 6.8 |

### The mode check every voice pays (`zqrp`)

Every pass of every track on the core (RPCH, stock machines, empty passes) runs the hook:

| | instr in cave | cycles in cave | + hook `bsr` | of which stock's own moves | net over stock |
|---|---|---|---|---|---|
| before | 7 | 15 | 20 | 2 | 18 |
| **after** | **6** | **14** | **19** | 2 | **17** |

(`move y:>$40,a` 3, `and` 1, `beq` 5, the two displaced stock moves 2, `rts` 3; the `bsr`
at the hook site 5.) Per track per frame: two passes, **38 cycles** (34 net over stock). The
`clr` it lost was unnecessary: AND sets Z from bits 47-24.

## Per-voice worst-case prices (the load guard's constants)

Measured worst frame over the suite (a split trig frame with ten SP ticks, the ring clear
and a clean slot), in-cave, **plus the two hook `bsr`s** (5 cycles each):

| voice | worst, cycles / frame | per sample | median, cycles / frame | per sample |
|---|---|---|---|---|
| **S950 (RPS9)** | **910** | 56.9 | 842 | 52.6 |
| **SP12 (RPSP)** | **2182** | 136.4 | 1834 | 114.6 |
| OT / RPCH / stock track | **38** | 2.4 | 38 | 2.4 |

(Baseline, same basis: RPS9 991, RPSP 2688, RPCH 40.) RPS9's 910 is structural (a split
trig frame is its dearest case). For RPSP the only path the suite cannot combine with a
trig frame is a resync on the frame's first pass (`zqsrs`, ≈ 12 cycles): a guard that wants
a structural bound should use **RPSP 2198 cycles per frame** (137.4 a sample). The one-time
`zqinit` (Y tag mismatch) is excluded, as before: `zqboot` runs it at boot (+3,598 boot
instructions, outside every audio pass).

## Words used, and where

**P** (standalone, `repitch_dsp_src.cave_org`): **429 words** (was 412), ending right below
DARK REV's routine: A `P:0x13d9..0x1585`, B `P:0x1199..0x1345`. The first run has 432 words
of room with SIDECHAIN's 388 kept free: **3 spare**. Layout: `zqrp`/`zqtok`/trig 40, RPS9
60, RPSP 231, `zqboot` 22, `zqinit` 76. SPRING's ~208 free words after DARK's routine are
**unused**; the cold `zqboot` + `zqinit` (98 words) can move there if the hot code ever needs
the room. The octabam form is the same 429 words (one contiguous block; octabam places it).

**X** (SPRING REVERB's own X tables, rewritten by the builder): **465 words**, unchanged in
size: run 1 (A `X:0x89a4`, B `X:0x8464`) the render's half-table, 81; run 2 (A `X:0x8afc`,
B `X:0x85bc`) the RPSP half-rows, 128, then RPS9's, 256 — **now tap-major**
(`repitch_dsp_src.r9_stored`; octabam's `PTABLE2` follows). `zqinit` alone reads them.

**Y** (unchanged range `Y:$A00-$FFF`): four RPSP slots of `$20` at `$A00` (`$18` words used
each: the 10-word residual ring, then OH OL PF HM PKW MASK RB | RF PHI RH LS | TAU RW TAG),
TABTAG `$A7F`, SPTAB `$A80-$B7F` (32 × 8, row-major), R9TAB `$C00-$DFF` (32 × 16,
**transposed**: tap t of phase p at `32t + p`), BTAB `$E00-$FFF` (16 rows of 32 words: the
ten taps' (T, D) pairs, then padding; was 320 words + a 161-word scratch run at `$F40`;
`zqinit` now builds T in R9TAB's place before it copies that table). Y layout 6, slot tag
`$5A5A09`. Registers: the same set as before (r1 r4 r6 r7, n1 n2 n4 n5 n6 n7, m1 and m7
restored; r5 restored); the hardware stack is shallower (the render has no DO).

## The optimisations

Savings are modelled cycles per output sample at their rate (outputs 1, ticks 0.59,
passes ≈ 0.12), read off the before/after profiles.

**RPSP, every output (−13 cycles, −11 instructions)**
1. **tau lives in r4** for the pass: `jset #20,r4` decides a tick (tau < PSP < 2.0, so bit 20
   is "tau ≥ 1"), and `(r4)-n4` takes the interval in a free parallel slot. Replaces load /
   `sub #>` / store / `bge` (9 → 4 cycles). **−5.**
2. **The out block rebuilt** (34 → 26 cycles, 32 → 24 instructions): the mid first, into x0
   (no n5 stash and reload); OH/OL ride the two `asl b` slots (two 1-bit shifts instead of
   `asl #2`); PF/PKW stores in ALU slots; the $7e mask from the walk, so `and` is a
   parallel-capable register op; after the mask and the base, **`asr a` leaves g in a0**
   (the address is even), so g needs no copy; **1−g disappears**: `side = M·s0 − g·s0 + g·s1`
   (one `mpyi #$7fffff` + two `mac`, the same integer in the accumulator); s0, R0 and R1 all
   go through x1, freeing x0; the ring slot is cleared in the L0 read's XY move;
   L = mid + side keeps a's fraction bits (the side never saturates: a convex mix of two
   24-bit values) and R = mid − lim(side). **−8.**

**RPSP, every tick (−24 cycles a tick → −14.2 a sample)**
3. **The tick state walked by r1** (RF PHI RH LS in that order, one `lua`) instead of eight
   `(r4+disp)` accesses, with the RF and RH loads in an R:Y move and a `tfr` slot; tau and u
   from r4 in three instructions (`asl #3,b,a` makes u in the other accumulator);
   **the LS one-pole as one `maci`**: `LS + ((x − LS) >> 4) = (x + 15·LS) >> 4` exactly (the
   product's b0 cannot carry). **−9.**
4. **The render's table as 32-word rows** (`BTAB + 32 j`, the ten (T, D) pairs then padding,
   walked with `(r5)+`): the row is `lsr #19 / lsl #5 / add`, the fraction `lsl #5 / lsr`
   (no `and #>$7fffff`), both from copies of u made in parallel slots. Was a ×20 row (8
   instructions) and a 4-instruction fraction. **−9.**
5. **The render unrolled** (ten taps, no DO), its last tap's dead read slot restoring r5.
   The ADC and the render both walk r5, so tau never leaves r4. **−6.**

**Every pass (RPSP −2.0, RPS9 −1.2)**
6. `zqrp`: no `clr` before the mode test (−1 on **every** voice pass).
7. The trig test as a displaced read + `jclr #12,a1` (was clr / move / `and #>` / `beq`).
8. `x:$418` read only on the trig path and in RPSP (RPS9 never needs the track offset); RPS9
   ends with `zqdone`'s tail inline (no `bra`).
9. RPSP: the slot tag compared as an immediate; `l:$40` read once through r4 = $40 (one L
   move instead of two long-absolute reads); r6 rests on OH from the start (no `lua`); a
   clean slot clears only the ring and the three words that start at zero.

**RPS9, every output (−4 cycles, −4 instructions)**
10. **Transposed table** (tap t of phase p at `R9TAB + 32t + p`, walked `(r7)+n7` inside
    the XY moves, which the model does not penalise): the row base is `R9TAB + phase` (one
    shift less). **−1.**
11. The first tap's base precomputed per pass (`r6 = r2 + 128 − 2c − 1` frames' words,
    m6 = $7f), so no per-output `sub`. **−1.**
12. The 12-bit tail one instruction shorter (`and y1,a x0,b`), and **the next output's
    fraction loads in the R store's XY move**. **−2.**

**Not cycles, but part of the change**
* The trig ring clear is a `do`, not a `rep` (interruptible; the standalone and octabam's form
  are now the same code, so `repitch_dsp_octabam.py` lost its REP substitution).
* RPSP's channel-6 and channel-1/2 builds (`RPK_OUT=ch6/ch12`) are dropped from the DSP
  kernel; `repitch_dsp_src.source()` refuses them. Git history has them; the model still
  renders them for listening packs.
* `tools/dsp_xasm.py` encodes `tfr a,b` / `tfr b,a` itself: our `dsp_asm` emits JJJ = 001,
  which is `rnd` (its check caught it; octabam's newer assembler has the fix). It also reads
  the disassembler's `func_NNNNNN` as an address.

## What didn't pay, or wasn't risked

1. **The render table as T and D runs per tap** (stride 16, `(r5)+n5`): two ALU ops fewer per
   tick, but dsp56kEmu adds +1 to each of the 20 single-move `(Rn)+Nn` reads (+20 modelled a
   tick). The padded rows cost one shift and walk with `(r5)+`.
2. **`jcc` / `jmp` (4 cycles) instead of `bcc` / `bra` (5)**: both assemblers (ours and
   octabam's) only encode the 12-bit short forms, and the kernel sits above `P:$FFF`.
   `jclr` / `jset` on registers assemble in both and are used.
3. **The mode test from x0.** Stock leaves `x = l:$40` at the hook (`P:0x3fc` →
   `0x40b` / `0x1ff` → `0x20e`, straight-line), which would save 2 cycles on every pass of
   every track, but the stock-or-engine decision should not rest on a register; not done.
4. **`lua (r6)+n1,r1`** for RPS9's first tap: one instruction instead of two, but 3 cycles.
5. **A modulo-7 m6** to drop the out walk's rewind: every displaced `(r6+d)` access would then
   depend on how the 56300 applies Mn to displacement addressing. Not risked.
6. **The residual ring or the render table in X memory** (XY moves: 3 instructions a tap
   instead of 4): the only X known free on both cores is in SPRING's table runs at
   `X:$8xxx`, where the 303 work found dense access unsafe on core 0, and octabam places
   those blocks elsewhere.
7. **A pull-form render** (each output sums the ticks that still owe it): more work per
   output. **Two loops per pass** (all mids, then all sides): frees registers for the side's
   constants but reads the table twice and adds a DO. Neither wins on paper.
8. **Caching the pass constants between a frame's two passes**: OH/OL depend on LS, which
   the first pass's ticks move; the twin recomputes them per pass.

## For the next step

* Flash `140C_VEM4D` (above) and A/B by ear against VEM3: it must sound identical; the
  emulator says so word for word, the hardware has not run it. The octabam module's manifest
  still calls `rpk_dsp.asm` "a copy of the hardware-proven one" — true again only after that
  flash (not edited here: the ColdFire session owns the manifest).
* If the load guard is updated, use the per-voice constants above; re-run
  `tools/repitch_dsp_cost.py` (both `--form`s) after any kernel change.
