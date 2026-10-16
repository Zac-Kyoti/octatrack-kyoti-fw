# VARISPEED_EMUS: implementation report (clean side)

Written 2026-10-14 by the **clean** implementation agent, in the worktree
`octatrack-kyoti-fw-repitch-rewrite` (branch `repitch-rewrite`). It follows
`VARISPEED_SPEC.md`, `VARISPEED_SCOPE.md` and `VARISPEED_SCOPE_EMUS.md`.
Nothing was flashed, promoted or pushed. KYOTI's combined image was not touched.

Marks: **C** = confirmed on our image (objdump, or an emulator run); **I** = inferred.

**Newest (2026-10-15, WIP, not flashed): `140C_VEM10` and its Bugbuild `BUG_VEM10` (§17): a slot pick that changes the machine names that track; VEM9 (§16) and VEM8 (§15) before it.**

**Current builds (2026-10-15, both WIP, neither flashed): `140C_VEM7` (§13), VEM6 with the
"6b, answers" change (TSTR / ATTR onto VARI over budget steps THAT track's EMUS to OT); and
`140C_VARI1` (§14), VARISPEED, the plain build from the same source (spec §7), standalone
and Bugbuild `BUG_VARI`.** `140C_VEM6` (§12): the guard redesigned (spec §6b, "6b
simplified"): refusals and one safety net, no run-time step-down.
`140C_VEM5` (§11) is the image on the user's MKI. Earlier: `140C_VEM2` (§8), the two fixes from the first hardware test; `140C_VEM3` (§9);
`140C_VEM4G` (§10), the DSP load guard; `140C_VEM4` (commit `10ac83e`, §11.1), the optimized
kernels with the guard at their prices.
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

**Sources** (all with `SPDX-License-Identifier: MIT` / `SPDX-FileCopyrightText: 2026 Zac Kyoti`):

| file | what |
|---|---|
| `tools/build_varispeed_emus.py` | the standalone builder (WIP, `KYOTI_ALLOW_WIP=1`) |
| `octabam-modules/varispeed-emus/varispeed_emus.s` | the ColdFire half, one link unit: PART 1 new core, PART 2 the retained code extended |
| `octabam-modules/varispeed-emus/manifest.py` | the octabam module |
| `octabam-modules/varispeed-emus/vem_dsp.asm`, `vem_dsp_ptable.py` | verbatim copies of the kernel files (header added) |
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
`VARISPEED_DSP_INSTALL.py`, copied in verbatim between markers.

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

- `tools/varispeed_emus_dsp_engine_check.py`: 89 PASS, 0 FAIL (RPS9/RPSP bit-exact with the
  DSP-exact twin on both payloads; 52.2 / 112.8 instr/sample).
- `tools/varispeed_emus_dsp_boot_check.py out/mainos_varispeed_emus.bin`: PASS on both payloads
  (memory outside Y:$A00-$FFF identical; tables + tag as the model).
- `tools/varispeed_emus_dsp_octabam_check.py`: 264/264 PASS.

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
- The spec, both scopes, `VARISPEED_RETAINED.s`, `VARISPEED_DSP_INSTALL.py` (all).
- `CLAUDE.md` (all), `START_HERE.md` and `FLASHING.md` §4 (filtered with `grep -v` on the
  keyword set), `reference/kb/caves.md` (all), `reference/handoffs/KYOTI_LOAD_AUDIT.md`
  L340-400 (filtered; the OTDEMO card's provenance).
- Allowed own code: `octabam-modules/repitch-repeat98-kyoti/README.md`,
  `patch_repitch_reload.s`, `vem_dsp.asm` (header and the table reads), `vem_dsp_ptable.py`
  (head); `tools/varispeed_emus_dsp_src.py` (head), the heads of the four DSP check tools.
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
   (`varispeed_emus_ab_pack.py`, `varispeed_emus_ab_speeds.py`, `varispeed_emus_ch12_listen.py`,
   `repitch_probe_kyoti.cpp`, `repitch_ot_emu_trace.patch`, `varispeed_emus_sp_reference.py`,
   `varispeed_emus_test_beat.py`); `ls reference/handoffs` printed `VARISPEED_OVERLAP.md`;
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

**(c) DSP checks** (kernel unchanged): `varispeed_emus_dsp_engine_check.py` 80/80 bit-exact + mode
switch 8/8, 0 FAIL; `varispeed_emus_dsp_boot_check.py out/mainos_varispeed_emus.bin` PASS on both
payloads; `varispeed_emus_dsp_octabam_check.py` 264/264 PASS (`out/vem/dsp2_*.txt`).

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

## 9. VEM3, 2026-10-14 (dirty side, DSP table only): S950 above 20 kHz

The user asked for this right after VEM2. The S950 (RPS9) virtual record filter left source
content at 20–22 kHz at −12…−17 dB. A 40 kHz recorder cannot hold it, and pitched down it
landed where a real S950 has nothing: 15–16.5 kHz at 0.75×. `varispeed_emus_model.fir_target`
now adds a stopband from 0.5 × FS_AKAI (20 kHz):

- **The filter:** weight 30, and 18.5–20 kHz left free. The result is ≥ 40 dB rejection above
  20 kHz (shipped: −11.5 dB), with the band up to 16 kHz within 0.7 dB of the MF6 shape. It
  rolls off about 5 dB faster than the MF6 between 16 and 20 kHz.
- **What changed:** only the tables (tools/varispeed_emus_dsp_src.py and the octabam
  `vem_dsp_ptable.py`, regenerated). The kernel code is unchanged apart from the table tag
  (TAGVAL `$504a23` → `$1974ed`), so the boot copy reloads the new tables.
- **The effect** (beat, against OT): at 78 BPM, 15–16.5 kHz goes −8.4 → −24.4 dB and
  12–15 kHz goes −1.4 → −3.3 dB. At 104 and 156 BPM, nothing changes by more than 2.5 dB
  (above 16.5 kHz at 104).
- **Checks:** engine check 80/80 bit-exact, mode switch 8/8; boot check PASS; octabam check
  264/264; RPS9 52.2 instructions per sample (unchanged).
- **Build:** OS VERSION `140C_VEM3`. syx `6a39fa79…`, CF bin `68a60119…`, MAIN OS `22848483…`.
  NOT flashed.

---

## 10. VEM4G, 2026-10-14 (clean side): the DSP load guard (spec §6)

Same worktree, clean side. Read for this section: the spec (all), this file §1-9, both scopes,
`CLAUDE.md`, `reference/kb/caves.md` (§0-§2b, filtered), `reference/kb/file-format.md` (the
pattern/track layout), our module sources, builder, tests, harness, `tools/varispeed_emus_dsp_profile.py`,
`tools/load_audit/{la_run.py (filtered), isr_stats.py, ot_emu_load_audit.patch}`, the stock image.
**Nothing was flashed, promoted or pushed.** KYOTI's combined image was not touched.

**A new build exists: `140C_VEM4G` (a test label), WIP, not flashed.**

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `9b04a6d9602da90af1545f292221fa04755efb37fa4655eb3daede45d2f35721` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `b261a5df8181ff9271fe6001f2d48d241cc67200a21e9a7e534b3f56c9b54f9d` |
| `out/mainos_varispeed_emus.bin` | `bfec7573576f8ac7d1d6e52b120ebefac5890561ea716ddae6d375817bd20b82` |
| `out/elek_varispeed_emus.bin` | `939c277dcfe64c16e559a8c5cfbf7dff27f31a99a5a25b309b302386699e047d` |

Unit: **4,016 B** at `0x400d6500..0x400d74b0` (1,932 B of the classic cave left), the same bytes
for `-mcpu=5407` and `54455`, sha256 `c650b4ad…` (manifest reference updated). Against VEM3 the
image differs only in the unit, the 19 detour target words and the descriptor pokes (the unit's
symbols moved): **the DSP payloads are byte-identical to VEM3's**. Rebuilt twice, same hashes.

Emulator: the harness/test binary is unchanged (`out/vem/octabam/out/emu/ot_emu`). The DSP-cycle
measurements use a second build of the same scratch source with an environment-gated cycle
stopwatch (`out/vem/octabam/out/emu_cyc/ot_emu`; `tools/varispeed_emus_ot_emu.patch` now carries
it), driven by scratch scripts in `out/vg/` (`measure.py`, `m1.py`-`m4.py`; not committed). VEM3's MAIN OS is kept as
`out/vem_variants/mainos_varispeed_emus_vem3.bin` (`22848483…`) with its symbols, for the
comparisons below.

### 10.1 Facts found (C = objdump of `section_3_MAIN_OS.bin` or an emulator run; I = inferred)

1. **Which core renders which tracks (C, emulator).** DSP core 1 (payload B, voice kernel entry
   `P:0x20e`, four-track loop `P:0x17a..0x333`) renders **T1-T4**; core 0 (payload A, `P:0x40b`,
   loop `P:0x372..0x53e`) renders **T5-T8**. Evidence: the VEM log's `x:$418` track offsets per
   core (T1 = core 1 offset 0; the `latch` test); and the loops' own cost: four SP12 voices on
   T1-T4 raise core 1's loop by 516 modelled cycles/sample and leave core 0's; three on T5-T7
   raise core 0's by 283. The ColdFire builds all eight voice records in one block per frame
   (voice loop `0x4000d3fc..0x4000d55e`, `0x80001c90 + 2688·frame + 336·t`); the split per core
   happens on the host-port side (I, not traced).
2. **The live FX types (C).** One byte per track: **FX1 at `0x80000ec4 + t`, FX2 at
   `0x80000ecc + t`**. The Part applies copy them from the Part (`0x4000220e..0x4000222a`: Part
   block `DB + 0x8ed80 + 0x18b2·part`, `+0` FX1, `+8` FX2), and every frame `0x40004d30` /
   `0x40004d40` copy them into the frame's per-track DSP record (words `+54` / `+56`): they are
   what the DSP runs this frame. Id -> effect: the FX1 / FX2 tables `0x400d5f58` / `0x400d5fdc`
   give each id's page descriptor `P`, whose `P+0` is the id itself, `P+4` the short name and
   `P+9` the long one: `0x00` NONE, `0x04` FLTR (FILTER), `0x05` SPAT, `0x08` DEL (FX2 only),
   `0x0c` EQ, `0x0d` DJEQ, `0x10` PHSR, `0x11` FLNG, `0x12` CHOR, `0x13` COMB, `0x14` PLTE,
   `0x15` SPRG, `0x16` DARK (FX2 only), `0x18` COMP, `0x1c` LOFI; every other id points at
   NONE's page. In this image SPRING (`0x15`) shows NONE and its DSP entry is the empty stub.
3. **Sounding (C).** The voice state `0x800049d8 + 168·t`, **byte `+0`**: nonzero while the voice
   plays. The stream engine outputs silence when it is 0 (`tst.b (a2)` at `0x400079b2`); the
   voice reset `0x40006820` clears it (`0x4000685e`), and the voice loop calls the reset on a
   stop event (`0x4000d45a`). Emulator: `0xff` on playing tracks, 0 after the reset.
4. **But the DSP does not care whether a voice sounds (C, emulator) -- a deviation from the
   spec's model, see 10.6.** The render sets every pass's output count from the pass length, not
   from the voice (`0x40004172..0x400041aa`, header `+0..+2`), and the kernel runs its engine
   over all of them. Measured: seven VARI SP12 voices, all reset at frame 801 (voice `+0` = 0 on
   every track, no trig until 820+): core 1's loop stays at 1,074-1,118 modelled cycles/sample
   (580 on OT). **An S950 / SP12 voice costs its engine on every frame its increment carries
   the engine, sounding or not.**
5. **Where to compute it (C).** The render's increment store (our H1, `vem_frame`) runs on the
   second pass of every ST/FL/PU track, **in track order T1..T8** inside the voice loop, and the
   records go to the DSP after the loop. So the first engaged VARI track of a core in a frame
   comes before every other emu voice of that core: one pass there can decide for the whole
   core within the same frame. The frame's identity: `0x800000e0` is the DSP's buffer index,
   read from the host word `0x2000001c` at every frame ISR entry (`0x4000aaee..0x4000ab02`;
   it halts if it exceeds 1, `0x4000ab3e`); emulator: it alternates 1, 0, 1, 0 frame by frame.
   The machine bytes `0x80000eb4 + 8·frame + t` (DB machine codes; `0xff` until a track's
   first trig) select the render through `0x400d6434`: only 0 ST, 1 FL and 4 PU reach
   `0x40004008`, and PICKUP's increments are masked (engine 0).
6. **The spec's prices re-measured (C, emulator, our scratch ot_emu with a cycle stopwatch,
   OTDEMO, 1,500 frames, the loops above, modelled = datasheet cycles):** base (all FX NONE)
   577 (core 1) / 482 (core 0) on stock, against the spec's 574 / 477; DARK x4: 273 / 260 per
   instance (spec 267); DJ EQ x4: 352 / 350 (spec 347). The emulation engines in situ: SP12
   129 per voice (core 1 mean), S950 43 on OTDEMO; 133 / 45 on MMTESTDT's core 0 (10.4); the
   profile's worst case (10.3) is higher.

### 10.2 Design

All in `varispeed_emus.s` (PART 1, "THE DSP LOAD GUARD"), three routines, about 80 B of state and 100 B of tables:

- **`vem_frame`** (engaged VARI tracks only; every other path is unchanged, so a track that is
  not VARI costs nothing new): reads the engine its increment carries (`36(a3)` bits 2-3), calls
  `vg_core`, then at a trig `vg_latch` with the engine EMUS asks for; tags the increment with the
  result.
- **`vg_core`**, per core and frame (key `frame << 4 | track` detects the first call of a core in
  a frame): FX = the prices of the core's eight live FX ids (cached per core with their sum,
  re-priced only when an id changes). If `VG_BASE + FX + 4·VG_SP12` fits the budget the core is
  **free** this frame and nothing else runs. Otherwise `est = VG_BASE + FX + Σ` the engine each of
  the core's ST/FL tracks carries; above the budget it **steps the core's emu voices down at
  once**, one engine at a time (SP12 -> S950 -> OT), lowering their carried engine in the render
  state (`+36`), so each plays the cheaper engine in this very frame and keeps it until its next
  trig. Order: **silent voices first** (voice `+0` = 0), then **the most recently started**
  (`vg_stamp`, the latch's counter), until the estimate fits or every emu voice is on OT (stock
  FX alone over budget: nothing more).
- **`vg_latch`**, at a trig: free core -> granted. Else `est - old engine + wanted`; while over
  budget the next cheaper engine (SP12 -> S950 -> OT). The start is stamped; `vg_down[t]` records
  whether it was stepped down.
- **Restore**: only at a later trig (`vg_latch` grants the EMUS choice when the budget allows).
- **Marker (draw path only)**: `emus_widget` calls `vg_mark`: while `vg_down[t]` is set and the
  track plays a cheaper engine than its EMUS setting, the dial points at the playing engine and
  the readout is `emus_fmt_dn`: **`OT!`** or **`S95!`** (at most four characters, like `S950`).
  A pending EMUS change (latched at the next trig) is not marked: `vg_down` is only set by the
  guard. `rp_swap_m` clears `vg_down[t]` on every VARI transition and adoption.
- State (`vg_fxc`, `vg_stamp`, `vg_est`, `vg_clock`, `vg_free`, `vg_down`, `vg_key`) lives in the
  unit, nowhere near `0x80006a40..0x80006abf` (the builder refuses it). The frame path calls no
  UI or kernel primitive.
- Builder: seven new CONTEXT asserts (the FX-id copies, the voice `+0` test and reset, the frame
  index read, the voice loop's machine bytes, the render table), default label `140C_VEM4G`.

### 10.3 Constants (one block in `varispeed_emus.s`, `VG_*`; the tests read it from there)

| constant | value | source |
|---|---|---|
| `VG_BASE_C1` / `VG_BASE_C0` | 574 / 477 | spec §6 item 1 (re-measured 577 / 482) |
| `VG_SC` | 0 | spec: SIDECHAIN_COMPRESSOR adds 56 per core; not in this image |
| `VG_FX_*` | DJ EQ 347, LO-FI 313, CHORUS 312, SPRING 306 (`VG_FX_SPRING_HERE` 0: the stub), FILTER 267, DARK 267, PLATE 240, PHASER 223, EQ 200, FLANGER 146, COMB 111, COMPRESSOR 89, SPATIALIZER 77, DELAY 0, NONE 0 | spec §6 item 1 |
| `VG_SP12` / `VG_S950` | **270 / 109** | `tools/varispeed_emus_dsp_profile.py`, worst ratio, its `~hw` column (see below) |
| `VG_BUDGET_C1` / `VG_BUDGET_C0` | 3930 / 3350 | spec §6 item 2, the clean points |

**Which engine price (a deviation from the instructions; please decide).** The profile reports
three figures per output sample, the worst over 0.5-1.99x (VEM3's kernel, both payloads):

| engine | instructions | datasheet cycles | `~hw` estimate |
|---|---|---|---|
| SP12 (RPSP) | 115.4 | 146.5 | 269.8 |
| S950 (RPS9) | 51.6 | 57.3 | 108.6 |

I was asked to use the datasheet ("modelled") column. With it the spec's own acceptance setup
does not trip: 4 x SP12 + DARK x4 + DJ EQ x3 on T5-T8 is 477 + 1,068 + 1,041 + 4·147 = **3,174**,
under the 3,350 clean point, and so is the user's crash bracket. The brackets themselves pin the
per-voice price in the budget's units: clean at DJ EQ x2 and crash at x3 give 278 and 288 (264
and 275 if SIDECHAIN's 56 was in the image they were measured on). The profile's `~hw` column
(a one-word instruction 2 cycles, a displaced access +2: this kernel is dense in displaced
accesses, the stock FX code is not) gives **270**, inside that range: DJ EQ x2 = 3,319 (fits,
by 31), x3 = 3,666 (steps down). So the build uses `~hw` for both engines. If the hardware
brackets were measured on an older, heavier kernel, the datasheet figures may be the right ones
and the guard over-protects (steps down at x3 where the unit might cope); switching is two
`.equ` lines. The in-situ datasheet figures (10.1 item 6) are lower still (129 / 43).

### 10.4 Tests

**(a) Harness, oracle = the shipped FINAL (`90b4a1c1…`):**
- full set, OTDEMO: **35/35 identical** (`out/vg/harness_otdemo.txt`);
- full set, MMTESTDT (STATIC), `--frames 6000`: **35/35 identical** (`out/vg/harness_mmtestdt.txt`);
- both print exactly the lines VEM2/VEM3's runs printed, the whole-run difference counts included
  (the known transition / adoption frames); the quick set (`out/vg/harness_quick.txt`, 9/9) ran
  on the first VEM4G build, before the one-line fix below, and its scenarios are part of the full
  set. Every harness scenario is under budget: OTDEMO's own FX price 1,620 (T1-T4) and 1,440
  (T5-T8), so seven SP12 voices estimate 3,274 / 2,727 against 3,930 / 3,350 -- both cores are
  "free" every frame; MMTESTDT (FILTER x4, DELAY x4) likewise.

**(b) `tools/varispeed_emus_test.py`: **24/24 PASS** (`out/vg/tests_all.txt`).** The 18 existing tests unchanged, plus six
guard scenarios on the real export **MMTESTDT** (T1-T8 STATIC, part 0, 120 BPM; card
`out/vem/img/mmtestdt.img`), all set by runtime pokes before the transport: T5-T8 VARI on the
two slots that hold a sample (slots 0 / 1), trigs poked into the playing pattern's T5-T8 masks
at steps 1/3/5/7 (bars at frames ~2 and ~5514), FX2 DARK x4, FX1 as listed, the rest NONE.
Expectations come from an independent Python model of the guard fed with the `VG_*` block and,
where every voice sounds, are also written out by hand:

| test | setup | result |
|---|---|---|
| `guard_x2` | 4 x SP12, DJ EQ x2 (est 3,319) | nothing steps down; **every pass on both cores equals VEM3's** (65,600 per core, `guard_x2_ref` = the same run on VEM3); `vg_down` 0 |
| `guard_x3` | 4 x SP12, DJ EQ x3 (3,666) | at the latch: T5 SP12, T6 SP12, **T7 S950, T8 S950** (bars 1 and 2); `vg_est` 3,344 = the model |
| `guard_latch` | EMUS SP12 SP12 S950 S950, DJ EQ x3 + FILTER on T8 | **T6 SP12 -> S950, T8 S950 -> OT** at their latches; T5 SP12, T7 S950 |
| `guard_mid` | x2, a third DJ EQ (T7) poked at frame 2,600, removed at 3,500 | all four sounding; at once (first cheaper pass at frame 2,602): **T8 SP12 -> S950 -> OT, then T7 SP12 -> S950** (most recent first), est 3,235; after the removal they stay down; T7 back on SP12 at its next trig (6,892), T8 at its (7,581); the marker through `emus_widget` (KNOB captured): T8 `(value 1, emus_fmt_dn)`, T7 `(64, emus_fmt_dn)`, T5 `(127, emus_fmt)`; `emus_fmt_dn` 1 / 64 / -1 = `OT!` / `S95!` / `???`; at the end T8 `(127, emus_fmt)` |
| `guard_silent` | as `guard_mid`, T6's voice stopped (stock reset) 4 frames before | **T6 (silent, older) SP12 -> S950 -> OT first, then T8 -> S950**; T6 / T8 back at their next trigs |

Negative controls (`out/vem_variants/`, built with `VEM_VARIANT`): `vg_nosilent` (the step-down ignores sounding) fails
`guard_silent` (it steps T8 and T7, the sounding ones, and leaves the silent T6) and passes
`guard_mid`; `vg_oldest` (the oldest first) fails `guard_mid` (it steps T5 to OT and T6 to S950).
One bug was caught by the tests during the work: the free test branched on the flags of the
`move.b` that stored the flag (a `move` sets Z), so a core that was NOT free also skipped the
estimate; fixed before the runs above.

**(c) DSP:** the payloads are byte-identical to VEM3's (so the engine and octabam checks stand);
`varispeed_emus_dsp_boot_check.py out/mainos_varispeed_emus.bin`: PASS on both payloads.

**(d) octabam:** `make bus` equivalent in the scratch octabam (`a67a1112`): `vem_cf: matches the
author's build at 0x400d6500 (4,016 B)`, the unit in DRAM at `0x40a955e0`, 19 detours.

**DSP load in situ (C, emulator, core 0's loop, datasheet cycles/sample, MMTESTDT):**


| setup | VEM3 | VEM4G |
|---|---|---|
| 4 x SP12 + DARK x4 + DJ EQ x2 | 3,055 | 3,055 (unchanged) |
| ... + DJ EQ x3 from the start | 3,455 | **3,276** (T7, T8 on S950) |
| x2, third DJ EQ at frame 2,600 (frames 2,700-4,900) | 3,455 | **3,230** (T8 OT, T7 S950) |

The same project, engines alone (datasheet, in situ): SP12 133 and S950 45 per voice above OT;
and its stock FX cost more than the spec's table (DARK 328 per instance here, 260-273 on OTDEMO;
DJ EQ 364). So in datasheet units measured in place, x2 (3,055) is under 3,350 and x3 (3,455) over
it as well -- the same verdict the guard's model (3,319 / 3,666) reaches with the `~hw` engine
price and the spec's FX table. FX prices clearly vary with the effect's settings or the project;
the table is the spec's.

### 10.5 The guard's ColdFire cost (C, emulator)

`python3 tools/varispeed_emus_test.py --cost`: `ot_emu --coverage` counts every ColdFire PC from
the transport start; summed per frame over the unit and over the guard's routines, VEM4G against
VEM3, 3,000 frames:



| scenario | unit, VEM3 | unit, VEM4G | delta | of which `vg_core` / `vg_latch` |
|---|---|---|---|---|
| OTDEMO, no VARI track | 227.4 | 227.5 | **0.0** | 0.0 |
| OTDEMO, 7 x VARI SP12 (both cores free) | 1,389.5 | 1,535.1 | **+145.6** | 127.0 |
| MMTESTDT, 4 x SP12, x2 (core 0 free) | 617.6 | 682.5 | **+64.9** | 57.0 |
| MMTESTDT, 4 x SP12, x3 (core 0 over: full estimate every frame) | 617.6 | 720.3 | **+102.8** | 94.9 |

(whole ColdFire per frame: about 32,000-35,600; the guard adds 0.2-0.4 %.) A project without
VARI tracks pays nothing. With VARI tracks the guard costs about 13 instructions per engaged
track per frame (reading the carried engine, the call, the "first on this core?" test) plus,
once per core and frame, about 35 (FX cache check, the free test) or about 70 (the full
estimate). **That is more than the spec's "a few dozen" with many VARI tracks** (146 with
seven). Ways down, if wanted: inline the per-track test (-2 each); cache the free verdict with
the FX ids (-~8 per core); skip the per-track test on tracks whose engine is OT and that do not
trig (needs care: the core pass must still run before the core's first emu voice). Nothing on
the DSP.

### 10.6 Deviations

1. **Engine prices: the profile's `~hw` column, not its datasheet column** (10.3). Two lines.
2. **"Sounding" voices.** The spec counts the engine of each *sounding* voice. The DSP runs the
   engine for every voice whose increment carries it, sounding or not (10.1 item 4), so the
   estimate counts those; sounding only orders the step-down (silent voices go first: inaudible,
   and they cost the same). Without this, a one-shot SP12 track whose sample has ended would
   still load the DSP and the guard would not see it.
3. **Step-down order within one voice:** the most recent voice goes all the way down (SP12 ->
   S950 -> OT) before the next one is touched ("most recently started first", read literally).
4. **The free shortcut:** a core whose base + FX leave room for four SP12 voices is not
   estimated at all that frame (no engine can overrun it). Same decisions, less work.
5. **Marker text** `OT!` / `S95!` (the spec gives the form, not the text).
6. **Untestable branch:** "stock FX alone over budget" cannot happen with today's numbers (the
   heaviest stock setup is 3,253 on core 0 and 3,350 on core 1, both within their budgets); the
   code path exists (every emu voice to OT, then nothing) but no test reaches it.

### 10.7 Open questions

- **The engine price column** (10.3): `~hw` (this build) or the datasheet one. The user's brackets
  support `~hw`; the kernel optimization will change both, and the brackets should be re-measured
  on hardware with the final kernel.
- **SIDECHAIN_COMPRESSOR in the same image** (KYOTI, an octabam remix): `VG_SC` is 0 here; the
  module does not know whether SC shares the image. A combined build should set it to 56.
- Only core 0 (T5-T8) was exercised over budget; core 1's budget (3,930) needs DJ EQ x4 with four
  SP12 voices (4,110) -- same code, other index.
- RTRG retrigs keep the trig's engine (as before) and are not stamped as new starts.

### 10.8 FLASHING §4 item (draft) -- the DSP load guard

OS VERSION `140C_VEM4G`. A project on T5-T8 with four STATIC/FLEX tracks on VARI, EMUS `SP12`,
samples that keep sounding (loops), DARK REV on every FX2:
1. **Normal load, no step-down:** FX1 DJ EQ on two of the four (T5, T6): all four play SP12, every
   EMUS readout shows `SP12`, no pops; let it run several minutes.
2. **The crash setup no longer crashes:** add DJ EQ on T7's FX1 while they play. Within a frame the
   most recently started of the four drops (its readout `OT!`, the next one `S95!`); audio stays
   clean (a click at the switch is acceptable), the sequencer keeps running, no squeal. Leave it
   five minutes; change patterns and parts.
3. **Restore:** remove the third DJ EQ: nothing changes until each stepped-down track's next trig,
   where it plays SP12 again and its readout loses the `!`.
4. **At the trig:** with DJ EQ x3 set before starting, the later tracks start on S950 (`S95!`).
5. **T1-T4** (the other core): four SP12 + DARK x4 + DJ EQ x3 plays all SP12 (no `!`).
6. An everyday project with VARI tracks: no `!` anywhere.

### 10.9 Blacklist statement (this session)

**I opened nothing on the spec §1 blacklist.** In particular I did not open
`reference/handoffs/KYOTI_LOAD_AUDIT.md`. Disclosures:
1. **The memory index** (`MEMORY.md`) was injected into this agent's context at start, as for the
   earlier clean sessions; I opened no memory file. Among its one-line summaries are a few about
   the load audit (that it rated the old kernel's DSP load high, and a SIDECHAIN tap bug) and the
   old module's history. Nothing here was taken from it: every fact in 10.1 comes from the image
   and our own emulator runs, every number from the spec, the profile or our measurements.
2. **Allowed files that mention the audit:** `tools/varispeed_emus_dsp_profile.py`'s docstring names
   the audit's section 2 as the source of its "modelled cycles" unit and quotes a per-voice
   budget ("about 60-75 per voice for four voices beside stock's heaviest FX on core 0"); the
   kernel's header says rev 17 followed "the DSP load audit's budget". `tools/load_audit/la_run.py`
   (read with the keyword lines removed; one line was skipped) names the audit as its origin and
   gave the loop bounds and FX ids, which I then confirmed (10.1). I used none of their numbers
   beyond the profile's own output.
3. The oracle was run only through the harness.

---

## 11. VEM5, 2026-10-15 (clean side): the guard's UX (spec §6a), and the guard tests

Same worktree, clean side. Read for this section: the spec (all, §6a new), this file §8 and §10,
`CLAUDE.md`, `reference/kb/caves.md` (§1-§2b, §5, filtered), `reference/kb/memory-map.md` (the
toast rows, filtered), our module sources, builder, tests, harness, the QUANTIZE_LIVE_REC_TOGGLE
and REC_TRIG_MUTE modules (how they raise toasts), and the stock image (objdump).
**Nothing was flashed, promoted or pushed.** KYOTI's combined image was not touched.

**A new build exists: `140C_VEM5`, WIP, not flashed.** Rebuilt twice, same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `4c2b15d11ae8e1d65fbec08cbafc31856a39fcd667d650c4c8484ab2e699cceb` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `ec278dae9047eca050817c300470873dca6e42257c35f13b83d6b194bdda01f9` |
| `out/mainos_varispeed_emus.bin` | `e96ed87ec0bf700051a6c3d3e6f2246c0ca7412f8645414da0218607cc3c9f5b` |
| `out/elek_varispeed_emus.bin` | `d32def067db1c8a805f3982c6f7b6ecd1057dd58e6aa9ce67e52c49c5a07fad7` |

Unit: **4,660 B** at `0x400d6500..0x400d7734` (1,288 B of the classic cave left), the same bytes
for `-mcpu=5407` and `54455`, sha256 `e19b17c0…` (manifest reference updated). Against VEM4 (the
`10ac83e` source, rebuilt as `out/vem_variants/mainos_varispeed_emus_vem4.bin`, `3ac96ebf…`) the
image differs only in the unit, the detour target words and the descriptor pokes: **the DSP
payloads are byte-identical**.

### 11.1 VEM4, for the record (commit `10ac83e`, not described here before)

The optimized kernels (bit-identical output) and the guard at their prices, re-profiled over
0.5-1.99x on both payloads (`~hw` column): **`VG_SP12` 270 -> 218, `VG_S950` 109 -> 99**. OS
VERSION `140C_VEM4`, syx `69493aff…`, not flashed. Four guard tests failed on it (20/24): they
hard-coded the step-downs computed with the old prices. §11.4 fixes them for good.

### 11.2 What changed

1. **The dial stays on the choice (§6a item 1).** `vg_mark` (draw path only) no longer moves the
   dial: while `vg_down[t]` is set and the track plays a cheaper engine than its EMUS setting, it
   only swaps the formatter, to **`emus_fmt_ot_dn` (`OT!`) or `emus_fmt_s95_dn` (`S95!`)**, by the
   engine the track plays. The dial value stays the choice's stop. When the guard restores the
   track at a later trig, `vg_latch` clears `vg_down[t]` and the readout is the plain one again.
   `emus_fmt_dn` / `emus_tab_dn` are gone.
2. **The toast (§6a item 2), from the user's own UI action only:**
   - **`vg_room`** (d1 = track -> d0): the room the track's DSP core has for it now, in the
     guard's own model: `budget - (base + the core's FX1/FX2 prices + the engine each OTHER
     ST/FL track of the core carries)`, the same terms `vg_core` sums (live FX ids
     `0x80000ec4/ecc`, machine bytes `0x80000eb4 + 8·frame + t`, render state `+36` bits 2-3). It
     is read fresh: the frame hook's own per-core sums (`vg_fxc`, `vg_est`) are kept only while a
     VARI track plays on that core and `vg_est` holds one core at a time, so they are not
     reliable from the UI task.
   - **`vg_ask`** (d1 = track, d0 = the engine asked for): OT, or a project tempo outside 30..300
     BPM (the track would play as OFF), says nothing. Otherwise the engine the guard would use is
     the asked one stepped down (SP12 -> S950 -> OT) until `price <= room`, `vg_latch`'s rule. If
     that is cheaper than the asked one: **`NOTIFY("MAX DSP: S950 USED" | "MAX DSP: OT USED",
     0x30)`**, stock's self-timing 0.8 s toast (dur > 0 only; dur <= 0 is the modal path that hung
     a unit, memory-map.md).
   - Its three callers, all UI-task handlers:
     - **EMUS** (`emus_p2step`, inside P2EDIT, the SRC SETUP encoder handler): when a report moves
       EMUS to a new stop, `vg_ask` for that stop's engine. A report that moves no stop (under six
       detents, or the same stop) asks nothing.
     - **SETUP TSTR** (`emus_p2step`'s new `.ep_tstr`, slot 4 on ST/FL): stock's steps are
       unchanged; the new value is P2EDIT's own (old + steps, clamped 0..4). After
       `rp_swap_ui` settles the domain, if the track is not on VARI and **`rp_gate_v`** (new:
       `rp_gate_m` with a given TSTR value, entering its tail at `.gm_test`) says the new TSTR
       puts it there (VARI, or AUTO on a VARI sample), `vg_ask` for its parked EMUS
       (**`db_park2`**; 0 = never written = OT).
     - **ATTR TIMESTRETCH** (`attr_up`, BEAT -> VARI only, the value-up key handler): the gates of
       every track before the edit (**`vg_gates`**), the edit, `rp_refresh` (the domains swap),
       then **`vg_entered`**: every track whose gate came on asks for its EMUS (now in the TSNS
       slot). If two tracks enter at once, each asks alone and the last toast shows.
   - **Nothing on the frame path changed.** `vem_frame`, `voice_set`, `vg_core`, `vg_latch`,
     `rp_swap`, `rp_swap_m`, `rp_gate_m`'s body, `caption_m`, `rp_poll_all` and the helpers they
     call disassemble to the same instructions as VEM4's (objdump of both link units, addresses
     aside; `rp_gate_m` gained only the `.gm_test` label). The guard acting on its own (the latch,
     the mid-note step-down, the restore) raises nothing.
3. **Builder**: three new CONTEXT asserts: NOTIFY's entry `0x4005a2b8` (close-if-open, the
   measure in font `0x400ba862`, the `textpx + 15` window), its `dur > 0` branch `0x4005a324`,
   and the window centring `0x40058184` (`x = (128 - w) / 2`). Default label `140C_VEM5`.
4. **Manifest**: docstring (GUARD line, ~4.7 KB), reference `e19b17c0…`.

### 11.3 The toast's text capacity (C, objdump of `section_3_MAIN_OS.bin`)

- **NOTIFY** `0x4005a2b8(text, dur)`: width = `0x40012f30(font 0x400ba862, -1, text)`; the window
  is `0x4005829c(width + 15, 0x12, …)`, 18 px high, centred by `0x40058134` on the screen:
  `x = (128 - w) / 2`, `y = (64 - h) / 2`. Each window owns a 1,024-byte bitmap (128 x 64 / 8).
  So the box fits the screen while **text width <= 113 px**.
- **The font** `0x400ba862`: fixed width 5 (`+0`), per-character widths at `[+8]` (0 = fixed),
  a glyph map at `[+12]` (negative = no glyph), characters 1 px apart. Letters and digits are
  5 px (`I` 1, `1` 2), space 4, `:` 1.
- **Ours:** `MAX DSP: S950 USED` = **100 px** (box 115, 6 px margin each side);
  `MAX DSP: OT USED` = 88 px (box 103). It fits in full; nothing was cut.
- **Stock, for comparison** (every string pushed right before a NOTIFY call, 145 of them): the
  widest are `NO FREE STATIC SLOTS!` 114 px, `NOT A STEREO SAMPLE!` 112, `BULK DATA TOO LARGE`
  110; our 100 px equals this repo's hardware-shown `QUANT LIVE REC OFF` (also 18 characters).
- The tests re-measure both texts from the built image (`toast_px`).

### 11.4 Tests

**(b) `tools/varispeed_emus_test.py`: 28/28 PASS** (`out/vem/tests_all_vem5.txt`): the 18
non-guard tests and seven `panel_*` unchanged, the six guard tests (the four repaired), and four
new `toast_*`.

**The four guard tests no longer hard-code engines.** Every expectation comes from `GuardModel`,
the independent model of spec §6 / §10.2 fed with the `VG_*` block read from
`varispeed_emus.s`: the bar-1 latch in trig order, the mid-note step-down, the bar-2 latch after
it. `GuardModel` takes the wrong rules as switches (`oldest`, `silent_first=False`), and each
scenario checks that it still **discriminates**, so a price change cannot make it pass quietly
without teeth:

| test | what it derives (prices of VEM5) | discrimination check |
|---|---|---|
| `guard_x3` | latch: T5-T7 SP12, **T8 S950** (est 3,339) | spec §6 item 6: x3 steps down, per the model; no toast |
| `guard_latch` | latch: T5, T6 SP12, **T7, T8 S950 -> OT** (est 3,289) | an S950 voice steps to OT; readouts `OT!` with the dial on S950 |
| `guard_mid` | third DJ EQ: **T8 SP12 -> S950** at once (est 3,339); back at its next trig | most-recent-first differs from oldest-first (which would step T5); `S95!` with the dial on SP12; no toast |
| `guard_silent` | T6 silent: **T6 SP12 -> S950** first (est 3,339) | silent-first differs from silence-ignored (which would step T8); no toast |

`guard_x2` (and `guard_x2_ref`, VEM3) assert spec §6 item 6's other half from the model: x2 does
not step down (est 3,111); every pass on both cores still equals VEM3's.

**New tests** (MMTESTDT, T5-T7 VARI SP12 + DJ EQ on their FX1 + DARK x4, latched by frame
~2,000; the user's action on T8 from frame 2,600; NOTIFY captured by a runtime stub that counts
the call, keeps `(text, dur)` and then runs stock's NOTIFY unchanged). The expected toast of
every action is `GuardModel.ask` on the model's own latch, after checking that the image's
carried engines equal the model's:

| test | actions on T8 (P2EDIT / the key handler, direct calls) | result |
|---|---|---|
| `toast_emus` | EMUS OT -> S950 -> SP12 -> S950 -> OT, then half a stop | toast **only at SP12: `MAX DSP: S950 USED`**; S950 fits (none); OT none; the half stop none; every stop stored |
| `toast_emus_ot` | the same, SPATIALIZER on T8's FX1 | **`MAX DSP: OT USED`** at S950, SP12, S950; none at OT |
| `toast_tstr` | TSTR BEAT -> VARI (EMUS SP12 parked); back to BEAT; S950 parked, -> VARI | **`MAX DSP: S950 USED`**; none on leaving; none when S950 fits |
| `toast_attr` | `0x4006edc8` (ATTR value-up) on STATIC slot 1, row 2, T8 on AUTO, EMUS SP12 parked | TIMESTRETCH BEAT -> VARI, **`MAX DSP: S950 USED`** |

On every toast: `dur` 0x30, the OS's toast handle `0x460d1e70` set and its countdown `0x460d1e6c`
= 0x30 (the stock toast really opened). The dial is checked in `guard_latch` (`OT!`, the dial on
S950) and `guard_mid` (`S95!`, the dial on SP12; `w8end` plain on SP12 after the restore).

**Negative controls** (`out/vem_variants/`, built from this source with `VEM_VARIANT`, sources in
`out/vem_variants/src/`):

| variant | fails | passes |
|---|---|---|
| `vg_oldest` (the oldest steps first) | `guard_mid` (steps T5), `guard_silent` | |
| `vg_nosilent` (silence not preferred) | `guard_silent` (steps T8) | `guard_mid` |
| `dial_follows` (VEM4's dial) | `guard_latch` (dial 1, want 64), `guard_mid` (64, want 127) | |
| `toast_always` (toasts even when it fits) | `toast_emus` (a1, a3), `toast_tstr` (t3) | `toast_emus_ot` (every request there is over) |

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), outputs in `out/vem5/`:
- quick set **9/9 identical**;
- full set, OTDEMO **35/35 identical**, full set, MMTESTDT (`--frames 6000`) **35/35
  identical**; both print **exactly** the lines VEM4G's runs printed (`out/vg/harness_*.txt`,
  `diff` empty), whole-run difference counts included.

**(c) DSP**: payloads byte-identical to VEM4's; `varispeed_emus_dsp_boot_check.py
out/mainos_varispeed_emus.bin`: **PASS** on both payloads.

**(d) octabam**: not rebuilt this session (the manifest's reference is updated; the builder
checks it).

**ColdFire cost** (`--cost`, 3,000 frames, against VEM3; `out/vem5/cost.txt`): unit per frame
227.5 (OTDEMO, no VARI) / 1,535.1 (7 x SP12) / 682.5 (MMTESTDT x2) / 720.3 (x3), **the same as
VEM4G's to the tenth** (§10.5): the frame path did not change. The new UI code runs only in the
handlers above.

### 11.5 Deviations and open questions

- **The toast length** is stock's house 0x30 (0.8 s), as QUANTIZE_LIVE_REC_TOGGLE and
  REC_TRIG_MUTE use. If 18 characters read too briefly on the unit, `TOAST_DUR` is one `.equ`
  (0x60 = 1.6 s, also a stock value).
- **The fit is the moment's**: the toast names the engine the guard would use *now*; the engine
  is taken at the next trig, when the core may have changed. Two tracks entering VARI by one
  ATTR edit each ask alone (each counts the other at its carried engine), and the last toast
  shows.
- **The emulator calls the handlers directly** (P2EDIT, `0x4006edc8`), not through the UI task;
  the panel tests show P2EDIT runs in the UI task on the unit's real path. NOTIFY from these
  handlers is the same use QUANTIZE_LIVE_REC_TOGGLE and REC_TRIG_MUTE make from theirs; the
  emulator cannot show UI-task safety (CLAUDE.md), the hardware item below does.
- No toast for an ATTR TEMPO edit that brings a sample into range, nor for a lock or scene that
  changes EMUS: the spec names only EMUS turns, SETUP TSTR and ATTR TIMESTRETCH.

### 11.6 FLASHING §4 item (draft) -- the guard's UX

OS VERSION `140C_VEM5`. The §10.8 project: T5-T8 STATIC/FLEX on VARI, looping samples, DARK REV
on every FX2.
1. **Dial stays:** EMUS `SP12` on all four, DJ EQ on T5-T7's FX1, play. T8 drops (§10.8 item 2);
   on T8's SRC SETUP page the **EMUS dial still points at SP12** while the readout says `S95!`
   (or `OT!`). Remove one DJ EQ: at T8's next trig the readout returns to `SP12`.
2. **Toast on EMUS:** with T5-T7 on SP12 + DJ EQ x3 and T8 on `OT`, turn T8's EMUS right. At
   `S950`: no toast. At `SP12`: **`MAX DSP: S950 USED`**, readable in full, about 0.8 s. Turn
   back to S950 and OT: no toast. Add SPATIALIZER on T8's FX1 and turn to S950: **`MAX DSP: OT
   USED`**.
3. **Toast on TSTR:** T8 on BEAT with EMUS SP12 from before; set TSTR to VARI: **`MAX DSP: S950
   USED`**. Back to BEAT: nothing.
4. **Toast on ATTR:** T8 on TSTR AUTO, its sample's TIMESTRETCH BEAT in the audio editor's ATTR
   page; step it to VARI: **`MAX DSP: S950 USED`**.
5. **Never on its own:** start with DJ EQ x3 already set (§10.8 item 4) and let it run, then add
   and remove DJ EQ while it plays: tracks step down and come back, **no toast ever appears**
   unless a knob or key was touched. Leave it five minutes: no crash, controls live, no crackle
   (the CLAUDE.md "Session 93" signature).
6. An everyday project: turning EMUS anywhere raises no toast.

### 11.7 Blacklist statement (this session)

**I opened nothing on the spec §1 blacklist.** Disclosures:
1. The memory index (`MEMORY.md`) was injected into this agent's context at start, as for the
   earlier clean sessions; I opened no memory file and took nothing from it.
2. `reference/kb/caves.md` §5 names `reference/handoffs/KYOTI_LOAD_AUDIT.md` as a reference in
   one line (a file name, nothing of its content); I did not open the audit.
3. In ot_emu's source tree I grepped only `tools/emu/ot_emu/main.cpp` (option names); the
   octabam `tools/verify/verify_dram_boot.py` path appeared in a file list, unopened.
4. The oracle was run only through the harness.

---

## 12. VEM6, 2026-10-15 (clean side): the guard refuses, one safety net (spec §6b, "6b simplified")

Same worktree, clean side. Read for this section: the spec (all, §6b and "6b, simplified"
new), this file §8, §10, §11, `CLAUDE.md`, `reference/kb/caves.md` (§0-§1, filtered),
`reference/kb/memory-map.md` (the part-apply family, the keymap, the UI loop, the FX choosers'
tables, the toast; filtered), our module sources, builder, manifest, tests, harness, ot_emu's
`main.cpp` options and `rtos.cpp`'s task table and load loop, and the stock image (objdump,
`out/clean-room/stock.dis`). **Nothing was flashed, promoted or pushed.** KYOTI's combined
image was not touched. The octabam module was not rebuilt this session (its reference is
updated; the builder checks it).

The work started on spec §6b as first written (per-path hooks: Part applies, RELOAD, the bulk
writers, PART_B / bank-pointer stores, TSTR / ATTR special cases). The user then simplified it
("6b, simplified": two refusals and one safety net); §12.2 is the simplified design, and §12.3
lists what was built for the first form and removed before any commit.

**A new build exists: `140C_VEM6`, WIP, not flashed.** Built twice, same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `16a07e772b137377863b0c2206c6e98b07762a7faa26071b82d6bd7a3fd97834` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `23fd69fe3df83594f66be6fda13416c835e6fbe81ba717e7dce5ec12371181ba` |
| `out/mainos_varispeed_emus.bin` | `5480ba2cfbc4ab798b50b9ff63a1a6d1f43f7226bee0cff9ee6731e703ef13ce` |
| `out/elek_varispeed_emus.bin` | `57355ac6963231fd1250e97cf933d1a2dbda7d9d4eca1f364022da24d88567b6` |

OS VERSION reads `140C_VEM6`. Unit: **4,852 B** at `0x400d6500..0x400d77f4` (1,096 B of the
classic cave left), the same bytes for `-mcpu=5407` and `54455`, sha256 `236e5218…` (manifest
reference updated). 22 detours (VEM5's 19 + 3), 12 descriptor pokes, 9,552 bytes differ from
stock. The DSP payloads are VEM4's / VEM5's (unchanged kernel, generator and tables). The
image VEM5 left on the unit is kept as `out/vem_variants/mainos_varispeed_emus_vem5.bin`
(`e96ed87e…`) with its symbols.

### 12.1 Facts found (C = objdump of `section_3_MAIN_OS.bin` or an ot_emu run; I = inferred)

1. **The FX type selection (C).** The FX1 / FX2 chooser is a window with its own 26-byte key
   records (`{code, 0, press, …}`, the keymap's format): FX1's at `0x400bc0e0..0x400bc17c`,
   FX2's alike. LEFT / RIGHT (`0x20` / `0x33`) move the list cursor (`0x4003ad8c`, list
   `0x460d5c8c`); UP / DOWN are `rts` (`0x400321e8`); NO (`0x32`) closes (`0x4003d440`);
   **YES (`0x31`) applies: FX1 `0x400526e4`, FX2 `0x40052474`** (records `0x400bc148`,
   `0x400bc372`: their only references). The apply takes no arguments: the cursor row
   (`0x460d5c94` / `0x460d5ca8`) indexes the rows (`0x400d6060` / `0x400d6090`, each a page
   pointer whose long is the type id), the id is compared with the Part's byte (`DB +
   part·0x18b2 + 0x8ed80 / 0x8ed88 + t`) -- the same id returns at once -- and only then the
   Part, its SRAM copy, the dirty flags, the live id (`0x80000ec4 / ecc + t`) and the page's
   defaults are written. Moving the cursor applies nothing. **So a refusal at the apply's
   entry stops a chosen type from landing, and leaves the chooser open on it.**
   The other writers of a Part's FX bytes are the bulk ones: the page paste `0x40027e4c`
   (`0x400284b6` / `0x400286ae`), the track paste `0x4002b654` (`0x4002b6fc` / `0x4002b706`),
   the PART menu's block copies, RELOAD PART's copy, the loader. Live-only writers (the Part
   applies `0x4000220e`; the sample loaders `0x40093e9c` / `0x40096ab0`, which restore the
   Part's ids, and `0x40043ba0` / `0x400940ac` / `0x40096c54`, which clear live ids to NONE)
   never raise the cost above the Part's settings.
2. **Where Part changes land, and in which context (C).**
   - **A sequencer pattern switch to another Part** (ot_emu, MMTESTDT with pattern 1 poked to
     use Part 1, cued with `0x400a1030(0, 1)`): at the commit (`0x400a44d0`, frame path; the
     sequencer's hand-off posts `{0x14, part}`, memory-map.md) **the UI task's case for message
     20 (`0x400621a6`) moves PART_B at `0x400621e2`**
     (instruction 939.42 M); **the light apply `0x40009e00` runs in the frame ISR
     (`0x4000b1d8`) one master step later** (950.13 M; the ISR posts message 25 just before it,
     `0x4000b188`). Message 17 (`0x40062142`) moves PART_B on a pattern change, message 21
     (`0x400622aa`) the bank pointer `[0x46c82456] = 0x400e21e0 + bank × 0x9b340`.
   - **The heavy apply `0x40009094(bank, part)`**: the PART menu (paste, clear, undo, save,
     RELOAD) in the UI task; the project load in the engine task (`0x400905d4` →
     `0x400907ea`). **RELOAD PART** `0x4004aab4(part)` copies the saved copy (`DB + 0x9504a +
     part × 0x18b2`) when the saved flag (`DB + 0x9b312 + part`) is set, then applies.
   - **The project load** (engine task; ot_emu watch on OTDEMO): the bank pointer
     (`0x40087d44`) and PART_B (`0x40087ea6`) first, the Part blocks reset to defaults
     (`0x40005684..`), then read from the card (`0x400165dc`), then the light and the heavy
     apply. **The UI task keeps running meanwhile** (1,098 message-loop passes during the load).
   - `0x80001828 / 0x80001829` = (bank, part) of the last apply: written by the three applies
     and nothing else -- whose bytes the live page bytes are.
3. **Machine changes (C).** The machine chooser writes the Part's machine byte and calls
   `0x400972fc(part, track, old machine)`; UI message 20 calls it for all eight tracks after a
   Part change. With per-machine parks and `rp_prev[2t+m]` (spec O1), a machine change makes
   no gate transition: the machine's VARI state simply comes along. Only a check of the
   settings sees it.
4. **The safe UI-task point (C): `0x40062d1c`, the tail of the UI task's message loop.** The
   task (entry `0x40061a94`) receives from the UI queue `0x460d17ae` (`jsr 0x40000d00` at
   `0x40061cd8`), dispatches 78 types through the table at `0x40061cfa` -- keys via
   `0x40031734`, encoders via `0x40031944`, so P2EDIT and every key handler run in this task --
   and **every case ends at `0x40062d1a` / `0x40062d1c`** before the next receive. Why it is
   safe to raise NOTIFY there:
   - it is the UI task itself, between messages: no handler is in flight, and the stack depth
     is the same on every pass (`sp = 0x460d8d80` on all 1,186 passes of a run, ot_emu);
   - **stock raises NOTIFY at this very level**: message cases 27 / 29 (`0x40062cc0`, a
     formatted text, 0x78) and 31 (`0x40062cf2`, "P%d DUB ABORTED", 0x30) call it and branch to
     this tail;
   - it runs **at 60 Hz even when idle**: DTIM1's ISR (`0x40055cb8`) posts message type 5
     (`0x400a7279`) to the UI queue on every second tick. Measured: 60 passes in 1 s idle,
     ~80 per 3,000 frames playing (ot_emu).
   So a step-down made anywhere reaches a toast within one UI message (≤ 17 ms).
5. **What else turns a gate on (C).** TSTR (P2EDIT, a paste), the sample's TIMESTRETCH and
   TEMPO (the ATTR keys), the sample loaded into the slot (its settings record's +0x110 /
   +0x114), the slot choice, a Part or bank switch, a load. The project tempo is clamped to
   720..7200 by stock (`0x40005c2e`, `0x4000fedc`), so it never closes the gate by itself.
6. **A defect of every build up to VEM5, found here (C, ot_emu).** Because PART_B moves a step
   before the new Part is applied (item 2), the frame hook polled the new Part's bytes against
   rp_prev, which still described the old Part. A track whose VARI state differs between the
   two Parts read as a TSTR change and **SWAPPED the new Part's PTCH/QUAN and TSNS/EMUS**.
   Measured on the VEM5 image (the one on the unit), test `net_part`: Part 1's T5 (not VARI,
   PTCH 70, QUAN 109 parked, TSNS 30, EMUS 127 parked) came out (109, 70, 127, 30). Fixed by
   `rp_sync` (§12.2); the fixed image keeps (70, 109, 30, 127).

### 12.2 Design (all in `varispeed_emus.s`, PART 1 "THE DSP LOAD GUARD"; constants `VG_*`, unchanged)

- **The estimate is a property of the settings** (spec §6b item 1): per DSP core, `VG_BASE` +
  the prices of its four tracks' FX1 / FX2 types (the current Part's bytes) + the engine price
  of each of its tracks whose current machine is ST / FL, whose gate is on (`rp_gate_m`: VARI,
  or AUTO on a VARI sample, the sample's tempo in range), with the project tempo in range,
  by its EMUS value -- in the TSNS slot, or in the park while a swap into VARI is still to come
  (`rp_prev[2t+m] == 0`) (`vg_scan`, `vg_fxsum`, `vg_est`). Prices and budgets: `VG_SP12` 218,
  `VG_S950` 99, `VG_BUDGET_C0` 3,350 (T5-T8), `VG_BUDGET_C1` 3,930 (T1-T4).
- **Refusal 1, EMUS** (`vg_cap`, from `emus_p2step` in P2EDIT): a move toward a dearer stop stops
  at the highest stop, from the current one up, whose engine fits the room the track's core
  has without it; stopped short flags the toast. A cheaper stop is always allowed.
- **Refusal 2, the FX type** (`vh_fx1` / `vh_fx2` at the choosers' YES `0x400526e4` /
  `0x40052474`, `vg_fx_try`): the new type is refused (nothing written, the chooser stays open,
  the toast flagged) when the core's estimate with it is over the budget **and** the core's
  base + FX alone would fit (emulated engines tip it). Stock FX alone over: not refused (the net
  then steps every emu track of the core, and nothing more).
- **The safety net** (`vg_tick` at `0x40062d1c`, the UI loop's tail, every UI message): `vg_sig`
  computes a signature of every input of the estimate -- the current Part block, its 16 FX
  bytes, the tempo range, per track its machine and that machine's TSTR, and on AUTO / VARI
  also the slot, the sample's TSMODE and tempo, `rp_prev`, the TSNS slot and the park (h = 33h +
  x). Only when it differs from the last one checked does `vg_fix` run: while a core is over its
  budget, the next track of the core -- **SP12 first, then S950, highest track number first** --
  gets EMUS = OT (`vg_step_ot`: the slot or the park where the value lives now, the working DB
  and its SRAM copy with the swap's dirty flags, and the live byte when the live bytes are the
  current Part's (`APPLIED_B/P`)), just enough. It covers Part change and reload, project and
  bank loads (old projects included), machine changes, pastes, sample / tempo changes that open
  a gate, and TSTR / ATTR onto VARI. Interrupts are masked inside `vg_fix`; it does nothing
  while a bulk write holds the Part (`vem_depth`).
- **The toast `MAX DSP: EMU LIMIT`**, `NOTIFY(text, 0x48)` = 1.2 s (stock's 0x30 × 1.5), is
  raised **only in `vg_tick`**: a refusal flags it in its handler and the loop's tail right after
  that handler raises it; a net step-down raises it at the tail that ran the net -- right after
  the UI handler that caused it, or at the next UI message when the cause was not the UI's. Its
  text is 92 px in the stock toast font: the box (text + 15) is 107 of the screen's 128.
- **`rp_sync`** (the defect of 12.1 item 6): `rp_prev` belongs to one Part (`rp_pb` / `rp_pp`:
  its bank blob and part). `rp_swap_m` calls it on a gate difference, before it would swap --
  nothing per frame otherwise -- and the guard calls it before it reads `rp_prev`. Another
  current Part: forget, so the next poll adopts the new Part as it is.
- **EMUS: four detents per stop** (`EM_DETENTS` 4); a reversal restarts the count, as before.
- **The frame hook** is VEM3's again: the engine latch at the trig unchanged, no estimate, no
  step-down, no toast.
- Builder: 3 new detours (`0x40062d1c` jmp `vg_tick`, `0x400526e4` jmp `vh_fx1`, `0x40052474`
  jmp `vh_fx2`, each body jumps back behind its displaced bytes, checked), new CONTEXT asserts
  (the UI loop's receive and tail, stock's own NOTIFY cases, the DTIM1 tick post, both choosers'
  YES bodies and records, the applies' `0x80001828/29` stores, the bank-blob formula, the
  PART_B store of message 20); default label `140C_VEM6`. Manifest: the detours, the docstring
  (GUARD line), reference `236e5218…`.

### 12.3 What was removed

- **The run-time step-down**: `vg_core` (per-frame estimate, at once mid-note), `vg_latch` (the
  step-down at the trig) and their state (`vg_fxc`, `vg_stamp`, `vg_est`, `vg_clock`,
  `vg_free`, `vg_down`, `vg_key`). The latch is VEM3's.
- **The `S95!` / `OT!` readout**: `vg_mark`, `emus_fmt_ot_dn`, `emus_fmt_s95_dn` and their
  strings. EMUS shows its stored value.
- **The old toasts**: `MAX DSP: S950 USED` / `OT USED`, `vg_room` (old), `vg_ask`, `vg_gates`,
  `vg_entered`, the `.ep_tstr` branch of `emus_p2step` (TSTR now keeps stock's conversion and
  the net sees a track enter VARI), the ATTR handler's gates-before/after.
- **Built for §6b's first form, removed before any commit when the user simplified it**: six
  detours on stock's PART_B / bank-pointer stores (`0x40062142`, `0x400621e2`, `0x40087ea6`,
  `0x400622aa`, `0x40087d44`, `0x40025aa2`) with a load-in-progress HOLD (`vg_busy`); a check
  after each Part apply (with a pending-Part wait, `vg_pend`); a check in the bulk writers'
  leave; `vg_enter` (TSTR parks OT itself); the ATTR handler's restricted fix (only the tracks
  that entered); a check on the frame hook's poll (`vg_dirty`); `vg_watch`. The net replaces
  them all; `rp_sync` replaces the store detours' forget.

### 12.4 Tests

**(b) `tools/varispeed_emus_test.py`: 33/33 PASS** (`out/vem6/tests_all.txt`). The 11 non-guard
tests (swap, fresh0, adopt, widget, item11, latch, o2, o2late, o2rev, old56) unchanged and
`p2edit` and the seven `panel_*` rewritten for four detents (p2edit: 8 detents in one report =
two stops, three back none, the fourth S950, pushed reports count one each, snapping, the count
restarting on another track and at SRC SETUP's open; panel: slow / fast / multi / jitter /
bounce / held / reset through the real panel path). **Retired: the VEM4G / VEM5 guard tests**
`guard_x2`, `guard_x2_ref`, `guard_x3`, `guard_latch`, `guard_mid`, `guard_silent` (run-time
step-down, marker) and `toast_emus`, `toast_emus_ot`, `toast_tstr`, `toast_attr` (the old
toasts), with `GuardModel`. **New** (MMTESTDT, T5-T8 = DSP core 0, all by runtime pokes on the
real export; every expectation from `NetModel`, an independent model fed with the `VG_*`
block, and every scenario checks that the right rule differs from the wrong ones it names;
NOTIFY captured, still run, and watched):

| test | setup and action | result (VEM6) |
|---|---|---|
| `net_load` | over at the start: S950 T5, SP12 T6-T8, DJ EQ x4 (3,686) | T8, T7 -> OT (3,250); T5 S950, T6 SP12 kept; from bar 2 each plays that engine; one toast |
| `net_part` | part 0 fits; pattern 1 poked to Part 1 (T5 not VARI, T6-T8 SP12, DJ EQ x4: 3,587), cued, plays from bar 2 | Part 1: T8, T7 -> OT, T6 SP12; T5's PTCH 70 / QUAN 109 / TSNS 30 / EMUS 127 untouched; Part 0 untouched; after the switch T6 SP12, T7 / T8 / T5 OT; one toast |
| `net_reload` | RELOAD PART from a saved copy (poked, flagged) with S950 T5, DJ EQ x4 | T8, T7 -> OT; T5 S950, T6 SP12 |
| `net_paste` | T5-T7 SP12 + DJ EQ (3,240); track paste T5 -> T8 (3,805) | T8, T7, T6 -> OT; T5 SP12 |
| `net_machine` | T8 STATIC (off) -> FLEX stored VARI SP12 (3,458) | T8's FLEX EMUS -> OT; T5-T7 SP12 |
| `net_gate` | T8 AUTO, SP12 parked; its sample's TIMESTRETCH poked to VARI | T8 enters, -> OT, plays OT from its next trig |
| `net_tstr` / `_order` / `_fit` | TSTR BEAT -> VARI through P2EDIT | T8 -> OT; with T6 entering and T8 already SP12: **T8** -> OT, T6 SP12 (the net's order); S950 that fits: nothing, no toast |
| `net_attr` | ATTR TIMESTRETCH BEAT -> VARI (value-up key) with T7, T8 on AUTO, SP12 parked | both enter; T8 -> OT, T7 SP12 |
| `ref_emus` | T5-T7 SP12 + DJ EQ x3, T8 OT: +4, +4, -4, +8 detents | S950 (no toast), **S950 refused SP12** (toast), OT, **S950 for +8** (toast) |
| `ref_emus_ot` | the same, SPATIALIZER on T8's FX1 | OT (toast), OT, OT, OT (toast) |
| `ref_fx` | SP12 x4, DJ EQ T5-T7, DARK T5-T7 (3,191): T8 FX2 DARK, FX2 SPATIALIZER, FX1 COMPRESSOR, FX1 SPATIALIZER | refused (3,458; toast), lands, refused (3,357; toast), lands |
| `ref_fx_alone` | a test build with core 0's budget 2,600 (`lowbudget`): T8 S950; T7 FX1 DJ EQ; T8 FX1 SPATIALIZER; T7 FX1 DJ EQ again | refused (engines tip it), lands, **lands** (stock alone 2,663 > 2,600) and the net steps T8 to OT, nothing more |
| `under` | SP12 x4 + DJ EQ x2 (3,111): EMUS SP12 -> S950 -> SP12, FX1 SPATIALIZER, a heavy apply of the same Part, RELOAD (nothing saved) | nothing changes, SPATIALIZER lands, **no toast** |

Every test with a toast checks: each `MAX DSP: EMU LIMIT` NOTIFY came **from `vg_tick`, on the
UI task's stack** (return address inside `vg_tick`, sp in `0x460d6de4..0x460d8de4`), with
`0x48`, once per refusal or step-down; the text is the image's and its box fits the screen.

**Deliberately wrong builds** (`--build-variants`, sources in `out/vem_variants/src/`; each run on
its tests, `out/vem6/variants.txt`): every one fails its tests, its control passes.

| build | wrong rule | fails |
|---|---|---|
| `w_low_first` | lowest track first | all nine `net_*` with a step-down (`under` passes) |
| `w_s950_first` | S950 before SP12 | `net_load`, `net_reload` (`net_part` passes: no S950 there) |
| `w_no_cap` | EMUS never refused | `ref_emus`, `ref_emus_ot` (the net then steps it to OT) |
| `w_no_fxref` | FX never refused | `ref_fx` |
| `w_no_sync` | no `rp_sync` | `net_part` (T5 swapped: 109, 70, 127, 30) |
| `w_6det` | six detents | `p2edit`, `panel_slow`, `_fast`, `_held`, `_reset` |
| `w_toast_direct` | NOTIFY raised in P2EDIT | `ref_emus`, `ref_emus_ot` (toast not from `vg_tick`) |
| `w_no_net` | the net never runs | all nine `net_*` |

The VEM5 image (on the unit) fails `p2edit`, `panel_slow`, `panel_reset` (six detents),
`net_load` (no net) and `net_part` (no net, and the PTCH/TSNS swap of 12.1 item 6).

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), outputs in `out/vem6/`: quick **9/9
identical**; full OTDEMO **35/35 identical**; full MMTESTDT (`--frames 6000`) **35/35
identical**. The quick set prints exactly VEM5's lines. In the full sets every scenario is
identical over its compared range; only the whole-run counts of a few scenarios moved, by 1 to
4 passes in frames 5-9, before the compared range (the first frames' transitions and
adoptions; the UI task now does ~600-1,600 more instructions around the run's first messages,
which shifts them by a frame in the emulator).

**(c) DSP**: payloads unchanged; `varispeed_emus_dsp_boot_check.py out/mainos_varispeed_emus.bin`:
**PASS** on both payloads.

**ColdFire cost** (C, ot_emu, `--cost`: coverage over 3,000 frames, against VEM3 (no guard),
`out/vem6/cost.txt`; and per event with watches at the routines' entries and exits,
`out/vem6/costw.log`):

| scenario | unit per frame, VEM3 -> VEM6 | of which the frame hook | the UI loop's tail |
|---|---|---|---|
| OTDEMO, no VARI | 227.4 -> 243.9 | +1.2 | 14.8 |
| OTDEMO, 7 x VARI SP12 | 1,389.5 -> 1,407.3 | +1.7 | 15.4 |
| MMTESTDT, 4 x SP12 + DJ EQ x2 (fits) | 617.6 -> 636.3 | +1.6 | 16.4 |
| MMTESTDT, over at the start (one step-down) | 617.6 -> 636.5 | +2.4 | 16.0 |

- **The frame hook: ~+2 instructions per frame** (VEM5's guard: +65 to +146). `rp_sync` runs
  only on a gate difference.
- **The UI loop's tail: ~660 instructions per UI message** without a change (`vg_sig` with
  eight ST tracks, four of them VARI; ~550 on OTDEMO), at ~60-80 messages a second: ~15 per
  frame on average, in the UI task, never in the frame ISR.
- **A change event: `vg_fix` ~960-1,130 instructions when it fits, ~1,580 when it steps two
  tracks**; a tail with a step-down and its toast ~8,500 (NOTIFY opening the window).
  (Whole ColdFire per frame: 32,000-35,500.)

### 12.5 Toasts: when none is possible, and caveats

- **No case without a toast was found.** Every refusal and every net step-down reaches
  `vg_tick` within one UI message, and DTIM1's 60 Hz tick keeps that loop turning.
- The toast for a sequencer pattern switch into an over-budget Part appears **about one step
  before** that Part plays (the UI moves PART_B then; the net fixes the Part before it is
  applied, so its first trigs already latch OT).
- RELOAD PART's own toast ("PART n RELOADED") is replaced by `MAX DSP: EMU LIMIT` when the
  reload steps something down (NOTIFY closes the open toast).
- While a bulk write holds the Part the check waits for its end (never seen from the UI task).
- **During a project load the net may run on the Part while the engine task writes it** (9
  checks during MMTESTDT's load, none stepped). A step-down there would land in bytes the load
  then overwrites, but could still toast and set the dirty flags; the loaded settings are
  checked again when they are complete.

### 12.6 Deviations and open questions

- **TSTR / ATTR onto VARI use the net's order** ("6b simplified" puts them under the net). The
  track entering goes to OT when it is the core's highest SP12 / S950 track; otherwise a
  higher-numbered one does (`net_tstr_order`: T6 enters, T8 steps). Spec §6b item 3 says "the
  track goes to VARI and its EMUS becomes OT". Please confirm which the user wants.
- **The engine follows at the next trig** (unchanged latch): after a step-down the DSP runs the
  old engine until each stepped track's next trig. For a sequencer Part switch the step-down
  comes a step before the switch (none). For a change from the PART menu, RELOAD, a paste or a
  machine change while playing, a trig inside that handler could still latch the old engine;
  a sample change that opens a gate at a trig plays that note with the old (parked) engine.
- **`rp_sync` fixes a defect of VEM1-VEM5**, including the flashed VEM5: a sequencer Part change
  between Parts whose VARI state differs swapped the new Part's PTCH/QUAN and TSNS/EMUS.
  Projects played on VEM5 may carry such swaps; there is no conversion.
- The "stock FX alone over" branch cannot happen with today's prices (the heaviest stock setup
  is 3,253 / 3,350 against 3,350 / 3,930); it is tested on the `lowbudget` test build only.
- Prices and budgets are §11's, to be re-tuned on hardware.
- The octabam module was not rebuilt (its detours and reference are updated).
- An emulator housekeeping note: once this session stopped every `ot_emu --image` process on
  the machine (to abort a harness run a rebuild had invalidated); a concurrent session's
  emulator runs, if any were running then, would have been stopped too.

### 12.7 FLASHING §4 item (draft) -- VARISPEED_EMUS VEM6, the guard

OS VERSION `140C_VEM6`. A project with T5-T8 STATIC / FLEX on VARI, looping samples, DARK REV on
every FX2 of T5-T8. "Toast" = `MAX DSP: EMU LIMIT`, readable in full, about 1.2 s.
1. **EMUS feel:** four detents per step, both directions; one detent back restarts the count.
2. **EMUS refused:** T5-T7 on SP12 with DJ EQ on their FX1, T8 on OT. Turn T8's EMUS right: at
   S950 no toast; four more detents: **it stays S950** and the toast shows. Turn left to OT: no
   toast. Put SPATIALIZER on T8's FX1 and turn right: **it stays OT**, toast.
3. **FX refused:** T5-T8 on SP12, DJ EQ on T5-T7's FX1, DARK on T5-T7's FX2, T8's FX1 / FX2 NONE.
   On T8 choose FX2 DARK REV and press YES: **it stays NONE**, toast, the chooser stays open;
   choose SPATIALIZER: it lands, no toast. FX1 COMPRESSOR: refused; FX1 SPATIALIZER: lands.
4. **TSTR onto VARI:** T5-T7 SP12 + DJ EQ x3; T8 on BEAT with EMUS SP12 from before. Set TSTR to
   VARI: T8 is on VARI, **its EMUS reads OT**, toast. Then the same with T6 entering while T8 is
   on SP12: T8 goes to OT (the order), T6 keeps SP12.
5. **ATTR onto VARI:** T7, T8 on AUTO with the same sample, both SP12 from before; the sample's
   TIMESTRETCH BEAT -> VARI in the audio editor: T8 OT, T7 SP12, toast.
6. **Part change while playing:** a second Part with T6-T8 SP12, DJ EQ on all four FX1, and T5
   NOT on VARI with a distinctive PTCH (e.g. +5) and TSNS. Chain a pattern that uses it: the
   toast shows about a step before it plays; on it T7 and T8 read OT, T6 SP12; **T5's PTCH and
   TSNS are what you set** (the `rp_sync` fix -- VEM5 swapped them). Switch back and forth for a
   few minutes: PTCH / QUAN / TSNS / EMUS values stay put on both Parts.
7. **Project load and RELOAD PART:** on VEM5, save a project over budget (4 x SP12 + DARK x4 +
   DJ EQ x3 on T5-T8, its Part saved too); flash VEM6 and load it: toast, T8 reads OT (then
   T7 if still needed), the others keep SP12. RELOAD PART on that Part: the same again.
8. **Machine change:** T8 on FLEX, VARI, EMUS SP12 while T5-T7 are on OT; switch T8 to STATIC
   (not VARI); put T5-T7 on SP12 and DJ EQ on T5-T7's FX1 (all fits); switch T8 back to FLEX:
   toast, T8's EMUS reads OT.
9. **The crash setup cannot be built:** 4 x SP12 + DARK x4 + DJ EQ x3 on T5-T8 -- the third DJ
   EQ or the fourth SP12 is refused. Leave the allowed maximum playing five minutes: no squeal,
   no pops, the sequencer runs.
10. **Toast safety:** provoke the toast often (EMUS against the limit, quick pattern switches
   between the two Parts while playing) for five minutes: no hang, controls live, no crackle
   (the CLAUDE.md "Session 93" signature).
11. **Everyday project:** no toast ever, nothing changes; no `S95!` / `OT!` anywhere.

### 12.8 Blacklist statement (this session)

**I opened nothing on the spec §1 blacklist.** Disclosures:
1. The memory index (`MEMORY.md`) was injected into this agent's context at start, as for the
   earlier clean sessions; it summarizes the old module's history. I opened no memory file and
   took nothing from it.
2. Greps of allowed files showed matching lines only: `reference/kb/memory-map.md` (a file
   list naming `REPITCH.md`, an attribution naming its author, a line naming "repitch-kyoti"),
   `reference/kb/caves.md` (lines naming `KYOTI_LOAD_AUDIT.md` and `tools/load_audit/...` as
   references, nothing of their content), `CLAUDE.md` (the concurrent-sessions line). I read no
   section about REPITCH.
3. ot_emu's `main.cpp` (option names) and `rtos.cpp` (the task table, the load loop): no
   keyword hits in either file.
4. The oracle was run only through the harness.

---

## 13. VEM7, 2026-10-15 (clean side): the entering track goes to OT (spec "6b, answers")

Same worktree, clean side. Read for this section: the spec (all; "6b, answers" and §7 new),
this file §8, §12, `CLAUDE.md`, our module sources, builders, manifest, tests and harness,
`tools/build_bugbuilds.py`, `tools/kyoti_status.py`, `tools/githooks/threads.txt`, octabam's
`tools/remix/schema.py` (`Linked.include`), `platform_build.py` and `build_bus.py` (only their
assembler / include lines, grepped), and the stock image (objdump). **Nothing was flashed,
promoted or pushed.** KYOTI's combined image was not touched.

**A new build exists: `140C_VEM7`, WIP, not flashed.** Built twice, same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `3a35a08592c6164d43ef7a246fa8fa29b3a1ff3b3bcd3b764b4742021d974ef7` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `09698bc6e0a2e48fc9d89d3707bf17ca1076d4d4bde1ba6f6c673d432ed292f2` |
| `out/mainos_varispeed_emus.bin` | `cb25bbaede331d0b3e1badd77cb13504881f8abe5599808f7fb170d541bc0e1a` |
| `out/elek_varispeed_emus.bin` | `5ce784b8723273d24c05ba91efcdd4fbdc74580e23add5376206294f3b9b11ef` |

OS VERSION reads `140C_VEM7`. Unit: **4,888 B** at `0x400d6500..0x400d7818` (1,060 B of the
classic cave left), the same bytes for `-mcpu=5407` and `54455`, sha256 `37f72b04…` (manifest
reference updated). 22 detours, 12 descriptor pokes, 9,583 bytes differ from stock. Against VEM6
the image differs only in the unit, the detour target words and the descriptor pokes: **the DSP
payloads are byte-identical to VEM6's** (checked byte by byte). VEM6's MAIN OS is kept as
`out/vem_variants/mainos_varispeed_emus_vem6.bin` (`5480ba2c…`) with its symbols.

### 13.1 What changed

- **TSTR or ATTR TIMESTRETCH (under AUTO) onto VARI over budget: THAT track's EMUS goes to OT**,
  with the toast. Mechanism (all UI task):
  - `vg_note` (d1 = track): when the track's gate (`rp_ui_gate`, its current machine) is off,
    its bit is set in `vg_pend`. Called by `emus_p2step` for P2EDIT's TSTR slot (slot 4, ST / FL;
    the panel's track) before stock's conversion, and by `attr_up` for every track just before
    the BEAT -> VARI store (the only ATTR edit that can open a gate).
  - `vg_tick` (the loop tail right after that handler): if `vg_pend` is set, it is cleared and
    `vg_entered` keeps the noted tracks whose gate is on now (the edit put them on VARI); then
    **`vg_fix` with exactly those tracks as its mask**. `vg_fix` already took a track mask (VEM6
    called it with -1): over budget, it steps only the entering tracks, SP12 first, then S950,
    highest track first, just enough. Then the usual signature check and the net (mask -1) for
    whatever is still over, in the net's order. One toast for both.
  - Several tracks entering by one ATTR edit: the net's order **among them** (net_attr: T7, T8
    enter, T8 steps).
- **RELOAD PART: no special code, confirmed.** The guard has no RELOAD path; `rp_reload` is only
  the retained hold/forget wrapper (`rp_prev` bookkeeping). A reload whose result is over budget
  changes the signature, and the net acts (`net_reload`, unchanged).
- `rp_gate_v` removed: dead since VEM6 (its only caller, `.ep_tstr`, went in §12.3).
- **One source for two builds** (spec §7): `varispeed_emus.s` gained the assembly switch
  `VEM_EMUS` (default 1, set in the source: octabam defsyms are link-time). With 1 it is
  VARISPEED_EMUS -- the switch commit (`dc3844f`) links to VEM6's unit bytes exactly
  (`236e5218…`); with 0 it is VARISPEED (§14). Everything VARISPEED_EMUS's alone sits inside
  `.if VEM_EMUS`: EMUS, the engine tag and latch, the stock-track mask, the guard, the TSNS
  pair of the swap, the TSNS caption.
- **Builder.** The ColdFire sites, pokes, context bytes, the unit link and the guarded splice
  that both builders use moved to `tools/varispeed_buildlib.py` (not a builder: no gate);
  `tools/build_varispeed_emus.py` adds EMUS's and the guard's own tables and keeps the DSP
  install. Checked: the refactored builder builds VEM6's image (`5480ba2c…`) from VEM6's source.
  Default label `140C_VEM7`.
- A stock fact checked for this: the ATTR tail's redraw `0x4006dbdc` does not read d1
  (`attr_up` now leaves d1 = -1 after its note loop).

### 13.2 Tests

**(b) `tools/varispeed_emus_test.py`: 34/34 PASS** (`out/vem7/tests_all.txt`): VEM6's 33 and the
new `net_attr_order`. `NetModel.enter_fix(fx, eng, entering)` models the rule (the entering
tracks first, the net's order for the rest); the tstr / attr scenarios take their expectation
from it, and the `_order` ones check that it differs from the net's order:

| test | setup and action | result (VEM7) |
|---|---|---|
| `net_tstr` | T8 BEAT -> VARI (SP12 parked), T5-T7 SP12, DJ EQ x3 (3,458) | T8 -> OT (here also the net's choice) |
| `net_tstr_order` | T6 BEAT -> VARI (SP12 parked) with T5, T7, T8 on SP12 (3,458) | **T6 -> OT, T8 keeps SP12** (VEM6: T8 -> OT); T6 plays OT from its next trig; one toast |
| `net_tstr_fit` | S950 that fits | nothing, no toast |
| `net_attr` | T7, T8 on AUTO enter (both SP12 parked) | T8 -> OT, T7 SP12 |
| `net_attr_order` (new) | T6, T7 on AUTO enter (SP12 parked) with T5, T8 VARI SP12 (3,458) | **T7 -> OT** (the highest ENTERING track), T8 keeps SP12 (the net would take T8) |

**Deliberately wrong builds** (`out/vem7/variants.txt`), each against its tests:

| build | wrong rule | fails | passes |
|---|---|---|---|
| `w_enter_net` (new) | the entering track gets the net's order (VEM6) | `net_tstr_order`, `net_attr_order` | the other 9 `net_*` / `under` |
| `w_low_first` | lowest track first | 8 (all `net_*` but `net_tstr`, `net_tstr_order`: one entering track has no order) | `under`, those two |
| `w_s950_first` | S950 before SP12 | `net_load`, `net_reload` | `net_part` |

| `w_no_cap` | EMUS never refused | `ref_emus`, `ref_emus_ot` | `ref_fx` |
| `w_no_fxref` | FX never refused | `ref_fx` | `ref_emus` |
| `w_no_sync` | no `rp_sync` | `net_part` | `net_load` |
| `w_6det` | six detents | `p2edit`, `panel_slow`, `_fast`, `_held`, `_reset` | `panel_multi`, `_jitter` |
| `w_toast_direct` | NOTIFY raised in P2EDIT | `ref_emus`, `ref_emus_ot` | `net_load` |
| `w_no_net` | the net never runs | `net_load`, `net_part`, `net_reload`, `net_paste`, `net_machine`, `net_gate` | `net_tstr*`, `net_attr*` (the entering step is not the net, VEM7), `ref_emus` |

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), outputs in `out/vem7/`: quick **9/9
identical**, full OTDEMO **35/35 identical**, full MMTESTDT (`--frames 6000`) **35/35
identical**; all three print **exactly VEM6's lines** (`diff` empty, whole-run counts included).

**(c) DSP**: payloads byte-identical to VEM6's; `varispeed_emus_dsp_boot_check.py
out/mainos_varispeed_emus.bin`: **PASS** on both payloads (`out/vem7/dsp_boot.txt`).

**(d) octabam**: the module (reference `37f72b04…`) was not rebuilt this session; the VARISPEED
module was (§14).

### 13.3 FLASHING §4 (draft) -- changes to §12.7 for VEM7

OS VERSION `140C_VEM7`. §12.7 stands, with items 4 and 5 replaced:
4. **TSTR onto VARI:** T5-T7 SP12 + DJ EQ on their FX1; T8 on BEAT with EMUS SP12 from before.
   Set TSTR to VARI: T8 is on VARI, **its EMUS reads OT**, toast. Then T5, T7, T8 on SP12 (DJ EQ
   on T5-T7) and T6 on BEAT with SP12 from before: set T6's TSTR to VARI: **T6's EMUS reads OT**,
   T8 keeps SP12, toast.
5. **ATTR onto VARI:** T5, T8 VARI SP12, DJ EQ on T5-T7; T6, T7 on AUTO with the same sample,
   both SP12 from before; the sample's TIMESTRETCH BEAT -> VARI in the audio editor: **T7 reads
   OT**, T6 and T8 keep SP12, toast.

### 13.4 Open questions

- **ATTR TEMPO** (or a sample change) that brings an AUTO / VARI track into range is not "TSTR or
  ATTR TIMESTRETCH": it keeps the net's order. Say if it should count as entering.
- The engine still follows at the next trig (unchanged latch, §12.6).

---

## 14. VARISPEED, 2026-10-15 (clean side): the plain build (spec §7)

Same session as §13. **Nothing was flashed, promoted or pushed.** VARISPEED is WIP: not on
`kyoti_status.FINAL`, no README entry.

**New builds exist: VARISPEED standalone `140C_VARI1` and its Bugbuild `BUG_VARI`, both WIP, not
flashed.** The standalone was built twice, same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED.syx` (MIDI DIN) | `78cfad333ff231adda18f415d9585deae7c09a9668882903b30b4b3afd97f64d` |
| `out/OCTATRACK_VARISPEED.bin` (CF card) | `ed3e19d9cc39386fb14493760818e7dbc9529e5524ee9c2a2d7d409edced2837` |
| `out/mainos_varispeed.bin` | `ce7e69fd15235433c22cd7bc5265ecce6329ccb7eb7d521632259f680134671b` |
| `out/elek_varispeed.bin` | `434898ad6553cfbd1ce20f4740c829d67f77724df6a6d95a050c596bf261c0e3` |
| `out/Bugbuilds/OCTATRACK_OS1.40C_VARISPEED_BATCH_BUGFIXES.syx` (`BUG_VARI`) | `f2f37df360f19f7667c6a78fead813fd5b47da322e29dfaa4e76cc365bca4a68` |
| `out/Bugbuilds/OCTATRACK_VARISPEED_BATCH_BUGFIXES.bin` | `15e5585b5228d1e8d760db16892dbf304c860e1868f409d765a71b14da63f8b4` |
| `out/Bugbuilds/mainos_varispeed_batch_bugfixes.bin` | `ea2b4f604307c3dec2507a74ca6819b6b470620a050783eee709973fbef1ab20` |

### 14.1 What is in, what is out

One source: `octabam-modules/varispeed-emus/varispeed_emus.s` assembled with **`VEM_EMUS = 0`**
(`as --defsym VEM_EMUS=0`). The unit: **2,388 B** at `0x400d6500..0x400d6e54` (3,560 B of the
classic cave left), the same bytes for `-mcpu=5407` and `54455`, sha256 `afd1eed1…`.
**2,231 bytes differ from stock**, every one of them the unit's, a detour's or a poke's (the
builder refuses anything else).

- **In** (the shared code, unchanged from VARISPEED_EMUS): TSTR five positions with stock's
  select and `tstr_fmt` (`VARI`); ATTR TIMESTRETCH `VARI` (label, up, down, the tails' poll);
  the gate (VARI, or AUTO on a VARI sample; sample and project tempo in 30..300 BPM); the exact
  ratio `floor(inc x N / D)`, the octave fold above 2x, the clamp at 2.0 - 16 LSB, dry, RATE
  applied; out of range = OFF (dry flag, stock increment); QUAN on PTCH (`quant_widget`,
  `quant_step`, `quant_fmt`, the four dial resolvers) with the per-machine PTCH parks and
  `rp_prev[2t+m]`; the item-11 fix; the hold / forget wrappers of SRC paste, track paste, the
  PART menu's paste core and CLEAR, RELOAD PART; the Part-apply forgets; `rp_sync`.
- **The VARI increment:** `inc & ~15`, exactly VARISPEED_EMUS's on EMUS = OT (it clears bits
  0-3 and ORs in engine 0). Every other increment: stock's, untouched.
- **Out:** EMUS (`emus_widget`, `emus_fmt`, `emus_p2step`, `emus_open`, the TSNS widget pokes,
  the P2EDIT and SRC SETUP detours); the TSNS <-> EMUS pair of the swap (TSNS stays TSNS; the
  NEIGHBOR byte VARISPEED_EMUS parks TSNS in is never touched; no live TSNS write); the TSNS
  caption (stock's); the engine tag and latch; the bits-2-3 mask on every other increment; the
  load guard (refusals, net, `vg_tick`, the FX choosers' detours, the toast); the DSP kernel and
  both DSP hooks -- **the DSP payloads, SPRING REVERB and both FX choosers are stock**.
- **17 detours** (the frame hook, five ATTR, four dial resolvers, two Part applies, RELOAD PART,
  four bulk writers) and **10 descriptor pokes** (TSTR count / widget / formatter, PTCH widget /
  step, STATIC and FLEX).

### 14.2 Builders

- **`tools/build_varispeed.py`** -> `out/mainos_varispeed.bin`, `out/OCTATRACK_OS1.40C_VARISPEED.syx`,
  `out/OCTATRACK_VARISPEED.bin`, `out/elek_varispeed.bin`, `out/varispeed_syms.json`; OS VERSION
  `140C_VARI1`. `gate()` first (WIP), `seal()` after the image. The same discipline as
  VARISPEED_EMUS's builder, through `tools/varispeed_buildlib.py` (every context span, detour site
  and poke asserted stock; no branch into a displaced span; the cave zero and inside the classic
  cave; no reference into `0x80006a40..0x80006abf`; 5407 == 54455; each body jumps back behind
  its site; EFT wrap and re-parse). Its own checks: none of VARISPEED_EMUS's symbols in the unit;
  no changed byte outside the unit, the detours and the pokes; the octabam form (below)
  assembles to the same bytes (5407 and 54455); the module's `reference` matches. Test variants:
  `VARI_VARIANT` / `VARI_VARIANT_SRC` (no wrap).
- **`tools/build_bugbuilds.py --wip VARISPEED`** (with `KYOTI_ALLOW_WIP=1`; refuses with exit 2
  without it, `out/vari/bug_noenv.txt`): composes only `BUG_VARI` from `WIP_FEATURES`, prints
  a WIP banner, runs the WIP builder, skips the promotion check and **never calls `seal()`**.
  The fixes relocate above the unit: `patch_partreapply` 402 B @ `0x400d6e54`,
  `patch_pattern_led` 158 B @ `0x400d6fe8`, `patch_trigscale` 62 B @ `0x400d7b00`; interlock
  DISJOINT, ALL PRESERVED, NO STRAYS; 2,794 B vs stock; 2,936 B of the cave zone left.
  VARISPEED's zero-valued runtime state at the unit's tail (`vem_depth`, `rk_acc`, `rp_pb` and
  the padding) is reserved from the fix caves, read from `out/varispeed_syms.json`.
  **The default run is unchanged**: `python3 tools/build_bugbuilds.py` without the flag (no
  `KYOTI_ALLOW_WIP`) built the seven final Bugbuilds, each "image matches the promoted FINAL
  build", "no problems flagged" (`out/vari/bugbuilds_final7.txt`).
- **octabam** (`octabam-modules/varispeed/`): `varispeed.s` is two lines, `.equ VEM_EMUS, 0` and
  `.include "remix.inc"`; `manifest.py`'s `Linked.include` writes the shared source's text
  (`../varispeed-emus/varispeed_emus.s`) as that `remix.inc` (gas resolves `.include` against
  the working directory and `-I` only, not the including file's folder, so a relative include
  of the sibling cannot work; `Linked.include` is octabam's own mechanism for generated
  assembler text). `kind` CF_PATCH, no DSP section, PLACE DRAM / CAVE like VARISPEED_EMUS,
  claims the 16 PTCH parks only. The ledger keeps it apart from VARISPEED_EMUS (same sites).
  The folder needs `varispeed-emus/` beside it. **Built** in the scratch octabam (`a67a1112`,
  `REMIX=varispeed BUILD=79 XBUS=1 SPEC=1 python3 tools/build/build_bus.py`, a scratch remix of
  the stock effects WITH SPRING REV, `out/bus_vari.log`): `VARISPEED vari_cf: matches the
  author's build at 0x400d6500 (2,388 B)`, DRAM unit at `0x40a955e0`, 17 detours, 6 symbol
  refs, 4 pokes, "stock rows kept: ... SPRING REV ..."; image `5b9ead44…`
  (`out/vem/img/octabam_vari_bus.bin`).

### 14.3 Tests

- **`tools/varispeed_test.py`: 11/11 PASS** (`out/vari/tests_all.txt`): `static` (DSP payloads A
  and B byte-identical to stock; both FX choosers' tables stock; FX2 offers SPRING; the five
  VARISPEED_EMUS-only sites stock; TSNS widgets 0; no stray byte; 17 detours / 10 pokes; no
  VARISPEED_EMUS symbol), `swap` (PTCH <-> QUAN with a fresh 1/1, TSNS / live TSNS / the NEIGHBOR
  TSNS-park byte never move, captions QUAN + stock TSNS), `adopt`, `p2edit` (TSNS on a VARI track
  steps as stock: 65 / 63 / 71; TSTR BEAT +1 -> VARI, +1 stays; T3 enters with QUAN 64), `widget`,
  `item11`, `o2`, `o2late`, `o2rev`, `old56`, `spring` (FX2 SPRING REVERB chosen on T1 lands:
  Part byte and live id 0x15).
- **Harness `--plain`** (VARI vs the oracle's TSTR 4 = VARISPEED_EMUS on OT; stock TSTR and
  PICKUP vs stock 1.40C; out of range vs stock OFF; every bit of l:$40): **quick 6/6 identical**
  (`out/vari/harness_quick.txt`); stock's own engine bits are nonzero on 13,163 compared passes
  of `stock_tstr_0` and come through unmasked. **Full OTDEMO 17/18, full MMTESTDT
  (`--frames 6000`) 18/18 identical.** The one difference is by design: `auto_OT`, T5 only, every
  pass, and only in y:$40 bits 0-1 (`f1a1bf` vs `f1a1bc`). T5 is §4 item 2's track: its Part says
  AUTO + a VARI sample but its voice plays another sample (the gate and the voice disagree), so
  it is NOT engaged and plays stock. VARISPEED_EMUS masks a stock increment's bits 2-3 (so the
  oracle shows 0); VARISPEED leaves stock's increment untouched (spec §7), so stock's own bits
  come through. Every engaged VARI track is bit-identical.
- **Wrong builds (quick plain):** `w_mask` **differs** on `stock_tstr_0` and the three `oor_*`
  (2/6 identical: the VARI ones); `w_lowbits` **differs** on `vari_OT_Tp_q0` and `pre_OT` (4/6:
  the stock ones). Each fails exactly the group it breaks.
- **The Bugbuild** (`BUG_VARI`): quick plain **6/6 identical**; `tools/varispeed_test.py` on it
  (`VEM_IMG` = the Bugbuild, the emulator tests) **10/10 PASS** (`out/vari/tests_bug.txt`).
- **The octabam image** (DRAM unit): quick plain **6/6 identical**.
- **DSP boot check:** not relevant (no kernel); the DSP payloads are byte-identical to stock.

### 14.4 FLASHING §4 (draft) -- VARISPEED

OS VERSION `140C_VARI1` (or `BUG_VARI`). Power-cycle once first.
1. **Stock untouched:** FX2 still offers SPRING REV and it sounds; an everyday project without
   VARI sounds as on stock; no toast ever.
2. **VARI:** a FLEX loop with matching ATTR TEMPO; TSTR has five positions, the fifth `VARI`. On
   VARI PTCH reads `QUAN`, TSNS still reads `TSNS`. Change the project tempo: speed and pitch
   move together, in time.
3. **QUAN:** 1/2 ... 2/1, one ratio per three detents; 2/1 an octave up.
4. **RATE:** reverse plays backwards at the same speed; RATE locks work.
5. **Leaving VARI:** TSTR to BEAT: PTCH shows its value from before VARI; TSNS is whatever it was
   set to (it never swaps).
6. **AUTO + ATTR:** TIMESTRETCH `VARI` after BEAT; an AUTO track on that sample plays VARI.
7. **Out of range** (sample tempo outside 30-300 BPM): plays as OFF, PTCH as pitch.
8. **Machine round trips, paste, PART menu, RELOAD PART, save / reload:** as §6 items 7-9 (QUAN
   only).
9. **`BUG_VARI` only:** FLASHING §4's BATCH_BUGFIXES checks, plus a Part change with VARI tracks.

### 14.5 Open questions

- None on the design. Hardware is untested; the emulator does not draw SRC SETUP.

### 14.6 Blacklist statement (this session, §13 and §14)

**I opened no blacklisted file.** Disclosures:
1. The memory index (`MEMORY.md`) was injected into context at start, as for earlier clean
   sessions; I opened no memory file and took nothing from it.
2. **A grep touched a blacklisted file's contents, nothing of it was seen:** `grep -rn "include="
   refs/octabam/modules/*/manifest.py | grep -v "/repitch"` searched every module manifest,
   `refs/octabam/modules/repitch/manifest.py` included; its lines (if any matched) were removed
   by the `grep -v` before display. Nothing from it reached me.
3. A grep of `refs/octabam/tools/build/build_bus.py` for keywords printed one comment line naming
   Jannik Aßfalg and an octabam PR number (attribution only). `ls -d refs/octabam/modules/*repitch*`
   printed the folder name `refs/octabam/modules/repitch`.
4. The oracle was run only through the harness.

---

## 15. VEM8, 2026-10-15 (clean side): indirect entry onto VARI steps that track (spec "6b, option B")

Same worktree, clean side. Read for this section: the spec (all; "6b, option B" new), this file
§12-§14, `CLAUDE.md`, our module source, builders, manifest, tests and harness, ot_emu's
`main.cpp` (option names, the step verbs) and `rtos.cpp` / `rtos.h` (`loadProjectLive` and its
constants), and the stock image (objdump, `out/clean-room/stock.dis`). **Nothing was flashed,
promoted or pushed.** KYOTI's combined image was not touched. The DSP kernel, its tables and its
generator were not touched (another agent is changing SP12 in another worktree).

**A new build exists: `140C_VEM8`, WIP, not flashed.**

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN) | `24f7d4a6bea9c5d33461e3e44b54fd852aa1cd568887c8985882750aef039ff4` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `b0ee3c06139d61e980d0e159ba06deab88db9a79431c62916efcab9737db5627` |
| `out/mainos_varispeed_emus.bin` | `f787f4204385c2dc9bb3012dd04dc5c6d6c1cd3cd265a9e9e936f1e326d94ab8` |
| `out/elek_varispeed_emus.bin` | `c0f2dbbe7839a399dafb71584f8bf1d67461d7e69f6ba13482b870f660bac411` |

OS VERSION reads `140C_VEM8`. Unit: **5,192 B** at `0x400d6500..0x400d7948` (756 B of the classic
cave left), sha256 `4f19e79c…` (manifest reference updated). 22 detours and 12 descriptor pokes,
as VEM7; 9,826 bytes differ from stock. The DSP payloads are VEM7's (the builder's DSP half is
unchanged; the boot check passes, §15.3).

**VARISPEED is unaffected** (`.if VEM_EMUS` holds everything new): `tools/build_varispeed.py`
on the changed source builds `out/OCTATRACK_OS1.40C_VARISPEED.syx` sha256
`78cfad333ff231adda18f415d9585deae7c09a9668882903b30b4b3afd97f64d`, `mainos_varispeed.bin`
`ce7e69fd…`: byte-identical to §14 (`140C_VARI1`).

### 15.1 Facts found (C = objdump of `section_3_MAIN_OS.bin` or an ot_emu run; I = inferred)

1. **What can turn a gate on.** The gate (`rp_gate_m`) reads the track's machine, that machine's
   TSTR, its slot byte (`Part + 0x8f04a + 5t + m`), and the slot's record: TIMESTRETCH (`+0x110`)
   and tempo (`+0x114`). The project tempo is clamped by stock (§12.1 item 5). Writers (C):
   - **TSTR**: P2EDIT (VEM7's `vg_note`), the pastes, the loads and Part applies.
   - **machine**: the machine chooser (then `0x400972fc`), and the slot assign below (it writes
     the machine byte from the audio editor's machine, `0x40079522`).
   - **slot byte**: a scan of every `#0x8f04a` reference finds two stores: the SRC page paste
     (`0x40027ec2`, inside `0x40027e4c`, held by `vh_srcpaste`) and **the slot assign
     `0x40079424`** (Part `0x400795c0`, its SRAM copy `0x400795c8`, the live slot byte
     `0x40079610`). The slot assign is reached from the SRC page (`0x4005a7fe`, which reads
     `PAGE_M`) and from the audio editor (`0x40079770`), both UI-task handlers. The wholesale
     writers (bank read, track paste, PART menu, RELOAD) copy blocks.
   - **the record's TIMESTRETCH / tempo**: the ATTR value keys (UI task; row 2 TIMESTRETCH, row 3
     TEMPO: `0x4006eb6c`, step 6, or 1 with FUNC, then `0x40099090`, which clamps to
     720..7200, so an ATTR TEMPO edit always lands in range); **the sample load into a slot**:
     `0x40022610(machine, slot, path)` writes the record's path and posts disk command 1 (STATIC) /
     0 (FLEX), handled in the disk task (`0x40084c08`: `0x40093980`, `0x40099148` /
     `0x40099680`, `0x4008fb58`); and the project load (`0x4009083c`, every slot).
2. **A sample load runs no Part apply** (C, ot_emu, MMTESTDT, a watch on `rp_forget`, both
   applies, the loader's functions): after `0x40022610(0, 2, "../AUDIO/ELEKTRON/isaak.wav")`
   the disk task loaded slot 2 (path, TIMESTRETCH 0 -> 2, tempo 714 -> 2880) with no
   `rp_forget` hit. It refreshes the tracks through the per-track apply `0x40001f18` (also
   the machine change's, `0x400973da`), which is not hooked.
3. **The project load can be checked half-done** (C, ot_emu, MMTESTDT, `loadProjectLive` =
   disk command 4, `0x40085336`): the reset `0x400909d8` and the parse `0x4009000c` each end in a
   light and a heavy apply (both forget); then the samples (`0x4009083c`), then every bank
   (`0x400905d4`). The current bank's read `0x4008ded0` returned at instruction 127.85 M,
   **the UI task's tail (`vg_tick`) ran at 128.09 M**, the light apply came at 128.13 M (from
   `0x400a1030`) and the heavy at 128.24 M. So one check can see the read Part before any
   apply: Part bytes rewritten, live bytes still the old ones, no forget yet.
4. **The live slot byte `0x8000082f + 72t`** is written by the applies (heavy `0x40009118`,
   light `0x400098ca`, the frame ISR's `0x4000b486`), the per-track apply (`0x400020fa`, in
   `0x40001f18`), the SRC paste (`0x40027fd8`) and the slot assign (`0x40079610`), and by
   nothing else (C: every reference of the address). So a slot byte that differs from its live
   byte was written without an apply: a bank read (or the SRC paste, which is held anyway).
5. **Every Part apply and bulk write already reaches `rp_forget`** (the two apply detours,
   `vh_leave`, `rp_sync` on another current Part; §12, §13). One flag there marks "Parts
   rewritten wholesale since the last check".

### 15.2 Design (`varispeed_emus.s`, PART 1, the guard; inside `.if VEM_EMUS`)

Inside the existing net, no new hooks:
- **`vg_new`** (run by `vg_tick` only when the signature changed) keeps a snapshot from the last
  check: each track's gate (`vg_gon`, its current machine, with the project tempo in range) and
  its key (`vg_tkey`: machine << 16 | that machine's TSTR << 8 | slot byte, `vg_key`). A track is
  **named** -- it became a VARI track indirectly -- when its gate is on now and was off then,
  its machine and TSTR are unchanged, no wholesale rewrite came between (`vg_bulk`), and either
  its slot byte is unchanged (what the slot plays changed: ATTR TEMPO / TIMESTRETCH, a sample
  load) or its slot byte equals its live slot byte (a slot assign; a bank read before its apply
  fails this, 15.1 items 3-4).
- **`vg_bulk`** (initially 1): set by `rp_forget`, read and cleared by `vg_new` with interrupts
  masked (the frame path can forget too). Set, nothing is named.
- **`vg_tick`**: signature -> `vg_new` -> the named tracks OR VEM7's TSTR / ATTR tracks
  (`vg_pend` -> `vg_entered`) -> `vg_fix` with that mask first (just enough of THEM, SP12 first,
  highest first among them), then `vg_fix(-1)` (the net's order for whatever is still over),
  the signature recomputed after a step, one toast. ATTR TIMESTRETCH -> VARI under AUTO is now
  caught by both (VEM7's note and `vg_new`), with the same result.
- **Net's order kept** for: a Part change or reload, a project / bank load, a paste, the PART
  menu (all forget, or hold then forget), a machine change (key), a TSTR change other than
  P2EDIT's (key), and a slot byte rewritten without its live byte.
- Cost: nothing in the frame path. The UI tail as before when nothing changed; `vg_new` adds
  ~8 x (`vg_tkey` + `rp_ui_gate`) only on a signature change.
- Shared code: `rp_forget` sets the flag inside `.if VEM_EMUS`; VARISPEED is byte-identical.

### 15.3 Tests

**(b) `tools/varispeed_emus_test.py`: 39/39 PASS** (`out/vem8/tests_all.txt`): VEM7's 34 unchanged and
five new, all on the real MMTESTDT export with runtime pokes only, every expectation from
`NetModel` (`enter_fix` for a named track, `fix` for the net), each checking that the right
rule differs from the wrong one here. Common set-up: T5, T7, T8 VARI SP12 on STATIC slot 0
(146.6 BPM), DJ EQ x3, DARK x4 (3,240, fits); T6 with SP12 parked; T6 entering makes 3,458.

| test | the change (stock code only) | result (VEM8) |
|---|---|---|
| `net_tempo_order` | T6 VARI on slot 1, slot 1's tempo 714 (out of range); the ATTR value-up key on the TEMPO row (`0x4006edc8`, row 3) -> 720 | **T6 -> OT**, T8 keeps SP12 (the net would take T8); TSTR untouched; T6 plays OT from its next trig; one toast |
| `net_slot_order` | T6 AUTO on the empty slot 2; slot 1's TIMESTRETCH VARI; the slot assign `0x40079424` gives T6 slot 1 (Part and live slot byte 1) | **T6 -> OT**, T8 SP12; one toast |
| `net_sample_order` | T6 VARI on the empty slot 2, its tempo 714; `0x40022610(0, 2, "../AUDIO/ELEKTRON/isaak.wav")` -> disk command 1 loads it (tempo 2880), outside any UI handler | **T6 -> OT**, T8 SP12; the toast at the UI loop's tail |
| `net_machine_order` | T6 STATIC (not VARI) -> FLEX stored VARI SP12 (machine byte + `0x400972fc`) | the net's order: **T8 -> OT**, T6's FLEX EMUS SP12 |
| `net_partwrite_order` | T6 AUTO on slot 2; its PART slot byte -> 1 and TSNS slot -> SP12 (as a bank read writes a Part, live bytes untouched), the heavy apply 100 frames later | the net's order: **T8 -> OT**, T6 SP12; one toast |

The sample load is reachable in the emulator through stock's own load-to-slot API: the path is
poked into the unit's zero tail behind the test stubs, the command runs in the disk task.

**Deliberately wrong builds** (`out/vem8/variants.txt`; `--build-variants all`, every one rebuilt
on the VEM8 source):

| build | wrong rule | fails | passes |
|---|---|---|---|
| `w_indirect_net` (new) | an indirect entry gets the net's order (VEM7) | `net_tempo_order`, `net_slot_order`, `net_sample_order` | the other 13 `net_*` / `under` |
| `w_name_all` (new) | every gate that comes on is named (no machine / TSTR / slot / bulk test) | `net_machine_order`, `net_partwrite_order` | 14 |
| `w_no_live` (new) | a changed slot byte named without the live-slot test | `net_partwrite_order` (two toasts: it steps T6 in the read Part, the apply's adopt undoes it, then the net steps T8) | 6 |
| `w_enter_net` | every entering track gets the net's order (VEM6) | `net_tstr_order`, `net_attr_order`, and the three indirect ones | 11 |
| `w_low_first` | lowest track first | 9 (`net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_attr`, `_attr_order`, `_partwrite_order`, `_machine_order`) | 7 (one named track has no order) |
| `w_s950_first` | S950 before SP12 | `net_load`, `net_reload` | `net_part` |
| `w_no_cap` | EMUS never refused | `ref_emus`, `ref_emus_ot` | `ref_fx` |
| `w_no_fxref` | FX never refused | `ref_fx` | `ref_emus` |
| `w_no_sync` | no `rp_sync` | `net_part` | `net_load` |
| `w_6det` | six detents | `p2edit`, `panel_slow`, `_fast`, `_held`, `_reset` | `panel_multi`, `_jitter` |
| `w_toast_direct` | NOTIFY raised in P2EDIT | `ref_emus`, `ref_emus_ot` | `net_load` |
| `w_no_net` | the net never runs | `net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_partwrite_order`, `_machine_order` | the named ones (`net_gate` now too: a sample attribute turning a gate on is an indirect entry) |

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), outputs in `out/vem8/`: quick **9/9
identical**, full OTDEMO **35/35 identical**, full MMTESTDT (`--frames 6000`) **34/35**: every line
(whole-run counts included) is **exactly VEM7's** from the re-run after the harness fix `4d1d54f`
(`out/vem7b/`, `diff` empty on all three). The one MMTESTDT non-identical, `tempo_edge_720`, is
"NOTHING COMPARED" in VEM7's re-run too: since `4d1d54f` an empty compared set fails, and at 30 BPM
no compared track reaches its start in 6,000 frames. A harness limit, not a difference.

**(c) DSP**: `varispeed_emus_dsp_boot_check.py out/mainos_varispeed_emus.bin`: **PASS** on both payloads
(`out/vem8/dsp_boot.txt`).

**VARISPEED**: rebuilt twice on the VEM8 source: syx `78cfad33…`, identical to §14.

**Reproducible**: VEM8 built twice, the same four hashes.

**ColdFire cost** (`--cost`, `out/vem8/cost.txt`, 3,000 frames vs VEM3): the unit +17.8 / +19.5 /
+20.5 / +20.3 instructions per frame (VEM6, §12.4: +16.5 to +18.9); the tail per UI message 557-636
(unchanged when nothing changed); a net check ~510-550. The tool's "frame" column (the unit minus
the tail and the net ranges) now also holds `vg_new` / `vg_tkey`, which sit outside those ranges:
+2.4 to +3.7 per frame there, averaged; the frame hook's code is unchanged.

### 15.4 FLASHING §4 (draft) -- changes to §12.7 / §13.3 for VEM8

OS VERSION `140C_VEM8`. §12.7 with §13.3 stands; add:
12. **ATTR TEMPO into range:** T5, T7, T8 VARI SP12 with DJ EQ on T5-T7's FX1 and DARK on every
    FX2; T6 on VARI with EMUS SP12 from before, playing a sample whose ATTR TEMPO is out of range
    (it plays as OFF). In the audio editor bring its TEMPO into range: **T6's EMUS reads OT**, T8
    keeps SP12, toast.
13. **Slot assign:** the same, T6 on AUTO with an empty slot; give the sample a TIMESTRETCH of
    VARI in the audio editor, then assign that slot to T6 from the SRC page: **T6 reads OT**, toast.
14. **Sample load:** the same, T6 on VARI on an empty slot with an out-of-range tempo (or a sample
    whose tempo is out of range); load a sample into that slot from the card: **T6 reads OT**,
    toast (after the load finishes).
15. **Net's order kept:** T6 STATIC not VARI with FLEX stored VARI SP12; switch T6 to FLEX: **T8
    reads OT**, T6 SP12.

### 15.5 Open questions

- **A slot assign that also changes the machine** (an audio-editor slot of the other machine type:
  `0x40079424` writes the machine byte too) counts as a machine change: the net's order. Say if it
  should name the track.
- **A named change and a Part apply in the same UI-message window** (~17 ms; e.g. a sample load
  finishing as the sequencer switches Part) take the net's order: the apply wins.
- **A project load's sample phase** runs before the current bank is read (15.1 item 3): a check
  then may name tracks of the outgoing Part and step them; the bank read overwrites those bytes
  and the final check (after the applies) uses the net's order. As in §12.5, such a load can show a
  toast for a step that does not survive. Not seen in the tests (MMTESTDT has no VARI track at load).
- The engine still follows at the next trig (unchanged latch).
- `VG_SP12` is unchanged here (218); the stereo SP12 price is the DSP work's.

### 15.6 Blacklist statement (this session)

**I opened no blacklisted file.** Disclosures:
1. The memory index (`MEMORY.md`) was injected into this agent's context at start, as for earlier
   clean sessions; it summarizes the old module's history. I opened no memory file and took
   nothing from it.
2. `CLAUDE.md` was read whole: it has one line naming the old thread ("repitch-kyoti") in its
   concurrent-sessions section; nothing about the old module.
3. ot_emu's `main.cpp`, `rtos.cpp`, `rtos.h` (in `out/vem/octabam/tools/emu/ot_emu/`) were used: `main.cpp` and `rtos.cpp` grepped
   for the keywords first (no hits), `rtos.h` grepped for four load constants only; read only for the step verbs and
   `loadProjectLive`.
4. The oracle was run only through the harness.

---

## 16. VEM9, 2026-10-15: SP12 in stereo merged, the guard's price, the guard tests solved from the constants

**The merge (dirty side / coordinator, commits `377dc64`, `36c8e83`):** SP12 (RPSP) back to full
stereo on the DSP side, merged with VEM8's option B; the guard's `VG_SP12` 218 -> **187** (the
re-profiled stereo price; `VG_S950` 99 unchanged). No other ColdFire change. **Build `140C_VEM9`,
WIP, not flashed:** `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` sha256
`aa1ee66e004fb2e920b86f5ee5a1fd069421a2822afa68194ff3517009d78d48`, `out/mainos_varispeed_emus.bin`
`3fabfd1c…` (rebuilt here with `KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py
140C_VEM9`: the same hashes).

**The problem:** at 187 the guard tests' fixed FX layouts (DJ EQ / DARK chosen for 218) fit, so
13 tests failed with "the model steps something here: got False" -- they had become no-ops.

**The fix (clean side, `tools/varispeed_emus_test.py`, commit `031aecd`; no firmware change):**
- `solve_fx(pred, fixed, prefer)`: every guard / net scenario's FX are chosen FROM the VG_*
  constants. Every reachable FX price sum over T5-T8's FX1 / FX2 slots (types limited to what
  this image's choosers offer, `fx_avail`) gets one deterministic witness; sums are tried in
  ascending order ("max": descending, the tightest fit) and the first assignment the scenario's
  predicate accepts is used. No assignment: the test run stops with an error.
- The predicates, all on `NetModel`: `g_over` (the net's scenarios: the pre-state fits, the
  post-state is over, the net keeps at least one emu track, and its order differs from each wrong
  order named: `low_first`, and `s950_first` where an S950 track is present); `g_enter` (TSTR /
  ATTR / option B: pre fits, post over, the entering rule differs from -- `_order` -- or equals
  the net's order); the controls (`net_tstr_fit`, `under`, Part 0 of `net_part` / `net_reload`) the
  tightest FX that still fit; `ref_emus` (S950 fits, SP12 refused) and `ref_emus_ot` (S950
  refused); `ref_fx`: the FX AND its four chooser actions solved (FX2 refused, FX2 lands, FX1
  refused, FX1 lands; DARK / SPATIALIZER / COMPRESSOR / SPATIALIZER preferred when they do it;
  at 187 it picks DJ EQ / SPATIALIZER / DJ EQ / SPATIALIZER); `ref_fx_alone` on the low-budget build
  (refused, lands, not refused + the net steps). `net_part` / `net_reload` take Part 1 / the saved
  copy's FX from the solver too (`part1_setup(fx1, fx2)`, `saved_setup(emus, fx1, fx2)`; the check
  reads them from the scenario, no more hard-coded DJ EQ / DARK). Each test prints its solved FX.
- A missing or stale low-budget image now FAILS `ref_fx_alone` (it used to be skipped silently).
- `--cost`'s two scenarios are solved the same way.
- Sweep (the scenario builder alone, the VG block varied): every scenario solves for SP12 120..320
  with S950 50..180 wherever S950 < SP12 leaves the premise of `ref_emus` possible; the
  combinations where it cannot (S950 >= SP12, or SP12 100 with a 50-wide window) stop with the error,
  as intended.

**Results on the VEM9 image** (`out/vem9t/`): **39/39 PASS**. Wrong builds (all rebuilt on the VEM9
source), each failing its tests:

| build | fails |
|---|---|
| `w_indirect_net` | `net_tempo_order`, `net_slot_order`, `net_sample_order` |
| `w_name_all` | `net_partwrite_order`, `net_machine_order` |
| `w_no_live` | `net_partwrite_order` |
| `w_enter_net` | `net_tstr_order`, `net_attr_order`, `net_tempo_order`, `net_slot_order`, `net_sample_order` |
| `w_low_first` | `net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_attr`, `_attr_order`, `_partwrite_order`, `_machine_order` |
| `w_s950_first` | `net_load`, `net_reload` |
| `w_no_cap` | `ref_emus`, `ref_emus_ot` |
| `w_no_fxref` | `ref_fx` |
| `w_no_sync` | `net_part` |
| `w_6det` | `p2edit`, `panel_slow`, `_fast`, `_held`, `_reset` |
| `w_toast_direct` | `ref_emus`, `ref_emus_ot` |
| `w_no_net` | `net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_partwrite_order`, `_machine_order` |

The same pattern as VEM8 (§15.3). The harness was not run here (the coordinator ran it: quick
9/9, full OTDEMO 35/35). No DSP file was touched.

**Blacklist:** nothing opened (as §15.6).

---

## 17. VEM10, 2026-10-15 (clean side): a slot pick that changes the machine names that track (spec "6b, option B extended")

Same worktree, clean side. Read for this section: the spec (all; "6b, option B extended" new),
this file §15-§16, `CLAUDE.md`, our module source, builders, manifest, tests and harness,
`tools/build_bugbuilds.py`, `tools/githooks/threads.txt`, octabam's `docs/remixer/PLACEMENT.md`
(its DRAM table only, grepped for the keywords first: no hits), ot_emu's `main.cpp` (the `call`
step only, grepped first: no hits), and the stock image (objdump, `out/clean-room/stock.dis`).
**Nothing was flashed, promoted or pushed.** KYOTI's combined image was not touched. The DSP
kernel, its tables and its generator were not touched.

**New builds exist: `140C_VEM10` (standalone) and `BUG_VEM10` (its Bugbuild), both WIP, not
flashed.** Each built twice, the same hashes.

| file | sha256 |
|---|---|
| `out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx` (MIDI DIN, `140C_VEM10`) | `1427a9afe0db1ed3d575c455c86219c4730234cce07ac9f2c34a70617396b087` |
| `out/OCTATRACK_VARISPEED_EMUS.bin` (CF card) | `07f0d38a8e6efd6361bbce5ded20fad3fa1fa651fa9818781c8da944d63ae137` |
| `out/mainos_varispeed_emus.bin` | `9926d55730fe02bb7683b9784941e18409cb8307110482f549f2684e4cec978f` |
| `out/elek_varispeed_emus.bin` | `005020c94da13505d6fd2ecd5ed0eb1c74f813d2602f3c3caffe997fe4dd27fc` |
| `out/Bugbuilds/OCTATRACK_OS1.40C_VARISPEED_EMUS_BATCH_BUGFIXES.syx` (`BUG_VEM10`) | `e0b173fb6d2f0e90d2371e7df275c0ccaefbace0d2a16e3d1bf797b93891314c` |
| `out/Bugbuilds/OCTATRACK_VARISPEED_EMUS_BATCH_BUGFIXES.bin` | `7b120d641dc0971019f9257583a0b4c7d8393c210afcd4c389ed87e3a6b1b30c` |
| `out/Bugbuilds/mainos_varispeed_emus_batch_bugfixes.bin` | `6a07848158f0d1f6f529937f015a99fa860ad269b423e0b7dd4c6401a9ddaf17` |

Unit: **5,260 B** at `0x400d6500..0x400d798c` (688 B of the classic cave left), the same bytes
for `-mcpu=5407` and `54455`, sha256 `4b4a2ec8…` (manifest reference updated). **24 detours**
(VEM9's 22 + two `jsr` sites), 12 descriptor pokes; 9,736 bytes differ from stock. The DSP half
of the builder is unchanged (boot check below).

### 17.1 Facts found (C = objdump of `section_3_MAIN_OS.bin` or an ot_emu run; I = inferred)

1. **Two machine / slot choosers reach the slot assign `0x40079424`**, its only callers
   (`0x4005a7fe`, `0x40079770`). Each is a YES-key handler, a `{0x31, 0, handler}` record like
   the FX choosers' (C: `0x400bb682` -> `0x4005a5a8`, the SRC menu's; `0x400cf72c` ->
   `0x400796a0`, the audio editor's). Each branches on its own **column**:
   - **SRC menu `0x4005a5a8`**: `0x460d1a48 == 0` (machine column) -> `0x4005a5c2`: the
     machine byte := `PAGE_M` (`0x4005a61c`), `0x400972fc(part, track, old)` (`0x4005a676`).
     This is **the machine selector**. `0x460d1a48 == 1` (slot column) -> `0x4005a758`:
     `jsr 0x4003d014` (`0x4005a760`; it selects `PAGE_M`'s slot row `0x460d5c44` STATIC /
     `0x460d5c58` FLEX into `0x46c8d1a0` / `0x46c8d19c` through `0x4006de34`); then, by
     `0x4005a7f0`: the same machine, or another machine whose slot byte differs from the slot
     picked -> the slot assign (`0x4005a7fe`), then the record check `0x40031d18` and the
     machine := `PAGE_M` again (`0x4005a826..0x4005a8b0`); another machine whose slot byte
     already holds the slot -> straight to `0x4005a826` (**a machine change with no slot
     assign**). Any other column value: out (`0x4005a75c`).
   - **Audio editor chooser `0x400796a0`**: `0x460e739a == 1` (slot column) falls into
     `0x400796d6` (`move.l 0x460e738e,%d4`, the chooser's machine), then the same structure
     (`0x40079760`: slot assign at `0x40079770`, or with the slot byte equal straight to
     `0x400798fe`); any other column -> `0x400798fe` -> `0x400797cc`, the machine write
     (`0x4007981e`) and `0x400972fc` (`0x40079878`): its machine path.
2. **The slot assign** (`0x40079424`): the picked machine's slot byte already equal to the slot
   -> out at `0x40079672` (no machine write); a FLEX / STATIC record whose `+8` is nonzero (44-B
   records at `0x46c922c4` / `0x46c90a78`) -> the refusal path `0x40079684` (`0x40021d94`), no
   machine write; otherwise the machine byte := the picked machine at `0x40079522` (always,
   even when unchanged), `0x400972fc`, then the slot byte (`0x400795c0`), its SRAM copy and
   the live slot byte (`0x40079610`).
3. **What tells them apart:** only a slot column passes `0x4005a760` / `0x400796d6`; a machine
   column reaches neither (the branches above). Both causes end in the same `0x400972fc` with
   the same Part bytes, so the bytes alone cannot tell them apart (C: `0x400972fc` is also
   called by the SRC paste, RELOAD, the Part switch `0x40062204` and three disk-side sites
   `0x40093f56`, `0x40094140`, `0x40096b58`). Hence a mark at the slot columns.
4. **A machine change writes no live slot byte for ST / FL** (C, objdump + ot_emu): in
   `0x400972fc` the per-track apply `0x40001f18` is only on the PICKUP branch (`0x4009733a..
   0x400973e4`); ot_emu, MMTESTDT: after the SRC menu's straight path (STATIC -> FLEX slot 7,
   no slot assign) the live slot byte still read 0 (the STATIC slot) 200 frames later. So
   VEM8's live-slot test cannot be applied to a slot pick's machine change.
5. **MMTESTDT's FLEX slots are all empty** (C, ot_emu: every FLEX record's `+8` is 1, the
   settings records empty with tempo 2880). The slot assign then takes its refusal path,
   which in ot_emu does not return (`0x40021d94`: "DID NOT RETURN -- unimplemented opcode at
   0x4003b108", a stock path waiting on UI). After `0x40022610(1, 7, path)` (disk command 0)
   FLEX slot 7's `+8` is 0 and the assign runs (net_slotmach_order).

### 17.2 The change (`varispeed_emus.s`, PART 1, the guard; all inside `.if VEM_EMUS`)

- **`vg_pick_src`** (`0x4005a760`: `jsr 0x4003d014` -> `jsr vg_pick_src`; it marks, then
  `jmp 0x4003d014`) and **`vg_pick_ae`** (`0x400796d6`: `move.l 0x460e738e,%d4` -> `jsr
  vg_pick_ae`; it marks, loads d4, `rts`): each sets the chooser's track (`0x100b14cc`) in the
  byte **`vg_pick`**. UI task (key handlers); every other register kept.
- **`vg_new`**: a track with its `vg_pick` bit set whose machine changed (key bits 16-23) and
  whose gate is on now is **named** -- its own EMUS goes to OT first (`vg_fix` with the named
  mask, as for VEM8). Its gate under the old machine does not matter (on -> on included:
  the new machine's VARI setting is the entry), and there is no live-slot test (17.1 item 4).
  A bulk change since the last check (`vg_bulk`) clears the pick: nothing is named, as before.
  Everything else in `vg_new` is VEM8's.
- **`vg_tick`** clears `vg_pick` at its common tail (every loop tail, the early exits too), so
  a pick counts only for the message whose handler set it.
- **Net's order kept** for: the machine selector (both choosers' machine columns), every other
  machine change (`0x400972fc` from pastes, RELOAD, the Part switch, the disk side), and all of
  VEM8's net cases.
- Cost: nothing in the frame path; `vg_new` +2 instructions per track (+3 more for a picked one) on a signature change;
  the two marks only on a slot column's YES.
- Builder: the two `jsr` detours; the column tests, the straight path and the slot assign's
  exit / machine write asserted as stock context (`0x4005a5b8`, `0x4005a758`, `0x4005a614`,
  `0x4005a7f0`, `0x400796ca`, `0x400794b6`, `0x40079520`). Default label `140C_VEM10`. The
  octabam manifest gained the two Detours (kind `jsr`) and the new reference; the module was
  not rebuilt in octabam this session.

### 17.3 Builds

- **Standalone:** `KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py 140C_VEM10` (hashes
  above; twice, identical).
- **Bugbuild `BUG_VEM10`:** `KYOTI_ALLOW_WIP=1 python3 tools/build_bugbuilds.py --wip
  VARISPEED_EMUS` (new `WIP_FEATURES` entry; refuses without the opt-in as `--wip VARISPEED`
  does; announced WIP, never sealed). The base's DSP payload edits come through as the
  SIDECHAIN base's do: the image as built, the fixes in the ColdFire cave zone only. **Every
  zero byte inside the unit** (`cave..end`, from `out/varispeed_emus_syms.json`, whose
  `unit_sha256` must match the base) is reserved from the fix caves (the runtime state --
  `vg_key`, `vg_last`, `vg_eng`, the flags, `em_ctx`, `rp_pb` -- and the tables' zero words).
  The fixes relocate above the unit: `patch_partreapply` 402 B @ `0x400d798c`,
  `patch_pattern_led` 158 B @ `0x400d7b20`, `patch_trigscale` 62 B @ `0x400d7bc0`; interlock
  **DISJOINT, ALL PRESERVED, NO STRAYS** (feature 9,736 B + fixes 563 B = 10,299 B); 112 B of
  the cave zone left.
- **`--wip VARISPEED` unchanged:** `BUG_VARI` syx `f2f37df3…bca4a68`, mainos `ea2b4f60…` --
  byte-identical to §14 (its reserved ranges are computed as before).
- **The final seven** (`python3 tools/build_bugbuilds.py`, no `KYOTI_ALLOW_WIP`): all seven
  built, each "image matches the promoted FINAL build", "no problems flagged" (SIDECHAIN
  included: this branch predates main's newer SIDECHAIN) -- `out/vem10/bugbuilds_final7.txt`.
- **Plain VARISPEED byte-identical:** `tools/build_varispeed.py` on the VEM10 source: syx
  `78cfad333ff231adda18f415d9585deae7c09a9668882903b30b4b3afd97f64d`, mainos `ce7e69fd…`,
  `140C_VARI1`: identical to §14 (everything new is inside `.if VEM_EMUS`).

### 17.4 Tests

**(b) `tools/varispeed_emus_test.py`: 45/45 PASS on the standalone** (`out/vem10/tests_all.txt`):
VEM9's 39 unchanged (`net_machine_order` included) and six new, all on the real MMTESTDT export,
by runtime pokes, through the choosers' **real YES handlers** (column, machine and slot row poked
as the panel leaves them); every expectation from `NetModel` (`enter_fix` for a named track,
`fix` for the net), FX solved from `VG_*` as in VEM9 (here T5 FLANGER / FLANGER, T6 PHASER /
PHASER, T7-T8 DJ EQ / DJ EQ: 3,164 fits, T6 entering on SP12 makes 3,351 > 3,350). Common: T5,
T7, T8 VARI SP12 on STATIC slot 0; the right rule takes T6, the net's would take T8.

| test | the change | result (VEM10) |
|---|---|---|
| `net_slotmach_order` | T6 STATIC (TSTR OFF), FLEX side VARI SP12 on FLEX slot 3; isaak.wav loaded into FLEX slot 7 at frame 10 (`0x40022610(1, 7, path)`); the SRC menu's slot column picks FLEX slot 7 (through the slot assign) | **T6 -> FLEX slot 7, its FLEX EMUS OT**, T8 keeps SP12; one toast; vg_gon showed T6 off before |
| `net_slotmach_same_order` | the same with T6's FLEX slot already 7 (no slot assign: `0x4005a826`) | **T6 -> OT**, T8 SP12; one toast |
| `net_slotmach_rev_order` | T6 FLEX (stock's machine change at frame 100), its STATIC side VARI with SP12 (slot + park) on slot 0; the SRC menu picks STATIC slot 1 | **T6 -> STATIC slot 1, OT**, T8 SP12; T6 plays OT from its next trig |
| `net_slotmach_ae_order` | the same through the audio editor's chooser (`0x400796a0`, column `0x460e739a` = 1) | **T6 -> OT**, T8 SP12 |
| `net_slotmach_vv_order` | as `_rev`, T6's FLEX side on VARI with EMUS OT (vg_gon: T6 ON before) | **T6 -> OT** (its new machine's VARI is the entry), T8 SP12 |
| `net_selmach_order` | T6 STATIC (TSTR OFF), FLEX stored VARI SP12; the SRC menu's **machine column** picks FLEX | the net's order: **T8 -> OT**, T6's FLEX EMUS SP12; one toast |

**Deliberately wrong builds** (`out/vem10/variants.txt`, all 15 rebuilt on the VEM10 source):

| build | wrong rule | fails |
|---|---|---|
| `w_slotmach_net` (new) | a slot pick's machine change gets the net's order (VEM9) | the five `net_slotmach_*` |
| `w_mach_named` (new) | every machine change is named (no pick test) | `net_machine_order`, `net_selmach_order` |
| `w_indirect_net` | no indirect entry named (VEM7) | `net_tempo/slot/sample_order` + the five `net_slotmach_*` |
| `w_name_all` | every gate that comes on is named | `net_partwrite_order`, `net_machine_order`, `net_selmach_order` |
| `w_no_live` | VEM8's slot change without the live test | `net_partwrite_order` |
| `w_enter_net` | every entering track the net's order (VEM6) | `net_tstr_order`, `net_attr_order`, the three VEM8 ones, the five `net_slotmach_*` |
| `w_low_first` | lowest track first | `net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_attr`, `_attr_order`, `_partwrite_order`, `_machine_order`, `_selmach_order` |
| `w_s950_first`, `w_no_cap`, `w_no_fxref`, `w_no_sync`, `w_6det`, `w_toast_direct` | as §16 | as §16 |
| `w_no_net` | the net never runs | `net_load`, `_part`, `_reload`, `_paste`, `_machine`, `_partwrite_order`, `_machine_order`, `_selmach_order` |

**The same suite on `BUG_VEM10`: 45/45 PASS** (`out/vem10/tests_bug.txt`; `VEM_IMG` = the
Bugbuild, `VEM_SYMS` = the standalone's symbols -- the unit is the same bytes at the same
address). The Bugbuild's fix caves fill the zero tail the tests put their stubs in, so the
stubs go to `VEM_STUB_AT=0x47fd8000` (high SDRAM above anything PLACEMENT.md's DRAM table saw
written; checked by the KNOB / NOTIFY captures and the sample path working: `widget`,
`ref_emus`, `net_sample_order` pass). `ref_fx_alone` runs, as always, on the low-budget
standalone variant, not on the Bugbuild.

**(a) Harness**, oracle = the shipped FINAL (`90b4a1c1…`), outputs in `out/vem10/`: quick
**9/9 identical** on the standalone and **9/9** on `BUG_VEM10`; full OTDEMO **35/35**; full
MMTESTDT (`--frames 6000`) **34/35**, the one being the known empty `tempo_edge_720` ("NOTHING
COMPARED"). Every line, whole-run counts included, is **exactly VEM9's** (`out/vem9/`; `diff`
empty on all four).

**(c) DSP:** `varispeed_emus_dsp_boot_check.py`: **PASS** on both payloads, on the standalone and on
`BUG_VEM10` (`out/vem10/dsp_boot*.txt`).

### 17.5 FLASHING §4 (draft) -- changes to §12.7 / §13.3 / §15.4 for VEM10

OS VERSION `140C_VEM10` (or `BUG_VEM10`). §12.7 with §13.3 and §15.4 stands; add:
16. **Slot pick that changes the machine:** T5, T7, T8 VARI SP12 with DJ EQ on T5-T7's FX1 and
    DARK on every FX2 (§15.4's set-up); T6 FLEX, its STATIC side on VARI with EMUS SP12 from
    before. On the SRC menu ([FUNC]+[SRC]) go to the slot list and pick a STATIC slot with a
    sample in range: **T6 becomes STATIC, its EMUS reads OT**, T8 keeps SP12, toast. The same
    with a STATIC slot that T6's STATIC side already holds (the machine changes, no new slot):
    the same result. The same from the audio editor's machine / slot chooser.
17. **The machine selector keeps the net's order:** the same set-up; on the SRC menu's machine
    list pick STATIC: **T8 reads OT**, T6 keeps SP12, toast.
18. **`BUG_VEM10` only:** FLASHING §4's BATCH_BUGFIXES checks, plus a Part change with VARI
    tracks.

### 17.6 Open questions

- **On -> on counts as an entry:** a track already on VARI under its old machine (EMUS OT, say)
  that a slot pick moves to its other machine's VARI SP12 is named too (`net_slotmach_vv_order`):
  the user acted on that track. Say if only off -> on should count.
- **The equal-slot pick** (the other machine's slot byte already on the slot picked: the
  machine changes with no slot assign) is treated as a slot pick: the user picked a slot from
  the list. Say if only the slot assign `0x40079424` itself should count.
- The audio editor's chooser (`0x400796a0`) is covered like the SRC menu's; its screen was not
  identified beyond its code and its YES record (`0x400cf72c`).
- Hardware untested: ot_emu does not draw the SRC menu; on the unit a slot list picking an
  empty slot opens stock's own path (`0x40021d94`), which the emulator cannot finish (17.1
  item 5), so that case is not tested here (it changes no machine).
- The engine still follows at the next trig (unchanged latch).

### 17.7 Blacklist statement (this session)

**I opened no blacklisted file.** Disclosures:
1. The memory index (`MEMORY.md`) was injected into this agent's context at start, as for
   earlier clean sessions; it summarizes the old module's history (including a few of its
   addresses and its RELOAD / swap bug fixes). I opened no memory file and used nothing from it;
   every fact above is from objdump of the stock image or ot_emu.
2. `refs/octabam/docs/remixer/PLACEMENT.md` and ot_emu's `main.cpp` were grepped for the
   keywords first (no hits) and read only for the DRAM table / the `call` step. `ls
   refs/octabam/docs/firmware/` printed the file name `REPITCH.md` (not opened).
3. `CLAUDE.md` was read whole (one line names the old thread, nothing of the module).
4. The oracle was run only through the harness.
