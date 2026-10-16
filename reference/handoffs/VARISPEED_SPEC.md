# VARISPEED_EMUS (the REPITCH rewrite): clean-room spec

Written 2026-10-13 for a clean-room rewrite of the ColdFire core of REPITCH_REPEAT98_KYOTI, and
revised 2026-10-14 when the user redesigned it as **VARISPEED_EMUS**. The goal is a module with no
code from Jannik Aßfalg's (repeat98) octabam `repitch` module, the base the shipped module grew
from. Jannik asked for the emulations to be separated from his Repitch altogether.
REPITCH_REPEAT98_KYOTI has been removed from every build here and from octabam (#721).

This file is **clean**: it states behaviour, our own interfaces and our own DSP facts. It names
none of his hook sites or mechanisms. Keep it that way.

## 1. The clean-room protocol

Two roles:

- **Dirty:** the session that has read Jannik's code or his firmware notes. It writes this spec,
  reviews results against behaviour, and alone keeps `VARISPEED_OVERLAP.md`.
- **Clean:** a fresh agent that does the firmware RE (scope) and the implementation, working
  from the **stock 1.40C image** and this project's general knowledge.

### Clean agents must NOT open (or grep the contents of)

- `refs/octabam/modules/repitch/`, `~/Documents/octabam/modules/repitch/` (Jannik's module)
- `refs/octabam/docs/firmware/REPITCH.md` and the same file in `~/Documents/octabam`
- in either octabam clone: `tools/verify/verify_repitch*`, `tools/harness/repitch_probe*`, and
  any paragraph of `docs/remixer/FAILURE_MODES.md` about REPITCH
- `reference/kb/octabam-index.md`, section `` ## `docs/firmware/REPITCH.md` `` (it ends at the
  next `## ` heading)
- in this repo: `octabam-modules/repitch-repeat98-kyoti/patch_repitch_kyoti.s` and
  `manifest.py` (use the redacted `VARISPEED_RETAINED.s` instead)
- `tools/repitch_probe_kyoti.cpp`, `tools/repitch_ot_emu_trace.patch`, and any other `tools/*repitch*`
  file not on the allowed list below (the old standalone builder is deleted on `main`; do not
  dig it out of git history)
- `reference/handoffs/REPITCH_*.md` **except this file and the scope file the clean agent
  writes**, especially `VARISPEED_OVERLAP.md`
- `NOTES.md` sessions and `CREDITS.md` paragraphs about repitch / RPCH / REPITCH
- `reference/handoffs/KYOTI_LOAD_AUDIT.md` (it names the old core's routines; §6 below carries
  the numbers)
- Claude's auto-memory files under `~/.claude/projects/*/memory/` (the Octatrack topic files
  and their archive record the old implementation)
- **any built image that contains REPITCH** (the standalone, the KYOTI combined images, the
  Bugbuilds, octabam remixes with either repitch module): do not disassemble them, diff them
  against stock, or trace them. In the implementation phase they may be run **only** through
  the black-box comparison in §5, which compares outputs.

Rule of thumb: before reading any file outside the allowed list, grep it for
`repitch|RPCH|REPITCH|repeat98|Jannik|Octapitch` and skip the matching sections. The DSP kernel
comments mention the old ColdFire routine names in passing; names alone are fine.

### Clean agents MAY use

- the stock image `out/raw/section_3_MAIN_OS.bin` (m68k-elf-objdump, `-m m68k:cfv4e`,
  `--adjust-vma=0x40000400`), `ghidra_project/`, `out/ghidra/*` exports, and the emulators
  (`tools/emu_rtos.py`, ot_emu) on **stock** images and on their own builds
- `reference/kb/*` (minus the section above), `START_HERE.md`, `CLAUDE.md`, `COVERAGE.md`,
  octabam's general firmware docs (PARAM_PAGES, STORAGE, …) minus repitch paragraphs, and
  octabam's toolchain and schema
- the DSP-side tools (ours, checked 2026-10-14 to carry nothing of his but file names):
  `tools/varispeed_emus_dsp.asm`, `tools/varispeed_emus_dsp_src.py`, `tools/varispeed_emus_model.py`,
  `tools/varispeed_emus_dsp_check.py`, `tools/varispeed_emus_dsp_engine_check.py`,
  `tools/varispeed_emus_dsp_engine_probe.cpp`, `tools/varispeed_emus_dsp_octabam.py`,
  `tools/varispeed_emus_dsp_octabam_check.py`, `tools/varispeed_emus_dsp_boot_check.py`,
  `tools/varispeed_emus_dsp_boot_probe.cpp`, `tools/varispeed_emus_dsp_probe.cpp`, `tools/varispeed_emus_dsp_render.cpp`,
  `tools/varispeed_emus_dsp_listen.py`, `tools/varispeed_emus_dsp_profile.py`, and `tools/dsp_xasm.py`
- `VARISPEED_DSP_INSTALL.py`: the old builder's DSP half, extracted verbatim (ours)
- the oracle `out/oracle/shipped_repitch_repeat98_kyoti_FINAL.bin` (sha256 `90b4a1c1…`), the
  shipped FINAL image: run it **only** through the §5 black-box harness, which compares outputs.
  Never disassemble it, diff it, or trace its ColdFire code
- our own code: `VARISPEED_RETAINED.s` (redacted from the shipped module),
  `octabam-modules/repitch-repeat98-kyoti/rpk_glyphs.s`, `patch_repitch_reload.s`,
  `vem_dsp.asm`, `vem_dsp_ptable.py`, and the module's `README.md`
- other features' code in this repo (DIRECT_JUMP, MUTE_MODES, …) as examples of how we hook

A firmware fact the clean agent rediscovers on its own (including a site that may turn out to
be the only workable one) is fine. Copying a fact from the blacklisted material is not.

## 2. What the feature does (VARISPEED_EMUS, revised 2026-10-14)

One build only: VARI + S950 + SP12, with the DSP kernel. There is no VARI-only variant.

1. **TSTR on STATIC and FLEX** gets five positions: `OFF AUTO NORM BEAT VARI`, raw 0..4. VARI is
   raw 4. (Clean scope §2.3: stock's unreferenced 5-position select widget fits this unmodified,
   with stock's own icons; the label comes from a new formatter, since stock's is shared with
   PICKUP.) PICKUP is untouched.
2. **Audio editor, ATTR page, TIMESTRETCH** (the sample's own setting) gains `VARISPEED` (raw 4)
   after BEAT. If the field cannot hold nine characters, use `VARI`. The value keys step
   OFF ↔ NORMAL ↔ BEAT ↔ VARISPEED, and every ATTR edit calls `rp_refresh`. Under SETUP `AUTO`,
   a sample whose TIMESTRETCH is VARISPEED plays as VARI.
3. **A VARI track**: SETUP 4, or AUTO with sample TSMODE 4. It must be STATIC or FLEX with a
   bound sample whose tempo (BPM×24) lies in 720..7200, and the project tempo must lie in the
   same range. On such a track:
   - **Speed** = (project BPM × p) / (sample BPM × q), where p/q is the QUAN ratio, computed
     **exactly in integers** (no rounding drift: N = projectBPM24·p, D = sampleBPM24·q). While
     N > 2D, D doubles (an exact octave fold). The scaled increment is clamped to 2.0 − 16
     LSB in the Q26 increment.
   - Pitch and length move together: **no grains, no time-stretch.** The track plays dry,
     forwards and in reverse, and follows tempo changes every frame.
   - **RATE still applies.** **PTCH is not applied as pitch**: its composed word selects the
     QUAN ratio (item 4).
   - **Above 2x** (N > 2D): the octave fold above stays, as in the shipped module (the user is
     leaning this way, 2026-10-14; it stays unless they say otherwise). True varispeed past 2x is a possible
     later research spike, not part of this work.
   - **Out of range** (a sample or project tempo outside 30..300 BPM): the track behaves exactly
     like TSTR **OFF**. It plays dry at normal speed, PTCH applies as pitch, PTCH shows as PTCH and
     TSNS as TSNS. It is not a VARI track.
4. **QUAN** (retained, unchanged): the PTCH page-1 slot on a VARI track. Index =
   `rk_bucket(word >> 8)` from the composed 16-bit PTCH word; ratio = `.rk_ratios[idx]`.
5. **EMUS** (new): on a VARI track, the **TSNS** slot (SRC SETUP page, beside TSTR) becomes
   **EMUS**, a three-value knob: `OT` (left), `S950` (middle), `SP12` (right) (order revised
   2026-10-14 after the first flash; it was S950 / OT / SP12). It follows **the
   same rules and mechanisms as PTCH/QUAN**:
   - its caption reads `EMUS` and its readout the value name, exactly when the VARI gate is on
     (the same gate as QUAN, `rp_ui_gate`);
   - the TSNS value and the EMUS value are kept separately: on a gate change they trade places
     with a **spare parked byte** that stock saves with the Part and never applies (QUAN parks
     PTCH in NEIGHBOR's page-1 `---` byte; EMUS needs its own such byte for TSNS);
   - **exactly three positions**, labelled `OT`, `S950`, `SP12`, nothing else ever shown. EMUS
     stores 1 / 64 / 127 (OT / S950 / SP12). The value must stay within 0..127, because stock's
     time-stretch task indexes a 128-entry table with it. Any other stored value displays as its
     bucket (0..42 OT, 43..85 S950, 86..127 SP12) and snaps to that stop on the first detent, as
     QUAN does;
   - first sight adopts without swapping; a parked byte of 0 means never written and enters EMUS
     as `OT`, stored 1 (the low stop is 1 so that 0 can mean "never written"). TSNS comes back unchanged
     on leaving VARI;
   - **six encoder detents in one direction step one position** (revised 2026-10-14: one detent
     per position was far too sensitive on the unit, "jumping around almost chaotically").
     Reversing direction restarts the count, so jitter cannot flip it. A fast or accelerated turn
     must not step faster than its physical detents (find out how stock's P2EDIT delivers deltas
     and with what acceleration, and count detents, not accelerated units);
   - PTCH↔QUAN and TSNS↔EMUS swap **together**, on the same gate transition.
   - **Engine changes take effect at the next trig.** Stock cannot lock page-2 parameters, but
     a mod can, so EMUS must be read as its composed value (base + any locks or scene values)
     wherever those would land. The DSP engine a sound plays with is latched when that sound's
     trig starts. Turning EMUS, or a lock/scene changing it, mid-note does not switch the engine
     until the next trig on that track.
6. **DSP mode tag** (our own design; the DSP kernel depends on it, unchanged). The Q26
   increment that reaches the DSP voice command carries the engine in **bits 2-3**: 0 = OT,
   1 = S950, 2 = SP12. The DSP rebuilds the increment as a net `>>2`, so bits 0-1 never arrive.
   On the DSP the mode lands in `y:$40` bits 0-1, where `vem_dsp.asm` reads it.
   - On a VARI track: clear bits 0-3, then OR in the latched engine << 2.
   - On **every other increment the firmware builds**: bits 2-3 must be 0 (clean scope §2.5
     measured a stock track whose bits 2-3 read as SP12).
7. **DSP kernel**: `vem_dsp.asm` (the hardware-proven kernel) unchanged, with its two hooks and Y
   claim as in the module README. It runs its engines only for S950/SP12. Every other voice pass
   costs its short mode check.
8. **Cost**: a track not on VARI should cost near nothing extra per frame.
9. **Coexistence**: conflicts with `repitch-repeat98-kyoti` (same TSTR words). Must coexist with
   every other KYOTI module.
10. **Old projects**: TSTR/TSMODE values 5 and 6 (saved with REPITCH_REPEAT98_KYOTI) get **no
    conversion and no special handling**. They must not crash anything; whatever stock does with
    an unknown value is acceptable.
11. **The swap must not repeat the shipped module's known bug**: after a VARI track's machine is
    switched to PICKUP or THRU and back, the shipped swap could trade PTCH and QUAN the wrong way
    round, and its dial-draw poll reached PICKUP tracks. Neither may happen, for PTCH/QUAN or for
    TSNS/EMUS. Add a test for both.

## 3. Interfaces to the retained code (`VARISPEED_RETAINED.s`)

The retained code is ours and may be changed where VARISPEED_EMUS needs it: the gate range (VARI
is raw 4 only, not 4..6), the second swapped pair, and item 11's fix.

- `rp_swap` (d1 = track, preserves all): the domain bookkeeping. It is extended to swap
  TSNS↔EMUS together with PTCH↔QUAN. The new core calls it **every frame for each track whose
  gate is on, or whose `rp_prev[t]` byte is nonzero**; a track with the gate off and
  `rp_prev[t] == 0` skips it. It is also polled at dial draws.
- `rp_prev`: 8 bytes, one per track (`0xff` forgotten, `0xfe` = RP_HOLD during RELOAD PART).
- `rp_ui_gate` (d1 → d0): the Part-DB form of the gate. The runtime gate **must agree with it**.
- `rk_bucket`, `.rk_ratios`, `quant_widget`, `quant_fmt`, `quant_step`, `qdial1..4`: QUAN.
  These are kept as they are; EMUS gets its own widget, formatter and step handler on the same
  pattern.
- `rp_refresh`: call after an ATTR TIMESTRETCH edit.
- **How the shipped module wired QUAN** (our own wiring, answering the EMUS scope's question):
  the STATIC and FLEX slot-0 widget pointers (`0x400d3116`, `0x400d32a8`) → `quant_widget`; the
  STATIC and FLEX slot-0 encoder-step pointers (`0x400d3146`, `0x400d32d8`) → `quant_step`; and
  `jmp` detours at the four `qdialN` sites named in the retained code (`0x40036698`,
  `0x4003690c`, `0x4003786a`, `0x40037c06`).
- `rp_forget` / `rp_apply1` / `rp_apply2` / `rp_reload` (`patch_repitch_reload.s`): Part
  applies and RELOAD PART, unchanged.
- `rpk_glyphs.s` is no longer needed: the 5-position widget uses stock's icons.

## 4. Decided (the user, 2026-10-14)

From the EMUS scope's open questions (`VARISPEED_SCOPE_EMUS.md`):
- **O1:** per-machine parks, gate and `rp_prev` (STATIC and FLEX each have their own), so a
  machine change never swaps. FLEX's PTCH park moving is fine: old projects get no conversion.
- **O2:** fix the paste/clear/undo class now: hold/forget wrappers on SRC page paste, track
  paste and the PART menu, built like `rp_reload`.
- **O3:** the ATTR label is `VARI` (`VARISPEED` measured 2-3 px past the 34-px box).
- **O4:** EMUS as in §2 item 5: three positions only.
- **O5:** ATTR TSMODE 5/6 shows `ERROR`, as stock.
- **O6:** no round-robin poll of the non-current machine.

- Name **VARISPEED_EMUS**; TSTR label `VARI`; ATTR label `VARI`.
- The ATTR integration is kept.
- One build (VARI + S950 + SP12 + the DSP kernel); no VARI-only build.
- The DSP kernel is the hardware-proven one, unchanged. No ColdFire-only emulation.

## 5. Acceptance (implementation phase)

- **Black-box equivalence** with the shipped FINAL REPITCH_REPEAT98_KYOTI image in the emulator,
  outputs only, where the two designs coincide:

  | new | shipped |
  |---|---|
  | VARI, EMUS `OT` | TSTR 4 (RPCH) |
  | VARI, EMUS `S950` | TSTR 5 (RPS9) |
  | VARI, EMUS `SP12` | TSTR 6 (RPSP) |

  Run it over TSTR × TSMODE × STATIC/FLEX/PICKUP × tempos in and out of range × QUAN values ×
  RATE values × forward/reverse:
  - the increment each DSP voice pass receives (`l:$40`) is bit-identical
  - the audio matches by levels/spectra
  - screens are compared only where the UI is the same (PTCH/QUAN, the ATTR row for VARISPEED vs
    REPITCH aside)

  Out of range is the one deliberate difference: OFF with stock pitch. Check it against stock OFF
  instead.
- New behaviour has its own tests: EMUS swap and adoption, the engine latch at trig (a mid-note
  EMUS change does not switch the engine), item 11, and item 10 (no crash).
- The DSP-side checks (`vem_dsp.asm` bit-exact vs the engine model) are unchanged and still pass.
- Hardware: a VARISPEED_EMUS checklist in FLASHING §4 on the MKI before any promotion.

## 6. The DSP load guard (added 2026-10-14, the user's request)

Source: our KYOTI load audit (2026-10-05). Its numbers are copied below. Clean agents do NOT open
`reference/handoffs/KYOTI_LOAD_AUDIT.md`: its per-feature table names the old ColdFire core's
routines and hook site. Shipped behaviour
today: four SP12 voices on one DSP core beside heavy stock FX can overrun the DSP on the unit. The
audio squeals or pops and the sequencer stops. The guard must prevent that, and must change nothing
in every situation that does not overrun.

1. **Model, per DSP core, recomputed every frame.** The estimate is the sum of:
   - a base: the four-track loop with all FX NONE: 574 modelled cycles on core 1, 477 on core 0;
   - the stock price of each FX1/FX2 effect on that core's four tracks, in modelled cycles per
     sample (measured on core 1; use them for both):

     | effect | cycles | effect | cycles | effect | cycles |
     |---|---|---|---|---|---|
     | DJ EQ | 347 | LO-FI | 313 | CHORUS | 312 |
     | SPRING | 306 | FILTER | 267 | DARK | 267 |
     | PLATE | 240 | PHASER | 223 | EQ | 200 |
     | FLANGER | 146 | COMB | 111 | COMPRESSOR | 89 |
     | SPATIALIZER | 77 | DELAY | 0 (ColdFire) | NONE | 0 |

     (SPRING is gone in this image. SIDECHAIN_COMPRESSOR, when it shares an image, adds a fixed
     56 per core.)
   - the price of each **sounding** voice's engine: SP12 and S950 at the per-voice worst case
     from `tools/varispeed_emus_dsp_profile.py`; OT costs 0.

   Keep every price and budget as a named constant in one place. The DSP kernels are being
   optimized in parallel, so their prices will change. Find which tracks run on which core, and
   how the ColdFire knows a track's FX types and whether its voice is sounding, from the stock
   image.
2. **Budget per core:** the user's hardware brackets (4 SP12 voices sounding, DARK on every
   FX2, DJ EQ added on FX1):
   - Core with T5–T8 (fails first): clean ≈ 3,350, crash ≈ 3,740 modelled cycles.
   - The other core: clean ≈ 3,930, crash ≈ 4,310.

   The guard acts above the **clean** point. These are the user's own measurements; they get
   re-tuned on hardware.
3. **What it does:**
   - **At the trig latch.** If latching S950 or SP12 would put the core over budget, latch the
     next cheaper engine instead: SP12 → S950 → OT, or S950 → OT.
   - **Mid-note.** If the estimate rises over budget later (another voice starts, an FX changes),
     step down the emu voices on that core at once, most recently started first, until the
     estimate is under budget. A click is better than a crash.
   - **Back up.** A stepped-down track returns to its EMUS choice only at a later trig, when the
     budget allows.
   - **Never anything else.** It never touches OT tracks, stock tracks or stock FX. If stock FX
     alone exceed the budget, the guard steps every emu voice on that core down to OT and does
     nothing more.
4. **Visible:** while a track plays a cheaper engine than its EMUS setting, its EMUS readout
   says so. For example, the playing engine with a marker, within the existing readout width.
   Draw paths only: no toast, nothing UI from the frame path (CLAUDE.md).
5. **Cost:** a few dozen ColdFire instructions per frame at most, and nothing on the DSP.
6. **Tests:**
   - **Under budget:** bit-identical increments to VEM3, on every existing harness scenario.
   - **Over budget:** scenarios built with runtime pokes on real exported projects. 4 × SP12 +
     DARK ×4 + DJ EQ ×3 on the T5–T8 core steps down; the same with DJ EQ ×2 does not.
   - **Stepping order and restore.**
   - **A FLASHING §4 hardware item:** the audit's crash setup no longer crashes, and nothing
     steps down at normal loads.

### 6a. Guard UX (the user, 2026-10-15, after VEM4G)

1. **The dial stays on the user's EMUS choice.** While the guard holds a track below it, only the
   readout changes, to the engine actually playing with a `!` (`S95!`, `OT!`). When the guard
   restores the track at a later trig, the readout returns to the choice.
2. **A toast, only when the user's own UI action meets the limit:** turning EMUS to an engine
   that does not fit, or switching a track into VARI (SETUP TSTR, or ATTR TIMESTRETCH under
   AUTO) whose EMUS does not fit.
   - "Does not fit" means: at that moment, with this track's engine counted as the one asked
     for, the core's estimate is over budget.
   - The text is exactly `MAX DSP: S950 USED` or `MAX DSP: OT USED`, naming the engine the guard
     would use.
   - If that text cannot be shown in full in a stock toast, do not cut it: report the measured
     limit and stop for the user's decision.
   - Raise the toast only from those UI handlers, the way this repo's other modules raise
     toasts from key handlers.
3. **No toast ever from the frame path,** and none when the guard acts on its own (CLAUDE.md:
   UI and kernel primitives from the frame path crashed a unit).

### 6b. The guard redesigned: refuse, never step down at run time (the user, 2026-10-15, after flashing VEM5)

This replaces §6 items 3–4 and all of §6a. The VEM5 guard stepped voices down at trigs and
mid-note, marked the readout `S95!` / `OT!`, and moved nothing the user could see. The user does
not want that. The new principle: **a change that would overload the DSP is not allowed.** The
control does not take the position the user was going for, and the toast `MAX DSP: EMU LIMIT`
shows. When something must give, the step-down is always to **OT**.

1. **The load is a property of the settings, not of playback.** VEM4G measured that the DSP runs
   a track's S950/SP12 engine on every pass whose increment carries it, sounding or not. So per
   core: base + the FX prices + the engine price of every track that is a VARI track (the §2
   gate: VARI or AUTO+VARI, ST/FL, tempos in range) with EMUS on S950 or SP12. Prices and
   budgets are as now (`VG_*`: SP12 218, S950 99, budgets 3,350 for T5–T8 and 3,930 for T1–T4).
   Nothing in the frame path steps anything down any more. The engine latch at the trig stays
   exactly as it is.
2. **Refused** (the value stays as it was, toast):
   - **EMUS turned toward an engine that does not fit.** The knob stops at the highest position
     that fits. Turning toward a cheaper engine is always allowed.
   - **An FX type that does not fit**, on a track's FX1 or FX2. The selection does not land on
     that effect. This applies only when emulated engines are what tip the core over: if stock
     FX alone exceed the budget (no S950/SP12 track counted on that core), nothing is refused.
3. **Allowed, but EMUS steps to OT** (a real change of the EMUS value, so the display always
   matches what plays; toast):
   - **SETUP TSTR or ATTR TIMESTRETCH (under AUTO) → VARI** on a track whose EMUS engine does not
     fit: the track goes to VARI and its EMUS becomes OT.
   - **Changes that cannot sensibly be refused:** Part change, Part reload (stock RELOAD PART and
     the KYOTI chords), project or bank load, a machine change that brings a VARI setting along,
     and any other way the settings land over budget (for example a sample or tempo change that
     turns a track's gate on). Just enough tracks on that core get EMUS = OT: **SP12 tracks
     first, then S950, highest track number first.**
4. **The toast, `MAX DSP: EMU LIMIT`, for 1.2 s** (1.5 × stock's 0.8 s).
   - Raise it only from UI-task handlers (keys, encoder, editors), never from the frame path
     (CLAUDE.md).
   - When a step-down happens outside the UI task (a pattern change that switches Part from
     the sequencer), set a flag and raise the toast later from a safe UI-task point. If there
     is none, no toast for that case: say so in the report.
5. **Removed:**
   - the run-time step-down, at the trig and mid-note;
   - the `S95!` / `OT!` readout;
   - the MAX DSP: S950/OT USED toasts.

   EMUS always shows its stored value, which is what plays.
6. **EMUS feel:** **4 detents per step** (was 6; the user: "at least 1/3 less turning").
   Reversal still restarts the count.
7. **Tests:**
   - Every refusal (EMUS, FX).
   - TSTR/ATTR → VARI stepping EMUS to OT.
   - Part change, reload and project load over budget stepping the right tracks to OT.
   - Nothing refused or changed under budget.
   - The harness stays identical on every existing scenario.
   - The toast only from UI handlers.

#### 6b, simplified (the user, 2026-10-15): two refusals and one safety net

Item 3's list of per-path hooks (Part change, reload, project and bank load, machine change,
gate changes) is replaced by **one safety net**:

- **The two refusals of item 2 stay,** at their UI handlers: EMUS, and the FX type.
- **The safety net:** a single check of the per-core settings estimate, run only when the
  settings have changed (keep a cheap signature of the inputs, and recompute only when it
  differs). It finds over-budget cores however they got there:
  - Part change or reload;
  - project or bank load, including projects from earlier builds, stock or the old module;
  - a machine change that activates a different per-machine setting;
  - copy/paste of FX pages, tracks or Parts;
  - a sample or tempo change that turns a gate on;
  - TSTR or ATTR → VARI.

  It sets just enough EMUS to OT on that core (SP12 first, then S950, highest track number
  first), using the existing swap/park rules.
- **The toast after a safety-net step-down:** raised from the UI task straight away if the change
  came from a UI handler, or later from a proven-safe UI-task point otherwise. Never from the
  frame path.

The behaviour the user sees is item 3's; only the mechanism is simpler.

#### 6b, answers (the user, 2026-10-15, after VEM6)

- **TSTR or ATTR → VARI on a track whose engine does not fit:** that track's own EMUS goes to OT,
  not the net's order. The user acts on that track. Every other over-budget case keeps the net's
  order.
- **RELOAD PART** gets no special code. The net acts on a reload only if the result is over budget,
  which on this firmware means a project-wide sample setting changed after the Part was saved
  (a sample's tempo or TIMESTRETCH, or the sample in a slot). Projects from earlier builds or
  the old module are out of scope (the user does not care about them).

## 7. VARISPEED: the plain build (the user, 2026-10-15)

A second feature from the same code: **VARISPEED**. It is VARI with QUAN and nothing emulated.

- **Kept, exactly as VARISPEED_EMUS:**
  - TSTR 5 positions (`VARI`), ATTR `VARI`;
  - the gate, the exact tempo ratio, QUAN on PTCH with its swap and park rules;
  - the per-machine state, the paste/clear/undo wrappers, the item-11 fix, `rp_sync`;
  - the octave fold above 2x;
  - out of range = OFF.

  A VARI track's increment is computed exactly as VARISPEED_EMUS computes it for EMUS = OT, so
  VARI plays bit-identically to VARISPEED_EMUS on OT.
- **Removed:**
  - the DSP kernel and both DSP hooks; SPRING REVERB stays in the image, untouched;
  - EMUS and the TSNS takeover (TSNS stays TSNS; no second park pair);
  - the load guard, its refusals, its safety net and its toast;
  - the engine tag and latch;
  - the bits-2-3 mask on stock tracks' increments: stock tracks are untouched.
- **Builds:**
  - a standalone, `tools/build_varispeed.py` → `OCTATRACK_OS1.40C_VARISPEED`;
  - a Bugbuild, `BUG_VARI`, composed by `tools/build_bugbuilds.py`. The composer only takes
    promoted bases, so add an explicit opt-in for one WIP base, keeping its refusals for
    everything else. With `KYOTI_ALLOW_WIP=1 ... --wip VARISPEED` it builds that one Bugbuild,
    clearly WIP. Nothing changes for the seven final Bugbuilds: their hashes must stay their pins.
- **Source:** shared with VARISPEED_EMUS, one source with an assembly switch, so fixes cannot
  diverge. (octabam `defsyms` are link-time: `.ifdef` gates need source defaults.)

#### 6b, option B (the user, 2026-10-15, after VEM7)

**A track that becomes a VARI track indirectly** steps **its own** EMUS to OT when its engine
does not fit, the same rule as TSTR/ATTR → VARI. "Indirectly" means its gate turns on with TSTR
untouched: a sample's ATTR tempo moved into range, a different sample assigned to its slot, a
sample loaded into the slot, or its sample's TIMESTRETCH set to VARI under AUTO. The net's order
(SP12 first, highest track first) applies only when no single track can be named as the one that
changed: Part change or reload, project or bank load, machine change, paste. If one action moves
several tracks onto VARI at once, those tracks step in the net's order among themselves.

(Also 2026-10-15: SP12 goes back to full stereo on the DSP side. The ColdFire side changes only
the guard's `VG_SP12` price, which the DSP work measures and the dirty side updates.)

#### 6b, option B extended (the user, 2026-10-15, after VEM9)

**A slot assign that also changes the machine** (a FLEX slot picked for a STATIC track, or the
reverse) counts as an indirect entry onto VARI for that track. If the new machine's setting puts
the track on VARI and its engine does not fit, **that track's own** EMUS steps to OT, with the
toast. It does not get the net's order. A machine change made on its own, from the machine
selector, keeps the net's order.

**VARISPEED_EMUS also gets a Bugbuild:** `BUG_VEM…`, composed by `tools/build_bugbuilds.py` through
the same explicit WIP opt-in as VARISPEED (`--wip VARISPEED_EMUS`). It is never sealed, and the
final Bugbuilds are untouched.

#### 6b, option B extended: answers (the user, 2026-10-15, after VEM10)

1. **A track already on VARI under its old machine,** which a slot pick moves onto its other
   machine's heavier VARI setting, counts as named: its own EMUS steps to OT. This is VEM10's
   behaviour.
2. **The equal-slot pick** (the machine changes, and the slot assign does not run because the
   other machine already holds that slot) counts as a slot pick. This is VEM10's behaviour.
