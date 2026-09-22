# On-CF file data model — Set / Project / Bank / Part / Pattern

What the Octatrack writes to the CF card, and how it maps to the in-RAM structures
in `memory-map.md`. Primary external source: **OctaLib** (snugsound). Our anchor
into the same data from the firmware side is `_DAT_46c82456` (see `memory-map.md`).

---

## Project layout on disk

> source: `refs/OctaLib/Research.md` @ `6e2438e` · fetched 2026-09-02 · confidence: **L** (author calls it "untested but likely")

A Project = **52 files**, each in two versions (`.work` = working memory,
`.strd` = stored/saved; load copies `.strd`→`.work`, save the inverse):

| Files | Names |
|---|---|
| Project (1) | `project` — **plain text**, sample-slot definitions + metadata |
| Arranger (8) | `arr01`..`arr08` |
| Bank (16) | `bank01`..`bank16` — fixed-length binary |
| Markers (1) | `markers` |

### `project` sample definitions (plain text)

```
[SAMPLE]
TYPE=              FLEX | STATIC
SLOT=              001-128  (+129-136 = FLEX recording buffers)
PATH=              ../path/to/file
TRIM_BARSx100=     length in bars ×100  (400 = 4 bars)
TSMODE=            timestretch mode
LOOPMODE=          loop mode
GAIN=              default 48
TRIGQUANTIZATION=  default -1
[/SAMPLE]
```

---

## Bank file — binary layout

> source: `refs/OctaLib/OctaLibCore/Constants.cs` + `BankUtils.cs` @ `6e2438e` · fetched 2026-09-02 · confidence: **C** for the offsets OctaLib actually reads, **L** for the structural sketch

Header (16 B): `46 4F 52 4D 00 00 00 00 44 50 53 31 42 41 4E 4B` = `FORM....DPS1BANK`

Structure: file header → **16 PTRN blocks** (each = 8 TRAC + 8 MTRA) → PART header
→ part names as plain text at end of file. Repeating `AA AA AA AA AA AA AA AA 00 00
00 00 00 00 00 00 10 02` marker between sections. Unset values padded `FF`.

### Key offsets (byte addresses within the bank file)

| Const | Value | Meaning |
|---|---|---|
| `ADDR_PAT01` | `0x00000016` | start of pattern-1 header |
| pattern-block stride | `0x8EEC` (36588) | `LENGTH_PATTERN_LENGTH` — PTRN *n* = `0x16 + 0x8EEC*n` |
| pattern header len | `8` | |
| `LENGTH_TRAC` | `0x922` (2338) | one audio-track block; 8 back-to-back after the header |
| `LENGTH_MTRA` | `0x8B9` (2233) | one MIDI-track block; 8 after the 8 TRAC blocks |
| `OFFSET_TRACK_NUM` | `+8` from TRAC/MTRA | track index (always matches position) |
| `OFFSET_TRACK_TRIGS` | `+9` from TRAC/MTRA | regular trigs, **reverse binary** bitfield (OctaLib reads 8 bytes) |
| `OFFSET_TRACK_REC_TRIGS` | `+41` (`0x29`) from TRAC | recording trigs |
| `OFFSET_PATTERN_PART_NUM` | `+0x8EE7` from PTRN | which Part (0-3) this pattern uses |
| `ADDR_PART_NAME[0..3]` | `0x9B4B3, 0x9B4BA, 0x9B4C1, 0x9B4C8` | 6-char part names (stride 7), NUL-terminated |

PTRN header addresses (pattern 1..16): `0x16, 0x8F02, 0x11DEE, 0x1ACDA, 0x23BC6,
0x2CAB2, 0x3599E, 0x3E88A, 0x47776, 0x50662, 0x5954E, 0x6243A, 0x6B326, 0x74212,
0x7D0FE, 0x85FEA`.

MTRA (pattern 1) addresses: `0x492E, 0x51E7, 0x5AA0, 0x6359, 0x6C12, 0x74CB, 0x7D84, 0x863D` (stride `0x8B9`).

PART block addresses (1..8 — **OctaLib notes "two sets of parts, why?"**, likely
`.work` vs saved copy): `0x8EED6, 0x90791, 0x9204C, 0x93907, 0x951C2, 0x96A7D, 0x98338, 0x99BF3` (stride `0x18BB`).

### Machine types

Machine-type byte values (octabam RTOS §10.13, by code + data — corrects the
earlier "0/1 = FLEX/STATIC" guess): **`0` = STATIC · `1` = FLEX · `4` = PICKUP**;
THRU / NEIGHBOR have no slot. FLEX/STATIC descriptors `0x400d2fe4` / `0x400d3176`
(`memory-map.md`).

**Per-track slot record — 5 bytes**, at part-record `+0x2d3 + 5*track + type`
(RAM `blob + part*0x18b2 + track*5 + type + 0x8f04a`): byte `+0` = STATIC slot,
`+1` = FLEX slot, `+4` = PICKUP buffer. Slot bytes are 0-based (`0` = slot 1,
`128` = recording buffer R1 — the file's `SLOT=129`). PICKUP's setter forces
`128+track` (its own recorder). `ot_project.py track-slot` writes these.

### Effect types → id  (from octa-bt-pt)

`FILTER 0x04 · SPATIALIZER 0x05 · DELAY 0x08 · EQ 0x0c · DJ EQ 0x0d · PHASER 0x10
· FLANGER 0x11 · CHORUS 0x12 · COMB 0x13 · PLATE REV 0x14 · SPRING REV 0x15 ·
DARK REV 0x16 · COMPRESSOR 0x18 · LOFI 0x1c` — full descriptor addresses in
`memory-map.md`. Stock FX1=FILTER, FX2=DELAY.

**Confirmed in the PART block** (DEMO `bank01.work`): each `PART` tag (`0x8EED6` +
`n*0x18BB`) is followed by `+8 = part index (0-3)`, then **8 bytes FX1 id / track**
then **8 bytes FX2 id / track**. e.g. PART slot 8: FX1 `04 18 0c 12 10 04 0c 1c`,
FX2 `08 08 14 08 08 12 12 08` — every FX2 is DELAY/PLATE/CHORUS, consistent with
the FX1-disallowed rule (`memory-map.md`). 8 PART slots = 4 live + 4 saved
(`.work` vs `.strd` copies inside the one file); only 4 name entries exist
(`ADDR_PART_NAME`), DEMO parts are `ONE`/`TWO`/`THREE`/`FOUR`.

### Full TRAC block layout — p-lock region mapped

> sources: our RE against a real hardware export — Elektron factory **OT DEMO**
> `bank01.work` (`~/Desktop/OT Backup/KYOTI/OT DEMO/`, exported 2026-01, 636 113 B,
> reproducible: it's the factory demo; `tools/inspect_bank.py`, Session 16) **+
> `refs/octabam/docs/RTOS_FORK.md` §10.6 @ `2f241e1`** (2026-09-06) which measured
> the same block against the firmware and via hardware `pattern-diff`.
> confidence: **C** for the step-mask offsets + the recorder masks, **L** for the
> p-lock array's internal parameter map (still needs the `pattern-diff` pass).

The audio-track block (`LENGTH_TRAC = 0x922`, from the `TRAC` tag) is **fixed
size**. octabam's framing: the `TRAC` chunk header is **9 bytes** (tag + length +
1 pad); track data starts at `+9`. Our offsets below are from the `TRAC` tag, so
they already include that (`+0x08` = the pad byte, which holds the track number;
`+0x09` = first data byte = OctaLib's `OFFSET_TRACK_TRIGS`).

| Offset | Size | Field |
|---|---|---|
| `+0x00` | 8 | `"TRAC\0\0\0\0"` tag |
| `+0x08` | 1 | track number (0–7) (= header pad byte) |
| `+0x09` | 8 | **mask 0x00** — regular note/sample trig; 64 steps, bit `step-1`, byte 7 bit 0 = step 1 |
| `+0x11` | 8 | **mask 0x08** — trig-type layer (trigless-trig / one-shot) — one of these three carries the "trigless lock" bit |
| `+0x19` | 8 | **mask 0x10** — trig-type layer |
| `+0x21` | 8 | **mask 0x18** — trig-type layer |
| `+0x29` | 8 | **mask 0x20** — recorder trig **REC1** (HW-confirmed; = OctaLib `OFFSET_TRACK_REC_TRIGS`) |
| `+0x31` | 8 | **mask 0x28** — recorder trig **REC2** (HW-confirmed) |
| `+0x39` | 8 | **mask 0x30** — recorder trig **REC3** |
| `+0x41` | 8 | **mask 0x38** — swing / slide (sets flag-word bits 5+8) |
| `+0x49` | 8 | per-step byte array (not a mask), default `0xAA` — micro-timing gate (`0x4009d3d6`) |
| `+0x51` | 8 | per-step byte array (not a mask), `0x00` in the DEMO |
| `+0x59` | 9 | **param header**: `[LEN] 02 00 FF 00 00 00 00 00` — `LEN` ∈ `{0x10,0x20,0x40}` = this **track's** step count 16/32/64 (per-track, → the "TRACK" scale mode, not the pattern master length) |
| `+0x62` | `0x800` | **p-lock array — 64 steps × 32 bytes.** `0xFF` = that parameter not locked on that step. `record[step][p]` = locked value of p-lockable parameter `p` |
| `+0x862` | `0xC0` | per-step aux array — 64 × 3 B (trig conditions / micro-timing / retrig?); `0x00` = default; empty in the DEMO |

`0x62 + 0x800 + 0xC0 = 0x922` exactly. Firmware consumers of the masks:
`0x4009d1e8` (step handler), `0x4009d382..0x4009da12`, per-track flag word
`0x46c7a6c0` — see [`memory-map.md`](memory-map.md) "Per-step sequencer data".

### p-lock array — byte → parameter map (hypothesis, confidence **L**)

**Evidence** (DEMO P11 t2, `tools/inspect_bank.py -p 11 -t 2`; 16-step track, 8
regular trigs, no trigless/rec trigs): records at exactly 32-byte spacing.
Byte `0x12` ramps `40 → 29 → 14 → 05 → 00` across steps 0,2,4,6,8 (one automated
parameter); byte `0x00` climbs `4F → 5E → 68` on steps 10,12,14 with `0x13`
appearing on step 14. Non-`0xFF` offsets across the pattern: `0x00, 0x12, 0x13`.

**Working model:** 32 bytes = **five 6-parameter page-1 groups + a 2-byte tail**,
in the OT's parameter-page order:

| record offset | page-1 group (6 params × 1 byte) |
|---|---|
| `0x00–0x05` | PLAYBACK (`PTCH STRT LEN RATE …`) |
| `0x06–0x0b` | AMP (`ATK HOLD REL VOL BAL XVOL`) |
| `0x0c–0x11` | LFO (audio) |
| `0x12–0x17` | FX1 |
| `0x18–0x1d` | FX2 |
| `0x1e–0x1f` | tail — sample-slot lock / validity? |

`0x12` = FX1 param 0 and `0x00` = PLAYBACK param 0 (PITCH) are the offsets seen
automated here — *consistent* with the model but **not confirmed** (P11 t2's part
was not resolved; most DEMO parts give track 2 an EQ, not a FILTER, on FX1, so
the ramp at `0x12` is probably an EQ band, not a cutoff). Payload cross-ref:
[`octakit-abi.md`](octakit-abi.md) FX1 `0x2fe` / FX2 `0x304` are 6 bytes apart
⇒ 6 params per FX page, which is where the "6-byte group" comes from.

Open: page-2 params (SLIC/LOOP/TSTR, AMP SYNC, FX SETUP), LFO-designer locks, the
sample-slot lock, trig-condition / micro-timing (likely the `+0x862` aux array).
The whole map is **untested** — the `pattern-diff` plan below pins it in one pass.

### NOTES Session 13 backlog — auto-remove an emptied trigless lock

A **trigless lock** = a step with a non-`0xFF` `record[step]` in `+0x62` but its
bit **clear** in mask 0x00 (`+0x09`) *and* in whichever of masks 0x08/0x10/0x18
is the "trigless trig" (retrig) layer. On the last-lock erase, `record[step]`
goes all-`0xFF`; the feature then also clears the step's bit in the mask that
lights the dim-red LED. **Which mask that is is the one open question** — it is
one of `+0x11/+0x19/+0x21`, and a pure p-lock may set *none* of them (the LED
predicate could be "row has a `+0x62` entry"). This is what the `pattern-diff`
pass settles.

#### Phase 0 test-pattern plan (uses octabam `ot_project.py pattern-diff`)

octabam's `tools/ot_project.py pattern-diff <projA> <projB> <bank>` diffs every
step-mask between two saved projects and prints the mask offset + steps that
changed — turning "which bit" into a 30-second hardware job. Also useful:
`pattern-trig` writes a trig on disk, `emu_rtos.py` loads a project through the
real firmware and runs the sequencer (see `techniques.md`). Bring both into
`tools/` (or `refs/octabam/tools/`) for the session.

On the MKI, from one cleared baseline project, save a copy after **each** of:

1. one **pure trigless lock** (2 p-locks: e.g. FILTER cutoff + AMP VOL) on step 4
2. erase **one** of those p-locks live (`[NO]`+knob, LIVE REC) — lock still lit
3. erase the **second** — lock should vanish (this is the target behaviour to observe today: it *doesn't*)
4. a **trigless trig** with LFO retrig + 1 p-lock on step 8
5. a **manually placed empty** trigless lock on step 12
6. a normal **sample trig** with 2 p-locks on step 16

`pattern-diff baseline↔1` pins the trigless-lock mask bit + the `record[step]`
offsets for cutoff & VOL (confirms the byte→param map). `1↔2↔3` shows the
multi-pass erase semantics and whether the mask bit clears on 1→0. `baseline↔4`
separates the retrig-trig mask from the pure-lock mask. `4` vs `5` vs `1`
separates "has retrig" from "bare lock" — the predicate must keep 4, delete 3,
keep 5.

#### Phase 1 — the LIVE-REC `[NO]`+knob erase handler (not yet located)

Static RE never pinned the knob→param *writer* (NOTES L410: "scattered through
UI"). Two ways in: (a) `emu_rtos` — drive a `[NO]`+knob event and watch what
touches the `+0x62`-equivalent RAM region (`[0x46c82456] + pat*0x18b2`, near
`+0x8f385`); (b) trace back from the mask consumers `0x4009d382..0x4009da12`.
The detour goes *after* the clear: if `record[step]` is all-`0xFF` and the step
is a bare trigless lock, clear its mask bit. Conservative — keep on any doubt.

> **octabam leads (2026-09-08, `COLDFIRE_PORT.md` O9b / `EMU.md`):**
> a coverage diff of a trig-run vs a no-trig run names **`0x4000c42c–0x4000c5a0`
> as "the p-lock applier"** (in the trig's 124-PC footprint, alongside an
> armed-bitmask check at `0x4000bd14`) — distinct from our Session-39 chain
> (`0x4009d1e8` step handler → `0x4000bad4` per-frame apply); cross-check it for
> the `+0x4900`→`#1` commit. And octabam's **`emu_rtos.py` now runs the full
> transport + sequencer end to end** with a card *freshly saved on the unit* +
> `--poke-trig` + `--start` + `--internal-clock` (clears CLOCK-RECEIVE
> `0x80000028` bit 0) — the "not tractable headless" wall of Session 34 predates
> that maturity. Transport `FW_TRANSPORT 0x4009b964`, start case `0x4009c458`
> (`state 0x800065b8 := 1`, phase inc `0x46107570 := tempo24<<4`, post to UI
> queue `0x460d1664`); the STOP case is our remaining `+0x4900`→`#1` candidate.

---

## Firmware ↔ disk cross-reference

| Concept | Disk (OctaLib) | RAM (our RE) |
|---|---|---|
| pattern block stride | `0x8EEC` (bank file) | `pat*0x8ed8` for tempo/settings (`FUN_4009c550`); `pat*0x18b2` for trig/param (`_DAT_46c82456`) |
| per-track block | `LENGTH_TRAC 0x922` | `trk*0xc` within the `_DAT_46c82456` trig region (**mismatch — resolve**) |
| pattern → Part | `PTRN +0x8EE7`, 1 byte | `FUN_40009094` applies Part by event |
| regular trigs | `TRAC +9` (mask 0x00), bit `step-1` | `FUN_400977cc` consumes trig → voice cmd |
| per-track seq data | `LENGTH_TRAC 0x922` (disk, 9-B header) | RAM stride **`0x91a`** (`mulsl #0x91a,%d7` @ `0x4009d376`) — 9 less: chunk header stripped on load |
| pattern seq data | `0x8EEC` (disk) | RAM `0x8ed8` — 8 less (`PTRN` header 8 B stripped) |
| playing bank/pattern | — | `0x800065bd` / `0x800065be` (sequencer's own; step handler indexes `bank*0x9b340 + 0x400e21e0`, `pat*0x8ed8`) |

octabam (RTOS §10.6) measured the RAM strides directly: **pattern `0x8ed8`, track
`0x91a`** — exactly `disk − header`. So a `TRAC`'s data *does* survive into RAM at
the same relative offsets (mask 0x00 at RAM `+0`, etc.); the older "RAM `trk*0xc`"
note was a different (header/pointer) view.

### RAM p-lock array — **CONFIRMED** (Session 24, `tools/emu_plock.py --confirm`)

**`[0x46c82456] blob + pattern*0x8ed8 + track*0x91a + 0x59`, 64 steps × 32 bytes** —
byte-for-byte identical to the disk `TRAC+0x62` array (the `+0x59` = disk `+0x62`
minus the 9-byte chunk header). Verified by loading the factory OT DEMO through the
real firmware in `emu_rtos` and diffing the RAM against `bank01.work` (P11 t2:
param header `10 02 00 ff …` and every locked step/offset/value match exactly). So
the on-disk map above **is** the RAM map — no repack. The param header
(`[LEN] 02 00 FF …`) is at blob `+0x50`.

### The p-lock RAM structures — four of them (Session 24)

| # | Address | Shape | Role |
|---|---|---|---|
| 1 | blob `TRAC+0x59` | `record[step][32]`, `0xFF`=unlocked | the pattern's **stored** p-locks (= disk, persisted on save) |
| 2 | `0x46c7ab30` / `0x46c76ac0` / `0x46c75fa0` | `[track*32 + param]` values (×2) + `[track*4]` bitmap | the sequencer's **live per-track working set** — the step handler `0x4009d1e8` + per-frame apply `0x4000bad4` read these; the engine applies them |
| 3 | `0x46c7aa24` / `0x46c77c32` / `0x46c7a874` | same `[track*32]` shape | **scene** p-lock storage (step handler uses these for the `d2 == -1` master/scene case) |
| 4 | `0x46c7bf2c` / `0x46c7d7d8` / `0x46c7e0de` | value `[param + heldStep*128]` / bitmap / per-param flag | **MIDI-track CC-lock** send queue — `FUN_40033e3c(track, param, value)` writes it (guard: `[0x8000003f + track]` must equal a held trig; `[0x46c76de0]` = the held list), `FUN_400409f4` sends each set bit as MIDI CC (`FUN_40010bc8` = serial TX ring) then clears it. **`emu_plock.py --call3e3c` (Session 25): `FUN_40033e3c` writes ONLY #4 — so it is NOT the audio p-lock writer.** The `[NO]`+knob path calls it with params `0x34–0x36` (`0x4005e164/e1a8/e1d2`). |

Flow (Session 38 corrections):
- **load** → `FUN_4009b220` fills #2 with `0xFF`, then the deserialiser populates #1
  (TRAC chunk) and `+0x4900` (its own chunk — Session 37).
- **pattern-enter / start-track** → `0x4009b842` / `0x4009c020` copy **#3 (SCENE)
  `0x46c7aa24` → #2**, per track (32 B + second array + bitmap). NOT #1→#2.
- **step** (playhead) → step handler `0x4009d1e8` per-param loop `0x4009d7dc`:
  reads `#1[step][param]` (`0x91a` stride, `+0x59` — the `lea @(0x58,Xn);lea
  @(1,An)`); `!= 0xFF` → writes it into **#2** unconditionally (no
  `+0x4900`/`+0x48d8` check). Then **per-frame apply `0x4000bad4`** reads the
  `#2` bitmap `0x46c75fa0` and applies to the engine. **Playback = `#1` → `#2`
  → engine; `+0x4900` is nowhere in the chain (Session 39).**
- **`+0x4900` → `#1` commit**: not found (S39). Not in edit (`0x4004ef54`) /
  release (`0x4005fb44`) / save (`0x4008a740`) / pattern-enter / step-handler /
  `0x4009da20` / frame-apply. `blob+0x4900` (`0x400e6ae0`) has 4 refs
  image-wide, all in the LIVE cluster. The commit is on transport (STOP/PLAY,
  `FW_TRANSPORT 0x4009b964`) / loop-wrap / a deferred task — untraced.
- **LIVE edit** (`0x40041784`/`0x40041bc4`) → `+0x4900` + bitmaps only, **never #1**;
  arms a bit in `0x46c7d344/d348`.
- **p-lock-mode exit** (`~0x40062120`) → draw family + `0x400339d8` (LED from #1) +
  `0x4009da20` (working set) + **`clrl 0x46c7d344/d348`** (arm bits). The
  `+0x4900` → #1 **commit** rides here (not yet pinned to an instruction —
  Session 39); today it is **add-only** (a LIVE erase's `0xFF` doesn't un-lock #1),
  which is Session 13's bug.
- **save** → #1 and `+0x4900` written as separate verbatim chunks (Session 37).

**The `[TRIG]`-hold + knob → #1 writer — LOCATED as `0x4004ef54` (Session 27); it
writes a live-edit buffer `+0x4900`, not #1 directly.**

*p-lock editor gate state* (Session 27, disassembled at the correct
`--adjust-vma=0x40000400`; all in the `0x460d17xx` UI-scratch page):

| addr | role |
|---|---|
| `0x460d172e` | **armed** flag (`u32`) — `!= 0` ⇒ a p-lock edit is in progress. Reader `0x40033d70`. Set `= 1` at `0x4005100c` (audio) / `0x4005167a`, cleared at `0x4005fbf2` / `0x40060196`. |
| `0x460d174a` | **u16 held-step bitmap** (bit p ⇒ step `0x460d174c + p`). Set `\|= 1<<step` at `0x40050fb8`. |
| `0x460d174c` | **u16** held-step base (`= basestep<<4`, `basestep = [0x460d1e04]`); reset when the bitmap goes 0. |
| `0x460d1746` | offset of the held step's record, **stride 0x10/step** (`basestep<<4 + step`, `0x40050fd0`). |
| `0x46c7d2e4` | per-step `\|= 1<<param` **locked bitmap** the knob writer maintains (`byte[step]`). Empty at rest. |
| `0x100b14d0` | current **pattern** byte (confirmed — `mvzb` → `0x0a` = DISK_PAT). |

Arm it from the harness: `call_as_main(0x40050f20, (step, 1))` — runs clean, sets
all of the above for `step`.

*The real handlers* (Session 27 — ⚠️ the image loads at vaddr `0x40000400`;
disassemble with `m68k-elf-objdump -b binary -m m68k:5407 --adjust-vma=0x40000400`,
never `0x40000000`. Session 26's fresh fn addresses are all 0x400 low):
- **grid-rec trig chain**: keycodes `0x01..0x10` → `0x40060ce0(keycode@4,event@8)`
  → (if `0x460d1736==0`) grid-rec trig dispatcher → event **1 (press) →
  `0x40050f20`**, 2 (hold) → `0x400587d4`, 0 (release) → `0x4005fb44` +
  `0x4003146c`. `0x40050f20(step, 1)` arms the editor: `0x460d172e = 1` (armed,
  `0x4005100c`), `0x460d174a |= 1<<step` (u16 held bitmap, `0x40050fb8`),
  `0x460d174c = basestep<<4` (u16, `basestep = [0x460d1e04]`),
  `0x460d1746 = basestep<<4 + step`. Gate: `0x460d5db4 ∈ {0,3}`, `0x80000012==0`.
- **p-lock knob-op dispatcher** = `~0x40062a00` (message handler, event struct in
  `a2`: `a2@0` opcode, `a2@2` param/matchval, `a2@8` value). Each opcode: if
  `0x460d172e != 0` (armed) → a p-lock op; elif `0x460d172a != 0` → a non-armed
  sibling.
  - **writer** `0x4004ef54(track@d7, matchval@fp, value@a2)` (from `0x40062a82`) —
    ⚠️ arg0 is the **track** (`d7`, drives `d5 = track*0x8b0`, `1<<track`). Writes
    `blob + pat*0x8ed8 + track*0x8b0 + step*0x20 + 0x4900 + 2` = value
    (`0x4004f062`), `0x46c7d2e4[step] |= 1<<track` (`0x4004f09e`). Only the `+2`
    byte; the record's `+0`/`+3`/`+4`/`+5` are the other 4 encoders of the page.
  - **eraser** `0x4004f124(track, a2@2, a2@3)` (from `0x40062a1c`) — `st`→`0xFF`
    into `+0`/`+3`/`+4`/`+5`.
  - **op 3** `0x4004f5f8(track, a2@2, a2@3, a2+8)` (from `0x40062afc`).

**`+0x4900` is the per-track LIVE-REC value buffer** (stride `track*0x8b0`,
step `*0x20`). `emu_plock.py --s27`: for the saved DEMO it is all `0xFF` while #1
holds every lock and `0x46c7d2e4` is zero — but that is because the DEMO was
never LIVE-edited, so its `+0x4900` **on-disk chunk** is all-`0xFF` (Session 37).
Other `+0x4900` byte writers: `0x4004f2a4` / `f3ac` / `f4d4` / `f830` (companion
slots), `0x400505f4` / `0x40050b98` (grid-rec), `0x4005fdc6` (release).

⚠️ **`+0x4900` is NOT repacked into `#1` on save** (Session 37 — refutes the
earlier model). The **bank-record serialiser `~0x4008a740`** (p-lock section
`0x4008ac20`–`0x4008b0d6`; `a5` = RAM pattern base, `d3` = file handle, checksum
`0x460fab5c`) writes, per track:
- **loop 1 / TRAC chunk**: `#1` (`a5 + 0x91a*trk + 0x59`, `0x800`) **verbatim,
  unconditional** + aux (`+0x859`, `0x40`) + aux2 (`+0x89b`, `0x80`)
- **loop 2 / a separate per-track chunk**: `+0x48d0`/`+0x48d8`/`+0x48e0`/`+0x48e8`
  /`+0x48f0` (8 B each) + `+0x48f8..+0x48ff` (bytes) + **`+0x4900`**
  (`a5 + 0x8b0*trk + 0x4900`, `0x800`) verbatim + `+0x5100` (`0x80`)

So `#1` and `+0x4900` are stored **side by side**, each read straight from RAM;
the working-view → `#1` merge is on **LOAD** or **pattern-enter**, not save
(Session 38 to pin which). `emu_plock.py --save` is the harness (sentinel `0x77`
in `#1` vs `0x33` in `+0x4900`; both reach disk, in different chunks).

**`0x400339d8` rebuilds the UI "step has a lock" bitmaps** — zeroes
`0x46c7d2e4[0..63]` + `0x46c7d48c[0..63]`, then for track 0–7 × step 0–63 ×
byte 0–31: stored `#1` byte (`blob + pat*0x8ed8 + track*0x91a + step*0x20 +
0x59`) `!= 0xFF` → `0x46c7d48c[step] |= 1<<track` (`0x40033a38`); live `+0x4900`
byte `!= 0xFF` → `0x46c7d2e4[step] |= 1<<track` (`0x40033a4c`). So
**`0x46c7d48c[step]` = bitmap of which tracks have a STORED p-lock on that step,
`0x46c7d2e4[step]` = same for LIVE `+0x4900` edits** (Session 29, proved:
`0x46c7d48c` bit `t` lights exactly #1's locked steps for track `t`). **The
detour anchor.** ⚠️ it reads `[0x100b14d0]` for the pattern — the emu harness
drifts that to 0 after a run-to-spin, re-assert before calling.

`objdump` prints a brief-format `lea (d8,An,Xn)` disp as raw hex with no `0x`
(so `lea %a0@(58,%d3:l)` = `0x58`), unlike a `(d16,An)` disp (signed decimal).

**The LIVE-REC gesture (`[NO]`+knob live-erase — the trigless-lock feature's
path)** is the `0x460d172a != 0` branch of `~0x40062a00`:
`0x40041bc4(track, a2@2, a2@3, a2@4)` = LIVE write/erase (grid-rec's
`0x4004ef54`/`0x4004f124` are the `0x460d172e`-armed siblings). `0x40041bc4`
updates p-lock state across parallel views keyed
`blob + bank*0x9b340 + pattern*0x8ed8 + track*{stride}`:
`+0x48d8`/`+0x48e0` (2×u32 param bitmap, track stride `0x8b0`, `0x1001aa26`
mirror) · `+0x4900` value records (bytes `+0/+1/+3/+4/+5` `st`'d `0xFF` on erase) ·
`+0x2880` PART-payload (`0x458` track / `0x476c` pat / `0x4d9a0` bank, a 6-bit
field at bits 7-12 of a u16) · `0x46c7d2e4[step] |= 1<<track` · dirty flags
`[0x4017d512]`, `[0x100f8598]`. **It never checks "lock count → 0" and never
touches a trig-type mask** — so the emptied trigless lock persists (Session 13's
complaint). The step handler (`0x4009d740`+, per-param loop `0x4009d7dc`)
consults a 64-bit param bitmap at **`TRAC + 0x0a`** + the `#1` values at
`TRAC + 0x59`.

**A pure p-lock trigless lock is DERIVED, not flagged** (Session 31,
`emu_plock.py --trigless` — hand-clear a locked step's `TRAC+0x00` note bit on
disk, reload): the step is then a trigless lock with **no other bit set**
anywhere (`TRAC+0x08/0x10/0x18/0x0a`, `+0x48d8`, `+0x4900` all empty at load),
and `0x46c7d48c[step]` (→ the dim-lock LED) lights **byte-identically** to the
note+lock case. So **trigless lock ≡ `#1[step] != 0xFF && TRAC+0x00 bit clear`**.

Revised model: **`#1` (`TRAC+0x59`) = the store** (deserialiser fills it on
load); `TRAC+0x0a` / `+0x48d8` / `+0x4900` are runtime working views, **empty
until an edit populates them lazily**. `0x40041bc4` (LIVE erase) clears the
working views but **not `#1`** → the emptied lock survives in `#1`, the LED stays
lit, re-serialises on save = Session 13's complaint.

**Detour (Option B)**: hook `0x40041bc4` exit — erase that took the `(track,
step)` working param-bitmap to 0 AND step is a pure trigless lock (`TRAC+0x00`
and `+0x08/0x10/0x18` bits clear) → clear `#1[track][step]` (32 bytes → `0xFF`) +
let `0x400339d8` refresh.

**Detour core action VALIDATED** (Session 32, `emu_plock.py --trigless`): on the
trigless bank, `#1 t1 step 4 := 32×0xFF` then `0x400339d8` → `0x46c7d48c[4]` goes
`0x43 → 0x41` (track-1 bit cleared → LED off), step 0 and other tracks untouched.

**The gap** (S33–34): `0x40041bc4` (LIVE erase) writes only `0x46c7d344` (arm
bit) + `0x46c7d2e4[a3]`, never `#1`; and (S37) **save doesn't merge either** —
`#1` and `+0x4900` are separate on-disk chunks (see above). So a LIVE-erase's
clear of `+0x4900` *persists* across save/load on its own; the erased lock is
almost certainly already gone for **playback**, and only the **LED**
(`0x46c7d48c` ← `0x400339d8`, built purely from `#1 != 0xFF`) stays lit —
exactly Session 13's "pure visual noise". The remaining question (S38): does
the LOAD deserialiser / pattern-enter build the playback set (`#2`) with the
working views masking `#1`? If yes → the fix is small: **(b) gate
`0x400339d8`'s `0x46c7d48c` build on the step being live-present** (it already
reads `+0x4900`). (a) hooking `0x40041bc4` to clear `#1` stays the fallback —
`0x4009b290(track+8)` = `[0x80006500+track+8]` must be 1 to reach the erase
body; the `0x4009b2d4` decode needs `0x46c775bc/759c[track+8]`, `0x800064e8+trk`,
`0x46c775ce` — all unset headless.

**Best path forward** = Session 13's original **Phase 0: HW export-and-diff** on
the MKI (targeted test patterns → export → diff banks). Blocked on the MKI.
`emu_plock.py --s34` is the headless-drive attempt (dead end, kept as a record).

`0x8000004a` is the "what does a knob turn do" bitfield: bit 0 → write the Part-data
value (encoder `0x4004eb24`); bit 1 → the CC-lock path.

`emu_plock.py --s27` compares `+0x4900` vs #1 and arms via `0x40050f20`;
`--watch --trig N --applyknob P V` arms then drives the `0x4004ef54` writer.

---

## To import next

- **ems-octakit** — **open-sourced 2026-09** (`ca3b527`). Distilled into
  [`octakit-abi.md`](octakit-abi.md): its `runtime/abi.inc` confirms
  `FUN_4008ded0` = bank deserialiser, `_DAT_46c82456` = bank pointer,
  `GK_STOCK_BANK_SIZE 0x9b4d1` = the DEMO `bank01.work` size, `GK_PART_PAYLOAD_SIZE
  0x18b2`, and adds the `.work`↔`.strd` store/restore choke points
  (`0x4008eda4` / `0x4008f0b0` / `0x4008ee74` / `0x4008f180`), the per-parameter-page
  payload offsets, and `GK_STOCK_SEQUENCER_PART_{STEP,CONDITION}_OFFSET`
  (`0x1832` / `0x1822`). Watch: `GK_STOCK_PATTERN_PART_OFFSET 0x8e57` vs OctaLib
  `+0x8EE7` — different framing, reconcile before a write.
- OctaLib credits **WiliWoW** (Elektronauts) for format help — worth a thread search.
- **octabam `ot_project.py`** (`@ 2f241e1`) — `pattern-trig` / `pattern-diff` /
  `set_track_slot` / `set_machine_type` / `part-name`: an on-disk bank/project
  editor + differ. `pattern-diff` is the tool for the p-lock Phase-0 pass above.
  `emu_rtos.py` loads a project through the real firmware (see `techniques.md`).
  Both worth vendoring into `tools/` for the next hardware session (their licence
  posture = octamax's: facts + small excerpts, not bulk source).
- Best remaining lever for the p-lock model: the Phase-0 `pattern-diff` pass
  (needs the MKI) + locating the LIVE-REC erase handler (needs `emu_rtos` or
  Ghidra).
