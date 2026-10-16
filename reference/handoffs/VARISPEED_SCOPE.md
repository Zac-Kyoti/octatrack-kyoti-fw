# REPITCH rewrite: clean-room scope

Written 2026-10-13 by the **clean** agent, from the stock 1.40C image (`section_3_MAIN_OS.bin`,
sha256 `164f3122…`, checked this session), stock emulator runs, `reference/kb/*` and the own-code
files the spec allows. Nothing here comes from the blacklisted material (§7 lists every source,
§7.3 the one incident). No code was written, built or flashed.

Marks: **C** = confirmed on our image (objdump, or an emulator run of the stock image);
**I** = inferred. Addresses are virtual (`file offset + 0x40000400`).

---

## 1. Summary

### 1.1 How stock plays a STATIC/FLEX sample (the facts the design rests on)

- **The render.** Each frame, the voice loop (`0x4000d3fc..0x4000d55e`, inside the frame ISR) calls,
  for every track, `render[mtype](t, frame, start, end)` twice: the old sound's tail
  `(t, [0x800000e4], 0, split)`, then `(t, [0x800000e0], split, 16)` (C, `0x4000d42a..0x4000d52c`).
  The table at `0x400d6434` is indexed by machine type: ST, FL and PU share **`0x40004008`**, THRU is
  `0x40004424`, NEIGHBOR `0x4000466c`, types 5–7 `0x400047f0` (C).
- **The increment.** `0x40004008` computes the Q26 increment **only on the second pass**
  (`btst #4,end` at `0x4000406a`): PTCH from the lane word at `+0` through the pitch table
  `0x400aa294`, times |RATE| unless SETUP RATE mode is TSTR (`0x4000407a..0x40004102`). It stores the
  result in the per-track render state `+36` (`0x80004898 + 40t`, store at `0x40004104`). The first
  pass reuses the stored value (`0x40004072`) (C).
- **Where it goes.** One value feeds **both** sides: the DSP voice record header `+8`
  (`0x40004116`), and the ColdFire position accumulator `+0`, which decides how many new frames the
  stream engine `0x40007960` must deliver (`0x40004172..0x400041c4`) (C).
- **Dry versus stretch.** The stream engine resolves TSTR at **`0x40007d80..0x40007dbc`**: lane `+28`,
  and AUTO goes to the sample's settings `+0x110`. It stores the effective mode in voice `+24`. Mode 0
  initialises a 1:1 source-per-ring-frame stepper (`0x40007ee4`), so the source advances exactly one
  frame per delivered frame, and the speed is the increment alone. Modes ≠ 0 run the CF-side stretch
  (C). Timestretch is entirely ColdFire-side: the DSP never sees TSTR (C, read census §2.2).

**Consequence.** If the increment is changed **before** the `+36` store, the ColdFire and the DSP
cannot disagree about the speed. If TSTR resolves to 0, the track is dry and the increment alone
sets the speed, forwards or in reverse.

### 1.2 Proposed hook list

| # | site | kind | purpose | class |
|---|---|---|---|---|
| H1 | `0x40004100` (8 B: `movclr acc0,d0; asr d6,d0; move.l d0,36(a3)`) | `jmp` detour, frame ISR | the whole per-frame core: gate, `rp_swap` call, lane TSTR→0 (dry), QUAN × tempo ratio × RATE, clamp, tag; mask bits 2-3 on every other ST/FL/PU increment | **FORCED** window (§2.1/§2.5); the exact site is CHOSEN |
| P1 | `0x400d30de`, `0x400d3270` | poke (u32) | TSTR count 4 → 7 (STATIC, FLEX) | FORCED (the descriptor is what the editor clamps with) |
| P2 | `0x400d313e`, `0x400d32d0` | poke (u32) | TSTR widget `0x40046c28` → `0x40046ab4` | CHOSEN |
| P3 | `0x40046b08` (`7004`→`7006`), `0x40046b9e` (`0x400be316`→`rpk_glyph_tab`) | poke | stock's unreferenced 5-position widget becomes 7-position with our glyphs | CHOSEN |
| P4 | `0x400d310e`, `0x400d32a0` | poke (u32) | TSTR formatter `0x4003b6a4` → new `tstr_fmt` (PICKUP keeps the stock one) | FORCED (the stock formatter is shared with PICKUP and has a 4-entry table) |
| H2 | `0x4006e71c` (10 B: `pea 0x400b94f6; bra.w 0x4006e878`) | `jmp` detour, UI task | ATTR TIMESTRETCH label for 4/5/6 (stock prints `ERROR`) | FORCED (the one `else` of the label chain) |
| H3 | `0x4006ee48` (6 B) | `jmp` detour, UI task | ATTR value up: 0→2→3→4→5→6, then `rp_refresh` | FORCED (the row-2 branch of the up handler) |
| H4 | `0x4006ef7c` (6 B) | `jmp` detour, UI task | ATTR value down: 6→5→4→3→2→0, then `rp_refresh` | FORCED (the row-2 branch of the down handler) |

The retained code keeps its own sites unchanged: `qdial1..4`, `quant_step` in `P+0x12a` slot 0, the
two Part applies, and RELOAD PART.

**What is not hooked.** The TSTR resolve (`0x40007d80`) is not hooked: H1 zeroes the lane's TSTR byte,
whose only reader is the resolve. Nothing in the stream engine is hooked. The pitch load is not
hooked, because H1 computes the repitch increment from RATE alone, exactly (§2.1).

### 1.3 Units, placement, size

- **New core, about 500 B.**
  - H1: about 260 B with the exact scale.
  - `tstr_fmt` with its table and strings: about 80 B.
  - H2: about 50 B with `REPITCH\0RPS9\0RPSP\0`.
  - H3/H4: about 2 × 45 B.
- **Retained ColdFire code.** `VARISPEED_RETAINED.s` assembles to 1184 B. `patch_repitch_reload.s`
  is 46 B. `rpk_glyphs.s` is 644 B. All three were measured with `m68k-elf-as -mcpu=54455`.
- **Total ColdFire about 2.4 KB.** That is too much for octabam's floating ROM run beside the other
  KYOTI modules. The module README says the shipped module, at about 2.6 KB, did not fit either.
- **Recommendation: DRAM units**, octabam `Linked(..., dram=True)`, as now (CHOSEN).
  - kb/caves.md §5: the DRAM loader is hardware-proven on a MKI.
  - The emulator measures DRAM code at ROM cost.
  - The alternative, the classic cave from `0x400d6500`, is contested and effectively full
    (caves §2/§2b).
  - The descriptor table `0x400d2e52..0x400d5f00` must never hold code (caves §0). P1/P2/P4 are value
    edits inside STATIC/FLEX records `P..P+0x192`, not placement.

### 1.4 Per-frame cost

The cost falls in the frame ISR, H1 only, and only on the second pass of ST/FL/PU tracks.
THRU, NEIGHBOR and empty tracks never reach it.

| track | stock at the site | with H1 |
|---|---|---|
| ST/FL/PU, TSTR OFF/NORM/BEAT | 3 instr | about 16 instr (TSTR byte test, `rp_prev[t]` test, mask) |
| ST/FL, TSTR AUTO (the default) | 3 | about 25 (adds voice `+8` → settings `+0x110`) |
| repitch track | 3 | about 80 for the core (3–4 `divu/remu`), or about 25 with the §6 cache; plus `rp_swap` about 60–80 (it runs `rp_ui_gate`: 3 `mulu.l`, about 15 loads), mandated per frame by spec §3 |

Measure with the load-audit ot_emu patch (`OT_ISR_OUT`, IPL ≥ 5 episodes) before and after (§5.3).

---

## 2. Per requirement

### 2.1 Item 3: a repitch track (speed, dry, RATE, tempo)

**The increment computation** (render `0x40004008`; frame layout `sp+52` = t, `+56` = frame, `+60`
= start, `+64` = end; all C by objdump).

| addr | what |
|---|---|
| `0x4000403c..0x40004056` | `a5 = 0x80000eb4 + frame*8 + t` (this frame's machine-type byte); `fp = [0x800062a8]` = lane record `0x80000510 + 384*frame + 48t`; `a3 = [0x800062a4]` = render state `0x80004898 + 40t` (set by the voice loop `0x4000d386..0x4000d3a8`, `+40`/`+48` per track at `0x4000d538/40`) |
| `0x4000405e` | render `+28 = [0x8000181c] << 4` (tempo for RTRG/RTIM) |
| `0x4000407a..0x400040b8` | RTIM (lane `+10`) → interpolated table `0x400aae0c` → render `+24` |
| `0x4000409e..0x400040e6` | PTCH = lane `+0`; `≤ 0x4000`: index `w>>5`, shift 1; else index `(w-0x3c00)>>5`, shift 0; linear interpolation in `0x400aa294` (EMAC, MACSR `0x20` fractional) |
| `0x400040d6..0x400040fc` | if SETUP RATE mode (lane `+27`) == 0 and RATE (lane `+6`) < `0x7f00`: × \|RATE−0x4000\|/0x4000 |
| `0x40004100..0x40004104` | `movclr acc0,d0; asr d6,d0; move.l d0,36(a3)` |
| `0x40004108..0x40004122` | DSP record header at `[0x80001c80]`: `+0`=0 (segment counts, filled later), `+4` = render `+32`, **`+8` = increment**, entries from `+16` |
| `0x40004172..0x40004190` | accumulator `+0 += inc·n`; new frames = `((acc − inc + 0x07ffffff) >> 26) − old`; header `+0 +=` frames |
| `0x400041c4` | `jsr 0x40007960(entries, frame, t, frames, n, second-pass flag)` (the only call site, C) |
| `0x40004232..0x40004258` | header `+12` = start accumulator, `+0..+2` = sample counts of up to three segments |

**Measured scales** (C: stock run with OTDEMO, `--watch-pc 0x400040a0,0x40004104`):

- The lane PTCH word is `ui<<8` plus modulation. T1 base `0x5e00`, lane `0x5414`.
- The pitch table `0x400aa294` holds `0x04000000·2^((i−32)/480)`, clamped to `0x04000000` below
  i = 32, and reaches `0x08000000` at i = 512. PTCH ui 4..124 is 0.5..2.0, and **word `0x4000` gives
  exactly `0x04000000`**.
- T1's measured increment `0x046100ab` equals pitch(lane `0x5414`) × (lane RATE `0x778f` − `0x4000`)
  / `0x4000` = 1.2611 × 0.8681 = 1.0948. This confirms the RATE factor.

**The rate-only increment, exactly.** Feed stock's own code a neutral PTCH (`0x4000`). Then
`acc = 0x08000000` and the RATE product is an exact multiple of 2^45, so EMAC truncation never
applies. The result is the integer:

```
inc_rate = 0x04000000                        if lane+27 != 0 or lane+6 >= 0x7f00
         = |lane+6 − 0x4000| << 12           otherwise
```

This is bit-identical to "stock with PTCH neutralised" (I, from the instruction semantics; check by
§5). H1 therefore needs no pitch hook.

**The scale.** Exact in 32-bit:

- Inputs: `N = T·p` and `D = S·q`, with `T = [0x8000181c]`, `S` = sample settings `+0x114`, and
  p/q = `.rk_ratios[rk_bucket(lane+0 >> 8)]`.
- Fold: while `N > 2D`, double `D`.
- Divide: `q1 = inc/D`, `r1 = inc%D`, `inc' = q1·N + (r1·N)/D`. Bounds: `N ≤ 7200·5`, `D < 2^17`, so
  `r1·N < 2^32`.
- Clamp to `0x07fffff0`. Tag: `(inc' & ~15) | mode<<2`.

**Tempo sources.**

- `0x8000181c` is BPM×24, copied from `0x80001814` once per frame at `0x4000ca9a` (C).
- `0x80001814` is clamped to 720..7200 by `set_tempo` `0x4009c708` (C). The MIDI-clock writer
  `0x40005c2c..0x40005c4a` clamps it too (C).
- Do **not** use `0x80001818`/`0x80001824`. The MIDI-clock path clamps them to 600..7320
  (`0x40005bf2..0x40005c1a`, C).
- The sample's BPM×24 is settings `+0x114`. The ATTR page prints it as `/24` with two decimals
  (`0x4006e72c..0x4006e75a`, C).

**Dry.**

- The resolve `0x40007d80..0x40007dbc` reads lane `+28` (TSTR). If it is 1 (AUTO), it reads settings
  `+0x110` via voice `+8`. A PICKUP 0 becomes 2. It stores the result in voice `+24` (C).
- The only reader of lane `+28` is `0x40007d80`. The stock run's read census (OT_RW over the lane
  records, §7.2) shows 1600 reads, all from that PC (C).
- **H1 writes `clr.b 28(fp)` for a repitch track.** The resolve then yields 0 on the same pass, since
  `0x400041c4` runs after H1.
- The next frame's first pass reads the previous frame's lane record, which was zeroed then (C:
  `0x40007a02..0x40007a1a` builds the lane pointer from the render's frame argument).
- Mode 0 sets the 1:1 stepper (`+128..+140` = 0,1,0,1 at `0x40007ee4`). The main loop
  `0x40008890..0x400088a6` then advances the source once per delivered frame (C).
- In mode 0 the pitch-derived stream quantities cancel: `a3 = a0`, `a5 = 2^31/a0`. So does the voice
  `+3` flag, which needs mode ≠ 0 (`0x40008190..0x40008226`, C).

**Direction.**

- The stream engine sets voice `+36` from lane `+6` − `0x4000`, or 1.0 when `≥ 0x7f00`. Its sign
  chooses forward (`0x40008866`) or reverse (`0x40008e3c`) (C, `0x40007a3a..0x40007a78`).
- The render uses \|RATE\|. So reverse, tape stops and RATE p-locks work dry with no extra code.

**Hooks for item 3, with liveness** (H1 at `0x40004100`).

- No branch targets inside `0x40004102..0x40004107`. Only `0x400040da`/`0x400040e4` branch, and they
  go *to* `0x40004100` (C). Every second-pass path converges there.
- **Live in:** `acc0` (stock pitch×rate), `d6` (shift), `a3`, `fp`, `a5`, the stack frame.
- **Must leave:** `d0` = the increment, `36(a3)` written, `acc0 == 0` (`0x400041fe` accumulates into
  it), MACSR unchanged. Then `jmp 0x40004108`.
- **Dead** (written before read up to the epilogue, C): `d1 d2 d3 d4 d5 d7 a0 a1 a2 a4 a5`, and `d6`
  after the shift (`0x40004126` reloads it).
- No register needs saving on the cheap path.

**Alternatives for item 3.**

- **The scale window is FORCED.** It must lie between the stock computation and the `+36` store,
  `0x40004084..0x40004107`.
  - Scaling only the DSP copy (`0x40004116`) desynchronises the ColdFire accumulator, so frames are
    delivered at the stock speed and consumed at another ✗.
  - Rewriting the lane PTCH so stock produces the ratio cannot be exact: the table is
    2^(i/480) and quantised ✗.
- **Within the window, the site is CHOSEN.**
  - (a) `0x40004100` alone (proposed): one detour, mask included.
  - (b) A pitch hook at `0x4000409e` (8 B: `mvzw (fp),d0; mov3q #1,d6; cmpi.w #0x4000,d0`) plus a
    second hook to scale, tag and mask. Stock then computes the RATE part. Costs two detours and buys
    nothing, because the rate-only form is exact.
  - (c) `0x40004108` (6 B, reached by both passes): would need its own pass test and re-store ✗.
- **The dry mechanism is CHOSEN.**
  - (a) Lane `+28 := 0` from H1 (proposed): no extra site.
  - (b) A detour at the resolve, `0x40007d96` (8 B) or `0x40007dbc` (8 B), mapping 4..6 → 0: one more
    detour, but it decides dry even when the gate is off.
    - Stock with raw 4..6 in voice `+24` behaves as NORM: only `== 3` and `!= 0` are tested,
      `0x40007ede`, `0x400082a8`, `0x4000847e` (C).
    - "Plays exactly as stock" for an **out-of-range** repitch track is therefore ambiguous: NORM-like
      raw, or OFF. §5 decides.

### 2.2 Item 2's runtime counterpart, AUTO and the gate (§3 agreement)

The runtime gate in H1 has a candidate test and a gate.

**Candidate.** Any of these makes the track a candidate:
- lane `+28` ∈ {4,5,6};
- lane `+28` = 1, and the voice `0x800049d8 + 168t` has a non-null `+8` whose settings `+0x110` ∈
  {4,5,6}.

**Gate.** The gate is on when all of these hold:
- the track is a candidate;
- the machine byte `(a5)` ∈ {0,1} (ST/FL);
- settings `+0x114` ∈ [720,7200];
- `[0x8000181c]` ∈ [720,7200].

The candidate test uses the same modes and range as `rp_ui_gate`.

| source | used by `rp_ui_gate` (retained) | used by H1 | when they differ |
|---|---|---|---|
| TSTR | Part DB page-2 byte | lane `+28` = live byte `0x80000834+72t`, copied each frame by `0x4000cb3a` (C) | never once the editor has stored (I) |
| machine | Part DB `+0x8eda2+t` | `0x80000eb4[frame*8+t]` (C), which also chose the render | before the first transport run (retained code comment) |
| sample | Part slot → `0x100d5b30`/`0x100b14f0 + slot·0x448` | voice `+8`, set at the trig by `0x4000f4dc..0x4000f4e0` to the same arrays (C), **including sample-slot locks** | sample locks; a slot change not yet retriggered |

**Recommendation (CHOSEN).** For every candidate, call `rp_swap(t)`. Then apply repitch only if the
gate is on **and** `rp_prev[t] == 1`, so QUAN is applied exactly when the slot holds QUAN (the DB
truth after the swap). Take the BPM from the voice, which is what is audible. The alternative is the
pure runtime gate: QUAN could then read a PTCH value under a sample lock. §5 decides which matches
the shipped module.

### 2.3 Item 1: TSTR seven positions (STATIC and FLEX)

**Descriptors** (C).
- `0x400d5f38[mtype]`: ST `P = 0x400d301c`, FL `0x400d31ae`, PU `0x400d3664`.
- TSTR is slot 10 (`TSTR` name at `E+0x4e+60`).
- Count (u32) at `P+0x9a+40`: `0x400d30de` / `0x400d3270`, value 4.
- Formatter `P+0xca+40` = `0x4003b6a4`.
- Widget `P+0xfa+40` = `0x40046c28`.
- PICKUP has its own entries (`0x400d3756`, `0x400d3786`), left untouched.
- kb/memory-map's "FLEX = `0x400d2fe4`, STATIC = `0x400d3176`" is swapped against the machine table
  and the retained `NAME_ST`/`NAME_FX` (C/I). Worth correcting by the dirty side.

**Widget.**
- `0x40046c28` is the 4-position select: bound `moveq #3`, icons `0x400be306`.
- `0x40046ab4` is a 5-position copy (bound `moveq #4` at `0x40046b08`, icons `0x400be316`: five 17×7
  records `0x400be28e..0x400be2de`). It has **no reference in stock**: no long pointer, and no
  pc-relative or absolute call in the full objdump (C).

| option | pros | cons |
|---|---|---|
| (a) poke `0x40046b08` → `7006` and `0x40046b9e` → `rpk_glyph_tab`; TSTR → `0x40046ab4` (proposed) | 2 pokes, no code; the RPCH-only build uses it **unmodified** (5 stock glyphs) | octabam's `REPITCH` may claim it (conflict already declared) |
| (b) a 372-B copy in our unit (absolute addressing only, relocates by copying) | no stock-widget edit | 372 B; a stock copy in our unit |

**Formatter.** `0x4003b6a4` has a 4-entry table `0x400a7e2e` (OFF, AUTO, NORM, BEAT; strings at
`0x400b4e78`, `0x400b571e`, `0x400b5728`, `0x400b572d`). Its bound `moveq #4` lets index 4 read past
the table (C). New `tstr_fmt(buf,v)`:
- `v ≤ 6` → `table7[v]` (the stock string addresses plus `RPCH`, `RPS9`, `RPSP`);
- else `0x400b442a` (`???`);
- then `jmp 0x40013a08` (sprintf), the stock tail convention.

FORCED because PICKUP shares the stock formatter.

**Load path.** Raw 4..6 is what is stored. No loader clamp of the Part's page-2 bytes was found; it was
not searched exhaustively (I). §5 loads real projects saved by the shipped module.

### 2.4 Item 2: audio editor ATTR, TIMESTRETCH row

All C.

**Label.**
- The row labels come from the table `0x400b2c18`; row 2 is `TIMESTRETCH` (`0x400b6923`).
- The value chain is `0x4006e6ec..0x4006e724`: settings `+0x110` 0 → `OFF`, 2 → `NORMAL`, 3 → `BEAT`,
  else `pea 0x400b94f6` (`ERROR`) and `bra.w 0x4006e878` (the common print).
- **H2 at `0x4006e71c`** is a branch target (`0x4006e710`); nothing targets its interior.
  - New code: `d0` 4/5/6 → `pea REPITCH/RPS9/RPSP`, else `pea ERROR`; then `jmp 0x4006e878`.
  - Live: `d0`, `d3`, `a2`, the stack. All are preserved.

**Up.**
- Handler `0x4006edc8`, referenced from `0x400ce52a/532/6d8/6e0` (I: key and encoder entries).
- Row 2 (`d0 == 2`, settings in `a0`) is at `0x4006ee48..0x4006ee66`: 0 → 2, 2 → 3, else nothing;
  then `bra 0x4006eef0` (`movea.l (sp)+,a2; jmp 0x4006dbdc`).
- **H3 at `0x4006ee48`** (6 B: `move.l 272(a0),d0; bne.s`).
  - New code: 0→2→3→4→5→6 (RPCH-only: …→4), store, `bsr rp_refresh`, `jmp 0x4006eef0`.
  - Free: `d0/d1`. `a0` is the settings pointer. The stack is unchanged.

**Down.**
- Handler `0x4006eefc`, referenced from `0x400ce510/518/6be/6c6`.
- Row 2 is at `0x4006ef7c..0x4006ef9c`: 2 → 0, 3 → 2. The tail is `0x4006f026`.
- **H4 at `0x4006ef7c`** (6 B: `move.l 272(a0),d0; cmp.l d0,d1`).
  - New code: 6→5→4→3→2→0, store, `bsr rp_refresh`, `jmp 0x4006f026`.

**Alternative for "every ATTR edit calls `rp_refresh`".** Detour both common tails instead:
`0x4006eef0` and `0x4006f026`, 8 B each, `movea.l (sp)+,a2; jmp 0x4006dbdc`. That covers every row
(GAIN, TEMPO, …) for two more detours. Only TIMESTRETCH can change the gate: the ATTR tempo stays
within 30–300 BPM (I). Choose by the §5 screen comparison.

**Persistence.**
- The `.work`/`.ot` text key `TSMODE` is parsed by `0x40086c32..0x40086c5a` with atoi and stored in
  `+0x110` **unvalidated** (C), so 4..6 survive loading on any firmware.
- The writers `0x40089316`/`0x40089540` print `TSMODE=%d` (C).

### 2.5 Item 5: every increment the firmware writes

All C. They were found statically: these are the only references to the record pointer
`0x80001c80`, plus the loop that sets it at `0x4000d414`. The stream engine only gets
`entries = header+16`.

| writer | machine | value | bits 2-3 |
|---|---|---|---|
| `0x40004028` | ST/FL/PU, empty pass (count ≤ 0) | literal `0x04000000` | 0 |
| `0x40004116` (from `+36`, written only at `0x40004104`) | ST/FL/PU | computed | **arbitrary**: T1 measured `0x046100ab` → bits 2-3 = `10` (would read as RPSP) |
| `0x40004448` | THRU | literal | 0 |
| `0x4000468c` | NEIGHBOR | literal | 0 |
| `0x40004804` | types 5–7 (`0x400047f0`) | literal | 0 |

- `0x400e1d56` (`addi.l #0x04000000`) is DSP payload data, not code.
- Render state `+36` has one writer (`0x40004104`). The voice reset `0x40006820` clears render `+4`
  only.
- **So H1 must mask the computed path** (`andi.l #0xfffffff3,d0`; FORCED: it is the only computed
  writer).
- Bits 0-1 never reach the DSP, so clearing them as well changes no `l:$40`. It changes only the
  ColdFire accumulator.

### 2.6 Item 7: the per-frame call point for `rp_swap`, and the cheap path

- `rp_swap` is called from H1: once per frame, on the second pass, per ST/FL/PU track.
  - For every candidate (§2.2).
  - For any other ST/FL/PU track whose `rp_prev[t] != 0` (forgotten, held, or last seen on).
- Cheap path for a stock track: TSTR byte test, optional AUTO dereference, `tst.b rp_prev(t)`, mask,
  store, `jmp`.
- `rp_swap` preserves every register and calls no kernel or UI primitive. `rp_caption` writes 4 bytes
  into the descriptor name fields. So it is legal from the frame ISR (CLAUDE.md "never call a UI or
  kernel primitive from a frame hook").

**Alternatives.**

| option | pros | cons |
|---|---|---|
| (a) from H1 (proposed) | no extra site | swaps after this frame's lane copy, so a transition frame plays one frame with the old domain's PTCH/QUAN value (the base word changes for the next frame) |
| (b) a pass over 8 tracks before the copier `0x4000cb2a` (e.g. at `0x4000cae8`) | the swap precedes the copy | SIDECHAIN_COMPRESSOR already detours `0x4000cae8`; needs a second gate computation from the live bytes |

THRU, NEIGHBOR and other machines never reach H1. That is preferable: see risk R5.

### 2.7 Item 6: the RPCH-only variant

The same H1 with mode fixed at 0: no tag, and the mask is optional, because without the kernel bits
2-3 mean nothing. TSTR count is 5. The widget is the stock `0x40046ab4` **unmodified** (P3 dropped,
P2 kept). `tstr_fmt` has 5 entries. H2 knows only `REPITCH`. H3 stops at 4. There are no DSP hooks
and no Y claim, so SPRING REV stays.

**Build form.** Make the differences **values**, not `.ifdef`: `RP_MAXMODE` 4/6 as a link-time
constant in `cmp`, the mask as a constant, the pokes in the manifest. Then one source serves an
octabam setting or a separate builder. That choice is the user's (spec §4).

**Open.** A project saved with the full module and holding TSTR or TSMODE 5/6, loaded in RPCH-only.
Treat it as RPCH, or as off? The 5-position widget draws nothing above 4: bound `bcs` at
`0x40046b0c`.

### 2.8 Item 4 (QUAN)

`idx = rk_bucket(lane+0 >> 8)` read in H1. Lane `+0` at render time is base plus p-locks plus scenes
(crossfader stage `0x4000cc96..0x4000cf3e`) **plus LFO**: the LFO stage `0x4000cf50..0x4000d096` adds
into lane words for destinations < 12 (C).

- If QUAN must ignore LFO-on-PTCH, snapshot lane `+0` for the 8 tracks before the LFO stage. That is a
  detour at `0x4000cf40` (10 B, a branch target, about 20 instr per frame).
- Where trig note transposition enters the lane is not located (I: probably the `0x80001658` words in
  `0x4000cbfc`).
- Both are settled by §5, per spec item 3.

---

## 3. Connection to the retained code

| retained | how the new core uses it |
|---|---|
| `rp_swap` (d1 = t) | `bsr` from H1 for candidates and `rp_prev[t] != 0`; afterwards H1 reads `rp_prev[t]` (== 1 → QUAN domain) |
| `rp_prev` | cheap-path test; `0xfe` (RP_HOLD) = not repitch for that frame (or keep the last decision; §5) |
| `rp_ui_gate` | not called by the core (cost); its rules are mirrored by the H1 gate (§2.2) |
| `rk_bucket`, `.rk_ratios` | H1: `idx`, then `p = ratios[2·idx]`, `q = ratios[2·idx+1]`; make `.rk_ratios` global (it is a local label in the file) |
| `rp_refresh` | H3/H4 after the store (UI task) |
| `rp_forget/apply1/apply2`, `rp_reload` | untouched |
| `quant_widget`, `quant_fmt`, `quant_step`, `qdial1..4` | untouched |
| `rpk_glyph_tab` | P3's icon table operand |

---

## 4. The RPCH-only variant

See §2.7. Cost per frame is the same as the full build minus nothing measurable. The DSP side
disappears entirely.

---

## 5. Test plan

### 5.1 Black-box equivalence harness (spec §5)

**Runner.** `ot_emu` (a scratch octabam copy only; never rebuild the shared clone or libunicorn).
- Both images are booted the same way: the shipped FINAL REPITCH image (`out/OCTATRACK_REPITCH_REPEAT98_KYOTI.bin`
  / its `mainos_*.bin`) and ours.
- Same card, same **real hardware-exported** project, `--sequencer --internal-clock --dsp`, and the
  same `--step N:poke:` script.
- Scenarios fork from one load with `--scenario`.
- The harness never disassembles, diffs or watches PCs inside the shipped image's module code. It
  records only the following.

1. **Increments.** Two observation points, both outside the module code.
   - The CF → DSP host-port stream (`--hostport-log`), parsed per voice record: header `+8` per track
     per pass.
   - A small scratch-copy ot_emu patch logging `x:$40`/`y:$40`, `x:$418` and `LC` at the stock voice
     kernel entry (A `P:0x40b`, B `P:0x20e`, our DSP facts in the module README). That address is
     identical in both images, because the DSP kernel is unchanged.
   - Compare per (frame, core, track offset, pass): **bit-identical**.
2. **Screens.** `--lcd` plane dumps after `--live-script` key sequences: PLAYBACK page 1 (PTCH/QUAN
   caption and dial), page 2 (SETUP: TSTR selector), and the audio editor ATTR page. Compare pixel
   for pixel.
3. **Audio.** `--audio-out` WAV, one scenario per soloed track. Compare RMS per 50 ms window and a
   1/3-octave spectrum within a tolerance. Never sample-exact, because the ColdFire workload differs.

**Setting the matrix by runtime poke** (the `tools/load_audit/la_run.py` pattern; no project file is
edited):

| what | where to poke |
|---|---|
| TSTR | Part byte `0x400e21e0 + 0x8ed80 + part·0x18b2 + 0x1da + 30t + 6m + 4`, and live `0x80000834 + 72t` |
| TSMODE / sample BPM | settings `+0x110` / `+0x114` of the slot (`0x100d5b30` or `0x100b14f0 + slot·0x448`) |
| tempo | `--step N:call:0x4009c708,<bpm24>` |
| PTCH/QUAN, RATE | base word `0x80000a50 + 64t + 2·flat`, live byte `0x80000810 + 72t + flat`, and the Part page-1 byte |
| SETUP RATE mode | live `0x80000833 + 72t` |
| ST/FL/PU | tracks of real projects that already use each machine |

**Matrix.** TSTR 0..6 × TSMODE 0/2/4/5/6 × ST/FL/PU × tempo in range and out (sample BPM 0, 719,
7201) × QUAN 9 stops × RATE {127, 96, 64, 32, 0} × RATE mode PTCH/TSTR × forward/reverse. Add the
transition and edge scenarios:
- the gate turning on and off mid-play;
- Part change and RELOAD PART (RP_HOLD);
- a project load;
- a sample-slot p-lock under AUTO;
- LFO on PTCH; a trig note;
- a sample shorter than 6144 frames (stock forces OFF there, `0x40007d70`);
- MIDI-clock tempo;
- a machine round trip ST → PU/THRU → ST in a repitch mode (R5).

**Oracle check first** (START_HERE's "grade against the spec"). Run the harness once on stock against
stock, and once against a deliberately wrong build (for example floor versus round in the scale). It
must report IDENTICAL for the first and catch the second. Poison the scratch RAM where relevant
(Unicorn zero-fills memory).

### 5.2 DSP

`vem_dsp.asm` is unchanged. Re-run its existing bit-exact and boot checks; they must still pass
(spec §5).

### 5.3 Load

Use the load-audit ot_emu (`OT_ISR_OUT`, IPL ≥ 5 episode instructions) on a real project with 0, 4
and 8 repitch tracks, and with 8 AUTO stock tracks. Compare against stock and against the shipped
image (outputs only).

### 5.4 Hardware

The FLASHING §4 REPITCH checklist on the MKI before any promotion (spec §5). Before the first flash,
add a diagnostic build that toasts the gate state and mode: the emulator's blind spots are the ISR
and the DSP timing (CLAUDE.md).

---

## 6. Risks, unknowns, effort

### 6.1 Risks and unknowns

| # | risk / unknown | handling |
|---|---|---|
| R1 | Bit-identity of `l:$40` with the shipped module depends on details the spec leaves open: floor or round in `N/D`, clamp before or after the fold, the mask covering bits 2-3 or 0-3 (the latter is invisible in `l:$40`) | the harness; the oracle check first |
| R2 | Transition frames: swap after the lane copy (§2.6); pass 1 of the gate's first frame may resolve stretch once (§2.1); RP_HOLD frames | compare transition scenarios; option (b) of §2.6 if needed |
| R3 | QUAN under LFO and note: post-LFO lane `+0` or pre-LFO snapshot | §2.8 option; the harness decides |
| R4 | Gate data source (voice `+8` versus the Part slot) under sample locks | the hybrid gate (§2.2); the harness |
| R5 | **Retained `rp_swap` can invert the domains** on a machine round trip. On PU/THRU, `rp_ui_gate` = 0 sets `rp_prev` = 0 without swapping (`.sw_none`). Back on ST/FL, 0 → 1 swaps QUAN out as if it were PTCH. H1 never calls it for THRU/NEIGHBOR, but PU reaches H1, and the retained dial poll `quant_widget` runs on any page whose slot-0 formatter is `0x4003b4b0`, which includes PICKUP (I) | test it; if the shipped module does the same it is out of scope for the rewrite, so report it to the user rather than fix it silently |
| R6 | Stack: H1 adds about 80 B (`rp_swap` → `rp_ui_gate`) on whatever stack the frame ISR interrupted (the watch-pc runs showed two different stacks) | the old core called the same chain per frame on hardware (I); keep H1's own frame at 0 |
| R7 | `rp_swap` writes Part DB, SRAM shadow and dirty flags from the ISR while the UI task may edit the same Part | inherited from the retained design |
| R8 | The 5-position widget: a static scan says no references; nothing else in stock was found using it at runtime | the RPCH-only variant needs it stock: assert the bytes per variant |
| R9 | RPCH-only with 5/6 from a full-module project | the user decides (§2.7) |
| R10 | Out-of-range repitch track: NORM-like (raw mode reaches the stream) or OFF | the harness; switch by adding the resolve detour (§2.1 b) |

### 6.2 Effort, phased

1. **Harness** (§5.1): scratch ot_emu patch, scenario runner, comparator, oracle check. 1–2 sessions.
2. **H1 core:** gate, `rp_swap`, dry, exact scale, tag and mask, with unit checks of the arithmetic
   against a Python model of spec item 3. 1 session.
3. **UI:** P1–P4, `tstr_fmt`, H2–H4, wired to `rp_refresh`. About 1 session.
4. **RPCH-only variant.** Half a session.
5. **Equivalence passes:** resolve R1–R4 and R10 against the shipped image; load measurement. 1–2
   sessions.
6. **Packaging:** octabam manifest (DRAM units, the conflicts), standalone builder, KYOTI re-pin,
   Bugbuild. 1 session.
7. **Hardware:** the FLASHING §4 checklist.

---

## 7. Provenance

### 7.1 Files read

| source | used for |
|---|---|
| `reference/handoffs/VARISPEED_SPEC.md` (all) | requirements, interfaces, protocol |
| `CLAUDE.md` (all) | rules |
| `START_HERE.md` | onboarding, filtered with `grep -v` on the keyword set |
| `reference/kb/caves.md` (all) | §0 descriptor table, §1/§2/§2b caves, §5 DRAM units |
| `reference/kb/memory-map.md` L40–50, 254–280, 510–520, 600–640, 733, 1125–1200 | frame ISR `0x4000aad0`; tempo chain; voice state `0x800049d8`/`0xA8`; page-1/page-2 publish path; base words `0x80000a50`; copier `0x4000cb2a`. All re-verified (C). Lines carrying the keyword set were skipped. |
| `reference/kb/techniques.md` L480–520 | CF METER frame budget |
| `COVERAGE.md`, `ARCHITECTURE.md`, `file-format.md` | grep lines only |
| `VARISPEED_RETAINED.s` (all) | interfaces; equates `SET_STATIC`/`SET_FLEX`/`DB_PTR`/`PTCH_FMT`/`KNOB`/`STEP_PTCH`, each re-checked where used (C via the descriptor dump) |
| `octabam-modules/repitch-repeat98-kyoti/` | `rpk_glyphs.s`, `patch_repitch_reload.s`, `vem_dsp_ptable.py`, `README.md` (all); `vem_dsp.asm` lines 1–140 (DSP entry state, `l:$40`/`y:$40` tag, `P:0x40b`/`P:0x20e`) |
| `tools/load_audit/la_run.py`, `tools/emu_rtos.py`, `tools/load_audit/ot_emu_load_audit.patch` (header, OT_RW hunk) | emulator method, Part poke offsets |
| `~/Documents/octabam/tools/emu/ot_emu/main.cpp` | option parsing only (grep) |
| `reference/handoffs/REC_TRIG_MUTE_SCOPE.md` L385–405 | filtered |
| other modules' manifests and sources | grep lines for site overlap: MUTE_MODES `0x4000d498`, SIDECHAIN `0x4000cae8`, no overlap with H1–H4/P1–P4 |

### 7.2 Image facts: objdump of `out/raw/section_3_MAIN_OS.bin`

Full listing in `out/clean-room/stock.dis`. Ranges disassembled:
- render and pass routines: `0x40003f96..0x40004268`, `0x400043a0..0x40004480`,
  `0x40004632..0x40004700`, `0x400047d0..0x40004840`;
- copier, crossfader, LFO and voice loop: `0x4000ca80..0x4000cd00`, `0x4000cd00..0x4000d0f0`,
  `0x4000d300..0x4000d580`;
- render-table dispatch: `0x4000bf60..0x4000c060`;
- voice reset: `0x40006820..0x400068e4`;
- stream engine: `0x40007960..0x40008fa0` (`out/clean-room/pos_engine.dis`);
- voice start: `0x4000f450..0x4000f560`;
- tempo paths: `0x40005bd0..0x40005c56`, `0x4009c708..0x4009c740`;
- widgets: `0x40046ab4..0x40046d20`;
- formatters: `0x4003b64c..0x4003b720`;
- ATTR page: `0x4006e600..0x4006e8a0`, `0x4006eda0..0x4006f034`;
- TSMODE parser: `0x40086c20..0x40086c70`;
- other: `0x40094170..0x400941e0`, `0x40096dc0..0x40096e20`, `0x40017a10..0x40017a50`,
  `0x4001a5c0..0x4001a5f0`, `0x40019d90..0x40019dac`.

Data and search scripts:
- `out/clean-room/desc.py`: machine table `0x400d5f38` and the STATIC/FLEX descriptor records.
- `out/clean-room/findlong.py`: 32-bit pointer searches.
- Inline Python: the tables `0x400d6400..0x400d64e0`, `0x400aa294`, `0x400aad08`, `0x400aae0c`,
  `0x400be306/316` and the icon records; strings `0x400a7e1e/2e/44`, the `TIMESTRETCH`/`NORMAL`/`BEAT`/
  `TSMODE` references.
- Whole-listing greps: `#67108864`, `0x80001c80`, `0x800062a4/8`, `@(272)`, the `0x8000181x` words, the
  `0x40046ab4` references, and the branch targets into each detour window.

### 7.3 Emulator runs (stock only)

Binary: `ot_emu` built in `../octatrack-kyoti-fw-octabam-port/out/la/octabam/out/emu/` (load-audit
patch). Run there, not rebuilt.
- Image: `.../la/img/stock.bin`, byte-identical to `out/raw/section_3_MAIN_OS.bin` (`cmp`).
- Card: `otdemo.img`, project KYOTI/OTDEMO.

1. `out/clean-room/run1`: 400 frames.
   - `OT_RW` read census over lane records, render state, voice state, live bytes, base words and the
     tempo words (`rw.txt`).
   - `--watch-pc 0x40004104,0x40007dbc` (`log.txt`).
   - Source of: the only readers of lane `+28`/`+27`/`+0`/`+6`, voice `+24`, render `+36`; the resolve
     values; the increments.
2. `out/clean-room/run2`: 30 frames.
   - `--watch-pc 0x400040a0`.
   - `--mem-dump` of base, live, lane, voice and render state.
   - Source of: the lane word = `ui<<8`, and the T1 increment arithmetic.

### 7.4 Blacklist statement

I did not open any blacklisted file. Two disclosures:

**(1) A misdirected command printed blacklisted file names.** A `cd` into a non-existent directory
failed, and the `grep -l -i 'repitch|rpch|repeat98'` that followed ran in the repository root. It
printed only **file names**, no contents. Names seen:
- `tools/repitch_ot_emu_trace.patch`
- `tools/varispeed_emus_test_beat.py`, `tools/varispeed_emus_ab_speeds.py`
- `tools/repitch_probe_kyoti.cpp`, `tools/varispeed_emus_dsp_*`
- `tools/build_repitch_repeat98_kyoti.py`, `tools/varispeed_emus_dsp.asm`
- `tools/varispeed_emus_model.py`, `tools/varispeed_emus_sp_reference.py`
- `tools/varispeed_emus_ab_pack.py`, `tools/varispeed_emus_ch12_listen.py`
- plus NOTES/README/CREDITS and similar.

**(2) The session's auto-loaded memory index.** The memory index (`MEMORY.md`) was injected into this
agent's context at start; I did not open any memory file. It contains one-line summaries of the old
implementation's history. None of its facts were used; each fact here was re-derived above. Examples:
- base words `0x80000a50+64t`: also in kb/memory-map and the retained code;
- the dirty-flag byte width: in the retained code;
- RELOAD PART: in `patch_repitch_reload.s`.

**Also read, on the allowed list.** The module `README.md` names the old hook *kinds* ("rate gate,
pitch gate, rate hook, TSTR resolve, three audio-editor ATTR hooks") and the 5-position widget
`0x40046ab4`. The widget was re-verified (C). This design hooks neither a pitch gate nor the TSTR
resolve.
