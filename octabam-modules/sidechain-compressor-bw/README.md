# SIDECHAIN_COMPRESSOR_BW (Sidechain Compressor B-W)

Stock **COMPRESSOR** with a **side-chain KEY** from any track, T1 to T8, and a
**base-width key filter**. Five controls join RMS on page 2:

| knob | what it does | readout |
|---|---|---|
| **MON** | ON: hear the processed key on this track instead (audition); switching it, or changing KEY while it is on, fades instead of clicking | `ON` / `OFF` |
| **KEY** | OFF (stock: the track's own signal), or T1–T8 | `OFF`, `T1`…`T8` |
| **KGN** | the key's gain, about −24 to +24 dB; 64 is unity | `-64`…`+63` |
| **KBAS** | the filter's base: a high-pass, 18 dB/oct Butterworth, at OFF or 20 Hz to 19.6 kHz | **Hz**: `40`, `990`, `1.2k` (kHz) |
| **KWID** | the filter's width: a low-pass, 12 dB/oct Butterworth, this many **octaves** above KBAS, 0.5 to 9.9, or OFF. With KBAS OFF it counts up from 20 Hz: a plain low-pass | **octaves**: `0.5`…`9.9`, `OFF` |

The base-width filter was added to isolate the key better than SIDECHAIN_COMPRESSOR's
one-knob KFLT — a kick's fundamental, for example, with KBAS cutting the sub-sonic rumble
below it (KBAS about 30–40 Hz, KWID about 1.2–1.5) — which reduces distortion and keeps the
compression smooth at short attack and release settings. The two knobs cannot cross, and each
readout is what the DSP runs (KBAS rounded to the filter's step, within 0.4 semitone).

SIDECHAIN_COMPRESSOR (the light version) is the same effect with the older filter and a
smaller DSP section. The two are declared conflicts: one per remix.

**Hardware-confirmed in the standalone image** (the author's MKI, 22 Oct 2026, build
`140C_SCKF4`): page 2, the KBAS and KWID ranges and readouts, the kick-fundamental case at short
attack and release, MON and KEY declick, and the DSP load with 1 + 7 and 4 + 4
COMPRESSOR / DJ EQ per core. This octabam form has not been flashed yet.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: one ROM unit, two `jsr` detours, the COMPRESSOR row, four DSP hooks |
| `../../tools/patch_sidechain_bw.s` | the ColdFire unit `scbw_cf`: MON's, KEY's, KBAS's and KWID's formatters, KEY's list widget, `sc_norm` |
| `../../tools/patch_sc_bw_dsp3.asm` | the DSP code: `sctap`, `scdet` (key filters, KEY declick), `moncommit` (MON crossfade), `scinit` |
| `../../tools/sc_keyfilt.py` | the key filters' table, constants and bit-exact model |
| `../../tools/sc_tables.py` | the KEY GAIN table |

Standalone image: `tools/build_sidechain_compressor_bw.py`. It reads the same files.

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
| 7 | MON (stored inverted: 1 = OFF) | `scbw_cf:mon_fmt` | stock switch `0x40046f10` |
| 8 | KEY | `scbw_cf:key_fmt` | `scbw_cf:key_list_fix` |
| 9 | KGN | stock bipolar `0x4003c7a0` | 0 (a plain knob) |
| 10 | KBAS | `scbw_cf:hp_fmt` | 0 |
| 11 | KWID | `scbw_cf:lp_fmt` | 0 |

KEY stays in slot 8, so MUTE_MODES' muted-KEY exemption works as with SIDECHAIN_COMPRESSOR.
`sc_norm` resets a COMPRESSOR saved on stock firmware (KEY above 8) to MON OFF, KEY OFF,
KGN 64, KBAS OFF, KWID OFF. A COMPRESSOR saved with SIDECHAIN_COMPRESSOR keeps its KEY; its
other page-2 values land on different knobs (KGN = the old KFLT, KBAS = the old KGN, KWID = the
old MON) and need setting again.

## Placement in octabam (PLACE)

| PLACE | `scbw_cf` |
|---|---|
| `CAVE` (default) | the ColdFire free region, as in the standalone image |
| `DRAM` | octabam's platform runtime; still re-linked at `0x400d7000` and compared with the author's bytes |

## Claims

As SIDECHAIN_COMPRESSOR: core-private Y `$7f0`–`$9ff` (MON words and the keybus) on both
cores, and the last `$202` words of each core's half of the shared window (A `$33dfe`.., B
`$3bdfe`..).

## Measured

- `scbw_cf`, linked at the standalone image's own address, is that image's bytes (octabam
  re-links and compares it every build).
- `tools/emu_sc_bw_dsp3.py` is ALL GOOD, also with `--layout octabam` (these addresses): the key
  filters bit-exact against `tools/sc_keyfilt.py` (incl. 24 chained blocks and the bypass in and
  out), the MON crossfade, MON consumed every block, the KEY hold, `scinit`.
- DSP section: 677 words (code 612 + the 65-word ptable); the ColdFire unit 600 B.
- Load, modelled (`ot_emu`, OTDEMO, a keyed COMPRESSOR on every track + DJ EQ): about 2,652
  cycles a sample on core 1 with the filters on, 2,475 with both off.

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.
