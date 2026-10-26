# VARISPEED_EMUS

Tempo-locked varispeed for STATIC and FLEX tracks, with two sampler emulations.

TSTR (SRC SETUP) gets a fifth position, **VARI**: `OFF AUTO NORM BEAT VARI`. A VARI track
plays its sample dry, tape-style. Speed and pitch move together, locked to the project
tempo: (project BPM × p) / (sample BPM × q), exact in integers. Above 2× it folds down an
octave. RATE still applies. On AUTO, a sample whose TIMESTRETCH (audio editor → ATTR) is VARI
plays the same way. A sample or project tempo outside 30–300 BPM plays as TSTR OFF.

On a VARI track two SRC SETUP knobs change job:

| knob | becomes | values |
|---|---|---|
| PTCH | **QUAN**, the ratio p/q | 1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1 |
| TSNS | **EMUS**, the engine | **OT** (stock playback), **S950** (Akai S900/S950), **SP12** (E-mu SP-1200), low to high, four detents per step |

Leaving VARI gives PTCH and TSNS back the values they had. An EMUS change takes effect at
the track's next trig.

**S950** models the Akai's 12-bit storage at its 40 kHz sampling rate. **SP12** models the
SP-1200's 26.04 kHz, 12-bit sampling and its raw outputs, in full stereo. Both run on the DSP, in the code space SPRING REVERB gives up.

**DSP load guard.** The guard estimates each DSP core's load from the settings: a base, the
Part's FX types, and the engines its VARI tracks use. A change that would overload a core is
refused, with the toast `MAX DSP: EMU LIMIT`:
- an EMUS turn stops at the heaviest engine that fits;
- an FX type does not land;
- a track entering VARI some other way (TSTR, ATTR, a sample's tempo, a slot assign or pick)
  has its EMUS set to OT.

A safety net in the UI task sets just enough EMUS to OT if a core gets over budget in any
other way. Nothing ever steps down while a sound plays.

**Before going back to stock firmware**, set every VARI back to OFF, AUTO, NORM or BEAT and save. TSTR VARI is saved in the Part and ATTR TIMESTRETCH VARI in the sample's `.ot` file, both as the raw value 4; stock 1.40C stores it unchecked and plays it as NORMAL timestretch, and its TSTR formatter (bound off by one) may show junk text. (`reference/kb/file-format.md`, the `.ot` attribute file.)

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: one linked unit, 24 detours, four pokes, eight symbol refs, the DSP section |
| `varispeed_emus.s` | the ColdFire unit (`vem_cf`); with `VEM_EMUS = 0` it is the plain VARISPEED module (`../varispeed/`) |
| `vem_dsp.asm` | the S950 / SP12 DSP kernel, generated from `tools/varispeed_emus_dsp.asm` by `tools/varispeed_emus_dsp_octabam.py` |
| `vem_dsp_ptable.py` | the kernel's two table blocks (81 + 384 words), generated likewise |

Standalone image: `tools/build_varispeed_emus.py` (OS VERSION `140C_VEM10`, SPRING REVERB
removed). The unit linked at that image's address is that image's bytes, checked on every
build.

## How it works

- **ColdFire.** The render's increment store (`0x40004100`) is the frame hook. It writes the
  VARI increment and carries the engine in bits 2–3 of the Q26 increment the DSP voice
  receives. The other detours cover:
  - P2EDIT's delta conversion and SRC SETUP's open (the EMUS detents);
  - five sites in the audio editor's ATTR page and the four SETUP dial resolvers;
  - both Part applies, RELOAD PART, and hold wrappers on the bulk writers (SRC page paste,
    track paste, the PART menu's paste core and CLEAR);
  - for the guard: the UI task's loop tail, the FX1/FX2 choosers' YES, and the slot columns
    of the SRC menu and the audio editor's chooser.
- **Descriptors.** STATIC's and FLEX's TSTR count goes 4 → 5, using stock's 5-position select
  and this unit's formatter. PTCH gets a new widget and encoder step, TSNS a new widget.
- **State.** The PTCH/QUAN and TSNS/EMUS swap keeps each machine's values in NEIGHBOR's
  unused `---` bytes of the same track (claimed in the Part window).
- **DSP.** `zqrp` at the voice kernel's prologue (A `P:0x40b`, B `P:0x20e`) renders S950 or
  SP12 passes; OT passes go to stock. `zqboot` at each payload's one-time memory clear copies
  the tables into Y. Core-private Y `$A00–$FFF`.

PLACE: DRAM (default) or CAVE (where the standalone image puts it). The ledger refuses this
module beside VARISPEED or anything else that writes the TSTR words or the same sites.

## On the unit

The author's MKI, 15 Oct 2026: the VEM10 build (standalone `140C_VEM10` or its Bugbuild `BUG_VEM10`).
