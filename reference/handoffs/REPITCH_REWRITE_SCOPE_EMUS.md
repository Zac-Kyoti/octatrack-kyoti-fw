# VARISPEED_EMUS: scope addendum (EMUS, the second pair, the trig latch, item 11)

Written 2026-10-14 by a **clean** agent. It extends `REPITCH_REWRITE_SCOPE.md` (the "first scope")
for the 5-position design in `REPITCH_REWRITE_SPEC.md` (revised 2026-10-14). Sources: the stock
1.40C image (`section_3_MAIN_OS.bin`, sha256 `164f3122…`, re-checked), stock-only emulator runs,
`reference/kb/*`, and the allowed own code. §9 lists every source and the blacklist statement.
Nothing was implemented, built, flashed or committed.

Marks: **C** = confirmed on our image (objdump, or a stock emulator run); **I** = inferred.
Addresses are virtual (file offset + `0x40000400`). `DB` = `[0x46c82456]`, the working bank blob;
Part offsets are DB-relative as in the retained code (`OFF_P1 0x8edaa`, `OFF_P2 0x8ef5a`).

---

## 1. Summary

### 1.1 Main findings

1. **TSNS** lives in the Part at `OFF_P2 + 30t + 6m + 5`, the SRAM shadow at `0x100a50a8 + part·0x18b2 + 30t
   + 6m + 5`, the live byte `0x80000835 + 72t`, and the lane at `0x80000510 + 384·frame + 48t + 29`. **Page 2
   has no base word**: the copier moves the live bytes straight into the lane every frame. Its only stock
   consumer is the time-stretch **analysis task** (`0x40098a5c`, task context), which reads lane `+29` and
   uses it as an index into the 128-entry threshold table `0x400d7c7c` (C). Nothing writes lane `+24..+31`
   during play except the copier (C). That makes lane `+29` the per-frame composed value, and the place a
   page-2 lock mod would have to write. **EMUS is read there.**
2. **A second parked byte exists: NEIGHBOR's page-2 slot 5** (`OFF_P2 + 30t + 23`). The read census shows
   no apply-path reader. It is saved by the bank writer (whole 240-byte page-2 block, `0x4008a3b6`) and
   loaded by the bank parser (`0x4008c58a`), then clamped to 0..127 by a **Part validator `0x40002318`**
   (C). That validator also corrects the first scope (§7). The other NEIGHBOR '---' bytes qualify in the
   same way.
3. **The SRC SETUP page** is one page object (`0x400bb7d0`). Draw `0x4003c830`, open `0x400584d0`, and
   seven encoder records → `P2EDIT 0x4003a474` (C). The renderer **does** read the descriptor widget column,
   formatter column and name field for TSNS (`0x4003ce38`, KNOB fallback), and draws each slot's dial
   *before* its caption in the same loop (C). **P2EDIT never calls a per-slot step handler**: its only
   delta conversion is `jsr 0x4003249c` at `0x4003a566` (C). So EMUS needs: two widget pokes, one call
   redirect, and no renderer shims.
4. **The trig latch** is inside H1 itself. The voice loop's per-track trig byte `0x46104d0c + t` **bit 4**
   means "a new sound starts this frame". It is still set while the second-pass render (H1) runs and is
   cleared after it (`0x4000d534`) (C). It is the same condition that sends the DSP its trig-start bit
   (C). The latched engine can be kept in **render state `+36` bits 2-3**, stock's own per-track
   increment, so no new state is needed. **RTRG retrigs do not pass through the trig byte**: the render
   restarts the voice itself (`0x4000421c`) (C). They keep the trig's engine.
5. **Item 11's root cause is wider than PICKUP/THRU.** The swap is keyed on a gate that depends on the
   *current machine*, while the slot it swaps is per machine and the park is shared. ST→PU→ST inverts the
   domains, and ST↔FL with different gates corrupts across machines. The fix: **per-machine gate, per-machine
   `rp_prev`, and per-machine parks.** Then a machine change never swaps anything, and the PICKUP poll is
   inert (§6).
6. **A related, unlisted bug class**: stock bulk writers (SRC page paste, track paste, the PART menu's
   paste/clear/undo) rewrite TSTR together with domain-consistent values, and bypass `rp_forget`. That is
   the same mechanism as the RELOAD PART bug the retained `rp_reload` fixed (§6.5). This is an open
   question.

### 1.2 Revised full hook list

| # | site | kind | purpose | class |
|---|---|---|---|---|
| H1 | `0x40004100` (8 B) | `jmp` detour, frame ISR | per-frame core: per-machine `rp_swap`, VARI gate (raw 4 / AUTO+TSMODE 4), dry (lane `+28 := 0`, also when out of range), exact QUAN×tempo×RATE, clamp, **engine latch** (trig byte bit 4 → EMUS from lane `+29`; else the tag already in `36(a3)`), tag, mask bits 2-3 on every other ST/FL/PU increment | FORCED window, CHOSEN site (first scope §2.1) |
| P1 | `0x400d30de`, `0x400d3270` | poke u32 4→**5** | TSTR count, STATIC/FLEX | FORCED |
| P2 | `0x400d313e`, `0x400d32d0` | poke u32 `0x40046c28`→`0x40046ab4` | stock 5-position widget, **unmodified** | CHOSEN |
| P4 | `0x400d310e`, `0x400d32a0` | poke u32 `0x4003b6a4`→`tstr_fmt` | OFF AUTO NORM BEAT VARI | FORCED (PICKUP shares the stock one) |
| H2 | `0x4006e71c` (10 B) | `jmp` detour, UI task | ATTR TIMESTRETCH label for 4 | FORCED |
| H3 | `0x4006ee48` (6 B) | `jmp` detour | ATTR up 0→2→3→4, `rp_refresh` | FORCED |
| H4 | `0x4006ef7c` (6 B) | `jmp` detour | ATTR down 4→3→2→0, `rp_refresh` | FORCED |
| **P5** | `0x400d3142`, `0x400d32d4` | poke u32 `0`→`emus_widget` | TSNS slot's widget (STATIC/FLEX slot 11) | CHOSEN (vs a detour at `0x4003ce38`) |
| **R1** | `0x4003a566` (6 B `jsr 0x4003249c`) | call redirect → `emus_p2step` | one detent = one EMUS value | FORCED (P2EDIT's only delta conversion); site CHOSEN (vs entry detour `0x4003a474`) |
| — | retained, unchanged sites | — | `qdial1..4`, `quant_step` at `0x400d3146`/`0x400d32d8`, `rp_apply1` `0x40009094`, `rp_apply2` `0x40009e00`, `rp_reload` `0x4004aab4` | as shipped |
| (opt) | `0x40027e4c`, `0x4002b654`, `0x4005a5a8` | hold/forget wrappers | SRC page paste, track paste, PART menu ops (§6.5) | CHOSEN if the user wants it |

Dropped from the first scope: **P3** (the glyph pokes) and `rpk_glyphs.s`.

**Count.** The core has 9 items: 5 code sites (H1-H4, R1) and 4 poke pairs (P1, P2, P4, P5).
- **FORCED: 7** (H1's window, P1, P4, H2, H3, H4, R1).
- **CHOSEN: 2** (P2, P5).
- In addition, H1's and R1's exact sites inside their windows are chosen.
- The optional bulk-writer wrappers would add 3 CHOSEN detours.

**Retained wiring to confirm.** The PLAYBACK page-1 dial is drawn at `0x4004e7a0` from the descriptor widget column (C,
run3: `a0 = 0x400479b4` read from STATIC `P+0xfa`). The four `qdial` sites draw the **SETUP pages of MIDI
NOTE, LFO, FX2 and FX1** (C: fixed record bases `0x400d3f20`, the `0x400d3b12` enable words,
`0x400d5fdc[id]`; value blocks `0x8f262/0x8f078/0x8f084/0x8f07e`), and `PTCH_FMT` occurs only in the
ST/FL/PU descriptors (C, pointer scan). So QUAN's dial on page 1 depends on `quant_widget` sitting in
`P+0xfa` slot 0 (`0x400d3116`, `0x400d32a8`, stock = KNOB). I cannot see the shipped manifest; the
implementation must check that this poke exists.

### 1.3 Units, size, cost

- **New core, about 0.5 KB.**
  - H1 with the latch: about 300 B.
  - `tstr_fmt` (5 entries): about 70 B.
  - H2: about 45 B.
  - H3/H4: about 90 B.
- **Retained, grown, about 1.6 KB.** Measured today: `REPITCH_REWRITE_RETAINED.s` 0x4a0 = 1184 B, `patch_repitch_reload.s` 46 B. The additions:
  - `emus_widget` about 70 B;
  - `emus_fmt` plus strings about 55 B;
  - `emus_p2step` about 80 B;
  - `emus_idx` plus the mode table about 25 B;
  - the second pair in `rp_swap` about 90 B;
  - per-machine gate, prev and parks about 60 B;
  - guards about 15 B;
  - optional background poll about 40 B.
- **Total about 2.2 KB** (first scope 2.4 KB, minus the 644 B of glyphs, plus EMUS). That is still more than octabam's floating ROM run → **DRAM units** (CHOSEN, unchanged; caves.md §5).
- **Per frame (frame ISR, H1, second pass of ST/FL/PU only).**

| track | stock | first scope | this design |
|---|---|---|---|
| ST/FL/PU, not a candidate, `rp_prev[t][m]==0` | 3 | ~16 | ~18 (per-machine index) |
| ST/FL, TSTR AUTO (default) | 3 | ~25 | ~27 |
| VARI track, steady | 3 | ~140-160 | ~150-185 (latch +6 per frame, +20 on a trig frame) |
| optional background poll (whole frame) | — | — | +~70, one gate evaluation |

DSP: the kernel is unchanged; the OT engine costs its mode check, and S950/SP12 cost what the module README measures.

---

## 2. Question 1: TSNS

### 2.1 Where it lives (all C)

| tier | address | evidence |
|---|---|---|
| Part DB byte | `DB + part·0x18b2 + 0x8ef5a + 30t + 6m + 5` | P2EDIT load `0x4003a55a` / store `0x4003a5b4`; run6: `P2EDIT(5,+1)` moved part 1 T8 m0 slot 5 (`0x40172ac3`) `0x40`→`0x41`, `+1,+8`→`0x4a`, `−100`→`0` (clamped to min) |
| SRAM shadow | `0x100a50a8 + part·0x18b2 + 30t + 6m + 5` (= `SHADOW_ADJ` + the DB offset) | `0x4003a5bc` |
| live byte | `0x80000830 + 72t + 5` = **`0x80000835 + 72t`** | `0x4003a60a`; run6 `0x80000a2d` (T8) followed the store |
| base word | **none for page 2** | copier `0x4000cb3a`: `movem.l` of live `+0x20..+0x2b` straight into lane `+24..+35` |
| lane | `0x80000510 + 384·frame + 48t + 29` | same copier; run9 (`--watch-mem`): the only writer of lane `+24..+31` during play is `0x4000cb3e` (240 writes / 120 frames) |
| voice | not stored | TSNS is consumed straight from the lane (§2.2) |

Also written:
- at Part apply (live byte from the snapshot, `0x400091fa`);
- at transport start (`0x4000c132`);
- by the machine/track refresher `0x40001f18` (live p2 := Part p2 of the track's DB machine, `0x40001fe6`);
- by SRC page paste (`0x40028134`);
- by P2EDIT.

Default: **64** in every ST/FL/PU track of the OTDEMO project's four parts (run3 dump).

### 2.2 Who reads it, when, and what stretch does with it

- **Only consumer: the analysis task.**
  - The task body is `0x40098a5c`, created at `0x40098a2c` with stack `0x4610555c`.
  - For each track whose voice machine (`voice+20`) is 0, 1 or 4 and needs a refill, it calls `0x400985ac`. The lane `+29` value is read at `0x40098c8c`, from the frame `[0x800000e0]`, signed.
  - `0x400985ac` passes it to the transient analysis `0x40098388`.
  - There, `0x40098452` indexes **`0x400d7c7c[tsns]`**, a 128-entry threshold curve (`0` … `0x407bf7`).
  - Detected positions go to a 4-slot ring in the voice's analysis state.
  - Census (run1, the first scope's): 4–12 reads per track in 400 frames, all from `0x40098c8c` (C).
- **Task context, not the ISR**; the read happens whenever the task runs. There is no per-voice snapshot of TSNS.
- **On a VARI track**, the TSNS slot holds EMUS. The task still reads it as a threshold index. With values kept in 0..127 the index stays inside the table. The track is dry (mode 0), so the result is inaudible (I).
  - **Constraint:** EMUS values must stay in 0..127. The page-2 renderer and the task both read the byte signed (`mvsb`).
- **No per-frame composed value beyond the lane.**
  - Stock's lock stages touch only lane `+0..+23`: the crossfader loop `0x4000cc02` writes 6 longs per track, and the LFO destinations are below 12 halfwords (first scope).
  - The p-lock table has no page-2 index. Bytes 0..29 are the five page-1 pages and 31 is the sample lock; 30 is unused (kb/memory-map "Step records", L).

### 2.3 Where locks or scene values would land

- A page-2 lock mod must make stock's own consumers obey it, and those consumers read the lane: `0x40007d80` for TSTR at `+28`, `0x40098c8c` for TSNS at `+29`.
- So locks would land in **lane `+24..+29` after the copier (`0x4000cb3e`) and before the voice loop (`0x4000d3fc`)**. That is the same window the crossfader and p-lock stages use for page 1.
- **Design:** H1 reads EMUS from lane `+29`, and the VARI candidate test from lane `+28`, of the frame being rendered (C for the stock readers, I for the hypothetical mod). The one exception is a frame in which `rp_swap` has just swapped (§5.3).

---

## 3. Question 2: the second parked byte

### 3.1 Candidates

NEIGHBOR (`m = 3`) has 6 page-1 and 6 page-2 bytes per track. Each is named `---`, has count `0x80` and min 0, a null formatter, widget and step, and enable nibbles 0 (C, descriptor `0x400d34d2`). THRU's page 2 is also all `---` (C), but THRU is a playing machine.

Every NEIGHBOR byte reads 0 in all four parts of a real project (run3).

**Proposed TSNS park: NEIGHBOR page-2 slot 5, `OFF_P2 + 30t + 23`.** This is the TSNS position. That matters in §3.4.

### 3.2 "Never applied": read census (C)

Run3: a stock load and UI session, with `OT_RW` over all four parts of the bank, their SRAM shadow, the live bytes and the lanes. Analysis in `out/clean-room/p2census.py`. Readers of NEIGHBOR page-2 bytes (`m = 3`, every slot):

| PC | what it is | applies the value? |
|---|---|---|
| `0x400026f2`, `0x4000270a` | **Part validator `0x40002318`**: clamps every machine's p1/p2 bytes to `[min, min+count−1]` from the descriptor | no; it clamps to 0..127 |
| `0x4008c5b0` | bank parser `0x4008be2c`: reads the 240-byte p2 block from the file into the Part, then checksums it | no; this is the load path |
| `0x400208ae..b4`, `0x40020924` | `memcpy` / block copy (whole-Part copies) | no; it moves the byte along with its Part |
| `0x4000aad0` | the frame ISR entry, the PC the patched emulator charges reads to while it stacks registers | no; an emulator attribution (I) |

The per-machine reader `0x400091fa` (Part apply) read only `m = 0/1/2`, the tracks' own machines.

Statically, every other `0x8ef5a` reader reads one machine's slot for the current or page machine:
- P2EDIT `0x4003a55a`;
- the page-2 renderer `0x4003ce0e`;
- the STRT formatter `0x4003b57e` (SLIC, `m` 0/1);
- the STRT/LEN step handler `0x4003ed34`;
- SRC page copy `0x400263b0` and paste `0x400280dc`.

Track copy `0x40029848` and track paste `0x4002b778` copy the whole 30-byte block.

**On a NEIGHBOR track** the byte does reach the live and lane `+29` (`0x40001f18` copies the DB machine's p2). The analysis task skips it (`voice+20 = 3`, set by NEIGHBOR's start `0x4000463c`). The NEIGHBOR render `0x4000466c` reads no lane byte (C). So no stock path applies it while the machine is NEIGHBOR. The one transient is in §3.4.

### 3.3 "Saved": save and load paths (C)

- **Save.** The bank writer (the function referencing the `PART` tag `0x400d1692` at `0x4008a18a`) checksums and writes the whole 240-byte page-2 block (`0x4008a3b6`, `pea 0xf0`, `jsr 0x400166b8`), and the page-1 block (`0x4008a33e`).
- **Load.**
  - `0x4008c58a` reads 240 bytes into `Part+0x1da`.
  - `0x4008cea0` then calls the validator `0x40002318`, which is also called from `0x4002579e`.
  - The validator keeps NEIGHBOR p2 slot 5 within 0..127.
- **Part copies.** RELOAD, part copy and undo move whole Parts (`memcpy`), so the byte travels with them.

### 3.4 Liveness note: the machine-switch transient (C mechanism, I audibility)

- Machine select (`0x400796a0` / `0x40079424` → `0x400972fc` → `0x40001f18`) rewrites the live p1/p2 bytes and base words for the **new** machine straight away.
- The render function `0x400d61f0[t]` and the runtime machine `0x80000eb4` change only when a trig is processed (`0x4000bfd0`, `0x4000c004`).
- `0x400972fc` also writes the voice-release ramp bitfield `0x8000184c` (`0x400973b8..c0`, C). I infer that it starts the voice's fade (I; kb/memory-map names `0x8000184c` the ramp trigger).
- So after ST→NEIGHBOR in the middle of a note, the fading ST voice renders until the next trig with NEIGHBOR's bytes in the lane. Stock does the same with its zeros.
- The TSNS position is harmless there: it is a threshold index inside the table. The retained PTCH park is in the PTCH position, which is also harmless (pitch only).
- Parks in the LOOP, SLIC, LEN, RTRG or TSTR positions would be riskier: those are a loop-mode index, slice and length at a retrig, a retrig count, and a stretch mode that dereferences `voice+8`.

### 3.5 Conclusion and fallback

NEIGHBOR p2 slot 5 qualifies (C). If the per-machine fix (§6) is chosen, two more parks are needed for FLEX. Proposed: **FL PTCH → NEIGHBOR p1 slot 5** (RTIM position: harmless while RTRG's position is 0) and **FL TSNS → NEIGHBOR p2 slot 3** (SETUP-RATE position: any non-zero value only selects TSTR-rate). These are CHOSEN by the §3.4 reasoning (I).

The fallback, if NEIGHBOR could not be used, would be THRU's p2 slots 2-5. They are `---` too, but THRU is a playing machine, so a fresh census would be needed.

---

## 4. Question 3: the EMUS UI

### 4.1 How SRC SETUP draws and edits TSNS (C)

**Page object** `0x400bb7d0`:
- open `[+0x1c] = 0x400584d0`, reached from `0x40032228` for page 0 on an audio track;
- draw `[+0x24] = 0x4003c830`;
- seven encoder records `0x400bb6f8..` → `0x4003a474` (P2EDIT).

**Renderer `0x4003c830`**, loop `0x4003cdd4..0x4003ceb8`, slots 0..5 = descriptor slots 6..11. For each slot:
1. value = `mvsb DB[OFF_P2 + 30t + 6m + slot]`, with `m` from `[0x460d5c30]`.
2. Nibble bit 0 → widget = `(P+0xfa+4(6+slot))`, or **KNOB `0x400479b4`** when null (`0x4003ce38..40`). The call `jsr (a0)` at `0x4003ce5c` passes `(x, y, slot, value, flags, P+0xca+4(6+slot), canvas)`; flags = 8 if nibble bit 2.
3. **Then** the caption: the name at `P+0x3a+6·slot` is drawn by `0x40013904` (`0x4003ce7a..a6`).

TSNS (slot 11):

| field | value |
|---|---|
| name | STATIC `0x400d3074`, FLEX `0x400d3206` (`TSNS\0\0`) |
| formatter | 0 |
| widget | 0 (`0x400d3142` / `0x400d32d4`) |
| step | 0 |
| min / count | 0 / 128 |
| nibble | 1 |

Because the widget is called before the caption in the same pass, a caption written by the widget shows on the same repaint. This differs from page 1, where (per the retained comment) the text pass runs first.

**Other renderers.** Every image reference to KNOB was classified. None draws a machine page-2 slot (C for each site; I for exhaustiveness):

| site | what it draws |
|---|---|
| `0x4003ce40` | machine SETUP |
| `0x400366a0`, `0x40036914`, `0x40037872`, `0x40037c0e` | the qdial sites: MIDI NOTE / LFO / FX2 / FX1 SETUP |
| `0x4003f5ee`, `0x4003fb10` | MIDI CTRL setup pages |
| `0x4007a1f4` | ARP setup |
| `0x4004e38e`, `0x4004e784` | page 1 of any page |
| `0x40057560`, `0x4007c66e`, `0x4007cac2`, `0x4007cb86` | hard-coded screens |

**Page 2 therefore has no equivalent of the page-1 qdial issue.**

**Edit: `P2EDIT(slot2, delta)` `0x4003a474`.**
1. If the encoder is held, `delta × 7`.
2. `m = [0x460d5c30]`; old = the DB byte.
3. `steps = 0x4003249c(slot2, delta)`: a per-encoder fractional accumulator (`0x46c7d244 + 20·slot`, divisor `[0x46c7dee6 + 20·slot]`; run6: `0x100` for encoder F, so one detent = one unit).
4. new = old + steps, clamped to the descriptor min/count.
5. Store DB, shadow, the dirty flags (DB `+0x95048` byte `|=`, `0x100b145e` byte `|=`, DB `+0x9b332 = 1`, `0x100f8598 = 1`, `jsr 0x40027e00`), the live byte, and the redraw mark `0x46c7d244 + 20·slot + 4 = 0x14`.
6. `jmp [0x400bb7f4]` (the draw).

**P2EDIT never reads `P+0x12a`.** The only callers are the seven records; `0x4003a566` is its own call site (C, call list).

**Emulator limit.** In this emulator the SETUP window opens (`0x400584d0` is entered) but is never drawn: run4a/b/c and run5 tried key sequences, which reached `0x40032228` but never `0x4003c830`. This is the "no UI tick" blind spot. UI tests must call P2EDIT and the widget directly, or run on hardware (§8).

### 4.2 What EMUS needs

**Value encoding** (CHOSEN, open question O4):
- the stored byte stays in TSNS's 0..127;
- `emus_idx(v)`: `v ≤ 42` → S950, `v ≤ 85` → OT, else SP12. A negative (lock) value is treated as S950;
- canonical stops **1 / 64 / 127**. Not 0 for S950, because 0 must mean "fresh";
- DSP mode table `{1, 0, 2}` (spec item 6: 0 = OT, 1 = S950, 2 = SP12);
- stock's own default (64) reads as OT.

**`emus_widget`** (P5, the descriptor widget of slot 11, STATIC and FLEX only):
1. If the UI track's DB machine is not 0/1 → `jmp KNOB` (guard: no poll off ST/FL).
2. `rp_swap(UI_TRACK)`; `g = rp_ui_gate(UI_TRACK, m)`.
3. Write the caption `'EMUS'` or `'TSNS'` to `0x400d3074` and `0x400d3206` (`rp_caption2`).
4. If not `g` → `jmp KNOB` with the caller's arguments (formatter null → `%d`). If this draw swapped, redraw with the fresh live byte, as `quant_widget` does.
5. Else KNOB(x, y, idx, **stop(emus_idx(v))**, flags, **`emus_fmt`**, canvas). The dial snaps hard left, centre or hard right.

**`emus_fmt(buf, v)`:** `v < 0` → `???` (`0x400b442a`), else `S950` / `OT` / `SP12`, then `jmp 0x40013a08`. Measured width with font `0x400ba876` (run8): 15, 7 and 15 px. `TSNS` and `EMUS` are 15 px each.

**`emus_p2step(slot2, delta)`** (R1):
1. If `slot2 ≠ 5`, or `[0x460d5c30] ∉ {0,1}`, or the gate is off → `jmp 0x4003249c`.
2. Else take old = the caller's `%d2` (the signed DB byte loaded at `0x4003a560` and live at the call), `i = emus_idx(old)`, `i' = clamp(i + sign(delta), 0, 2)`, and return `stop(i') − old`.
3. Stock then adds, clamps (0..127), stores, marks and draws.

One detent is one value; a held encoder (`×7`) still moves one value. Relying on `%d2` ties this to P2EDIT's register allocation (C at `0x4003a560..74`). The alternative is to re-read the DB byte with P2EDIT's own index (`a4`), which is equally live.

**Formatter column:** left at 0. Only this renderer reads slot 11's formatter, and it passes it to the widget (I). That makes a P5-style formatter poke unnecessary.

**Caption:** written at swap time (`sw_seen`, beside PTCH/QUAN) and by `emus_widget`. The name fields are global per descriptor, as with QUAN.

---

## 5. Question 4: the trig latch

### 5.1 Where the ColdFire knows a new sound starts (C)

- **The trig byte.** In the voice loop `0x4000d3fc..0x4000d55e`, for track `t`, `a2 = 0x46104d0c + t`. It is copied each frame from `0x46104d15 + t` (`0x4000c642`) by the frame ISR's event decode.
  - Bits 0-3 are the sample offset (`split`).
  - **Bit 4 is a new sound.**
  - Bit 5 is set by the event path `0x4000b5b8` (value `0x30`).
- **Where bit 4 is set.** The event paths `0x4000b5b8` (event word `0x46c80354[t]` bit 2), `0x4000b9b8` (`0x46c7e998`), `0x4000bd70`, `0x4000bdca` and `0x4000be6c` all set it.
  - run7, a stock `--sequencer` run of 300 frames: five new sounds (T1, T3, T4, T7 FLEX, T8 MASTER), all via `0x4000b9b8`, trig byte `0x10`, all reaching `0x4000d47a` (C).
  - Live trig keys and MIDI notes post into the same event words (I: the decode is source-agnostic; not run).
- **Order within a frame.**
  1. First pass: the **old** render function `0x400d61d0[t]` renders `(0, split)`.
  2. If bit 4 is set (`0x4000d472`): `start = 0x400d6454[machine]`, then `start(t, …)` returns bits that are **ORed into the DSP voice record word `0x8000014c + (frame·8+t)·64`** (halfword `$1E`, `0x4000d4b0`). This is the DSP's "trig starts" bit. Render state `+0/+8/+12/+32` is cleared and `+4` is set.
  3. Second pass: the new render runs `(split, 16)`. **H1 runs here.**
  4. `0x4000d534` clears bits 4-7 of the trig byte.
- **So inside H1, `btst #4, 0x46104d0c(t)` is exactly "this frame starts a new sound on t"**, the same condition and frame as the DSP's trig-start bit. `t` is at `52(sp)` in the render frame.
- **RTRG.** Retrigs are counted inside the render: render state `+4/+8/+12/+24/+28`, lane `+8` RTRG at `0x4000414a`. At a retrig point the render calls the voice start `0x4000f450` itself (`0x4000421c`) and discards its return value. **Neither the trig byte nor the DSP trig bit fires** (C). The increment for the whole pass is computed once, before the retrig loop (H1 at `0x40004100`), so it could not change mid-pass anyway.

### 5.2 Latch design (CHOSEN)

- **Trig frame, VARI track:** `e = emus_idx(lane+29)`, or the live byte `0x80000835+72t` if `rp_swap` swapped this call (§5.3). Then tag `= modetab[e] << 2`.
- **Any other frame:** `e_tag = (36(a3) >> 2) & 3`, the previous frame's stored increment. H1 reads it before it overwrites `36(a3)`.
- Non-VARI increments are masked, so their tag is 0:
  - VARI turned on in the middle of a note → OT until the next trig;
  - VARI turned off → stock (masked);
  - an EMUS turn, lock or scene in the middle of a note → no change until the next trig;
  - retrigs → the trig's engine.
- **State.**
  - Render state `+36` (`0x80004898 + 40t`) has a single writer, `0x40004104`, which H1 replaces, and is reused by stock on the next first pass (`0x40004072`).
  - It is outside `0x80006a40..0x80006abf`, and stock depends on it every frame, so it is reliable (C for the readers and writer). No byte is added.
  - The first pass of a trig frame (the old sound's tail) still reuses the old `+36`, so the old tail keeps the old engine. That is what the DSP's trig guard expects: it acts only on the second pass, `LC = 1` (`rpk_dsp.asm` header).
- **Alternative:** an 8-byte latch array in our unit's data, next to `rp_prev`. Equivalent, plus 8 B and one store. Use it only if the `+36` round trip turns out not to be exact; a C check of `0x40004072` shows it is.

### 5.3 Transition frame

The swap runs after this frame's copier, so lane `+29` (and lane `+0` for QUAN) still holds the old domain on the frame `rp_swap` changes it. A trig on that frame would latch TSNS as EMUS for the whole note.

**Rule:** when `rp_swap` reports a swap this call, H1 reads EMUS from the live byte `0x80000835+72t`, and QUAN from the live byte `0x80000810+72t` `<<8`, for that frame. This also closes the first scope's R2 for QUAN.

### 5.4 DSP interaction

- The DSP gets the mode with every pass (`y:$40` bits 0-1) and keeps no engine state of its own.
- On a trig frame:
  - pass 1 carries the old tag and the trig bit with `LC = 2`, so there is no ring clear;
  - pass 2 carries the new tag and `LC = 1`, so the ring behind the new sound is cleared and RPSP's slot is reset.
- That is consistent.
- **Retrigs** fire neither the latch nor the DSP guard. That is a pre-existing kernel gap (START_HERE: "Not specifically tested: RTRG retrigs"). An S950/SP12 retrig may replay a few stale frames. It is unchanged by this design and listed as a risk.

---

## 6. Question 5: `rp_swap` with two pairs, and item 11

### 6.1 The bug, exactly (from the retained code, C by reading it)

- `rp_ui_gate(t)` evaluates the **current DB machine** only: machine ∉ {0,1} → 0.
- `rp_swap`:
  1. `d0 = gate`; if `d0 ≠ rp_prev[t]`, it stores `rp_prev[t] = d0`;
  2. **then** `machine > 1` → `.sw_none`;
  3. otherwise it swaps the current machine's slot with **one park shared by ST and FL**.
- **ST(VARI) → PU → ST.** On PU: gate 0, `rp_prev` 1→0, no swap, so ST's slot still holds QUAN. Back on ST: gate 1, `rp_prev` 0→1 → swap. QUAN goes to the park, and the parked PTCH comes back as "QUAN": **inverted**. THRU and NEIGHBOR do the same.
- **ST(VARI) → FL(not VARI).** FL: gate 0 ≠ 1 → swap **FL's** PTCH with the park, which holds ST's PTCH. FL's PTCH is lost into the park, and ST's slot still holds QUAN: **cross-machine corruption**.
- **Dial poll.** `quant_widget` → `rp_swap(UI_TRACK)` on any page that reaches it. On a PU track it can run the PU branch above.

### 6.2 Fix (CHOSEN; option A of open question O1)

- **Per-machine gate.** `rp_ui_gate_m(t, m)` uses only machine `m`'s own Part bytes:
  - TSTR `OFF_P2 + 30t + 6m + 4` (VARI = **4 only**; AUTO (1) → sample TSMODE `+0x110` == 4);
  - the sample slot `OFF_SLOT5 + 5t + m` (array by `m`);
  - BPM ×24 `+0x114` in 720..7200.

  This is the retained body with `d3` = `m` passed in. The project tempo is always in range: `set_tempo` clamps it (first scope, C).
- **Per-machine state.** `rp_prev[t][m]`, 16 bytes, `m ∈ {ST, FL}`, same codes (0/1, `0xff` forgotten, `0xfe` HOLD). `rp_forget` and `rp_reload` write all 16 (four longs; `patch_repitch_reload.s` changes from two longs).
- **Per-machine parks:**

  | pair | ST park | FL park |
  |---|---|---|
  | PTCH↔QUAN | NEIGHBOR p1 s0 (retained `PARKED = 18`) | NEIGHBOR p1 s5 (`OFF_P1 + 30t + 23`) |
  | TSNS↔EMUS | NEIGHBOR p2 s5 (`OFF_P2 + 30t + 23`) | NEIGHBOR p2 s3 (`OFF_P2 + 30t + 21`) |

- **Invariant:** slot `(t, m)` holds the VARI domain ⇔ `rp_prev[t][m] = 1` ⇔ `g_m(t)`, outside of a pending transition. It can be recovered from the saved Part, so adoption after any load, apply or reload is always right.
- **`rp_swap(t)`.** Takes `m` = the DB machine.
  - `m ∉ {0,1}` → **return without touching anything**. This makes the PICKUP/THRU/NEIGHBOR path inert, and the dial poll on PICKUP becomes a no-op.
  - Else compare `g_m(t)` with `rp_prev[t][m]`:
    - HOLD → none;
    - forgotten → adopt;
    - differs → **swap both pairs of machine `m` together**, in DB and shadow;
    - live bytes: PTCH live `0x80000810+72t` plus base word `0x80000a50+64t` = `v<<8`, and TSNS live `0x80000835+72t` (no base word);
    - the four dirty flags, written once.
  - Return: `d0` bit 0 = swapped, bit 1 = `rp_prev[t][m]` after the call. H1 uses both.
  - A machine change itself never swaps: neither machine's gate depends on which machine is current.
- **Fresh rules.**
  - PTCH/QUAN: as retained (entering value < 4 → 64, both directions).
  - TSNS/EMUS: **entering EMUS** with park == 0 → 64 (OT). **Leaving:** the TSNS comes back verbatim, so TSNS 0 survives a round trip. The cost: a slot adopted in VARI and never live-swapped (an old RPCH project) leaves VARI with TSNS 0.
- **Non-current machine.** A gate change can happen while the machine is not current: an ATTR edit of a sample the other machine uses, or a sample replaced in its slot. Then the swap is deferred until that machine is current. A save and load in between would adopt the new gate over the old domain.
  - Mitigations: `rp_refresh` (the ATTR path) polls all 8 tracks × both machines;
  - and, optionally, H1 polls one `(track, non-current machine)` pair per frame, round robin over 8 frames (about 70 instructions per frame). Open question O6.
- **Guards.** `quant_widget` and `emus_widget` return stock KNOB without polling when the UI track's DB machine ∉ {0,1}. Install them only in the ST/FL descriptor columns.

### 6.3 Option B (not chosen)

- **Design:** one park per pair, with `rp_prev[t]` ∈ {none, ST, FL} recording which machine's slot holds the VARI domain.
- **Cheaper:** 2 parks, 8 bytes.
- **Weaker:**
  - When ST and FL are both set to VARI, QUAN/EMUS values migrate between them.
  - After save and load it is **ambiguous** which machine's slot holds VARI, because the Part does not record it. An adopt can therefore invert again.

### 6.4 Test design for both pairs (emulator, our build; fixtures by runtime poke only)

Setup:
- T1 STATIC, a sample with BPM in range, TSTR 4;
- PTCH 70 and TSNS 30 entered before VARI, so they are parked;
- QUAN set to the 3/2 stop (109) and EMUS to SP12 (127) while in VARI.

| # | sequence | assert |
|---|---|---|
| S1 | ST → PU → ST; machine changed as stock does (DB `+0x8eda2+t` and shadow, then `--step call 0x400972fc,part,t,old`); 50 frames between steps; call the widgets on the PU track | ST p1 s0 = 109, ST p2 s5 = 127, parks 70/30, `rp_prev[1][ST]` = 1; **PU's own p1/p2 bytes and every park unchanged on PU**; no DB write while on PU |
| S2 | as S1 via THRU and via NEIGHBOR | same |
| S3 | ST(VARI) → FL with FL TSTR AUTO (not VARI) → ST | FL's PTCH/TSNS unchanged; ST as S1 |
| S4 | ST(VARI) → FL, set FL to VARI (FL parks receive FL's values) → ST → FL | both machines' natives and VARI values exact |
| S5 | TSTR 4→3→4 live (P2EDIT `call 0x4003a474,4,±1`) | the two pairs swap together, exactly once each way; captions at `0x400d3032`/`0x400d3074` follow |
| S6 | fresh park (NEIGHBOR p2 s5 = 0) → VARI | EMUS = 64 (OT); leaving gives TSNS verbatim |
| S7 | Part apply, RELOAD PART, bank reload | `rp_prev` forgotten or held; values adopted, no swap |
| S8 | save the bank with T1 in VARI (or poke the Part, then run the writer and parser), reload | bytes identical through the validator; adopt, no swap |

Run each sequence once with the shipped FINAL image as a **black-box differential**: outputs only (DB bytes after each step). That documents the old behaviour. Where the shipped image inverts, that is the expected difference (spec item 11).

### 6.5 Bulk writers (an open question, O2)

These rewrite one machine's or a whole track's or Part's SRC bytes, TSTR included. They refresh live via `0x400972fc` and never pass through `rp_forget`.

| writer | site | callers |
|---|---|---|
| SRC page paste | `0x40027e4c`, case 0 writes machine, slot and 6+6 bytes | `0x40028f9a` / `0x40028fda` |
| track paste | `0x4002b654` (30-byte block copy at `0x4002b778`) | `0x4002b968` / `0x4002b9a4` |
| PART menu COPY / PASTE ON PART / CLEAR / UNDO | `0x4005a5a8` (from `0x400bb684`; `0x400972fc` at `0x4005a676` / `0x4005a8b0`) | — |

If the gate of the written machine changes, the next poll swaps data that is already consistent: the RELOAD PART class.

**Fix:** the `rp_reload` pattern. Put every `rp_prev` byte on HOLD for the call, then forget, so the next poll adopts. Adoption is correct in every paste case, because the invariant in §6.2 holds for the pasted data and for the target's own parks. Cost: about 3 × 40 B, 3 detours. The prologues are `lea -N(sp),sp; movem.l` (C, function heads in §9.2).

---

## 7. Question 6: the first scope, revised for five positions

| first scope | revision |
|---|---|
| gate raw 4..6, AUTO TSMODE 4..6 | **raw 4 only; AUTO TSMODE 4 only**; per-machine (§6.2) |
| H1 mode from TSTR (4/5/6 → 0/1/2) | **mode from the latched EMUS** (§5.2); the tag on every frame comes from `36(a3)` or the trig-frame read |
| H1 dry for gated tracks | dry (`clr.b 28(fp)`) for **every VARI candidate, in range or not**. Spec: out of range = OFF; stock would treat raw 4 as NORM (first scope §2.1, C), so this settles R10 without a resolve detour |
| R2 transition frame | live-byte reads on a swap frame (§5.3) |
| P1 count 4→7 | 4→**5** |
| P2 widget → `0x40046ab4` | kept, **unmodified** (5 stock icons, bound `moveq #4`) |
| P3 glyph pokes, `rpk_glyphs.s` | **dropped** |
| P4 `tstr_fmt` 7 entries | **5 entries** (OFF AUTO NORM BEAT VARI), else `???` |
| H2 REPITCH/RPS9/RPSP | **4 only** → `VARISPEED` or `VARI` (§7.1); 5/6 keep stock `ERROR` |
| H3 up …→4→5→6 | **…→3→4**, stops at 4 |
| H4 down 6→5→4→… | **4→3→2→0**; 5/6 stay stuck, as in stock (O5) |
| §2.7 RPCH-only variant | it is the main design, with the full DSP kernel, its two hooks and the Y claim; **no separate build** |
| new | P5, R1, `emus_*`, the second pair, per-machine parks and prev, guards |
| "no loader clamp of page-2 bytes was found" (§2.3, I) | **wrong: validator `0x40002318`** clamps p1/p2 to the descriptor at bank load (C). It reads the count at runtime, so with P1 a stored TSTR 5/6 (an old RPS9/RPSP project) **loads as 4 (VARI)**, and EMUS is adopted from that track's TSNS (usually 64 → OT). On stock, 5/6 would clamp to 3 (BEAT). Item 10: acceptable, no special handling. TSMODE is not validated (first scope, C); 5/6 there behave as NORM-like raw, which is stock's handling |

### 7.1 ATTR label width (C)

- Measured with stock's own `0x40012f30` on font `0x400ba876` (run8): `VARISPEED` 35 px, `VARI` 15, `NORMAL` 23, `ERROR` 19, `TIMESTRETCH` 43.
- The ATTR value is drawn at x = 69 (`pea 0x45`, `0x4006e8a0`). The selection box spans x = 68..101 (`0x4006e8ba..ca`).
- `VARISPEED` ends at about x = 104: **2-3 px past the box**, though still on screen.
- By the spec's own rule, the field cannot hold nine characters → **`VARI`**, unless the user accepts the overflow (O3).

### 7.2 Effort, phased

1. **Harness:** the first scope's §5.1, plus direct calls to P2EDIT and the widgets (the SETUP window cannot be opened in the emulator). 1–2 sessions.
2. **H1 with the latch and per-machine domain checks.** 1 session.
3. **Retained refactor:** per-machine gate, prev and parks, the second pair, guards, 16-byte reload. 1 session.
4. **UI:** P1, P2, P4, P5, R1, `tstr_fmt`, `emus_*`, H2–H4. 1–1.5 sessions.
5. **(Optional) bulk-writer wrappers.** 0.5 session.
6. **Equivalence passes and load.** 1–2 sessions.
7. **Packaging:** DRAM units, conflicts, standalone, KYOTI re-pin, Bugbuild. 1 session.
8. **Hardware:** the FLASHING §4 checklist, with a diagnostic build that toasts gate, machine, `rp_prev` and tag first.

---

## 8. Risks, open questions, test-plan delta

### 8.1 Risks

| # | risk | handling |
|---|---|---|
| E1 | `emus_p2step` reads P2EDIT's `%d2` (register coupling) | assert the stock bytes `0x4003a55a..0x4003a576` at build; or re-read the DB byte |
| E2 | Machine-switch transient feeds park bytes to a fading old voice (§3.4) | parks only in harmless positions; stock does the same with zeros |
| E3 | A non-current machine's gate changes, then save/load before it becomes current (§6.2) | `rp_refresh` polls all × both; optional round-robin poll |
| E4 | Bulk writers invert domains (§6.5) | wrappers (O2); pre-existing in the shipped design |
| E5 | RTRG retrigs: no DSP ring guard (§5.4) | unchanged kernel; hardware test of S950/SP12 with RTRG |
| E6 | EMUS seen by the analysis task as TSNS | values 0..127 → in-table; dry track → inaudible (I) |
| E7 | Emulator cannot draw SETUP (UI tick) | direct calls; LCD checks on hardware |
| E8 | Old FL tracks in RPCH projects: the PTCH park moves (s0 → p1 s5), so leaving VARI gives PTCH 64 | O1; one-time, no crash |
| E9 | Old RPS9/RPSP projects load as VARI + OT-by-default (validator) | item 10 accepted |
| E10 | QUAN's page-1 dial needs `quant_widget` in `P+0xfa` slot 0 (§1.2) | verify the wiring in implementation |

### 8.2 Open questions for the user

- **O1.** Per-machine parks and prev (exact; FLEX's PTCH park moves; 4 park bytes per track), or a single shared park with documented ST/FL caveats?
- **O2.** Fix the bulk-writer class (SRC page paste, track paste, PART menu) now, with three hold/forget wrappers?
- **O3.** ATTR label `VARI` (fits) or `VARISPEED` (2-3 px past the selection box)?
- **O4.** EMUS stops 1/64/127, zones by thirds, fresh park 0 → OT, TSNS restored verbatim on leaving: confirm.
- **O5.** ATTR down from a stock-unknown TSMODE 5/6: leave it stuck at `ERROR` (stock), or step to 4?
- **O6.** The round-robin background poll of the non-current machine (about 70 instructions per frame)?

### 8.3 Test-plan delta against the first scope's §5

- **Matrix.** TSTR 0..4 (not 0..6) × TSMODE 0/2/3/4 × **EMUS S950/OT/SP12** × the rest as before.
  - Equivalence: VARI+OT ≡ TSTR 4, VARI+S950 ≡ 5, VARI+SP12 ≡ 6 (spec §5).
  - Out of range against **stock OFF**.
- **Tag and latch.** On the CF→DSP host-port stream (header `+8` per pass):
  - (a) tag bits 2-3 = `modetab[EMUS]` on VARI tracks, 0 everywhere else;
  - (b) poke the live byte `0x80000835+72t` mid-note → the tag is unchanged until the next trig, then changes on **pass 2** of the trig frame, with pass 1 still old;
  - (c) RTRG > 0 → the tag stays constant through retrigs;
  - (d) a trig on the swap frame (§5.3) latches the new EMUS.
- **EMUS UI** (direct calls):
  - `P2EDIT(5, ±1)` with `[0x460d5c30]` = 0/1 → stops 1→64→127, clamped at both ends;
  - held (`×7`) → one stop;
  - gate off → stock steps;
  - `emus_widget` called with a canvas → the value argument snaps to the stop, the formatter is `emus_fmt`, and the caption bytes are set;
  - on hardware: an LCD photo of SRC SETUP on a VARI track.
- **Swap.** §6.4 S1–S8.
- **Validator and persistence.** S8, plus a bank holding TSTR 5/6 (from a real project saved with the shipped module, if the user can export one) → loads as 4, no crash.
- **Item 10.** TSMODE 5/6 sample under AUTO → NORM-like stretch, ATTR shows `ERROR`, no crash.
- **Load.** `OT_ISR_OUT` with 0/4/8 VARI tracks × EMUS OT/S950/SP12, and 8 AUTO stock tracks. Compare against stock and the shipped image (outputs only).
- **Oracle first** (unchanged rule). The harness must flag a build whose latch follows EMUS mid-note.

---

## 9. Provenance

### 9.1 Files read

| source | used for |
|---|---|
| `reference/handoffs/REPITCH_REWRITE_SPEC.md` (all) | requirements, protocol |
| `reference/handoffs/REPITCH_REWRITE_SCOPE.md` (all) | base scope |
| `reference/handoffs/REPITCH_REWRITE_RETAINED.s` (all) | `rp_swap`, `rp_ui_gate`, QUAN, `rp_caption`, `rp_forget`, the offset equates |
| `octabam-modules/repitch-repeat98-kyoti/`: `patch_repitch_reload.s`, `README.md` (all); `rpk_dsp.asm` L1–160 and the `x:$419` lines | the reload wrapper, DSP entry state, the trig bit, `y:$40` |
| `CLAUDE.md`, `START_HERE.md` (filtered with `grep -v` on the keyword set) | rules |
| `reference/kb/caves.md` (all) | §0 descriptor table, §5 DRAM |
| `reference/kb/memory-map.md` L555–600, L800–850, L1100–1240 (see §9.4) | lock indices, keycodes, publish path, page-2 lane |
| `reference/kb/file-format.md` (grep only) | Part block |
| `tools/load_audit/la_run.py` (filtered), `ot_emu_load_audit.patch` (header) | run method, `OT_RW` |
| `~/Documents/octabam/tools/emu/ot_emu/main.cpp` (option and step parsing only) | `--step`, `--live-script`, `--watch-mem` semantics |

### 9.2 Image facts (objdump of `out/raw/section_3_MAIN_OS.bin`; listing `out/clean-room/stock.dis`)

Disassembled ranges:
- copier `0x4000ca80..0x4000cc60`;
- voice loop `0x4000d2c0..0x4000d580`;
- render `0x40004008..0x40004268`;
- NEIGHBOR start/render `0x4000463c..0x400046f0`;
- trig events `0x4000b480..0x4000b780`, `0x4000b8d6..0x4000be78`, `0x4000bed0..0x4000c010`, `0x4000c560..0x4000c6c0`;
- analysis task `0x400989d0..0x40098d20`, `0x400985ac..0x40098720`, `0x40098388..0x40098480`;
- P2EDIT `0x4003a474..0x4003a6c0`;
- accumulators `0x4003240c..0x40032520`;
- setup opener `0x40032228..0x400323a0`;
- page keys `0x40055720..0x40055910`;
- page-2 renderer `0x4003cc80..0x4003cf40` (head `0x4003c830`);
- page-1 renderer `0x4004e4c0..0x4004e830`;
- qdial regions `0x40036600..0x400366c0`, `0x400368a0..0x40036930`, `0x40037760..0x400378b0`, `0x40037b40..0x40037c30`;
- other KNOB sites `0x4003f4f0..0x4003f600`, `0x4007a1d4..0x4007a1f4`;
- KNOB `0x400479b4..0x40047b40`;
- validator `0x40002500..0x40002740`;
- bank parser `0x4008c560..0x4008c5d0`; writer `0x4008a33a..0x4008a446`;
- refresher `0x40001f18..0x40002000`;
- machine select `0x40079424..0x40079600`; `0x400972fc` calls;
- paste `0x40027d80..0x40028150`, `0x40029754` / `0x4002b654` heads;
- ATTR `0x4006e600..0x4006e8d0`;
- memcpy `0x40020898..0x40020930`.

Data scripts:
- `out/clean-room/desc.py`: the descriptor records of STATIC, FLEX, PICKUP, NEIGHBOR, THRU and the MIDI pages;
- `findlong.py`: pointer scans for `0x4003c830`, `0x4003b4b0`, `0x4003b6a4`, `0x40046ab4`, `0x40046c28`, `0x400479b4`, `0x4003249c`, `0x4003a474`, `0x400bb7d0..f4`;
- `encl.py`: enclosing functions and callers;
- inline dumps: `0x400bb6d0..0x400bb830`, the keymap `0x400bfc10`, `0x400d6454` / `0x400d6434` / `0x400d61d0` / `0x400d61f0`, `0x400d7c7c`, `PART` tags `0x400d1690`, strings.

### 9.3 Emulator runs (stock only)

Binary: `../octatrack-kyoti-fw-octabam-port/out/la/octabam/out/emu/ot_emu` (load-audit patch, not rebuilt). Image `…/out/la/img/stock.bin` = `out/raw/section_3_MAIN_OS.bin` (`cmp`). Card `otdemo.img`, project KYOTI/OTDEMO. Outputs in `out/clean-room/`:

| run | what | source of |
|---|---|---|
| run3 | `--live-script` (SRC presses, encoders), `OT_RW` over bank-0 Parts, SRAM shadow, live, lanes; `--mem-dump` of the Parts | the §3.2 census (`p2census.py`), page-1 draws at `0x4004e7a0` reading the descriptor widget, the Part contents and defaults |
| run4a/b/c, run5 | key sequences for SRC SETUP | the window open is entered, the draw is never reached (§4.1) |
| run6 | `--step call 0x4003a474,5,n` with dumps | the TSNS store, the live byte, the clamp, the encoder divisor table |
| run7 | `--sequencer` 300 frames, `--watch-pc` on the trig paths | the five trig starts through `0x4000b9b8` → `0x4000d47a`, trig byte `0x10`, no retrig |
| run8 | `--step call 0x40012f30` on poked strings | label widths |
| run9 | `--watch-mem` on lane `+24..+31` and the live p2 bytes, 120 frames | the writers: copier, apply, transport start, boot |

### 9.4 Blacklist statement

**I did not open any blacklisted file.** Disclosures:

1. **The memory index.** The auto-memory index `MEMORY.md` was injected into my context by the system at start; I did not open any memory file. It contains one-line summaries of the old implementation, for example:
   - base words `0x80000a50+64t`;
   - `rp_swap` dirty flags written with `or.l`;
   - RELOAD PART bypassing `rp_forget`;
   - DSP revisions.

   I used none of these. Each related fact here comes from the image or the allowed retained code.
2. **A kb paragraph I should have skipped.** I read `reference/kb/memory-map.md` L1100–1240, the publish-path section, which contains one sentence matching the keyword set (L1179). It says a page-1 write behind the editor must go to the base word, and that "repitch-kyoti's PTCH/QUAN swap did exactly that from rev 5 to rev 15 (fixed rev 16)". The task told me to skip such sections. The same fact is in the retained code's comment; nothing else from that sentence was used.
3. **Names only.**
   - `ls octabam-modules/repitch-repeat98-kyoti/` printed the names `manifest.py` and `patch_repitch_kyoti.s`; neither was opened.
   - `rpk_dsp.asm`'s header names `tools/patch_repitch_kyoti.s` and `rate_hook` (the spec allows names).
   - `la_run.py` L18 names the old TSTR values.
4. **Other material listed but not used.**
   - `ls …/out/la/img` showed `obkyoti11.bin`, an octabam KYOTI image that contains the shipped module. I did not run, disassemble, diff or read it.
   - `pgrep` printed another session's `ot_emu` command lines (BlackPyramids_303 work, not REPITCH).
   - caves.md L206/L285 mention REPITCH in passing (the SPRING reclaim, DRAM); that file was required reading.
