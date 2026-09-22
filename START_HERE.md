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
| `reference/MERGE.md` | **combining every final-scoped mod into one firmware** — cave allocation, detour inventory, the `[YES]` trampoline, shared-state table. The combined build is **deferred and deliberately not buildable** until every feature is shippable; this doc is what it will be rebuilt from |
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
DIRECT JUMP pattern-change mode, and a DSP side-chain compressor (now
hardware-confirmed on MKI, single-core and cross-core both).
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
| **DIRECT JUMP** pattern-change mode | **Sessions 60-64** (full trail in NOTES.md): `V3` flashed and did nothing → **v4** fixed reachability, then threw a hardware `EXCEPTION VEC:04 ADDR 0x400BF0F2` after a few `[PTN]` presses **twice** before the real cause (a stack-discipline bug) was found and fixed in Session 64 — **confirmed crash-free on hardware in Session 66**. Combo toggling and the fast (~1-step) switch timing are both **HW-confirmed working** (and Session 69 additionally confirmed the fast-switch timing dynamically, under full-firmware emulation). **⚠️ STILL OPEN: with DIRECT JUMP ON, every manual pattern change starts the new pattern at step 1**, not the playhead position — two fix attempts on `dj_c`'s D7 write (Sessions 60/65) both failed on hardware despite passing isolated emulator checks each time. **Session 69 found the likely root cause dynamically (full-firmware route A, `tools/emu_directjump_dynamic.py`, no code changed yet)**: `dj_c`'s D7 multiplier `0x80006628` (commented "per-step tick multiplier, usually 1") is actually the project's own OWN Session-15-documented **loop-region start, normally 0** — so D7 evaluates to 0 regardless of the true resume step, dynamically confirmed (`0x80006604` written to literal `0x0` at a real switch despite a correct nonzero resume step). Independently, `dj_c` never writes `DAT_800065e4[]`/`DAT_800065f4[]` (per-track audio/MIDI step) at all, which Session 15's *original* 4-array design (before any build attempt) said the fix must cover — and this array was dynamically observed being reset to 0 by stock code on every switch, unopposed. Either bug alone reproduces the reported symptom. Not yet fixed or reflashed — full detail + the exact next steps: `NOTES.md` "Session 69". ⚠️ RELOAD2's `rl_yes` shares the dead-`0x4005e4c8`-while-`[PTN]`-held mechanism v1-v3 had — likely equally broken, not yet fixed. | `NOTES.md` "Session 15" + "Session 21" (+ continued) + **"Session 60"** → **"Session 69"** |
| **DSP side-chain compressor** | **HARDWARE CONFIRMED, SHIPPING — single-core AND cross-core (any of 8 tracks)** (see below). User considers this final for now; may want minor fine-tuning later. | `NOTES.md` "Session 17" (+ continued 1–8) → "Session 77" (×3) |
| **RELOAD FROM PROJECT** — per-pattern / per-track reload from the CF card, no transport stop | **Built, not flashed.** Two images: **`build_reload2.py`** (SEQ-focused, 3-item `TRK SEQ` / `PTN SEQ` / `PART + PTN SEQ`; opens on `TRK SEQ`) and `build_reload.py` (3-item `PTN SEQ` / `ALL PARTS` / `PARTS + PTN SEQ`). **`TRK SEQ`** (S47) = the one currently-addressed track (audio or MIDI, from `0x80000000`/`0x80000012`) — `G_KIND=3`, slices `slab+t*0x91a` (audio) / `slab+0x48d0+t*0x8b0` (MIDI) out of the parsed pattern. **`PTN SEQ`** = whole pattern, restores the live `slab+0x8e57` Part-link byte after the copy. **`PART + PTN SEQ`** (S47) = whole pattern incl. the link + `FUN_40009094(bank, savedPart)` + `0x80000003` — faithful "back to the card". **UX:** hold `[PTN]` ~0.5 s opens a sticky no-timeout picker, `[YES]` executes + closes, `[NO]` cancels; quick tap = SELECT PATTERN. 6 detours (`rl_ptn` / `rl_no` / `rl_yes` / `rl_arr_a` / `rl_arr_b` / `rl_job`). New scratch `G_TRK 0x80006a54` / `G_TMIDI 0x80006a55`. `rl_arm_trk` = the entry point for a future `[PTN]+[TRACK]` power move (chord is free; not built). **Session 80: fixed the dead-hook bug Session 60 flagged and never addressed** — `rl_yes`/`rl_no` sat on the identical `[PTN]`-held keymap-overlay mechanism that made `DIRECTJUMP_V3` do nothing on hardware (Session 60), so answering YES/NO while STILL physically holding `[PTN]` would very likely have done nothing. Fixed the same way DIRECT JUMP v4 was (write the handler straight into the overlay's dead/no-op press slot instead of relying on the detour alone) — `rl_yes_ptnheld`/`rl_no_ptnheld`, dynamically verified against the real stock layer-push code in the new `tools/emu_reload2_keymap.py` (**ALL GOOD**). The original `0x4005e4c8`/`0x4005e25c` detours are kept, unchanged — RELOAD2's picker is sticky/no-timeout by design, so answering it AFTER releasing `[PTN]` (the documented common case) still goes through them. **`emu_reload2.py` `--combo` / `--trk` / `--patched --trk` — all ALL GOOD** (the last two also needed a one-line fix to a pre-existing, unrelated test-timing bug in `emu_reload.py`'s `cmd_trk` — it sampled `G_KIND` before the async worker had run at all; confirmed via a stashed pre-fix rebuild that this predates this session; fixed alongside the keymap fix, same commit). HW-only: hold feel; arrow/`[TRACK]` reaching the picker; `FUN_4008cebc` vs a real card; `FUN_40009094` from the storage task while playing; both the "released PTN" and "still holding PTN" YES/NO gestures. `FLASHING.md` §4.7.

**Session 80 continued — HARDWARE REPORT, 2 more real bugs found + fixed:** flashed and tested; (1) holding `[PTN]` did nothing unless the sequencer was playing — the `RUNNING` gate was never actually load-bearing (`rl_job`'s own worker logic doesn't depend on it) and is now dropped, so these actions work whether the transport is running or stopped; (2) after ONE successful TRK SEQ reload, holding `[PTN]` again **stopped opening the picker at all, permanently, with no recovery** — root cause not conclusively pinned down (a static read of `FUN_40022778`, the storage-task job poster, found it always posts through ONE fixed scratch message buffer, `0x460bd912` — a real, plausible way for a request to get silently coalesced if pressed twice before the first is drained, but a full dynamic repro proved too expensive under the full-RTOS emulator to nail down this session — see `tools/diag_reload2_reopen.py`'s docstring for the detailed, instructive trail of dead ends). Fixed the actual DESIGN FLAW regardless of root cause: `rl_ptn` no longer gates opening the picker on `G_KIND` at all, so a stuck flag can never again permanently lock out the feature; the re-entrancy protection moved to `rl_yes_exec` (refuses to arm+post a new request while a previous one's `G_KIND` is unserviced, toasts "RELOAD BUSY" instead of silently doing nothing or corrupting the pending job). `emu_reload.py`'s `cmd_combo` covers both new behaviours; **`--combo` 18/18, `--trk` (untouched worker path) re-confirmed ALL GOOD.** **Deferred to a later session** (user: "we can work on #2 and #4 later"): a real multi-item list-style picker UI (single-popup redraw isn't good enough — user pointed at stock `[FUNC]+[UP]`'s own list menu as a UI/UX model to repurpose, not yet RE'd) and the reload's actual seamless-timing correctness (audible gap, sync drift, and a reset-to-step-1 that Session 42 already flagged and deferred as an MVP gap, never revisited — a real fix means porting DIRECT JUMP's own hard-won playhead-preservation design, comparable in depth to that multi-session saga). **Session 80 continued (2) — HARDWARE REPORT #2, gesture moved off `[PTN]`:** the `[PTN]`-hold entry fired only ~1 try in 5, `[PTN]` was triple-booked (stock chooser + DIRECT JUMP's `[PTN]+[YES]` + our hold), and our `rl_yes_ptnheld` poke **collided with the very slot DIRECT JUMP v4 pokes `dj_toggle` into**. Entry is now **`[BANK]` + `[YES]`** (user's suggestion, mirroring DIRECT JUMP): `[BANK]` press pushes its own overlay layer (`0x400cff14`, records `0x400cff34`) through the same `FUN_40031494` rebuild, and its YES record (`0x400d00ee`) has press = NULL — the identical dead slot, so `rl_bank_yes` is poked into `0x400d00f0`. **`rl_ptn` + both `[PTN]`-layer pokes are GONE and `[PTN]` is asserted byte-for-byte stock** — PTN+YES is DIRECT JUMP's alone, so this pair no longer needs `MERGE.md`'s `[YES]` trampoline. Also **fixed a regression this thread caused**: dropping the `RUNNING` gate made a stopped-transport reload start playback jerkily (the previous commit's claim that the gate "was never load-bearing" was an inference hardware falsified) — `rlj_setflag` now only arms `RELOAD_NOW` while running, else just `RDRAW` (**itself a hypothesis; the real start mechanism was never traced**). `--combo` **19/19**, `emu_reload2_keymap.py` retargeted to the BANK layer and **ALL GOOD** (real press → rebuild → slot resolves to `rl_bank_yes` → jsr really opens the picker). **STILL OPEN from hardware:** the list UI (found stock's 12-entry list table at `0x400beb72`; renderer not yet located), the ~1s pause-then-restart timing (lead: our worker rejoins stock's exit so the job's begin/done overlay lifecycle — which pops a keymap layer — still brackets every reload), arrow glitches (LEFT/RIGHT share handlers with DOWN/UP *and auto-repeat*), and near-constant "RELOAD BUSY" (which now **confirms** `G_KIND` really does get stuck). **Session 80 continued (3) — HARDWARE REPORT #3: `[BANK]`+`[YES]` CONFIRMED WORKING on the unit** ("most of the time"; the misses line up with the `RELOAD BUSY` stuck-`G_KIND` state, still unfixed). Also confirmed on hardware: `[PTN]` is stock again, a stopped transport is no longer started, and the `clr.l BANK_COMMIT` guess held (its comment is now HARDWARE-CONFIRMED, not INFERRED). **New fix — the SELECT BANK toast no longer flashes under the picker.** Stock opens SELECT BANK on `[BANK]` **press** (unlike `[PTN]`, which opens SELECT PATTERN on **release**), so every reload gesture showed it underneath. It is now deferred to release and swallowed entirely during a reload, mirroring stock `[PTN]`. This required correcting Session 80 continued (2)'s own claim that release pops the keymap layer — **it does not**: `0x4007b408` is the *window's* `onClose`, and the **window owns the layer** (measured: press shows window *then* pushes layer; release calls nothing and leaves it live; calling `0x4007b408` directly pops it and restores the YES slot). So the window cannot merely be suppressed — exactly one teardown must run on every path. 2 new detours (7 total): `rl_bank_press` `0x4007af42` suppresses only the `jsr FUN_40059f8c` and reserves the 4 arg slots (`lea -16(sp),sp`) the tail's own `lea 28(sp),sp` reclaims, leaving the layer push intact; `rl_bank_rel` `0x4007b3e0` picks one of three routes — trig-already-picked (its own "bank N" toast owns teardown), picker-open (swallow + teardown directly, stock `[PTN]`'s shape), or plain tap (show the window here with stock's own args). New `tools/diag_bank_window.py` **ALL GOOD** on stock *and* patched, including a press-side **stack-balance** check; `--combo` **19/19**, keymap **ALL GOOD**. **KB fixed** (`memory-map.md` `0x46c7d8de`): hold delay and repeat interval are two independent fields (`[22..23]`/`[24..25]`), PTN is keycode **`0x2e`** with delay `0x1e` (the old "0 for trig/track/PTN/BANK" was wrong), and only the arrows repeat — UP+RIGHT share `0x4004b970`, DOWN+LEFT share `0x400491a0` *and auto-repeat*, the likely mechanism behind the arrow glitches. **RETRACTED**: "(2)"'s claim that `FUN_400238a4` has zero xrefs was a scan artifact — it is called by **`bsr.w`** from `0x400239a2`; any xref sweep here must cover absolute, pc-relative EA, short branch *and* `bsr.w`. **Session 80 continued (4) — HARDWARE CONFIRMED "(3)" ("all of the changes seem to be operating cleanly"), then ROOT-CAUSED THE ~1 s STALL + SEQUENCER RESTART (issue #2).** The type-0x14 job **is** stock's RELOAD BANK, and its doneFn re-reads **all 16 patterns of the bank off the card** after our slice copy, every time — the stall, the restart, and the reason TRK SEQ was only *nominally* per-track (the whole bank reverted behind it). **Our own suite had been printing `deser_seen=True` for sessions**: `cmd_trk` hooks the deserialiser, calls it "residual" and *stops the emulator there*, so nothing had ever looked at the tail. Found with the new `tools/diag_reload2_deser.py` (traces the real storage task past that point). **Two wrong turns, both caught by measurement:** (1) detouring the obvious `jsr 0x40080844` in doneFn changed **nothing** — the counters showed it running *twice*, the reload being in the second pair off the SUCCESS path (`0x40023c62` → `bsr.w 0x40023b68`); "numerically near `0x40080844`" is not "inside" it, the same error as the `FUN_400238a4` retraction above. (2) Suppressing the reload **alone made the feature inaudible** — our worker writes only the cold blob, and stock's reload was what refilled the live playback cache `0x1001614e`. Fix = `rl_done` @ `0x40023c62` (one-shot flag `rl_own`, so a genuine stock RELOAD BANK is never suppressed) jumping to doneFn's epilogue, **plus** `rl_job` calling stock's own **`FUN_4000faf0(bank)`** ("make bank current", RAM→RAM, a few ms not ~1 s) to refresh the live cache. Now: no deserialiser, no 16 parses, layer balance 0, **cold blob AND live copy both reverted**; `--trk` **ALL GOOD with `deser_seen=False`** and every per-track precision check still passing — TRK SEQ is genuinely per-track at last. 8 detours, 1364 B. **Two hypotheses DIED — do not re-run them:** keymap-layer imbalance is NOT why `[YES]` goes dead (push/pop balance measured 0), and a single clean reload does NOT reproduce the stuck `G_KIND` (reads 0 every time), so `RELOAD BUSY` needs a different trigger entirely. **Session 80 continued (5) — "(4)" FAILED ON HARDWARE AND IS BACKED OUT.** Flashed, and it made the unit materially worse: `[BANK]`+`[YES]` "hardly ever executes", `[YES]` "almost always" gives `RELOAD BUSY`, and — a **stock-feature regression** — **stock `[BANK]` single-press stops working entirely after a few reload attempts**. The *timeline* identified the culprit, not reasoning: "(3)" was already hardware-confirmed clean, and the next flash contained only "(4)"'s two changes (`rl_done` + the `FUN_4000faf0` live-refresh, which stand or fall together since the refresh exists only to replace what `rl_done` suppresses). Both are backed out — `rl_done`/`rl_own` behind **`.ifdef RL_DONE`** (`--defsym RL_DONE=1` to resurrect), the `LIVE_REFRESH` call commented out. **The default build is 1306 B, byte-for-byte the confirmed-good "(3)" image** (only `.equ`s and the guarded block differ from `f729df3`); `--trk`/`--combo`/keymap/bank-window all ALL GOOD again. **Why the emulator passed a build hardware rejects:** the tests measured ONE reload, and on one reload everything genuinely is correct (layer balance 0, `G_KIND` 0, both copies reverted). The hardware phrase "after a few times" is the finding — state accumulates across repeated reloads and nothing here drives more than one. Leading (UNPROVEN) explanation: skipping `0x40023b68` drops job/window bookkeeping, and a wedged popup state would explain all three symptoms at once (`rl_bank_yes` bails on `POPUP != 0`; a wedged window system means the deferred SELECT BANK never draws; a wedged job path means `G_KIND` is never consumed). **Killed this round:** layer-stack imbalance (new `--stress` mode drives 5 taps + 3 reload gestures on stock *and* patched — depth and the BANK slot never drift; pushing an already-linked layer is idempotent) and `FUN_4000faf0` clobbering our scratch (all seven of its copy destinations decoded; none touch `0x80006a50..55`). **STILL TRUE from "(4)":** the type-0x14 job IS stock's RELOAD BANK and its doneFn really does re-read all 16 patterns off the card after our slice — issue #2's root cause stands, only the fix is retracted. **GATE for any retry: a multi-reload test (3–5 consecutive) asserting `G_KIND`, `POPUP`, layer depth and the BANK/YES dispatch slots all return to baseline after each. Single-reload green is now known to be worthless evidence here.** | `NOTES.md` "Session 42"–"44" + "Session 47" + "Session 80" + "Session 80 continued" (+ "(2)"–"(5)") |
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
| `build_sidechain3.py` → `SIDECHAIN3_CROSS.*` | **CROSS-CORE SIDECHAIN — HARDWARE CONFIRMED, SHIPPING (2026-09-20, Session 77 continued again).** KEY now picks ANY of the 8 tracks, flat (T1..T8, widened from "this track's own 4 same-core siblings"), list-style UI matching LFO TRIG; KEY GAIN (declick-smoothed), KEY FLT (one-pole LP/HP/OFF, declicked), SC LISTEN / MON, over a donated SPRING REVERB (1063-word P budget/payload, ~388 used). Cross-core reach via a per-core generation counter + shared-window publish/foreign-read (`Y:0x30000-0x3FFFF`, see "Cross-core SIDECHAIN" below). `patch_sc_dsp3.asm` (DSP) + `patch_sidechain.s` (ColdFire menu/formatters, incl. the `key_list_fix` trampoline) + `sc_tables.py` (coefficient tables) + `build_sidechain3.py` (output renamed `SIDECHAIN3`→`SIDECHAIN3_CROSS` since the value semantics genuinely changed). | `emu_sc_dsp3.py` / `emu_sc_dsp3_xcore.py` / `emu_sc_dsp3_moncommit.py` (plain + `--patched`) all clean, plus a real dual-core run under `tools/dsp56300_xcore`'s `dsp_host_xcore` (lock-step + `-skew` fuzz); **user confirms it sounds and looks good on real MKI hardware, cross-core included** |

**Known-open, deliberately left alone**: a very mild HP↔OFF pop remains (three separate hardware-tested declick designs have each failed or regressed — see `NOTES.md` Session 76's trail — do not re-attempt without a fundamentally different approach); low-ATK/REL "graininess" on a busy key (research-only so far, no fix attempted, user may revisit).

**Cross-core SIDECHAIN — DONE, HARDWARE CONFIRMED (Session 77, ×3).** KEY now picks *any* of the 8 tracks, not just this track's 4 same-core siblings. Leaned heavily on **octabam** (`refs/octabam/`)'s own shipped cross-core mechanism (`refs/octabam/docs/effects/XBUS.md` + `refs/octabam/CLAUDE.md`'s traps list) for the race-safety shape (four rotating buffers, reader two behind the writer) — adapted rather than ported wholesale, since this feature needed no accumulator/housekeeper-election machinery XBUS's own bus does. Full design + implementation + validation trail in `NOTES.md`'s three "Session 77" entries. **User: consider this build final for now** — minor fine-tuning may follow, no open work is queued.

**Session 77 (+ continued, + continued again): HARDWARE CONFIRMED, SHIPPING.**
Track↔payload mapping settled (payload A = tracks 5–8, payload B = tracks
1–4, three independent confirmations). Cross-core KEY is a raw-audio-relay
(user's call — full parity with same-core KEY). Dual-core emulator toolchain
built (`tools/dsp56300_xcore/`, reproducible via its own `setup.sh`) and used
to validate the shared-window publish/generation-counter/foreign-core-read
mechanism (`tools/patch_sc_dsp3.asm`'s `sctap`/`scdet`) both numerically
(`tools/emu_sc_dsp3_xcore.py`) and under a real dual-core run (both cores'
generation counters agree after 50 blocks, lock-step and under `-skew`
fuzzing). KEY widened 0→8 flat on the ColdFire side (`tools/patch_sidechain.s`,
`tools/build_sidechain3.py`, descriptor count 5→9). Built and flashed
`out/OCTATRACK_OS1.40C_SIDECHAIN3_CROSS.syx` — user: **"seems to be working
well"** on the MKI, no crash, no regression, cross-core KEY audibly correct.
**The compressor can now key off any of the 8 tracks, not just this track's
own 4 same-core siblings — this settles the SIDECHAIN thread. Consider it
final for now** (the user may want minor fine-tuning later, no open work is
queued against it). Full trail, including two real bugs fixed along the way
and a debugging detour worth knowing about before touching this thread
again: `NOTES.md`'s three "Session 77..." entries, right after the Session
76 handoff brief.

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
2. ~~Flash `SIDECHAIN2`~~ / ~~flash `SIDECHAIN3`~~ / ~~flash `SIDECHAIN3_CROSS`~~ —
   **done, both single-core AND cross-core SIDECHAIN are HARDWARE CONFIRMED and
   shipping as of 2026-09-20** (see "Side-chain compressor" above). User considers
   this build final for now; no further work queued against this thread.
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

**Combined firmware — deferred, deliberately not buildable.** There is no single
"everything" image and no `build_merged.py`: shipping one while DIRECT JUMP, RELOAD
FROM PROJECT and the part-change carryover fix are unfinished would quietly include
them. Flash the per-feature builds one at a time (`BUILD_KYOTI.md`, `FLASHING.md`).
The full allocation map, detour inventory and the `[YES]`-trampoline design are kept
current in `reference/MERGE.md`, which is what the combined build will be
reconstructed from when the remaining work lands.

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
but should not be flashed again.** The withdrawn merge tooling still wired `DJ_V3` (the old, dead
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
`0x800065b8` poke. NEXT: an HW pass once the MKI is back. (`patch_partreapply` was checked against
`MERGE.md` and is orthogonal to every other mod — no shared globals, no detour
collisions — so folding it into a combined build will be mechanical whenever that
build is revived; the combined build itself is deferred and not currently buildable.) All the
emulator tooling from this session is safely in `tools/` (not scratchpad) —
`emu_partswitch.py`, `diff_flex_static.py`, `check_reccache_causation.py`,
`scan_parts.py`, `patch_partreapply.s`, `build_partreapply.py`.

**Backlog (scoped, Phase 1 tooling next):** auto-remove a trigless lock once a LIVE-REC
`[NO]`+knob erase clears its last p-lock. Data model is mapped to the step-mask level
(`kb/file-format.md`); the remaining RE is locating the erase handler — drive it in
`emu_rtos` and `--watch-mem` the sequenced-data RAM. Full brief: `NOTES.md` "Session 13"
+ "Session 20" + "Session 23".

**RELOAD FROM PROJECT — BUILT** (Sessions 42–44, 47, 80), see the frontier row above.
Two images: `build_reload2.py` (SEQ-focused 3-item — `TRK SEQ` / `PTN SEQ` /
`PART + PTN SEQ`) and `build_reload.py` (`PTN SEQ` / `ALL PARTS` / `PARTS + PTN SEQ`).
Session 44 reworked the UX to OT-native: **hold `[PTN]`** opens a sticky picker,
**no timeout**, arrows + `[YES]`/`[NO]`. Session 80 fixed a dead-hook bug in
`build_reload2.py` only (Session 60 flagged it, never addressed — see the frontier
row above); `build_reload.py` (the 3-item `PTN SEQ`/`ALL PARTS`/`PARTS + PTN SEQ`
sibling) shares the identical `rl_yes`/`0x4005e4c8` mechanism in `patch_reload.s`
and has **NOT** received the same fix yet — treat it as equally likely affected
until it does. Both emu-clean on the paths checked so far, neither flashed.
Brief: `NOTES.md` "Session 42"–"44" + "Session 47" + "Session 80".
