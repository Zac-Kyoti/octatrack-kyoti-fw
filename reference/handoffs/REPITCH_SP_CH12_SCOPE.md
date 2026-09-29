# repitch-kyoti — scope: RPSP as the SP-1200's channel 1/2 (dynamic filter)

Written Session 111 continued (2026-09-28), at the user's request, after hearing rev 13:
*"my ears just don't expect the channel 7/8 raw variety of sound when I think of the SP-1200
sound."* Constraint: ideally **no further effect donated** (SPRING is already gone).
**RPCH and RPS9 are locked** (the user: "they sound great") — nothing here may change their
output. No code was written for this scope.

Markers as in `REPITCH_FIDELITY_SCOPE.md`: ✅ manufacturer (E-mu / Rossum) · 🟡 derived by us ·
📎 forum / secondary · ❓ unknown.

## ⏩ rev 14 BUILT (Session 112, 2026-09-28) — emulation-verified, NOT flashed

- **Envelope A** (the user's pick at gate 1): the OT's own AMP level, read on the DSP (X:(x:$20a+8),
  core 1's AMP stage, one frame old), through the SP's diode + 10 µF (τ 0.15 s, updated per hook
  visit); poles at 1.0 kHz × 2^(4·env); 4 stages, resonance 0. ATK/HOLD/REL shape it; with HOLD 127
  the filter stays open (≈ 7/8 with the top rolled off). §4's hit signal was found DSP-side (the
  unpacked per-voice word +$1E, bit 12 — NOTES Session 112); **no ColdFire change**. The fixed-AR
  fallback was not needed; TSNS (§6a) needs ColdFire → not done.
- §3 done as proposed, with full tables (§3a): 593 words over SPRING's five X modules; the canary
  (gate 0a) held on stock and on rev 14.
- **Found and fixed on the way:** DARK REVERB calls a routine inside SPRING's module that rev 10–13's
  cave overwrote (DARK REV was broken on those images); and the crack at every trig start in
  RPS9/RPSP (stale ring audio replayed at the new trig's full AMP) — both fixed in rev 14.
- Cost: RPSP ≈ 173 DSP instructions/sample (rev 13 ≈ 128; §5 estimated 155–170), RPS9 61.
- Build: `out/OCTATRACK_OS1.40C_REPITCH_KYOTI_REV14.syx`, sha256 `217a9c19…`. `RPK_CH12=0` builds 7/8.

---

## 0. Summary

- **What channel 1/2 is.** The same 26.04 kHz, 12-bit, drop-sample staircase RPSP already
  makes, through an **SSM2044 4-pole low-pass** whose cutoff is pushed open on each hit and
  falls back as the sound decays. Channels 1–2 are the only SP outputs with this; the Mix output
  carries them filtered. It is one added stage on the rev 13 engine, not a new engine.
- **Space without a donor: found (static proof; runtime canary still owed).** SPRING's stock
  payload also loads **five X-memory data tables per core that only SPRING's code references**
  (716 words; §3). They are loaded at boot for an effect this image has removed. Moving RPSP's
  table data (189 words) there frees that much DSP program memory — enough for the filter, with
  room left — and RPS9's tables stay exactly where they are.
- **The hit signal: probably already on the DSP.** Every trig reaches the DSP as a per-track voice
  command, and the OT's AMP envelope runs on the DSP. So the filter can likely key off DSP-side
  state with **no ColdFire change**. This needs one tracing session to confirm (§4, gate 0b).
- **Cost:** about +30–35 DSP instructions per sample for an RPSP track (§5).
- **The big unknown is the envelope's exact shape** (§1c): the sources disagree, so the design
  carries 2–3 candidate shapes to a listening gate, and your ears pick.

## 1. What channel 1/2 does

### 1a. Documented (✅)
- **SSM2044 on channels 1 and 2 only** (Rossum product page and QuickStart guide; Wikipedia,
  citing Hyland, *SP-1200: The Art and Science*). The reissue uses the SSI2144, "designed in
  collaboration with Rossum to faithfully emulate that original analog circuit."
- **"The classic SP-1200 sound is duplicated with the resonance slider fully left, and the
  frequency slider centered."** (Rossum reissue QuickStart guide, "Filter Real Time Control".)
  The classic sound has **no resonance**. The reissue's rear sliders set the initial cutoff and
  resonance; the original had fixed trims.
- **The envelopes can be switched off** on the reissue ("boots with the channel 1-2 filter
  envelopes disabled") — so the envelope is a distinct, CPU-driven element.
- **Factory trim** (service manual p. 34): "Short the two test points CNL0 and CNL1 which puts the
  filters into oscillation. Tune the output frequency of each filter to 1.0 kHz."
- **Mix output = filtered channels 1–6 + raw 7/8** (Rossum QSG: "Filtered channel outputs 1
  through 6, channel outputs 7 and 8 … are heard at the Mix output"). Records made from the Mix
  heard a sound's channel filter; raw 7/8 is the exception, not the norm.

### 1b. Our schematic reading (🟡, SK103 p. 16, Session 109)
Two SSM2044s, caps 0.01/0.01/0.01 µF/820 pF; the cutoff control comes from the channel's `GAIN`
line (the 8-bit multiplying DAC's level, which the Z80 also ramps for DECAY) through a diode into
a 10 µF capacitor. Reading: the cutoff **follows the channel's gain envelope**, rising fast on a
hit (diode) and falling as the gain decays or the capacitor discharges (order 0.15 s through
~15 kΩ; other paths exist, so approximate).

### 1c. Envelope shape — conflicting secondary claims (📎)
| source | claim |
|---|---|
| search summaries of dxarmy "Adjusting the 1200's filters?" / derived pages | "a simple AR envelope generated by the Z80 … 5 ms sloping attack, followed by a decay", modulating **both volume and filter cutoff** |
| forum summary (outputs thread) | "starts relatively unfiltered but after about 1 ms the cutoff drops to around 250 Hz" |
| our §1b reading | open on the hit, closing over ~0.1–0.2 s with the gain |

The first and third agree (the cutoff tracks an AR gain envelope). The second is an outlier or
describes a very short DECAY setting. **Settle by ear (gate 1), and by measuring a real ch 1/2
recording if one can be found** (e.g. the SoundCloud "EMU SP1200 filter test").

## 2. Target behaviour for RPSP (proposed)

```
 rev 13 RPSP (staircase at 26.04 kHz, 12-bit, drop-sample, band-limited render)
   └─► SSM2044-style 4-pole low-pass, resonance 0
         cutoff = f_rest × 2^(depth × env)          (exponential, like the chip's CV)
         env    = AR: ~5 ms attack from each hit, then a decay
```
- **Keyed off the OT's own AMP envelope if gate 0b allows** (the SP's filter follows its GAIN
  line, and the OT's AMP envelope is the OT's GAIN): the user's ATK/HOLD/REL then shape the
  filter as DECAY did on the SP. Fallback: a fixed AR envelope started by the trig itself.
- **Constants, not new UI**: f_rest, depth and the decay time are fixed (the "classic" settings).
  Candidates come from §1c and are chosen at gate 1.
- **Replace or add?** The ColdFire cave has 12 bytes left under its ceiling (build output), so an
  8th TSTR position (widget bound + icon + glyph) does not fit today. Recommended: **RPSP becomes
  channel 1/2**, and 7/8 stays reachable by a build switch. A user-facing 7/8 ↔ 1/2 choice is a
  later item that needs ColdFire space first. (The DSP side already has a spare mode code, 3.)

## 3. DSP memory — without donating another effect

Octabam's hardware-checked map (CHIP.md §4): **no free DSP program memory** outside donor
modules. Our cave (671/675 words) sits in SPRING's module after SIDECHAIN3's 388.

**Found (Session 111):** SPRING's stock code references six X-memory data tables that the stock
loader writes at boot. Scanning every program module of both payloads for their addresses:

| payload A | payload B | words | referenced by |
|---|---|---:|---|
| X:0x89a4 | X:0x8464 | 72 | SPRING only |
| X:0x89ec | X:0x84ac | 72 | SPRING only |
| X:0x8a34 | X:0x84f4 | 72 | SPRING only |
| X:0x8afc | X:0x85bc | 116 | SPRING only |
| X:0x8b70 | X:0x8630 | 384 | SPRING only |
| X:0x8cf0 | X:0x87b0 | 27 | SPRING **and** the next module (P:0x1679 / 0x1439) — **off limits** |

So **716 words per core** (0x8afc–0x8cef is one contiguous 500-word run) are loaded at boot for
an effect this image has removed. **Proposal:** rewrite those modules' payload bytes, in the same
guarded way the P cave is written (same load address, same count, stock bytes asserted), to
carry **RPSP's table data** (the 108-word packed virtual-ADC table and the 81-word render
table). zqinit then copies X→Y instead of P→Y (same code shape). This frees **189 P words**;
RPS9's table and code stay byte-identical in P, so its output cannot change. The filter needs
~60–90 words (§5). If even more room is wanted later, RPS9's 144 data words could move too, as a
bit-identical relocation.

**Caveat (CLAUDE.md, "static proof is necessary, not sufficient"):** the scan shows no *code*
reference. A runtime canary is still owed (gate 0a): fill the ranges after boot, then run
project loads, FX changes on both buses, scenes and the reverbs/delays in `ot_emu`, and watch for
any write or read (`--dsp-writes` / a private trace build). Then check on hardware with a
diagnostic build before relying on it.

### 3a. Table fidelity (asked 2026-09-28)
With RPSP's tables in X there is room to store every table in full again (rev 12's layout) —
RPSP 192 + RPS9 256 + render 81 = 529 source words, inside the 716 (runtime copies in Y as today).
**Measured on `isaak.wav`, it would change nothing audible:** rev 13's packing (9 of 32 rows)
and the full tables give the same junk-to-music at 1/1, 0.9 and 0.75, to 0.1 dB, for both RPSP
and RPS9. So do 64- and 128-phase tables. (A finer grid only lowers pure-tone spurs, already at
−43…−49 dB, by ~8 dB.) So restoring full rows is harmless insurance, not an improvement. For
RPS9 (locked) the choice is: leave it byte-identical, or restore rev 12's exact rows (a ≤ −54.6 dB
change, unmeasurable on real material). **Correction:** NOTES "Session 111 continued (2)"
blamed RPSP's extra 4–11 kHz junk at 1/1 on the 32-phase grid; this measurement rules that out.

**Worst case, measured (decision 2026-09-28: restore full fidelity for BOTH).** A full-scale
pure tone at each table's worst frequency, at a ratio that sweeps every fractional position,
does expose the packing: RPS9 −61 dBFS difference at 14.6 kHz (ratio 1.016) and a line 55 dB below
the tone at 10.8 kHz (ratio 0.516); RPSP −68 dBFS, line 57 dB below. That is above the 12-bit
floor (≈ −74 dBFS), so measurable, though not audible. The user's rule: measurable ⇒ restore. Plan:
RPS9 full = 256 source words (+112 over packed), RPSP full = 192 (+84), render 81 → **529 of the
716 X words**; the packed-row expansion code (~48 P words) is replaced by rev 12's plain mirror
copy (~9 words per table). RPS9's output becomes rev 12's exact design (the only deliberate
change to a locked mode, requested by the user).

## 4. The hit signal

The DSP kernel we hook does not know when a trig fires: the ColdFire streams audio and the ring
coordinate runs continuously through trigs (NOTES Session 110). But (NOTES Sessions 9–11, 14):
- `trig_to_voice` (`0x400977cc`) sends every sequencer trig to the DSP as a **voice command**
  (STATIC: `position | 0x10`, FLEX: `position | 0x8010`), queued by `FUN_40005178` and delivered
  by the frame builder (`0x4000bd3c` / `0x4000c8a4`);
- the **OT's AMP envelope runs on the DSP** (a note-off is bit 0x10 of that command; the DSP
  runs the release stage).

So there is DSP-side state that changes at every hit: the command word's arrival and the AMP
envelope restarting. **Gate 0b:** trace it in `ot_emu` (private build with register/memory
logging, as Session 110 did — never the shared binary). The goal is to find where each track's
envelope level/stage and the start command sit on the DSP, whether our hook can read them in the
same frame, and that retrigs, slices and p-locked starts all show. If they are readable:
**DSP-only, no ColdFire change**.
Fallback (ColdFire): a toggle bit set by a hook in `trig_to_voice`'s tail, carried in the tagged
increment (bit 4 of the Q26 increment = DSP y:$40 bit 2; the tag already costs ≤ 12·2⁻²⁶) — costs
ColdFire cave bytes, which are scarce (§2).

## 5. Cost

Budget (octabam CHIP.md, hardware): 4,532 cycles/sample/core, stock ≈ 1,410, ≈ 2 cycles per
simple instruction.

| stage | instructions/sample (est.) |
|---|---:|
| envelope (read/derive, one-pole decay) | 4–6 |
| cutoff → coefficient (exponential; a 33-entry Y table + interpolation, or a short polynomial) | 6–8 |
| 4 one-pole stages × 2 channels (resonance 0) | 16–20 |
| **filter total** | **≈ 30–35** |
| RPSP rev 13 today | 125–137 |
| **RPSP channel 1/2 with the rev 13 render** | **≈ 155–170** |
| … with the cheap box render instead (option, gate 1) | ≈ 100–110 |

The filter sits dark between hits, which is also where the box render's folds (13–18 kHz) would
be removed. Whether the band-limited render is still needed through a channel 1/2 filter is a
measurement at gate 1: it matters only in the milliseconds the filter is open.

Y memory for state: ~10 words per track (4 poles × 2 channels, envelope, previous-command/level)
in Y:`$F48–$F7F` (free on stock per octabam's probe, beside our `$E00–$F40`).

## 6. Gates

- **0a — X-table canary** (emulator, then a hardware diagnostic): SPRING's five exclusive X
  tables are untouched at runtime.
- **0b — hit/envelope observables** (emulator trace): where the DSP holds each track's AMP
  envelope and start command; readable from our hook; timing vs the frame.
- **1 — model and listening**: the SSM2044 stage in `tools/repitch_engine_model.py` (float +
  integer twin) with 2–3 envelope candidates from §1c. Render `isaak.wav` (90 and 120 BPM) and
  a drum loop through each, next to the rev 13 7/8 render. **You pick one.** Also decide the
  render: the rev 13 render or the cheap box.
- **2 — DSP**: tables to X, the filter, the hit signal; `repitch_dsp_engine_check.py` bit-exact
  (the twin gains the filter), mode switch, full firmware in `ot_emu`. RPCH/RPS9 outputs must be
  sample-identical to rev 13.
- **3 — build, flash, listen.**

## 6a. UI: none needed; TSNS as an optional cutoff offset
The original SP-1200's channel 1/2 cutoff and resonance were fixed factory trims; only the
Rossum reissue added rear sliders ("classic" = resonance fully left, frequency centred). So the
core build uses fixed classic constants. Optional (after the core works): playback page 2's
**TSNS** has no function in the repitch modes and is p-lockable/LFO-able; it could be the initial
cutoff offset (64 = classic). **Gate 0c:** does TSNS already reach the DSP per track (the
timestretch engine's own parameter)? If yes, the DSP reads it — no ColdFire change; the label
stays "TSNS" (a relabel costs ColdFire cave bytes; 12 left). If no, defer (ColdFire space).

## 7. Not in this scope
A user-facing 7/8 ↔ 1/2 selector (needs ColdFire cave space); resonance control; channels 3–6 (their fixed filters are already modelled in
`sp_channel_filter()` and could reuse this work later).

## Sources
- Rossum SP-1200 product page: <https://www.rossum-electro.com/products/sp-1200>
- Rossum SP-1200 Reissue QuickStart Guide:
  <https://cdn.shopify.com/s/files/1/0277/4548/4865/files/SP-1200_Reissue_QSG.pdf>
- SP-1200 Owner's Manual (§1F, tuning):
  <https://archive.org/stream/synthmanual-emu-sp-1200-owners-manual/emusp-1200ownersmanual_djvu.txt>
- SP-1200 Service Manual (trims p. 34; theory p. 41):
  <https://archive.org/stream/emu-sp-1200-service-manual-1987/Emu-SP-1200-Service-Manual-1987_djvu.txt>
- Wikipedia, E-mu SP-1200 (citing Hyland 2011): <https://en.wikipedia.org/wiki/E-mu_SP-1200>
- 📎 dxarmy, "Adjusting the 1200's filters?":
  <https://www.tapatalk.com/groups/sp1200/adjusting-the-1200-s-filters-t561.html> (not fetchable;
  quoted via search summaries)
- 📎 dxarmy, "sp1200 mix out better than 8 outs":
  <https://www.tapatalk.com/groups/sp1200/sp1200-mix-out-better-than-8-outs-t1057.html>
- Octabam, `docs/firmware/CHIP.md` §4 (DSP program memory), §6 (Y map) — `refs/octabam/`
