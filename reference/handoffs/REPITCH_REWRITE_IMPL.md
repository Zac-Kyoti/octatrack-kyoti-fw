# VARISPEED_EMUS: implementation report (clean side)

Written 2026-10-14 by the **clean** implementation agent, in the worktree
`octatrack-kyoti-fw-repitch-rewrite` (branch `repitch-rewrite`). It follows
`REPITCH_REWRITE_SPEC.md`, `REPITCH_REWRITE_SCOPE.md` and `REPITCH_REWRITE_SCOPE_EMUS.md`.
Nothing was flashed, promoted or pushed. KYOTI's combined image was not touched.

Marks: **C** = confirmed on our image (objdump, or an emulator run); **I** = inferred.

**Current build: `140C_VEM2` (§8, 2026-10-14), the two fixes from the first hardware test.**
§1-§5 describe `140C_VEM1`, the image flashed on 2026-10-14; where VEM2 changed something,
§8 says so.

---

## 1. What was built

**A new build exists: VARISPEED_EMUS, WIP, not flashed.**

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `ca04cc16526985b8dc6cc0f6fe07e1621536c01a3410166813a875900175a550` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `2e9ca4c23f92814aa4be43ab0404c0149c0dbdc8d5423af8d5793daf65e859e0` |
| `out/mainos_varispeed_emus.bin` (patched MAIN OS) | `610846a99adeaa184c08a190c1f242ea273110da16f222bbf236d555b600f7f0` |
| `out/elek_varispeed_emus.bin` (EFT container) | `322b5f4f7305696a1616a7f9d29af0db62c27625bd15c284a2b230ed274dc016` |

OS VERSION reads `140C_VEM1`. The builder is deterministic (rebuilt three times, same hashes).

**Sources** (all with `SPDX-License-Identifier: MIT` / `SPDX-FileCopyrightText: 2026 Zac-Kyoti`):

| file | what |
|---|---|
| `tools/build_varispeed_emus.py` | the standalone builder (WIP, `KYOTI_ALLOW_WIP=1`) |
| `octabam-modules/varispeed-emus/varispeed_emus.s` | the ColdFire half, one link unit: PART 1 new core, PART 2 the retained code extended |
| `octabam-modules/varispeed-emus/manifest.py` | the octabam module |
| `octabam-modules/varispeed-emus/rpk_dsp.asm`, `rpk_dsp_ptable.py` | verbatim copies of the kernel files (header added) |
| `tools/varispeed_emus_harness.py` | the black-box equivalence harness (spec §5) |
| `tools/varispeed_emus_test.py` | the new-behaviour tests |
| `tools/varispeed_emus_ot_emu.patch` | the scratch ot_emu patch both use (DSP voice-entry log) |

**Sizes.** ColdFire unit 2,952 B at `0x400d6500..0x400d7088` (classic cave; 2,996 B of it
left), identical bytes for `-mcpu=5407` and `54455`. DSP: 412 words per payload in SPRING
REVERB's P module (A `P:0x13ea`, B `P:0x11aa`, ending below DARK REV's routine), 465 table
words in SPRING's X data, as the DSP install always placed them. 7,838 bytes differ from stock.

**Builder discipline.** Every detour, poke and context span is asserted against stock first;
nothing may branch into a displaced span (one false positive allow-listed with the
instruction it sits in: `0x4003670e` is the address word of `jsr 0x400a6994`); the cave must
be zero and inside `0x400d6500..0x400d7c3c`; the unit may not reference
`0x80006a40..0x80006abf`; the 5-position select `0x40046ab4` must still be unreferenced in
stock; each body must jump back to its site + the displaced length; the module manifest's
`reference` must equal the unit (refused otherwise); EFT wrap + re-parse. The DSP half is
`REPITCH_REWRITE_DSP_INSTALL.py`, copied in verbatim between markers.

## 2. Hooks as implemented

All in the standalone image; the octabam module declares the same.

| # | site | displaced | kind | target | purpose |
|---|---|---|---|---|---|
| H1 | `0x40004100` | 8 B | jmp | `vem_frame` | the frame core: candidate test, per-machine poll, dry, exact QUAN x tempo x RATE, clamp, engine latch, mask bits 2-3 elsewhere |
| R1 | `0x4003a566` | 6 B | jsr | `emus_p2step` | P2EDIT's delta conversion: one EMUS stop per detent (VEM2: per six detents, §8) |
| R2 | `0x400585f4` | 6 B | jsr | `emus_open` | VEM2 only: SRC SETUP's open, the EMUS detent count restarts (§8) |
| H2 | `0x4006e71c` | 10 B | jmp | `attr_label` | ATTR TIMESTRETCH 4 -> `VARI`; else `ERROR` as stock |
| H3 | `0x4006ee48` | 6 B | jmp | `attr_up` | OFF -> NORMAL -> BEAT -> VARI, `rp_refresh` |
| H4 | `0x4006ef7c` | 6 B | jmp | `attr_down` | VARI -> BEAT -> NORMAL -> OFF, `rp_refresh`; 5/6 stay |
| T1/T2 | `0x4006eef0`, `0x4006f026` | 8 B each | jmp | `attr_tail` | every ATTR edit polls the gates (`rp_poll_all`) |
| Q1-4 | `0x40036698`, `0x4003690c`, `0x4003786a`, `0x40037c06` | 14 B each | jmp | `qdial1..4` | retained, unchanged |
| A1/A2 | `0x40009094`, `0x40009e00` | 8 B each | jmp | `rp_apply1/2` | retained: forget at the Part applies |
| RL | `0x4004aab4` | 8 B | jmp | `rp_reload` | RELOAD PART: hold, forget (16 bytes now) |
| O2a | `0x40027e4c` | 8 B | jmp | `vh_srcpaste` | SRC page paste and its undo |
| O2b | `0x4002b654` | 8 B | jmp | `vh_trkpaste` | track paste and its undo |
| O2c | `0x40029a4c` | 8 B | jmp | `vh_partpaste` | the PART menu's paste core (PASTE and UNDO) |
| O2d | `0x4004a9d0` | 8 B | jmp | `vh_partclear` | the PART menu's CLEAR |

Descriptor pokes (u32): TSTR count 4 -> 5 (`0x400d30de`, `0x400d3270`); TSTR widget
`0x40046c28` -> `0x40046ab4` (`0x400d313e`, `0x400d32d0`); TSTR formatter -> `tstr_fmt`
(`0x400d310e`, `0x400d32a0`); TSNS widget 0 -> `emus_widget` (`0x400d3142`, `0x400d32d4`);
PTCH widget KNOB -> `quant_widget` (`0x400d3116`, `0x400d32a8`); PTCH step -> `quant_step`
(`0x400d3146`, `0x400d32d8`). PICKUP's entries untouched.

DSP: `zqrp` at A `P:0x40b` / B `P:0x20e`, `zqboot` at A `P:0x46` / B `P:0x47`; SPRING's
dispatch entry -> the empty-FX stub; SPRING removed from FX2's chooser, `id2e` -> NONE on
both buses.

**State.** `rp_prev[2t+m]` (16 B: 0/1, `0xff` forgotten, `0xfe` HOLD), `vem_depth` (nested
holds), `rk_acc`, all in the unit. The engine latch lives in render state `+36` bits 2-3, as
the EMUS scope designed (no new state). Parks: NEIGHBOR p1 s0 / p1 s5 (ST / FL PTCH), p2 s5 /
p2 s3 (ST / FL TSNS).

**Cost (C, whole-run ColdFire instructions per frame, OTDEMO, 3,000 frames).** Stock TSTR on
all tracks: new 32,153 vs shipped 32,538. Seven VARI tracks: new 33,334 vs shipped 33,626;
pre-set SP12: 34,265 vs 34,545. Stock image with TSTR OFF: 32,145. Seven *out-of-range* VARI
candidates: 33,037 (+892/frame over stock: each candidate polls its gate every frame, as the
spec's §3 rule requires). Not the load-audit ISR measurement (§5).

## 3. Tests and results

Emulator: a scratch octabam `git worktree` at `a67a1112` under `out/vem/octabam` (vendor and
`out/raw` symlinked read-only to `~/Documents/octabam`), `ot_emu` target only, with
`tools/varispeed_emus_ot_emu.patch`. Projects: **OTDEMO** (set KYOTI, the user's hardware
backup as staged for the load audit; T1-T7 FLEX, T8 THRU) and **MMTESTDT**
(`refs/octabam/out/mmtestdt_dsp_card.img`, a hardware export; T1-T8 STATIC). All settings by
runtime pokes and calls; no project file edited.

### (a) Black-box equivalence vs the shipped FINAL (spec §5)

Observation point: `x:$40` / `y:$40` at the DSP voice kernel's entry (unchanged kernel, both
images), every pass, both cores. Per track from its first trig after frame 60 (the new image
latches the engine at a trig, the shipped takes it from TSTR at once), or, for scenarios set
before the transport starts (`pre_*`), every pass from frame 10.

- **Oracle check first:** stock vs stock IDENTICAL; a deliberately wrong build (round instead
  of floor in the scale, `out/vem_variants/mainos_varispeed_emus_wrong_round.bin`) DIFFERS
  (T1, 3,239/3,239 passes, all three engines).
- **OTDEMO, 29 + 3 scenarios:** VARI x {OT, S950, SP12} x tempo {project, 87.5, 150 BPM} x
  two QUAN sets (all 9 stops) x RATE {127, 112, 96, 32, 16, 0} (forward, reverse, full
  reverse) on 7 tracks; AUTO with sample TSMODE 4 (shipped 4/5/6); SETUP RATE mode TSTR with
  sample tempos at 720/721/7199/7200; project tempo 720 and 7200; stock TSTR 0..3 x TSMODE
  0/2/3; two PICKUP tracks beside VARI ones: **32/32 identical** (`out/vem/harness_otdemo.txt`).
- **Pre-set, every pass:** `pre_OT`, `pre_S950`, `pre_SP12`: **3/3 identical** from frame 10,
  about 5,980 passes per track on T1-T7, engine bits included.
- **MMTESTDT (STATIC), 32 scenarios, 6,000 frames:** **32/32 identical**; only T1 triggers in
  that pattern, so this covers STATIC on T1 (5,795-9,513 passes per scenario).
- **Out of range vs stock OFF** (sample BPM 0, 719, 7201): identical on both projects with the
  engine bits masked; the new image's engine bits are 0 on every pass (checked).
- **The octabam-built image** (`make bus`, DRAM unit): 3/3 identical (quick set).
- **Audio** (levels and spectra, never samples): `pre_OT` RMS max 0.09 dB, 1/3-octave max
  0.57 dB; `pre_S950` 0.09 / 0.35 dB; `pre_SP12` 0.09 / **1.05 dB** (the harness's 1.0 dB
  limit, so it prints DIFFER; RMS is within 0.09 dB and the DSP inputs are bit-identical; the
  two runs' transport starts are 3 samples apart). Only core 0 puts out TX0 in the emulator.
  **Superseded 2026-10-14 (dirty-side review):** that run compared whole files, which are silent
  until the project loads (~16.5 s of 17.6 s), so it judged ~1 s of sound with onsets 2-5 samples
  apart. The harness now compares from each recording's onset. A long run (`--frames 22000`,
  7.93 s of sound, `out/vem/harness_audio_long.txt`) gives all three engines MATCH: RMS max
  0.1 dB and 1/3-octave max 0.03 dB (OT 0.02, S950 0.03, SP12 0.01).
- **Screens:** not compared. The emulator never draws SRC SETUP; the widgets are tested
  directly in (b).

**Whole-run differences (by design, listed by the harness):** (1) until each track's next
trig after VARI is switched on mid-note, the new image plays OT where the shipped plays
S950/SP12 (the spec's trig latch); (2) at a gate transition the two differ for **one computed
increment** (one or two passes): the new image reads QUAN from the live byte on the swap
frame (EMUS scope §5.3), the shipped from the stale lane; and at a first-sight adoption the new
image engages one frame earlier. Nothing else differs.

### (b) New behaviour (`tools/varispeed_emus_test.py`): **11/11 PASS**

| test | what it shows |
|---|---|
| swap | PTCH 70 / TSNS 30 -> VARI: QUAN 64 / EMUS 64 from fresh parks, 70 / 30 parked; both pairs on the same frame (frames 12-14); live byte, base word `0x4000`, SRAM copy, captions `QUAN`/`EMUS`; back to BEAT: 70 / 30 back, 109 / 127 parked, `PTCH`/`TSNS`; back to VARI: 109 / 127 |
| fresh0 | TSNS 0 enters EMUS as OT (64) and comes back as 0 |
| adopt | a Part already in VARI with `rp_prev` forgotten is adopted, no swap; the other machine adopted to 0 |
| p2edit | EMUS through P2EDIT: 64 +1 -> 127, +1 -> 127, -1 -> 64, -1 -> 1, -1 -> 1, +7 -> 64, 30 +1 -> 64, 50 -1 -> 1, 100 -1 -> 64, 90 +1 -> 127, -7 -> 64; gate off: 64 + 1 = 65 (stock); TSTR BEAT +1 -> VARI, +1 stays; the editor's TSTR change swaps |
| widget | `emus_widget` passes KNOB the stop (30 -> 1, 100 -> 127, 64, 1, -1 bare frame) with `emus_fmt`; `quant_widget` 50 -> 49, 124 -> 124 with `quant_fmt`; off VARI both pass the caller's arguments through; `emus_fmt` S950/S950/OT/OT/OT/SP12/SP12/??? at 1/42/43/64/85/86/127/-1; `tstr_fmt` OFF AUTO NORM BEAT VARI ??? ???; `quant_fmt` 1/2 1/1 2/1 |
| item11 | FLEX VARI (QUAN 109, EMUS 127, parks 70/30) -> PICKUP -> FLEX -> THRU -> FLEX -> STATIC -> STATIC VARI -> FLEX -> STATIC -> FLEX: FLEX's slots, parks and `rp_prev` never change; PICKUP's own bytes untouched; both widgets on PICKUP pass the stock dial through without polling; STATIC enters VARI with its own parks (80/40) and keeps them |
| latch | T1 VARI from frame 2 (mid-note): OT until its trig at frame 1380; EMUS -> SP12 at frame 500 (mid-note): no change until that trig; the trig's first pass (the old sound) OT, its second pass and after SP12 |
| o2 | SRC page paste of the VARI T1 onto T2: T2 gets TSTR 4, QUAN 109, EMUS 127 unswapped, its parks untouched; undone; track paste T1 -> T3 (parks travel); PART CLEAR, its UNDO, PART COPY / PASTE, RELOAD PART: each target adopted, nothing swapped, no HOLD left, depth 0 |
| o2late | after the paste, T2 plays: adopted as VARI with 109 / 127, still unswapped |
| o2rev | a non-VARI page pasted over the VARI T1, then the PLAYBACK dial polls: the pasted 50 / 20 stay, parks 70 / 30 untouched, `rp_prev` 0 |
| old56 | TSTR 5 / 6 and AUTO with TSMODE 5 / 6 for 1,500 frames: no crash, not VARI, values left as they are |

**Negative controls:** a build whose engine follows EMUS on every frame
(`out/vem_variants/mainos_varispeed_emus_wrong_latch.bin`) fails `latch`
(`[(502, 1, 2, 0), ...]`); a build without the four O2 holds (`..._no_o2.bin`) fails `o2rev`
(the pasted 50 / 20 swapped out for 70 / 30). The real build passes both.

### (c) DSP-side checks: all pass, unchanged kernel

- `tools/repitch_dsp_engine_check.py`: 89 PASS, 0 FAIL (RPS9/RPSP bit-exact with the
  DSP-exact twin on both payloads; 52.2 / 112.8 instr/sample).
- `tools/repitch_dsp_boot_check.py out/mainos_varispeed_emus.bin`: PASS on both payloads
  (memory outside Y:$A00-$FFF identical; tables + tag as the model).
- `tools/repitch_dsp_octabam_check.py`: 264/264 PASS.

### (d) octabam module

In the scratch octabam (`a67a1112`, with `modules/varispeed-emus` symlinked to this repo and a
`remixes/test/varispeed-emus` remix of the stock effects less SPRING REV): **`make bus`
succeeds.** `vem_cf: matches the author's build at 0x400d6500 (2,952 B)`; the unit lands in
DRAM at `0x40a955e0`, 18 detours, 8 symbol refs, 4 pokes; the DSP section 413 words per
payload in SPRING's run, both table blocks in SPRING's X data, both hooks wired. The image
(`a8ba2823...`) boots in ot_emu and is identical to the shipped image in the quick harness.

## 4. Deviations from the scopes, with reasons

1. **The third O2 site.** The EMUS scope's "PART menu" site `0x4005a5a8` is **machine select**
   (it writes the UI track's DB machine from `0x460d5c30`, refuses NEIGHBOR on T1/T5 with
   toast `0x400b4889`, calls `0x400972fc`) (C). The PART menu's writers are its paste core
   `0x40029a4c(clip, part)` (reached by PASTE `0x40029b78` and UNDO `0x40029b08`) and CLEAR
   `0x4004a9d0(part)` (C: handlers `0x4002e7cc`/`0x4002e868`/`0x4002e8f8`). Those two are
   wrapped; machine select is not (a machine change swaps nothing in the per-machine design).
2. **Engagement needs the runtime gate.** A track whose Part gate says VARI but whose voice
   does not (a sample lock under AUTO) plays stock (masked), not a rate-only VARI speed. This
   is what the shipped image does (first full run: `auto_*` differed on T5 until this change).
3. **Placement.** The standalone puts the unit in the classic cave from `0x400d6500` (ROM,
   proven start); DRAM is the octabam default as the scopes recommend, CAVE selectable where
   octabam has module settings.
4. **Every ATTR edit polls** (spec item 2): the two handler tails are detoured too (the first
   scope's alternative); H3/H4 still call `rp_refresh` (the dial's redraw mark), the tails
   only poll.
5. **`rp_refresh` polls all 8 tracks x both machines** (EMUS scope §6.2's mitigation for a
   gate change of the non-current machine); live bytes only for the current machine.
6. **Counted holds** (`vem_depth`): while a hold wrapper runs, `rp_forget` writes HOLD. The
   PART paste core tail-jumps into the heavy apply for the current part, whose forget would
   otherwise release the hold in the middle of the operation.
7. **UI-side swaps run at IPL 7** (`rp_swap_ui`, `rp_poll_all`), so the frame hook cannot swap
   the same pair halfway through (the inherited race, first scope R7).
8. **`rp_swap` also adopts the non-current machine's forgotten byte** (no data moves), so a
   forgotten pair does not keep a track off the cheap path after every Part apply.
9. **`emus_p2step`** asks stock's accumulator first and steps by its sign (a held `x7`, or any
   fractional delta, is still one stop) and returns `stop - old`, so P2EDIT stores the stop
   itself even if a swap moved the byte under it.
10. **The RATE-only increment is computed in closed form** (`|w - 0x4000| << 12`, stock's own
   signed `0x7f00` test, `0x04000000` when SETUP RATE is TSTR), as the first scope derived; the
   harness confirms it bit-identical with the shipped image.
11. **Module README not written** (not asked for); the manifest docstring documents it.

## 5. Known gaps

- **No hardware run.** The emulator's blind spots (no SRC SETUP draw, no real DSP timing)
  are exactly the UI and timing; the EMUS dial, captions and the ATTR row are tested only
  through direct calls.
- **STATIC** equivalence covers MMTESTDT's T1 only (the only track that triggers there);
  STATIC's swap and parks are covered by `item11`. **PICKUP** is only shown untouched.
- **Not tested:** RTRG retrigs (the kernel's pre-existing gap), a trig landing on the swap
  frame (EMUS scope §8.3 d), LFO on PTCH, MIDI-clock tempo, a sample shorter than 6,144 frames,
  the ISR load audit (`OT_ISR_OUT`).
- **The shipped image's item-11 inversion was not reproduced** in a black-box run
  (FLEX -> PICKUP -> FLEX, 50 frames each): without a UI draw or a PICKUP trig, its poll never
  saw PICKUP. So the "fixed" claim rests on the new image's own tests.
- **O2 tested by direct calls** with arguments read from the disassembly (copy core
  `0x40026314(clip, part, track, case, flag)`, undo snapshot `0x40027d38(part, track, case,
  flag)`, track copy/paste `(clip, pattern, track)` into the pattern's own part); the key
  paths themselves were not driven.
- **Old projects with TSTR 5 / 6**: no exported project from the shipped module was available;
  the load-time validator clamp (to 4) was not exercised, only runtime 5 / 6 (no crash).
- **Tracks that never triggered since a load** are not polled by the frame hook (their render
  is not the ST/FL one); the page draws and `rp_refresh` poll them, and the first trig does.
- **octabam:** built on `a67a1112`, which has no module settings (so DRAM only there); not
  built on octabam's current `main`; no `make check`, no `verify_dram_boot`.
- **The audio check's SP12 band difference** (1.05 dB) is just over the harness's own 1.0 dB
  limit; not investigated further.
- **Housekeeping:** the scratch octabam is a `git worktree` of `~/Documents/octabam`
  registered in that clone (`out/vem/octabam`, detached at `a67a1112`, with local edits to
  `tools/emu/ot_emu/dsp.{cpp,h}` and the module/remix links). Remove it with
  `git -C ~/Documents/octabam worktree remove --force <this worktree>/out/vem/octabam` when
  done; the patch is kept in `tools/varispeed_emus_ot_emu.patch`.

## 6. Draft hardware checklist (for FLASHING §4)

OS VERSION `140C_VEM2` (updated for VEM2, §8). Power-cycle once first. SPRING REV is gone
from FX2; a project that used it loads NONE there.

1. **VARI.** A FLEX loop whose ATTR TEMPO matches it. SRC SETUP: TSTR has five positions,
   the fifth reads `VARI` with a stock icon. On VARI: PTCH's caption reads `QUAN`, TSNS's
   reads `EMUS`. Change the project tempo: the loop speeds up and slows down with its pitch
   (tape style) and stays in time. QUAN: one ratio per three detents, 1/2 ... 2/1; 2/1 plays
   an octave up at double speed, 1/1 sits in the middle.
2. **RATE.** Reverse RATE plays backwards at the same speed; centre stops; a RATE p-lock
   works.
3. **EMUS.** Knob hard left `OT`, centre `S950`, hard right `SP12`; nothing in between. Six
   detents in one direction step one position (the first five show no change); turning back
   restarts the count, so wiggling the knob never flips it. Turning fast does not skip: a
   quick spin moves one position per six detents, never more; the same with the encoder
   pressed. Half a count (three detents) is forgotten when you leave SRC SETUP or change
   track. Turn it while a long note plays: no change until the next trig, then S950 grit /
   SP12 dull. 4 tracks of S950/SP12 on one core with DARK REV: no overload.
4. **Leaving VARI.** TSTR to BEAT: PTCH and TSNS show the values they had before VARI;
   back to VARI: the QUAN and EMUS you set.
5. **AUTO + ATTR.** Audio editor, ATTR, TIMESTRETCH: `VARI` after BEAT; a track on AUTO with
   that sample plays VARI; back on the PLAYBACK page PTCH reads QUAN at once.
6. **Out of range.** A sample whose tempo is outside 30-300 BPM on VARI plays as OFF, PTCH
   as pitch, caption PTCH.
7. **Machine round trips (item 11).** A FLEX track on VARI (PTCH +5 before, QUAN 3/2, EMUS
   SP12): switch to PICKUP, play a little, back to FLEX: QUAN 3/2 and EMUS SP12 unchanged,
   leaving VARI gives PTCH +5. Same via THRU. FLEX -> STATIC (STATIC on its own VARI with
   different values) -> FLEX: each machine keeps its own.
8. **Paste (O2).** Copy a VARI track's SRC page, paste on a non-VARI track: it shows the same
   QUAN ratio and EMUS (not a jump to another value); undo the paste: its old PTCH. Paste a
   non-VARI page over a VARI track: the pasted PTCH stays. Track copy/paste, PART menu
   COPY / PASTE / CLEAR / UNDO and RELOAD PART on a Part with VARI tracks: values as written,
   no PTCH/QUAN jumps.
9. **Persistence.** Save, power-cycle, reload: QUAN and EMUS as saved; leaving VARI gives the
   saved PTCH / TSNS.
10. **Old projects.** A project saved with REPITCH_REPEAT98_KYOTI on RPS9/RPSP: loads, no
   crash (TSTR shows VARI; EMUS shows the bucket of that track's TSNS, stock's 64 = S950
   since VEM2). A project saved with VEM1 shows its EMUS OT as S950 and its S950 as OT (§8.5).
11. **External MIDI clock.** VARI follows a clock tempo change.

Before the first flash, consider a diagnostic build that shows the gate, machine, `rp_prev`
and the engine on screen (first scope §5.4).

## 7. Provenance

### 7.1 Files read
- The spec, both scopes, `REPITCH_REWRITE_RETAINED.s`, `REPITCH_REWRITE_DSP_INSTALL.py` (all).
- `CLAUDE.md` (all), `START_HERE.md` and `FLASHING.md` §4 (filtered with `grep -v` on the
  keyword set), `reference/kb/caves.md` (all), `reference/handoffs/KYOTI_LOAD_AUDIT.md`
  L340-400 (filtered; the OTDEMO card's provenance).
- Allowed own code: `octabam-modules/repitch-repeat98-kyoti/README.md`,
  `patch_repitch_reload.s`, `rpk_dsp.asm` (header and the table reads), `rpk_dsp_ptable.py`
  (head); `tools/repitch_dsp_src.py` (head), the heads of the four DSP check tools.
- Examples: `tools/build_rec_trig_mute.py`, `tools/build_sidechain_compressor.py`,
  `tools/kyoti_status.py` (`seal`), `tools/dram/dram.py`,
  `octabam-modules/sidechain-compressor/manifest.py`, `tools/load_audit/la_run.py` (filtered).
- octabam (general): `tools/remix/schema.py` (no keyword hits), `tools/emu/ot_emu/main.cpp`,
  `dsp.cpp`, `dsp.h` (option parsing, the pc-watch and peek code), `CMakeLists.txt`, the
  `Makefile`, two test remixes.

### 7.2 Image facts established here (objdump of `section_3_MAIN_OS.bin` unless noted)
- The render around H1 and the voice loop (re-verified, scopes' facts) (C).
- P2EDIT's register use at the R1 call: `a3` slot2, `d3` delta (x7 when held), `d2` the old
  signed byte, `d4` track, `d5` part, `[0x460d5c30]` the page machine (C).
- The page-2 renderer's widget call `(x, y, idx, value, flags, fmt, canvas)` (C).
- Stock TSTR formatter's 4-entry table and its bound (C); the strings used (C).
- ATTR handler entry states: `d1 = 2`, `a0` settings at H3/H4; the common tails (C).
- `0x40026664` is a clipboard-compatibility check (kind and up to 11 fields vs
  `0x460c80f4..`) (C); the SRC copy core's arguments and the type word `26` at clip
  `+0x8ed8` = `0x460c80f0` (C, emulator); the undo-snapshot wrapper clears that type word (C,
  emulator: paste refused until reordered).
- Track paste writes the Part data of the **pattern's own part** (`pattern + 0x8e56 + 1`) (C).
- The PART menu's handlers and functions listed in §4.1 (C); the paste core tail-jumps to the
  heavy apply `0x40009094` for the current part (C).
- `0x400972fc(part, track)` takes two arguments (C).
- DSP `l:$40` at the kernel entry: `x:$40` low 6 bits = integer part (`0xc0` above it),
  `y:$40` = fraction incl. the engine bits (C, emulator; the stock module's unpack at
  `P:0x3c6`).
- An interrupt taken at the kernel entry re-arrives at the same PC (the log de-duplicates)
  (C, emulator).
- A track that has not triggered since a load does not reach H1 (C, emulator: `rp_prev`
  stays `0xff` on T2/T5/T6 of OTDEMO until their first trig).
- `0x400d2fe4`/`0x400d3176` are STATIC's/FLEX's `E` (the machine table gives
  `P = 0x400d301c` STATIC, `0x400d31ae` FLEX) (C, agrees with the first scope's correction).

### 7.3 Emulator runs (all scripted; outputs under `out/vem/`)
`runs/t0`, `runs/s1` (stock, the logger), `runs/v0`, `runs/a5`, `runs/pd`, `runs/mm*`,
`runs/o11` (the shipped image, item-11 differential, Part bytes only), the harness runs
`harness_otdemo/`, `harness_mmtestdt/`, `harness_octabam/`, `oracle_check_*`, the test runs
`tests/`, `tests_wrong_latch/`, `tests_no_o2/`, the DSP check logs.

### 7.4 Blacklist statement
**I did not open any blacklisted file.** Disclosures:
1. **The memory index** (`MEMORY.md`) was injected into my context by the system at start;
   I opened no memory file. It summarises the old implementation (e.g. the dirty-flag width,
   RELOAD PART bypassing `rp_forget`, DSP revisions). Nothing was taken from it; the related
   facts here come from the retained code and the image.
2. **Names only:** `ls tools/` printed the names of blacklisted tools
   (`repitch_ab_pack.py`, `repitch_ab_speeds.py`, `repitch_ch12_listen.py`,
   `repitch_probe_kyoti.cpp`, `repitch_ot_emu_trace.patch`, `repitch_sp_reference.py`,
   `repitch_test_beat.py`); `ls reference/handoffs` printed `REPITCH_REWRITE_OVERLAP.md`;
   `ls octabam-modules/repitch-repeat98-kyoti/` printed `manifest.py`,
   `patch_repitch_kyoti.s`; `ls refs/octabam/out` printed `kv1_rpk_card.img` (not used).
3. **Fragments:** a keyword `grep -n` on `tools/build_kyoti.py` and `la_run.py`, cut to 12
   and 8 characters, printed fragments such as `REPITCH_R`, `V1.4 vs V`, `same `; nothing
   else of those lines was read. The load-audit scratch's `git log -1` printed a commit
   subject naming the old module's README hardware line.
4. **octabam's `CMakeLists.txt`** (toolchain, read in full) has a test target built from
   `tools/harness/repitch_probe.cpp` with one comment sentence about Jannik's module relying
   on stock TSTR values, descriptor bounds and "one rate-selection block". I did not open the
   probe and built only the `ot_emu` target.
5. **The scratch octabam worktree** checked out `modules/repitch/` and
   `modules/repitch-repeat98-kyoti/` (and the test remixes of both); I deleted them in the
   scratch, unopened, so the registry would not load them.
6. **The oracle** was only run through the harness (outputs: DSP inputs, audio, and Part
   bytes in the item-11 differential). No disassembly, diff or trace of its code.

---

## 8. 2026-10-14: VEM2, the two fixes from the first hardware test

The user flashed `140C_VEM1` (§1) on the MKI on 2026-10-14 and reported two things: the EMUS
order should be OT, S950, SP12 (left to right), and the EMUS knob was "jumping around the
three values almost chaotically". Spec §2 item 5 was revised (commit `b076cd0`). Clean side,
same worktree. Nothing was flashed, promoted or pushed.

### 8.1 Why the knob was chaotic (C, stock code and the emulator)

How a turn reaches EMUS, read from the stock image and checked in ot_emu:

1. **The panel link.** The panel UART's command `0x3r` carries encoder r's **signed detent
   count**. The RX parser (`0x4009228c`, case `0x30` at `0x400924e4`) does not scale it.
   If the previous report for that encoder is still unread, it adds the count to the pending
   message (`0x4009250c`). Otherwise it posts a new `{type, encoder, count, stamp}` message
   (`0x40092526`). **There is no acceleration on the ColdFire side.** A report of more than
   one detent is the panel's own count, or the parser's coalescing.
2. **The UI task** (`0x40061dd2`) takes the message under IPL 7, clears the pending flag
   and calls the encoder dispatch `0x40031944(encoder, count)`. The dispatch tail-jumps to
   the handler in the live table `0x46c7dede + 20*enc`, which on SRC SETUP is P2EDIT
   `0x4003a474`. That is **one P2EDIT call per message**. Measured: one entry per report in
   every sequence below, never two.
3. **P2EDIT** multiplies the count by 7 while the encoder is pushed
   (`[0x46c7d8ee + 24*(slot2 + 0x38)]`, `0x4003a49c`). It then calls stock's accumulator
   `0x4003249c(slot2, delta)`. The divisor comes from the page's set-up `0x400326d4`: the
   encoder record's `+10` = `0x8000 / max(count, 40)`. For TSNS (count 128) that is `0x100`,
   so one unit is one value. **Any parameter with fewer than 40 values gets 3.2 detents per
   value from stock itself**: stock's own 5-position TSTR select needs 3.2 detents per position.
4. **VEM1's `emus_p2step`** turned every nonzero result into one whole stop, by its sign alone.
   So:
   - the three positions sat **one detent apart** (2 detents from end to end), 3.2x more
     sensitive than stock's own TSTR select;
   - **every reverse report flipped a whole position.** On the panel path, a `+1 / -1`
     jitter moved the value on every report (S950 / OT / S950 / OT ... in VEM1's order), and
     a turn with a back-bounce every third report swung between all three.

The other suspected causes were ruled out. A `--watch-mem` on the TSNS DB byte showed **no
writer but P2EDIT's own store** (`0x4003a5ba`), so no stock write raced ours and the snap did
not fight the stored value: the widget only displays it. The handler was never reached twice
per report. **The cause is the step rule**: any report, of any size and either sign, moved a
whole stop. The emulator cannot measure how often the MKI's encoders bounce or report
backwards. Any such report was enough to flip EMUS, and the panel tests below reproduce
exactly that on the VEM1 image.

**Emulator note (corrects the EMUS scope §4.1).** SRC SETUP opens and draws in ot_emu when the
panel's track is not T8. OTDEMO comes up on T8, where `0x400584d0` exits early
(`[0x80000000] == 7 && [0x80000034] != 0`). With `UI_TRACK = 0` poked after the load, `[SRC]`
pressed twice opens the page. It registers P2EDIT for the encoders, `0x4003c830` draws, and
`enc 5 ±n` lines in a `--live-script` reach P2EDIT through the real parser.

### 8.2 What changed

- **Order** (spec item 5): `emus_stops` stays `1, 64, 127`, now OT / S950 / SP12;
  `emus_idx` buckets: 0..42 (and negative) OT, 43..85 S950, 86..127 SP12; `emus_mode`
  `{0, 1, 2}`; `emus_tab` `OT, S950, SP12`. A fresh park (0) enters EMUS as **1 (OT)**
  (`rp_swap_m`). The DSP engine numbers are unchanged.
- **The step** (`emus_p2step`, R1). It still calls stock's accumulator first, which keeps
  stock's state and its hold-off; for TSNS the result is the report's units. On a VARI track:
  - **detents** = |units|, divided by 7 when the encoder is pushed (the same flag P2EDIT
    reads, asserted in the builder's CONTEXT), at least 1;
  - a signed count `em_tally`: a report in the other direction restarts it at 0 first; it
    adds the detents; every `EM_DETENTS = 6` makes one stop, clamped at OT and SP12;
  - a report of n detents counts n, so a fast or coalesced turn moves exactly one stop per
    six physical detents, never more;
  - the return is still `stop - old`, so a non-stop value snaps to its bucket's stop on the
    first detent, and P2EDIT stores the stop itself.
- **Reset.** The count's owner `em_ctx` (track | machine << 8 | part << 16) is compared on
  every slot-5 edit on ST/FL, VARI or not; a change restarts the count. The new detour
  **R2: `0x400585f4` (`jsr 0x400326d4`, SRC SETUP's encoder set-up) -> `jsr emus_open`**
  clears the count and tail-jumps to stock. In the emulator that site runs at every open of
  the page: entering it, and the close/re-open stock does on a **track change** (C: a track
  key on SRC SETUP re-enters `0x400584d0` with the new track and passes `0x400585f4`).
  Leaving and re-entering the page passes it too.
- **State**: `em_tally` (byte, after `rk_acc`) and `em_ctx` (long), in the unit, nowhere near
  `0x80006a40..0x80006abf` (the builder refuses that range). The QUAN tally is unchanged.
- Builder: R2 in `DETOURS`; two new CONTEXT asserts (P2EDIT's x7 test `0x4003a480..`, SRC
  SETUP's call `0x400585e0..`); default version `140C_VEM2`; 19 detours. Manifest: the same
  detour, the docstring, the new unit reference. Harness: `EMUS = {OT: 1, S950: 64, SP12:
  127}` against the oracle's TSTR 4 / 5 / 6.

Unit: **3,084 B** at `0x400d6500..0x400d710c` (2,864 B of the classic cave left), the same
bytes for `-mcpu=5407` and `54455`, sha256 `cd003bfa…` (manifest reference updated). 7,959
bytes differ from stock.

### 8.3 Build

**A new build exists: VARISPEED_EMUS VEM2, WIP, not flashed.** Rebuilt twice, same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `742b5a9b014454c42631ae3059c5b3b3e3d42f0ba4b7cd7760cd9ccce2c0e776` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `9a58af547c176e7991dee765f8edd1bac5ae64c8bf03e8daad058540c41e7dc2` |
| `out/mainos_varispeed_emus.bin` | `d298fea41fdf1e8cd3e01c2f208175397bdde66f16ebf1e6bd47639913d546da` |
| `out/elek_varispeed_emus.bin` | `109cbf3162c1c199d34eb7fd0a4302fc56ddae668b4da0db75fd1483fadbf81b` |

OS VERSION reads `140C_VEM2`. The VEM1 MAIN OS (`610846a9…`, the flashed one) is kept for
comparisons as `out/vem_variants/mainos_varispeed_emus_vem1.bin`; its `.syx` was overwritten
by this build (same output name).

### 8.4 Tests

**(b) `tools/varispeed_emus_test.py`: 18/18 PASS** (`out/vem/tests/`). The existing 11 have
the new order (fresh EMUS 1, `emus_fmt` OT/OT/S950/S950/S950/SP12/SP12 at
1/42/43/64/85/86/127, the widget's stops). `p2edit` was rewritten for the detent rule, as
direct P2EDIT calls: five detents no step, the sixth S950; one back, no step; one forward
again, no step; jitter `-1 +1 -1 +1`, no step; one report of 12 detents moves two stops, to
SP12; pushed (x7) reports count one detent each (4 forward, then 5 back no step, the sixth
S950); 30 snaps to OT and 100 to SP12 on the first detent; five back, then an edit on T2
(the owner changes), then back on T1: counting from 0; four more, then `emus_open`: counting
from 0 again, and the sixth since then steps. Gate off on T2 still steps stock (64 -> 65).

Seven new **`panel_*`** scenarios run through the real panel path: transport stopped,
OTDEMO, T1 FLEX on VARI, SRC SETUP opened with `[SRC]` x2, every stored value read at
P2EDIT's store. Expected value after each report:

| scenario | reports | VEM2 (PASS) | VEM1 (FAIL) |
|---|---|---|---|
| slow | 7x `+1` then 7x `-1`, 150 ms apart | OT x5, S950 ... S950, OT x2 | one stop every report |
| fast | 12x `+1` then 12x `-1`, **3 ms** apart (each reached P2EDIT on its own: no coalescing in the emulator) | S950 at the 6th, SP12 at the 12th; back the same way | one stop every report |
| multi | `+3 +3 +6 -2 -4 -12` | OT S950 SP12 SP12 S950 OT | one stop per report whatever its size (clamped at the ends) |
| jitter | `+1 -1` x6 | OT throughout | flips on **every** report |
| bounce | `+1 +1 -1` x6 | OT throughout (each bounce restarts) | swings across all three |
| held | encoder pushed, 7 right, 7 left | as slow | as slow on VEM1 |
| reset | 3 right, page closed + reopened, 9 right, T2 and back, 6 right | 3 + 5 no step, S950 at the 6th since the reopen, SP12 at the 6th since the track change; 4 page opens seen | SP12 by the 2nd report |

On the VEM1 image (`VEM_IMG=out/vem_variants/mainos_varispeed_emus_vem1.bin`, its syms) the
run gives **6/18**: all seven `panel_*` fail as in the table, and so do the order-dependent
checks (swap, fresh0, p2edit, widget, item11). The octabam-built image (below) passes swap,
fresh0, p2edit, latch and all seven `panel_*` (11/11, its symbols shifted to the DRAM unit).

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), EMUS OT/S950/SP12 against its
TSTR 4/5/6:
- quick set: **9/9 identical** (`out/vem/harness2_quick.txt`);
- full set, OTDEMO: **35/35 identical**: 32 equivalence scenarios, the 3 `pre_*`
  included, plus 3 out-of-range scenarios against stock OFF (`out/vem/harness2_otdemo.txt`);
- full set, MMTESTDT (STATIC), `--frames 6000`: **35/35 identical**, 3,493-11,980 passes on
  T1 (`out/vem/harness2_mmtestdt.txt`);
- the octabam-built image, quick set: **9/9 identical** (`out/vem/harness2_octabam.txt`).

The whole-run differences are the ones listed in §3 (a) (the trig latch; the transition and
adoption frames), nothing else.

**(c) DSP checks** (kernel unchanged): `repitch_dsp_engine_check.py` 80/80 bit-exact + mode
switch 8/8, 0 FAIL; `repitch_dsp_boot_check.py out/mainos_varispeed_emus.bin` PASS on both
payloads; `repitch_dsp_octabam_check.py` 264/264 PASS (`out/vem/dsp2_*.txt`).

**(d) octabam module.** Rebuilt in the scratch octabam (`out/vem/octabam`, `a67a1112`,
`REMIX=varispeed-emus BUILD=79 XBUS=1 SPEC=1 python3 tools/build/build_bus.py`, log
`out/bus_vem2.log`): `vem_cf: matches the author's build at 0x400d6500 (3,084 B)`, 19
detours including `jsr 0x400585f4 -> emus_open`; image `2a231962…`
(`out/vem/img/octabam_vem2_bus.bin`). The scratch remix's docstring now gives the new order.

### 8.5 Open points

- **Projects saved with VEM1.** The stored values keep their bytes, so VEM1's OT (64) now
  reads S950 and its S950 (1) reads OT; SP12 is unchanged. No conversion, as the spec
  asks.
- **Bounce versus the restart rule.** As the spec asks, a single reverse report restarts the
  count. If the unit's encoder reports backwards often during a forward turn (once every
  few detents), EMUS could feel stuck. `panel_bounce` shows that case: `+1 +1 -1`, never
  reaching six. The emulator cannot say how often the MKI does this. If the hardware test
  shows it, a gentler rule (a reverse report subtracts instead of restarting) is a
  one-line change.
- The hardware checklist (§6) has the new item 3, plus item 10 adjusted.
- The ACCUM hold-off flag (`0x46c7d244 + 20*slot + 12`) is still honoured. When it is set,
  the report is ignored and the count does not move.

### 8.6 Blacklist statement (this session)

I opened nothing on the spec §1 blacklist. Read: the spec (all), this file, the EMUS scope
(the P2EDIT/EMUS parts and its headings), `CLAUDE.md`, our module sources, builder, tests,
harness and manifest. Also read: the stock image (objdump and `out/clean-room/stock.dis`);
`reference/kb/memory-map.md` (key/encoder tables) and `reference/kb/octabam-index.md` §
`docs/firmware/PANEL.md`, both grepped and checked to sit outside the blacklisted section;
octabam's `docs/firmware/PANEL.md` (grepped first, no keyword hits); and `ot_emu`'s
`main.cpp` (options, the live script, watches). The oracle was run only through the harness.
Disclosures: the memory index (`MEMORY.md`) was injected into context at start, as before.
I opened no memory file and took nothing from it. The scratch octabam's build log lists
other modules' names, none of them read.
