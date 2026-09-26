# START HERE — onboarding for a new session

Octatrack (OS 1.40C) firmware reverse-engineering + custom behaviour patches.
This file is the stable entry point. Read it, then the pointers it names. Keep it short;
update the **Current frontier** section at the end of each session.

---

## 0. What loads automatically

Running Claude on this Mac auto-loads the project memory
(`~/.claude/projects/-Users-kyoti-m4/memory/octamax-re-project.md`) — a per-session
digest of state. Treat it as the summary; this repo's docs are the detail.

Local repo: `~/Documents/octatrack-kyoti-fw/` (was `~/Documents/octamax/` until
2026-09-01). Published as <https://github.com/Zac-Kyoti/octatrack-kyoti-fw>. It is an
independent project, **not** a fork in any sense that matters: none of octamax's code
is in a build, only its concepts (credit lives in `CREDITS.md` and one README line —
keep it there). Remotes: `origin` = the published repo, `upstream` = mxldyn (fetch
only, for `whatsnew.py`).

## 1. Read order for a new chat

1. **This file** — §5 is the state of every build, §6 the current frontier. There is
   **one branch** (`main`); it carries finished and unfinished work alike, and the
   unfinished builders gate themselves (see §5).
2. **`NOTES.md`** — the RE log. **Do not read top-to-bottom** (it starts at 2026-07 recon).
   Jump to the newest `## Session N` section and the most recent
   `### … STATE OF PLAY` / `### NEXT …` blocks. Section index: `grep -nE '^## ' NOTES.md`.
3. **`reference/kb/*.md`** for anything touching the descriptor table, file formats, DSP, or
   the container; **task-specific docs** from the map below.
4. Only then open `tools/*` and `out/ghidra/*` for the subsystem in question.

## 2. Document map — what each file is for

| File | Use it for |
|---|---|
| `START_HERE.md` | this — onboarding + current frontier |
| `NOTES.md` | the full chronological RE log; every finding, every session, every dead end |
| `reference/kb/*.md` | **distilled knowledge base** — address map + file format + DSP + container + techniques, ours merged with external RE. Read the relevant one before a new patch |
| `reference/EXTERNAL_RESEARCH.md` | index of the 6 external OT-RE repos + the sync/distill workflow (`tools/refs/`) |
| `reference/MERGE.md` | **combining every final-scoped mod into one firmware** — cave allocation, detour inventory, shared-state table, and the two remaining blockers. The combined build is **deliberately not buildable** until every feature is shippable; this doc is what it will be rebuilt from, and it stages the merge as `KYOTI_V1.0` / `KYOTI_V1.1` |
| `reference/handoffs/*.md` | per-thread handoffs for work still open — read the relevant one **before** re-probing that thread (`DIRECTJUMP_SCALES_HANDOFF.md`, `RELOAD2_HANDOFF.md`) |
| `reference/AR_DIRECT_JUMP.md` | the Analog Rytm's own pattern-commit arithmetic, which DIRECT JUMP's position rule is ported from, plus its measurement hazards |
| `reference/RELOAD_REDESIGN.md` | the RELOAD3 chord design: why the picker went, the measured keymap facts, the Part-half semantics |
| `README.md` | what the firmware is, the feature list + per-feature HW status, repo layout, lineage |
| `BUILD_KYOTI.md` | roll-your-own build guide (every `build_*.py`, prerequisites, the reproducible patch) |
| `COVERAGE.md` | **this project's own** RE coverage: what is mapped vs still dark, per manual chapter. Descriptive; the scope policy is in `CLAUDE.md` |
| `ARCHITECTURE.md` | memory map, container format, boot/upgrade chain |
| `FLASHING.md` | step-by-step flashing (MIDI + CF card) and the per-feature hardware test procedures |
| `reference/upstream-notes.md` | inherited octamax mod-design notes (scenes, LED, lazy transitions, arp, bank paging) — kept for reference, **not** part of OT Kyoti FW |
| `tools/attic/` | the octamax mod patch sources + `build.py` — RE cross-reference, not built here |

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
- **`er.stage_project` is not concurrency-safe** — it stages into a single shared tree, so
  two full-firmware diagnostics started in parallel race in `mkdir`. Run the suite
  sequentially.

## 4. Toolchain entry points

| Need | Command |
|---|---|
| decompressed stock image | `out/raw/section_3_MAIN_OS.bin` (base `0x40000400`); regen via `./fetch-os.sh && ./analyze.sh` |
| disassemble | `./disasm.sh` (r2, m68k BE, base wired) — note r2 mis-decodes some ColdFire ops; prefer Ghidra |
| Ghidra headless | JDK 21 + Ghidra 12.1.2 paths in the memory file; project `ghidra_project octamax`, `-process section_3_MAIN_OS.bin -noanalysis`; one-shot probe scripts in `tools/ghidra/attic/*.java` (see `tools/ghidra/README.md`), dumps land in `out/ghidra/` |
| CPU emulation | `tools/emu_*.py` (Unicorn, runs the real image bytes) — one per feature |
| build a flashable | `tools/build_*.py` → `.syx` (MIDI) + `.bin` (CF card); see README §"Building" |
| external RE research | `python3 tools/refs/sync.py` (clone/refresh the 6 repos into `refs/`, gitignored) · `python3 tools/refs/whatsnew.py` (what changed upstream → re-distil into `reference/kb/`) |

## 5. Shipped / in-flight work

**One branch.** `main` carries every build, finished or not, plus the KB and the
diagnostics. The long-lived `wip` branch was retired on 2026-09-26: it had drifted 41/11
commits from `main`, mostly the same changes under different SHAs from cherry-picking
back and forth, and every sync cost a conflict-heavy merge. **Use short-lived topic
branches** for anything risky and merge them here when they settle.

What keeps unfinished work from being mistaken for shippable is `tools/kyoti_status.py`:
each builder declares **FINAL**, **PREVIEW** or **WIP** and announces it on every run, and
a **WIP** builder exits non-zero unless `KYOTI_ALLOW_WIP=1` is in the environment. Today
DIRECT JUMP is the only non-FINAL feature — `build_directjump_v4.py` is PREVIEW
(1x-confirmed), `build_directjump_v5.py` is WIP. When a tier changes, change the call and
the README table together. Upstream RE repos are tracked via `refs/`
(see `reference/EXTERNAL_RESEARCH.md`), not a mirrored branch.

**Finished and hardware-confirmed on the MKI** (per-feature detail and flash dates:
`README.md` → *Hardware-test status*, and `BUILD_KYOTI.md`):

| Thread | Build | State |
|---|---|---|
| **Bug 1** — Plays-Free MIDI manual-trig stall | `build_trigscale_only.py` | **confirmed** 2026-08-28. Always-on, folded into every feature build |
| **Bug 2** — a p-lock-only pattern reads as empty (grid LED unlit) | `build_pattern_led.py` | **confirmed** 2026-09-13 |
| **MUTE MODE** — `OT` / `OTFX` / `OTFX-T` / `DT-T`, menu, SOLO, `'ANDY'` persistence | `build_mutemode_dt.py` | **confirmed, final** 2026-09-21. All four modes; one persisted word with the menu index derived from it |
| **QUANTIZE LIVE REC** — `[REC]` + `[PLAY]`, then `[PLAY]` again while the toast is up | `build_qlrec.py` | **confirmed working** (2026-09-25) after three instructive failures: a `dur<=0` toast hung the unit, a `0x400522ca` frame-handler detour crashed it, and a private scratch word at `0x80006a60` did not survive on the unit. Now keeps **no state at all** — the gate is stock's toast handle. 2 cosmetic issues parked |
| **SIDE-CHAIN COMPRESSOR** — `KEY`/`KFLT`/`KGN`/`MON`, cross-core | `build_sidechain3.py` → `SIDECHAIN3_CROSS` | **confirmed, final** 2026-09-20, single-core and cross-core both |
| **TRIGLESS-LOCK AUTO-REMOVE** | `build_triglock.py` | **confirmed, final** 2026-09-21 |
| **Part-change carryover** — PICKUP→FLEX stuck loop + spurious Part-edited flag | `build_partreapply.py` | **confirmed** 2026-09-22/23, thread closed |

**Composites** — `build_bugbuilds.py` gives each finished feature its **own** image with
all three bug fixes folded into it: MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK and
RELOAD3, five images, written only to `out/Bugbuilds/`. Features are never combined with
each other. Not flashed; the composition itself is proven by a per-run
interlock proof. There is deliberately **no single all-in-one image**:
`tools/build_merged.py` stays withdrawn so a combined build cannot quietly ship an
unfinished feature. `reference/MERGE.md` is the authoritative allocation map it will
be rebuilt from, and stages the merge as `KYOTI_V1.0` (the seven mods finished when
it was written, nothing to resolve) then `KYOTI_V1.1` (+ DIRECT JUMP + RELOAD3; RELOAD3
has since been confirmed final, the map not yet re-cut).

**Not a shipped fix:** the MIDI LFO SETUP knobs sending CC on the twin audio channel
(the item older notes called "Bug 2", before that number was reused for the
pattern-LED fix) — emulation says it is **likely already fixed in stock 1.40C**,
awaiting a hardware check. `tools/emu_lfocc.py`.

**Not part of any build:** the third-party reference patch sources in `tools/attic/`
(branding, no BANK/PTN countdown, lazy Part transitions, arp key-scales, LED dirty
indicators). Kept for RE cross-reference; design notes in `reference/upstream-notes.md`;
credit in `CREDITS.md`.

**External-RE knowledge base** — `reference/kb/*.md`, the address-keyed distillate of
the 6 prior-art repos (octabam DSP map + kernel/RTOS + step-mask map, OctaLib file
formats, octa-bt-pt + octabam descriptor table, the bank-file p-lock region,
ems-octakit's `abi.inc` ~500-address map → `kb/octakit-abi.md`, the keymap/keycodes).
`python3 tools/refs/sync.py` populates the `refs/` cache;
`reference/EXTERNAL_RESEARCH.md` is the index.

---

## 6. Current frontier — UPDATE THIS EACH SESSION

**As of 2026-09-26 (Session 102 committed; a Session 103 experiment is uncommitted in
the working tree).** Every finished feature is here, and so is the one open thread.
RELOAD3, QLREC's stateless rewrite and SIDECHAIN3's UI fix were the last promotions
(2026-09-25).

**One thread is open (DIRECT JUMP). Everything else in §5 is finished, RELOAD3 included.**
DIRECT JUMP's builder is WIP-gated (see §5) so a visitor cannot build it by accident.

> Check this section against the tree before trusting it — it has gone stale before
> (2026-09-25: three claims about `main` that a merge had already made false).

**One thread is open (DIRECT JUMP). Everything else in §5 is finished, RELOAD3 included.**

### DIRECT JUMP — hardware-confirmed at 1x; non-1x scales are the whole remaining problem

`build_directjump_v5.py` (v1–v4 superseded). **Baseline to not regress**, flashed
2026-09-23 at 1x scales: tracks and patterns stay in master time through a switch,
patterns land on the correct step, mixed track lengths in one pattern work together
(7 / 12 / 16), MASTER LENGTH is respected including `INF`.

**Non-1x scales — how the thread got here.**

1. *Session 88 (Hook P, per-track step index).* Correct on paper, **flashed, and broke
   the 1x baseline; reverted.** The step-index theory was not the audible bug.
2. *Sessions 97–99 (V5.5).* The stock commit tail destroys each track's sub-step tick
   counter, so a track on a different ticks-per-step than the master lands mid-step.
   V5.5 preserved the counter by suppression (Hooks Z/X). **Hardware-rejected.** The
   emulator could not provoke the failure; a diagnostic build's on-screen toast
   (`A Z X Y P R`) measured it on the unit instead.
3. *Session 100 (V5.7).* The toast proved two holes: the mod-reduce sat at a site the
   unit runs for only some tracks (moved into Hook Z), and commits land mid-master-step
   (the master tick counter is now seeded with the remainder). Still fractional.
4. *Session 101 (V5.8).* The audible observable was found — the scheduled fire-timestamp
   table, `tools/diag_tablearm_phase.py` — and the bug reproduced in the emulator: the
   half-step flip originates at **natural pattern wraps**, which re-enter the commit body
   and re-phase 1x tracks under a 2x master. V5.8 preserves through wraps too. **On the
   unit: a large improvement** — fractional is now confined to the landing interval and
   heals at the cycle restart.
5. *Session 102 (V5.9).* The `V5_8D2` toast showed the residual is **not** the
   master-remainder case (N1 of A6). It also named a new symptom present since V5.8: a
   spurious trig once per cycle on the 2x track, half a step off-grid — the tail's
   reposition fire and the track's own advance fire, exclusive in stock only because
   stock zeroes the counter, both running under the wrap-preserve. V5.9's Hook W cut
   that conditionally; the suppression path is unreachable in the emulator, so hardware
   decides. **Session 103 (uncommitted) is replacing Hook W with a Hook V** that defers
   each track's whole apply to its own step boundary — read the working tree and
   `NOTES.md` before assuming which is current.

**Method lessons, hard-won:** the emulator judges STEP advances, which was the wrong
observable — trust the fire-timestamp table. Diagnostic builds with an on-screen toast
beat further static analysis (also how RELOAD3 and QLREC were cracked). Do not keep
state in `0x80006a40..0x80006abf`. MIDI twin sites of the patched blocks
(`0x400a4cb0` area) are still unpatched — audio-only coverage.

**Still open from earlier:** a report that the visited steps depend on which trigs are
on the grid, and that LEDs and audio disagree about position.

The position rule is the Analog Rytm's own commit arithmetic (`reference/AR_DIRECT_JUMP.md`,
incl. its §9 re-review). The mode deliberately does not persist — OFF on every power-on.
Handoff: `reference/handoffs/DIRECTJUMP_PHASE_HANDOFF.md` (the older
`DIRECTJUMP_SCALES_HANDOFF.md` is stale — its `CNTDN_TBL` section 5 was retired).
Detail: `NOTES.md` "Session 15" + "Session 21" + "Session 35", then "Session 60"–"Session 102".

### RELOAD FROM PROJECT — RELOAD3, FINAL (hardware-confirmed 2026-09-25)

`build_reload3.py`. Two direct chords: **`[PTN]` + `[TRACK n]`** (track sequence from
the card, Part untouched) and **`[BANK]` + `[TRACK n]`** (the same plus re-apply the
saved Part from RAM). No modal window, no keymap layer of ours, no timeout. It reloads
the *playing* pattern, never restarts the sequence or the metronome, and reports when
the job has actually finished — with a built-in check (`SEQ RELOAD LOST`) if the trigs
did not land.

The last open bug — the sequence intermittently not restored while the toast said
RELOADED — was root-caused on the unit with `build_reload3.py --diag`, whose toast prints
the request as armed and as read by the worker. The request bytes lived at
`0x80006a50-55`, a RAM block the unit overwrites, so the worker sometimes reloaded a
different (MIDI) track and then verified that. They now live in the patch's own cave, and
the build refuses any reference into `0x80006a40..0x80006abf`. The user reported every
issue resolved. **Do not keep state in that block** (`kb/caves.md`, CLAUDE.md,
NOTES "Session 98"). Deferred by the user: all-tracks and whole-bank variants. Handoff:
`reference/handoffs/RELOAD3_SEQFAIL_HANDOFF.md`. Spec and measurements:
`reference/RELOAD_REDESIGN.md`; detail: `NOTES.md` "Session 42"–"44" + "Session 47" +
"Session 80"–"Session 98".

### Blockers on the staged merge

Both are DIRECT-JUMP-vs-someone-else, and both are *builder assertion* conflicts
rather than byte conflicts (`reference/MERGE.md`):

- **B1** — DIRECT JUMP v4 asserts the `'ANDY'` block restore stays stock, while MUTE
  MODE must widen it. `DJ_MODE` needs relocating; `0x800000f8` is a candidate, not yet
  proven free.
- **B2** — DIRECT JUMP v4 writes the `[PTN]`-overlay `[YES]` record, while RELOAD3
  asserts that overlay is byte-for-byte stock.

`KYOTI_V1.0` (the seven finished mods) has neither problem and is buildable as soon as
the withdrawn builder is reconstructed from the allocation map.

### Side-chain compressor — closed, but keep these

Final and hardware-confirmed; no open work queued. Two things worth not relearning:

- **Not emulable:** the actual gain-reduction-from-`keybus` chain. `dsp_host` cannot
  run the stock compressor end to end, so the *response* is a hardware test;
  `emu_sc_dsp3.py` verifies the GAIN/FLT/LISTEN data transforms numerically against a
  reference, which is a different claim.
- **dsp56kEmu quirks**, worked around in `patch_sc_dsp3.asm` and all three HW-correct:
  `move x:(rN+d),a` reads wrong (use `,b`); a short `move #imm` to a data reg is
  left-aligned (use `cmp #>imm`); `asr` leaves bits in acc0 that `tst`/`cmp` see
  (normalise first).

Known-open and deliberately left alone: a very mild HP↔OFF pop (three hardware-tested
declick designs each failed or regressed — `NOTES.md` Session 76's trail; do not
re-attempt without a fundamentally different approach), and low-ATK/REL "graininess"
on a busy key (research-only, no fix attempted).
