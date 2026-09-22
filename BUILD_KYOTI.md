# Roll your own OT Kyoti FW

This builds a **modified Octatrack OS 1.40C** from *your own* copy of the official
firmware. No Elektron binary is included here or produced for anyone but you; the
build is byte-for-byte reproducible from the stock file.

> **Read [`FLASHING.md`](FLASHING.md) before you flash anything.** Flashing
> non-official firmware risks the warranty and can leave the unit needing the
> bootloader recovery path. Static analysis is harmless; writing to hardware is
> not. The author runs these on an Octatrack **MKI** he owns.

> **Branch:** this is `wip`. The published **`main`** branch builds only the
> original hardware-tested baseline — `build_trigscale_only.py`,
> `build_mutemode.py` (softmute **V6b**, `OT` / `OT+FX`), `build_softmute.py`.
> This branch carries everything `main` has plus the features below.
> **Finished and hardware-confirmed on this branch:** the Bug-2 pattern-LED
> fix (`build_pattern_led.py`), **QUANTIZE LIVE REC** (`build_qlrec.py`), and
> the **SIDE-CHAIN COMPRESSOR** (`build_sidechain3.py`) — all flashed, working,
> no open issues. **Still active work-in-progress:** **MUTE MODE**'s `OT+FX`/`DT`
> modes (a real, characterized-but-unfixed blip/echo bug), **DIRECT JUMP**
> (`build_directjump_v4.py` — the toggle itself is hardware-confirmed reachable
> and crash-free, but a playhead-reset bug is still open), and **RELOAD FROM
> PROJECT** (`build_reload2.py` — first hardware pass found 3 bugs, 2 are fixed
> but not yet reflashed), the **part-change carryover fix** (`build_partreapply.py`
> — flashed but does not fix the originally reported bug), and See
> *Hardware-test status* below for exact per-item state. Earlier, superseded
> builds of these same features (old DIRECT JUMP and SIDE-CHAIN stages, the
> always-on softmute, the 3-item RELOAD picker) are no longer listed here —
> they're historical only; see `NOTES.md`.

## What you get

| build command | version string | contents |
|---|---|---|
| `python3 tools/build_trigscale_only.py` | `1.40C` (unchanged) | **Bug 1 fix only** — the Plays-Free MIDI manual-trig stall — on otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_pattern_led.py` | `1.40C` (unchanged) | **Bug 2 fix only** — a pattern whose only content is p-locks (MIDI-track locks, or audio trigless locks) no longer reads as an empty slot; its grid LED lights under `[PTN]`. On otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_qlrec.py` | `140C_KYOTI` | Bug 1 fix + **QUANTIZE LIVE REC** front-panel toggle: hold `[REC]`, tap `[PLAY]` twice to flip the PERSONALIZE row (with an on/off toast); the first `[REC]`+`[PLAY]` still starts live recording. **Hardware-confirmed, final** (two purely cosmetic issues parked, see below) |
| `python3 tools/build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | `140C_KYOTI` | Bug 1 fix + the full **SIDE-CHAIN COMPRESSOR** (`KEY` reaching any of the 8 tracks, `KFLT`, `KGAIN`, `SC LISTEN`/`MON`), donor now SPRING REVERB. **Hardware-confirmed, final** — see below |
| `python3 tools/build_mutemode.py` | `140C_KYOTI` | Bug 1 fix + **MUTE MODE** toggle: `OT` (stock) / `OT+FX` (soft mute — dry cuts clean, FX tails ring; **and, on this branch, soloed-out tracks get the same soft cut**). *Active WIP — a real blip/echo bug is open, see below* |
| `python3 tools/build_mutemode_dt.py` | `140C_KYOTI` | as above **+ a third mode `DT`** — pure sequencer mute (a sounding voice rides its own AMP envelope; only new trigs are suppressed). *Active WIP, same open bug as above* |
| *(a fourth mode `OTFX` — instant cut + FX tails + **playhead-resume** unmute — is reverse-engineered but **not built**; NOTES "Session 14")* | — | — |
| `python3 tools/build_directjump_v4.py` | `140C_KYOTI` | Bug 1 fix + a **DIRECT JUMP** toggle (`[PTN]` + `[YES]`, transient overlay): a manually cued pattern switches on the next step tick, loads the new Part at once (arranger/chain untouched). *Active WIP — the toggle itself is hardware-confirmed reachable and crash-free; the "keeps playhead position" behaviour is not yet fixed (it currently restarts at step 1), see below* |
| `python3 tools/build_reload2.py` | `140C_KYOTI` | Bug 1 fix + **RELOAD FROM PROJECT** (SEQ-focused): **hold `[PTN]`** opens a sticky picker (opens on `TRK SEQ`; arrows to `PTN SEQ` / `PART + PTN SEQ`), `[YES]` executes + closes / `[NO]` cancels, no timeout. `TRK SEQ` = the one currently-addressed track (audio or MIDI); `PTN SEQ` = the whole pattern, Part assignment preserved; `PART + PTN SEQ` = whole pattern incl. the Part link + apply that Part. From the card's last SAVE BANK, **without stopping playback**. *Active WIP — first hardware pass found 3 bugs; 2 are fixed but not yet reflashed, see below* |
| `python3 tools/build_partreapply.py` | `1.40C` (unchanged) | **Part-change carryover fix** — after a pattern change that links a different Part, forces the full stock Part-reapply path (recorder record, scene morph, `TRK_PART`/`TRK_BANK` consistency) instead of the stock code's partial one. On otherwise-stock 1.40C. *Active WIP — flashed and behaviorally safe, but the fix does not address the originally reported PICKUP→FLEX stuck-loop bug; see below* |
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
| **QUANTIZE LIVE REC** toggle (`build_qlrec.py`) | **hardware-confirmed, final** — an early design hung the unit (2026-09-13), root-caused and rewritten, reflashed with no hang; double-tap timing, toast fade/close and label polarity all HW-confirmed correct. Two purely cosmetic issues (a brief textless-box flash, PERSONALIZE row not live-redrawing) are parked, not chased further |
| MUTE MODE menu + `OT+FX` soft **mute** mechanism (`main`, softmute V6b) | **hardware-confirmed** — the Session-10 build was flashed and works |
| soft cut extended to **SOLO** (softmute V7 — this branch's `build_mutemode.py`) / **DT** mode (`build_mutemode_dt.py`) | **active WIP.** Session 57 found and fixed the original leak (a muted track's second level word was clamped instead of zeroed); flashed, and DT is now hardware-confirmed clean *with AMP RELEASE set to infinite*. With a finite release, both `OT+FX` and `DT` still show a real, once-per-cycle-ish blip/echo — root cause is precisely characterized (a stock function transiently clears the mute-state byte around a trig, racing the mute-cut hook) but **not yet fixed**. Do not flash expecting this closed; see `NOTES.md` "Session 57" onward |
| MUTE MODE 4th option (`OTFX` playhead-resume) | **reverse-engineered only** — not built; landing it renumbers the menu to `OT / OTFX / OTFX-T / DT-T` |
| **DIRECT JUMP** (`build_directjump_v4.py`) | **active WIP, partly hardware-confirmed.** Flashed repeatedly; a crash bug was found and fixed, and the toggle itself — reachability and the fast (~1-step) switch timing — is now **hardware-confirmed working**. **Still open: with DIRECT JUMP on, a manual pattern change restarts the new pattern at step 1** instead of keeping the playhead position. Root cause was mechanically proven 2026-09-20; the fix has not yet been built or flashed. Earlier `v1`–`v3` builds are dead on hardware (the toggle never reached the handler at all) and are no longer listed here |
| **SIDE-CHAIN COMPRESSOR**, incl. cross-core `KEY` (`build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS`) | **hardware-confirmed, final for now** — flashed 2026-09-20, MKI, works well. `KEY` reaches any of the 8 tracks (not just same-core siblings); `KFLT`/`KGAIN`/`SC LISTEN` all confirmed. Earlier `build_sidechain.py`/`build_sidechain2.py` were intermediate stages and are no longer listed here |
| **RELOAD FROM PROJECT** picker + SEQ worker (`build_reload2.py`) | **active WIP, partly hardware-confirmed.** First-ever flash (2026-09-20) found 3 real bugs: the `[PTN]`-held YES/NO handlers could be unreachable while still physically holding `[PTN]` (fixed and dynamically verified), a `RUNNING`-transport gate that wasn't actually load-bearing (dropped), and a case where the picker could stop opening at all after one use (fixed by removing the flawed gate rather than chasing its root cause). **Not yet reflashed with these fixes.** A real seamless-timing fix (an audible gap / step-1 reset on reload) and a proper list-style picker UI are deferred. The earlier 3-item `build_reload.py` predates this hardening and is no longer listed here |
| **Part-change carryover fix** (`build_partreapply.py`) | **active WIP, partly hardware-confirmed.** Flashed 2026-09-13: the recorder-cache and scene-morph pieces are behaviorally safe (though reports #2/#3 could not be reliably reproduced on stock, so treat as unconfirmed); **the originally reported #1 bug (PICKUP→FLEX stuck loop) is NOT fixed** — it reproduces identically on stock and patched. Root cause still open, see `NOTES.md` "Session 50" |
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
python3 tools/build_qlrec.py                  # -> out/OCTATRACK_*QLREC.{syx,bin}
# or build_pattern_led.py / build_sidechain3.py (also finished + hardware-confirmed),
# or any other build command from the table above
```

Every build is a **guarded binary patch**: it asserts the stock bytes at each
splice site, checks the code caves are free / non-overlapping / inside the free
zone, derives every detour target from the linker symbol table (never
hardcoded), and round-trips the result through `elektron-firmware-tool`. It
aborts before writing if anything is off — a wrong stock file, an already-patched
image, or a checksum mismatch.

Pass a custom version string as the first argument if you want
(`python3 tools/build_mutemode.py MY_BUILD`), but the Kyoti builds default to
`140C_KYOTI` and that is what appears on the boot splash and SYSTEM STATUS.

## The reproducible patch (no assembler needed)

`sysex/` carries the **Bug-1 fix** captured hunk-by-hunk as JSON (load address +
expected original bytes + replacement bytes) and applies it with
`sysex/apply_patch.py` — no cross-assembler required. See
[`sysex/README.md`](sysex/README.md). Everything else — the Bug-2 pattern-LED fix,
MUTE MODE, DIRECT JUMP, side-chain, RELOAD FROM PROJECT, QUANTIZE LIVE REC — is
build-from-source only.

## Flashing

See [`FLASHING.md`](FLASHING.md). Short version: MIDI **DIN** (not USB) for the
`.syx`, or **PROJECT → OS UPGRADE** from the CF card for the `.bin` (much
faster). Keep the official `.syx` on hand — `[FUNC]` + power on → `[TRIG 3]`
recovers the unit even from a bad OS, because an OS update never touches the
bootloader. Never cut power during `UPDATING FLASH`. Your CF card, projects and
samples are untouched by an OS update.
