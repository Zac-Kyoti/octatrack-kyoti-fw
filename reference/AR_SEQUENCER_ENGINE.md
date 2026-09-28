# Analog Rytm — the sequencer and timing engine, annotated decompilation

AR Session 10 (2026-09-26). Written because the OT thread's "gold" DIRECT JUMP build turned
out to be step-fractional even at 1x / NORMAL mode / a plain 16-step ↔ 7-step pattern switch,
so the OT port restarts from AR's *whole* engine rather than from its commit loops alone.
Canonical copy here; mirrored to `octatrack-kyoti-fw/reference/AR_SEQUENCER_ENGINE.md`.

> **Outcome for the OT port (2026-09-27).** This decompilation did what it was written for.
> OT DIRECT JUMP **V6.4** ported AR's commit exactly — through the OT's own stock landing
> (`0x80006687` path), §6 — and was **hardware-confirmed as AR-exact**, AR's faults included.
> **V7** then deviated on purpose and **shipped** (hardware-confirmed the same day): it keeps
> V6.4's landing but replaces the position rule. AR (and V6.4) derive the new pattern's
> position from the *outgoing* pattern's master counter, which wraps with that pattern; V7
> lands every track where it would be had the new pattern played since START, from an absolute
> clock counter — which removes AR's whole-step shifts, the master-scale lurch and the landing
> duplicate (`AR_DJ_QUIRKS.md` items 1–3). OT `NOTES.md` Session 108 and
> `octatrack-kyoti-fw/reference/handoffs/DIRECTJUMP_V7_DESIGN.md`.

Source: MAIN OS 1.73, `section_3_MAIN_OS.bin`, load base `0x40000400`, ColdFire BE. Every
address is measured in Ghidra 12.1.2 (`tools/ghidra/GhidraSeqCensus.java` = global census,
`GhidraDecompArgs.java` = decompile + listing; outputs in `out/ghidra/*_session10.txt`).
Ghidra's ColdFire decompiler was cross-read against the raw listing everywhere it matters
(`mvs`/`mvz`/`divsl` operand order — see AR_DIRECT_JUMP.md §8). "Inferred" is marked as such.

Supersedes nothing: AR_DIRECT_JUMP.md stays the record of the commit loops and the OT
mapping; §7 below corrects it where this pass proved it wrong.

---

## 1. Interrupt topology and the timebase

### 1.1 The three sequencer interrupt handlers (installer `FUN_40097fee`, called once at boot)

| vector | INTC | level | handler | role |
|---|---|---|---|---|
| 108 | INTC0 src 44 (`ICR 0xfc04806c`) | 5 | `FUN_40097838` (968 B, `rte`) | **clock-edge ISR**: MIDI clock out, SPP/continue landing, then *forces* src 57 |
| 121 | INTC0 src 57 (`ICR 0xfc048079`) | 2 | `FUN_4009905c` (3958 B, `rte`) | **the sequencer tick ISR** — the whole engine |
| 190 | INTC1 src 62 (`ICR 0xfc04c07e`) | 4 | `FUN_40097820` (24 B) | acks INTC1 `INTFRCH` bit 30 only (`0xfc04c010 &= 0xbfffffff`) |

Both INTC0 handlers are **forced-interrupt** targets (`INTFRCH = 0xfc048010`): src 44 is
acked with `& 0xffffefff` at `0x40097862` (that ISR runs with `SR = 0x2700`, all interrupts
masked, from its first instruction), src 57 with `& 0xfdffffff` at `0x40099080`. The chain,
measured:

```
MIDI realtime parser FUN_40080f54 (a task; its pointer sits in the table at 0x401a61bc)
   switch (status & 0xf):  0xF8 clock -> tempo estimator (24-entry ring 0x40abe598, one
   quarter note) and, if FUN_4009c460() == 1 (external sync):  INTFRCH |= 0x1000  (src 44)
   0xF2 SPP -> FUN_4009a7e8(position)      0xFA/0xFB start/continue -> FUN_40098226
   0xFC stop -> FUN_4009a142             0xF0 7E ... -> sysex handler
FUN_40097838 (src 44, level 5): ... ; INTFRCH |= 0x2000000  (src 57)   [0x40097bf0, then rte]
FUN_4009905c (src 57, level 2): the tick.
```

`FUN_4009c460()` = `31 - clz(0x4024be38)` = index of the highest set bit of the sync-source
mask (`FUN_4009c4ca` sets a bit, `FUN_4009c522` clears one). Observed values: 0 internal,
1 external MIDI clock (the only value that forces src 44 from the parser), 2 set by the
serial/USB link handler `FUN_4009cb5c` (its transport commands `iVar9 == 2/3` call
`FUN_4009867a` stop / `FUN_40098092` start-at-position).

With **internal** clock nothing in CPU code forces src 44. The tick ISR's tail
(`0x40099f28`–`0x40099faa`) writes a **deadline mailbox** `0x80006838` (with `0x80006834` as a
base, cleared at transport start) and no CPU instruction reads it back except the ISR itself.
Like OT's `0x8000xxxx` region it is shared with the DSP host interface, so the internal clock
edge is generated outside CPU code from that deadline. Not resolved further — the port does
not need it. (The tail also re-arms the two slice counters below.)

### 1.2 Units

- One **tick = 1/24 quarter note** (MIDI clock rate): 1x resolution = 6 ticks per 16th step
  (`tps` table `0x401a8ff0` = 3, 4, 6, 8, 12, 24, 48 for the 7 resolutions), the MIDI-clock
  phase counter `0x40566757` wraps at `0x30` and notifies at 0 and `0x18` (= every beat).
- Time is kept as a **fixed-point tick count, `0xdbba0` = 900 000 sub-units per tick**.
  `0x40566570` = **now**, `+= 900000` once per tick at `0x400990b4`. Published copies:
  `0x8000682c` (every tick), `0x8000ab64` (only under external sync), `0x42737dc4` (display),
  `0x8000ab30` (bar clock). Every fire time, microtiming offset and count-in below is in this
  domain; the conversion to samples is done by the consumer of the shared region.
- The ISR also runs on **quarter-tick slices**: `0x40566578` = sub-units left until the next
  tick, `0x40566574` = slice (`0x36ee8` = 225 000 = ¼ tick). **Every musical phase of the ISR
  is gated on `0x40566578 == 0`** ("this entry is a real tick"). Slices exist for MIDI clock
  output (`FUN_400941ee`/`FUN_40094212` pulses from the src-44 ISR with `FUN_40118442(port,
  450000|225000)` pulse widths) and the deadline arithmetic; under external sync the slice is
  forced to the full remainder (`0x40099f70`), so the ISR runs once per incoming clock.

### 1.3 Data that the engine reads

- Pattern record base `0x40b6a620`, stride `0x14f00`; track record = pattern + `t*0x395`,
  13 tracks (12 drum + FX). Fields used here: `+0x14eb3` word pattern length,
  `+0x14eb5` word CHANGE length, `+0x14eb7` kit (−1 = current `0x80006830`), `+0x14eb8` swing
  amount, `+0x14eb9` per-track-scale mode, `+0x14eba` master resolution, `+0x14ebb` swing level,
  `+0x14ebc` word pattern tempo; per track `+0x2c5` length, `+0x2c7` resolution, `+0x354`
  trig-condition cycle length (`+0x355..` its step map), `+0x2ca/+0x2d1` "sparse step list"
  mode, `+0x2c9` retrig/probability, step trig words at `track + step*2`, per-step bytes at
  `+0x80/+0xc0/+0x100/+0x140(microtiming)/+0x180/+0x1c0/+0x200/+0x240(condition)/+0x280`,
  p-locks at pattern `+0x2e91 + t*0x162a + step*0x58` (0x2a params × 2 B).
- Chain/song rows `0x41680bce + row*0x14` (pattern at `+0`… the picker `FUN_40097e84` reads
  `+0x14`-strided fields `0x41680bbc/bc0/bc4/bc8/bcc`), current row `0x4168273c`,
  pending row `0x41682740`.
- Settings record `0x416a603c + 0xe4*proj` (`0x416a56ec` = index): `+0x60` metronome on,
  `+0x64/+0x68/+0x6c` time-signature/count-in fields, `+0x74/+0x78` clock/transport send,
  `+0x7c` transport receive, `+0x80` send transport, `+0x88` program-change send.

---

## 2. The complete sequencer state vector (all measured; ✓ = new to this pass)

Master scalars:

| address | width | meaning |
|---|---|---|
| `0x405666e0` | long | transport: 0 stopped, 1 running, 2 paused (`FUN_4009a142`) |
| `0x405666e4` | word | master step (bounded by pattern length) |
| `0x405666e6` | byte | master ticks-within-step, `++` per tick at `0x40099962`, wrap at `0x40099974` |
| `0x405666e8` | word | master step − 1 (the step being sounded) |
| `0x40566774` | byte | master resolution index |
| `0x40566754/55` | byte | current pattern / next pattern (`0x55` = −1 means "stop at end") |
| `0x40566756` | byte | previous pattern (still read for tracks whose fire countdown is pending) |
| `0x40566782` | byte | ✓ "stop pending" (set at a wrap when next pattern = −1; the step body then stops) |
| `0x40566748` | long | ✓ transport engaged (1 = MIDI clock out / bar counter enabled) |
| `0x405667d6` | word | ✓ count-in ticks before the second commit path (§3 D3) |
| `0x405667b8` | word | ✓ **hold mask**: track skips one advance (`0x400997c0`) — AR's `0x80006626` |
| `0x405667d4` | word | ✓ **first-fire mask**: track's next schedule uses `tps − cntdn` (`0x400995b4`) |
| `0x40566828` | long | ✓ "pattern change armed at this wrap" (set at phase 2, consumed at phase 0) |
| `0x4056682c` | long | ✓ set by the queued-change setter `FUN_4009884c`, cleared at the wrap-change |
| `0x40566758/5c/60/64` | long | ✓ cycle bookkeeping (start step / end step, current and next) |
| `0x4056676c/70` | long | ✓ 16th-step counter / tick-in-16th (0..5) |
| `0x4056674c/4d` | byte | ✓ bar / step-in-bar for the MIDI-clock bar counter |
| `0x405667dc/e0/e4/e8` | long | PTN CHG request: target, DIRECT START flag, countdown, "recompute countdown" |
| `0x405667f4/f6` | word/byte | **SPP / pause snapshot**: target step, sub-step remainder (§5 — NOT the DIRECT JUMP path) |
| `0x40566768` | long | ✓ absolute tick position for continue (`phase + tps×(step−1)`) |
| `0x40566814` | long | ✓ ticks until the MIDI CONTINUE byte after an SPP landing |

Per-track arrays (13 entries each, contiguous):

| array | width | meaning |
|---|---|---|
| `0x405666ec` | long | track engaged (1) — 0 stopped, 2 paused |
| `0x40566720` | byte | step index (leads the audio by one step, §3 E/F) |
| `0x4056673a` | byte | step − 1 (the sounding step) |
| `0x4056672d` | byte | ticks-within-step |
| `0x40566775` | byte | resolution index |
| `0x405667c7` | byte | countdown reload: `tps_t − 1` normally; `tps_t − tps_master_old` after a wrap-change |
| `0x405667ba` | byte | ✓ **fire countdown** (−1 idle): deferred landing after a wrap-change — AR's `CNTDN_TBL` |
| `0x40566830` | byte | ✓ trig-condition step counter (wraps at `+0x354` or the length; calls `FUN_400976f6`) |
| `0x40566784` | word | ✓ next step computed at the wrap-change (`ceil`), consumed when the fire countdown expires |
| `0x4056679e` | word | ✓ sub-step remainder from that `ceil` — AR's `PAIR` |
| `0x405667f7` / `0x40566804` | byte | ✓ SPP snapshot: step / tick per track (written by `FUN_40099fd2`) |
| `0x8000681c` | byte | ✓ fire-slot mask (bits 0..2) — shared region |
| `0x8000aa5c` | long ×3 | ✓ **fire times** per slot, sub-unit domain — shared region |
| `0x4273c990` | 0x38 B ×3 | ✓ event records per slot (14 longs: valid, note, vel, length, 1/length, flags, …, p-lock list ptr) |
| `0x42739480` | 0x15c B ×3 | ✓ resolved p-lock delta lists per slot |
| `0x42737d80/8d/9a/a7/b4/dc8` | byte | ✓ display copies of step−1 / step / tick / pattern per track |

`0x4273818c` (long) = the last computed microtiming offset (sub-units), `0x427380e4` = the
scratch record the scheduler fills (its first long = "an event was built").

---

## 3. The tick ISR `FUN_4009905c`, phase by phase

Order matters and is the one thing OT's port had wrong; the phases below run in this order
on every entry, each gated as stated. `cfg` = settings record; "tick" = `0x40566578 == 0`.

**A. `0x4009905c`–`0x4009908c` — prologue.** Ack `INTFRCH` bit 25; `cfg` pointer.

**B. `0x4009908e`–`0x400990c0` — advance *now*** (tick only): `if sync==1: 0x8000ab64 = now`;
`now += 900000; 0x8000682c = now`.

**C. `0x400990c6`–`0x40099110` — MIDI CONTINUE countdown** (tick, running, `0x40566814>0`):
send `0xFB` when it reaches 0 (`FUN_40083a44`, or park it in `0x405667d8` for the src-44 ISR
when transport-send is off), then `FUN_40097c00` (clock-out enable).

**D. `0x40099114`–`0x400994c6` — the pattern-change commits** (tick only).

- D1 `0x4009911e`–`0x40099158`: if `0x405667e8` ("request arrived") → clear it and
  **`countdown 0x405667e4 = tps[master_res] − master_tick_phase`** = ticks until the next
  master step boundary. Recomputed on every request, never accumulated.
- D2 `0x4009915e`–`0x4009936c`: `--countdown`; at 0 → **THE DIRECT START / DIRECT JUMP
  COMMIT** (AR_DIRECT_JUMP.md §2 lists the loops; what it does, in order):
  1. `0x40566782 = 0`; cycle vars reset; `pat_prev = pat_cur`; `pat_cur = pat_cur_b = target`
     (`0x400991ae/b4`, adjacent).
  2. `0x405667c7[t] = tps_t − 1` for all tracks; **`master_tick_phase = tps_master − 1`**
     (`0x4009921a` / `0x40099234`).
  3. `0x405667d4 = 0xffff` (first-fire pending for every track).
  4. `new_step = DIRECT START ? 0 : master_step mod patLen` (`0x40099274`).
  5. per track: `step = new_step mod len_t`, `step−1`, `tick-in-step = 0`,
     **`fire countdown = −1`**, trig-condition counter `= new_step mod len_t`
     (`0x4009929e`–`0x400992d2`). **No hold bits, no catch-up, no remainder.**
  6. `master_step = new_step`, `master_step−1`, resolutions (`0x400992d4`–`0x40099328`),
     all tracks engaged (`0x405666ec[t] = 1`), transport = 1.
  7. `FUN_4011a388(now + 900000, pat)`: publish "pattern/kit/tempo take effect at the next
     tick" to the shared region (`0x8000ab2c` = time, `0x80006812` kit, `0x80006810` row,
     `0x80006814` tempo, `0x8000ab50` = 1). UI notify.
- D3 `0x40099370`–`0x400994c6`: an independent count-in commit (`0x405667d6` ticks, armed by
  transport start when count-in is configured): identical rebuild with `new_step = 0`, then
  MIDI `0xFA`. Two commit paths, one discipline (as AR_DIRECT_JUMP.md §2 said).

Because D1 lands D2 exactly on a master step boundary tick and D2 sets the phase to
`tps−1`, phase G below wraps it to 0 in the same ISR, so the master step body runs on the
commit tick and every track's first-fire path in E fires immediately. The commit is
**synchronous for all 13 tracks** and leaves no per-track state to reconcile.

**E. `0x400994ca`–`0x4009972e` — per-track trig scheduling** (13×; runs every entry, but the
scheduling body is tick-gated at `0x4009958a`). For track `t` engaged and no stop pending:

```
c   = fire_cntdn[t]                     ; -1 idle, >=0 landing pending after a wrap-change
pat = (c >= 0) ? pat_prev : pat_cur     ; a track still landing reads the OLD pattern
tps = tps[res_t of that pattern]
ahead = tps ; if c == 0: ahead -= cntdn[t]
if tick && tick_in_step[t] == 0:
    slot = first free of 3 (ff1 over ~slotmask[t] & 7)           ; 0x4009959a-0x400995b2
    if first_fire[t]: ahead -= cntdn[t]                          ; 0x400995b4
    FUN_400989d0(t, pat, step[t], slot)                          ; build the event (§4)
    fire_time[t][slot] = now + micro(0x4273818c) + (ahead-1)*900000   ; 0x40099604
    if event built: slotmask[t] |= 1<<slot
    dedupe: same pattern or c != 0 -> kill other slots with the SAME fire time;
            pattern just changed (c == 0) -> kill other slots later than
            now + (tps_master-1)*900000  (drops the old pattern's lookahead)   ; 0x40099664-0x400996ee
    if c == 0:        tick_in_step[t] = cntdn[t]                 ; 0x400996fc
    if first_fire[t]: tick_in_step[t] = cntdn[t]; clear bit      ; 0x4009970e-0x40099714
```

Steady state: `ahead = tps`, so the event for `step[t]` is computed at the **first** tick of
its window and fires at the **last** (`now + (tps−1)` ticks) — a one-step lookahead; F
advances `step[t]` at the end of that same last tick. After the DJ commit `ahead = 1`: fires
now, and `tick_in_step = tps−1` makes F advance immediately, so the next step's window opens
on the very next tick with a full `tps` — the grid is exact by construction.

**F. `0x40099732`–`0x4009991a` — per-track advance** (tick only), 13×, engaged tracks:
`++tick_in_step`; at `>= tps[res_t]`: `= 0`; if `fire_cntdn < 0` refresh `res_t` from the
pattern; if **hold bit clear**: publish pattern id, `step−1 = step`, `step++` wrap `len_t`,
trig-condition counter `++` wrap (`+0x354` or `len_t`, `FUN_400976f6(t)` at its wrap);
**hold bit set** (`0x400997c0`–`0x400997fc`): clear it, `cntdn[t] = remainder_word[t]`
(`0x4056679f + 2t`), set the first-fire bit — the advance is *skipped once* to convert the
wrap-change `ceil` to `floor` (exactly OT dead end 1 in the handoff). Then the display copies
(`0x400998c2`–`0x400998f6`), `0x42737dc4 = now`.

**G. `0x4009991c`–`0x40099dbe` — master advance** (tick, transport == 1):
`++master_tick_phase`, wrap at `tps[master_res]` (`0x40099962`–`0x4009997c`).
- stop pending && phase == 0 (`0x40099982`–`0x40099a74`): MIDI `0xFC`, disengage all, transport 0.
- phase == 2 (`0x40099a78`–`0x40099b7e`): decide whether this cycle ends here —
  per-track-scale mode with a CHANGE length hit (`(master_step+1) % chg == 0`, only if a
  chain/song row change or a different pattern is due), or `master_step >= len−1`, or the
  cycle-end override `0x4056675c`. If so `pat_cur_b = FUN_40097e84()` (chain/song picker),
  program-change out (`FUN_40097c2c`), `0x40566828 = 1`.
- phase == 0 (`0x40099b80`–`0x40099dbe`): `master_step−1 = master_step; master_step++` wrap at
  `len`; `master_res` refresh. If `0x40566828`: next == −1 → cancel every scheduled event at or
  after the boundary, stop pending; else **THE WRAP-CHANGE** (`0x40099c38`–`0x40099d9c`):
  `pat_prev = pat_cur; pat_cur = next; FUN_4011a388(now + tps*900000, next)`;
  `master_step = cycle-start (0x40566758)`, **`master_tick_phase = 0`** (`0x40099cd6`),
  `T = master_step × tps_master_new`; per track: `q = ceil(T / tps_t)` → `0x40566784[t]`,
  `rem = T − q×tps_t` (`+tps_t` if negative) → `0x4056679e[t]`, `rem > 0` → hold bit,
  `cntdn[t] = max(0, tps_t − tps_master_old)`, `fire_cntdn[t] = max(1, tps_master_old + 1 − tps_t)`.
  **This is byte-for-byte the algorithm OT's boundary body runs** (ceil / PAIR / CATCHUP /
  CNTDN_TBL, AR_DIRECT_JUMP.md §3, §5 dead ends 1–4) — it is AR's *wrap* path, and AR never
  uses it for DIRECT JUMP.

**H. `0x40099dc0`–`0x40099e2c` — fire-countdown landing**, 13×: `if fire_cntdn >= 0: --`; at 0:
`step = 0x40566784[t]`, trig-condition counter likewise, `tick_in_step = 0`, display copies —
the deferred per-track landing after a wrap-change (OT's "CNTDN expiry → STEP write +
reposition"). Skipped-advance semantics come from F's hold bit, not from here.

**I. `0x40099e32`–`0x40099f26` — MIDI-clock bar counter and metronome** (`FUN_40118518` →
`0x80006818`), the 48-phase clock counter `0x40566757`, the 16th counters.

**J. `0x40099f28`–`0x40099fba` — timer tail**: re-arm `0x40566578 = 900000` / `0x40566574 =
225000` when zero; with SR = 0x2700: under external sync slice = whole remainder; subtract
the slice from both; deadline `0x80006838 = max(0, old + 0x80000001 + 0x80006834 + slice)`
(internal) or `slice` alone (external); `rte`.

---

## 4. The event builder `FUN_400989d0(track, pattern, step, slot)` — what "scheduling" means

Called from E (slot 0..2, fills `0x427380e4` + `0x4273c990[t][slot]`) and from the SPP
pre-roll `FUN_40099fd2` (slot −1, fills `0x4273811c` + `0x42737dd8[t]`). Measured behaviour:

1. Resolve the step through the trig-condition map (`+0x354/+0x355`) and the sparse-step
   list (`+0x2ca/+0x2d1`) → the pattern step whose trig word is read (`track + step*2`).
2. Trig word bit 0 = trig, bit 2 = disabled, bit 4 = swing applies, bits 7/8 (`0x180`) and
   `0x10000` = p-lock/"has locks" flags; bit 5 = retrig. Condition byte `+0x240`
   (`FUN_400974c8`: %, 1:2 … fill, pre/not-pre, A:B cycles; `FUN_40097480` = probability).
3. **Microtiming**: `micro = ((0x7f − swingLevel) × 0x202) × tps × 25 × microByte(+0x140)
   >> 16`, plus `swingAmount × tps × 12` when bit 4 is set; stored ×1500 in `0x4273818c`
   (sub-units). E adds it to the fire time. So microtiming is applied at *schedule* time.
4. The record: note/velocity/length (`+0x80/+0xc0/+0x100`, −1 → kit defaults `+0x2c0..`),
   retrig distance from the next trig search, flags, kit (`+0x14eb7` or current), and a
   resolved **p-lock delta list** (`FUN_400988fc`: for each of 0x2a params, lock value minus
   the kit's live value at `0x415e265e + kit*0x9e3 + t*0x98`) written to `0x42739480 + t*0x414
   + slot*0x15c`.

No CPU code reads `0x8000aa5c` fire times except E's own dedupe compares. The consumer that
turns `(fire time, record)` into sound is on the other side of the shared region, exactly as
OT's `DAT_80001904` timestamps written by `0x400a2e18`. **On both machines the CPU sequencer
is a scheduler; it never fires anything itself.**

---

## 5. Request paths, and which one DIRECT JUMP is

| entry | what it does |
|---|---|
| UI `FUN_4003e636(view, pat)` (`0x4003e636`, decompiled this pass) | mode 1 → `FUN_4009a5b0(pat, 1)` DIRECT START; mode 2 → `FUN_4009a5b0(pat, 0)` DIRECT JUMP/TEMP; other modes → `FUN_4009a2ae(pat)` immediate when stopped; a `view+0xc6` flag → `FUN_4009884c(pat)` (queued: `0x405667e8 = 1`, target, `0x4056682c = 1`, DIRECT START flag untouched — semantics not traced) |
| `FUN_4009a5b0(pat, directStart)` | running: with SR=0x2700 write `0x405667e8 = 1`, target, flag (→ D1/D2). stopped: chain row's pattern → `FUN_4009a2ae` |
| `FUN_4009a2ae(pat)` | immediate setter while stopped: pattern, `FUN_40099fd2` pre-roll, program change, kit `FUN_401188ec`, tempo `FUN_401184ae` |
| `FUN_40097e84()` | chain / song next-pattern picker, called from G at phase 2 |
| **`FUN_4009a7e8(spp)`** ← MIDI `0xF2`, `FUN_4009a93e` | position in 16ths ×6 → ticks; `FUN_4009a3e2(1,1)` full reset; row/pattern; `FUN_4009a5b0(pat, 1)` (stopped → immediate); **`FUN_4009a618(ticks, ticks-to-next-step)`**: reduce into the current pattern's cycle, split into **(target step `0x405667f4`, sub-step remainder `0x405667f6`)** rounded up to the step, `0x40566814` = ticks until CONTINUE; `FUN_40099fd2` pre-computes every track's landing step/tick (`0x405667f7/0x40566804`) and its first event (`0x42737dd8`, offsets `0x427380b0`) |
| `FUN_4009a142()` ← MIDI `0xFC` / pause | transport = 2; snapshot `target = master_step−1`, `remainder = phase`, `0x40566768` abs ticks; pre-roll |
| `FUN_40098226(sendStart)` ← MIDI `0xFA/0xFB`, UI play | **transport start / continue**: `master_step = target + 1` (wrap), **`phase = remainder`** (`0x40098358`), per-track step/tick from the snapshot (`0x400983c0`–`0x40098440`), fire times = `now + offset (+ (tps − tick)×900000 if mid-step)` (`0x4009850c`–`0x400985b0`), count-in → `0x405667d6`, `now = 0x8000ab64 + 2 or 6 × 0x4024be34` |
| `FUN_40098092(offsetTicks)` ← serial link | same landing, deferred to the src-44 ISR via `0x405666dc` (`0x40097868`–`0x40097ac6`, identical code) |
| `FUN_4009867a()` / `FUN_4009a3e2(a, force)` | stop / full reset (all counters, slot masks, records) |

**So the (target step, remainder) pair is the PAUSE / SONG-POSITION mechanism.** It is
consumed only by transport start/continue (`FUN_40098226`, `FUN_40098092`+ISR). The DIRECT
JUMP commit (D2) never reads `0x405667f6`; it lands on a boundary by construction (D1) and
writes the phase itself.

---

## 6. AR's DIRECT JUMP as a specification (the port target)

1. **Request**: record target and the DIRECT START flag; set "recompute". Nothing else.
2. **Quantise**: on the next tick, `countdown = tps_master − master_tick_phase` — the next
   master step boundary, at most `tps_master` ticks away, recomputed per request.
3. **Commit tick** (before the per-track scheduling loop of that same tick):
   pattern pointers; `new_step = master_step mod patLen` (0 for DIRECT START);
   for every track `step = new_step mod len_t`, `step−1`, `tick_in_step = 0`,
   `cntdn = tps_t − 1`, `fire_cntdn = −1`; first-fire mask all set; hold mask untouched
   (already 0 on a boundary); `master_step = new_step`; **`master_tick_phase = tps_master −
   1`** so the master step body runs at the end of this tick; publish the pattern/kit/tempo
   switch for `now + 1 tick`.
4. **Let the normal loops run**: E fires every track's `new_step` immediately (`ahead = 1`),
   re-seeds `tick_in_step = tps_t − 1`; F advances every track at the end of the tick; G
   advances the master. From the next tick on, nothing distinguishes a jumped pattern from
   one that started there.
5. **Never** enter the wrap-change path (G/H: ceil, remainder, hold, catch-up, fire
   countdown) for a jump. That path exists to re-phase tracks whose `tps` differs from the
   master's across a *cycle* boundary; it assumes `master_tick_phase = 0` and a `T` derived
   from the cycle start, and it defers per track. A jump has none of those properties.

The audible cost the user has confirmed on AR hardware — "the occasional spurious trig at the
jump" — is step 4: the immediate fire of `new_step` plus the dedupe rule in E that only kills
*later* old-pattern events when the pattern just changed.

---

## 7. Corrections to AR_DIRECT_JUMP.md carried by this pass

- **§9 is mis-attributed.** `0x405667f4/f6` are written by `FUN_4009a618`, reached only from
  the SPP/continue path (`FUN_4009a7e8`, `FUN_4009a9e0`) and by the pause `FUN_4009a142`, and
  consumed only by transport start (`0x40098358`, `0x40097910` in the src-44 ISR). The DIRECT
  JUMP commit carries **no sub-step remainder**; it counts down *to* the boundary and sets the
  phase to `tps − 1`. The "three parallel consumer sites" of §9 are the three transport-start
  landings, not jump variants. §9's stated consequence for OT — that V5.7's `dj_mrem` seed "is
  the same mechanism in the same role" — is therefore **withdrawn**: AR's DJ has nothing to
  seed, because its commit never lands mid-step.
- §2's "`0x405667c7 = ticksPerStep − 1`" is the DJ-commit value; at wrap-changes the same
  array holds `max(0, tps_t − tps_master_old)` (catch-up), and `0x405667ba` is a *fire
  countdown* (`max(1, tps_master_old + 1 − tps_t)`), not a constant −1. §7 item 3 ("semantics
  of the 0/−1 arrays") is closed: `0x4056672d` = ticks-within-step, `0x405667ba` = fire
  countdown, −1 idle.
- §4's "AR commits from an independent per-tick function" is right in spirit and wrong in
  letter: `FUN_4009905c` *is* the tick ISR (`rte`), and the commit is a phase inside it that
  runs **before** the per-track scheduling and advance loops — the ordering that makes the
  synchronous rebuild sufficient.
- §7b's "nothing in AR's request or commit path writes the tick phase" was corrected in §9
  and is now corrected again: the DJ commit writes `tps − 1`, transport start writes the
  snapshot remainder, the wrap-change writes 0.
- §1's "the wait is to the next step/resolution boundary" is exactly the next **master**
  step boundary (`tps[master_res]`), not a per-track one.

## 8. Still open on the AR side (low priority, unchanged in kind)

1. The `view+0xc6 → FUN_4009884c` queued-change variant and `0x4056682c`'s reader.
2. TEMP JUMP's revert bookkeeping (still reads as DIRECT JUMP through this whole pipeline).
3. The internal-clock deadline consumer (`0x80006838`) — outside CPU code.
4. The exact meaning of event-record fields [6], [8]–[11] (per-step bytes `+0x280`, `+0x100`
   via table `0x401c5a64`, `+0x1c0`, `+0x180`, `+0x200`).
