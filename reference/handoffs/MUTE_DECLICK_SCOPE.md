# MUTE_MODES declick — scope (discussion only, 2026-10-11)

Status: **talk only. Nothing built, nothing flashed.** Saved for later refinement.

## The ask

Stock OT mutes (dry + FX) can pop: the cut or the unmute lands at a non-zero point in the
waveform. Stock STOP/pause (dry cut, FX rings) and triple-STOP (dry + FX cut) never pop. In
MUTE_MODES, **OT and OTFX can pop; OTFX-T and DT-T don't.** Goal: no pop in any mode,
**including OT**, while every mode still feels "instant".

## Why the modes differ (from `octabam-modules/mute-modes/patch_softmute.s` + NOTES)

| mode | how the dry is silenced | mute | unmute |
|---|---|---|---|
| OT | stock `FUN_40004db8` zeroes the track's post-FX main-mix level word `frame[8t+2]` in one frame | step to 0, can pop | step back mid-waveform, can pop |
| OTFX (GATE 3) | hook 1 zeroes +6/+10 of the per-track DSP block (`0x80000110 + sel*512 + t*64`, both halves) every frame | step, can pop | step back mid-waveform, can pop |
| OTFX-T (GATE 1) | note-off `FUN_40008f84(t)` on the mute edge + `DAT_8000184a` held (the STOP-style release, Session 9 V5) | DSP's own declick fade, no pop | nothing sounding; the next trig starts fresh |
| DT-T (GATE 2) | nothing cut, the voice rides its AMP envelope | no pop | same as OTFX-T |

- The STOP-style cut went into **OTFX-T only**. It sounds instant but is a fade: in the emulator
  (NOTES ~l.9338) it starts ~4 frames (~1.5 ms) after the mute and is down ~17 dB by
  ~24 frames (~9 ms). The user approved it in Session 9 as "fast but smooth".
- OTFX can't use that path: a note-off frees the voice, and OTFX exists to resume at the playhead.
- In the `-T` modes, unmute never brings a voice back mid-waveform, which is why only OT and
  OTFX pop on unmute.
- **SIDE-CHAIN KEY tracks** (Session 116, `p1_key`) are muted the OT way in every mode, so they
  can pop even in OTFX-T.
- SOLO-silenced tracks follow the same per-mode paths as mute.

Frame = 16 samples = 362.8 µs (`reference/kb/techniques.md`).

## Options

1. **A ColdFire ramp over several frames (recommended to scope first).** Instead of stepping the
   gain word to 0, scale it over N ≈ 8–14 frames (~3–5 ms), and do the reverse on unmute.
   - OT: ramp `frame[8t+2]`. The FX return fades with it, so OT stays "instant, tails die".
   - OTFX: ramp +6/+10 instead of clearing them.
   - Fits the existing hook 1 per-frame cave and the SHADOW edge detection. Needs a small
     per-track ramp state in patch RAM; extra cost only while a ramp runs.
   - Precedent: SIDECHAIN's KGN smoothing (a ~5 ms ramp updated once per 16-sample block)
     removed audible clicks on hardware.
2. **Reuse the DSP declick fade without freeing the voice.** Probably dead: that path resets the
   play position (`pcurs+0xc = 0`, Session 9 V4), which breaks resume. It is also pre-FX, so it
   can't give OT its "tails die" behaviour.
3. **Smoothing per sample in the DSP program.** Best sound, but costs DSP P-memory and cycles
   (REPITCH is already High in `KYOTI_LOAD_AUDIT.md`) and changes every stock level move. Only
   if option 1 leaves audible stepping.

Rejected: waiting for a true zero crossing. L/R cross at different times, and it needs
per-sample DSP work. A short ramp is the standard fix, and it is what STOP already does.

## Open questions (RE before any build)

1. **How does triple-STOP silence the FX return without a pop?** If stock already has a smoothed
   post-FX kill, OT mode may reuse it. Highest-value first probe.
2. **What do the words hold: a straight gain, or a table index?** That decides whether
   "multiply by k/N" is a linear fade. Applies to both `frame[8t+2]` and +6/+10.
3. **OT ramp placement.** Stock writes `frame[8t+2]` inside `FUN_40004db8`, *after* hook 1 runs.
   Options: clear the track's D5 mute bit while ramping and write the scaled word ourselves
   (which ping-pong half?), or add a detour after the function. Also mind the ColdFire budget
   (frame ISR max ~306 µs / 362.8 with 7 FLEX on MKII).
4. **Does OTFX's ramp hold?** +6/+10 are rewritten every frame by the level chain
   (`0x4000ced4`, `0x4000cb4e`, ...). Scaling must apply once per fresh value, not compound.
5. **User decision:** the README promises "OT = stock". Declick OT directly (breaks the promise,
   but only in a way anyone would welcome), or keep stock OT and offer the declick separately?

## Plan sketch (not committed to)

One ramp mechanism shared by OT, OTFX and the KEY-track fallback; OTFX-T and DT-T unchanged.
Emulator checks use levels/spectra (not sample-exact diffs). Then an A/B listening pack
(old vs. declicked, mute and unmute, on a sustained sine and a loop), then a hardware flash.
