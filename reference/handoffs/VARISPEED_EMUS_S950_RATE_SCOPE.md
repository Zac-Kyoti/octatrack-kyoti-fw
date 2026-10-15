# VARISPEED_EMUS: S950 recording rate (scope)

2026-10-14. Nothing built. DSP side only: the S950 kernel is our own code, so the clean-room
rules for the ColdFire core do not apply here.

## Why

The user heard the S950 engine sound almost like plain varispeed above 1/1. That is what the
shipped model does. It is a sampler that recorded at **40 kHz**, through a 6th-order record
filter at 0.4 × 40 kHz = 16 kHz, stored at 12 bits, and played back cleanly. The real
S900/S950 runs each voice's DAC clock at (rate × pitch) into a tracking filter, so it has no
interpolation artifacts. Pitched up, the 16 kHz limit moves past the OT's 22 kHz output, and
only 12-bit storage is left:

| tempo (loop 104) | S950 40 kHz vs OT, 16 kHz+ |
|---|---|
| 78 (0.75×) | −21.7 dB |
| 104 (1/1) | −6.8 dB |
| 130 (1.25×) | +0.8 dB |
| 156 (1.5×) | +1.1 dB |

Owners often sampled at lower rates (the S950 does 7.5–48 kHz). That narrower band is much
of the S900/S950 sound on records, and it stays audible when pitched up.

## The two ways to add a recording rate

**A. Cheap: move the filter.** Today's DSP structure with a table designed for a lower rate
(`fir_target`: cutoff 0.4 × rate). Measured fit of the kernel to the target:

| rate | cutoff | 16 taps | 24 taps |
|---|---|---|---|
| 40 kHz | 16 kHz | within 0.2 dB | within 0.1 dB |
| 32 kHz | 12.8 kHz | within 0.1 dB, stopband on target | same |
| 22.05 kHz | 8.8 kHz | within 0.3 dB; stopband −36 dB at 20 kHz (target −43) | within 0.1 dB; −41 dB |

- **Not modelled:** record aliasing. The real machine samples at the low rate, so what its
  filter passes above half the rate folds back down.
- **Cost (one rate, 16 taps):** the same cycles and table size as today. 24 taps adds about
  16 instructions per S950 voice (≈ 57 → ≈ 73 cycles).
- **Memory:** a 24-tap table does not fit the Y claim (Y:$A00–$FFF is nearly full: RPSP
  slots, both virtual-ADC tables, the render table). Store half the rows (they mirror), or
  grow the claim down into the ~90 free words below SIDECHAIN's $7F0.

**B. Full: record at the low rate.**
1. Record: filter, sample on a virtual grid at the rate (fold-back included), 12-bit.
2. Play: a band-limited interpolator from that grid at (rate × speed), removing images only.

- The DSP shape is like RPSP's tick grid, with a clean reconstruction instead of a staircase.
- **Cost:** an ADC kernel per stored sample plus an interpolation kernel per output. That is
  RPSP-class, ≈ 150 cycles per voice in stereo (RPSP saves cycles by running only the mid).
  Four S950 voices on one core with DARK REV would need re-measuring against the load audit.
- **Ring:** two kernels deep behind the play position; to be checked against the 64-frame
  ring at 2×.

## The listening pack

[S950 Recording Rate](https://claude.ai/artifact/DgsRKH6TY7vf7q4553yUQ2), from
`tools/varispeed_emus_s950_rates.py`. The synthesized beat and its wide version, 78 / 104 /
130 / 156 BPM. The clips:

- OT;
- S950 40 kHz (the shipped twin);
- S950 32 kHz and 22 kHz (B, full);
- S950 22 kHz cheap (A, 24 taps).

The full model is checked against the shipped kernel at 40 kHz: within 0.4 dB per band at
104 and 130, and 1.1 dB at 156. At 78 it is darker above 16 kHz, because a real 40 kHz S950
cannot keep source content above 20 kHz. The shipped model keeps a −12…−17 dB remnant of it,
which lands at 15–16.5 kHz when pitched down. That is a small inaccuracy in the shipped
model; B fixes it, A does not.

Band levels against OT (beat), from the pack's manifest:

| tempo | 32 kHz | 22 kHz full | 22 kHz cheap |
|---|---|---|---|
| 78 | 12–16k −55, 16k+ −42 | 8–12k −20, above gone | 8–12k −14, 12–16k −31 |
| 104 | 12–16k −4.7, 16k+ −48 | 8–12k −5.4, above gone | 8–12k −5.3, 12–16k −21 |
| 130 | 16k+ −5.2 | 12–16k −9.8, 16k+ gone | 12–16k −9.0, 16k+ −23 |
| 156 | 16k+ −1.9 | 12–16k −3.3, 16k+ −21 | 12–16k −3.4, 16k+ −15 |

"Gone" means the full model's ideal reconstruction. A real tracking filter leaks some images
there.

## Decisions (the user's)

1. **Rate:** 40 (as now), 32 or 22 kHz, by ear.
2. **A or B:** if A and B at 22 kHz sound alike, A wins: no cycle cost, no new structure.
3. **One rate or a choice:**
   - one build-wide rate, the simplest;
   - or more EMUS positions (e.g. OT / S950-40 / S950-22 / SP12; EMUS would grow from 3 to 4
     positions, and the six-detent feel stays);
   - each extra rate is one more table in Y.
4. If B: whether to also fix the 40 kHz pitch-down remnant above.

## Checks for whichever is built

- `repitch_dsp_engine_check.py`: the kernel bit-exact against its twin at the new table or
  structure.
- `repitch_dsp_profile.py`: cycles per voice.
- The KYOTI load-audit setup on hardware (four S950 voices + DARK REV per core).
- An A/B pack of the built kernel (the twin), not the float model.
