# REC_TRIG_MUTE — scope (2026-10-02, research only, nothing built)

**Ask.** `[TRK]` + `[NO]` mutes the held track's **recorder trigs**: the trigs stay in the pattern,
but the sequencer stops firing them. `[TRK]` + `[YES]` unmutes them. This works in any mode and on
any screen, with GRID REC on or off and REC SETUP open or closed. Toasts (user's wording, revised 2026-10-02):
`REC TRIGS MUTED` / `REC TRIGS UNMUTED`. `[FUNC]` + `[YES]`/`[NO]` stay stock everywhere.

**Use case (the user's).** A track has ordinary recorder trigs that fire on every pattern cycle.
`[TRK]`+`[NO]` at any moment: the recording already running finishes its RLEN, and no new
recording starts in later cycles. `[TRK]`+`[YES]`: recording resumes at the next recorder trig.

**Verdict: feasible and small.** It needs two keymap-record repoints, one 10-byte detour in the
step handler, and about 150 B of code plus one state byte. It also fits the full KYOTI V1.0
image, because the code can go into the stock handlers that the repoint makes dead (§4).
Every address below comes from our own disassembly of `section_3_MAIN_OS.bin` (confidence
**C** unless marked).

## 1. What stock does today

### The keys

- The base keymaps (T1 `0x400bfc10`, T2 `0x400c01f4`) send YES `0x31` to `0x4005e4c8` and NO
  `0x32` to `0x4005e25c`. Without the arranger and without PERSONALIZE `DISABLE YES/NO ARM`
  (`0x800000b8`), YES calls `0x4005e294` (ARM) and NO calls `0x4005e0e8` (DISARM). ARM has these
  branches:
  - GRID REC off (`0x460d1736 == 0`) → **ARM ALL** (`0x46c7ff64 = 0x46c803d4 = 0xffff`).
  - GRID REC on and screen `0x460d5db4 == 0` → **ARM TRK**: the active track's sample one-shots
    (bit `t`).
  - GRID REC on and screen `== 3` (**REC SETUP**) → **ARM REC TRK**: the active track's recorder
    one-shots (bit `t+8`).
  - any other screen → ARM ALL.
- **Holding a track key pushes its own input-map layer.** Each track-key record (codes
  `0x10..0x17`) carries the layer `0x400d164a`, whose keys table at `0x400d1594` reads:

  | code | record | press / release handler |
  |---|---|---|
  | YES `0x31` | `0x400d15e2` | `0x400834d8` / `0x400834d8` |
  | NO `0x32` | `0x400d15fc` | `0x40083488` / `0x40083488` |

  (FUNC is keycode `0x2d`: the GRID REC editor tests `is_key_held(0x2d)` at `0x400304fe` to
  toggle the one-shot layer.)
  `0x400834d8`: on press, if the held-track mask `0x460fab40` is non-zero, it ORs `held<<8` into
  `0x46c803d4` and `0x46c7ff64`, sends CC `0x35`, and shows **`ARM REC TRK`**. `0x40083488` ORs
  `held<<8` into `0x46c7fe22` and shows **`DISARM REC TRK`**. **They check neither GRID REC nor
  the screen.**
- So the user's observation holds: in GRID REC with REC SETUP open, `[TRK]`+`[YES]` and
  `[FUNC]`+`[YES]` give the same result. One addition: `[TRK]`+`[YES]`/`[NO]` arms or disarms the
  held tracks' **recorder one-shots on every screen**, not only there.

### The one-shot state (corrects KB rows written in Sessions 9–14)

The three words below are **one-shot arm/disarm requests**, not mute masks. The frame ISR
(`0x4000ac44..0x4000ac80`) applies them to the spent mask:

| word | meaning |
|---|---|
| `0x46c803d4` | arm request: `0x8000184e &= ~req`, then cleared |
| `0x46c7fe22` | disarm request: `0x8000184e \|= req`, then cleared |
| `0x8000184e` | one-shot **spent** mask: bits 0–7 sample trigs, bits 8–15 recorder trigs |
| `0x46c7ff64` | arm-pending mask, which the frame builder's one-shot test excludes |

`memory-map.md` still calls `_DAT_46c7ff64` the "post-FX MAIN mute" and `0x46c803d4` CUE/MUTE.
The toast strings and CC `0x35` show they are the one-shot arm state. The KB should be corrected
when this thread commits.

### How a recorder trig fires

1. **Step handler** `0x4009d1e8` (sequencer task, about 3 frames ahead). For track `d7` it ANDs
   the step bit with masks `0x20`/`0x28`/`0x30` (REC1/2/3) into `d3` bits 12/13/14
   (`0x4009d91a..0x4009d9a0`). Then:
   ```
   4009d9a4: 4a83            tst.l  %d3
   4009d9a6: 676e            beq.s  0x4009da16        ; no recorder trig on this step -> return
   4009d9a8: 243c 0000 091a  move.l #0x91a,%d2
   4009d9ae: 4c07 2800       muls.l %d7,%d2
   ...       writes 0x46c7a9de[t] (length) and 0x46c7a6c0[t] = d3|0x20 (|0x120 if mask 0x38 is set)
   ```
2. **Scheduler** `0x400a33f6`: copies `0x46c7a6c0[t]` into the recorder event slot `0x46c7faa4`
   and clears it.
3. **Frame builder** `0x4000c926`: applies one-shot gating (`btst #8`, the spent mask
   `0x8000184e`, then marks the trig spent) and starts the recording.

**`0x46c7a6c0` has exactly three references in the image:** the step handler's write, and the
scheduler's read and clear. The step handler is therefore the only producer of recorder events,
and gating `d3` there is a complete mute.

Side lead, not needed here: the KB lists mask `0x38` (+`0x41`) as "swing / slide" (**L**). It
feeds bit 8, and the frame builder tests bit 8 for one-shot gating, so `0x38` is more likely the
**recorder one-shot** layer. Confirm it with `pattern-diff` before editing the KB.

## 2. Design

**State.** One byte `RTM_MASK`, bit `t` = track `t`'s recorder trigs muted. It lives in our own
code (as DJ_MODE and RELOAD3's request bytes do), **not** in the scratch RAM at `0x80006a40+`
(CLAUDE.md). The key handler (UI task) is its only writer and the step handler only reads it, so
there is no read-modify-write race.

**Keys:** repoint the two `[TRK]`-layer records, or reuse their bodies in place (§4).
- `rtm_no` (press only, event 1): `held = 0x460fab40`; if 0, return. `RTM_MASK |= held`.
  Toast `REC TRIGS MUTED`.
- `rtm_yes` (press only): `RTM_MASK &= ~held`. Toast `REC TRIGS UNMUTED`.
- The toast is a tail call into `NOTIFY 0x4005a2b8(text, 0x30)`, the same idiom the stock
  handler uses. It is legal here because this is a **key handler**, not the frame path.
- The mask covers **every held track**, as stock does. Holding T1+T3 and pressing NO mutes both.

**Gate:** replace `0x4009d9a4..0x4009d9ad` (10 B) with:
```
4009d9a4: jsr    rtm_gate.l          ; 6 B
4009d9aa: beq.s  0x4009da16          ; 676a -- flags come back from rtm_gate
4009d9ac: nop                        ; 4e71 (d2 is already loaded by the gate)
4009d9ae: muls.l %d7,%d2             ; stock, untouched

rtm_gate: move.l #0x91a,%d2          ; the displaced instruction
          cmpi.l #8,%d7 ; bcc.s 1f   ; guard: only audio tracks 0..7
          btst   %d7,RTM_MASK        ; byte operand, bit d7
          beq.s  1f
          moveq  #0,%d3              ; muted: behave as "no recorder trig on this step"
1:        tst.l  %d3                 ; rts leaves CCR alone
          rts
```
`d0`/`d1` are dead at this point (both are reloaded at `0x4009d9b2`/`b6`). The return path
`0x4009da16` restores all registers with `movem`. ColdFire's ALU is long-only (no `or.b Dn,<ea>`),
so the key handlers do `move.b` / `or.l` / `move.b`.

**Why this gives the use case exactly.** Muting removes only *new* recorder events. A recording
already running was scheduled earlier and runs to its RLEN. A step that would have started a new
recording behaves like an empty step, so it neither starts nor restarts one.

## 3. Behaviour notes for the user to accept

1. **The stock `[TRK]`+`[YES]`/`[NO]` is lost.** That is ARM/DISARM REC TRK for the *held* tracks
   on any screen, including its CC `0x35` MIDI out. Arming and disarming recorder one-shots stays
   available through stock `[FUNC]`+`[YES]`/`[NO]`, or plain YES/NO, in GRID REC + REC SETUP
   (active track only), and through incoming MIDI CC.
2. **One-shot recorder trigs on a muted track stay armed.** They are skipped, not spent, so they
   fire at their next step after unmute.
3. **No on-screen state apart from the toast.** The REC SETUP grid still shows the trigs. An
   indicator (for example on the REC SETUP page) would be a separate v2.
4. **Muting does not stop a running recording.** That matches the request. A recording can still
   be started by hand with `[TRK]`+`[REC1..3]`, which this feature does not touch.

## 4. Space — and how it fits the full KYOTI V1.0 image

Measured from `out/KYOTI/kyoti_v1.0_map.json`: every zone of KYOTI V1.0 is full (CAVE 6 B left,
SAFE 8, PASTE 12, PERS1 12, all others ≤ 11). A new feature cannot get a new cave there.

**Way out:** after the change, `0x400834d8` and `0x40083488` are **unreachable**. Their only
references in the whole image are the press/release fields of the two records above (2 each). A
full-image scan found **0** branches or absolute references from outside into
`0x40083488..0x40083543` (188 B, ends at the next function `0x40083544`). So we **overwrite those
bodies in place**, which means the records do not even need repointing:

| piece | ≈ size |
|---|---:|
| `rtm_no` + `rtm_yes` + shared toast tail | ~80 B |
| `rtm_gate` | ~28 B |
| `RTM_MASK` (+ pad) | 2 B |
| `"REC TRIGS MUTED"` + `"REC TRIGS UNMUTED"` | 34 B |
| **total** | **~145 B of 188** |

This is stock `.text` (the safest memory in the image), not a cave, so the caves.md canary
concern does not apply. The one runtime write is our own `RTM_MASK` byte. `rtm_no` must start at
`0x40083488` and `rtm_yes` at `0x400834d8`, or else the two records get repointed; either way it
has to be asserted. No KYOTI module or `build_kyoti.py` assertion touches `0x40083488..0x40083544`,
`0x400d1594..0x400d1630` or `0x4009d9a4..0x4009d9ae` (grep of `tools/` and `octabam-modules/`).

## 5. Build plan (when the user says go)

- Feature name **REC_TRIG_MUTE** (proposed): `tools/build_rec_trig_mute.py` (standalone, on stock,
  WIP gate + `seal`), source `octabam-modules/rec-trig-mute/patch_rectrigmute.s`. Register the
  thread in `tools/githooks/threads.txt` before the first commit.
- The builder asserts stock bytes at `0x40083488..0x40083544`, at `0x4009d9a4` (10 B), and at the
  two layer records. It also checks that the image has no reference into the reused range other
  than the four record fields.
- KYOTI: add it as a piece placed at the fixed address (`0x40083488`, not a zone) plus the
  `0x4009d9a4` detour. **octabam port, open question:** whether a module can claim a dead stock
  function body as its placement (it is not a `TableGrow`/zone claim). Ask Sam alongside the
  existing schema questions.

## 6. Verification plan

- **Emulator (logic only):** set `0x460fab40`, call `0x40083488`/`0x400834d8` with event 1 and
  check `RTM_MASK` and the toast text. Watch writes to `0x46c7a6c0[t]` across a sequencer run with
  the mask clear vs set: muted → no write for `t`, other tracks unchanged. Use a
  **hardware-exported project with recorder trigs on two tracks** (ask the user; none is in
  `out/fixtures` that I know of).
- **Hardware:** the use case above (a long RLEN finishes after NO, nothing new records in the next
  cycle, YES resumes); T1+T3 held; the other tracks unaffected; FUNC+YES/NO in GRID REC + REC
  SETUP still arm/disarm REC TRK; GRID REC off + FUNC+YES still ARM ALL; one-shot recorder trig
  muted → unmute → it fires.

## 7. Decisions (answered by the user 2026-10-02)

1. **Persistence: volatile.** Power-up = all unmuted (the image byte is 0). The mask survives
   pattern, Part, bank and project changes; nothing in stock touches it.
2. **MIDI mode: must work** — no MIDI gate. Note what that means mechanically: MIDI tracks have
   **no recorders and no recorder trigs** (recorder trigs live only in the audio `TRAC` records;
   the step-handler path above is audio-only, stride `0x91a`). The held mask is the *physical*
   track keys in both modes (`0x460fab40 |= 1 << (keycode - 0x10)` at `0x40083b94`, no MIDI
   offset), so in MIDI mode `[TRK n]`+`[NO]` mutes **audio track n's recorder trigs** — the same
   track stock's `[TRK]`+`[YES]` arms in MIDI mode. ⚠️ If the user means something else by "MIDI
   track recording trigs", ask before building.
3. **Multiple held tracks: all of them**, like stock.
4. **Toasts: `REC TRIGS MUTED` (15) / `REC TRIGS UNMUTED` (17).** Both shorter than the
   hardware-confirmed `QUANT LIVE REC OFF` (18), so no fit risk; strings = 34 B (§4 total drops
   to ~145 B).
5. **Across pattern changes: global (option 2)** — see §8.

## 8. Pattern changes

**Stock does not re-arm one-shot recorder trigs on a pattern change** (static reading, every
writer enumerated; confidence **C** on the list, the behaviour wants one hardware check). The
spent state is **per track, not per pattern**: one word, `0x8000184e`, bits 8–15. Its only writers
in the image:

| site | what |
|---|---|
| `0x400047c2` | boot init (clear) |
| `0x4000ac56` / `0x4000ac76` | frame ISR applying the arm (`0x46c803d4`) / disarm (`0x46c7fe22`) requests |
| `0x4000b972` / `0x4000c970` | frame builder marking a sample / recorder one-shot spent as it fires |
| `0x400a113c` | **STOP-STOP**: clears the whole word unless PERSONALIZE **DIS. STOP-STOP ARM** (`0x800000bc`) is on |

The arm requests come only from YES/NO (`0x4005e294`/`0x4005e0e8`), the `[TRK]` layer
(`0x400834d8`/`0x40083488`), and **placing a one-shot recorder trig** in the GRID REC editor
(`0x40030926`, `0x40060a36`, toast `ARMED`). None of these is on the pattern-switch path
(`0x400a4xxx`), and no block clear covers the word (the neighbouring per-track arrays from
`0x8000182a`/`0x80001842` end at `0x80001849`). So a recorder one-shot spent in pattern A stays
spent after switching to B: B's one-shot recorder trigs on that track do not fire until re-armed
(keys, STOP-STOP, or placing one).

**Our implementation: option 2, global** (the user's lean, and the natural fit). `RTM_MASK` is
our own byte, nothing in stock clears it, and the gate reads it on every step of whatever pattern
is playing. A muted track stays muted through pattern, Part and bank changes until
`[TRK]`+`[YES]`. That also matches how stock treats one-shot state (per track, across patterns).
Option 1 would need an extra hook on the switch body, which DIRECT_JUMP_KYOTI already detours
three times (`dj_a/b/c`), so we avoid it.

Hardware check to add to §6: arm a recorder one-shot in pattern A, let it fire, switch to B with
a one-shot recorder trig on the same track → stock does not fire it. Then the same with the track
muted → still muted in B; unmute → B's normal recorder trigs fire.

## 9. The track status glyph at the screen edges

**Found by emulation** (route A, `--load-project`, with every write to the LCD plane's left
columns logged together with the return addresses on the stack). The renderer is
**`0x4004be88..0x4004c0a4`**, called from `0x4004d87a`. It loops over tracks `d3 = 0..7` and draws
one small bitmap per track, at `x = 1` for T1–4 or `x = 121 - 1` for T5–8, with
`y = 47 - 15·(t & 3)`. It inverts the box for the active track (`d4`). It caches each track's state
(`0x400c0cb8[t]`, active flag `0x400c0c98[t]`, MIDI-mode `0x400c0c94`) and redraws a track only
when that changes, so it is evidently polled. It sets the flush flag `0x46c7c72c = 1` after a
redraw.

**State.** `v = FUN_40000e50(t)` = the voice record `0x800049d8 + 168·t`:

```
d2 = v[0] && !(0x8000184a bit t)      ; playing
d1 = v[1] != 0                         ; recorder live
d0 = v[2] != 0
a4 = d2 + 2·d1 + 4·d0
```

**Bitmaps** (descriptor `{w, h, 1, data, mask}`, column-major, 4 B per column, rows = the top 5
bits). We decoded the pixels:

| a4 | descriptor | glyph | drawn at |
|---|---|---|---|
| 0 | `0x400bb306` | ■ 3×5 | `x+2` |
| 1 | `0x400bb2f2` | ▶ 3×5 | `x+2` |
| 2 | `0x400bb31a` | **+** 3×5 | `x+2` |
| 3 | `0x400bb32e` | **+▶** 7×5 | `x` |
| ≥ 4 | — | nothing (box cleared only) | |
| PICKUP | `FUN_40097168(t)` → 0..4 | the same set plus `0x400bb342` ×▶ | |

So **"+" is driven by `voice[1]`, the recorder-live flag, not by trigs.** This is **L**: it is
inferred from the glyph and the user's reading of it ("record"). Confirm it in the emulator by
starting a recording and watching `voice[1]` and the redraw.

### What this means for the request

1. **"No '+' while muted" needs no glyph change.** The mute stops new recordings, so `voice[1]`
   stays clear and the "+" disappears by itself once the last recording ends. While that last
   recording runs (allowed by design), "+" is correct, because a recording really is running.
2. **"..." = "recorder trigs present but muted"** needs a hook. The proposed logic:
   - recorder live (`d1`) → stock glyph (+ / +▶), the true state wins;
   - else, if `RTM_MASK` bit `t` is set **and the track has at least one live recorder trig** in
     the active pattern → the new state `a4 = 8 | d2` and a dots glyph;
   - else → stock.
   
   "Live recorder trig" = `(REC1 | REC2 | REC3)` at track record `+0x20/+0x28/+0x30` (64-bit,
   working copy `[0x46c82456] + pat·0x8ed8 + t·0x91a`, `pat = 0x100b14d0`). When the track's
   recorder one-shot is **spent** (`0x8000184e & ~0x46c7ff64`, bit `t+8`), the **one-shot layer
   `+0x38`** is removed from that set. So spent one-shots don't count, as asked. Steps beyond the
   track length are not masked out in v1 (edge case).
   
   **Mask `0x38` = the recorder one-shot layer is now C.** The GRID REC editor toggles it with
   FUNC (`0x40030568`, eor at `+0x38`), and the REC SETUP LED painter dims exactly those steps when
   the track's recorder one-shot is spent (`0x40034308..0x40034338`). The KB's "swing / slide (L)"
   label is wrong.
3. **Where to hook.**
   - **State:** `0x4004bee2` `lea 0x400c0cb8,%a0` (6 B) → `jsr rtm_glyph`. The stub computes the
     above, folds it into `a4`, re-does the `lea`, and returns. Folding it into `a4` makes the stock
     cache see a change, so the mute toggling, a one-shot being spent, or a re-arm all redraw on
     the next poll. Scratch registers there: `d0 d1 d2 a0 a1` (all reloaded before use); more need
     `movem`.
   - **Draw:** `0x4004c00c` `moveq #3,%d0 ; cmpl %a4,%d0 ; bnes 0x4004c02a` (6 B) → `jmp
     rtm_draw`. That stub: `a4 == 3` → `jmp 0x4004c012`; `a4 ∈ {8, 9}` → push `(desc, plane
     0x400bf10a, x, a2@(49))` and `jmp 0x4004c024` (stock's own `jsr %a5@` + `lea 16(sp)`); else
     `jmp 0x4004c02a`.
   - Both are UI-task drawing code, not the frame path, so nothing here is subject to the
     engine-hook rule.
4. **Glyph design (user decision).** The box is about 8 px wide, so a glyph can be at most 7 wide.

   | state | proposal A (simple) | proposal B (keeps play info) |
   |---|---|---|
   | muted, live trigs, voice idle | `...` 5×5 (dots on the bottom row) | `...` |
   | muted, live trigs, voice playing | `...` | `..▶` 7×5 (two dots + ▶, like `+▶`) |

   Each glyph costs a 20 B descriptor + 4 B per column of data (+ a mask; it may alias the data,
   to check against the blit `0x400128a8`).
5. **PICKUP machines** have their own status path (`FUN_40097168`). v1 proposal: dots only on
   non-PICKUP tracks, unless the user wants them there too.

### Space (adds to §4)

| piece | ≈ size |
|---|---:|
| `rtm_glyph` (mask test, recording precedence, 64-bit trig OR, spent one-shot removal) | 90–100 B |
| `rtm_draw` | ~40 B |
| `...` glyph (desc + data, mask aliased) | ~40 B (+48 for B's `..▶`) |
| **total** | **~170 B (A) / ~220 B (B)** |

Available: the reused handler bodies have ~43 B left after §4. **`FUN_4005a0e0`** is the bare
text-popup builder, dead in stock (0 absolute or PC-relative references in stock *and* in the
KYOTI V1.0 image). It spans `0x4005a0e0..0x4005a14b`, **108 B** including pad. That is verified: the next function
(`linkw`) starts at `0x4005a14c`, and a full-image scan found 0 references from outside into the
range. Together that is **~151 B: enough for neither A nor B as sketched**, so KYOTI needs one of:
- trim `rtm_glyph` (for example, drop the spent one-shot refinement, ~25 B);
- find one more dead stock routine;
- or ship the glyph as a v2 after the mute itself.

A standalone build on stock has the classic cave and no space problem.

### MIDI mode

The renderer re-draws on a MIDI-mode change (`0x400c0c94`) but always reads the audio voices
`0..7`. What it shows in MIDI mode is unverified; check it in the emulator before relying on it.

## 10. Full scope in KYOTI V1.0 — measured budget and placement (2026-10-02)

User decisions: glyph **B** (`...` idle / `..▶` playing), **no dots on PICKUP** in v1, and **the
full scope** (mute + both glyphs + skip spent one-shots) **if the space can be found**. It can.

**Measured, not estimated.** A size draft assembled with `m68k-elf-as -mcpu=5407` (removed once
`octabam-modules/rec-trig-mute/patch_rec_trig_mute.s` replaced it) gave:

| piece | bytes |
|---|---:|
| `rtm_no` + `rtm_yes` + shared toast tail | 94 |
| `rtm_gate` (step handler) | 28 |
| `rtm_glyph` (state: mask, recording precedence, 64-bit trig OR, spent one-shot removal) | 166 |
| `rtm_draw` (incl. centring `...` at `x+1`) | 66 |
| 2 glyph descriptors (40) + pixel data `...` 5 col / `..▶` 7 col (48) — masks **reuse stock's 7-column opaque mask `0x400c514e`** | 88 |
| strings `REC TRIGS MUTED` / `REC TRIGS UNMUTED` | 34 |
| `RTM_MASK` | 1 |
| **total** | **477** (+1 pad) |

My earlier ~145 B and ~170–220 B figures were estimates and too low. The KYOTI zones are full, so
the code goes into **stock code that nothing can reach** (the same idea as the TRK handlers). The
dead-code scan (`deadscan`, this session) rejected any candidate with **any** of: a branch or call
from outside into the range, a code literal pointing into it, or a **byte-aligned 4-byte pointer
anywhere in the stock or KYOTI image** whose value falls inside the range. (A first, looser pass
that only checked the start address let `0x40073984` through. It is live, called through
11 wrappers that menu tables point into, so the strict rule is required.) The remaining
regions were then read by hand:

| region | size | what it was | proof | gets |
|---|---:|---|---|---|
| `0x40083488..0x40083544` | 188 | stock `[TRK]`+NO/YES handlers, dead once we own the two layer records | only refs = the 4 record fields | keys 94 + gate 28 + strings 34 = **156** (32 spare) |
| `0x4005a0e0..0x4005a14c` | 108 | bare text-popup builder, dead in stock (KB) | 0 refs, stock + KYOTI, strict scan; RELOAD3 only `.equ`s it (`POPUP2`, unused) | `rtm_draw` 66 + 2 descriptors 40 = **106** (2 spare) |
| `0x40032bd4..0x40032d08` | 308 | an orphaned encoder value / acceleration helper (same encoder state `0x46c7d244` as the live `0x4003240c`/`0x40032510`) | 0 refs, strict scan | `rtm_glyph` 166 + pixel data 48 = **214** (94 spare) |
| CAVE tail `0x400d7c36..` | 6 | KYOTI classic cave remainder | proven runtime-writable (DJ_MODE lives in CAVE) | **`RTM_MASK`** (1 B) |

`RTM_MASK` is the one byte written at runtime, so it goes in the proven-writable cave rather than
in reused `.text`. No project has yet been shown to write into the `0x4000..0x400a` code range
at runtime, and there is no reason to be the first.

**Emulator cross-check** (route A, `--load-project --sequencer --frames 600`, `--watch-calls`):
none of the three regions' entry points was entered, while the control (the sidebar renderer
`0x4004be88`) was entered 20×. This is **weak** evidence: the live zero-cross dialog was not
entered either, because route A does not exercise every menu. The static proof is what qualifies a
region. The builder must re-run the strict scan on every build and refuse if anything points into
a reused range.

**Other claims checked.** `refs/` (octakit, midisc, octalab, octamax, octabam) and our own modules
mention none of these regions. The exception is `0x40046ab4`/`0x40046d9c`: stock's 2–5-position
select widgets, also dead in stock, but octabam's REPITCH *calls* the 5-position one, so they are
**not** used here. Reusing `FUN_4005a0e0` means no future feature can call stock's bare popup;
RELOAD3 moved away from it already.

**Build-time assertions** (in addition to §5): stock bytes of all three regions match the stock
image exactly. Strict reference scan = 0 for each region in the *composed* image, apart from our own
detours and the two `[TRK]`-layer records. `0x4004bee2` (6 B `lea`), `0x4004c00c` (6 B) and
`0x4009d9a4` (10 B) are stock, and no branch targets the interior of any of the three. The
CAVE-tail byte is free in the composed image.

**Dot placement — decided (user, 2026-10-02): centred.** Dots sit on the middle row (row 2 of 5,
column byte `0x20`). The 5-wide `...` is drawn at `x+1` so it is centred in the 7-px box. `..▶`
is 7 wide at `x`, like stock's `+▶`:

```
 ...  (5x5 at x+1)     ..▶  (7x5 at x)
 .....                 ....#..
 .....                 ....##.
 #.#.#                 #.#.###
 .....                 ....##.
 .....                 ....#..
```

## 11. MIDI — receive and transmit on a free CC (user request, 2026-10-02)

### Which CCs are free

Stock audio-track CC map (receive handler `FUN_4000e79c`, octabam `docs/firmware/MIDI.md` App. A,
re-read against our disassembly): used = 7, 8, 16–61, 112–127. **Free in stock: 0–6, 9–15,
62–111.** Already claimed by other projects we track:
- **CC 62–73**: octabam `modules/cc-map` and octamad `ccpage2` (FX2 / FX1 page 2).
- CC 74: only used as the "past the range → stock" probe in octamad's verify script, not a claim.

Also avoided:
- **98–101**: NRPN/RPN select numbers; external gear treats them specially.
- **0 / 32**: bank select.
- **6 / 38**: data entry.

**Proposal: CC 80** (MIDI's "general purpose 5", no conventional meaning). Any of **74–97** or
**102–111** works equally; the user picks.

### Receive

All unused CCs 62–111 reach one instruction group in the stock compare chain:

```
4000f210: 7c77        moveq  #119,%d6
4000f212: bc81        cmp.l  %d1,%d6
4000f214: 6c5e        bge.s  0x4000f274      ; CC <= 119 and unclaimed -> epilogue (ignored)
4000f216: ...                                ; CC 120-127: MIDI-track solo bits
```

These are exactly **6 B**, so we replace them with `jmp rtm_cc`. `rtm_cc` replays them for every
other CC. For our CC it mirrors stock's CC 52/53 (`0x4000ed7e`) one-for-one:
- Same gate: `0x40033970()` + auto channel → ignore; **project AUDIO CC IN** (`0x80000049`) off →
  ignore.
- Same track loop: tracks `d5 .. a4-1` whose bit is set in the channel mask `d7`. On the AUTO
  channel that is the active track (set up at `0x4000e8fe..e91a`).
- **value > 0 → mute, value 0 → unmute** (same convention as stock's mute CC 49).
- Writes only `RTM_MASK`: no toast, no UI call. Stock CCs don't toast, and this runs on the MIDI
  task.
- The edge glyph follows by itself, because the renderer polls and our state is folded into its
  cache.

The entry wrappers in octabam's `cc-map` and in octakit hook the handler's **entry**
(`0x4000e79c`) and tail-call stock for CCs they don't own, so a hook *inside* the chain composes
with them.

⚠️ The builder must assert `0x4000f210..f215` is stock. The emulator must confirm `d5`/`a4`/`d7`
still hold the loop set-up at `0x4000f210` (nothing in the chain between `0x4000e91c` and
`0x4000f210` writes them on the fall-through path, by reading; prove it by driving the CC).

### Transmit

- **When:** on `[TRK]`+`[NO]` / `[TRK]`+`[YES]`, for **each held track** t, send
  `FUN_40033e3c(t, RTM_CC, 127 / 0)`. This is stock's own audio CC-out enqueue, the one its
  `[TRK]`+YES uses for CC 53.
- **Gating and channel:** gated by **project AUDIO CC OUT**, and sent on **that track's MIDI
  channel** (`0x8000003f + t`). A channel shared with a MIDI track is skipped, as stock does. It
  is buffered and sent by the polled transmitter `FUN_400409f4`, so it is legal from a key handler.
- **Values:** 127 for mute, 0 for unmute. Stock's arm CCs send 1/0. 127/0 suits controllers
  with toggle LEDs, and both read as "> 0".
- **No echo:** a received CC is **not** re-sent, so no MIDI loops (stock CC 52/53 doesn't echo
  either).

### Space — with MIDI the total is 624 B, so a 4th dead region

Measured (the size draft, before the real source): keys + transmit loop 158, gate 28, glyph state
166, glyph draw 66, CC receive 82, data 124 (2 desc 40, pixels 48, strings 34, mask + pad 2).

**4th region: `0x4009e7dc..0x4009e884` (168 B).** An orphaned arranger-row resolver (walks the
22-byte arranger rows at `[0x10000000]`), next to its live sibling `FUN_4009e884` (the one
DIRECT_JUMP_KYOTI calls for Program Change). It passes the strict scan (stock + KYOTI), was
not entered in the emulator run, and its toast string `ARR PARSE ERROR` (`0x400b94ec`) is
referenced only from inside it.

| region | size | contents | spare |
|---|---:|---|---:|
| `0x40083488..0x40083544` (stock TRK handlers) | 188 | keys + CC transmit 158, gate 28 | 2 |
| `0x4005a0e0..0x4005a14c` (dead popup) | 108 | glyph draw 66, 2 descriptors 40 | 2 |
| `0x40032bd4..0x40032d08` (orphan encoder helper) | 308 | glyph state 166, pixels 48, strings 34 | 60 |
| `0x4009e7dc..0x4009e884` (orphan arranger resolver) | 168 | CC receive 82 | 86 |
| CAVE tail `0x400d7c36` | 6 | `RTM_MASK` (1) | 5 |

### Decisions for the user

1. **CC number** — CC 80 proposed.
2. **Transmit values** 127 / 0 (vs stock-style 1 / 0).
3. **Toast on receive?** Recommended **no**. Stock CCs don't toast, and a toast from the MIDI
   task is an untested path (CLAUDE.md: only key handlers are proven-safe callers of NOTIFY).

## 12. First build — standalone on stock, WIP (2026-10-02)

User decisions: CC 80; transmit **1 / 0**, stock's own on/off values (CC 53's arm pushes 1, the
mute CC sends `neg` of a 0/−1 flag); no toast on receive.

- Source `octabam-modules/rec-trig-mute/patch_rec_trig_mute.s`, builder `tools/build_rec_trig_mute.py`. `.keys` 186/188,
  `.glyph` 246/308, `.draw` 104/108, `.ccrx` 84/168. The YES record is **repointed** at
  `rtm_yes` (0x400834de); NO keeps 0x40083488. 754 B changed vs stock; `140C_RTM`.
  - `syx`: `bf29a57447a7abd4c68e65cbe9beac00f7c5ffe8c1cdac989c0931a6c6c8057a`
  - `bin`: `2a089c97724d1e93b44d8b5ad8557bb93a6450f85179bb1bc1798017e1c655c8`
  - `mainos`: `d56e44248e7f02633054f145eef913042b9450f8778cf6e15c28dceb003292b9`
- A register audit caught `rtm_yes` using callee-saved `%d2` (the MUTE MODE `%d3` class of bug).
  It was fixed before any test ran.
- **`tools/emu_rec_trig_mute.py`: ALL PASS** (route A, OT DEMO):
  - keys: mask, the per-held-track CC 80 sends (1/0), the toast texts, release / nothing held;
  - CC in: track channel, value 0 / 1 / 100, AUDIO CC IN off, CC 100 ignored, CC 120 still on
    stock's path;
  - gate: REC1 poked on every step of T1 + T2 with T1 muted: 5 flag-word writes for T2, 0 for
    T1; after unmute, T1 gets 4;
  - glyph: cache T1 = 8, T2 = 2 (stock "+", a recording really ran); blit with `D_DOTS` at x=1;
    spent one-shot → stock; unmute → stock.
  - The AUTO-channel case was skipped: the demo's AUTO channel is unset or shared.
  - LCD screenshot `out/rec_trig_mute_lcd.png` shows the centred `...` on T1 and `+` on T2.
- Route A does not poll the edge renderer: it is called from `FUN_40052200`'s UI-frame path
  (`0x4005222e`), which the emulator barely runs, so the test calls `0x4004bd48` directly. That
  it redraws on its own is a **hardware** check.
- Not yet: the KYOTI V1.0 composite, the user's project, hardware.

## 13. Hardware report + glyph rule changed (2026-10-02)

The user **flashed build 1** (`bf29a574…`): "seems to work well". That build is untested beyond
that remark: no specific checks were reported.

**New glyph rule (user):** a track with recorder trigs muted always shows **`..■`** (idle) or
**`..▶`** (playing), whether or not it has recorder trigs. The triple-dot `...` is gone, and so is
the "live recorder trigs" computation (pattern masks, spent one-shots): §9's live-trig logic and
§10's 166-B `rtm_glyph` are superseded by a 12-instruction stub. Kept: a muted track whose
recording is still running shows stock's `+` / `+▶` until the recording ends (true state).
- `..■` = dots on cols 0/2 (middle row) + stock's ■ columns (`0x70` ×3), 7 wide at `x`, like
  `+▶`.
- Build 2: `.keys` 186/188, `.glyph` 126/308, `.draw` 96/108, `.ccrx` 84/168; 745 B changed
  vs stock; `140C_RTM`.
  - `syx`: `c1cd738100cfc0d03cf697d17927d11cec1e5c44b7616d9d63395a303978f038`
  - `bin`: `187553d0186ef960eda7af7eb237cf1259fc723c549f92148d805f10b8abf73e`
  - `mainos`: `34f06e293a6f97f0ade3db740273c7f41e06717f3971798c85f1cb362911c804`
- `emu_rec_trig_mute.py` **ALL PASS**. The new cases: muted T1 with **no** recorder trigs → dots;
  muted T2 mid-recording → stock `+`. The LCD shows `..■` on T1.

## 14. Status — shelved as finished (2026-10-02)

**Hardware:** the user flashed **build 2** (`c1cd7381…`) and reported "works well". No
itemised checks came with either report.

**Status:** **WIP, not promoted** (the user did not ask). The image is standalone on stock: no
KYOTI composite.

**Deliberately not done (user):**
- the MIDI additions in §11's follow-up: echo of received CC 80, CC 80 state at power-up / on
  a request;
- the KYOTI V1.0 composite. The four reused regions were scanned free in KYOTI V1.0 (§10). A
  composite needs `build_kyoti.py` to place `RTM_MASK` (CAVE tail) and run the same strict
  scan on the composed image.

## 15. Promoted; composed into KYOTI V1.0 (2026-10-03)

- **REC_TRIG_MUTE is FINAL** (mainos `34f06e29…`, syx `c1cd7381…`, the image the user flashed).
- **`build_kyoti.py`** composes it. `RTM_MASK` is a CAVE piece there (`0x400d7c28`); the
  standalone keeps `0x400d7c3a`.
- **The new KYOTI V1.0** (syx `5106f7fb…`) is WIP until flashed and promoted.
- **Local octabam module:** `octabam-modules/rec-trig-mute/` (not pushed).
- Detail and the hardware test list: `NOTES.md` Session 123.

The §14 "not done" items are now: the MIDI additions, and KYOTI's promotion after the
hardware test.

## 16. KYOTI V1.0 promoted with it (2026-10-03)

The user flashed KYOTI V1.0 `5106f7fb…` and passed the hardware list. MIDI CC 80 was **not**
tested on hardware. KYOTI V1.0 was promoted (mainos `82dd6660…`). `NOTES.md` Session 123
continued.
