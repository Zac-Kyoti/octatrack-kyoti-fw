# Octatrack OS 1.40C — address map (merged)

The single cross-referenced picture: our findings (`NOTES.md`) + anything imported
from the external repos. **Seeded 2026-09-02 from `NOTES.md` Sessions 1–15;** extend
it as you go (see `reference/kb/README.md` for the entry rules).

Namespace: `0x40xxxxxx` = MAIN OS code (load base `0x40000400`, file
`out/raw/section_3_MAIN_OS.bin`) · `0x800xxxxx` = work RAM · `0x46cxxxxx` /
`0x20xxxxxx` = MMIO & driver structs · `FUN_`/`DAT_`/`_DAT_` = Ghidra auto-names.

Confidence: **C**onfirmed (HW or real decompile) · **L**ikely (emu/inference) ·
**?** open question.

---

## Boot / platform

| Addr | Conf | What | Source |
|---|---|---|---|
| `0x40000400` | C | MAIN OS load base | START_HERE |
| `0x46c8d18c` | C | MKI/MKII probe. `tstl 0x46c8d18c ; sne ; …` → `moveq #15` becomes 15 (MKI) or 16 (MKII) PERSONALIZE items. Stock 1.40C is one image for both. | NOTES §"MKI only" |
| `FUN_40001d4c` | C | DSP **P-memory** loader — 24-bit word stream, starts `0x20000000 = 0x81`. Uploads the DSP program at startup. | NOTES L269 |
| `0x80000037` | C | SOLO-mode flag (byte). `FUN_40004db8` branches on `tst.b 0x80000037`. | NOTES Session 11 |
| `FUN_4000f938` | C | Boot **re-images the DSP shared-RAM window** from ROM: `0x401086f4` → `0x80000000` (`0x3e88` B) then zero-fill to `0x80004000`. Sole caller `0x40000512`. ⇒ **every `0x800000xx` word is volatile** — cleared on every power-on. | octamax `c78ff70` |

## Kernel / RTOS scheduler

> source: `refs/octabam/docs/RTOS_FORK.md` §2 @ `2f241e1` (2026-09-06), read byte-exact from the image. confidence: **C** for the addresses, **L/❓** for a few task rows. Our `COVERAGE.md` marks this untouched — this is the first map of it.

| Addr | Conf | What |
|---|---|---|
| `0x40000550` | C | **Scheduler entry** — one handler for `trap #0` (vector 32) **and** PIT0 (vector 171); boot writes it into both slots at `0x400005d8/dc`. Masks interrupts, `moveml` saves regs into the current TCB, takes the head of the top ready list, clears the reschedule bit (`0xfc04c010 &= ~0x800`), re-arms PIT0 with `0xb3f`, `rte`s into the new task. |
| `0x400005fc` | C | TCB builder. TCB: `+0x00/+0x04` next/prev · `+0x08` → list head `0x800068dc + 4·prio` · `+0x0c..+0x4b` saved `d0-d7,a0-a7` (**`a7` at `+0x48`**) · `+0x4c` ready flag. (`ARCHITECTURE.md` §4's "SP at 0x38" is wrong.) |
| `0x800068fc` | C | current TCB pointer |
| `0x800068d8` | C | top-priority pointer — points *into* the `0x800068dc[8]` array of per-priority list heads (higher index = higher priority) |
| `0x40000d50(vec,fn)` | C | vector install → `[VBR + 4·vec]`; **VBR = `0x40000000`** (image's own first KB). Kernel init `0x40000db0` refills all 256 slots with the default trampoline `0x40000d74` (calls `[0x460ba970]`). |
| `0x400008ea` | C | signal/reschedule → sets **INTFRCH bit 11 of INTC1** (`0xfc04c010`), source 43 / vector 171 = the scheduler. Make-ready `0x4000063c` does *not* force. |
| `0x4000aad0` | C | **DSP frame handler** — INTC0 source 1, vector `0x41`, level 5. Installed `0x4001fc02`. Masks itself at entry; re-armed by state 7 of the chain it kicks. External-clock path `0x4000acbc`; countdown `0x46107570` decremented `tempo24<<4`/frame at `0x4000ad50`, forces INTC0 source 32 at `0x4000ae00`. |
| `0x400a1e0c` | C | **Sequencer tick handler** — INTC0 source 32, vector `0x60`, installed by seq init `0x400a1050`/`0x400a109c`. The source is **left masked**; the tick is delivered by INTFRC regardless of the mask (MCF54455RM §17.2.3). ~28 ticks / 400 frames at 120 BPM internal. |
| `0xb6` / src 54 | C | ATA interrupt → `0x40015304` (one sector per interrupt). PIT1 (storage delay) = vector `0xac` / src 44 → `0x40020d38`. |

**Tasks — eleven** (octabam, measured under the real scheduler): prio 6 voice/DSP
mailbox `0x40005540` · prio 5 storage(FAT/ATA) `0x4001ee30` · prio 4 key-repeat
timer `0x4005593c` · prio 3 **UI** `0x40056c40` · prio 1 **engine** (46-opcode
dispatcher) `0x4008445c` · prio 1 **sys** `0x40061a94` (serial+SPI, then spawns
storage/UI/p3) · prio 0 **main** `0x4001f834` (init list, then idle `bras .` at
`0x4001fc9c` — main *is* the idle task). Several prio-2/prio-1 rows still ❓.

**⚠️ The saved task context does NOT include EMAC state.** The TCB fields above
(`+0x0c..+0x4b`) are `moveml`-saved `d0-d7,a0-a7` only — no `MACSR`/`ACC0`/`ACC1`
slot. The EMAC's rounding mode (`MACSR` bit 6, S/U) is genuinely global, process-wide
state. **Confirmed directly against our own image** (`m68k-elf-objdump -m m68k:cfv4e`,
Session "part 5"): the per-frame copier function (`0x4000cae8`, per the per-voice-record
section below) sets `MACSR=0xb0` for an early knob/MIDI interpolator, then `MACSR=0x60`
(fractional, S/U=1, 16-bit rounding on `movclrl` read-out per the CFPRM's pseudocode) for
**four** near-identical back-to-back level-chain loops (`0x4000ccae`/`cd22`/`cd64`/`ce40`
— our `levelchain_mute` hook 12's site, MUTE MODE thread, is the last of these four, at
`0x4000ced0/ced4`), then later, **still inside the exact same function, no `rts` in
between** — this is sequential code, not a separate task — sets `MACSR=0x20` twice more
(`0x4000cf60` register-sourced, `0x4000d3ae` literal). No explicit interrupt-mask write
(`%sr`/`trap`/`rte`) was found anywhere in this ~1.7 KB span either. So the hazard isn't
"two tasks fight over MACSR" (there's only one task/call here) — it's that **this one
function's own MACSR=0x60 window can, as far as static disassembly can show, be preempted
by a PIT0 tick (5.0 ms / 220.5 samples) like any other code, and if some UNRELATED task
elsewhere in the system also touches the EMAC while it's paused** (plausible in volume:
`kb/techniques.md` already notes "~5,600 EMAC-site instructions run per sequencer frame"
system-wide) **the resumed function reads back corrupted values for the rest of its own
pass — every remaining track/ping this invocation still has to do, not just one.** Any
change that adds cycles to one of the four level-chain loops (100+ combined hits/frame)
shifts how close this function runs to the tick boundary and is a plausible way to open
that window on a build that never opens it stock — a race a short/synthetic emulator
scenario may never get scheduled into. **Not yet resolved**: which task calls this
copier function at all, or whether it's even preemptible in practice (needs dynamic
tracing, `emu_rtos.py`, not more static reading — see `NOTES.md` "Session 58 continued
yet again, part 5"). (source: `refs/octabam` `CLAUDE.md` "MACSR S/U IS BIT 6..." +
`docs/firmware/KERNEL.md` "Emulator facts", pulled 2026-09-16 at `f77d5d7`; octabam's own
ColdFire port had this exact S/U bit wrong for this exact function once, "every voice
rendered silent" — O9b, 8 Sep 2026 — independent confirmation this specific code is
unusually easy to mismodel.) See
`NOTES.md` "Session 58 continued yet again, part 4" for the mute-mode incident this
was pulled to explain.

## Sequencer clock / tick

| Addr | Conf | What | Source |
|---|---|---|---|
| `0x4000aad0` | C | Frame ISR. Fires on reading the frame index at `0x2000001c`; accumulates a `2³¹/tempo` phase accumulator; wakes the seq task via a kernel queue. Sample-accurate. | NOTES L261, COVERAGE |
| `0x2000001c` | C | MMIO frame-index register (read triggers the ISR path) | NOTES L261 |
| `FUN_4009c550` | L | Sets tempo period from pattern data (`_DAT_46c82456 + pat*0x8ed8`) | NOTES L260 |
| `FUN_400977cc` | L | trig → voice command mapping (seq task side) | COVERAGE, NOTES L263 |
| `FUN_40005030` | L | trig apply path (paired with `FUN_400977cc`) | NOTES L298 |
| `0x4009d1e8` | C | **step handler** — called per track ~3 frames ahead of the step; the frame-0 call schedules the event that fires on the step. | octabam RTOS §8.3 |
| `0x4009b5c8` | C | `FW_START_TRACK` — indexes the bank blob by the sequencer's *own* playing bank/pattern bytes `0x800065bd`/`0x800065be` (`bank*0x9b340 + 0x400e21e0`, `pattern*0x8ed8`). Same `FUN_4009b5c8` as NOTES' "normal track start". | octabam RTOS §8.3 |
| `0x800065bd` / `0x800065be` | C | the **sequencer's** playing bank / pattern (distinct from the pending/active/outgoing bytes at `0x800065bf..c2`). DIRECT JUMP's step-position lever `_DAT_800065b4` lives right below. | octabam RTOS §8.3 (confirms NOTES Session 15) |
| `0x400a1030(bank,pat)` | C | wrapper over the cue-primitive `FUN_400a0570`; the LOAD PROJECT handler's last step is `0x400a1030(0x80000002, 0x80000004)` at `0x40025b16`. | octabam RTOS §8.3 |

### Per-step sequencer data — the TRAC step masks

> source: `refs/octabam/docs/RTOS_FORK.md` §10.6 @ `2f241e1`, hardware-confirmed via `pattern-diff` (6 Sep 2026). See [`file-format.md`](file-format.md) for the on-disk side. confidence: **C** for the recorder masks + mask 0x00, **L** for 0x08–0x38.

A `TRAC` record opens with **8 step-mask fields, 8 B each (64-bit BE, bit `step-1`)**;
RAM per-track stride `0x91a` (`mulsl #0x91a,%d7` at `0x4009d376`). Disk data starts
9 B past the `TRAC` tag (header is tag+len+**1 pad**), i.e. our file-format offsets
from the tag: `+0x09, +0x11, +0x19, +0x21, +0x29, +0x31, +0x39, +0x41`.

| mask (RAM) | disk off | consumer | meaning |
|---|---|---|---|
| `0x00` | `+0x09` | `0x4009d41c` | note / sample trig (`poke_trig`'s target) |
| `0x08` `0x10` `0x18` | `+0x11` `+0x19` `+0x21` | `0x4009d382..9a` | ORed into the "anything on this step" test — trig-type / trigless-trig layers |
| `0x20` | `+0x29` | `0x4009d93c` → bit 12 of `0x46c7a6c0` | **recorder trig, REC1** (matches OctaLib `OFFSET_TRACK_REC_TRIGS +0x29`) |
| `0x28` | `+0x31` | `0x4009d96e` → bit 13 | **recorder trig, REC2** (HW-confirmed: toggling REC2 off clears only this) |
| `0x30` | `+0x39` | `0x4009d99a` → bit 14 | **recorder trig, REC3** |
| `0x38` | `+0x41` | `0x4009d9f6` → bits 5+8 | swing / slide (read only when 12/13/14 fired) |

`0x40` / `0x48` (disk `+0x49` / `+0x51`) are **not masks** — a per-step byte array
(default `0xAA`); `0x4009d3d6` gates a per-step byte into a timing calc. Per-track
flag word: `0x46c7a6c0`.

## Pattern change / cue / Parts  (Session 15 — DIRECT JUMP)

| Addr | Conf | What | Source |
|---|---|---|---|
| `FUN_400a0570(bank,pat,loopStart,loopEnd,p5)` | C | **The cue-pattern primitive** — single choke point for every pattern change (manual trig, arranger, chain). If seq running (`_DAT_800065b8==1`) it stashes the pending pattern into `_DAT_800065bf/c0`. | NOTES Session 15 |
| `FUN_400a1eea` | C | Per-step pattern switch / pattern reload. 3 reload blocks, each zeroes `_DAT_800065b4`. CHAIN-AFTER gate inside. | NOTES Session 15 |
| `0x400a44d0` | C | **THE COMMIT**: `move.b D1,(0x800065be)` then `0x400a44dc: move.b (800065bf),(800065bd)` — pending pat/bank → active. `800065c1/c2` first hold the *outgoing* pat/bank. | NOTES L3866 |
| `FUN_4009e884` | C | Sends MIDI Program Change for a pattern switch — fired 2 steps early (`if DAT_800065b6 == 2`). | NOTES Session 15 |
| `_DAT_800065b4` | C | Master step position — reset to 0 in every pattern-reload block (this is the lever DIRECT JUMP save/restores with modulo). | NOTES Session 15 |
| `DAT_800065b6` | ? | Step counter — NOTES uses it as both "sub-step counter reset every full step" (L1332) and "master step" (L3728, `==2` PC preload). **Reconcile before relying on it.** | NOTES L1332 vs L3728 |
| `_DAT_800065b8` | L | Per-pattern "sequencer actually stepping" state (not merely "playing") | NOTES L1638 |
| `0x800065bd–c2` | C | pending/active/outgoing bank+pattern bytes (see COMMIT above) | NOTES L3866 |
| `_DAT_800065bf/c0` | C | pending pattern stash written by `FUN_400a0570` | NOTES Session 15 |
| `0x800000a8` | C | free scratch word — DIRECT JUMP menu state (`OFF/ON`) | NOTES Session 15 |

## Parts / Bank apply

| Addr | Conf | What | Source |
|---|---|---|---|
| `FUN_40009094` | C | Applies a Part **by event** — per-track apply loop. The only path that actually swaps Part params (Scenario B). Hook point for lazy Part transitions. | NOTES L295–298 |

## Track start / PLAYS FREE

| Addr | Conf | What | Source |
|---|---|---|---|
| `FUN_4009f3a4` | C | Reads `PLAYS_FREE` / `SCALE_MODE` / `DIRECT` per-track flags at track-struct `+0x48fc` / `+0x48fd` / `+0x48fe`. | NOTES L1506 |
| `FUN_4009b5c8(track)` | L | Normal (non-PLAYS-FREE) track start | NOTES L1540 |
| `FUN_40044584(track, pressOrRelease)` | C | **Manual-trig key handler** — the Bug 1 (Plays-Free MIDI manual-trig stall) site. Fix lives in `tools/patch_trigscale.s`. | NOTES L1515, Bug 1 |

## Voices / audio data model

| Addr | Conf | What | Source |
|---|---|---|---|
| `0x800049d8` | C | Per-track voice state. Stride `0xA8` (168), 8 tracks; voice index ≡ track for sample machines. Safe resolver `FUN_40000e50(voice) → 0x800049d8 + voice*168`. Field map (octamax `DESIGN_SLICEVIEW.md` @ `7d9debc`): `+0` (b) active `0xFF`/`0` · `+8` (l) SETTINGS ptr (slot-resolved) · `+23` (b) loop mode 0 one-shot / 1 loop / 2 ping-pong · `+32` (b, signed) **current slice index**, `−1` none (re-bound every audio frame → tracks p-locks/scenes) · `+36` (w, signed) rate `0x4000`=1.0×, `<0` reverse · `+48/+52` (l) active window start/end · `+68` (l) **live play position** (`0x40008898` fwd / `0x40008e6e` rev). Torn on loop-wrap (`0x400088dc..902` rewrites 6 longs) — clamp, don't mask. Playback-position engine (bounds/wrap/ping-pong) = `FUN_40007960`, ColdFire not DSP. | NOTES L192 · octamax `7d9debc` |
| slice table | C | via `SETTINGS = voice@8`: entry `n` at `SETTINGS + 312 + n*12 = {start,end,loop}` (loop `0xFFFFFFFF` = no loop point); count at `SETTINGS + 1092`; firmware indexes `+300 + (slice+1)*12` (entry −1 = whole-sample trim). Stock SLICES view renderer = view-3 arm of `0x40044920` (`0x40044cda..f06`): grid bitmap `0x400beafa` at (61,10), count read at `0x40044e28`. | octamax `DESIGN_SLICEVIEW.md` @ `7d9debc` |
| `FUN_40005178` | C | Queues per-track voice commands into mailboxes `0x46c7e9fa` / `0x800018be` / `0x800018de`, indexed `[t*4]`. | NOTES L196 |
| `FUN_40097168` | L | Machine-type page dispatch (5 PLAYBACK descriptor entries). ⚠️ the **stored machine-type byte** values are **0 = STATIC · 1 = FLEX · 4 = PICKUP** (octabam RTOS §10.13, by code + data — the trig-side slot lookup `0x400050b8` routes type 0 → STATIC arena `0x100d5b30+id*1096`, types 1/4 → FLEX arena `0x100b14f0+id*1096`). THRU/NEIGHBOR have no slot. | COVERAGE · octabam `47f6cc5` |
| `0x80004f1c` | C | **per-track RECORDER state record** — 16 × 84 B (2 banks × 8 tracks, double-buffered; bank bit per track in `0x80004f18`). Arm caller fills the *other* bank (header `0x00000101`, `+2` = 1 pending); per-frame track fn `0x400068e4` promotes 1 → 2 and flips the bank. Not a sample-slot record. | octabam RTOS §10.13 |
| `0x80003c20 + 16*type` | C | recorder **block-table reciprocal** = `2^31 / block_size` (type 0: 2048 / 3 B/sample · 1: 1024 / 6 · 2: 3072 / 2 · 3: 1536 / 4). `macl pos,recip` (fractional) = `pos / block`. | octabam RTOS §10.16 |
| `FUN_40008f84(track)` | C | Start a graceful voice release — sets `DAT_8000184a \|= 1<<t` (release *state*). | NOTES L2703 |
| `FUN_40008fe4(track)` | C | Wraps `FUN_40008f84`; also sets `DAT_8000184c = 0xff`. `FUN_40008fe4(0xffffffff)` = all. | NOTES L2709 |
| `DAT_8000184a` | C | voice-release state bitfield (`1<<t`) | NOTES Session 9 |
| `DAT_8000184c` | C | voice-release **ramp trigger** bitfield (`1<<t`) — the bit that actually starts the fade. | NOTES L2765 |
| `FUN_400836d8` | C | voice release phase handler; `phase==1` branch. No-op for FLEX/STATIC. | NOTES L2683, L2760 |
| `0x46c7ff42` | L | Per-voice **pre-FX amp** array. Stride 4, 8 voices. Filled every frame by `FUN_4000d16c` at `0x4000d36e`. Sits right below `_DAT_46c7ff64`. Candidate lever for the 4th mute mode. | NOTES Session 14 |
| `FUN_4000d16c` | C | Per-frame voice-parameter fill (writes `0x46c7ff42[t]`) | NOTES Session 14 |

## Mute / solo / cue

| Addr | Conf | What | Source |
|---|---|---|---|
| `_DAT_80000008` | C | Mute/solo/cue bitfield. **bits 0–7 = solo, 8–15 = mute, 16–23 = cue** (per project memory; NOTES L3053 says bit 8+t muted / bit 16+t cued — consistent). | NOTES Session 9/11 |
| `FUN_40004dbc` (entry `0x40004db8`) | C | Per-frame **mute gate**. `D5 = _DAT_80000008`; per-track. Hook site `0x40004dc6`. Its only mute lever = zero the post-FX MAIN word. Branches on `tst.b 0x80000037` (solo). SOFT MUTE hooks here + `FUN_40005178`. | NOTES Session 9/11/14 |
| `_DAT_46c7ff64` | C | "silenced in MAIN out" mask (`<<8` per-track layout) — the **post-FX MAIN mute**. Read by the frame builder. | NOTES Session 9/14 |
| `FUN_40083eb0` | C | Track-LED painter. Loops 8 tracks over an id table at `0x400a9670`; reads the same `_DAT_80000008` mute/cue bits. | NOTES L704, L3053 |

## Storage / file data model

| Addr | Conf | What | Source |
|---|---|---|---|
| `_DAT_46c82456` | C | **Bank-blob pointer** (the deserialised bank). Blob base seen `0x400e21e0` after a load; the step handler `0x4009d1e8` indexes it `bank*0x9b340 + 0x400e21e0`, pattern `*0x8ed8`, track `*0x91a`. (Distinct from `pat*0x18b2` = the PART-payload view.) | NOTES L197 · octakit-abi · Session 24 |
| `_DAT_46c82xxx` | ? | FAT-layer vtable region (storage driver) | COVERAGE |

### p-lock RAM structures (Session 24 — `tools/emu_plock.py`)

| Addr | Conf | What |
|---|---|---|
| blob `TRAC + 0x59` | **C** | the pattern's **stored** p-locks, `record[step][32]`, `0xFF` = unlocked. RAM = disk `TRAC+0x62` byte-for-byte (`emu_plock.py --confirm`). Persisted on save. Param header at `+0x50`. |
| `0x46c7ab30` / `0x46c76ac0` | C | the sequencer's **live per-track** p-lock values, `[track*32 + param]` (32 params/track). The engine + step handler read these. |
| `0x46c75fa0` | C | live per-track lock **bitmap**, `[track*4]` longs. |
| `0x46c7aa24` / `0x46c77c32` / `0x46c7a874` | C | **scene** p-lock storage, same `[track*32]` / bitmap shape. |
| `0x46c7bf2c` / `0x46c7d7d8` / `0x46c7e0de` | C | **MIDI-track CC-lock** send queue — `FUN_40033e3c` writes (gated `0x8000004a` bit 1), `FUN_400409f4` sends each set bit as MIDI CC (`FUN_40010bc8`) then clears it. Not the audio store. |
| `FUN_4009b220` | C | fills `0x46c7ab30`+companions with `0xFF` (p-lock reset). Called from boot `0x4001f95c` + project load `0x400238a8`. |
| `0x4009b84c` / `0x4009c02c` | C | 32-byte copy loops: splice scene/pattern p-locks (`0x46c7aa24` …) → the live set (`0x46c7ab30` …) on pattern-enter. |
| `0x8000004a` | C | "what a knob turn does" bitfield: bit 0 = write Part-data value (encoder `0x4004eb24`); bit 1 = MIDI CC-lock path. |

## UI / menu

| Addr | Conf | What | Source |
|---|---|---|---|
| `FUN_4006d57c(title,nLines,linesArray,3,handler)` | C | Shared **confirm-popup / dialog constructor** — YES → `handler(0)`, NO → `handler(1)`; guard `_DAT_460e5cd0 == 0`. Used to add PERSONALIZE / menu entries (MUTE MODE, DIRECT JUMP). | NOTES L90 + `refs/octabam/docs/MAINMENU.md` @ e1dcfa9 |
| `0x400a9670` | C | 8-entry track-id table used by the LED painter | NOTES L704 |
| `FUN_40064908` | L | **SETTINGS-tree menu draw fn** — renders rows, calls each row's `+0x0c` value-getter. Row stride ×24 computed at `0x4006496a`. | `refs/octabam/docs/MAINMENU.md` @ e1dcfa9 |
| `FUN_40064c18` | L | SETTINGS-tree **menu opener** (heap-allocates the window); thunk `0x40064d78`. Cleanup `FUN_400650a0 → FUN_40064bc0`. Nav skip-if-unselectable at `0x40064f0a` / `0x40064fe8`. | same |
| `FUN_4005578c(keycode,edge)` | L | key dispatch via the u32 table at `0x400a7280` | same |
| `FUN_40005638` | L | FX-default initialiser — **contains** the FILTER/DELAY descriptor `lea` operands `0x40005680` (FX1) / `0x4000568a` (FX2) that octa-bt-pt patches. Not the live FX assignment, just the boot default. | `refs/octabam/docs/{MAINMENU,DSP}.md` + octa-bt-pt |
| `FUN_400053d8(0x44,0,0,val,0,0)` | L | generic setter, triggered by a write to `0x80000049` | `refs/octabam/docs/` @ e1dcfa9 |
| `FUN_40012bd8` | L | "draw string at (x,y)" text primitive; `FUN_40012254` = XOR-rect (selection highlight) | same |

> **SETTINGS tree ≠ PERSONALIZE menu.** octabam mapped the newer struct-based
> SETTINGS tree: **24-byte rows** (`+0x00` label ptr · `+0x04` geom · `+0x08`
> action fn ptr / selectable marker · `+0x0c` value-getter ptr · `+0x10` child
> list · `+0x14` page id) and a 28-byte list descriptor (`+0x00` count, `+0x04`
> scroll, `+0x18` row array). Our MUTE MODE / DIRECT JUMP work patches the older
> **PERSONALIZE** screen = 3 flat parallel `u32[16]` arrays at `0x400b2a34`
> (label) / `0x400b2a74` (getter) / `0x400b2ac0` (setter). Don't conflate them.

## Key input / dispatch

> sources: `refs/octabam/docs/{MAINMENU,RTOS_FORK}.md` @ `2f241e1` + our own keymap decode (Session 21). confidence: **C** for the tables + keycodes (decoded + disassembled), **L** for the `0x400d2d54` labels.

**The keymap** is 26-byte records `{u8 code, 0, press:u32, release:u32, h3:u32, aux:u32,
0, u16 flags}` in two tables — T1 `0x400bfc10..` (58 recs) / T2 `0x400c01f4..` (63 recs,
adds `0x1c..0x1f`); selector structs `{table_ptr, 0x400c085a}` at `0x400c090c` /
`0x400c0920`. The dispatcher calls `press`/`release` as `handler(keycode@4, event@8)`,
`event` 1 = press · 0 = release · 2 = hold. **Keycodes (decoded):**

| key | code | handler | key | code | handler |
|---|---|---|---|---|---|
| trig 1–16 | `0x00–0x0f` | `0x40060ce0` | **PTN** | `0x2e` | `FUN_4005a044` |
| track keys | `0x10–0x17` | `0x40040250` → mute `FUN_40083ab4` | **BANK** | `0x2f` | `0x4007af80` |
| **STOP** | `0x27` | `0x4004aca4` | **PLAY** | `0x28` | `0x40061778` (press only) |
| **REC** | `0x29` | `0x40048774` (press + release) | | | |
| param-page | `0x22–0x26` | `FUN_4005578c` (via `0x400a7280={0,2,1,3,4}`) | **PAGE** | `0x1b` | `FUN_4004ffc4` |
| MKII MAIN MENU | `0x1c` | `0x40064d78` → `FUN_40064c18` | **YES** | `0x31` | `0x4005e4c8` |
| **arrow UP** | `0x34` | `0x4004b970` | **NO** | `0x32` | `0x4005e25c` |
| **arrow RIGHT** | `0x21` | `0x4004b970` (same as UP) | **arrow DOWN** | `0x33` | `0x400491a0` |
| **arrow LEFT** | `0x20` | `0x400491a0` (same as DOWN) | | | |

Arrows (Session 43, confidence C — decoded from the keymap + cross-checked vs octabam
MAINMENU.md §7, HW-tested there): **UP `0x34` / RIGHT `0x21` share `0x4004b970`**;
**DOWN `0x33` / LEFT `0x20` share `0x400491a0`** (a wrapper — arg==press &&
`0x80000012`==0 && `0x8000004b`==3 → `0x460d17aa=1; jmp 0x4007c404`, else arranger →
`0x40049114`, else `rts`). `0x40049114` is the list-cursor mover: `0x460d16e4` cursor,
`0x460d16e8` scroll. `0x4004b970` special-cases keycode `0x34` vs `0x21` at `0x4004b9d6`.
Both handlers are reached via the keymap for `handler(keycode@4, event@8)`; RELOAD FROM
PROJECT's `patch_reload{,2}.s` detour both (displaced prologue: `0x4004b970` = `lea
-12(sp),sp ; movem.l d2-d3/a2,(sp)` resume `0x4004b978`; `0x400491a0` = `move.l d2,-(sp)
; movea.l 8(sp),a0` resume `0x400491a6`). The T1/T2 selector is chosen in the event loop
`FUN_40061b60` at `0x40061bca` on `0x46c8d18c` (MKI vs MKII).

`FUN_4005a044` (**PTN**): press → `0x460d1742 = 1` ("[PTN] held"), clear `0x460d173e`;
release → opens SELECT PATTERN (`FUN_40059f8c(0x400b484e, 0xf0, 1, 0x40043418)`) **only if
`0x460d173e == 0` and `0x460d1ab2 != 0`**. **No other handler reads `0x460d1742`** — so
`[PTN]` + X is a free chord, and a partner that sets `0x460d173e` suppresses the chooser.
(DIRECT JUMP's `[PTN]`+`[YES]` toggle, NOTES Session 21, uses exactly this.)

`0x4005e4c8` (**YES**): checks arranger `0x460d1aec` (→ `jmp 0x4004903c`), then `0x800000b8`
(`DISABLE YES/NO ARM`) → `rts`, else `bra 0x4005e294` (arm). Prologue 8 B =
`222f0004 202f0008`, resume `0x4005e4d0`.

| Addr | Conf | What |
|---|---|---|
| `0x400d2d54` | C | keycode-indexed jump table; `[27..29]` = `0x4000a274`/`0x4000a200`/`0x4000a1e0`. **This is the MIDI/DIN "RECEIVE TRANSPORT" remote path, not the panel** — each entry's first insn is `tstb 0x80000029; beq rts` (`0x80000029` = the RECEIVE TRANSPORT setting), and the `0x40001998` dispatcher only indexes keycodes 16–32. Panel PLAY/REC/STOP = keymap codes `0x28`/`0x29`/`0x27` (above). octabam's `emu_rtos` drives this path because its harness has `0x80000029` set. |
| `0x460d1726` | C | **"REC held"** (longword) — set to 1 at the end of every `[REC]` press (`0x40048830`), cleared on `[REC]` release (`0x4004883a`). No other handler distinguishes it → `[REC]`+X is a free chord. `0x40061778` (PLAY) already reads it: held → start LIVE REC, else transport toggle. (QUANTIZE LIVE REC toggle, NOTES Session 46.) |
| `0x46c7d8de` | C | runtime key-state table, stride **24**, one record per keycode ≤ 63, populated from the T1/T2 keymap by `set_key_state 0x40031734` (the sole per-key dispatcher: `set_key_state(code,event)` → calls the record's press/release handler with `(code@4, event@8)`). Record `+16` = held flag → `is_key_held(code)` = `FUN_4003171c` = `*(u32*)(0x46c7d8ee + code*24)`. `+8` (u16, from the keymap `flags` field) = hold/repeat delay; `0` ⇒ press fires once, no auto-repeat (true for all of trig / track / PLAY / REC / PTN / BANK; nonzero only for the arrows). |
| `0x80000000` | C | current audio track (byte; UI mirror `0x100b14cc`). `0x80000012 != 0` = MIDI mode (page resolution adds +8). FUNC is **not** a plain keymap record — its held-flag was not located (Session 21). |
| `_DAT_460e5cd0` | C | `!= 0` ⇒ a `FUN_4006d57c` dialog is open (that ctor bails on it at entry). Gate a new global combo on `== 0`. |

### Transient overlay primitives

| Fn | Shape |
|---|---|
| `FUN_4006d57c(title,nLines,lines,3,handler)` | **blocking** YES/NO dialog (needs a keypress); sets `0x460e5cd0` |
| `FUN_40059f8c(text, ticks, enable, on_timeout)` | auto-dismiss window, h=30px — **hardcodes `0x460d1e54 = 4` countdown boxes** (drawn by `0x40037cc8`, gated `0x460d1e5c != 0`), handle in `0x460d1e5c` (SELECT-BANK/PTN global, but the "in SELECT BANK" test also needs `0x460d1e60 == 0x4007b408`). Tick `FUN_40056ab8` (0 locatable callers but HW-confirmed live) → expiry `FUN_40056a70` (SELECT-close **then** jmp `0x460d1e60`, so the `on_timeout` cb fires only if `0x460d1e5c != 0`). **DIRECT JUMP v1's toggle** (`ticks 0x28` ≈ 0.66 s). |
| `FUN_4005a0e0(text)` | **bare text popup**, h=18px, own handle `0x460d1e64`, font `0x400ba862`, ctor `FUN_4005829c(w, 0x12, 0,0, 0xa, FUN_40056bc0)`, close cb `FUN_40056bc0`, **no timeout**. DEAD CODE in stock (0 callers). **DIRECT JUMP v2** revives it + `dj_tick2` (a frame countdown spliced at `0x400522ca` inside the per-frame fn `@0x40052200`) for a box-free auto-dismiss toast. |
| `FUN_4005a2b8(text, dur)` | the OS notification (= ems-octakit `GK_STOCK_NOTIFICATION_SHOW`, stock's "PART n RELOADED"). `dur > 0` → self-timing, no handle to manage (**DIRECT JUMP v3**, `patch_reload2` `rl_yes`). **`dur ≤ 0` → persistent** (the `0x4005a334` branch, no countdown); handle `0x460d1e70`, close explicitly with **`0x40056bec()`** (no args, no-op if none open). Window auto-sizes to `textpx + 15`, h=18px. **QUANTIZE LIVE REC** (NOTES Session 46) uses `dur = 0`, closed on `[REC]` release. |
| `FUN_4005829c(x,y,w,h,?,close_cb)` | bare window ctor; `FUN_40012f30` measures text, `FUN_40057008`/`FUN_40013904` draw. |
| `FUN_400808bc` | non-modal overlay example ("RELOADING BANK"), handle `0x460f790c`, explicit close. |
| `FUN_4001f23c` | recompute + store the `'ANDY'` block checksum (`0x100fff00`, over `0x100fff04`+252 B, `+=514`). Self-contained, no args, `rts`. Call this after writing an ANDY shadow from **outside** the PERSONALIZE dispatcher (which does it via `jmp 0x4001f23c @ 0x40069074`). |

### Screen drawing primitives & the periodic-repaint hole

> source: octamax `DESIGN_SLICEVIEW.md` @ `7d9debc` (2026-09). confidence: **C**
> (disassembled + emulator-green in octamax; feature itself not in any Kyoti build).

Surface descriptor `0x400bf10a` = 128×64, column-major, 32 px/longword. All
primitives cdecl; `mode` 1 = set / 0 = clear / −1 = XOR. Dirty flag (request a
flush): `move.l #1, 0x46c7c72c`. Fonts: `0x400ba876` (6 px) · `0x400ba89e`
(12 px). ⚠️ `0x460d1a54 == 2` suppresses flushes — set dirty, never call the
compositor directly.

| fn | signature |
|---|---|
| `0x40012254` | `fillrect(surf, x0, y0, x1, y1, mode)` |
| `0x40012bd8` | `drawtext(font, surf, x, y, mode, str)` |
| `0x40013904` | `drawfmt(font, surf, x, y, align, mode, measureStr, fmt, …)` |
| `0x40011b94` | `vline(surf, x, y0, y1, mode)` · `0x400128a8` `blit(bitmapDesc, surf, x, y)` |
| `0x40012f30` | measure text (used by the bare-window ctor) |

**The UI loop is event-driven** — it blocks on the message queue and flushes
(`jsr 0x40013abc @ 0x40062d46`) only when `0x46c7c72c` is set, so nothing paints
between events. octamax's fix for a live display: the timer task `0x40056c40`
runs the countdown tick `FUN_40056ab8` for every type-1 timer message, and the
6-byte `tstl 0x46104ca8` right after that call (**`0x40056c92`**) is a clean
detour hole that fires **even with no TIMER enabled**. Post UI event 78 (handler
`0x40062d04` → `jsr 0x4004581c` = view header+content redraw) to the UI queue,
throttled to one outstanding message. Blink phase = a patch-owned counter in
free RAM (`0x80006c66+`), toggled by the same tick. (NO TIMER / LAZY already
detour `FUN_40056ab8` — a proven periodic-UI-tick site.)

## Effect & machine parameter-descriptor table (`0x400d2e52`–`0x400d5f00`)

> sources: `refs/octa-bt-pt/patch_tool/addresses.json` + `tools/generate_streamlit_patch.py` @ `e970dd0` (2026-09-02) · **`refs/octabam/docs/PARAM_PAGES.md` @ `2f241e1`** (2026-09-06) — a full struct decode of the same table. confidence: **C** for FILTER/DELAY/NONE + the layout (two independent decodes agree), **L** for the other effects' id↔`E` pairing.

**One table describes every parameter page on the machine** — not just effects:
the 5 machine types, AMP, both LFOs, the recorder, the MIDI NOTE/ARP/CTRL pages,
routing, and the 15 effects. octabam: **31 entries × `0x192` (402) bytes**,
`0x400d2e52 .. 0x400d5f00`. 402 isn't a multiple of 4 → it's a **packed serialised
blob, not a C struct**; walkers must do unaligned longword reads. There is no
`lea`/immediate to the table base anywhere in the image (entries are reached
individually), which is why an xref sweep never finds it.

Entry layout (offsets from entry start `E`):

| off | size | field |
|---|---|---|
| `E+0x00` | 6×u32 | per-encoder handler pointers (usually `0x40038d94`) |
| `E+0x35` | 6 B | flags — not decoded |
| `E+0x3b` | u8 | **effect id** (0 for non-FX pages) |
| `E+0x3c` | 5 B | display abbreviation, NUL-term |
| `E+0x41` | 13 B | full name, NUL-term |
| `E+0x4e` | 12×6 B | **parameter names** (6/page, 2 pages), NUL-padded |
| `E+0x96` | 12×u8 | **default value** per parameter |
| `E+0xa2` | 12×u32 | **minimum value** per parameter |
| `E+0xd2` | 12×u32 | **number of selectable values** per parameter (count, not max: `128`=0–127, `2`=on/off) |
| `E+0x11a` | u32 | formatter / custom-display callback (0 = none) |
| `E+0x176` | u32 | page-class handler |

The shipped **arp key-scale** feature (`build.py`'s `ARP_COUNT_AT = 0x400d4096`) is
just "parameter 11's value-count in the ARPEGGIATOR descriptor" — the struct decode
lands on the exact two addresses `NOTES.md` found via the F-knob handler, confirming
the layout. Widening a `E+0xd2` count is the general lever for "more options on an
existing selector" (arp scales, LFO waveforms (19), LFO destinations (30)).

Stock FX1 = FILTER, FX2 = DELAY; FX-default assignment via `lea` operands
`0x40005680` (FX1) / `0x4000568a` (FX2); NONE descriptor `E = 0x400d45e0`.

| Effect | id | `E` | Effect | id | `E` |
|---|---|---|---|---|---|
| FILTER | `0x04` | `0x400d4772` | PLATE REV | `0x14` | `0x400d5594` |
| SPATIALIZER | `0x05` | `0x400d4904` | SPRING REV | `0x15` | `0x400d5726` |
| DELAY | `0x08` | `0x400d4a96` | DARK REV | `0x16` | `0x400d58b8` |
| EQUALIZER | `0x0c` | `0x400d4c28` | COMPRESSOR | `0x18` | `0x400d5a4a` |
| DJ EQ | `0x0d` | `0x400d4dba` | **MULTIBCOMP** | **`0x19`** | **`0x400d5bdc`** |
| PHASER | `0x10` | `0x400d4f4c` | LOFI | `0x1c` | `0x400d5d6e` |
| FLANGER | `0x11` | `0x400d50de` | COMB FILTER | `0x13` | `0x400d5402` |
| CHORUS | `0x12` | `0x400d5270` | | | |

> **MULTIBCOMP (id `0x19`, `E = 0x400d5bdc`)** was missing from the octa-bt-pt
> reading — octabam's walk found it between COMPRESSOR and LO-FI. Effect ids are
> sparse (`04 05 08 0c 0d 10 11 12 13 14 15 16 18 19 1c`); the gaps are the place
> to look when asking whether an effect can be *added*.

**Non-FX entries** (octabam, ids all 0): 0–4 = the 5 machine types (PLAYBACK, one
page each — 0/1 = FLEX/STATIC, 2 = THRU `INAB/INCD`, 3 = NEIGHBOR (no params),
4 = PICKUP); 5 = LFO (audio); 6 = AMP; 7 = MIXER / main+cue routing (**bespoke
renderer — its per-param enable bitmap lies**); 8 = **track recorder**; 9 = NOTE;
10 = ARP; 11 = LFO (MIDI); 12/13 = CONTROL 1/2; 14 = NONE. Entry −1 at
`0x400d2e52` (blank name) = the **master-track** page, returned by `FUN_40031da4`
for track 7 when `DAT_80000034` is set.

Two page-class handlers cover the effects, **both gate on `0x800000a0`** (a word in
the PERSONALIZE block, see below) plus a check of `0x46c7dd26`:
`0x40032814` (FILTER/SPAT/DELAY/EQ/PHASER/FLANGER/CHORUS/COMB; indexes
`0x46c7d244 + idx*20`) and `0x400328e4` (DJEQ/PLATE/SPRING/DARK/COMP/MBC/LOFI +
audio-LFO + routing).

FX1-disallowed (hardware menu restriction, not addressing): DELAY + the 3 reverbs
(FX2-exclusive; cf. `dsp56300.md` FX1 3072 words / FX2 16384).

### Track-recorder parameter page (entry 8) — storage is three-tiered

> source: `refs/octabam/docs/PARAM_PAGES.md` §"Entry 8" @ `2f241e1`, crediting Bryan T's hardware decode (2 Sep 2026). confidence: **C** (hardware-confirmed display values).

`page1 INAB INCD RLEN TRIG SRC3 LOOP · page2 FIN FOUT AB QREC QPL CD`. The value
travels **UI → Part storage → publication → engine**:

| tier | address | note |
|---|---|---|
| bank blob | `[0x46c82456] + 0x8f382 + part*6322 + track*12` | the persisted "Part" copy; part index at `0x100b14cf` |
| SRAM mirror | `0x100a54d0 + …` | |
| per-frame published copy | `0x80000cf4 + track*12 + [0x800000e0]*96` | what the recorder's own code reads |

`[0x800000e0]` is the DSP frame selector (0/1) — cf. the persistence note's warning
that the ANDY-block restore must stop before `0x800000e0`. `RLEN` reaches the engine
as `(raw+1)` steps → samples at `0x4006e3b2`. ⚠️ Two page defaults are overridden by
an unlocated fixup: TRIG draws `ONE` (raw 1 = `ONE2`), SRC3 draws `MAIN` (raw 0 = `-`).

**Machine** descriptors, same 12-byte-slot + `0x96` block shape:
`FLEX = 0x400d2fe4`, `STATIC = 0x400d3176` (TSTR = slot byte index 10; `1`=AUTO
stock, `0`=OFF). PICKUP's TSTR has min 1 (0 stalls the sequencer — OOB table idx).

### Parameter value → the engine — the publish path (page 1 vs page 2)

> source: `refs/octabam/docs/midi_re_cc.md` §3/§6/§7 + `docs/COLDFIRE_PORT.md` O9c–O9d
> @ `04b8512` (2026-09-05..08). confidence: **C** — §7 and the O9d record layout are
> hardware-/port-measured across 12+ flashes; **L** for the exact halfword offsets
> where noted. Supersedes the older "page-2 r6 offsets less certain — verify" note
> in `NOTES.md` Session 17.

A parameter byte travels **UI/CC → Part store → a live lane → the per-frame DSP
copier → the effect's block**. Page 1 and page 2 take *different* lanes, and only
one of them has an explicit "publish" step:

| | **page 1** (knobs, CC 16–45) | **page 2** (RMS / selects / our sidechain KEY*) |
|---|---|---|
| generic writer | `FUN_40054cd8(track, flat, value)` — `flat = page*6 + slot`; callers `0x40062530` / `0x400625aa` (CC) / `0x400a15f0`. Knob path `FUN_40055008` is a near-copy. | `P2EDIT = 0x4003a474(slot2, delta)` — reached via the 7-record page table `0x400bb6f8`. **CC never reaches page 2** (handler admits only `cc−16 < 30`; slot `flat % 6`). |
| Part store | audio: `Part + 0x8edaa + track*30 + machine*7 + slot` (PB page) / `Part + 0x8ee9a + track*24 + (flat−6)` (AMP·LFO·FX1·FX2). MIDI: `Part + 0x8f162 + (t−8)*32 + flat`. | `DB + part*6322 + 0x8ef5a + track*30 + page*6 + slot2` — `part = 0x80000003`, `track = 0x80000000`, `page = long 0x460d5c30` (staged index; **0 for FX2 page 2** → store is `+0 + slot2`). |
| shadow | `0x100a4ef8` / `0x100a4fe8 + same off` | `0x100a50a8 + part*6322 + track*30 + page*6 + slot2` |
| "edited" flags | `0x40027e00/e30` (dirty) | `DB+0x95048 |= 1<<part`, `0x100b145e |= 1<<part`, `DB+0x9b332 = 1`, `0x100f8598 = 1` — **omit any of these and the Part store is inert** (measured, octabam tags 94–99). |
| clamp | `min = P+0x6a[slot]`, `max = min + P+0x9a[slot] − 1` (`0x40054dee`) | same, at descriptor index `slot2+6` |
| **live lane byte** | `0x80000810 + track*72 + flat` (+ `0xa0` slew marker at `0x80000db4 + track*72 + (flat/4)*4`) | **`0x80000830 + track*72 + slot2`** (= `0x80000810 + track*72 + 0x20 + slot2`) + redraw `0x46c7d244[slot2*20 + 4] = 0x14` |
| dial reads | the Part via the page cache | displayed value at `0x8f084 + track*30 + slot` (`slot = slot2+6`) — **separate from the store**; a write that skips it leaves the dial stale |
| **DSP publish** | writer calls resolver `0x4009da20` → posts a **kind-0x0f** record to the DSP param queue `0x460d17ee`, consumed `0x4009204c` | **none.** Page 2 reaches the DSP *only* through the per-frame copier `0x4000cae8` (twin `0x40003d14`), which ships `0x80000a50`'s halfwords **and the `+0x20` lane** to host-port staging every frame, unconditionally. |
| load-time fill | frame-builder refreshers `0x40170f8a` / `0x4017107a` (4 instances) from project storage | same refreshers; `0x4000c19c` on transport start re-applies the **saved bank's pattern part** over the lane (`0x4017107a + bank·635712 + part·6322 + track·24` → `0x80000816 + track·72`) |

MIDI-CC pipeline: `UART → parser → queue 0x46c7e974 → MIDI-in task 0x40005540 →
0x400d6474[status>>4] → CC handler 0x4000e79c → kernel queue 0x460d17ae (poster
0x400053d8) → UI task 0x40061cd2 → 0x40061cfa[kind−1] → kind 0x40 → 0x40062496 →
FUN_40054cd8`. Crossfader: CC 48 → kind `0x44` → `0x4006269a` (rebuilds gain table
`0x80003c60..88`); panel xfader → kind `0x04` → `0x40061e0a` (same body).

Also written by `FUN_40054cd8` (p-lock/override state, octabam 🟡): per-track lock
bit `0x80001538[t] &= ~(1<<flat)`, byte `0x80001658[t*32+flat]`. (Cf. our
`0x46c75fa0` bitmap / `0x46c7ab30` live values in "p-lock RAM structures".)

### Per-voice DSP record — what the copier assembles each frame

> source: `refs/octabam/docs/COLDFIRE_PORT.md` O9d @ `04b8512` (2026-09-08), decoded
> from the host-port block dump. confidence: **C** for the record split + id slots,
> **L** for the exact page offsets.

`0x80000110` / `0x80000310` → **core 1** (tracks 5–8), `0x80000210` / `0x80000410`
→ **core 0** (tracks 1–4). 128 halfwords each = **32 per track**, one DSP word per
halfword:

| halfword | field |
|---|---|
| `+0..5` | AMP page 1 |
| `+6..11` | FX1 page 1 (`value << 8`; page-2 select in the **low byte** of the same halfword — the "flag word") |
| `+12..17` | FX2 page 1 (same encoding) |
| `+27` | FX1 id · `+28` FX2 id |

Assembled by copier `0x4000cae8` from the pre-image `0x80000a50 + track*64`
(halfwords 12..29). DSP-side landing: per-voice block at `X:0x4000` (`0x034000`);
FILTER's coefficient block is `X:0x2c0` for the **FX2** instance, `X:0x3a0` for
**FX1** (id byte at DSP record `+27/+28`; `r6` param base `X:0x2c3 / 0x3a3`).
Stock RAM part page snapshot at `0x4017109e` (e.g. `0x7f40007f` = BASE 127 WDTH 64).

## PERSONALIZE settings — persistence (the 'ANDY' battery-SRAM block)

> source: `refs/octamax` `c78ff70` (2026-09-06), verified against our `section_3_MAIN_OS.bin` in Session 19. confidence: **C** (bytes + octamax HW-confirmed).

**`0x800000xx` is volatile** — `FUN_4000f938` re-images `0x80000000..0x80004000`
from ROM on every boot. A PERSONALIZE setting only survives a power cycle if it is
also written to the checksummed **'ANDY' block in battery SRAM at `0x100fff00`**:

| Addr | What |
|---|---|
| `0x100fff00` | block base; magic `'ANDY'` @ `+4`, version 36 @ `+0xe` |
| `FUN_4001f23c` | checksum over 252 B from `+4`; **key handler re-runs it after every setter** via `jmp 0x4001f23c` at `0x40069074` |
| `FUN_4001f340` | boot **validate**; on mismatch → defaults |
| `FUN_4001f298` | **defaults** path — zero-fills the whole block (so unconfigured = 0) |
| `0x4001f322` / `0x4001f3be` / `0x4001fb24` | the three **restore** sites: `memcpy(0x80000070, 0x100fff00, 0x64)` (boot / validate / defaults). `0x64` covers runtime `0x80000070..0x800000d3` only. |
| stock setter pattern | writes *both* copies, e.g. `0x40068898`: `0x80000090` **and** `0x100fff20`. shadow = `0x100fff00 + (runtime − 0x80000070)`. |

**Stock PERSONALIZE runtime words** — the full set, from disassembling the 16
getters/setters (Session 20; each getter reads its word + one neighbour):
`0x8000008c 90 94 98 9c a0 a4 ac b0 b4 b8 bc c0 c4 c8 cc d0`. `MUTE FOCUSES TRK`
`0x90`, `QUANTIZE LIVE REC` `0xac`, `LED BRIGHTNESS` `0xd0` (behind the MKII
`0x46c8d18c` gate), FX page-class gate `0xa0`. `0x70..0x8b` is restored too but is
something else (not a PERSONALIZE row). Restore ends `0x800000d3`; DSP frame
selector `0x800000e0` (35 refs — never widen the restore past `0xdf`).

### Free scratch words (for new menu/feature state)

Whole-image scan for each (Session 20): `0x800000a8`, `0x800000d8` — **0 ColdFire
refs**; `0x800000d4` — 0 (its two matches are inside the appended DSP payloads,
not code); `0x800000b4` — **5 real refs in the menu code, taken**.

| Addr | shadow | Status |
|---|---|---|
| `0x800000a8` | `0x100fff38` | free of any stock use, **but inside the stock `0x64` restore** → its value is overwritten from the shadow every boot. DIRECT JUMP (`wip`, Session 15) uses it as menu state and does **not** write the shadow, so its `ON` setting silently resets to `OFF` on a power cycle (same bug Session 19 fixed for `0xdc`). No aliasing / corruption — just non-persistence. Fix: move it to `0x800000d8` (below) and give it the Session-19 treatment. |
| `0x800000d4` | `0x100fff64` | free; outside the stock `0x64` restore |
| `0x800000d8` | `0x100fff68` | free; outside the stock `0x64` restore — **the slot to give DIRECT JUMP** (rides MUTE MODE's `0x70` extension) |
| `0x800000dc` | `0x100fff6c` | **taken** — MUTE MODE / SOFT-MUTE GATE. Session 19: build extends the restore to `0x70` + the setter writes the shadow, so it persists. |

A new toggle that must persist: (1) put its word in `0x800000d4..df`, (2) have
`build_*.py` extend all three restore `pea 0x64` → `pea 0x70`, (3) have the setter
`move.l %d0,<shadow>`. Checksum is automatic. Range `0x70` ends at `0x800000df`,
one short of `0x800000e0` — do **not** widen further. See `tools/patch_mutemode.s`.

> **Need real space, not just a scratch word?** ems-octakit reclaims a multi-MB
> slice of the flex sample pool and appends an unpacked runtime there
> (`0x45d0dde0`, ~128 KB ColdFire code + MB of RAM) — 4 constant patches in the
> audio-page allocator `0x40096f80–0x40097130` + ~10 boot splices. ColdFire only,
> costs sample time. `kb/octakit-abi.md` "The append-a-runtime architecture".

---

## MIDI track scenes — the midisc address map (1.40C)

source: `refs/midisc/tools/midisc/memory_map.py` + `docs/TECH.md` @ `eb8b4bc` ·
fetched 2026-09-16 · **C** (HW-confirmed by that project; a live ColdFire patch
shipping as `1.40MIDISC8`, same base OS as this project — `BASE = 0x40000400`).
midisc adds MIDI-track scene A/B locks + XF morph; octabam already vendors it
as a submodule (`modules/midi-scenes`).

**MIDI page/flat resolver** (`FUN_40031da4(track, page_kind)`, MIDI tracks
`track >= 8`): `PAGE_MODE = 0x460D1684` (u32); flat index = `PAGE_MODE*6 +
encoder`. `PAGE_MODE` 0=NOTE(flats 0-5) / 1=LFO(6-11) / 2=ARP(12-17) /
3=CTRL1(18-23) / 4=CTRL2(24-29). ARP order TRAN,LEG,MODE,SPD,RNGE,NLEN;
descriptor counts LEG=2 MODE=7 SPD=96 RNGE=8.

**Live scene bank ("MSC")**: `MSC = 0x400D6600`, `16 scenes × 8 MIDI tracks ×
32 flats` (index `scene*256 + track*32 + flat`), empty cell `0xFF`. Companion
state: `SCENE_HELD = 0x460D169C`, `MIDI_FLAG = 0x80000012`, `BANK_PTR =
0x46C82456`, `PART_DISP = 0x100B14CF`, `TRACK_DISP = 0x100B14CC`.

**Part-Save / reboot persistence** — a sparse blob *inside the part window*
(not a separate file), the pattern to copy for any new per-part persistent
state: offset `bank+part*0x18B2 + 0x90522` (`SPARSE_OFF`), shadow twin at
`+0x967EC`, 144 bytes, magic u16 `0x4D53` ('MS'), up to 46 `{u16 flat_or_id,
u8 value}` entries. Durable save is the *same three-step path stock Part Save
uses* — working→shadow→`PART_STAGING` (`0x100AB196`) + set `PART_SAVED`
(`bank+0x9B312`) — a sparse-only write does not survive reboot. A **freeze
twin** sits 144 B before the live sparse (`FREEZE_SPARSE_OFF = SPARSE_OFF -
144`) so Part Reload can restore pre-edit state after a reboot, seeded from
DRAM `CKPT` (`CLIP+0x200`, `CLIP = 0x460C9A00`) via a hook *after* stock
`jsr faf0` (`AFTER_PROJECT_LOAD = 0x400622C6`) — stock `faf0` fills
CF/bank/`PART_PROJECT` but never DRAM CKPT, so anything relying on CKPT must
seed it itself post-load. **Never body-hook `PROJECT_LOAD` (`0x4000faf0`) or
`PROJECT_SAVE` (`0x4000fbb4`)** directly — this project doesn't.

**XF-over-step-lock morph engine** (`xf_mix`, `SAFE_CAVE`): scenes are an
*offset layer* on top of step (p-lock) values, not a replacement — locked XF
side reads the MSC scene cell, the empty XF side reads `TRIG_SNAP[track][flat]`
(a DRAM snapshot of the raw trig/p-lock row taken by a trampoline right
*before* remix) if that step locked the flat, else falls back to
`MIDI_BEHIND` (`0x8F162`, the unlocked dial value). At full A/full B (weight
0 or `0x7F` exactly) it additionally pokes `LFO_BASE` (`0x46C78960`,
`track*32+flat`) so locked flats read as an absolute scene with no step-lock
audible at the pure end; mid-XF it deliberately does **not** re-poke every
step (reintroduces audible stepping on both-scene lerps). `xf_mix` writes
`MIDI_VOICE` (`0x46C76DC0`) only, never `MIDI_SOUND` (`0x100A52B0`) — writing
the UI-facing copy aliases unlocked cells into a sticky post-reboot state.

**CC freeze-on-full-B gotcha, generalizable**: stock `CC_TX`
(`0x4009EEC8`) reads the *dialed* `d2` register, not the mixed value, so a
CTRL CC locked to scene B looked frozen on the panel but kept transmitting
live values until a `build_voice_reload_d2` step explicitly reloads
`d2 <- MIDI_VOICE[track*0x44+flat]` after every `xf_mix`. Generalizes: any
mix/remix step that writes an internal "current value" table but leaves a
register a downstream *send* path still reads independently will silently
un-freeze under it.

**Bank-register clobber** (useful defensive pattern for any code near
`BANK_PTR`): stock `move.l d0,(0x46C82456)` at two bank switch/init sites
(`0x400622AA` guarded, `0x40087D44` unconditional) clobbers caller registers
on ColdFire — midisc wraps both with a `lea`/`movem` save-restore (not
`movem` to `-(sp)`, which the ColdFire form doesn't support the same way).
Site B (`0x40087D44`) must **never** pack/save state — mid bank-load is not
a safe point for a durable write.

→ full detail (hook site table, code-cave placement, compose-with-Octakit
notes) in [`techniques.md`](techniques.md) "midisc — MIDI scene locks".

---

## To import next (from `refs/`)

- **octabam `docs/`** — swept 2026-09-02 (menu/UI) + 2026-09-06 (kernel, sequencer
  masks, descriptor table, recorder page) + 2026-09-08 (`midi_re_cc.md` §7 page-2
  publish path, `COLDFIRE_PORT.md` O9d per-voice DSP record — both above; the
  ColdFire port itself → `techniques.md`). Still uncatalogued: the DSP-effects work
  (bus screen, reverb, xbus, one-aux bus — out of scope) and ~20 octabam-only
  `FUN_40xxxxxx` (screen-record / audio-editor / part-teardown). RTOS 10.17–10.18
  (recorder-seam module, Bryan's click) — recorder-specific, not ours.
- **p-lock byte→parameter map** — hypothesis now in [`file-format.md`](file-format.md)
  ("byte→parameter map"); needs the hardware `pattern-diff` pass to confirm, and
  the LIVE-REC erase handler still to be located (start from the mask consumers
  `0x4009d382..0x4009da12` above, or drive `emu_rtos` — see `techniques.md`).

_Done: octa-bt-pt descriptor table; octabam+octa-bt-pt DSP boot map (`dsp56300.md`);
OctaLib bank layout + our own p-lock-region RE (`file-format.md`); octabam menu
cluster (above); ems-octakit's `abi.inc` / `firmware.json` address map
(`octakit-abi.md`, open-sourced 2026-09)._

_ems-octakit's ~500 `GK_STOCK_*` symbols are curated in
[`octakit-abi.md`](octakit-abi.md) rather than merged inline here — cross-check it
first when RE'ing a Part / Kit / Bank / scene / LFO-designer / sequencer-tick area._
