# Roll your own OT Kyoti FW

This builds a **modified Octatrack OS 1.40C** from *your own* copy of the official
firmware. No Elektron binary is included here or produced for anyone but you; the
build is byte-for-byte reproducible from the stock file.

> **Read [`FLASHING.md`](FLASHING.md) before you flash anything.** Flashing
> non-official firmware risks the warranty and can leave the unit needing the
> bootloader recovery path. Static analysis is harmless; writing to hardware is
> not. The author runs these on an Octatrack **MKI** he owns.

> **Branch:** **`main`** carries six finished, hardware-confirmed features — the
> Bug-1 manual-trig fix (`build_trigscale_only.py`), the Bug-2 pattern-LED fix
> (`build_pattern_led.py`), **MUTE MODE** (`build_mutemode_dt.py`, all four modes),
> **QUANTIZE LIVE REC** (`build_qlrec.py`), the **SIDE-CHAIN COMPRESSOR**
> (`build_sidechain3.py`) and **trigless-lock auto-remove** (`build_triglock.py`)
> — all flashed, working, no open issues. `wip` is the frontier: those six plus a
> **seventh finished one**, the **part-change carryover fix**
> (`build_partreapply.py`, hardware-confirmed 2026-09-22/23 but not yet promoted to
> `main`), the **Bugbuild** composites (`build_bugbuilds.py`), and the two threads
> still in progress. **Still active work-in-progress:** **DIRECT JUMP**
> (`build_directjump_v4.py` — hardware-confirmed at 1x track and master scales; the
> non-1x fix is built and emulator-validated but not yet flashed). **RELOAD FROM PROJECT**
> (`build_reload3.py`) is finished and hardware-confirmed as of 2026-09-25. See *Hardware-test status* below for exact
> per-item state. Earlier, superseded builds of these same features are no longer
> listed here — they're historical only; see `NOTES.md`.

## What you get

| build command | version string | contents |
|---|---|---|
| `python3 tools/build_trigscale_only.py` | `1.40C` (unchanged) | **Bug 1 fix only** — the Plays-Free MIDI manual-trig stall — on otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_pattern_led.py` | `1.40C` (unchanged) | **Bug 2 fix only** — a pattern whose only content is p-locks (MIDI-track locks, or audio trigless locks) no longer reads as an empty slot; its grid LED lights under `[PTN]`. On otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_qlrec.py [VERSTR] [LIVE_DUR]` | `140C_KYOTI` | Bug 1 fix + **QUANTIZE LIVE REC** front-panel toggle, **toast-gated**: hold `[REC]` + tap `[PLAY]` → a toast shows the current PERSONALIZE value; tap `[PLAY]` again *while that toast is up* → the value inverts and the toast re-opens on it; again inverts it back. Once the toast has gone a tap only shows the value again. The first `[REC]`+`[PLAY]` still starts live recording, and the toast closes instantly on `[REC]` release. `LIVE_DUR` (default `0x3c` = 60 = **1.000 s** at the derived 1/60 s UI tick) is the toast's life *and* the flip window — they are the same thing, the OS's own countdown. **Hardware-confirmed working.** |
| `python3 tools/build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | `140C_KYOTI` | Bug 1 fix + the full **SIDE-CHAIN COMPRESSOR** on the COMPRESSOR's page 2: `KEY` (any of the 8 tracks), `KFLT` (declicked one-pole, below centre LP / above centre HP / centre off), `KGN` (declick-smoothed key trim) and `MON` (audition the filtered key). The DSP code space is donated by **SPRING REVERB**, pulled from the FX2 list; SPATIALIZER is untouched. **Hardware-confirmed, final** — see below |
| `python3 tools/build_mutemode_dt.py` | `140C_KYOTI` | Bug 1 fix + **MUTE MODE**, all four values: `OT` (stock, byte-for-byte) / `OTFX` (hard dry cut, FX tails ring, sequencer untouched — unmuting resumes at the playhead) / `OTFX-T` (same cut, but new trigs stay suppressed) / `DT-T` (pure sequencer mute, Digitakt-style). SOLO follows the selected mode. **This is the shipping MUTE MODE build.** |
| `python3 tools/build_mutemode.py` | `140C_KYOTI` | the same toggle built with two values only (`OT` / `OT+FX`) — the original baseline, kept for comparison; prefer `build_mutemode_dt.py` |
| `python3 tools/build_directjump_v4.py` | `140C_KYOTI` | Bug 1 fix + a **DIRECT JUMP** toggle (`[PTN]` + `[YES]`, transient overlay, deliberately not persisted — OFF on every power-on): a manually cued pattern switches on the next step tick and **keeps playing in master time** (`masterStep mod newMasterLen`, each track `that mod trackLen`), loads the new Part at once, sends the Program Change ~1 step early; arranger and chains untouched. *Hardware-confirmed at 1x track and master scales; the non-1x fix is built and emulator-validated but unflashed — see below* |
| `python3 tools/build_reload3.py` | `140C_KYOTI` | Bug 1 fix + **RELOAD FROM PROJECT**, as two direct chords — no picker, no modal window, no timeout. **`[PTN]` + `[TRACK n]`** reloads that track's card-saved sequence with the Part untouched; **`[BANK]` + `[TRACK n]`** does the same and re-applies the saved Part (from RAM, via stock's own reload-part routine). From the card's last SAVE BANK, **without touching the transport**. **Hardware-confirmed, final** (2026-09-25). The result is shown when the reload has *finished*, and a built-in check reports `SEQ RELOAD LOST` if the trigs did not land. `--diag` builds an on-screen diagnostic variant (`python3 tools/build_reload3.py --diag`, separate `_DIAG` files) |
| `python3 tools/build_partreapply.py` | `1.40C` (unchanged) | **Part-change carryover fix** — after a pattern change that links a different Part, forces the full stock Part-reapply path (recorder record, scene morph, `TRK_PART`/`TRK_BANK` consistency) instead of the stock code's partial one, **re-seeds the per-track sample slot a track leaving PICKUP would otherwise keep**, and stops a pattern switch into a PICKUP track from spuriously marking its Part unsaved. On otherwise-stock 1.40C. **Hardware-confirmed, final** — see below |
| `python3 tools/build_bugbuilds.py` | per-image (`BUG_MUTEDT`, `BUG_QLREC`, `BUG_SC3X`, `BUG_TRIGLK`, `BUG_RL3`) | **Each finished feature, with all three bug fixes folded in** — MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK and RELOAD3, each composed with PARTREAPPLY + PATTERNLED + PLAYSFREEFIX. Writes **only** to `out/Bugbuilds/`, so the standalone per-feature images above are left alone. Composes onto the finished feature image rather than re-deriving it, with an interlock proof asserted on every run. *Not flashed — every ingredient is individually confirmed, the composites are not* |
| `python3 tools/build_triglock.py` | `1.40C` (unchanged) | **Auto-remove an emptied trigless lock** — a LIVE-REC `[NO]`+knob erase that clears a step's last p-lock now also drops the now-purposeless trigless lock, instead of leaving it lit on the trig row indefinitely. An empty trigless lock placed deliberately with `FUNC`+`TRIG` is left alone. On otherwise-stock 1.40C. **Hardware-confirmed, final.** |

All mods are **OFF by default** (`MUTE MODE = OT`; `KEY = OFF`, stored per Part).
A freshly flashed unit is indistinguishable from stock until you opt in. An OS
upgrade resets PERSONALIZE.

These are the Bug-1 fix + the Kyoti mods only. Maxolydian's octamax behaviour
mods (arp key-scales, lazy Part transitions, BANK/PTN countdown removal, LED
"dirty" indicators, `MAXOLYDIAN` branding) are **not** built here — their patch
sources are kept in [`tools/attic/`](tools/attic/) for reverse-engineering
cross-reference. See [`CREDITS.md`](CREDITS.md).

### Hardware-test status

| element | status |
|---|---|
| Bug 1 manual-trig fix | **hardware-confirmed, final** (flashed 2026-08-28; the whole of `build_trigscale_only.py`) |
| Bug 2 p-lock-only pattern shows empty (`build_pattern_led.py`) | **hardware-confirmed, final** — flashed 2026-09-13, grid LED lights correctly, no regression. Full-firmware `emu_pattern_led.py` also passes |
| **QUANTIZE LIVE REC** toggle (`build_qlrec.py`) | **hardware-confirmed working (2026-09-25), after three failed flashes worth recording.** (1) An early design passed `dur<=0` to `FUN_4005a2b8` and **hung the unit** — that call tail-jumps into the modal overlay stack. (2) The replacement drove the toast from a detour of `0x400522ca`, believed since Session 21 to be a safe "per-control-frame tick"; it is not — `NOTIFY`/`NOTIFY_CLOSE` reach `FUN_40000c3c`, the kernel post/wake, and running that from the engine frame handler **hard-crashed the unit** (dead controls, persistent HF crackle). ⚠️ That crash was already **latent in the Session 51 build** this table once called "final": it armed the hook only after a successful double-tap, so it was rare, not absent. (3) The rewrite then never flipped, because its one private scratch word at `0x80006a60` **does not survive between key presses on hardware** — found by a diagnostic build that named the failing condition on screen, after static analysis and the emulator had both reported success. The shipping patch now keeps **no state at all**: the gate is stock's own toast handle `0x460d1e70`. Cave 176 B, two detours, zero scratch. Trade-off, deliberate: any toast on screen arms the flip, stock's included. Two cosmetic issues (a brief textless-box flash, PERSONALIZE row not live-redrawing) are parked |
| **MUTE MODE** — all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`), the menu, SOLO handling and `'ANDY'` persistence (`build_mutemode_dt.py`) | **hardware-confirmed, final** — flashed and tested 2026-09-21 on MKI; one persisted word with the menu index derived from it, so menu and firmware cannot disagree |
| **DIRECT JUMP** (`build_directjump_v4.py`) | **hardware-confirmed at 1x scales; active WIP beyond them.** Flashed 2026-09-23 on the MKI: tracks and patterns stay in **master time** through a switch, patterns land on the **correct step**, mixed track lengths in one pattern work together (7 / 12 / 16), and **MASTER LENGTH is respected including `INF`**. This is the hard-won baseline — do not regress it. **All of that is confirmed only with 1x track scales and a 1x master scale.** Non-1x was root-caused and fixed 2026-09-24 — Hook P read the master step once and used it as every track's step index, which is correct only when master and track share a ticks-per-step; it now reads the per-track value stock's own rebuild already computed. Bit-identical to the confirmed build at 1x, emulator-validated on four fixtures, **not yet flashed**. Separately open and unexplained by that fix: a report that the visited steps depend on which trigs are on the grid and that LEDs and audio disagree. Two hardware faults were found and fixed getting here: a transport-start **lockup** from a hook gated on a global that lives beyond the boot zero-fill (garbage at power-on; the emulator zero-fills, so it could never have caught it), and **doubled trigs** from writing a per-track "previous step" array that stock's commit tail deliberately leaves alone. Earlier `v1`–`v3` builds are dead on hardware (the toggle never reached the handler at all) and are no longer listed here |
| **SIDE-CHAIN COMPRESSOR**, incl. cross-core `KEY` (`build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS`) | **hardware-confirmed, final** — flashed 2026-09-20, MKI, works well, single-core and cross-core both. `KEY` reaches any of the 8 tracks (not just same-core siblings); `KFLT` / `KGN` / `MON` all confirmed. The donor is **SPRING REVERB** (FX2-exclusive, pulled from the FX2 chooser and null-stubbed for older projects that still reference it by id) — **SPATIALIZER is untouched** and stays a normal selectable effect; an earlier stage donated SPATIALIZER instead, ran out of slack, and was reverted. A very mild HP↔OFF filter pop remains, filed as research-only; it does not block shipping. Earlier `build_sidechain.py`/`build_sidechain2.py` were intermediate stages and are no longer listed here |
| **RELOAD FROM PROJECT** — two direct chords (`build_reload3.py`) | **hardware-confirmed, final** — flashed 2026-09-25 on the MKI. What was confirmed: the intermittent failure where the toast said RELOADED but the edited sequence kept playing no longer occurs, and the user reports no RELOAD issue remaining. **Root cause**, found with an on-screen diagnostic build whose toast showed the reload's request as armed by the chord (`C`) and as read by the worker (`W`): the request bytes lived at `0x80006a50-55`, inside a RAM block the unit overwrites at runtime (the same trap QLREC hit), so the worker sometimes read a different track and the MIDI flag set, reloaded a MIDI track instead, checked *that*, and passed. They now live in the patch's own cave, and the build refuses any reference into `0x80006a40..0x80006abf`. Earlier flashes: 2026-09-23 both chords execute, no conflicts; 2026-09-24 reloads "quick and on-time". The modal picker was deleted in Session 85 (~13 hardware bugs in the picker / keymap / popup machinery, **none** in the worker); a reload never restarts the sequence or the metronome; SELECT BANK opens on the `[BANK]` release. All-tracks and whole-bank variants are deferred by the user. `build_reload2.py` (the picker) and `build_reload.py` (the original) are superseded and kept only for rollback and reference |
| **Part-change carryover fix** (`build_partreapply.py`) | **hardware-confirmed, final** — the thread is closed. Report #1 (a FLEX track stuck playing an old PICKUP loop) is **fixed, confirmed on MKI 2026-09-22**: the voice dispatch reads the sample slot from a per-track pre-image that stock re-seeds only when a track *enters* PICKUP and never when it leaves, so the PICKUP slot survived into the new FLEX machine — the 2026-09-13 build copied stock's kill bit but omitted the re-seed, which is why it changed nothing. A second stock bug found while testing it (a pattern switch into a PICKUP track spuriously marking that Part edited/unsaved) is **fixed, confirmed 2026-09-23**, restoring the whole byte so a genuine edit made before the switch survives. Reports #2/#3 (recorder SRC/RLEN, REC SETUP) could never be reliably reproduced on stock and remain unconfirmed; the recorder-cache and scene-morph pieces are behaviorally safe regardless. This is the one finished feature still on `wip` only — `main` carries the older, pre-Session-81 build. See `NOTES.md` "Session 81" |
| **Bugbuild composites** (`build_bugbuilds.py` → `out/Bugbuilds/`) | **not flashed.** Each base feature and each bug fix is individually hardware-confirmed in the rows above, but no composite image has been on hardware. What is proven is the composition: every run asserts each cave region all-zero before use, exact stock bytes at every detour site, no branch into a detour site, and a byte-level check that the composite's delta against stock is exactly the *disjoint union* of the feature's own delta and the three fixes' own, with no unattributed bytes. All four images report clean and pass `emu_pattern_led`. `--with-wip` will fold the fixes into DIRECT JUMP and RELOAD3 the same way once those are finished |
| **Auto-remove an emptied trigless lock** (`build_triglock.py`) | **hardware-confirmed, final** (MKI, 2026-09-21). The handler was found by tracing the gesture on the unit after three builds aimed at the wrong code did nothing. The detour sits on the erase store so a deliberate `FUNC`+`TRIG` empty placeholder is not deleted by an unrelated `[NO]`+knob; emulator-validated 8/8 against real exports, then confirmed on hardware |

The ColdFire emulator (Unicorn, real image bytes) proves control-flow and the
DSP frame-word edits; the DSP emulator (dsp56kEmu) runs the actual DSP56300
code. Neither proves how anything *sounds* on the unit. `OT` mode is
byte-for-byte stock. Flash at your own risk.

Each build emits, in `out/`:

```
mainos_*.bin                      the patched MAIN OS section
elek_*.bin                        the rebuilt ELEK container
OCTATRACK_OS1.40C_*.syx           MIDI-DIN upgrade transport
OCTATRACK_*.bin                   CF-card OS UPGRADE transport (faster)
```

## Prerequisites

- **Python 3.8+**
- **ColdFire cross-assembler** — `m68k-elf-as`, `m68k-elf-ld`, `m68k-elf-objcopy`
  (targeting `-mcpu=5407`). On macOS: `brew install m68k-elf-gcc` (or a
  `m68k-elf-binutils` formula/tap).
- **Your own copy of the official OS 1.40C** — from
  <https://www.elektron.se/support-downloads/octatrack-mkii>. The same image
  serves MKI and MKII.
- *For `build_sidechain3.py`* — the DSP56300 toolchain (`dsp_asm`,
  `dsp56kDisassemble`) built into `vendor/dsp56300/`, and the external-RE
  clone cache (`python3 tools/refs/sync.py`, which it reads `dsp_modmap.py`
  from). Every other build here is ColdFire-only and needs neither.

## One-time setup

```sh
./fetch-os.sh     # downloads the official OS 1.40C into downloads/ and extracts it
./analyze.sh      # unpacks it -> out/raw/section_3_MAIN_OS.bin  (the decompressed MAIN OS)
./setup.sh        # clones + patches + builds elektron-firmware-tool into vendor/
```

`fetch-os.sh` pulls the Elektron download; if the URL has moved, drop the
`OCTATRACK_OS1.40C.zip` (or the extracted `.syx`) into `downloads/` yourself and
re-run `./analyze.sh`.

## Build

```sh
python3 tools/build_qlrec.py                  # one feature -> out/OCTATRACK_*QLREC.{syx,bin}
# or build_pattern_led.py / build_sidechain3.py (also finished + hardware-confirmed),
# or any other build command from the table above

python3 tools/build_bugbuilds.py              # each finished feature + all 3 bug fixes
                                              #   -> out/Bugbuilds/ (the images above are untouched)
```

There is deliberately **no single all-in-one image**: `tools/build_merged.py` is
withdrawn so a combined build cannot quietly ship an unfinished feature.
[`reference/MERGE.md`](reference/MERGE.md) is the authoritative allocation map it
will be rebuilt from, and it stages the merge as `KYOTI_V1.0` (the seven finished
mods, nothing to resolve) then `KYOTI_V1.1` (+ DIRECT JUMP and RELOAD3).

Every build is a **guarded binary patch**: it asserts the stock bytes at each
splice site, checks the code caves are free / non-overlapping / inside the free
zone, derives every detour target from the linker symbol table (never
hardcoded), and round-trips the result through `elektron-firmware-tool`. It
aborts before writing if anything is off — a wrong stock file, an already-patched
image, or a checksum mismatch.

Pass a custom version string as the first argument if you want
(`python3 tools/build_mutemode_dt.py MY_BUILD`), but the Kyoti builds default to
`140C_KYOTI` and that is what appears on the boot splash and SYSTEM STATUS.

## The reproducible patch (no assembler needed)

`sysex/` carries the **Bug-1 fix** captured hunk-by-hunk as JSON (load address +
expected original bytes + replacement bytes) and applies it with
`sysex/apply_patch.py` — no cross-assembler required. See
[`sysex/README.md`](sysex/README.md). Everything else — the Bug-2 pattern-LED fix,
MUTE MODE, DIRECT JUMP, side-chain, RELOAD FROM PROJECT, QUANTIZE LIVE REC,
trigless-lock auto-remove and the part-change carryover fix — is build-from-source
only.

## Flashing

See [`FLASHING.md`](FLASHING.md). Short version: MIDI **DIN** (not USB) for the
`.syx`, or **PROJECT → OS UPGRADE** from the CF card for the `.bin` (much
faster). Keep the official `.syx` on hand — `[FUNC]` + power on → `[TRIG 3]`
recovers the unit even from a bad OS, because an OS update never touches the
bootloader. Never cut power during `UPDATING FLASH`. Your CF card, projects and
samples are untouched by an OS update.
