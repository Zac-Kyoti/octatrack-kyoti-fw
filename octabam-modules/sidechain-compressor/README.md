# SIDECHAIN_COMPRESSOR

Stock **COMPRESSOR** with a **side-chain KEY**: any track, T1 to T8, can drive its
detector. Four controls join RMS on page 2.

This is the **light** version: its DSP section is smaller (465 words), but its one-knob key
filter (KFLT, 6 dB/oct) does not isolate the key as well as the base-width filter of
**SIDECHAIN_COMPRESSOR_BW** (Sidechain Compressor B-W, `../sidechain-compressor-bw`), which
reduces distortion and keeps the compression smooth at short attack and release settings. The
two are the same effect: one per remix.

| knob | what it does |
|---|---|
| **KEY** | OFF (stock: the track's own signal), or T1–T8 |
| **KFLT** | the key's filter: 64 bypass, below low-pass, above high-pass |
| **KGN** | the key's gain, about −24 to +24 dB; 64 is unity |
| **MON** | ON: hear the processed key on this track instead (audition); switching it, or changing KEY while it is on, fades instead of clicking |

**Hardware-confirmed in this octabam form** (the author's MKI, 2026-10-04, see Measured).
The one-pass tap (15 Oct 2026, below) is hardware-confirmed in the standalone image (the
author's MKI, 2026-10-16); in this octabam form it leaves every Y and shared-window word as the
code before it did (emulator), and has not been flashed.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: one ROM unit, two `jsr` detours, the COMPRESSOR row, three DSP hooks |
| `../../tools/patch_sidechain.s` | the ColdFire unit `sc_cf`: KEY's and KFLT's formatters, KEY's list widget, `sc_norm` |
| `../../tools/patch_sc_dsp3.asm` | the DSP code: `sctap`, `scdet`, `moncommit` |
| `../../tools/sc_tables.py` | the KEY GAIN and KEY FLT tables and coefficients |

Standalone image: `tools/build_sidechain_compressor.py`. It reads the same three files.

## How it works

The effect is still stock COMPRESSOR. `MenuEntry(replaces="COMPRESSOR", stock_dsp=True)`
leaves its dispatch entry as it is, and the module's DSP code runs only from three hooks:

| hook | payload A | payload B | what it does |
|---|---|---|---|
| `sctap` | `P:0x004a7` | `P:0x0029c` | dispatcher, every track, every block: publish the track's audio to this core's keybus and to the cross-core window |
| `scdet` | `P:0x01ab1` | `P:0x01871` | COMPRESSOR proc+0: the detector reads the KEY track through KGN and KFLT; the result is stashed for MON. While MON is audible, a new KEY waits for MON to fade out |
| `moncommit` | `P:0x0050e` | `P:0x00303` | dispatcher, per-track commit: with MON on, the stashed key replaces the track's output, with a 64-sample crossfade either way |

`moncommit` replays the displaced `move x:>$206,r0` before entering
`scmonbody`. A composed dispatcher hook may call `scmonbody` after replaying
that instruction itself. The body preserves `r0` for the stock output commit.

The values that differ per core (own and foreign core base, the window addresses, the
branch sense) are `DspSection.subst`. The 48 table words are one `ptable`. The source
reads it at the KEY GAIN site through its single base literal. At the KEY FLT site it
uses `lua (r1+$10),r1` and a `nop` from that same base, where the standalone builder
writes `move #>FTAB,r1`.

Page 2's slots 8–11 are raw descriptor words, as the standalone builder writes them:

| slot | formatter | widget |
|---|---|---|
| KEY | `sc_cf:key_fmt` | `sc_cf:key_list_fix` |
| KFLT | `sc_cf:kfilt_fmt` | 0 (a plain knob) |
| KGN | stock bipolar `0x4003c7a0` | 0 |
| MON | stock ON/OFF `0x4003c14c` | stock switch `0x40046f10` |

**A COMPRESSOR saved on stock firmware comes up with its side-chain OFF.** Stock
COMPRESSOR does not use page-2 slots 8–11, but its descriptor gives them the defaults
`0x7f/0/0/0` and choosing the effect writes them, so such a compressor would read as
KEY 127 (the DSP would key from unrelated memory), KFLT and KGN at minimum. `sc_norm`,
called by a `jsr` detour at the first instruction of both page-2 copiers (`0x4000cae8`, its
twin `0x40003d1c`), resets every COMPRESSOR whose KEY is above 8 to KEY OFF, KFLT 64,
KGN 64, MON OFF. It checks the current part's working store and the live lane the copier
sends to the DSP, each against its own FX id, every frame (171 instructions). A KEY of 0–8
was set on this firmware and is never changed.

**With MUTE_MODES:** a muted KEY track keeps feeding the compressor. MUTE_MODES carries
that variant when this module is in the remix.

**Not with BusDelay or BusVerb.** The cross-core window (the last `$202` words of each
core's half) overlaps theirs, so the ledger refuses the pair.

**Where the keybus lives is a build choice.** The DSP names the keybus and MON words only
through `@KEYB@`, `@KEYB1@` and `@MONB@`. This manifest sets Session 115's `Y:$7f0–$9ff`
(`$800`/`$820`/`$7f0`), which no FX2 slot reaches. The standalone and KYOTI images put them
in the tail of the first internal FX2 slot, `Y:$7df0–$7fff` (15 Oct 2026), past stock's
highest write at slot `+$3da2`; that frees `$7f0–$9ff` for BLACKPYRAMIDS_303. It is not
used here because MINIVERB, GATE VERB and WAVE write that tail: their FX2 buffers fill the
slot (GATE VERB to `+$3EF7`).

**The window has the same problem (open).** It is the tail of T7's and T3's FX2 slot, so
MINIVERB, GATE VERB or WAVE on T3 or T7 writes into it, and this module overwrites that part
of their buffer every block. In octabam's DSP host on the `test/sct-reverbs` scratch remix, MINIVERB
on T7 wrote all 514 window words, GATE VERB the first 250. The ledger does not refuse
these pairs yet. Not yet heard on hardware; a later version moves the window.

## Placement in octabam (PLACE)

A build setting, store `octabam.sidechain-compressor` (the id octabam already files this
effect's page defaults under), picks where octabam links `sc_cf`:

| PLACE | `sc_cf` |
|---|---|
| `CAVE` (default) | the ColdFire free region, as before; images bit-identical to the build without the setting (`test/sidechain-compressor`, `test/kyoti-mute-sidechain`) |
| `DRAM` | octabam's platform runtime, as `rl3` and `dj7`; still re-linked at `0x400d7000` and compared with the author's bytes |

A remix pins it: `settings={("octabam.sidechain-compressor", "PLACE"): Pin("DRAM")}`.
The DRAM runtime is assembled for the 54455, so `tools/patch_sidechain.s` no longer
carries `.cpu 5407`; every builder passes `-mcpu=5407` on the command line, and the
unit's 338 B of `.text` are identical with and without the line, for 5407 and 54455.
`DRAM` has not run on a unit.

## The tap, since 15 Oct 2026

`sctap` used to copy the block twice, to the keybus and then to the cross-core window. Each
copy was a loop of `move x:(r0)+,x0` / `move x0,y:(rN)+`, so 4 instructions a word. It now
computes both addresses first, then makes one pass of 2 instructions a word:
`move a,y:(r1)+` to the keybus, and the XY move `move x:(r0)+,a  a,y:(r6)+`, which writes
the window and loads the next word. `r6` is free there because the displaced
`move x:>$208,r6` reloads it on the way out.
- **Speed:** in `ot_emu`, 96 instructions a call where the old tap took 163, with 4 calls a
  block per core. That is about 17 fewer instructions a sample on each core.
- **Size:** the section is 4 words shorter (384).
- **Output:** the words it writes are the same.

## Measured

- `sc_cf`, linked at the standalone image's own address, is that image's bytes for
  `-mcpu=5407` and `54455` alike (octabam re-links and compares it every build).
- The cloned COMPRESSOR descriptor equals the standalone image's, except for the three
  words that point into `sc_cf`.
- On both payloads, octabam's placed DSP code is the standalone's, instruction for
  instruction, except for the two table loads above. The 48 table words are identical.
- `make check-remix` passes for `sidechain-compressor`, for MUTE_MODES with this module,
  and for all six KYOTI modules with this module.
- **On hardware, this octabam form** (the author's MKI, 2026-10-04, an octabam-built image
  with all six KYOTI modules, REC_TRIG_MUTE and this module): COMPRESSOR's page 1
  (ATK..MIX) and page 2 (RMS, KEY, KFLT, KGN, MON); KEY ducking on the same core and
  **across cores in both directions** (T1 → T5, T5 → T1); KFLT, KGN, MON; no reverb
  cross-talk with DARK or PLATE REV on T7; a muted KEY in each MUTE MODE, and the first kick
  after PLAY with it muted.
- `sc_norm` (2026-10-08), in `ot_emu` on the standalone, this octabam form and KYOTI V1.1:
  a COMPRESSOR put over stock's `7f/00/00/00` comes up KEY OFF, KFLT and KGN centred, MON
  OFF, on screen, in the Part and in the DSP record, transport running or stopped; an
  in-range KEY (T8) is kept; keyed audio is bit-identical to the build before. On hardware
  the standalone and KYOTI V1.1 with `sc_norm` were flashed with no issues; a project saved
  on stock firmware was not specifically tried.
- The 15 Oct 2026 changes, emulator only:
  - **`tools/emu_sc_sctap.py`:** 6 blocks of 4 tracks, on a counter that crosses
    `$800000`. Every keybus and window word is as modelled, and no other Y word changes.
    With `--ref` it compares against the old tap (`8265344`): all of internal Y and the
    shared window are equal, with the keybus compared at each version's address.
    `--layout octabam --ref 8b2e3c9` (this manifest's addresses, against the two-loop tap
    at the same addresses): 0 Y words differ.
  - **`tools/emu_sc_dsp3.py`:** ALL GOOD with the new addresses, with `--layout octabam`,
    and with `--patched` against the built image.
  - **`ot_emu`**, with the standalone image, a project with KEY = T2 and MON on and off:
    the mix is sample-identical to the promoted build over the run's common
    591,712 frames. `--dsp-watch` shows `sctap` writing Y:`$7e00`/`$7f00` with the values
    it used to write at `$800`/`$900`, and nothing writes `$800` any more.
- The 20 Oct 2026 MON and KEY declick: on hardware in the standalone image (the author's
  MKI, 140C_SCDK2); this octabam form not flashed. `tools/emu_sc_dsp3.py` ALL GOOD, also
  with `--layout octabam`: the crossfade bit-exact against its model, MON consumed every
  block (an effect changed with MON on fades out instead of replaying a frozen stash), and a
  KEY change held while MON fades. The KEY declick keeps its state at COMPRESSOR's
  r7+$2c/$2d (free while COMPRESSOR runs: an r7 canary, emulator and hardware). `scmonbody`
  now also uses x1 and y1 (a, b, x0, x1, y1, r1, n1, r3).
- Before that, on the standalone image and the KYOTI V1.0 combined image: KEY ducking,
  MON, a muted KEY with MUTE_MODES (Session 117).

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.
