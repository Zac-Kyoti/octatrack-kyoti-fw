# BLACKPYRAMIDS_303 voice calibration tools

The tools behind BLACKPYRAMIDS_303's voice (2026-10-21): the scorer against a real TB-303, the joint fit, the
generator of the ColdFire tables and the DSP constants, and the checks. What the voice is, and what of it is
Open303's: `reference/BLACKPYRAMIDS_303.md`. How it was arrived at: `reference/handoffs/OT303_VOICE_CALIBRATION.md`.

## Inputs

- **Din Sync's TB-303 reference recordings** (400 C2 notes with known CUTOFF / RES / ENV MOD / DECAY / ACCENT
  positions, http://www.dinsync.info/2010/02/tb-303-reference-recordings-for-x0xb0x.html), downloaded by hand to
  `out/dinsync/raw/SET-<A1..E5>.wav`. Measurement only: they are not part of this repository and must not be
  redistributed.
- `data/voice.json`: the fitted voice (settings and the knob laws: real-303 % -> the engine's values).
- `data/knob_curves.json`: the RES / ACCENT effect curves the knobs are spaced by (`evenknob.py`).

## The build path

`gen_body.py` writes `tools/ot303/cf/body_tables.h` (ColdFire tables and constants) and
`tools/ot303/cf/body_dsp.json` (the DSP's X constants and the cutoff table's layout, read by
`tools/ot303/hwprobe_image.py`). Both are committed; regenerate after changing `data/` or `gen_body.py`, then rebuild
with `tools/build_blackpyramids_303.py`.

## Renderers

Both drive the integer twin (`tools/ot303/twin.h`, bit-exact to the DSP engine):

    cc -std=c99 -O2 -Itools/ot303/cf -c tools/ot303/cf/params.c -o out/body/params.o
    cc -std=c99 -O2 -Itools/ot303/cf -c tools/ot303/cf/record.c -o out/body/record.o
    cc -std=c99 -O2 -Itools/ot303/cf -c out/ot303/host/ytab.c -o out/body/ytab.o
    c++ -std=c++17 -O2 -w -Itools/ot303 -Itools/ot303/cf tools/ot303/body/bp_render.cpp out/body/params.o -o out/body/bp_render.k
    c++ -std=c++17 -O2 -w -Itools/ot303 -Itools/ot303/cf tools/ot303/body/bp_cf.cpp out/body/params.o out/body/record.o out/body/ytab.o -o out/body/bp_cf

- `bp_render.cpp`: the prototype. Takes engine values and data-only candidate settings (see its header) on top of
  the previous release's ColdFire words, so link it with that `params.c`, not today's:
  `git show 5af46f8:tools/ot303/cf/params.c > out/body/params_mt35.c` (with its `params.h` / `params_const.h`).
- `bp_cf.cpp`: the voice exactly as the ColdFire makes it (record.c + params.c); every word from the record.
  `ytab.o` from the `ytab.c` that `tools/ot303/host_check.py` writes.

## Scoring and checks

- `realref.py`, `realref2.py`: the yardstick against the recordings (third-octave bands x time windows, one
  global gain); `fit.py`, `fit_joint.py`, `study.py`: the fits.
- `cfcheck.py`: the ColdFire build against its prototype on the recordings, with and without level (tone only).
- `headroom.py`: the 4,320-note ceiling sweep (hard saturations anywhere in the engine).
- `evenknob.py`: the RES / ACCENT effect curves; `volclick.py`: switch noise crossing VOL 64 / 65;
  `drivecheck.py`: accent peaks at the driven VOL against the recordings.
