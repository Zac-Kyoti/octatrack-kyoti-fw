# Analog Rytm DIRECT JUMP — full mechanism, and its mapping onto the Octatrack

Canonical record of the AR-side reverse engineering and what it produced on the OT side.
Kept in **both** repos (`ar-kyoti-fw/AR_DIRECT_JUMP.md` and
`octatrack-kyoti-fw/reference/AR_DIRECT_JUMP.md`) so neither project depends on the other
being at hand.

AR source: MAIN OS 1.73, `section_3_MAIN_OS.bin`, load base `0x40000400`, ColdFire/m68k BE.
OT source: OS 1.40C MKI, same toolchain. Every address below is **measured** in Ghidra or
raw disassembly unless explicitly marked inferred. Derivation trails: `ar-kyoti-fw/NOTES.md`
Sessions 1–9, `octatrack-kyoti-fw/NOTES.md` Session 79 cont.20–31.

---

## 1. AR: the request path

PTN CHG mode is a small integer at `picker + 0x74`, read via `FUN_400b3d1e`:

| value | mode |
|-------|------|
| 0 | SEQUENTIAL |
| 1 | DIRECT START |
| 2 | DIRECT JUMP |
| 3+ | TEMP JUMP (saturates to 2 at the read site) |

The UI dispatcher (`FUN_4003fc14`) filters SEQUENTIAL out **before** any of the machinery
below; it never reaches `FUN_4003e636`. SEQUENTIAL uses an unrelated "picker value changed"
notify path.

**Queue write — `FUN_4009a5b0`**, called from `FUN_4003e636`. Writes three globals fresh on
every request:

- `DAT_405667dc` — resolved target pattern
- `DAT_405667e0` — start-behaviour flag: **non-zero = DIRECT START**, zero = DIRECT JUMP/TEMP
- `DAT_405667e8` — countdown base, **recomputed from the current tick every time**, never
  accumulated. This is what makes a second request before the first commits behave correctly.

If the transport is stopped (`DAT_405666e0 == 0`) it instead calls `FUN_4009a2ae`, a
synchronous immediate setter — nothing to quantise against.

**Countdown — `FUN_4009905c`, per tick.** Waits on `DAT_405667e4`, derived from
`DAT_405667e8` and the ticks-per-step table at `0x401a8ff0` (measured `3, 4, 6, 8, 12, 24,
48`). The wait is to the **next step/resolution boundary** — at most a few dozen ticks, never
a full pattern.

---

## 2. AR: the commit — this is the part that matters

At the boundary, `FUN_4009905c` writes the pattern atomically:

```
0x400991ae   move.b D0b,(0x40566754)      ; both in the same two instructions,
0x400991b4   move.b D0b,(0x40566755)      ; no window where they disagree
```

Then the master position:

```
0x40099252   tst.l (0x405667e0)           ; DIRECT START?
0x4009925a   D0 = 0x14eb3                 ; pattern-wide step length (word)
0x40099262   D2 = mvz.w (0x405666e4)      ; current master step
0x40099274   divsl.l D1,D2:D0             ; D0 = masterStep mod patternLen
0x4009927a   clr.l D0                     ; DIRECT START -> 0
```

**And then the payload, which Sessions 1–7 missed entirely**: two unconditional loops over
all **13 tracks** (12 drum + 1 FX) that rebuild every per-track array from scratch.

Loop 1 — per-track countdown reloads (`0x400991de`–`0x40099202`):

```
*(0x405667c7 + t) = ticksPerStep[ *(track_t + 0x2c7) ] - 1
```

Loop 2 — per-track phase (`0x4009927c`–`0x400992d2`):

```
A6=0x40566720  A5=0x4056673a  A4=0x4056672d  A3=0x405667ba  A2=0x40566830
A1 = pattern record base ; D1 = 0
loop:                                       ; 13 iterations
    D3 = D5 ? *(A1 + 0x2c5)                 ; per-track scale mode -> THIS track's length
            : *(A0 + 0x14eb3)               ; else pattern-wide length (word)
    D7 = D0                                 ; master new_step, reloaded every pass
    D2 = D7 mod D3                          ; divsl.l D3,D2:D7 -- remainder
    A1 += 0x395                             ; next track record
    *(A6)++ = D2 ; *(A5)++ = D2-1 ; *(A4)++ = 0 ; *(A3)++ = -1 ; *(A2)++ = D2
until ++D1 == 13
```

Loop bound `0x2e91` = **exactly** 13 × stride `0x395` (917) — arithmetic, not inference.

**Complete per-track array inventory**, all 13 entries, tiling contiguously, with four
boundaries independently confirmed by the function's own `cmpa.l` sentinels (`0x40566720`,
`0x40566747`, `0x40566782`, `0x405667d4`):

| array | width | value |
|-------|-------|-------|
| `0x405666ec` | long | `1` |
| `0x40566720` | byte | `new_step mod trackLen` |
| `0x4056672d` | byte | `0` |
| `0x4056673a` | byte | `(new_step mod trackLen) - 1` |
| `0x40566775` | byte | per-track resolution index |
| `0x405667ba` | byte | `-1` |
| `0x405667c7` | byte | `ticksPerStep[trackRes] - 1` |
| `0x40566830` | byte | `new_step mod trackLen` |

Plus master scalars `0x405666e4 = new_step`, `0x405666e8 = new_step - 1`, `0x405666e6` =
master ticks-per-step − 1, `0x40566774` = master resolution index, `0x405667d4 = -1`.

A second, independently-gated commit site (`0x40099370` onward, gated on `0x405667d6` and
`0x40566748 == 1`) rebuilds `0x405667c7[t]` with byte-identical logic at
`0x400993e8`–`0x40099404`. **Two commit paths, one discipline.**

### The AR invariant

> **Rewrite the whole per-track state vector from one master position; never patch it.**

No per-track value survives a commit, so "stale per-track variable" is not a failure mode
that exists on AR. The atomic paired write and the fresh-per-request countdown are real but
secondary.

### AR is NOT simpler than OT

`0x14eb9` is AR's **per-track scale mode flag** — the direct analogue of OT's `SCALE_MODE`.
AR has per-track lengths *and* per-track resolutions, confirmed by the user against hardware
(12 drum tracks + FX track, each independently settable). AR's correctness is a property of
*how it commits*, not of a simpler data model.

---

## 3. The OT equivalent — which turned out to already exist

The decisive OT-side finding (Session 79 cont.21): **OT already contains the same rebuild**,
at `0x400a4884`–`0x400a49e2` (audio) and its MIDI twin from `0x400a49e6`. It had been
invisible for the whole project because it sits inside a **1586-byte region Ghidra never
decoded** (`0x400a4568`–`0x400a4b9a`), now force-decoded and saved.

Per track it does:

```
0x400a4900/06  D0 = SCALE_MODE ? blob[t][+0x51] : pattern[+0x8e54]
0x400a490a     D1 = LEN_TBL[D0]                    ; this track's TICKS PER STEP
0x400a490e-10  D0 = (D7 - 1) + D1
0x400a4912     divsl.l D1,D0:D0                    ; q = ceil(D7 / tps_t)
0x400a4916     NEXT_STEP[t] = q                    ; first store
0x400a4950     D1 = mvs.w NEXT_STEP[t]             ; read back, SIGN-EXTENDED
0x400a4966/72  D0 = SCALE_MODE ? blob[t][+0x50] : pattern[+0x8e53]   ; this track's LENGTH
0x400a4976     divsl.l D0,D2:D1                    ; q mod length_t
0x400a497a     NEXT_STEP[t] = remainder            ; surviving value
0x400a4920/24  PAIR[t] = D7 - q*tps_t              ; sub-step phase
0x400a49c6     CNTDN_TBL[t] = LEN_TBL difference   ; scale phase-alignment delay
```

and the boundary body then seeds `STEP[t]` from `NEXT_STEP[t]` at `0x400a4be6`.

Its **only** position input is `D7`, built just before it:

```
0x400a4802  tst.b (pattern + 0x8e55)               ; SCALE_MODE
0x400a4808  SCALE_MODE!=0 -> D0 = pattern + 0x8e52 ; master scale
0x400a4822  SCALE_MODE==0 -> D0 = pattern + 0x8e54
0x400a4812  D7 = LEN_TBL[D0]                       ; master ticks per step
0x400a481c  D7 *= *(long)0x80006628                 ; START OFFSET IN MASTER STEPS
```

`0x80006628` is **normally 0**, which is why every OT commit restarts every track at step 0.

---

## 4. AR ↔ OT mapping

| concept | Analog Rytm | Octatrack |
|---------|-------------|-----------|
| tracks | 13 (12 drum + FX) | 16 (8 audio + 8 MIDI) |
| track record stride | `0x395` | `0x91a` audio / `0x8b0` MIDI |
| per-track scale-mode flag | pattern `+0x14eb9` | pattern `+0x8e55` |
| per-track length | track `+0x2c5` | track `+0x50` / MIDI `+0` |
| per-track resolution / scale | track `+0x2c7` | track `+0x51` / MIDI `+1` |
| pattern default length | `+0x14eb3` (word) | `+0x8e53` |
| pattern default scale | `+0x14eba` | `+0x8e54` |
| master scale in per-track mode | — (single field) | `+0x8e52` |
| ticks-per-step table | `0x401a8ff0` = 3,4,6,8,12,24,48 | `LEN_TBL 0x400aba50` = 3,4,6,8,12,24,48,96,48,24,12,6 |
| commit site | `FUN_4009905c` (own per-tick fn) | inside `consumer_a6c0_a33f8`, rebuild loop `0x400a4884` |
| pattern commit write | `0x400991ae`/`0x400991b4`, **back-to-back** | `ACT_PAT 0x800065be` / `ACT_BANK 0x800065bd`, **12 bytes apart** |
| request/cue | `DAT_405667dc/e0/e8` | `PEND_PAT 0x800065c0` / `PEND_BANK 0x800065bf` |
| quantise-to-boundary | `DAT_405667e4` countdown | Hook A arms, commits on the next step tick |
| position input | `new_step = masterStep mod patternLen` | `D7 = LEN_TBL[masterScale] * 0x80006628` |
| per-track step | `0x40566720[t]` | `0x800064d0[t]` |
| per-track step − 1 | `0x4056673a[t]` | `0x800064e0[t]` |
| per-track countdown reload | `0x405667c7[t]` | `CNTDN_TBL 0x800065c3[t]` |
| per-track resolution cache | `0x40566775[t]` | `TRK_SCALE_IX 0x8000663e[t]` |
| ticks-within-step | (implicit in countdown) | `0x800064f0[t]` |
| quotient / remainder scratch | — | `NEXT_STEP 0x800065e4[t]` / `PAIR 0x80006604[t]` |
| master step | `0x405666e4` (word) | `STEP 0x800065b6` |

**Both machines have the same architecture.** Each rebuilds every per-track variable at
commit, from one master position, dividing by that track's own ticks-per-step and wrapping to
that track's own length.

Two genuine differences:

1. **AR's pattern pointer write is atomic** (two adjacent instructions); OT's `ACT_PAT` and
   `ACT_BANK` writes are 12 bytes apart, so a window exists in principle. Not yet observed to
   matter on OT.
2. **AR commits from an independent per-tick function.** OT's rebuild lives inside the
   pattern-boundary body, which is why OT's DIRECT JUMP has to reach it at all.

---

## 5. What the port actually turned out to be

Not a port. OT's AR-equivalent machinery was already there and already correct — it had
simply never been given a non-zero offset, because `0x80006628` is 0 at a natural boundary
and nothing ever set it otherwise.

> **DIRECT JUMP = set `0x80006628` to the resume offset before `D7` is built, and let stock's
> own rebuild loop do the rest.**

Implemented as **Hook H** at `0x400a47f6` (6 bytes, replaces `lea 0x400eb034,A0`): when armed,
`0x80006628 = G_ABSTICK`. Then `D7 = LEN_TBL[masterScale] × G_ABSTICK` = absolute ticks, and
per track `NEXT_STEP[t] = (absTicks / tps_t) mod length_t` — exactly the user's stated model:
*every pattern behaves as if it had been playing silently the whole time at its own length.*

`G_ABSTICK` and not the outgoing master step, because once `STEP` has wrapped against the
outgoing pattern's length the elapsed information is gone and no later modulo recovers it.

**Measured** (`tools/diag_d7_inject.py`, patched firmware, armed commit, DJTESTxxx pattern
1 → 0, `SCALE_MODE = 1`, `G_ABSTICK = 26` → `D7 = 156`):

| track | scale | len | tps | STEP | derivation |
|-------|-------|-----|-----|------|------------|
| 0, 3–15 | 2 | 16 | 6 | **10** | 156/6 = 26 steps, 26 mod 16 |
| 1 | 0 (2x) | 16 | 3 | **4** | 156/3 = 52 steps, 52 mod 16 |
| 2 | 2 | 12 | 6 | **2** | 26 mod 12 |

16/16, coherent across differing scales **and** differing lengths. Reverse direction (0 → 1)
also 16/16.

### Three "repair" hooks, two of them actively harmful

The pre-existing patch tried to *repair* per-track state after the fact. Removing that
approach removed the bugs:

- **Hook F (`dj_pertrack_fix`) — REMOVED.** Computed `G_ABSTICK mod LEN_TBL[scale]`, i.e. mod
  **ticks-per-step**, and wrote it into both the per-track STEP array and the
  ticks-within-step array, audio tracks only. Measured: it dropped audio tracks from the
  correct 10 to 2 while MIDI kept 10 — audio/MIDI desync on every armed commit. This is also
  the mechanism of the flashed hardware regression.
- **`dj_c` — two bugs fixed.** Same `LEN_TBL` misreading (resume step was `absTicks mod 6`,
  a value in 0..5), and it overrode `D7` *after* stock built it and *before* the loop read
  it, replacing the correct offset with a small wrong one.
- **Hook D (`dj_scaleix_fix`) — retained, not fully cleared.** Unconditional (not
  `DJ_MODE`-gated). Measured inert with the feature off, but it reads the scale from
  `+0x8e54` unconditionally whereas stock's own master-scale source is `+0x8e52` when
  `SCALE_MODE` is set. Needs a pattern where those differ.

The common root: `LEN_TBL` is a **ticks-per-step** table (its entries are exactly OT's scale
multipliers 2x, 3/2x, 1x, 3/4x, 1/2x, 1/4x, 1/8x, 1/16x), and had been read as a *pattern
length* table for many sessions. That misreading was baked into two separate hooks.

---

## 6. Known limitation — 16-bit position bound

`NEXT_STEP[t]` is stored with `move.w` at `0x400a4916` and read back **sign-extended** with
`mvs.w` at `0x400a4950`. The first divide's quotient equals `G_ABSTICK` (when the track's
resolution matches the master's), so `G_ABSTICK` must fit a **signed word**.

**Measured** by poking the counter: `G_ABSTICK = 40002` → `D7 = 240012` →
`NEXT_STEP = -14`, `STEP = 242` on a 16-step pattern. Garbage.

Bound ≈ **32767 master steps** — roughly 68 minutes of continuous transport at 120 BPM with
16th-note steps. Hook H must reduce `G_ABSTICK` before storing it. The reduction modulus has
to be a common multiple of the per-track lengths in play, or per-track positions shift;
choosing it correctly is **open work**.

AR does not have this problem: its dividend is the bounded master step
(`masterStep mod patternLen`), not an unbounded absolute counter — a direct consequence of
AR committing from its own per-tick function rather than reusing a boundary body.

---

## 7. AR-side items still open

1. **TEMP JUMP's revert bookkeeping.** `FUN_400b3d1e` saturates mode ≥ 3 to 2, so TEMP JUMP
   is byte-for-byte identical to DIRECT JUMP through this entire pipeline. Whatever makes it
   revert lives elsewhere — plausibly reusing `DAT_40566756` ("previous pattern"), **inferred,
   not checked**.
2. **SEQUENTIAL's own commit path** (`0x4015716c` write target) — located but not traced.
3. **Semantics of AR's `0`/`-1` per-track arrays** (`0x4056672d`, `0x405667ba`). OT's port
   does not need them, but the symmetry is unexplained.

## 8. Methodology hazards recorded along the way

- **Ghidra's printed operand order for ColdFire `divsl.l` is unreliable.** Read the extension
  word: field(14:12) = dividend **and** quotient destination, field(2:0) = remainder.
- **objdump garbles ColdFire `mvs`/`mvz`/`muls.l`/`divsl` into `.short`** — use Ghidra for
  these regions.
- **"X is never referenced" is only as strong as the instruction coverage under it.** The
  firmware-wide scan reported OT's `PAIR` array as having no writer at all; coverage of the
  enclosing function was 86.6%, and the writer was in the undecoded gap.
- **Reference-based write detection misses register-indirect `(An)` stores.** Writer counts
  from such a scan are a lower bound, not a census.
- **A snapshot at a hook's entry measures the state before that hook, not after.** This
  produced a false "16/16 correct" result while Hook F was still clobbering audio tracks.
- **A one-tick flag cannot be observed by sampling every few ticks.** `G_ARMED` is set and
  cleared on consecutive ticks; sampling it produced a false "the DJ path never armed".
