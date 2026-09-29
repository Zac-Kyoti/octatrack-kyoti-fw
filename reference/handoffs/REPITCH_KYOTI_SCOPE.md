# repitch-kyoti — build scope

Written Session 106 (2026-09-27). Nothing here is built. This is a scope, not a handoff
from work in progress: read §0, then §1 for the one architectural fact that shapes
everything else.

Markers as in the rest of the repo: ✅ measured, 🟡 inferred/proposed. Borrowed facts
name their source — per `CLAUDE.md`, a borrowed address is a claim until checked against
our own image, and the ones that still need that check are flagged **[VERIFY]**.

---

## 0. CURRENT STATE — read this first

> **FINAL — rev 16, hardware-confirmed 2026-09-29** (`tools/build_repitch_kyoti.py`, tier FINAL,
> `140C_RPK16`; Bugbuild `BUG_RPK16`). Rev 15 fixed the last trig crack (trigs on a frame
> boundary), rev 16 the TSTR switch that kept the other domain's PTCH/QUAN value and the QUAN
> pressed-turn speed (NOTES Session 112 continued (2)–(4)). Everything below is the design record as it evolved from Session 106; the per-rev status notes are history.

**Status (updated Session 106, same day): GATE 1 IS BUILT and statically
verified** — `tools/patch_repitch_kyoti.s` + `tools/build_repitch_kyoti.py` (WIP
tier), image `out/mainos_repitch_kyoti.bin`, syx `140C_RPK1`. Cave
`0x400d6f80..0x400d76fc` (1916 B), 7 detours + 8 descriptor pokes, 0 strays.
**NOT flashed.** The increment builder and resolver are **proven in-emulator**
(`tools/repitch_probe_kyoti.cpp`, Musashi `ot::Machine` over the real firmware
code: 560 feature-off cases bit-identical to stock, 1400 repitch cases equal
to an independent QUANT/fold/tag model, guards + resolver + bucket edges
green, SP balance checked every run). Unvalidated: the UI draws and hardware. User decisions folded in: modes are **RPCH /
RPS9 / RPSP** (RPS9 was RP12 below). **AUTO semantics revised twice:** the
S106 AUTO-always-RPCH decision was superseded in S107 after checking the
manual's contract — **ATTR offers REPITCH/RPS9/RPSP (raw 4/5/6) and AUTO
applies each sample's own mode**, re-resolved live from the binding. Flash 1
also exposed that page-1 dial renderers bypass the descriptor widget column
(four hardcoded sites, shimmed, formatter-keyed) and the dial caption now
swaps PTCH↔QUAN at draw time via the descriptor name field.
Design deltas vs the scope as first written, all verified against the image:

- **QUANT needs NO editor hook.** The PTCH slot edits a plain ui value
  (min 4, count 121, default 64 = neutral; the record word is `ui<<8`) through
  descriptor metadata — `E+0x00`'s `0x40038d94` is a *randomizer*, not the
  edit path. QUANT is a read-side bucketing of ui (15-wide buckets, neutral
  centred in 1/1), captured in `pitch_gate` from the *composed* word, so
  **QUANT is p-lockable and scene-morphable for free**, legacy projects load
  as 1/1, and leaving RPCH restores plain PTCH with whatever the knob holds.
- The octave-fold runs in the 16-bit integer domain *before* any division
  (`D <<= 1` while `N > 2D`), so the ratio stays exact; clamp is
  `INC_MAX−4` so the 2-bit mode tag can never exceed stock's 2.0 ceiling
  (16,128-case rational-reference grid: worst error 4 LSB of Q26).
- The 7-position TSTR widget is the stock 5-position body (372 B,
  position-independent — absolute jsr/lea only) cloned into the cave with two
  words patched (bound `moveq #4→#6` at +0x54, icon-table lea at +0xe8);
  glyphs keep stock's visual language (17×7 bordered box, dithered field,
  clear cell at stride 2). Formatter ABI decoded: `fmt(buf, value)`,
  tail-jump to sprintf `0x40013a08` with the label replacing `value` at
  `8(%sp)`.
- `d3` carries `bpm24 | modeoff<<16 | quant_idx<<24` from `rate_gate` through
  `pitch_gate` to `rate_hook`; the finished increment's low 2 bits carry
  modeoff (gate-2 pre-staging; the stock-collision question in §4 stands).

Every `[VERIFY]` item below is now ✅ byte-verified (descriptor fields, widget
family, icon tables, all 7 detour sites' displaced bytes). Remaining before
PREVIEW: an emulator pass (page draw + increment oracle) and the first flash.

The original scope follows, kept as written apart from the mode rename.

The feature: extend octabam's REPITCH concept into a multi-mode tempo-following
varispeed playback mode with a quantised ratio control.

- **Baseline** is octabam's `modules/repitch/` (their image OCTABAM81, working on an
  MKII 2026-09-16), written by **Jannik Aßfalg (repeat98)**. ~~Concepts only~~ —
  *corrected 2026-09-29:* the build adapts his ColdFire code (tempo-source routine,
  all seven hook sites, the TSTR label formatter) and his probe scaffold; see
  `CREDITS.md`. Our build is its own module.
- **Two features, not one:** (a) `QUANT`, a quantised ratio control, pure ColdFire,
  zero DSP risk; (b) three interpolation character modes, which need DSP work.
  **They are separately shippable and should be separately shipped** — see §6.
- **Build against KYOTI_V1.0, not V1.1.** V1.1 has 64–332 B of cave left (§5).
- **The one unsettled question** is the per-track mode channel across the
  ColdFire→DSP boundary (§4). Settle it before writing any mode code; if it has no
  answer the character modes degrade to a single global mode, which is a real feature
  regression and changes whether they are worth building at all.

---

## 1. The architectural fact that drives the scope ✅ (measured this session)

**Interpolation happens on the DSP56300, not the ColdFire.**

octabam's existing REPITCH is a pure ColdFire control-plane patch: 7 detours, no signal
code. It changes the playback *increment* and forces the voice renderer onto the dry
path; the reconstruction algorithm is whatever stock already does. So the baseline mode
is free, and **every other mode requires cutting DSP program words.**

Verified against our own image (`out/raw/section_3_MAIN_OS.bin`, sha256 `164f3122…`,
load base `0x40000400`) and against payload A of the DSP program:

**(a) The ColdFire does format conversion only, 1:1, no interpolation.** ✅
The dispatch at `0x40008752` (forward) / `0x400087b6` (reverse) is four straight-line
copy loops — 16-bit mono duplicated to L/R, 16-bit stereo, 24-bit mono, 24-bit stereo —
all sequential `move (a0)+` into 32-bit stereo words. No phase accumulator, no
fractional read.

    m68k-elf-objdump -D -b binary -m m68k:cfv4e -EB \
      --adjust-vma=0x40000400 --start-address=0x40008700 --stop-address=0x400087e0 \
      out/raw/section_3_MAIN_OS.bin

**(b) The DSP voice playback engine at `P:0x3a1` is a 2-tap linear interpolator.** ✅
Reproduce the disassembly with octabam's tool:

    cd refs/octabam && python3 tools/build/dsp_disasm_all.py   # -> out/dsp/payload_A.asm

Module `P:0x003a1`, 125 words. `m6 = $7f` at `P:0x3a9` sets a 128-word modulo ring.
`P:0x3fc–0x40a` pre-computes, per output sample, a (ring offset, fraction) pair into a
table from the increment — the phase accumulator is `add x,a` at `P:0x406`, so **the
fraction is derived on the DSP, not supplied by the ColdFire** (this matters in §4).
The interpolation kernel, `P:0x40f–0x41a`:

    000411: move x:(r6)+,x0            ; x0 = s[k]      (L0)
    000412: tfr  x0,a      a1,y0       ; a  = L0     ;  y0 = f  (the fraction)
    000413: mac  -y0,x0,a  x:(r6)+,x1  ; a  = L0 - f*L0 ; x1 = s[k+1] (R0)
    000414: mpy  -x1,y0,b  x:(r6)+,y1  ; b  = -f*R0     ; y1 = s[k+2] (L1)
    000415: move x:(r6)+,x0            ;                  x0 = s[k+3] (R1)
    000416: add  x1,b      r2,r6       ; b  = R0 - f*R0
    000417: mac  y1,y0,a   x:(r5),n6   ; a  = (1-f)*L0 + f*L1
    000418: mac  y0,x0,b               ; b  = (1-f)*R0 + f*R1
    000419: move a,x:(r3)+  y:(r5)+,a
    00041a: lsr  a  b,x:(r3)+  y:(r6)+n6,y1

Four source words read, two output words written: **one stereo output frame per
iteration, 10 instructions.** Textbook 2-point linear interpolation per channel on an
interleaved stereo pair, 24-bit fixed point, 56-bit accumulators. **No oversampling and
no pre-decimation filter** — so pitching up aliases, and at the 2.0 clamp everything
above 11.025 kHz folds.

### Two corrections to inherited documents

- `refs/octabam/docs/firmware/DSP.md` marks "2-tap linear interpolator over a 128-word
  ring" as 🟡 (attributed to Bryan T, 30 Aug 2026). **This session upgrades it to ✅** —
  the kernel above is the evidence.
- `refs/octabam/docs/TIMESTRETCH_PIPELINE.md:272` lists the interpolation method as
  unknown and guesses it is "in the sample format dispatch loops" on the ColdFire.
  **That guess is wrong** — the dispatch is a 1:1 copy (a above). That document's
  addresses are also 0x400 low (it assumed load base `0x40000000`), so the dispatch it
  means is `0x40008752`, not `0x40008352`.

### Consequence for the feature set

Cost is not symmetric in the way the mode list suggests. **Removing** reconstruction
(zero-order hold) and **degrading** it (bit truncation) are cheap or free. **Improving**
it is expensive. §2 prices each one.

---

## 2. Mode set — three ship, one cut

| TSTR | raw | reconstruction | DSP cost | status |
|---|---:|---|---:|---|
| `RPCH` | 4 | stock 2-tap linear | **0 w** | baseline, exists in concept today |
| `RPS9` | 5 | linear + 12-bit truncate | ~4 w | **ship** — "S950/Akai" character |
| `RPSP` | 6 | ZOH + 12-bit + ~26 kHz hold | ~15–20 w | **ship** — "SP-1200" character |
| ~~`RPHQ`~~ | — | 4-point Catmull-Rom | ~2.4× cycles | **CUT** — see below |

`w` = DSP program words. 🟡 all three cost estimates.

### `RPS9` — linear + 12-bit. Ship it first.

> **⚠️ CORRECTION (Session 109, 2026-09-28): the next paragraph is wrong.** Akai's own
> S900 service manual (voice block diagram No. 860913A) shows each voice's 12-bit DAC
> read out by its own programmable clock, followed by a per-voice 6th-order
> switched-capacitor filter, with **no interpolator**. RPS9 as shipped (linear + 12-bit)
> therefore models only the 12-bit storage. RPSP also still lacks the ~26 kHz hold
> this section promised. Both are scoped properly, from manufacturer sources, in
> [`REPITCH_FIDELITY_SCOPE.md`](REPITCH_FIDELITY_SCOPE.md).

The Akai S900/S950 **did** interpolate; that is exactly why detuning on an Akai does not
sound like detuning on an SP-1200. So the correct S950 model is the interpolator already
present plus 12-bit truncation: **one AND mask on the output store at `P:0x419`/`0x41a`.**

It is the cheapest possible character mode *and* the one that makes `RPSP` legible by
contrast. It is also the right **first** DSP change — see §6.

### `RPSP` — SP-1200. Cheap because it removes work.

The SP-1200 has no interpolation at all: it repeats and drops samples at a fixed rate.
In the kernel above the fraction arrives in `y0`; **force `y0 = 0`** and the two MACs at
`0x413`/`0x417` and `0x414`/`0x418` collapse to `a = s[k]`, `b = s[k+1]` — exact
zero-order hold, **fewer cycles than linear.** Add the same 12-bit mask and a hold
counter for ~26 kHz (SP-1200: 12-bit, 26.04 kHz). Nothing new is computed.

⚠️ `y0` is loaded by a *parallel* move (`tfr x0,a  a1,y0`) inside a tightly scheduled
loop. Zeroing it in place risks the pipeline; the safe shape is a branch to a separate
4-instruction copy loop in spare space, selected once per block rather than per sample.

### Why the "cleaner" mode is cut — the arithmetic, not a preference

You asked for a cleaner mode "if possible". It is possible and it is not worth it:

1. **Cycles.** The measured inner loop is 10 instructions per stereo output frame,
   reading 4 words. Catmull-Rom needs 4 input frames per channel = **8 words**, plus
   ~4 mults + 4 adds per channel ⇒ ~24 instructions. 🟡 **~2.4× the voice-engine inner
   loop, × 8 tracks.** DSP cycle headroom is unmeasured in this repo *and* in octabam,
   so this mode alone would require a headroom campaign before a line could be written.
2. **It changes the cross-chip data contract.** Cubic needs an extra frame of history in
   the 128-word ring, so the ColdFire's source-supply count (`d7 = increment × d3` at
   `0x400041c4`) needs a lookahead frame and the `$7e` mask / `m6 = $7f` modulo wrap
   needs re-deriving. That is the expensive class of change — the same class that makes
   §4 the risk it is.
3. **The payoff points away from where REPITCH actually goes.** Pitching *down* (project
   slower than the sample — the common case) has **no aliasing at all**; cubic buys
   ~1.5 dB of droop at 10 kHz. ✅ linear's worst-case (half-sample) response, `sinc²`:

       1 kHz −0.01 dB   10 kHz −1.50 dB   15 kHz −3.44 dB   20 kHz −6.34 dB

   The audible problem is pitching *up*, and **cubic does not fix it** — up-pitch
   aliasing needs a pre-decimation filter, a different and much larger job.

**Cheap substitute, if a clean mode is still wanted:** a 2-tap boxcar pre-average on the
source when speed > 1. ~3 DSP instructions, 🟡 roughly 6 dB off the worst up-pitch fold.
Make it automatic inside `RPCH` rather than a fifth enum value. Stretch goal, not scope.

---

## 3. UI and storage

Shape follows octabam's REPITCH so the module reads as a sibling, plus two new controls.

### TSTR enum 5 → 7

`OFF AUTO NORM BEAT RPCH RPS9 RPSP`, raw 0–6. Existing raw numbers untouched, so saved
projects load unchanged; a project saved with a new mode stores 4/5/6, which a stock OS
does not know (🟡 SETUP: blank value + granular playback; ATTR: `ERROR`).

**Widget problem.** ✅ (octabam `docs/firmware/PARAM_PAGES.md` + `REPITCH.md`)
**[VERIFY against our image before relying on it]** — stock's select family is
2/3/4/5 positions only: `0x40046f10`, `0x40046d9c`, `0x40046c28`, `0x40046ab4`. One
shared body differing in a `cmp #N-1` bound and a 17×7 icon table (`0x400be2f2`,
`0x400be2fa`, `0x400be306`, `0x400be316`); a value past the bound draws nothing.
octabam's REPITCH already spends the 5-position twin, which stock references nowhere.
**There is no 7-position widget in stock.**

- **(a) Author one** — new entry point (`cmp #6` + pointer to our own icon table) plus
  7 icons at 17×7 ≈ 105 B data + ~40 B code = **~145 B**. Recommended; the icon row is
  the OT's visual idiom.
- **(b) Fallback** — a plain labelled value through the TSTR formatter's existing 8-byte
  stack buffer. ~0 extra bytes, loses the icons. Take this if the build ends up against
  the V1.1 budget.

### `QUANT` lives on the reclaimed PTCH slot

This is the design decision worth defending. PTCH is already disabled and drawn empty on
a REPITCH track (octabam's `pitch_gate` at `0x4000409e` + `ptch_widget` on slot 0).
Rather than leave a dead knob and add a control elsewhere, **draw `QUANT` there**:

- No new parameter slot, no new page, no new editor, no change to the PLAYBACK SETUP
  window record (`0x400bb7c8`, editor `0x4003a474(slot, delta)`).
- It is the correct knob: `QUANT` moves pitch and rhythm together, so it belongs where
  a hand reaching for PTCH already goes.
- It **removes** the existing dead-knob wart instead of adding a second one.
- **Storage for free.** The PTCH word at per-track record `+0` is 16 bits and unused
  under REPITCH. Store the `QUANT` index there: saved projects carry it with no new
  project-file field and no parser change — the same philosophy as `TSMODE=4`.

**Eight positions** (knob `0x400479b4` + a text formatter; every label fits the 8-byte
buffer). `1/1` is today's behaviour, so it is the default and the module stays compatible
with itself:

| `QUANT` | cents | interval | loop length | cycle closes | feel |
|---|---:|---|---|---|---|
| `1/2` | −1200 | octave down | 2 bars | 1 pass / 2 bars | half-time |
| `2/3` | −702 | just P5 down (3:2) | 3/2 bars | 2 pass / 3 bars | 3-over-2, slow |
| `3/4` | −498 | just P4 down (4:3) | 4/3 bars | 3 pass / 4 bars | 4-over-3, slow |
| `1/1` | 0 | unison | 1 bar | 1 pass / 1 bar | locked 1:1 |
| `5/4` | +386 | just M3 up (5:4) | 4/5 bars | 5 pass / 4 bars | quintuplet |
| `4/3` | +498 | just P4 up | 3/4 bars | 4 pass / 3 bars | dotted-8th |
| `3/2` | +702 | just P5 up | 2/3 bars | 3 pass / 2 bars | triplet |
| `2/1` | +1200 | octave up | 1/2 bars | 2 pass / 1 bar | double-time |

Loop lengths and cycles assume a sample loop of one bar of its own content. With
`QUANT = p/q`, loop length is `q/p` bars and the cycle closes after **p passes over
q bars** — every value is rational, so **none of them drift.** That is the whole point of
quantising: the interval and the polyrhythm are the same ratio, so they agree.

**Tuning note, not a bug.** These are *just* intervals — pure against themselves, off
12-TET. Octaves, fourths and fifths are within 2 cents (≈0.7 Hz beating on a 440 Hz
root) and read as slight chorusing. **Thirds are a colour decision:** 5/4 is 13.7 cents
flat of ET (≈4.4 Hz beating), clearly audible against a 12-TET synth on sustained
material. Fine solo or over percussion, awkward in a chord. Worth a line in the README.

### ⚠️ `QUANT` must be clamp-aware — the one place this fails quietly

The speed clamp is `INC_MAX = 0x08000000` (2.0 in the Q26 increment; octabam's
`repitch.s` `rate_hook`). If `R × p/q > 2.0` the clamp silently destroys the rational
relationship and **the polyrhythm degenerates into drift** — the exact failure the
quantisation exists to prevent. `QUANT` must octave-fold (halve until it fits) or refuse
the value. ~10 instructions in `rate_hook`. **Do not ship without this.**

### Unchanged from octabam's REPITCH

ATTR `TIMESTRETCH` gains the same three values at raw 4/5/6 (extends the existing
`attr_label` / `attr_up` / `attr_down` detours at `0x4006e71c`, `0x4006ee56`,
`0x4006ef7c` — **no new sites**); applies when track TSTR is `AUTO`; RATE still applies,
so tape stops keep working; PICKUP is not offered REPITCH; a sample without a tempo in
30..300 BPM (BPMx24 720..7200) plays as stock.

---

## 4. The per-track mode channel — THE RISK. Settle this first.

`P:0x3a1` serves all voices from a per-voice parameter block. A per-track mode needs a
flag crossing the ColdFire→DSP boundary. Options, cheapest first:

1. 🟡 **Tag the low 2 bits of the Q26 increment.** Zero ABI change: the ColdFire already
   writes the increment to state `+36` (states `0x80004898 + 40·t`), and the DSP already
   reads it as `l:(r4)+` for `add x,a` at `P:0x406`. Precision cost: 2 bits of Q26
   ≈ 6e-8 per sample ≈ **0.03 samples over a 10-second loop**, non-cumulative across
   re-trigs — inaudible. **Unverified:** needs a check that nothing else reads those bits
   and that the ColdFire source supplier (`0x400041c4`, `d7 = increment × d3`) tolerates
   it. Note the increment is explicitly shared by the ColdFire supplier and the DSP voice
   command, so both sides see the tag.
2. 🟡 **Steal spare high bits of an existing block field.** The block reads at
   `P:0x3b2–0x3f7` mask with `y0 = $ff` and shift by `#$10` / `#$a` — packed subfields,
   so spare bits may exist. Cheap if they do. Needs a scan.
3. **Add a field to the per-voice block.** Correct and expensive: changes a layout both
   chips agree on, i.e. the same class of change that got cubic cut in §2.

**If all three fail the fallback is a single global mode** — every track gets the same
character. That is a real feature regression, and it changes the value of the character
modes enough that you should know before writing them. Hence the ordering in §6.

---

## 5. Byte budget

### ColdFire — ✅ figures from `reference/kb/caves.md` and `reference/MERGE.md`

Free zone `0x400d64da … 0x400d7c3c` = **5986 B**, "contested and effectively full",
shared with octamax / octabam / midisc / octalab. **Read `caves.md` before naming an
address** (CLAUDE.md hard constraint; two projects have bricked units here).

| item | bytes |
|---|---:|
| repitch logic (7 detours + cave body), ported | ~600 |
| `QUANT`: ratio table, exact p/q multiply, octave-fold, 8-string formatter | ~150 |
| 7-position TSTR widget + icon table (option **a**) | ~145 |
| ATTR labels, 3 modes | ~60 |
| mode → increment tag encode | ~20 |
| **total** | **~975 — budget 1.2 kB** |

🟡 every row is an estimate; the ~600 B baseline is inferred from octabam's 279-line
`repitch.s` plus 56 B of detour stubs, not measured.

| target | free | verdict |
|---|---:|---|
| **on top of KYOTI_V1.0** (free run at `0x400d6f80`) | **3196 B** | ✅ comfortable |
| on top of V1.1 (RELOAD3 2104 B + DIRECT JUMP V7.0.1 1980 B) | **≈ −888 B before repitch** (V6's 758 B gave +332 B) | ❌ needs a second zone |

**Build against V1.0.** V1.1 no longer fits one zone even before repitch (DIRECT JUMP V7.0.1's cave is 1980 B; both V1.1 mods are FINAL as of 2026-09-27).
If it must coexist with V1.1: second zone `0x400d2ee6` (314 B) plus midisc's published
D-region pads `0x400d347e..0x400d34cf` (81 B) and `0x400d352d..0x400d356f` (66 B) — and
per `MERGE.md`, a second zone means the builder must pack multiple ranges and assert the
result, not hand-copy addresses.

### DSP — ~25–30 words total 🟡

- Payload A internal P is contiguous, top `P:0x01fdf`. `P:0x2000` is **executable and
  hardware-proven** (a relocated CHORUS ran on a unit — octabam `DSP.md`). Upper bound
  unmeasured.
- This repo's own precedent is **donor slots**: **SIDECHAIN3_CROSS** (the finalized
  sidechain build — `tools/build_sidechain3.py`, outputs `out/mainos_sidechain3_cross.bin`)
  donates **SPRING REVERB** (id `0x15`, FX2-exclusive), whose module measures **1063
  words**. ✅ 30 words is trivial against that. A donated effect loads as `NONE` in the
  UI (Session 91), which is the real cost — worth avoiding if `P:0x2000` proves out.
  ⚠️ `tools/patch_sc_dsp3.asm:226` still carries a **stale** `SPATIALIZER's 261w donor`
  comment from the superseded donor; `build_sidechain3.py:163` is the correct record
  ("the old SPATIALIZER donor"). Do not size a DSP cave from that comment.
- ⚠️ **`P:0x3a1` has no slack** (125 words, contiguous neighbours). The shape of the work
  is: jump out to spare space, dispatch on mode, jump back — **not** in-place expansion.
- Do not assume octabam's "507 free words in the DELAY SERVER slot" (`dsp/alias_probe.asm`)
  applies here: that is *their* rig, where BusDelay is a placeholder. In a stock-derived
  image that slot holds the real delay.

---

## 6. Build order — each gate independently useful

1. **ColdFire only, no DSP.** Full 7-value enum, widget, ATTR labels, `QUANT` on the
   PTCH slot, clamp-aware octave-fold. All three modes resolve to the *same* linear
   playback. ~80 % of the bytes, 100 % of the UI risk, **zero DSP risk**, and verifiable
   entirely under the port — octabam's `verify_repitch.py` increment oracle already
   checks 9,000 combinations against stock, and the same shape covers `QUANT`.
   **`QUANT` alone is a shippable feature and should be flashed on its own.**
2. **Prove the increment tag (§4).** A DSP probe that reads the low 2 bits and publishes
   them somewhere visible; octabam's `dsp/xmem_probe.asm` and `dsp/page2_probe.asm` are
   the idiom. Settle §4 here, or adopt the global-mode fallback knowingly.
3. **`RPS9`.** One mask. The smallest possible DSP change, immediately audible, and it
   proves the entire cross-chip chain end to end.
4. **`RPSP`.** ZOH (branch to a copy loop, not an in-place `y0` zero) + hold counter.
5. *Optional:* the 2-tap up-pitch pre-average from §2.

### Two recommendations against the obvious order

- **`RPS9` before `RPSP`**, even though SP-1200 is the mode actually wanted. It is a
  ~4-word change that validates the whole mode path; if the tag scheme is broken you
  find out for nearly nothing instead of after writing the hold logic.
- **Do not bundle gate 1 behind the character work.** `QUANT` with no new modes is a
  genuinely novel control — just-intonation intervals and closing polyrhythms from one
  knob, with none of the DSP risk. It is the part of this build most likely to survive
  contact with hardware.

---

## 7. Open questions

- §4, the mode channel. Everything downstream of gate 2 depends on it.
- DSP cycle headroom is unmeasured. Not blocking for gates 1–4 (ZOH is cheaper than
  linear; a mask is free), but it is the reason cubic is cut, and it would have to be
  measured before that decision could be revisited.
- The widget family addresses in §3 are octabam's measurements, not ours. **[VERIFY]**
- Slices and the recorder buffers: octabam's REPITCH README lists them as unmeasured on
  their side too. Inherited unknown.
- Whether `QUANT` should be per-track only, or also settable per sample on the ATTR page
  the way `TIMESTRETCH` is. Per-track is more useful live; per-sample is more consistent
  with where the mode enum lives. Not decided.
