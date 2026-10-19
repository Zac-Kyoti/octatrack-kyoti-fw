# SIDECHAIN_COMPRESSOR: MON declick + HP/LP key filters (scope, 2026-10-19)

Status: **§1 (MON declick) built, emulator-verified, NOT flashed** (NOTES 2026-10-19). §2–3: scope,
with the layout decided (§3). Read against origin/main `99a1319`
(`tools/patch_sc_dsp3.asm`, `tools/patch_sidechain.s`, `tools/sc_tables.py`,
`tools/build_sidechain_compressor.py`, `octabam-modules/sidechain-compressor/`,
`octabam-modules/mute-modes/patch_softmute.s`).

## The asks

1. **MON declick.** Page 2's MON switch clicks. MON is an audition aid, not a performance
   control, so a very fast fade is fine. The aim is cosmetic: no pop.
2. **Replace the bipolar KFLT with two filters**: a high-pass (rumble) and a low-pass (top),
   which together can isolate a band. No resonant peaks. HP about −18 dB/oct, LP gentler
   (−12 or "−8"). The two must not cross. The user's first proposal
   was `RMS · KEY · KGN · KFHP · KFLP · MON`; decided: §3.

---

## 1. MON declick

### Why it clicks today

`moncommit` (dispatcher per-track commit, A `P:0x50e` / B `P:0x303`) replaces the track's
committed block `X:0..$1f` with the processed key stash whenever `MON_ON[track] == $10000`.
It is a hard swap between two unrelated signals at a block boundary. Session 76 (4) judged it
"PFL-style, leave it". With a fast fade accepted, it can be fixed.

### Mechanism (recommended)

A **linear crossfade in `moncommit`**: `out = dry + g·(key − dry)`, with `g` ramping 0↔1 at a
fixed step per sample. The default is **64 samples (4 blocks, ≈1.45 ms)**, set by one
constant, with an A/B listening pack at 32/64/128 samples. Fast paths: at
`g = 0`, return as today; at `g = 1`, the plain copy, as today. Steady-state cost is unchanged.
A fade costs about 4 instr/sample on that one track for ~1.5 ms.

A crossfade needs both signals in the same block, so three supporting changes are needed:

| change | why |
|---|---|
| `scdet` stashes the processed key while MON is on **or a fade-out is still running** | so a MON-off fade has a live key to fade *from* (today the stash stops the instant MON turns off) |
| the gen-1 stash is indexed by the **consumer** track (`x:$420`), not the source track | today two COMPRESSORs keying the same source share one stash slot (the last writer wins). "Always stash" would make a MON-off compressor overwrite a MON-on one's audition. Indexing by consumer fixes that, and `MON_KEY` is then no longer needed |
| the freed `MON_KEY[track]` word holds the fade position, `MON_FADE` (0–4 blocks) | no new memory, no change to the declared Y range ($7f0..$7ff in octabam, $7df0..$7dff standalone) |

**`MON_ON` is consumed, not sticky** (built; simpler than the GCNT heartbeat first scoped,
which would alias every 4 blocks). `scdet` arms it (`$10000`) every block MON is on;
`moncommit` reads it and clears it. If `scdet` stops running, the next block fades out. This
fixes an **existing bug, confirmed by code reading** (only `scdet` writes `MON_ON`): with MON
on, changing the track's effect away from COMPRESSOR leaves `MON_ON` set, and `moncommit`
replays a frozen 16-sample stash (a buzz) until the effect comes back. Not yet seen on the
unit.

Edge cases:
- **KEY → OFF while MON is on**: the stash stops updating, so the ≤4-block fade-out replays
  the last block, fading. That is ≈1.5 ms of a repeated block under a fade. It is probably
  inaudible; check by ear.
- **KEY changed while MON is on** (source swap): optionally, run the same fade out and back
  in when the stashed source changes. Not required by the ask.

### Risk

`moncommit` is the hook with the worst hardware history: S59/60 register reuse there hung the
sequencer transport. The multiply needs two of `x0/x1/y0/y1` plus an accumulator. Before
writing it, **audit which registers `func_00034f` and the dispatcher after it read**, on both
payloads, in our own image (CLAUDE.md: a borrowed claim is not a fact). Gate it with
`emu_sc_dsp3*.py` and `ot_emu`, then a HW flash with a transport-heavy test.

---

## 2. Key filters

### Research summary

| reference | key filters |
|---|---|
| Drawmer DS201 (the classic "frequency-conscious" gate; same HP+LP idea, plus KEY LISTEN = our MON) | HP **25 Hz–4 kHz**, LP **250 Hz–35 kHz**; the band between them passes |
| SSL Bus+ | side-chain HPF **12 dB/oct**, OFF then 0–300 Hz in 10 Hz steps |
| SSL Bus Comp MK3 / 500-series | stepped side-chain HPF, 30–185 Hz |
| FabFilter Pro-C | side-chain low/high cut with slopes up to 96 dB/oct plus a mid band |

Hardware detector filters are almost always **Butterworth-type (maximally flat), 12 dB/oct**,
and the HP is by far the most common one. An 18 dB/oct HP is steeper than most hardware, and
it fits the "ignore the kick's sub" goal well. **"−8 dB/oct" is not available**: a plain
filter's slope is a multiple of 6 dB/oct (one pole each). The real choices for the LP are 6
or 12; I recommend **12**, because a 6 dB/oct LP is only −6 dB one octave up and isolates
little.

### Filter type: Butterworth (measured, scipy, fs 44.1 kHz, HP 3rd order + LP 2nd order)

| type | max gain (any setting) | LP step overshoot | 1 oct below HP | 1 oct above LP | band HP 50 / LP 100 peak | 55 Hz kick through HP@100, peak out |
|---|---|---|---|---|---|---|
| **Butterworth** | **0.000 dB** | 4.3 % | **−18.1 dB** | **−12.3 dB** | −1.5 dB | **0.20** |
| Bessel | 0.000 dB | 0.4 % | −12.0 dB | −9.9 dB | −2.9 dB | 0.26 |
| critically damped (cascade of the current one-pole) | 0.000 dB | 0 % | −9.3 dB | −8.5 dB | −3.2 dB | 0.33 |

All three have **no magnitude peak at any setting**: no frequency is ever boosted, so none
"resonates" in the sense the user means. They differ in the time domain. Butterworth's small
step overshoot only shapes the transient that reaches the detector, which the compressor's
own attack/release then smooth. Its rejection is clearly the best: a kick's sub under an HP
at 100 Hz comes through 40 % lower than with the one-pole cascade. That rejection is what
makes the compressor respond tightly. **Recommendation: Butterworth.** The fallback, if DSP
size or time runs short, is a cascade of the existing hardware-proven one-pole (no overshoot,
cheapest, but about half the rejection in dB).

### Structure: TPT (zero-delay-feedback) sections

- **HP (18 dB/oct)** = a 2nd-order TPT state-variable section (damping k = 1, the 3rd-order
  Butterworth pair) × a TPT one-pole, both at fc.
- **LP (12 dB/oct)** = one 2nd-order TPT section, k = √2.
- Mono, on the existing `(L+R)/2` mixdown, written to both channels, as today.

Why TPT and not the old Chamberlin SVF or a direct-form biquad:
- it is stable at every cutoff, so the stability ceiling that killed the Chamberlin SVF in S64
  does not apply;
- a coefficient change mid-signal does not burst, the way direct-form biquads can while a knob
  turns;
- it behaves well numerically at 20 Hz in 24-bit/56-bit.

Coefficients come from one per-step `g = tan(π·f/fs)` table. The derived terms
(`1/(1+g(g+k))` …) are computed **once per block**: about two `div` sequences per block per
instance, as a `do` loop, never `rep` (octabam refuses `rep`; the BP303 rule bans it on
core 0). `g` glides per block the way KGN does today, so a sweep with MON on is zipper-free.
**Implementation risk:** confirm that `tools/dsp_xasm.py` / `dsp_asm` assemble `div` and `do`
correctly. If not, store the coefficients, either at a coarser grid with interpolation or
whole: about 3 words × 160 steps × 2 filters, which is too big, so interpolation it would be.

### Ranges and the no-crossing rule

One shared log grid, **16 steps/octave (¾ semitone)**: `f(g) = 20 Hz · 2^(g/16)`.

| knob | 0 | 1 … 126 | 127 | covers |
|---|---|---|---|---|
| **KFHP** | **OFF** | g = 0…125 → 20 Hz … 4.4 kHz | 4.7 kHz | rumble/sub (20–80), kick fundamental (40–100), body, up to snare/hat territory (cf. DS201 4 kHz) |
| **KFLP** | 80 Hz | g = 32…158 → 80 Hz … 18.8 kHz | **OFF** | kick-only keying (80–150), mids, de-ess-style highs |

Sample points: HP knob 17 = 40 Hz, 33 = 80, 49 = 160, 65 = 320, 97 = 1.28 kHz, 113 = 2.56 kHz.
LP knob 16 = 160 Hz, 48 = 640, 64 = 1.28 kHz, 96 = 5.1 kHz, 112 = 10.2 kHz.

- **OFF is a coefficient, not a code path.** HP OFF runs the HP at ≈5 Hz; LP OFF runs the LP
  at ≈20 kHz. Both are transparent for a detector, and there is no bypass branch to switch
  in and out. **This removes the centre-pop class entirely**: no bipolar knob, no hard
  bypass, no HP re-entry hack. The `r7+$14` "previous block was OFF" flag and the LP/HP
  edge overrides go away.
- **No crossing, enforced in the DSP**: `g_LP_eff = max(g_LP, g_HP + 16)`, so the LP is always
  at least one octave above the HP. In knob terms, LP ≥ HP − 17. At exactly one octave apart,
  the band's peak is −1.5 dB (table above): still a usable, very narrow key. This has to be
  in the DSP, not the UI: p-locks, scenes and FX LFO destinations move each knob on its own,
  so a UI-side "push the other knob" can't guarantee it. The LP display shows its own knob
  value, which can sit below the effective LP while clamped (minor; noted for the README).
- **Formatters** show Hz (`20`, `160`, `1.3k`, `18k`), computed from a 16-entry `2^(i/16)`
  table plus a shift, so as to not spend 256 B of the ColdFire cave on a full table.

### State, size, cost

- **Per-instance state**: 5 filter states + 2 `g` glides = 7 words. `$14` and `$16` are
  reclaimed (`$17` KGN and the `$18` latch stay). That leaves **≈5 words short**. The
  candidates: each instance owns a 0x100-word r7 block (octabam DSP.md), and stock COMPRESSOR
  touches only `$f..$1b` (our disassembly, A `P:0x1aa4`). So `$1c..$70` look free, but **this
  needs a canary** (emulator `--dsp-watch`, then hardware), as with every "unreferenced"
  memory in this project. S76 shelved a cascade for exactly this lack of state.
- **DSP P size**: about +100 code words and a ~160-word `g` table, against the current 384 +
  48 words. The standalone and KYOTI images have SPRING's 1063-word donor to themselves
  (≈630 words slack), so it fits.
- **DSP load**: today a keyed COMPRESSOR is 69 instr/sample (load audit). The new filter adds
  an estimated +15–20 instr/sample (to ≈85–90), against DJ EQ's 306. It does not make a new
  worst case. Measure it with the load-audit meter.

---

## 3. Page layout (decided 2026-10-19)

**`RMS · MON · KEY · KGN · KFHP · KFLP`** (slots 6–11), MON stored **inverted**; a new major
version, with a README disclaimer that older SIDECHAIN projects sound different.

Stock COMPRESSOR's page-2 descriptor, read from our image (E `0x400d5a4a`):

| slot | stock | today | new |
|---|---|---|---|
| 6 | RMS | RMS | RMS |
| 7 | hidden switch, count 2, **default 1** (DSP never reads it: `asr #$10` drops bits 8–15) | empty | **MON**, stored 1 = OFF, 0 = ON |
| 8 | default `0x7f` | KEY | KEY (unchanged) |
| 9 | default 0 | KFLT | KGN |
| 10 | default 0 | KGN | KFHP |
| 11 | default 0 | MON | KFLP |

- **Why MON is inverted:** slot 7 holds 1 in every compressor saved on stock or on SIDECHAIN
  so far (stock's default, never visible). Stored plainly, every old compressor with a KEY would
  come up monitoring. Inverted, all of them come up MON OFF. A custom formatter shows ON/OFF;
  check on hardware that the switch graphic does not draw backwards (fallback: a plain
  two-step knob).
- **KEY stays in slot 8**, so MUTE_MODES' `p1_key` (+38) is unchanged in every form, and
  `sc_norm`'s stock check (KEY > 8) still works. `sc_norm` gains slot 7 (reset to 1 = MON OFF)
  and the new defaults (KGN 64, KFHP 0 = OFF, KFLP 127 = OFF).
- **Old SIDECHAIN compressors load as:** KEY kept; KGN = old KFLT (64 → unity; an old LP/HP
  setting → some gain between −24 and +24 dB); KFHP = old KGN (usually 64 → HP ≈ 300 Hz);
  KFLP = old MON (0/1 → LP ≈ 80 Hz, pushed to ≈ 600 Hz by the no-crossing rule). Audible
  and fixable by re-dialling; this is what the disclaimer covers. P-locks and scene locks on
  slots 9–11 remap the same way.
- **KEY OFF is stock** (decided): no filtering of the compressor's own signal.

---

## 4. Build-family flags

**Standalone / KYOTI**
- New descriptor writes for slots 7 and 9–11, slot 7's enable-bitmap nibble, MON's inverted
  formatter on slot 7 (stock's switch widget is already there), `sc_norm` extended to slot 7.
  The Hz formatters add some CF bytes.
- KYOTI re-pins SIDECHAIN; BUG_SC3X changes. MUTE_MODES is untouched (KEY stays in slot 8).
  KYOTI's ColdFire caves are tight: check room for the formatters.
- The DSP fits SPRING's donor in both.

**octabam**
- The manifest's page-2 `Param` list changes, as do `ptable` (gain 16 + the new `g` table)
  and the DSP section size. Re-run `make check-remix` for `sidechain-compressor`,
  `kyoti-mute-sidechain`, every KYOTI test remix and the official remixes with BP303 and
  VARISPEED: octabam's DSP placer is shared, and P space is contested.
- The new r7 words (`$1c..`) are per-instance state that the ledger does not model as a
  `DspRange`. Check whether octabam wants a claim kind for it, or a note.
- The usage fragment `docs/site/usage/sidechain-compressor.md` and its screenshots change.
  The usual PR checklist applies: THIRD_PARTY pin row, rebase, then the gates.

**Modwerk**
- `resident_dsp.py` SHA-256-pins `patch_sc_dsp3.asm`, the manifest and `sc_tables`, and
  applies exact-text patches (GCNT seed adoption, MON consume) to our asm. This scope
  rewrites `moncommit`'s MON consume path and the whole KFLT block, so **Modwerk's adapters
  need owner (Jannik) review and rework**, not an author bot update. The Y range stays
  `0x7f0 + 0x210`.
- It is a settings-breaking change for Modwerk users' saved projects (§3): version it as a
  major bump, with a release note. MM needs no change.
- Qualification, UI captures and the `sidechain-*-proofs` all re-run.
- Ordering: SC 0.1.3 (window move, waiting on the user's MODWERK_SC013 test) should land
  first. Then this.

---

## 5. Suggested order of work

1. ~~Confirm the stale-MON buzz~~ (confirmed by code reading; fixed by the declick's consume).
2. ~~MON declick alone~~ built and emulator-verified 2026-10-19; HW test pending.
3. RE canary for r7 `$1c..$70` on both payloads.
4. Filter prototype in `emu_sc_dsp3.py` against a numpy reference (bit-exact), plus an A/B
   pack: Butterworth vs the one-pole cascade, on a kick + bass loop.
5. Layout (§3, decided), then standalone → KYOTI → octabam → Modwerk.

## Sources

- Drawmer DS201 operator's manual (key filter ranges): https://www.drawmer.com/uploads/manuals/ds201_operators_manual.pdf
- SSL The Bus+ review, Sound On Sound (12 dB/oct side-chain HPF, 0–300 Hz): https://www.soundonsound.com/reviews/ssl-the-bus-plus
- SSL Stereo Bus Compressor MK3 (stepped HPF): https://providence-sound-and-vision.odoo.com/shop/ssl-bus-compressor-mk3-35333
- FabFilter Pro-C side-chain section: https://fabfilter.com/help/pro-c/using/sidechainsection
- Butterworth vs Bessel overshoot (ADI FAQ): https://ez.analog.com/precision-technology-signal-chains/precision-wide-bandwidth-signal-chains/a/fast-precision-faqs/c/all-fast-precision-tech-notes/FP746/how-can-i-decide-what-filter-approximation-to-use-chebyshev-butterworth-or-bessel-etc
- Filter numbers in §2: scipy `butter`/`bessel` (norm='mag'), fs 44.1 kHz, this session.
