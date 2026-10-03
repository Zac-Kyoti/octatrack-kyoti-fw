# SIDECHAIN_COMPRESSOR

Stock **COMPRESSOR** with a **side-chain KEY**: any track, T1 to T8, can drive its
detector. Four controls join RMS on page 2:

| knob | what it does |
|---|---|
| **KEY** | OFF (stock: the track's own signal), or T1–T8 |
| **KFLT** | the key's filter: 64 bypass, below low-pass, above high-pass |
| **KGN** | the key's gain, about −24 to +24 dB; 64 is unity |
| **MON** | ON: hear the processed key on this track instead (audition) |

## ⚠️ Work in progress

Built and gated in octabam. This form has not been run on a unit.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: one ROM unit, the COMPRESSOR row, three DSP hooks |
| `../../tools/patch_sidechain.s` | the ColdFire unit `sc_cf`: KEY's and KFLT's formatters, KEY's list widget |
| `../../tools/patch_sc_dsp3.asm` | the DSP code: `sctap`, `scdet`, `moncommit` |
| `../../tools/sc_tables.py` | the KEY GAIN and KEY FLT tables and coefficients |

Standalone image: `tools/build_sidechain_compressor.py`. It reads the same three files.

## How it works

The effect is still stock COMPRESSOR. `MenuEntry(replaces="COMPRESSOR", stock_dsp=True)`
leaves its dispatch entry as it is, and the module's DSP code runs only from three hooks:

| hook | payload A | payload B | what it does |
|---|---|---|---|
| `sctap` | `P:0x004a7` | `P:0x0029c` | dispatcher, every track, every block: publish the track's audio to this core's keybus and to the cross-core window |
| `scdet` | `P:0x01ab1` | `P:0x01871` | COMPRESSOR proc+0: the detector reads the KEY track through KGN and KFLT; the result is stashed for MON |
| `moncommit` | `P:0x0050e` | `P:0x00303` | dispatcher, per-track commit: with MON on, the stashed key replaces the track's output |

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

**With MUTE_MODES:** a muted KEY track keeps feeding the compressor. MUTE_MODES carries
that variant when this module is in the remix.

**Not with BusDelay or BusVerb.** The keybus (core-private `Y:$7f0–$9ff`) and the
cross-core window (the last `$202` words of each core's half) overlap theirs. The ledger
refuses the pair. A later version is planned to move both.

## Measured

- `sc_cf`, linked at the standalone image's own address, is that image's bytes for
  `-mcpu=5407` and `54455` alike (octabam re-links and compares it every build).
- The cloned COMPRESSOR descriptor equals the standalone image's, except for the three
  words that point into `sc_cf`.
- On both payloads, octabam's placed DSP code is the standalone's, instruction for
  instruction, except for the two table loads above. The 48 table words are identical.
- `make check-remix` passes for `sidechain-compressor`, for MUTE_MODES with this module,
  and for all six KYOTI modules with this module.
- **On hardware** (the author's MKI, the standalone image and the KYOTI V1.0 combined
  image): KEY ducking, MON, and a muted KEY with MUTE_MODES (Session 117). No reverb
  cross-talk. **Not yet tested on a unit:** cross-core KEY in both directions, a reverb on
  T7 beside SIDE-CHAIN, and the first kick after PLAY with a muted key (`FLASHING.md`
  §4.11 block 4). This octabam form has not been run on a unit.

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed.
