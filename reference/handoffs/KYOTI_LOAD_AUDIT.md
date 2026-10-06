# KYOTI processor-load audit (2026-10-05, Session 125)

**What this is.** Every KYOTI feature, priced for DSP and ColdFire load against the user's bar
(confirmed 2026-10-05): *every configuration that is clean on stock OS 1.40C must stay clean
with the feature in the image; a feature's own new modes may add load, but not enough to break
a configuration stock allows.* This is an audit only: no feature code changed, no build
re-pinned, nothing pushed. Measurement tools: `tools/load_audit/` (section 9).

---

## 1. The answer, ranked

> **Update 2026-10-06 (3): HW-F on OBKYOTI12.**
>
> - HW-A's configuration (DJ EQ in both slots on T5–T8, 4 voices) plus **RPSP on T8: clean**.
> - Then **RPS9 or RPSP on T7 as well: crash.**
>
> Core 0's ceiling is now ≈ 3,760–3,830 modelled cycles (stock worst + SIDECHAIN ≈ 3,516, +1 RPSP
> ≈ 240, +1 RPS9 ≈ 77). The earlier 4 × RPSP estimate (≈ 3,740, crash) sits ~1 % under it: model
> error, voice work not counted. **Beside stock's heaviest effects, a core has room for one REPITCH
> voice.**
>
> **The bar** ("stock-clean configurations stay clean with the new mode selected") needs
> 4 REPITCH voices in ≲ 240–310 modelled cycles: **≈ 60–75 per voice**. That is about RPS9's
> cost today (77), against RPSP's 239.
>
> The REPITCH session's target is RPSP ≲ ~60 modelled cycles per voice, or a cap of one
> REPITCH voice per core when the core's FX are heavy, or the limit documented.


> **Update 2026-10-06 (2): HW-B, HW-C, HW-D on OBKYOTI12** (syx `754742de…`, built by the REPITCH
> session).
>
> **The image.** OBKYOTI11 + CF METER, minus ERASE_EMPTY_TRIGLESS_LOCKS. Checked here: the
> REPITCH and SIDECHAIN hooks and code are word-identical to OBKYOTI11 (A `P:13d6` / B `1196`,
> `sctap` A `1282` / B `1042`). The only differing DSP words are the run after DARK's helper:
> A `15a9..1676`, B `1369..1436`. They were unreferenced SPRING code in OBKYOTI11 and are CF METER
> in OBKYOTI12.
>
> **Results**, all clean (no crash, dropout or glitch):
> - **HW-B:** RPS9 ×4 on T5–T8, DARK ×4, DJ EQ on T6–T8, T5 FX1 NONE. The DJ-EQ-on-T5 variant
>   was not run; predicted clean.
> - **HW-C:** RPSP on T8, then T7+T8, then T6+T7+T8, with the same FX. So **3 RPSP voices fit
>   beside DARK ×4 + DJ EQ ×3 on core 0; the 4th crashes** (S120). The model's "borderline"
>   point (≈ 3,500) is clean.
> - **HW-D:** 8 STATIC voices on long samples, FX NONE, a busy UI, stock TSTR and then RPSP ×8.
>   No gross ColdFire failure, so REPITCH's frame-ISR cost goes from Medium to **Low (no meter
>   reading)**.
>
> **Still open for the bar.** Stock's worst case on core 0 is already ≈ 3,520 (clean, HW-A).
> One RPSP voice adds ≈ 240, which lands at the crashing point (≈ 3,740). Predicted: HW-A plus
> RPSP on one track fails or sits on the edge (**HW-F**, not yet run). If so, RPSP fits the
> bar on core 0 only at ≲ 55 modelled cycles per voice for 4 voices (≈ 220 cycles of headroom
> per core), or with a voice cap. That is the target for the REPITCH session.


> **Update 2026-10-06: HW-A ran clean on OBKYOTI11** (user). DJ EQ was in both slots on T5–T8
> and on T1–T4, four voices sounding, stock TSTR. So stock's worst DSP load plus SIDECHAIN's
> `sctap` fits on both cores, and **SIDECHAIN drops to Low**. Core 0's ceiling is now bracketed
> by OBKYOTI11's DJ EQ ×16 measure (≈ 3,520 modelled cycles, clean) and the user's RPSP crash
> (≈ 3,740). Predictions for HW-B/C on core 0:
>
> | test | modelled cycles | prediction |
> |---|---|---|
> | RPS9 ×4 + DARK ×4 + DJ EQ ×3 | ≈ 3,090 | clean |
> | the same + DJ EQ on T5 | ≈ 3,440 | clean |
> | RPSP ×1 with the crash FX | ≈ 3,020 | clean |
> | RPSP ×2 | ≈ 3,260 | clean |
> | RPSP ×3 | ≈ 3,500 | borderline |
> | RPSP ×4 | ≈ 3,740 | crash (known) |


| # | feature | risk | in one line |
|---|---|---|---|
| 1 | **REPITCH_REPEAT98_KYOTI**, DSP | **High** (hardware) | 4 RPSP voices on a core cost ≈ 720 instr / ≈ 955 modelled cycles per sample, ≈ 2.75 DJ EQs. That broke a stock-legal FX set on the user's unit (DARK ×4 + DJ EQ ×3 on T5–T8). |
| 2 | **REPITCH_REPEAT98_KYOTI**, ColdFire | **Low** since HW-D (was Medium; no meter reading) | Its rate path runs **inside the frame ISR for every playing voice, even with no track in a REPITCH mode**: +5.5 % frame-ISR p99 at 7 voices (+7.4 % with RPSP). Stock's hardware ISR headroom at 7 voices is only ~10–15 % of the frame. |
| 3 | **SIDECHAIN_COMPRESSOR**, DSP | **Low** since HW-A (was Medium) | `sctap` copies every track's audio twice per frame, on both cores, whenever the module is in the image: +43 instr / +56 cycles per sample per core, with no COMPRESSOR anywhere. On core 0, stock's own worst case already sits *inside* the band between a hardware-clean and a hardware-crashing configuration, so 1.6 % more may or may not tip it. One flash-free test settles it (HW-A). |
| 4 | EMPTY_PATTERN_LED_FIX | Low | [PTN] held over a bank of empty patterns: +7.3 M instr/s at task level, roughly doubling task-level ColdFire work while held. Frame ISR untouched. [BANK] held is now exactly stock (the S119 fix holds). |
| 5 | DIRECT_JUMP_KYOTI | Low | The landing tick (IPL 2) is +3.5 k instr over stock's pattern-change tick, once per jump. Adds nothing to the frame ISR. |
| 6 | MUTE_MODES | Low | +45 instr per frame in the ISR; muting or unmuting all 8 tracks in one frame shows no spike in any mode. |
| 7 | RELOAD_FROM_PROJECT | Low | Both chords with the transport running: frame ISR and tick identical to stock; card I/O stays at task level; no interrupt masking. |
| 8 | REC_TRIG_MUTE, QUANTIZE_LIVE_REC_TOGGLE, ERASE_EMPTY_TRIGLESS_LOCKS, MIDI_PLAYS_FREE_FIX, PART_CHANGE_CARRYOVER_FIX | None | Event-driven and bounded (a few instructions per recorder trig; a ≤ 32-byte row check per erased lock; a 96-byte copy per Part change). |

**Outside the load question, found on the way (section 8): KYOTI V1.0 jumps to 0xD6000000 when
the MASTER track's PLAYBACK or LFO page is drawn** (T8 MASTER on). The bytes REPITCH's glyphs
keep in the CAVE2 pad are a stock parameter page's row data. Emulator, real code path,
reproduced by loading the user's own `OT DEMO`. KYOTI V1.0 only; every standalone image,
Bugbuild and OBKYOTI image is clean.

---

## 2. Units, instruments and how far to trust them

- **DSP:** the firmware's own dispatch under `ot_emu`, stopwatch on each core's whole four-track
  loop (core 1 = payload B `P:17a..333`, tracks 1–4; core 0 = payload A `P:372..53e`, tracks
  5–8). Reported per sample, in two units:
  - **executed instructions** (octabam's meter unit);
  - **modelled cycles**: dsp56300's datasheet table (`opcodecycles.h`) summed per executed
    instruction. No memory stalls, no DO-loop overhead.

  Modelled cycles over-read FILTER: 267 cycles/sample, against CHIP.md's hardware 192. They also
  under-read nothing we can check. Neither unit is the hardware's: the hardware ceiling is
  bracketed only by the user's own crash tests (section 3).
- **ColdFire:** the per-PC instruction count (`--coverage`) plus new per-interrupt-level counters:
  - every frame-ISR invocation (IPL ≥ 5) as one episode, with its instruction count;
  - every sequencer-tick episode (IPL 2), its own instructions only.

  Hardware anchor: octabam's CF METER on Bryan T's MKII (`modules/cfmeter/README.md`). The frame
  period is 362.8 µs. Stock's frame ISR with 7 FLEX voices playing runs at mean 244–268 µs,
  **max 291–306 µs**. With 7 STATIC voices: mean 256–285 µs, **max 307–330 µs**, idle 0.00 %.
  Each voice costs ~16.5 µs. CPI is ~1.1 at baseline and ~4.4 on the voice path.
- **Fixtures:** only real exported projects, set up by runtime pokes; no file was edited.
  - **`OT DEMO`**, from the user's backup (`~/Desktop/OT Backup/KYOTI`, copied first; the
    original is untouched). It loads at A05 / Part 2: FLEX on T1–T7, T8 THRU as MASTER.
  - **`MMTESTDT`**.

  FX were set by poking the live FX ids (`0x80000ec4/ecc[t]`) and the Part bytes, TSTR by the
  Part's TSTR byte, mutes and MUTE MODE by their RAM words, and keys by the panel matrix.
- **Blind spots:**
  - The emulator renders work the chip cannot afford; it bounds cost, it doesn't prove a fit.
  - No SRAM contention is modelled.
  - Card timing isn't the hardware's.
  - OT DEMO plays at most 1–2 voices at once per core. Per-voice costs were metered per hook
    visit and scaled to 4 voices.
  - Not exercised:
    - stock timestretch actually stretching;
    - THRU/NEIGHBOR/PICKUP machines and recorders while recording;
    - MIDI floods and 300 BPM;
    - the arranger and scenes moving.

---

## 3. The DSP ceiling, bracketed by the user's hardware tests

The user's OBKYOTI11 tests, 2026-10-05: four tracks continuously sounding in RPSP, DARK REV on
every FX2, **FX1 = NONE except where DJ EQ was added** (user's answer, this session).

Measured on OBKYOTI11 with the same FX (OT DEMO, TSTR stock), plus 4 × the metered RPSP voice
(180 instr / 239 cycles). Mean per sample, four-track loop:

| core | configuration | instructions | modelled cycles | on hardware |
|---|---|---|---|---|
| 0 | RPSP ×4 + DARK ×4 + DJ EQ ×2 | ≈ 2,620 | ≈ 3,350 | clean |
| 0 | RPSP ×4 + DARK ×4 + DJ EQ ×3 | ≈ 2,950 | ≈ 3,740 | **crash** (squeal, sequencer stops) |
| 1 | RPSP ×4 + DARK ×4 + DJ EQ ×3 | ≈ 3,090 | ≈ 3,930 | clean |
| 1 | RPSP ×4 + DARK ×4 + DJ EQ ×4 | ≈ 3,420 | ≈ 4,310 | **crash** (pop, silence) |

The stock worst case, for comparison: DJ EQ (the dearest effect) in all 16 slots, measured:

| image | core 1 instr / cycles | core 0 instr / cycles |
|---|---|---|
| stock 1.40C | 3,009 / 3,592 | 2,910 / 3,454 |
| OBKYOTI11 (stock TSTR) | 3,058 / 3,656 | 2,958 / 3,516 |

What follows:
- **Fact:** core 0 fails earlier than core 1 (it also runs the frame I/O, the mixdown and the
  mailbox, outside the measured loop).
- **Inference:** on core 1, stock's worst case sits below a configuration known clean, so there
  is margin there.
- **Inference:** on core 0, stock's worst case (3,454 cycles) lies between the clean (≈3,350) and
  crashing (≈3,740) points. Counted in instructions, stock's worst case plus SIDECHAIN (2,958)
  even sits at the crashing point (2,950). So **stock itself may run within a few percent of
  core 0's ceiling**, and every fixed cost added to core 0 matters.
- Both estimated rows leave out the stock per-voice work of the 2–3 extra voices the user had
  sounding (AMP etc., not measured), which would move both bounds up by the same small amount.

---

## 4. Per-feature table

Costs are per sample per core (DSP) or per 16-sample frame (ColdFire), mean unless marked.

| feature · plane · context | worst-case cost | margin vs the full stock battery | risk | evidence | optimisation (sound/behaviour change?) | test that settles it |
|---|---|---|---|---|---|---|
| **REPITCH** · DSP · voice-kernel prologue hook (A `P:40b` / B `P:20e`), each playing pass, per track | RPSP 180 instr / 239 cyc per voice (worst frame 192 / 251); RPS9 64 / 77; RPCH ≈ 0; unused ≈ 0.5 per core. **×4 voices: 720 / 955.** First RPSP/RPS9 pass on a core: one visit of 4,050–5,192 instr (vs ~2,300–2,700), ≈ +160 instr / +200 cyc for that one frame | None at 4 voices on core 0 with heavy FX: hardware crash at DARK ×4 + DJ EQ ×3 | **High** | hardware (user) + emulator per-visit meter | see section 5: cheaper render or filter (sound), the same kernel scheduled better (no change), a per-core voice cap (behaviour), the table copy moved out of the audio pass (no change) | HW-B, HW-C, HW-E |
| **REPITCH** · ColdFire · `rate_gate` → `rp_swap` → `rp_ui_gate` + `rp_source` (+ `rate_hook`), from the playback-increment builder `0x4000406a`: **frame ISR, IPL 5** (SR 0x2504), per playing voice per pass | ~200 instr per voice per frame **with stock TSTR**. 7 FLEX voices: frame-ISR p99 29,543 → 31,154 (+5.5 %), max 35,628 → 37,485. RPSP: p99 31,742 (+7.4 %), max 38,675 (+8.6 %). OBKYOTI11 (DRAM): p99 31,195, max 37,572 | ≈ +1.6–3.0 k instr at the ISR's peak ≈ 7–12 µs at CPI 1.1 (up to ~25 µs at CPI 2), against ~33–56 µs of hardware headroom (7 STATIC, max 307–330 µs of 362.8). An 8th voice takes ~16.5 µs more | **Medium** | emulator (coverage, ISR episodes); hardware anchor from CF METER on a MKII | early-out in `rate_gate` when `rp_prev[t]` = 0 and the lane's TSTR is not AUTO/RPCH/RPS9/RPSP, which takes the unused cost to ≈ 0; poll `rp_swap`/`rp_ui_gate` from the dial draw (it already is) rather than per voice in the ISR. No change to sound | HW-D (CF METER) |
| **SIDECHAIN** · DSP · `sctap` at the dispatcher's FX1 entry, **every track, every block, both cores, always**; `moncommit` per track | fixed **10.7 instr / 14 cyc per track = 43 / 56 per core**, no COMPRESSOR needed. A COMPRESSOR instance with KEY: +29 / +38 over stock COMPRESSOR (69 / 89); KEY off: +20 / +27. A side-chained COMPRESSOR stays far cheaper than DJ EQ (306 / 347), so its own mode never creates a new worst case | core 1: margin exists. **Core 0: unknown**, since stock's worst case is already inside the clean–crash band (section 3); +56 cyc is ~1.6 % of it | **Medium** | emulator; hardware: OBKYOTI11 passed every SIDECHAIN test, none at the stock worst case | publish a track only when some COMPRESSOR's KEY names it (a per-core "keys wanted" mask): ≈ 0 when unused. Same-core keys read the shared-window copy, so one copy instead of two (halves the cost). No change to sound | **HW-A** (no flash) |
| **SIDECHAIN** · ColdFire · formatters, KEY list | 0 at steady state (coverage: identical to stock) | — | None | emulator | — | — |
| **MUTE_MODES** · ColdFire · `pre` in the frame builder `0x40004dc6` (frame ISR), `mt_trig` per trig, note-off loop on mute edges | +45 instr per frame. All-8 mute / unmute edges in OT, OTFX-T, DT-T, OTFX: frame-ISR max 33,536–34,275 vs stock 34,079 (the maxima are the pattern-event frames, not the edges). DT-T / OTFX-T make muted frames *cheaper* (dropped trigs) | ample | Low | emulator | none needed | — |
| **DIRECT_JUMP_KYOTI** · ColdFire · `[PTN]`+`[YES]` key layer; landing tick (IPL 2) | landing tick 16.4–17.1 k instr vs stock's pattern-change tick 13.1–13.6 k (+~3.5 k, once per jump). Frame ISR: identical to stock. Steady state 0.3 instr per frame | ample (IPL 2 is pre-empted by the frame ISR) | Low | emulator (3 jumps, MMTESTDT) | none needed | — |
| **RELOAD_FROM_PROJECT** · ColdFire · key chords → stock message `0x14` worker (`sys` task) → card reads → toast | `[BANK]`+`[T1]` and `[PTN]`+`[T2]` while playing: worker and FINISHED toast each ran; frame-ISR p99 / max and tick max identical to stock; no masked section. OBKYOTI11 (DRAM form): the same | ample | Low | emulator (card timing is not the hardware's) | none needed | optional: chord during a 7-voice STATIC pattern, listen for streaming dropouts |
| **EMPTY_PATTERN_LED_FIX** · ColdFire · `FUN_4009a464` detour, UI task (LED refresh) | [PTN] held over an empty bank: +14.6 M instr in 2 s (7.3 M/s, ≈ 2× task-level work) vs stock +2.0 M. [BANK] held: +0.06 M (= stock). Worst case = every pattern empty (a pattern with a trig exits at the stock test) | ok while there is idle time. Task-level only, but S119 showed task-level starvation can glitch audio on a 0 %-idle unit | Low | emulator | test the audio trig-type layer `TRAC+0x10..0x17` (trigless locks) before scanning the 2 KB lock arrays. Needs proof of equivalence: orphan locks left by the erase bug | optional: hold [PTN] in a 7-voice STATIC project |
| **REC_TRIG_MUTE** · ColdFire · step-handler gate (per recorder trig), edge glyph (redraw), CC 80 (event) | a few instructions per recorder trig; nothing per frame | — | None | static + steady-state coverage | — | — |
| **QUANTIZE_LIVE_REC_TOGGLE** · key combo + toast | event only | — | None | static | — | — |
| **ERASE_EMPTY_TRIGLESS_LOCKS** · erase store `0x40038a5c` (`sys` task) | ≤ 32-byte row check per erased locked parameter | — | None | static | — | — |
| **MIDI_PLAYS_FREE_FIX** · pattern setup | a few instructions per track (MIDI branch) | — | None | static | — | — |
| **PART_CHANGE_CARRYOVER_FIX** · "select Part" handler | 96-byte copy + ≤ 8 calls per Part change | — | None | static | — | — |
| **KYOTI V1.0** (sum) | DSP: SIDECHAIN's 43 / 56 per core always, plus REPITCH when used. ColdFire on MMTESTDT (1–2 voices): +221 instr per frame (+0.85 %): REPITCH 195, MUTE_MODES 45, DJ 0.3 | as rows 1–3 | High / Medium | emulator | as above | HW-A…E. **The MASTER-page crash, section 8** |
| **OBKYOTI11** (octabam) | same kernels. RELOAD / DJ / REPITCH-CF run from DRAM at no measurable extra cost. ColdFire +4.2 % instructions on OT DEMO, almost all REPITCH's rate path | as rows 1–3 | High / Medium | emulator + the user's tests | as above | HW-A…E |

Stock per-instance DSP prices in the same units, for scale (instr / modelled cycles, core 1):

| | | | |
|---|---|---|---|
| DJ EQ 306 / 347 | LO-FI 280 / 313 | CHORUS 267 / 312 | SPRING 271 / 306 |
| FILTER 214 / 267 | DARK 209 / 267 | PLATE 194 / 240 | PHASER 188 / 223 |
| EQ 148 / 200 | FLANGER 121 / 146 | COMB 99 / 111 | COMPRESSOR 69 / 89 |
| SPATIALIZER 64 / 77 | DELAY 0 (ColdFire) | four-track loop, all NONE: 427 / 574 (core 1), 350 / 477 (core 0) | |

---

## 5. REPITCH: what lowering it means

These are for the REPITCH session, which owns the fix; nothing here was changed.

- **The kernel, unchanged sound:**
  - its datasheet cycles per instruction are 1.33, against DJ EQ's 1.14 and SPRING's 1.13;
  - displaced `(rN+disp)` / `r7` accesses and two-word immediates in the per-sample path are
    the usual cause (CHIP.md: a one-word displaced move costs ~4 cycles where a plain one
    costs 2);
  - parallel moves and post-increment pointers could recover part of that without changing
    a bit of output, provable with the 264-case bit-exact gate.
- **The render, changes sound:** the band-limited 10-tap render (+~57 instr) and the
  channel 1/2 4-pole filter (+~50) are what took RPSP from 65 (rev 12) to 172. Fewer taps, or
  the filter at a lower order, trades fidelity for headroom.
- **A per-core voice cap, changes behaviour:** for example, at most N RPSP voices per core,
  with the rest falling back to RPS9 (77 cycles) or RPCH. HW-C finds N.
- **The table copy, unchanged sound:** moving the first-use copy (~5,400 instr in one visit)
  out of the audio pass removes the one-frame spike on a core's first RPSP/RPS9 pass. Today
  that spike can click when the core is already within ~200 cycles of its ceiling.
- **Target, inference:** stock's worst case on core 0 sits near its ceiling, so 4 RPSP voices
  fit beside heavy FX only if RPSP costs about what stock's voice kernel does. Short of that,
  "how many RPSP voices fit beside the heaviest stock FX" has to be measured (HW-C / HW-E) and
  either capped or documented.

---

## 6. Hardware test plan

Batched, in order. **Ask before any of it; none was run.**

**On the unit as it is now: OBKYOTI11 flashed, syx `fae359bb…`. No flash needed.**

- **HW-A, SIDECHAIN fixed cost against stock's worst case. The one that matters most.**
  - Setup: a new Part, T8 a normal track (MASTER off). T5–T8 STATIC or FLEX on long or looped
    samples, all four sounding all the time. TSTR = OFF on all. **FX1 = DJ EQ and FX2 = DJ EQ on
    T5, T6, T7 and T8.** Transport running at 120 BPM for 2 minutes. Then the same on T1–T4.
  - Listen for the high squeal, silence, a stopped sequencer, pops.
  - If it's clean: SIDECHAIN (and every other always-on cost) passes the stock bar on the DSP,
    and its risk drops to Low.
  - If it fails: run the same on stock OS 1.40C. If stock fails too, the configuration isn't
    stock-clean and nothing in KYOTI is to blame. If only OBKYOTI11 fails, SIDECHAIN's `sctap`
    is the cause (High), and the optimisation in row 3 is the fix.
- **HW-B, RPS9 in place of RPSP.** The user's crashing core-0 set (T5–T8 sounding, DARK ×4,
  DJ EQ on T6–T8, FX1 T5 = NONE) with TSTR = **RPS9** on all four. The model predicts clean
  (RPS9 ≈ 300 cycles for 4 voices against RPSP's 955).
- **HW-C, how many RPSP voices fit.** The same crashing set, with RPSP on only 3, then 2, then 1
  of the four tracks (the rest TSTR OFF). The first count that is clean is the per-core
  capacity beside DARK ×4 + DJ EQ ×3.
- **HW-D, quick ColdFire check without a meter.** 8 tracks of STATIC on long samples, all
  sounding, TSTR stock. Then all 8 in RPSP with FX1 = FX2 = NONE (so the DSP isn't the limit).
  Listen for stutter, timing drift and sluggish keys. Only a gross failure shows without CF
  METER.

**Needs a test image. I'll build it only if you say so, and state its path and sha256.**

- **HW-E, numbers instead of "did it break".** An octabam remix with CF METER (and CF METER
  IDLE) plus the OBKYOTI11 modules, and a control remix that is the same minus REPITCH. CF
  METER sits on T8's FX2; its `DBRN` knob burns 24 DSP cycles per step on core 0 and it prints
  the frame-ISR time.
  - Spare DSP cycles on core 0: DJ EQ on T5–T7 FX1+FX2 and T8 FX1, with RPSP on 0 / 2 / 3
    voices.
  - ColdFire frame-ISR mean and max: 7–8 voices, stock TSTR, REPITCH image vs control. That is
    REPITCH's unused ColdFire cost on an MKI.
  - The same with RPSP on.

---

## 7. What stays open

- **The hardware ceiling of core 0 relative to stock's own worst case:** HW-A. If stock 1.40C
  itself fails with 16 DJ EQs and 4 voices on core 0, the bar has to be re-read for that core.
- **REPITCH's ColdFire share of the frame ISR on an MKI:** HW-E. Today it rests on a MKII CF
  METER anchor and an assumed CPI.
- **The S114 crash** (`VEC:0B PC 0x00800000 SR 0x2500`, in the frame ISR, never reproduced).
  Nothing here ties it to load. DIRECT_JUMP_KYOTI adds no frame-ISR work at all (measured), and
  the frame ISR's largest episodes are stock's pattern-event frames. Its leading suspect stays
  the MUTE MODE `%d3` bug fixed in S117.

---

## 8. Found on the way: KYOTI V1.0 crashes on the MASTER track's PLAYBACK / LFO page

This is not a load issue; it is recorded here because the audit tripped over it.

- **Reproduction (emulator, real code):** KYOTI V1.0 (`mainos_kyoti_v1.0.bin`, FINAL
  `82dd6660…`) loading the user's `OT DEMO`: `MASTER_TRACK=1`, saved state TRACK = 8. The PC
  goes to `0xD6000000` during the load's first screen draw. Stock, OBKYOTI11 and the standalone
  REPITCH image load the same card cleanly.
- **Mechanism, read and confirmed by trap:**
  - The page getter `0x40031da4` returns record `0x400d2e8a` for page 0 (PLAYBACK) and page 2
    (LFO) of T8 when T8 is MASTER (`0x80000034` ≠ 0).
  - The renderer `0x4004e4c6..` takes per-row "active" flags from the record's last 8 bytes
    (`+0x18A`, via `0x400a6994`). For an active row it calls the widget pointer at row + 48
    (`jsr (a0)` at `0x4004e7a0`).
  - In stock those bytes are zero: no active rows, the default widget.
  - In KYOTI V1.0 that record's tail and rows hold `rpk_reload` and the glyph bitmaps (CAVE2,
    `0x400d2ee8..0x400d301c`), so the tail reads `4ef9400d2b76` (a `jmp`) and the widget
    pointer reads `0xd6000000`.
- **The same class elsewhere:** MERGE.md's midisc pads are the zero tails of these 402-byte page
  records. Its evidence was "the one stock reader found reads only `+0x5e..+0x69`", but this
  renderer reads `+0xCA..` and `+0x18A..`. Of the records whose tail KYOTI V1.0 changes:
  - **`0x400d34d2`, NEIGHBOR's PLAYBACK page.** Its tail holds PLAYSFREEFIX's `jmp 0x4009b704`
    (RELD pad). Drawn in the emulator with T1 switched to NEIGHBOR: no derail; the flag bytes
    decode harmlessly. Latent, not live.
  - **`0x400d29d4`:** no reference found.
  - **`0x400d4618`, the FX NONE page.** Its tail is still zero (the SEAM pieces end exactly
    where it begins, at `0x400d47a2`): drawn, no derail.
- **Scope:** only KYOTI V1.0. Every standalone, Bugbuild and OBKYOTI6–11 image has zeros there.
- **Not done:** no fix, no build, no hardware test. On hardware the expected symptom is an
  EXCEPTION screen when selecting T8's PLAYBACK or LFO page with T8 MASTER on. Testing it means
  flashing KYOTI V1.0 and crashing the unit on purpose.
- **The fix belongs to the KYOTI V1.0 builder (kyoti-v1 thread):** keep CAVE2 off record
  `0x400d2e8a`'s rows and tail, and add the renderer's reads to MERGE.md's evidence and to the
  builder's guard.

---

## 9. Reproduce

- **`tools/load_audit/ot_emu_load_audit.patch`:** against octabam `36a056c5` `tools/emu/ot_emu`.
  Apply only in a **scratch copy** of octabam, never the shared clone. It adds:
  - multi-stopwatch with modelled cycles (`OT_SW_EXTRA`, `OT_SW_OUT`);
  - ColdFire per-interrupt-level counts (`OT_IPL_OUT2`);
  - frame-ISR and tick episodes (`OT_ISR_OUT`, `OT_TICK_OUT`, `OT_IPL_FROM`);
  - a garbage-PC tripwire (`OT_TRIPWIRE`);
  - a PC trap with registers (`OT_TRIP_PC`).
- **`tools/load_audit/la_run.py`:** one run, FX and TSTR by runtime poke, both loops.
  `tools/load_audit/isr_stats.py` summarises episode files.
- **Cards:** `stage_card.py` on a *copy* of the project plus its samples.
  - OT DEMO: set `KYOTI`, project `OTDEMO`, every `PATH=` sample from the backup's `AUDIO/`,
    128 MB image.
  - MMTESTDT: `refs/octabam/out/mmtestdt_dsp_card.img`.
- **Images:** copies of the FINAL / flashed files.

  | image | file | sha256 |
  |---|---|---|
  | stock | `out/raw/section_3_MAIN_OS.bin` | `164f3122…` |
  | KYOTI V1.0 | `out/KYOTI/mainos_kyoti_v1.0.bin` | `82dd6660…` |
  | REPITCH | `out/mainos_repitch_repeat98_kyoti.bin` | `845aca5b…` |
  | SIDECHAIN | `out/mainos_sidechain_compressor.bin` | `dfafc90c…` |
  | MUTE_MODES | `out/mainos_mute_modes.bin` | `b5e24316…` |
  | DIRECT_JUMP_KYOTI | `out/mainos_direct_jump_kyoti.bin` | `3f26d8de…` |
  | RELOAD | `out/mainos_reload_from_project.bin` | `19a3a62c…` |
  | EMPTY_PATTERN_LED_FIX | `out/mainos_empty_pattern_led_fix.bin` | `0e50306d…` |
  | OBKYOTI11 | `out/octabam_kyoti11/mainos_bus.bin` (octabam-port worktree) | `3c2f502e…` (syx `fae359bb…`) |

- **Run lengths:** 1,500 frames (FX prices) or 6,000 frames (a full pattern at 120 BPM),
  frames 101+ counted. Example:

  ```sh
  LA_SCRATCH=<scratch> la_run.py c0crash --image obkyoti11 --frames 6000 \
      --fx1 NONEx5,DJEQx3 --fx2 NONEx4,DARKx4 --tstr 6x8 --extra 1:20e:210,0:40b:40d
  ```
