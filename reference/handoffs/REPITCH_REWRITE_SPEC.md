# REPITCH rewrite: clean-room spec

Written 2026-10-13 for a clean-room rewrite of the ColdFire core of REPITCH_REPEAT98_KYOTI. The
goal is a module with no code from Jannik Aßfalg's (repeat98) octabam `repitch` module, the base
the shipped module grew from. Jannik asked for the emulations to be separated from his Repitch
altogether. The rewrite keeps the feature the same for the player and replaces only the part
that came from his code.

This file is **clean**: it states behaviour, our own interfaces and our own DSP facts. It names
none of his hook sites or mechanisms. Keep it that way.

## 1. The clean-room protocol

Two roles:

- **Dirty:** the session that has read Jannik's code or his firmware notes. It writes this spec,
  reviews results against behaviour, and alone keeps `REPITCH_REWRITE_OVERLAP.md`.
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
  `manifest.py` (use the redacted `REPITCH_REWRITE_RETAINED.s` instead)
- `tools/*repitch*` (builder, probes, trace patch, emulator checks)
- `reference/handoffs/REPITCH_*.md` **except this file and the scope file the clean agent
  writes**, especially `REPITCH_REWRITE_OVERLAP.md`
- `NOTES.md` sessions and `CREDITS.md` paragraphs about repitch / RPCH / REPITCH
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
- our own code: `REPITCH_REWRITE_RETAINED.s` (redacted from the shipped module),
  `octabam-modules/repitch-repeat98-kyoti/rpk_glyphs.s`, `patch_repitch_reload.s`,
  `rpk_dsp.asm`, `rpk_dsp_ptable.py`, and the module's `README.md`
- other features' code in this repo (DIRECT_JUMP, MUTE_MODES, …) as examples of how we hook

A firmware fact the clean agent rediscovers on its own (including a site that may turn out to
be the only workable one) is fine. Copying a fact from the blacklisted material is not.

## 2. What the feature does (unchanged for the player)

1. **TSTR on STATIC and FLEX** gets seven positions: `OFF AUTO NORM BEAT RPCH RPS9 RPSP`, raw
   values 0..6. Raw 4/5/6 are what the Part and project store. Projects saved with the shipped
   module (and RPCH projects from octabam's REPITCH) must load unchanged. The selector draws
   our seven glyphs (`rpk_glyphs.s`). PICKUP is untouched.
2. **Audio editor, ATTR page, TIMESTRETCH** (the sample's own setting) gains `REPITCH`,
   `RPS9`, `RPSP` (raw 4/5/6) after BEAT. The value keys step OFF ↔ NORMAL ↔ BEAT ↔ REPITCH ↔
   RPS9 ↔ RPSP, and every ATTR edit calls `rp_refresh` so the PLAYBACK dial follows at once.
   Under SETUP `AUTO`, the sample's own value applies, mode included.
3. **A repitch track**: SETUP 4/5/6, or AUTO with sample TSMODE 4/5/6. It must be STATIC or
   FLEX with a bound sample whose tempo (BPM×24) lies in 720..7200, and the project tempo must
   lie in the same range. On such a track:
   - **Speed** = (project BPM × p) / (sample BPM × q), where p/q is the QUAN ratio, computed
     **exactly in integers** (no rounding drift: N = projectBPM24·p, D = sampleBPM24·q). While
     N > 2D, D doubles (an exact octave fold). The scaled increment is clamped to 2.0 − 16
     LSB in the Q26 increment (the tag in item 5 must never push it past 2.0).
   - Pitch and length move together: **no grains, no time-stretch.** The track plays dry,
     forwards and in reverse, and follows tempo changes every frame.
   - **RATE still applies** (tape stops keep working). **PTCH is not applied as pitch.** Its
     composed word (base value + p-locks + scenes) selects the QUAN ratio instead (item 4).
     For LFO-on-PTCH and note transposition, match the shipped module's behaviour; find out
     by the §5 comparison.
   - Outside the tempo ranges, or off these modes, the track plays exactly as stock.
4. **QUAN** (retained code): the PTCH page-1 slot on a repitch track. Index =
   `rk_bucket(word >> 8)` from the composed 16-bit PTCH word; ratio = `.rk_ratios[idx]`
   (p, q bytes; nine values 1/2 … 2/1, 1/1 at ui 64).
5. **DSP mode tag** (our own design; the DSP kernel depends on it). The Q26 increment that
   reaches the DSP voice command carries the mode in **bits 2-3**: 0 = RPCH, 1 = RPS9,
   2 = RPSP. The DSP rebuilds the increment as a net `>>2`, so bits 0-1 never arrive. On the
   DSP the mode lands in `y:$40` bits 0-1 (`l:$40` = this voice's increment), where
   `rpk_dsp.asm` reads it.
   - On a repitch track: clear bits 0-3, then OR in mode<<2.
   - On **every other increment the firmware builds**: bits 2-3 must be 0, so a stock track
     never reads as RPS9/RPSP by chance (PTCH +1 st gives arbitrary low bits). Our earlier
     finding, which you should verify yourself: the firmware's other increment writers store
     the literal `0x04000000`.
6. **DSP kernel**: `rpk_dsp.asm` unchanged, with its two hooks and Y claim as in the module
   README. New requirement: an **RPCH-only build option** with no DSP hooks, no Y claim and
   no effect given up. TSTR then has five positions (no RPS9/RPSP), and ATTR offers only
   REPITCH.
7. **Cost**: a track not on a repitch mode should cost near nothing extra per frame (a few
   instructions). The KYOTI load audit flagged the old per-frame path; don't regress it.
8. **Coexistence**: conflicts with octabam's `REPITCH` and with `repitch-repeat98-kyoti` (same
   TSTR words). It must coexist with every other KYOTI module.

## 3. Interfaces to the retained code (`REPITCH_REWRITE_RETAINED.s`)

- `rp_swap` (d1 = track, preserves all): the PTCH↔QUAN domain bookkeeping. The new core calls
  it **every frame for each track whose repitch gate is on, or whose `rp_prev[t]` byte is
  nonzero** (the gate was on last time, or the bookkeeping is forgotten/held). A track with
  the gate off and `rp_prev[t] == 0` skips it: that is the cheap path for stock tracks. It is
  also polled at dial draws (already in the retained code).
- `rp_prev`: 8 bytes, one per track (`0xff` forgotten, `0xfe` = RP_HOLD during RELOAD PART).
- `rp_ui_gate` (d1 → d0): the Part-DB form of the gate, used by the UI. The runtime gate the
  new core computes **must agree with it** (same modes, same tempo range, STATIC/FLEX only).
- `rk_bucket`, `.rk_ratios`: QUAN index and ratio table (item 4).
- `rp_refresh`: call after an ATTR TIMESTRETCH edit.
- `rp_forget` / `rp_apply1` / `rp_apply2` / `rp_reload` (`patch_repitch_reload.s`): Part
  applies and RELOAD PART. These are our own hook sites and stay as they are.
- `quant_widget`, `quant_fmt`, `quant_step`, `qdial1..4`: QUAN drawing and stepping. Ours,
  staying as they are.
- The old core read the per-track TSTR, the sample's TSMODE/tempo and the project tempo for
  itself. The new core finds and reads them its own way.

## 4. Open product decisions (the user's)

- **Name.** Placeholder `REPITCH_KYOTI`. `repeat98` leaves the name either way.
- **ATTR integration**: kept by default (item 2). Report its cost; it can be dropped.
- **RPCH-only option** (item 6): asked for, but the build form (setting vs. separate builder)
  is still open.

## 5. Acceptance (implementation phase)

- **Black-box equivalence** with the shipped FINAL REPITCH image in the emulator, comparing
  **outputs only**, over the same matrix of TSTR 0..6 × TSMODE 0/2/4/5/6 × STATIC/FLEX/PICKUP ×
  tempos in and out of range × PTCH/QUAN values × RATE values × forward/reverse:
  - the increment each DSP voice pass receives (`l:$40`) is bit-identical
  - the screens (PLAYBACK page, PLAYBACK SETUP, ATTR) are identical
  - the audio matches by levels/spectra (not sample-exact: the CF workload differs)
- The DSP-side checks (`rpk_dsp.asm` bit-exact vs the engine model) are unchanged and still
  pass.
- Hardware: the FLASHING §4 REPITCH checklist on the MKI before any promotion.
