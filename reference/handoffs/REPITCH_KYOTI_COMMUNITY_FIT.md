# repitch-kyoti rev 11 — implementation choices vs. the "typical" SP-1200 / S900-S950 sound

Written Session 110 continued (2026-09-28), at the user's request, to be citable later.
Answers: *why did RPS9/RPSP land on these specific parameters, and does that match what
the sampling community actually considers the iconic sound of each machine?* No code
changed to produce this — it is a summary of rev 11's design choices
(`reference/handoffs/REPITCH_FIDELITY_SCOPE.md`, `tools/repitch_engine_model.py`)
checked against community sources (search-engine summaries of Gearspace, the dxarmy
SP-1200 forum, MPC-Forums, and plugin-maker writeups — the forum pages themselves
blocked direct fetching, so treat these as consensus impressions, not measurements).

> **FINAL — rev 16, hardware-confirmed 2026-09-29** (`tools/build_repitch_kyoti.py`). This page
> describes rev 11; since rev 14 RPSP is heard through the SP-1200's channel 1/2 filter
> (`REPITCH_SP_CH12_SCOPE.md`), and rev 12 retuned RPS9 (`REPITCH_FIDELITY_SCOPE.md`).

---

## RPSP (SP-1200)

**Copied straight from E-mu's own service manual, and confirmed by the community as the
core of the sound:**
- the fixed 26.04 kHz clock
- repeat/skip pitch changes on the SP's own grid (its 7-bit adder-carry mechanism)
- 12-bit storage
- a stepped output with no smoothing

The community consistently credits exactly these three things — 26.04 kHz, 12-bit, and
skip/repeat pitching — for the SP's grit. The classic move was sampling a 33 rpm record
at 45 rpm and tuning it down on the SP; that slow-down is where RPSP's character is
strongest, and QUAN 3/4 (0.75×) lands almost exactly on the ~−5 semitones producers used
to undo 45→33. **Verdict: matches.**

**Input (anti-alias) filter, ~4th order around 11 kHz:** E-mu's manual only says "on the
order of 42 dB/octave, below half the sample rate" — the component values were not
recovered from the schematic. This is a reasonable guess, not a measurement, and the
community doesn't discuss this stage at all (it isn't audible the way the output filters
are). **Verdict: unverified, low community salience either way.**

**Output channel 5 — the weakest choice, and it does not match the iconic sound.** I
picked channel 5 as a mid-brightness default, not because anyone prefers it. Community
consensus on the SP's 8 outputs:
- **Channels 1–2** are the iconic ones: a dynamic SSM2044 filter that snaps open on each
  hit and closes over ~1 ms, giving the "murky filtered basslines" and thumpy kicks
  people mean by "the SP sound."
- **Channels 7–8** are raw and unfiltered — the usual choice for the dirtiest drums.
- **Channels 3–6** are described as subtler, "crispy," progressively brighter.

Channel 5 is a defensible neutral middle, but it is not what the community calls
classic. **Verdict: does not match the most-desired sound; 1–2 (dynamic) or 7–8 (raw)
would.** Building the 1–2 dynamic filter is the bigger job (needs a note-on signal from
the ColdFire, which the DSP kernel doesn't currently get); switching the fixed default to
7/8 costs nothing.

**Exact QUAN ratios instead of the SP's true 1/128 semitone grid:** inaudible difference,
and it keeps tempo lock, which the real machine never offered. Not a community-sound
question — a deliberate tradeoff for the tempo-following feature this whole module is
built around.

**Allowing 1/2 and 2/1** (outside the SP's ±5-semitone *software* range, inside its
*hardware* range): harmless; no community objection either way.

---

## RPS9 (Akai S900/S950)

**32 kHz recording rate (12.8 kHz bandwidth) — a plausible default, not a canonical one.**
There is no single "correct" S950 rate: it went up to 48 kHz (19.2 kHz bandwidth) and in
practice producers picked a rate to trade memory against fidelity. Reports vary widely —
some left it at 20 kHz bandwidth for most material, some deliberately went lower for
crunch, and the 45→33 rpm trick was used on Akais too. 32 kHz sits in the middle: clearly
band-limited without being dull. **Verdict: plausible, not the canonical "crunchy Akai"
setting** — a lower default would better match the grittier end of what people describe,
and this remains a user-facing choice (Q1 in the fidelity scope) precisely because there
is no single right answer.

**Record filter shaped like the MF6CN-50 (6th-order Butterworth, steep):** matches Akai's
own service documentation exactly, and matches the community's description of the S950's
filter as steep and smooth — sitting between the cleaner S1000 and the grittier SP-1200.
**Verdict: matches.**

**Clean pitching, no interpolation smear (each voice's own DAC clock, not a calculated
in-between value):** matches the common account of why Akais detune more smoothly than
the SP. **Verdict: matches.**

**12-bit storage:** matches both machines and every community account of them.
**Verdict: matches.**

**The largest gap: no sweepable filter.** The S950's steep low-pass was a *playable*
instrument, not just a fixed anti-alias stage — many of the filtered loops and isolated
basslines on well-known 90s records reportedly came from sweeping it live, and at least
one community discussion explicitly credits the S950 rather than the SP-1200 for that
sound. RPS9 keeps its filter fixed at the recording bandwidth. I left the S950's FILTER
control out on the reasoning that the Octatrack already has its own per-track filter —
but the OT's filter doesn't have this steep, smooth, non-resonant Butterworth shape, so
the specific Akai move isn't actually reproduced by relying on the OT's filter instead.
**Verdict: gap — this is arguably the most-requested Akai trait and the one rev 11 lacks.**

**Not attempted, and not what RPS9 is:** the S950's offline cyclic timestretch, whose
pushed-past-its-limits artifacts (metallic, phasey, stuttering) defined a lot of 90s
jungle/drum-and-bass production. That's a distinct, well-loved sound in its own right and
would be a separate mode, not a tweak to RPS9's varispeed engine.

---

## Summary table

| Choice | Matches the typical/desired sound? |
|---|---|
| SP fixed clock, skip/repeat pitching, 12-bit | **Yes — core of the sound** |
| SP pitch-down behavior (QUAN 3/4 ≈ 45→33 rpm) | **Yes** |
| SP input filter ~11 kHz | Plausible guess; no community data either way |
| SP output channel 5 (current default) | **Partly — neutral, not iconic.** 1–2 or 7–8 are what people mean by "the SP sound" |
| Akai 32 kHz record rate | Plausible middle; real usage varied, crunch came from *lower* rates |
| Akai steep 6th-order record filter, clean pitching, 12-bit | **Yes** |
| No sweepable Akai filter | **Gap — the S950's most-cited creative use** |

**If prioritizing a next revision, in order:**
1. Default RPSP to channel 7/8 (or make it selectable) — near-zero cost, closes the
   biggest gap between the current default and the iconic sound.
2. Add a sweepable steep filter to RPS9.
3. Build the SP channel 1–2 dynamic filter (the SSM2044 + note-on envelope) — the
   larger, ColdFire-touching job, but the single most-requested SP trait not yet modeled.

## Sources

- [Mastering the classic SP-1200 sound (Crates of JR)](https://cratesofjr.blogspot.com/2025/12/mastering-classic-e-mu-sp-1200-sound.html)
- [dxarmy SP-1200 forum: OUTPUTS...FILTERS](https://www.tapatalk.com/groups/sp1200/outputs-filters-t284.html)
- [dxarmy SP-1200 forum: mix out better than 8 outs](https://www.tapatalk.com/groups/sp1200/sp1200-mix-out-better-than-8-outs-t1057.html)
- [Gearspace: what kind of filtering is done in an SP1200?](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/628756-what-kind-filtering-done-sp1200-recreating-12-bit-akai-possible.html)
- [dxarmy SP-1200 forum: sampling at 45 rpm](https://www.tapatalk.com/groups/sp1200/sampling-at-higher-speeds-45-rpm-etc-properly-t924.html)
- [LANDR: the SP-1200](https://blog.landr.com/sp-1200/)
- [Rossum SP-1200](https://www.rossum-electro.com/products/sp-1200)
- [Gearspace: Akai S950 users, how are you using your sample rates?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/175308-akai-s950-users-how-u-using-your-sample-rates-tips-tricks.html)
- [Gearspace: Akai S950 bandwidth vs sample rate](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/871357-akai-s950-bandwidth-vs-samplerate.html)
- [Gearspace: S950, and not the SP1200, the real sound of boom bap?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1067026-s950-not-sp1200-real-sound-boombap-3.html)
- [Classic boom bap and lo-fi plugins: SP1200/S950](https://audioplugin.deals/articles/classic-boom-bap-amp-lo-fi-plugins-sp1200-s950/)
- [MusicTech: waveTracing SP950](https://musictech.com/news/wavetracing-sp950-e-mu-sp1200-akai-s950/)
- [NITELIFE Audio: timestretched jungle vocals](https://nitelifeaudio.com/classic-techniques-timestretched-jungle-vocal/)
- [Mod Wiggler: old-school jungle sample aliasing](https://www.modwiggler.com/forum/viewtopic.php?t=239824)
