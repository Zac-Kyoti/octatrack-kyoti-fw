# START HERE — onboarding for a new session

Octatrack (OS 1.40C) firmware reverse-engineering and custom behaviour patches. This is the
stable entry point: read it, then the pointers it names. Keep it short, and update §6 at the
end of each session.

---

## 0. What loads automatically

Running Claude on this Mac auto-loads the project memory
(`~/.claude/projects/-Users-kyoti-m4/memory/octamax-re-project.md`) — a per-session digest
of state. Treat it as the summary; this repo's docs are the detail.

Local repo: `~/Documents/octatrack-kyoti-fw/`, published as
<https://github.com/Zac-Kyoti/octatrack-kyoti-fw>. It is an independent project: none of
octamax's feature code is in a build, only its concepts and a few setup scripts (credit in
`CREDITS.md`, the licence carve-out in `LICENSE`). Remotes: `origin` = the published repo,
`upstream` = mxldyn (fetch only, for `whatsnew.py`).

## 1. Read order for a new chat

1. **This file.** §5 is how work is organised, §6 the open work.
2. **`NOTES.md`** — the RE log. **Do not read top-to-bottom** (it starts at 2026-07 recon).
   Jump to the newest `## Session N` and the most recent `### … STATE OF PLAY` /
   `### NEXT …` blocks. Section index: `grep -nE '^## ' NOTES.md`.
3. **`reference/kb/*.md`** for anything touching the descriptor table, file formats, DSP,
   the container or **caves**; then the task-specific docs from §2.
4. Only then open `tools/*` and `out/ghidra/*` for the subsystem in question.

## 2. Document map

| File | Use it for |
|---|---|
| `README.md` | the final features, what each does, its hardware status and final build |
| `BUILD_KYOTI.md` | how to build: prerequisites, setup, one command per final feature |
| `FLASHING.md` | how to flash (MIDI and CF card), verify, and recover |
| `NOTES.md` | the full chronological RE log — every finding, every session, every dead end |
| `reference/kb/*.md` | the distilled knowledge base — address map, file format, DSP, container, techniques, caves; ours merged with external RE |
| `reference/MERGE.md` | the combined image (`tools/build_kyoti.py`): its cave layout across zones, the evidence for each zone, the resolved merge blockers |
| `reference/handoffs/*.md` | design contracts and scopes: `DIRECTJUMP_V7_DESIGN.md` (DIRECT_JUMP_KYOTI), `REPITCH_*` (REPITCH_REPEAT98_KYOTI), `RELOAD3_SEQFAIL_HANDOFF.md` |
| `reference/RELOAD_REDESIGN.md` | RELOAD_FROM_PROJECT's chord design and the measured keymap facts |
| `reference/OT_SEQUENCER_BUGS.md` | every stock sequencer bug we have determined, and the measured NOT-bugs |
| `reference/AR_*.md` | the Analog Rytm's sequencer and pattern-commit arithmetic (DIRECT_JUMP_KYOTI research) |
| `reference/EXTERNAL_RESEARCH.md` · `UPSTREAM_INBOX.md` | the external OT-RE repos we track, and what is pending distillation |
| `COVERAGE.md` | this project's own RE coverage: what is mapped vs still dark, per manual chapter |
| `ARCHITECTURE.md` | memory map, container format, boot/upgrade chain |
| `octabam-modules/` | the features packaged as octabam modules — one self-contained folder each |

## 3. Hard constraints (do not relearn these the hard way)

- **Hardware = Octatrack MKI only.** The user does not own a MKII. Stock 1.40C is one image
  for both; the boot `0x46c8d18c` probe adapts it (e.g. the MKI shows 15 PERSONALIZE items,
  no `LED BRIGHTNESS`). Earlier notes that said "MKII" were wrong and are corrected.
- **Test data**: only ever use real hardware-exported project files. Never fabricate or
  hand-edit a `.work`/bank/project blob. If a run needs test banks, ask the user to export.
- **macOS TCC**: `~/Documents` is protected; the responsible binary is the Anthropic `claude`
  binary, **not** VS Code. Grant Full Disk Access to
  `~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude`
  (re-add after each extension update) or run `claude` from Terminal.app.
- **Builds are guarded binary patches**, never hand-assembled images: every splice asserts the
  stock bytes it overwrites, asserts caves are free / non-overlapping / within the free zone,
  and round-trips through Elektron's own firmware tool. Keep it that way.
- "Corruption" in the notes = **Ghidra failing to decompile** dense ColdFire functions
  (`halt_baddata()` markers), a readability limit — *not* corruption in the OS or our output.

### Measurement rules, each paid for by a hardware regression

- **A green suite does not mean a current flashable image.** A builder can `sys.exit()`
  after writing `out/mainos_*.bin` but before wrapping the `.syx`/`.bin`; every emulator
  tool loads the pre-abort file, so the tests pass while the artifact you would flash is
  stale. Check the **mtime of the artifact you would actually flash** against the commits
  it should contain. The tests cannot tell you this, by construction.
- **Never snapshot at a detour site; snapshot at the return address.** A Unicorn code hook
  fires *before* the instruction executes, so hooking your own `jsr` measures stock's
  output. This has produced both a false FAIL on correct code and a false PASS on code
  that was corrupting tracks.
- **Unicorn zero-fills memory**, so every uninitialised global reads 0 in the emulator and
  a hook gated on one can never fire there. A differential gate cannot see this class of
  bug — it reported IDENTICAL on a build that locked the unit up. Poison the scratch block
  before the patched run.
- **Role-equivalence is not semantic equivalence.** Before copying any AR per-track write
  onto its OT counterpart, measure OT's own writers and readers of that array first. The
  mapping table pairs arrays by role; that is not licence to copy writes element-wise.
- **Keep time by reading the clock, never by reseeding it.** Both DIRECT JUMP and RELOAD3
  shipped a bug that came down to writing the master playhead; the metronome's beat flags
  derive from the same word, so one write breaks two things at once.
- **Grade against the spec, not a proxy.** DIRECT JUMP V1–V5 passed gate after gate that
  measured timing classes modulo the step length, which cannot see a whole-step shift. V7
  was graded by equality with a never-switched reference run of the same pattern
  (`tools/diag_reflock.py` + `cmp_reflock.py`), after the oracle itself was shown to fail the
  known-bad builds — and passed first time on hardware.
- **`er.stage_project` is not concurrency-safe** — it stages into a single shared tree, so
  two full-firmware diagnostics started in parallel race in `mkdir`. Run the suite
  sequentially.

## 4. Toolchain entry points

| Need | Command |
|---|---|
| decompressed stock image | `out/raw/section_3_MAIN_OS.bin` (base `0x40000400`); regenerate with `./fetch-os.sh && ./analyze.sh` |
| disassemble | `m68k-elf-objdump -D -b binary -m m68k:cfv4e -EB --adjust-vma=0x40000400 --start-address=… out/raw/section_3_MAIN_OS.bin` |
| Ghidra headless | JDK 21 + Ghidra 12.1.2 paths in the memory file; project `ghidra_project octamax`, `-process section_3_MAIN_OS.bin -noanalysis`; helpers in `tools/ghidra/`, dumps land in `out/ghidra/` |
| ColdFire emulation | `tools/emu_rtos.py` (Unicorn on real image bytes, via octabam's emulator in `refs/octabam/`) |
| DIRECT_JUMP_KYOTI timing gate | `tools/diag_reflock.py` + `tools/cmp_reflock.py` (equality with a never-switched reference run) |
| REPITCH_REPEAT98_KYOTI DSP gate | `tools/repitch_dsp_*` (bit-exact against the reference engine) |
| DSP assembly | `tools/dsp_xasm.py` over `vendor/dsp56300`'s `dsp_asm` |
| a final build | `tools/build_<feature>.py` → `.syx` (MIDI) + `.bin` (CF card); see `BUILD_KYOTI.md` |
| the combined image | `tools/build_kyoti.py` — **WIP, withdrawn 2026-10-06** (crashes; see §6) |
| octabam's remixer (`make remix`) | `sh tools/octabam_remixer.sh` — its own clone at `~/Documents/octabam`, fast-forwarded to octabam's `main` on every launch; `refs/octabam` stays the pinned research harness |
| each feature + BATCH_BUGFIXES | `tools/build_bugbuilds.py` (final, seven images; REPITCH's `BUG_RPK16` is WIP since 2026-10-06 and skipped) |
| DIRECT JUMP V6.4, the OT↔AR parity build | `tools/build_direct_jump_v6_4.py` — WIP **by design**: kept buildable at the user's request (hardware-confirmed image `4a6c1b5e…`), never to be promoted |
| external RE research | `python3 tools/refs/sync.py` (clone or refresh the tracked repos into `refs/`) · `python3 tools/refs/whatsnew.py` |

## 5. How work is organised

**One branch, `main`**, carries everything. **Several sessions may work at once** —
`CLAUDE.md` "Concurrent sessions": one git worktree per session (`tools/worktree.sh`),
explicit-path commits, and a commit guard driven by `tools/githooks/threads.txt`.

**Everything is WIP until the author promotes it to final.** `tools/kyoti_status.py` holds
the FINAL list: each promoted builder, pinned to the sha256 of the image it built when
promoted. Every builder calls `gate(__file__)` first — a builder not on the list refuses to
run without `KYOTI_ALLOW_WIP=1` — and `seal(__file__, image)` after writing its image: a
final builder whose image has changed since promotion is WIP again, and refuses without the
opt-in. Diagnostic variants build a different image, so they are WIP too.

**Promotion happens only on the author's explicit instruction.** Build it, put the sha256
that `seal()` prints into `FINAL`, and give the feature its entry in `README.md` (and
`BUILD_KYOTI.md`). An update to a final feature replaces the old final: in place when the
builder itself was updated, or — when the update is a new builder — it takes the old
builder's FINAL entry and the old builder is deleted. There is no superseded tier.

**Feature names.** Use these everywhere — builders, images, docs, octabam keys:

| feature | builder | octabam module |
|---|---|---|
| MUTE_MODES | `build_mute_modes.py` | `octabam-modules/mute-modes` |
| DIRECT_JUMP_KYOTI | `build_direct_jump_kyoti.py` | `octabam-modules/direct-jump-kyoti` |
| SIDECHAIN_COMPRESSOR | `build_sidechain_compressor.py` | `octabam-modules/sidechain-compressor` (octabam #565; on hardware 2026-10-04) |
| RELOAD_FROM_PROJECT | `build_reload_from_project.py` | `octabam-modules/reload-from-project` |
| REPITCH_REPEAT98_KYOTI | `build_repitch_repeat98_kyoti.py` (**WIP since 2026-10-06**) | `octabam-modules/repitch-repeat98-kyoti` (octabam #561; on hardware 2026-10-05) |
| QUANTIZE_LIVE_REC_TOGGLE | `build_quantize_live_rec_toggle.py` | `octabam-modules/quantize-live-rec-toggle` |
| ERASE_EMPTY_TRIGLESS_LOCKS | `build_erase_empty_trigless_locks.py` | `octabam-modules/erase-empty-trigless-locks` |
| REC_TRIG_MUTE | `build_rec_trig_mute.py` | `octabam-modules/rec-trig-mute` |
| BATCH_BUGFIXES: MIDI_PLAYS_FREE_FIX · EMPTY_PATTERN_LED_FIX · PART_CHANGE_CARRYOVER_FIX | `build_midi_plays_free_fix.py` · `build_empty_pattern_led_fix.py` · `build_part_change_carryover_fix.py` | `octabam-modules/batch-bugfixes` |

The assembly sources keep their historical names (`patch_directjump_v7.s`,
`patch_trigscale.s`, …) so they stay greppable against `NOTES.md`. Octabam module folders
are lowercase-hyphen, because octabam requires a module's name to equal its folder.

## 6. Open work — UPDATE THIS EACH SESSION

> Check this against the tree before trusting it; it has gone stale before.

- **KYOTI V1.0** (`tools/build_kyoti.py`) — **WITHDRAWN 2026-10-06** (was FINAL 2026-09-30,
  syx `5106f7fb…`). Its midisc pads are live stock parameter-page tables. Confirmed crashes:
  - an encoder on an FX page set to NONE;
  - T8's PLAYBACK/LFO page with T8 MASTER on.

  Builds only with `KYOTI_ALLOW_WIP=1`. `reference/handoffs/KYOTI_LOAD_AUDIT.md` §8/§8b;
  replacement under discussion (octabam remix). The octabam images OBKYOTI6–12 are clean.
- **DIRECT_JUMP_KYOTI** — not yet on hardware: MIDI tracks, and Program Change on fast
  re-cues.
- **REPITCH_REPEAT98_KYOTI** — **demoted to WIP 2026-10-06** (standalone build and
  `BUG_RPK16`; FINAL pins removed, README entry replaced by a notice). On the user's MKI, RPSP
  on all four tracks of a core with DARK REV + DJ EQ crashes the DSP (tone, sequencer stops);
  beside stock's heaviest FX a core has room for about one RPSP voice.
  `reference/handoffs/KYOTI_LOAD_AUDIT.md` §1 (HW-A..F): the bar is ≈ 60–75 modelled cycles
  per voice; RPSP costs ≈ 234–239, RPS9 ≈ 77 (≈ 58 in the octabam-port worktree's unpushed
  bit-exact rework). Not specifically tested: RTRG retrigs.
- **octabam port** — the six modules, REC_TRIG_MUTE and SIDECHAIN_COMPRESSOR (+ MUTE_MODES'
  SC_KEY variant, #565) are merged in octabam. REPITCH_REPEAT98_KYOTI: PR sambanks/octabam#561,
  both halves, hardware-confirmed in octabam form 2026-10-05 (OBKYOTI11, only SPRING REV given
  up). `NOTES.md` Session 120 continued (4)-(8).
- **KYOTI modules × Octakit** — ⚠️ octabam removed Octakit on 2026-10-06 (replaced by its own KITS), so the
  conflicts below no longer bite there; KITS is untested with our modules. DIRECT_JUMP_KYOTI and RELOAD_FROM_PROJECT crash beside
  Octakit and are refused with it until bridges exist (`a7a5291`, `c9a66cf`; live in octabam
  since `f3b12f36`). Scope, findings and the plan:
  `reference/handoffs/DIRECTJUMP_OCTAKIT_SCOPE.md` — start at its §0. `NOTES.md` Session 121.
- **REC_TRIG_MUTE** (`tools/build_rec_trig_mute.py`) — FINAL since 2026-10-03, standalone
  (syx `c1cd7381…`) and in KYOTI V1.0. MIDI CC 80 not tried on hardware yet. Not done on
  purpose: MIDI echo / CC 80 state at power-up. Also as `BUG_RTM` (+ BATCH_BUGFIXES), and
  as an octabam module (sambanks/octabam #566 merged `fa24fb53`; follow-up #572 open). `reference/handoffs/REC_TRIG_MUTE_SCOPE.md`, `NOTES.md`
  Sessions 122–123.
- **KYOTI load audit** (Session 125) — `reference/handoffs/KYOTI_LOAD_AUDIT.md`: ranked DSP/ColdFire
  costs of every feature, the hardware test plan (HW-A first, no flash), and **a KYOTI V1.0 crash on
  the MASTER track's PLAYBACK/LFO page** (emulator; section 8), not fixed yet.
