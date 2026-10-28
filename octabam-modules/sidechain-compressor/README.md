# SIDECHAIN_COMPRESSOR

Stock **COMPRESSOR** with a **side-chain KEY** from any track, T1 to T8, and a
**base-width key filter**. Five controls join RMS on page 2:

| knob | what it does | readout |
|---|---|---|
| **MON** | ON: hear the processed key on this track instead (audition); switching it, or changing KEY while it is on, fades (256 samples, about 6 ms) instead of clicking | `OFF` (left) / `ON` (right) |
| **KEY** | OFF (stock: the track's own signal), or T1–T8; one position per detent, also with the encoder pressed | `OFF`, `T1`…`T8` |
| **KGN** | the key's gain, about −24 to +24 dB; 64 is unity | `-64`…`+63` |
| **KBAS** | the filter's base: a high-pass, 18 dB/oct Butterworth, at OFF or 20 Hz to 19.6 kHz | **Hz**: `40`, `990`, `1.2k` (kHz) |
| **KWID** | the filter's width: a low-pass, 12 dB/oct Butterworth, this many **octaves** above KBAS, 0.5 to 9.9, or OFF. With KBAS OFF it counts up from 20 Hz: a plain low-pass | **octaves**: `0.5`…`9.9`, `OFF` |

The base-width filter isolates the key — a kick's fundamental, for example, with KBAS cutting
the sub-sonic rumble below it (KBAS about 30–40 Hz, KWID about 1.2–1.5) — which reduces
distortion and keeps the compression smooth at short attack and release settings. The two
knobs cannot cross, and each readout is what the DSP runs (KBAS rounded to the filter's step,
within 0.4 semitone).

## Changed on 25 Oct 2026: MON, KEY and the octabam table fix

- MON shows OFF on the left and ON on the right. A COMPRESSOR saved with any earlier version
  of this module comes up with MON OFF.
- KEY moves one position per detent when the encoder is pressed and turned (stock moves 7).
- Switching MON, or changing KEY while MON is on, fades over 256 samples (64 before).
- The octabam form read the key filters' coefficients from the wrong memory, so KBAS and KWID
  gave silence, level jumps and squeals (OCTABAM31, 24 Oct 2026). The key-filter table is now
  its own `ptable2`, loaded by its own literal as in the standalone image.

**Hardware-confirmed:** the table fix in this octabam form (the author's MKI, OCTABAM32,
25 Oct 2026); MON, KEY and the fades in the standalone image (`140C_SCKD3`, 25 Oct 2026).

## Changed on 22 Oct 2026: the base-width key filter

This version replaces the previous one, whose page 2 was RMS · KEY · KFLT · KGN · MON with a
one-knob key filter (KFLT, 6 dB/oct: below centre low-pass, above centre high-pass). The new
filter isolates the key much better, but page 2 is laid out differently, so **a COMPRESSOR
saved with the previous version sounds different** until its knobs are set again:

| saved value | now lands on | what to do |
|---|---|---|
| KEY | KEY (unchanged) | nothing |
| the old KFLT | KGN | set KGN back (64 is unity) |
| the old KGN | KBAS | set the key's high-pass; OFF for none |
| the old MON | KWID | set the key's low-pass; OFF for none |
| — | MON (now slot 7) | comes up OFF |

A COMPRESSOR saved on stock firmware is not affected: it comes up with the side-chain off, as
before. The previous version still builds, as a WIP standalone image only and not recommended:
`tools/build_sidechain_compressor_light.py`.

**Hardware-confirmed in the standalone image** (the author's MKI, 22 Oct 2026, build
`140C_SCKF4`): page 2, the KBAS and KWID ranges and readouts, the kick-fundamental case at short
attack and release, MON and KEY declick, and the DSP load with 1 + 7 and 4 + 4
COMPRESSOR / DJ EQ per core; and in the KYOTI V1.6 combined image (22 Oct 2026).

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: one ROM unit, two `jsr` detours, the COMPRESSOR row, four DSP hooks |
| `../../tools/patch_sidechain.s` | the ColdFire unit `sc_cf`: MON's and KEY's step handlers, MON's switch, the MON, KEY, KBAS and KWID formatters, `sc_norm` |
| `../../tools/ui_switch.s` | the ColdFire unit `sc_ui` (shared with VARISPEED): KEY's 9-position rotary switch, KWID's knob with the link clip |
| `../../tools/patch_sc_dsp3.asm` | the DSP code: `sctap`, `scdet` (key filters, KEY declick), `moncommit` (MON crossfade), `scinit` |
| `../../tools/sc_keyfilt.py` | the key filters' table, constants and bit-exact model |
| `../../tools/sc_tables.py` | the KEY GAIN table |

Standalone image: `tools/build_sidechain_compressor.py`. It reads the same files.

## How it works

The effect is still stock COMPRESSOR. `MenuEntry(replaces="COMPRESSOR", stock_dsp=True)`
leaves its dispatch entry as it is, and the module's DSP code runs only from four hooks:

| hook | payload A | payload B | what it does |
|---|---|---|---|
| `sctap` | `P:0x004a7` | `P:0x0029c` | dispatcher, every track, every block: publish the track's audio to this core's keybus and to the cross-core window |
| `scdet` | `P:0x01ab1` | `P:0x01871` | COMPRESSOR proc+0: the detector reads the KEY track through KGN and the key filters; the result is stashed for MON. While MON is audible, a new KEY waits for MON to fade out |
| `moncommit` | `P:0x0050e` | `P:0x00303` | dispatcher, per-track commit: with MON on, the stashed key replaces the track's output, with a 64-sample crossfade either way |
| `scinit` | `P:0x01aa4` | `P:0x01864` | COMPRESSOR init: the key filters start over |

**The key filters.** A TPT one-pole high-pass times a TPT state-variable high-pass at KBAS
(18 dB/oct), then a TPT state-variable low-pass KWID above it (12 dB/oct), Butterworth, on one
grid, f = 20 Hz · 2^(g/16). The coefficients come from a 49-word table and the DSP's `div`,
recomputed only while a cutoff glides (5 ms). With both knobs at OFF the filters are bypassed,
without a step. Their state lives in COMPRESSOR's own r7 block (r7+$1c..$2d), which stock
COMPRESSOR leaves free (an r7 canary, emulator and hardware, 19 Oct 2026); `scinit` resets it,
because another effect in the slot may have used those words.

**For a composed caller:** `scmonbody` uses a, b, x0, x1, y1, r1, n1 and r3.

## Page 2

| slot | label | formatter | widget |
|---|---|---|---|
| 7 | MON: 2 = OFF, 3 = ON (count 4; step handler `sc_cf:mon_step` keeps it on 2..3) | `sc_cf:mon_fmt` | `sc_cf:mon_widget`: the stock switch `0x40046f10` |
| 8 | KEY (step handler `sc_cf:key_step`: no push-turn speed-up) | `sc_cf:key_fmt` | `sc_ui:sw9_widget`: a 9-position rotary switch |
| 9 | KGN | stock bipolar `0x4003c7a0` | 0 (a plain knob) |
| 10 | KBAS | `sc_cf:hp_fmt` | 0 |
| 11 | KWID | `sc_cf:lp_fmt` | `sc_ui:clip_knob`: the stock knob and the link clip to KBAS |

KEY stays in slot 8, so MUTE_MODES' muted-KEY exemption works as before. `sc_norm` resets a
COMPRESSOR saved on stock firmware (KEY above 8) to MON OFF, KEY OFF, KGN 64, KBAS OFF, KWID
OFF, and sets MON OFF wherever it is not 2 or 3 (a COMPRESSOR saved with an earlier version).
A COMPRESSOR saved before 22 Oct 2026: see "Changed on 22 Oct 2026" above.

## Placement in octabam (PLACE)

| PLACE | `sc_cf`, `sc_ui` |
|---|---|
| `CAVE` (default) | the ColdFire free region, as in the standalone image |
| `DRAM` | octabam's platform runtime; still re-linked at `0x400d7000` / `0x400d7300` and compared with the author's bytes |

## One copy for both cores (FORM)

| `FORM` | what is built |
|---|---|
| `PER_CORE` (default) | the DSP source as every other build assembles it: one copy per payload |
| `SHARED` | `tools/sc_shared.py`'s form: one copy that runs on both cores, for octabam's demand loader |

`SHARED` is opt-in and only octabam's demand-loaded remix sets it. `tools/patch_sc_dsp3.asm`
is not edited; the standalone, KYOTI and Modwerk builders do not read `sc_shared.py`, and with
`PER_CORE` octabam's images are byte-identical to the previous pin's (`test/sidechain-compressor`
and `test/kyoti-mute-sidechain`; the build report gains the setting's line).

What the shared form changes, and why (`tools/sc_shared.py` has the full description):

- The per-core values come from the track (`x:$420`), not from per-payload tokens.
- The cross-core key window is indexed by the absolute track and sits behind the tables, as
  zero words the manifest appends to the `ptable2`, so it is copied (cleared) with the code on
  every load and the reverb guard covers it. This needs octabam's window placement, which puts
  the tables right behind the code; the form is not for a harvested placement.
- The generation counters sit behind the window, zeroed with it; GSEED is gone.
- A foreign key reads the KEY track's core's own counter and takes the previous generation,
  instead of this core's counter minus two. Under the loader both counters stop while the code
  is withdrawn, so the rate-locked assumption would not hold across loads.

`tools/emu_sc_shared.py` runs both forms under `dsp_host` and compares them (ALL GOOD, 83
checks, 28 Oct 2026): `sctap`'s keybus and every window word for both cores' tracks, the
counters, nothing else written; `scdet`'s X:$40 for every KEY track from both cores, with each
foreign key at all four counter values, and a one-off counter reading a different generation.
Two deliberate breaks were caught (the foreign generation 32 checks, the core-local gate 4).
Not run on a unit.

## Claims

Core-private Y `$7f0`–`$9ff` (MON words and the keybus) on both
cores, and the last `$202` words of each core's half of the shared window (A `$33dfe`.., B
`$3bdfe`..).

## Measured

- `sc_cf`, linked at the standalone image's own address, is that image's bytes (octabam
  re-links and compares it every build).
- `tools/emu_sc_dsp3.py` is ALL GOOD, also with `--layout octabam` (these addresses): the key
  filters bit-exact against `tools/sc_keyfilt.py` (incl. 24 chained blocks and the bypass in and
  out), the MON crossfade, MON consumed every block, the KEY hold, `scinit`.
- `tools/emu_sc_dsp3_xcore.py` (the generation counter, the window publish, the foreign read)
  and `tools/emu_sc_sctap.py` (every Y and window word `sctap` writes) are ALL GOOD with
  `--layout octabam`. All three read this manifest's `subst`; `--manifest PATH` tests another
  copy of it (a moved window) and `--org HEX` puts the code elsewhere in P, refusing a
  placement in the shared window that overlaps either payload's window words.
- DSP section: 677 words (code 612, the 16-word ptable and the 49-word ptable2); the ColdFire
  units 698 B (`sc_cf`) and 616 B (`sc_ui`).
- `tools/emu_sc_dsp3.py --ftab-lua` replays the broken table load of 24 Oct: every key-filter
  case fails, as heard on hardware.
- Load, modelled (`ot_emu`, OTDEMO, a keyed COMPRESSOR on every track + DJ EQ): about 2,652
  cycles a sample on core 1 with the filters on, 2,475 with both off.

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.
