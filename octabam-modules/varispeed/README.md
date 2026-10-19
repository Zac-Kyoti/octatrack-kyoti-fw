# VARISPEED

Tempo-locked varispeed for STATIC and FLEX tracks: VARI and QUAN, nothing emulated.

TSTR (SRC SETUP) gets a fifth position, **VARI**: `OFF AUTO NORM BEAT VARI`. A VARI track
plays its sample dry, tape-style. Speed and pitch move together, locked to the project
tempo: (project BPM × p) / (sample BPM × q), exact in integers. Above 2× it folds down an
octave. RATE still applies. On AUTO, a sample whose TIMESTRETCH (audio editor → ATTR) is VARI
plays the same way. A sample or project tempo outside 30–300 BPM plays as TSTR OFF.

On a VARI track PTCH becomes **QUAN**, the ratio p/q: `1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1`.
Leaving VARI gives PTCH back its value. TSNS stays TSNS. The DSP is stock: SPRING REVERB
stays, and there is no load guard.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: two linked units, 16 detours, four pokes, six symbol refs; requires STORE |
| `varispeed.s` | two lines: `.equ VEM_EMUS, 0` and `.include "remix.inc"`, where `remix.inc` is the text of `../varispeed-emus/varispeed_emus.s` (`Linked.include`) |
| `varispeed_store.s` | octabam only: the STORE handlers for the PART menu's CLEAR (`vs_st_partclear`, `vs_st_partsaved`) |

This folder needs `varispeed-emus/` beside it: the two modules assemble one source, so a fix
to the shared code lands in both. A VARI track's increment equals VARISPEED_EMUS's on
EMUS = OT, bit for bit.

Standalone image: `tools/build_varispeed.py` (OS VERSION `140C_VARI1`). It assembles this
wrapper too and refuses a build whose bytes differ.

## How it works

The render's increment store (`0x40004100`) is the frame hook. The other detours cover:
- five sites in the audio editor's ATTR page and the four SETUP dial resolvers;
- both Part applies and RELOAD PART;
- hold wrappers on the bulk writers (SRC page paste, track paste, the PART menu's paste core).

The PART menu's CLEAR (`0x4004a9d0`) is STORE's site in octabam, so there VARISPEED is a STORE
client: `partclear` holds (and sets a flag), and the `partsaved` that ends the clear forgets
(stock Part Clear tail-jumps into Part Save, whose only exit is STORE's `partsaved` site).
A SAVE PART without a CLEAR finds the flag clear and does nothing. The standalone image has
no STORE and keeps its own detour on CLEAR (`vh_partclear`).

STATIC's and FLEX's TSTR count goes 4 → 5, using stock's 5-position select and this unit's
formatter. PTCH gets a new widget and encoder step. The PTCH/QUAN swap keeps each machine's
PTCH in NEIGHBOR's unused `---` bytes of the same track (claimed in the Part window).

PLACE: DRAM (default) or CAVE (where the standalone image puts it). The ledger refuses this
module beside VARISPEED_EMUS or anything else that writes the TSTR words or the same sites.

## On the unit

The author's MKI, 15 Oct 2026: the VARI1 build (standalone `140C_VARI1` or its Bugbuild `BUG_VARI`).
