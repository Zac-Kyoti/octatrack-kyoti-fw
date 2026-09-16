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
2026-09-01). Published as <https://github.com/Zac-Kyoti/octatrack-kyoti-fw>; began
as a fork of `mxldyn/octamax`, derived from it since. Remotes: `origin` = the
published repo, `upstream` = mxldyn (fetch only, for `whatsnew.py`).

## 1. Read order for a new chat

1. **This file** — §6 says which branch the current work is on (`main` vs `wip`).
   Check out that branch before reading further; each branch's `START_HERE.md` / `NOTES.md`
   reflects its own state.
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
| `reference/MERGE.md` | **combining every final-scoped mod into one firmware** — cave allocation, detour inventory, the `[YES]` trampoline, shared-state table. `tools/build_merged.py` + `tools/emu_merged.py`. No-flash prep (Session 45) |
| `README.md` | what the firmware is, the feature list + per-feature HW status, repo layout, lineage |
| `BUILD_KYOTI.md` | roll-your-own build guide (every `build_*.py`, prerequisites, the reproducible patch) |
| `COVERAGE.md` | what firmware subsystems are mapped vs untouched; the DSP-is-a-separate-blob caveat |
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

Two branches. **`main`** is the stable line: only hardware-tested build tooling,
plus the shared knowledge base. **`wip`** (this) is the active
frontier — everything not yet on hardware: the DT and solo mute modes, a
DIRECT JUMP pattern-change mode, and an in-progress DSP side-chain compressor.
Octamax's current state is tracked via `refs/octamax/` (see `reference/EXTERNAL_RESEARCH.md`),
not a mirrored branch.

| Thread | State |
|---|---|
| **Bug 1** — Plays-Free MIDI manual-trig stall | **FIXED + HW-confirmed on MKI.** `tools/patch_trigscale.s`, always-on. In every build. |
| **Bug 2** — MIDI LFO SETUP knobs send CC on the twin audio channel | Emulation says **likely already fixed in 1.40C**; awaiting HW confirmation. `tools/emu_lfocc.py`. |
| **MUTE MODE** PERSONALIZE toggle (`main`) | `tools/patch_mutemode.s`, values `OT / OT+FX`. Menu surgery HW-confirmed (Session 10). |
| ↳ **OT+FX** soft mute — dry cuts fast+clean, FX inserts ring (`main`) | `patch_softmute.s` **V6b** (V6 mechanism + the Session-10 gate/frame fixes). **Flashed on MKI, works.** `python3 tools/build_mutemode.py`. |
| ↳ MUTE MODE **now persists across power cycle** (`main`, Session 19) | `0x800000xx` is volatile; setter now also writes the `'ANDY'` battery-SRAM shadow `0x100fff6c` and the build extends the block restore `0x64`→`0x70` at 3 sites. Emu-verified, **not yet flashed.** From octamax `c78ff70`. |
| ↳ **OT+FX for SOLO** (non-soloed tracks keep FX tails) | `patch_softmute.s` **V7**, **`wip` only** — emulator-verified (`emu_solo.py`), never flashed. |
| ↳ **DT** (Digitakt-style pure sequencer mute) | **`wip` only** — emulator-verified (`emu_dt.py`, `build_mutemode_dt.py`), never flashed. |
| Maxolydian's octamax behaviour mods (branding, no BANK/PTN countdown, lazy Part transitions, arp key-scales, LED dirty indicators) | **Not in any OT Kyoti FW build.** Patch sources kept for RE cross-reference in `tools/attic/`; design notes in `reference/upstream-notes.md`; credit in `CREDITS.md`. |
| **External-RE knowledge base** (`main`, Sessions 16 / 18 / 20 — merged into `wip`) | `reference/kb/*.md` — address-keyed distillate of the 6 prior-art repos (octabam DSP map + kernel/RTOS + step-mask map, OctaLib file formats, octa-bt-pt + octabam descriptor table, the bank-file p-lock region, ems-octakit's `abi.inc` ~500-address map → `kb/octakit-abi.md`, the keymap/keycodes). `python3 tools/refs/sync.py` populates the `refs/` cache; `reference/EXTERNAL_RESEARCH.md` is the index. |

Build outputs on `main` (all `140C_KYOTI`, all carry the Bug-1 fix):
- `build_trigscale_only.py` → `out/OCTATRACK_*PLAYSFREEFIX.*` — Bug-1 fix only, version stays `1.40C`.
- `build_mutemode.py` → `out/OCTATRACK_*MUTEMODE.*` — Bug-1 fix + MUTE MODE (`OT` / `OT+FX`). **The flashed line.**
- `build_softmute.py` → `out/OCTATRACK_*SOFTMUTE_PFFIX.*` — Bug-1 fix + V6b soft mute ALWAYS ON (no menu).

---

## 6. Current frontier — UPDATE THIS EACH SESSION

**As of 2026-09-06. You are on `wip`** — the active branch. `main` is merged
in through Session 20: the external-RE knowledge base (`reference/kb/*.md` — run
`tools/refs/sync.py` to populate the `refs/` cache), the kernel/RTOS + step-mask maps,
the keymap/keycodes, and the **MUTE MODE `'ANDY'`-shadow persistence** (Session 19; DIRECT
JUMP already uses it, DT still needs it — see below). Everything here is emulator-verified,
**nothing flashed**.


| thread | state | detail |
|---|---|---|
| **DT** mute mode | built, `emu_dt.py` clean · `build_mutemode_dt.py`. Persists across a power cycle (Session 22 folded in the `'ANDY'` shadow — byte-identical to `build_mutemode.py`). | `NOTES.md` "Session 12" |
| **OT+FX → SOLO** (softmute V7) | built, `emu_solo.py` clean · `build_mutemode.py` on this branch | `NOTES.md` "Session 11" |
| **4th MUTE MODE** — instant cut + FX tails + resume-at-playhead | RE'd, not built; gated on the same HW unknown as DT | `NOTES.md` "Session 14" |
| **DIRECT JUMP** pattern-change mode | **`DIRECTJUMP_V3` flashed 2026-09-14/15 — DID NOTHING** (combo dead, Session 60: stock `[PTN]`-held UI overlay NULLs the `[YES]` dispatch slot). **v4 flashed 2026-09-15 — combo reachable but "sort of works"** (Session 61: toast didn't close on `[PTN]` release + `dj_c` — shared by every DJ build since Session 15 — clobbered D7, a tick count two per-track phase loops need right after the hook, breaking playhead-preservation; both fixed). **That v4 then threw a real hardware EXCEPTION (VEC:04, ADDR 0x400BF0F2) after a few `[PTN]` presses** (Session 62: the toast-close hook was calling `NOTIFY_CLOSE` from inside another function mid-teardown of the same list our layer lives on — rebuilt to call nothing at all, just arms the countdown stock's own safe per-frame tick already reads). Every fix dynamically verified against the *real* stock layer-push/dispatch/release code (`tools/emu_directjump_v4.py`), not hand-built stubs. **Not yet reflashed** — a plain power cycle recovers a unit that hit the exception. ⚠️ RELOAD2's `rl_yes` shares the same dead `0x4005e4c8` hook — likely equally broken, not yet fixed. | `NOTES.md` "Session 15" + "Session 21" (+ continued) + **"Session 60"** + **"Session 61"** + **"Session 62"** |
| **DSP side-chain compressor** | see below | `NOTES.md` "Session 17" (+ continued 1–8) |
| **RELOAD FROM PROJECT** — per-pattern / per-track reload from the CF card, no transport stop | **Built, not flashed.** Two images: **`build_reload2.py`** (SEQ-focused, 3-item `TRK SEQ` / `PTN SEQ` / `PART + PTN SEQ`; opens on `TRK SEQ`) and `build_reload.py` (3-item `PTN SEQ` / `ALL PARTS` / `PARTS + PTN SEQ`). **`TRK SEQ`** (S47) = the one currently-addressed track (audio or MIDI, from `0x80000000`/`0x80000012`) — `G_KIND=3`, slices `slab+t*0x91a` (audio) / `slab+0x48d0+t*0x8b0` (MIDI) out of the parsed pattern. **`PTN SEQ`** = whole pattern, restores the live `slab+0x8e57` Part-link byte after the copy. **`PART + PTN SEQ`** (S47) = whole pattern incl. the link + `FUN_40009094(bank, savedPart)` + `0x80000003` — faithful "back to the card". **UX:** hold `[PTN]` ~0.5 s opens a sticky no-timeout picker, `[YES]` executes + closes, `[NO]` cancels; quick tap = SELECT PATTERN. 6 detours (`rl_ptn` / `rl_no` / `rl_yes` / `rl_arr_a` / `rl_arr_b` / `rl_job`). New scratch `G_TRK 0x80006a54` / `G_TMIDI 0x80006a55`. `rl_arm_trk` = the entry point for a future `[PTN]+[TRACK]` power move (chord is free; not built). **`emu_reload2.py` `--combo` + `--trk` ALL GOOD**; `--patched` = the whole-pattern worker. HW-only: hold feel; arrow/`[TRACK]` reaching the picker; `FUN_4008cebc` vs a real card; `FUN_40009094` from the storage task while playing. `FLASHING.md` §4.7. | `NOTES.md` "Session 42"–"44" + "Session 47" |
| **QUANTIZE LIVE REC** — surface the PERSONALIZE row to the panel | **Built, not flashed (Session 46).** **Hold `[REC]`, tap `[PLAY]` twice** → toggles `QUANTIZE LIVE REC` (`0x800000ac`, the all-or-nothing live-rec quantize, *not* the per-track TRIG QUANT). Persistent "QUANT LIVE REC ON/OFF" toast shows while `[REC]` is held, clears on release (no timer). No menu surgery — the variable + its power-cycle persistence are stock (`0x800000ac` is inside the `0x64` ANDY span); we mirror the setter (word + shadow `0x100fff3c` + `jsr FUN_4001f23c`). 2 detours: `qlr_play` `0x40061778` / `qlr_recrel` `0x4004883a`. `patch_qlrec.s` + `build_qlrec.py` + `emu_qlrec.py` **ALL GOOD**. 247 B vs stock. HW-only: eyeball the toast, the feel of odd-press swallowing. | `NOTES.md` "Session 46" |

The shared HW unknown for **DT** and the **4th mode**: does the DSP keep advancing a
0-amp / envelope-riding voice while the frame level words flow untouched? Flashing DT
settles it. (`FUN_40004db8` is downstream of the voice updater, so it should.)

### Side-chain compressor — where it stands

External **KEY**-track input for the DynamiX COMPRESSOR. It's a DSP job, not ColdFire —
the compressor is 180 DSP words (`P:0x01aa4` payload A / `P:0x01864` B; id `0x18`), the
ColdFire never sees audio. octabam's DSP load-map + module table transfer to our image
verbatim (SHA `164f3122…`, MKI==MKII). COMPRESSOR fully reversed: param map `r6+$0..5` =
ATK/REL/THRS/RAT/GAIN/MIX, `+$c` = RMS. **Sidechain tap point:** the detector reads
`x:(r0)+` @`0x1ab3`; the dry/wet path re-anchors via `n6`, so redirecting *only* the
detector to a shared-Y `keybus` is dry-signal-safe. Publish tap = `func_0004a7` (`P:0x004a7`),
copy `X:0` → `keybus[track]`. `keybus` = abs-Y `0x800–0xC00`, quad-buffered, same-core only.
DSP56300 toolchain (`dsp_asm` + `dsp_host`) built in `vendor/` (gitignored; scratchpad
`build_dsp_asm.sh`).

| build | contents | status |
|---|---|---|
| `build_sidechain.py` → `SIDECHAIN.*` | `KEY` menu param only (COMPRESSOR pg2, descriptor slot 8), DSP inert | `emu_sidechain.py` clean |
| `build_sidechain2.py` → `SIDECHAIN2.*` | + 37-word DSP hooks (`patch_sc_dsp.asm` = `sctap`+`scdet`) over a **donated SPATIALIZER** (also pulled from the FX1/FX2 choosers + ID2POS) | `emu_sc_dsp.py --patched` + `emu_sidechain.py` clean |
| `build_sidechain3.py` → `SIDECHAIN3.*` | **step 3 (Session 36):** = step 2 + `KEY GAIN` scaler + `KEY FLT` 2-pole Chamberlin SVF (`patch_sc_dsp3.asm`) + `SC LISTEN` via a 3rd hook `sctail`. `sc_tables.py` = shared 16-word gain / 32-word f tables | `emu_sc_dsp3.py` (isolation + `--patched` end-to-end) clean vs a Python SVF ref; `emu_sidechain.py` formatters clean |

Not emulable: the actual gain-reduction-from-`keybus` chain — `dsp_host` can't run the stock
compressor end-to-end, so it's a hardware test. (`emu_sc_dsp3.py` numerically verifies the
new GAIN/FLT/LISTEN data transforms against a reference; the compressor's *response* to them
is HW.) dsp56kEmu quirks worked around in `patch_sc_dsp3.asm`: `move x:(rN+d),a` reads wrong
(use `,b`); short `move #imm` to data regs is left-aligned (use `cmp #>imm`); `asr` leaves
bits in acc0 that `tst`/`cmp` see (normalise first). All three fixes are HW-correct.

### Blocker & NEXT

The user is away from the MKI — build + emulate only. The stack waits on one hardware
session, in order:

1. **Flash DT** — settles the shared "does the DSP keep advancing a 0-amp voice?" unknown
   (DT + the 4th mute mode both rest on it). Checklist: `NOTES.md` "Session 12 → NEXT".
2. **Flash `SIDECHAIN2`** — HW test plan in `NOTES.md` "Session 17 continued (8)".
3. If (2) good → **flash `SIDECHAIN3`** (step 3: `KEY GAIN` + `KEY FLT` SVF + `SC LISTEN`,
   built Session 36). HW test additions in `NOTES.md` "Session 36"; tune `sc_tables.py`
   (gain law / filter range / q) after a listen.
4. **Flash `DIRECTJUMP_V4`** (`build_directjump_v4.py` — v1/v2/v3 are DEAD ON HARDWARE,
   Session 60: the `[PTN]`-held stock overlay NULLs `[YES]`'s dispatch slot the whole time
   it's held, so their `0x4005e4c8` detour never runs; v4 fixes it by writing `dj_toggle`
   into that overlay's own `[YES]` slot instead) — the `[PTN]`+`[YES]` toggle now actually
   reaches dj_toggle + the 5 sequencer-hook unknowns + does the toast read cleanly /
   `DJ_TOAST_DUR` feel right. HW test lists: `NOTES.md` "Session 15 continued" +
   "Session 21 continued" + "Session 45" + "Session 60".
5. Then: build the 4th mute mode; OT+FX-solo checklist (`NOTES.md` "Session 11 → NEXT").

**Also no-flash:** all three MUTE MODE builds + DIRECT JUMP now carry the `'ANDY'`-shadow
persistence (Session 22). **`tools/emu_rtos.py`** wraps octabam's full-firmware emulator
(runs the real scheduler/tasks/CF/LOAD-PROJECT against our image — M6a/M6b verified,
Session 23) — the tool for the p-lock backlog below.

**Combined firmware (Session 45, no-flash):** `tools/build_merged.py` composes all five
final-scoped mods (Bug-1 + MUTE MODE + **DIRECT JUMP v3** + SIDECHAIN3 + RELOAD2) into
`out/OCTATRACK_OS1.40C_KYOTI_ALL.{syx,bin}` — caves auto-packed, the one shared handler
(`[YES]` @ `0x4005e4c8`) resolved by a trampoline (RELOAD2 outer → `dj_toggle` chain,
`patch_reload2.s` `.ifdef MERGE`). `tools/emu_merged.py` ALL GOOD. **Not flashed** —
flash the per-feature builds first (order below), then the combined image. Full map +
open decisions: `reference/MERGE.md`.

**DIRECT JUMP v3 (Session 45):** `build_directjump_v3.py` / `--defsym DJ_V3=1` — the
confirmation toast is `FUN_4005a2b8(text, dur)`, the OS's own self-timing notification
(what `patch_reload2` uses, = ems-octakit `GK_STOCK_NOTIFICATION_SHOW`). No countdown
boxes (v1), no `0x400522ca` splice (v2), no shared popup handle. `emu_directjump_v3.py`
ALL GOOD; dj_a/b/c byte-identical to v1. **Flashed 2026-09-14/15 — did nothing** (the
combo never reaches `0x4005e4c8` at all while `[PTN]` is held; see v4 below).

**DIRECT JUMP v4 (Session 60) — the fix, keeps v3's toast:**
`build_directjump_v4.py` / `--defsym DJ_V3=1,DJ_KEYMAP=1` — drops the `0x4005e4c8`
detour entirely and instead pokes `dj_toggle`'s address into the stock `[PTN]`-held
overlay layer's own (normally NULL) `[YES]` record, so the layer's own rebuild wires
the runtime dispatch straight to it. `tools/emu_directjump_v4.py` runs the *real* stock
`FUN_4005a044`/layer-push/rebuild code (not a hand-built stub) and confirms: the dead
slot on the v3 image (reproducing the HW failure), the live slot → `dj_toggle` on v4,
and that `jsr`-ing that live slot actually runs the toggle end to end (re-checksum +
toast fire + `DJ_MODE` flips). **Now the preferred build — v1/v2/v3 kept for reference
but should not be flashed again.** `build_merged.py` still wires `DJ_V3` (the old, dead
combo) — needs bumping to `DJ_KEYMAP` before the merge is touched again (not done yet;
RELOAD2's `rl_yes` likely needs the identical fix first, since it shares the same
detour).

**"Part params carry over after a pattern→Part change" (Session 49) — FIXED, built,
emu-validated, NOT flashed:** three Elektronauts reports, one family — a pattern change
that links a different Part runs only a *light* re-apply (`sys` handler `0x400621a6`:
`FUN_400972fc`×8 + `FUN_40009e00` + redraws), skipping the full `FUN_40009094` / kind-4
a manual PART select runs. Root cause and fix design: `NOTES.md` "Session 49 — HANDOFF".
Root cause for #1 specifically: `FUN_400972fc`'s `oldType==4 (PICKUP) && newType!=4`
branch never rebinds the voice slot; PICKUP and FLEX share one sample arena so the stale
slot keeps reading as valid — the FLEX track sounds the old pickup loop. **Fix built:**
`tools/patch_partreapply.s` + `tools/build_partreapply.py` → `out/mainos_partreapply.bin`
— detours `0x40062216` (right after the `FUN_400972fc`×8 loop) to: always re-copy the
recorder record from the new Part (closes #2/#3), set the `0x8000184c` kill-bit on the
exact PICKUP→non-PICKUP transition (closes #1 — no longer "unverified", see below),
retrigger the scene morph once, and call Elektron's own full `FUN_40009094` only when
the transport is stopped (respects the frame-builder's existing lazy catch-up while
playing, doesn't race it). **Validated**: clean A/B via
`tools/emu_partswitch.py --repro` (stock, reproduces) vs `--repro --patched` (fixed) —
kill bitmap `0x00→0x01`, recorder cache stale marker → Part 1's real record, bonus fix
to `TRK_PART`/`TRK_BANK` consistency across all 8 tracks. Along the way, fixed a
pre-existing harness bug in `emu_partswitch.py`: `press_key_live(KEY_STOP)` never
actually stopped the transport, which made the first validation pass look like a
no-op on both stock and patched images — replaced with a direct
`0x800065b8` poke. NEXT: add `patch_partreapply` to `build_merged.py` (checked against
`MERGE.md` — orthogonal to all seven existing mods, no shared globals or detour
collisions, should be mechanical), then an HW pass once the MKI is back. All the
emulator tooling from this session is safely in `tools/` (not scratchpad) —
`emu_partswitch.py`, `diff_flex_static.py`, `check_reccache_causation.py`,
`scan_parts.py`, `patch_partreapply.s`, `build_partreapply.py`.

**Backlog (scoped, Phase 1 tooling next):** auto-remove a trigless lock once a LIVE-REC
`[NO]`+knob erase clears its last p-lock. Data model is mapped to the step-mask level
(`kb/file-format.md`); the remaining RE is locating the erase handler — drive it in
`emu_rtos` and `--watch-mem` the sequenced-data RAM. Full brief: `NOTES.md` "Session 13"
+ "Session 20" + "Session 23".

**RELOAD FROM PROJECT — BUILT** (Sessions 42–44, 47), see the frontier row above.
Two images: `build_reload2.py` (SEQ-focused 3-item — `TRK SEQ` / `PTN SEQ` /
`PART + PTN SEQ`) and `build_reload.py` (`PTN SEQ` / `ALL PARTS` / `PARTS + PTN SEQ`).
Session 44 reworked the UX to OT-native: **hold `[PTN]`** opens a sticky picker,
**no timeout**, arrows + `[YES]`/`[NO]`. Both emu-clean, neither flashed.
Brief: `NOTES.md` "Session 42"–"44" + "Session 47".
