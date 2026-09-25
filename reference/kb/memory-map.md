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
>
> **⚠️ Citation moved upstream (2026-09-22).** `docs/RTOS_FORK.md` and
> `docs/COLDFIRE_PORT.md` **no longer exist at octabam's tip** — that material was
> reorganised into `docs/firmware/KERNEL.md` (+ `PANEL.md`, `STORAGE.md`,
> `RECORDER.md`, `LFO.md`, `LEVEL_LAW.md`, `COLDFIRE_DELAY.md`, `REPITCH.md`), and
> the original logs are reachable only from git history:
> `git -C refs/octabam show 3ceba41:docs/history/RTOS_FORK.md`. The commit-pinned
> citations throughout this file remain accurate *at their pinned commit* — but to
> read the current version of any RTOS claim, go to `docs/firmware/KERNEL.md`.

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
scenario may never get scheduled into. **✅ RESOLVED 2026-09-24 — "no task, and the scheduler
cannot preempt it."** Three independent upstream sources place this whole span inside
the **DSP frame ISR**, and the decisive numbers were verified against our own image
this session:

- **The frame ISR extends `0x4000aad0 .. 0x4000d9b0`** and ends in an `rte` —
  verified locally: `0x4000d9ae: rte`. (source: `refs/octamad/docs/firmware/STOCK_PROFILE.md`
  @ `ccb11fb`, branch `origin/poly-machine`, 23 Sep 2026 — Jannik Aßfalg / repeat98.)
  **Every** MACSR site above — `0x4000cae8`, `0x4000ccae/cd22/cd64/ce40/ced0`,
  `0x4000cf60`, `0x4000d3ae` — falls inside it. There is no "calling task": this is
  interrupt context. octemu independently annotates `0x4000c202`, `0x4000cc60` and
  `0x4000d12c` as "inside frame_isr" (`refs/octemu/re/coldfire.syms` @ `6a9ff68`).
- **The frame ISR runs at interrupt level 5** — verified locally:
  `0x4001fc2e: moveq #5,%d0` → `0x4001fc30: moveb %d0,0xfc048041` (INTC0 ICR1 = 5).
  It also masks its own source at entry: `0x4000aada: moveb #1,0xfc04801c` (INTC0 SIMR).
- **The PIT0 time-slice runs at interrupt level 1** — verified locally:
  `0x400005e2: moveb #1,0xfc04c06b` (INTC1 ICR43 = 1), unmasked at
  `0x400005ea: moveb #43,0xfc04c01d` (CIMR).

On ColdFire/68k an exception sets the SR mask to the interrupting level, and only a
**higher** level can interrupt. Level 1 cannot preempt level 5 — **the scheduler
provably cannot land inside the MACSR=0x60 window**, so the hazard as originally
written (a PIT0 tick pausing the level chain while another *task* touches the EMAC)
**cannot happen.**

**What remains, now narrow and specific:** only sources at **level 6 or 7** can
interrupt the frame ISR. Per octabam's vector table those are UART0 RX / MIDI IN
(INTC0 source 26, `0x400106ec`) and the serial link (source 27, `0x400109bc`) — both
confirmed level 6 locally (`0xfc04805a`/`0xfc04805b` ← 6) — plus the level-7 halt
path (`0x4001fca0`), which never returns. **The open question is therefore only:
does the MIDI-IN or serial-link ISR touch the EMAC?** A small bounded read, not a
dynamic-tracing project. Until it is done, "adding cycles to the level chain" is
**not** a scheduler race; the original worry is retired.

⚠️ `FUN_4000c8a4`, which several older notes and `tools/patch_partreapply.s` name as
a function, **is not a function boundary** — it points *inside* this ISR, and at that
exact address inside an operand (same `STOCK_PROFILE.md` source). Do not treat it as
a callable entry. (source: `refs/octabam` `CLAUDE.md` "MACSR S/U IS BIT 6..." +
`docs/firmware/KERNEL.md` "Emulator facts", pulled 2026-09-16 at `f77d5d7`; octabam's own
ColdFire port had this exact S/U bit wrong for this exact function once, "every voice
rendered silent" — O9b, 8 Sep 2026 — independent confirmation this specific code is
unusually easy to mismodel.) See
`NOTES.md` "Session 58 continued yet again, part 4" for the mute-mode incident this
was pulled to explain.

## Interrupt levels — the full verified table (new 2026-09-24)

> source: our own disassembly this session (every `ICR` write in the image, located
> by scanning for `0xfc048041`/`0xfc04801d` and their siblings), cross-read against
> `refs/octabam/docs/firmware/KERNEL.md` @ `111fd76` and
> `refs/octemu/re/coldfire.syms` @ `6a9ff68`. confidence: **C** — each level is a
> literal `moveq #N` feeding a `moveb` into that source's ICR.

Neither octabam's nor octemu's tables carry the interrupt **levels**; they matter
because on ColdFire only a *higher* level preempts, which is what settles every
"can X interrupt Y?" question (see the MACSR resolution above).

| ICR write site | register | source | **level** | handler / what |
|---|---|---|---:|---|
| `0x4001fc30` | `0xfc048041` | INTC0 1 | **5** | DSP frame ISR `0x4000aad0` (masks itself at entry via SIMR `0xfc04801c`) |
| `0x4001f824` | `0xfc048047` | INTC0 7 | **7** | halt / panic path `0x4001fca0` (`bras .`, never returns) |
| `0x400160ce` | `0xfc048056` | INTC0 22 | **3** | ATA |
| `0x400110b6` | `0xfc04805a` | INTC0 26 | **6** | UART0 RX — **MIDI IN** `0x400106ec` |
| `0x40010fb2` | `0xfc04805b` | INTC0 27 | **6** | serial link `0x400109bc` |
| `0x40010d76` | `0xfc04805c` | INTC0 28 | **4** | serial block `0x40010b88` |
| `0x4004048a` | `0xfc048061` | INTC0 33 | **3** | ❓ `0x40055cb8` |
| `0x40040454` | `0xfc048062` | INTC0 34 | **1** | ❓ `0x400409f4` |
| `0x40092f18` | `0xfc048064` | INTC0 36 | **4** | MIDI framer `0x40092bf4` |
| `0x40092694` | `0xfc048065` | INTC0 37 | **4** | ❓ `0x4009228c` |
| `0x400005e2` | `0xfc04c06b` | INTC1 43 | **1** | **PIT0 — the 5.0 ms time-slice** `0x40000550` |

**The two facts that follow immediately:**

1. **The scheduler is the lowest-priority interrupt in the machine** (level 1). It
   cannot preempt *any* audio, MIDI, serial or storage ISR. Every "is my hook
   racing the scheduler?" worry inside an ISR is answered *no* by this table alone.
2. **MIDI IN and the serial link (level 6) are the only things that can interrupt
   the frame ISR.** They are the entire remaining preemption surface for
   frame-ISR-resident code.

⚠️ Unmasking convention: the firmware **never writes IMRH/IMRL**. It unmasks through
`CIMR` (INTC base `+0x1d`, value = source number; `0x40` = all) and sets `ICRn` at
`+0x40+n`. A `CIMR` write must also clear `IMRL`'s MASKALL bit. (source: octabam
`KERNEL.md`, marked 🟡 there.)

## Kernel primitives — the callable RTOS API (new 2026-09-24)

> source: `refs/octabam/docs/firmware/KERNEL.md` @ `111fd76` (read byte-exact from the
> image), cross-checked against `refs/octemu/re/coldfire.syms` @ `6a9ff68`. confidence:
> **C** for the addresses; see the noted disagreements.

Useful to us for a specific reason: several of our features want to *hand work to a
task* rather than do it inside a hook. `k_queue_post` is how stock does that, and it
has 149 call sites — a well-worn path.

| Addr | primitive | notes |
|---|---|---|
| `0x400005fc` | `task_create(tcb, entry, prio, stack, size)` | a new task's saved context is an exception frame on its own stack: `[0x407c][SR 0x2000][entry PC]` with the exit thunk under it (`0x4000061c`–`0x40000626`) |
| `0x4000063c` | `make_ready(tcb)` | raises the top pointer; does **not** force a switch |
| `0x4000068c` | `unlink(tcb)` | |
| `0x40000818` | `event_wait(event)` | |
| `0x40000888` | `event_signal` | ⚠️ octemu names `sem_post = 0x400008b0` instead — 40 bytes apart; likely two entries of the same facility. Unresolved. |
| `0x400008ea` | `signal / reschedule` | sets INTFRCH bit 11 of INTC1 (`0xfc04c010`) → source 43 → the scheduler. Lands once the primitive restores the caller's SR. |
| `0x400007a4` | `counting_wait` | traps at `0x40000810` |
| `0x40000bd4` | `queue_init` | |
| `0x40000c3c` | **`queue_post(queue, msg)`** | ring at `queue+0x14`, mask `+0x10`, head/wridx `+0x18`, count `+0x04`; wakes the waiter at `+0x0c`. IPL7-masked. **136 `jsr` + 13 `jmp` = 149 sites** (octemu's count). |
| `0x40000d1a` | `queue_receive` | ⚠️ octemu says the entry is `0x40000d00` and describes it as spinning on count `+0x04` around the wait primitive `0x40000818`. `0x40000d00` is the likelier function head; `0x40000d1a` is plausibly the post-prologue label. |
| `0x400006e4` | `task_exit` | octemu: clears its own TCB runnable flag `+76` and blocks forever |
| `0x400009e4` | `mutex_init` | |
| `0x400009f4` | **`mutex_lock`** | owner TCB `+0`, waiter list `+4`/`+8`, chained through `TCB+0x50`; contended take traps at `0x40000a78`. octemu: masks to IPL7, **45 `jsr` sites**. |
| `0x40000a94` | `mutex_trylock` | |
| `0x40000ab4` | `mutex_unlock` | hands to the first waiter; traps if that waiter outranks the top pointer |
| `0x40010db0` / `0x40010d90` | serial-link driver's wrappers over the mutex | |
| `0x40000d50(vec, fn)` | `vector_install` | writes `[VBR + 4·vec]`; **VBR = `0x40000000`** |

**TCB, extended:** our table above stops at `+0x4c` (ready flag). Add **`+0x50` =
the lock waiter chain** (octabam; octemu corroborates as "TCB +76/+80" = `+0x4c`/`+0x50`).

**Task table, extended with TCB and stack addresses** (octabam measured these with a
hook on `task_create`; we previously had only the entry points):

| prio | TCB | entry | stack (+size) | what |
|---:|---|---|---|---|
| 6 | `0x46c7fb0c` | `0x40005540` | `0x46c7ea20` +0x1000 | MIDI / voice mailbox |
| 5 | `0x460bcc2c` | `0x4001ee30` | `0x460bc42c` +0x800 | storage (FAT/ATA) |
| 4 | `0x460d4f80` | `0x4005593c` | `0x460d4780` +0x800 | key-repeat timer |
| 3 | `0x460d59d4` | `0x40056c40` | `0x460d51d4` +0x800 | **UI** — `queue_receive(UI_QUEUE)` |
| 2 | `0x460fab80` | `0x40091d18` | `0x460fabd4` +0x2000 | ❓ |
| 2 | `0x460ffd44` | `0x400921c4` | `0x460fdd44` +0x2000 | ❓ |
| 2 | `0x460e0e38` | `0x4009203c` | `0x460dee38` +0x2000 | ❓ (ping-pongs with sys) |
| 1 | `0x460ddde4` | `0x4008445c` | `0x460d9de4` +0x4000 | **engine** — 46-opcode dispatcher, queue **`0x460d17ce`**; **RELOAD BANK = types `0x14` and `6`** |
| 1 | `0x46105508` | `0x40098a5c` | `0x4610555c` +0x2000 | ❓ |
| 1 | `0x46c7bed8` | `0x40061a94` | `0x460d6de4` +0x2000 | sys: serial + SPI start-up, then creates storage, UI, p3 |
| 0 | `0x46c7ae84` | `0x4001f834` | top `0x46c7becc` | main: init list, then `bras .` at `0x4001fc9c` = **idle** |

**⚠️ `RELOAD BANK` is engine-task opcodes `0x14` and `6` on queue `0x460d17ce`** — the
mechanism our RELOAD2/RELOAD3 features sit on top of. Worth reading before the next
revision of `tools/patch_reload3.s`.

**Handoff detail:** at the `trap #0` at PC `0x40000e46` only `main` is ready; the
current TCB `0x46c7ae30` is the pre-multitasking context, saved once and never
resumed. First switch is the first tick (sample 8,812 under octabam's route A).

**Time-slice numbers:** PIT0 `0xfc080000`, prescaler 2¹¹ (PCSR `0x0b36` at init,
`0x0b3f` on every switch), PMR `264,000,000 / 409,600 − 1 = 643` → **5.0 ms per tick
= 220.5 samples = 13.8 audio frames**. PIT1 `0xfc084000` (PCSR `0x0b3a`, PMR 2014) is
the storage layer's delay timer (`0x40020c7c`).
⚠️ octemu's `coldfire.syms` calls the PIT0 tick "10 ms". octabam's arithmetic above is
shown in full and checks out; **prefer 5.0 ms**, and note octemu may be describing a
different PCSR state.

## The part-apply family — `0x40009094` vs `0x40009848` vs `0x40009e00` (new 2026-09-24)

> source: **our own disassembly this session** (`m68k-elf-objdump -m m68k:cfv4e`,
> extents walked to the first `rts`, absolute-write and `jsr` sets diffed
> mechanically), prompted by `refs/octemu/re/coldfire.syms` @ `6a9ff68` and
> **independently corroborated on hardware** by
> `refs/octalab/docs/FINDINGS.md` @ `e0dc56d` ("A part lives three times", MKI,
> 12 Sep 2026). confidence: **C**.

**This is the Session 49 answer.** The S49 hypothesis was "the pattern-change path
never runs `FUN_40009094`". That is now **confirmed literally true** — and the reason
is that stock has **three** part-apply routines, and the pattern-change path takes the
lightest one.

All three share a prologue: write the publish bytes `0x80001828` / `0x80001829`, clear
the 0x100-byte block `0x46c7d6d4..0x46c7d7d4` in a 16-byte-stride loop, then index
`param_snapshot_base` (`0x40170f60`) at **`part*0x18b2 (6322) + bank*0x9b340 (635712)`**.

| | `0x40009094` — `STOCK_APPLY` | `0x40009848` | `0x40009e00` |
|---|---|---|---|
| size | **1,970 B**, 596 insns | 2,378 B, 756 insns | **914 B**, 271 insns |
| publish bytes `0x80001828/29` | ✅ | ✅ | ✅ |
| `0x400d64ba` / `0x400d64bc` | ✅ | ✅ | ✅ |
| scene table `0x800010e4..e7` | — | ✅ | ✅ |
| **tempo republish** `0x80001814`, `0x80001818`, `0x8000181c`, `0x80001824` | ✅ | — | — |
| **eDMA TCD re-arm** — `0xfc04501e` (TCD0.CSR), `0xfc04503e` (TCD1.CSR), plus TCD6/7 at `0xfc0450c0..fe` | ✅ | — | — |
| **INTC0 re-unmask** — CIMR `0xfc04801d`, ICR `0xfc048048/49/4f` | ✅ | — | — |
| `jsr` targets | `queue_post 0x40000c3c`, `memcpy 0x40020898`, `0x40020950`, `0x4009ec70` | `memcpy 0x40020898` | **none** |

`0xfc045000` is the **eDMA TCD array** (32 B/channel); TCD0/TCD1 CSRs are, in octemu's
words, "the measured audio-chain arms". So:

> **`FUN_40009094` is the only variant that restarts the audio engine.** It
> republishes tempo, re-arms the audio eDMA chain, re-unmasks the interrupt sources
> and posts a message to a kernel queue. The other two only move parameter bytes.

**Who calls which:**

- **`seq_goto_pattern` (`0x400a0570`) → `0x40009e00`.** Verified: at `0x400a05e2`
  `lea 0x400eb036,%a0`; at `0x400a05e8` `mvsb %a0@(1,%d0:l),%d0` reads slab
  **`+0x8e57`** — the pattern→Part link already in our trailer table — then
  `0x400a05f0: jsr 0x40009e00` with `(bank, part)`. **The pattern-change path applies
  a Part using the variant that never restarts the engine.**
- **`0x40029a4c(src, part)` → `0x40009094(bank, part)`.** octalab, on a MKI: the stock
  part setter "writes both [bank and SRAM copy], sets the part-edited bits
  (`bank + 0x95048`, `0x100b145e`) and the dirty flags, and **re-applies the current
  part to the engine with `0x40009094(bank, part)`** — which also copies scenes A/B
  (indexes at `part + 0x10/0x11`) into the live copy `0x80000ed4`: a scene written
  this way plays at once."

**⚠️ Argument order: `(bank, part)`.** Verified three ways — our disassembly of all
three prologues (arg1 × `0x9b340` = the bank stride, arg2 × `0x18b2` = the part
stride), the `seq_goto_pattern` call site pushing `%d0` (part) then `%d4` (bank), and
octalab's hardware-derived `0x40009094(bank, part)`. **octemu's `coldfire.syms`
labels `par_apply_part = 0x40009848` as `apply_part(part, pattern)` — that signature
is wrong** (and inconsistent with octemu's own `param_snapshot_base` stride note in
the same file). Do not copy it.

**What this means for the S49 bug family** (PICKUP→FLEX plays the old pickup loop;
recorder SRC/RLEN carries over; REC SETUP last-tweak leaks): the carry-over is
explained by the *delta* in the table above, not by a missing call. A fix does **not**
have to call the heavy `0x40009094` from the pattern-change path (which would
re-arm eDMA and post a queue message mid-pattern-change — plausibly worse than the
bug). It has to add **only the part of the delta the symptom needs**. The delta is now
enumerated, which is what the S49 handoff was missing. `tools/diff_flex_static.py`
remains the right instrument; this table tells it what to look for.

## A Part lives three times — and a bank-only write is lost at reboot (new 2026-09-24)

> source: `refs/octalab/docs/FINDINGS.md` @ `e0dc56d` · fetched 2026-09-24.
> confidence: **C** — measured on an **Octatrack MKI**, 12 Sep 2026.

A Part (`0x18b2` = 6,322 bytes) exists in **three** places:

| copy | address | notes |
|---|---|---|
| bank's **working** part | `bank + 0x8ed80 + part*0x18b2` | |
| bank's **saved** part | `bank + 0x9504a + part*0x18b2` | |
| **SRAM copy** | `0x100a4ece + part*0x18b2` | **the one the unit comes back with after a power cycle**, synced to the card or not. (Patterns have theirs at `0x1001614e`.) |

octemu corroborates the last two independently as `pd_live_working_part_base = 0x100a4ece`
and `pd_live_saved_part_base = 0x100ab196` (both "64 B == nvram.bin[…]").

**⚠️ The trap, measured on hardware:** the stock parameter writer `0x40054cd8` writes
**the bank *and* the SRAM copy**. **A direct write to the bank alone is lost at the
next boot** — octalab measured exactly this: randomised scenes gone, the scene
selector kept. Any patch of ours that writes part data must write both, or go through
`0x40029a4c(src, part)`, which does both plus the dirty bits plus the engine re-apply.

Related NVRAM part model (octemu `coldfire.syms` @ `6a9ff68`, confidence **C**):

| Addr | What |
|---|---|
| `0x100b145e` | live part-**dirty** bitmask, one byte |
| `0x100b145f` | live per-part **saved** flags, 4 B |
| `0x100b1463` | the four live part **names**, 7 B each (`ONE TWO THREE FOUR`) |
| `0x100b14cf` | **current part** index 0..3 (mirror `0x80000003`) |
| `0x100b14d0` | **current pattern** index 0..15 (mirror `0x80000004`) |
| `0x4004a908` | `save_part(n)` — working→saved in blob *and* live image, sets the saved flag |
| `0x4004aab4` | `reload_part(n)` — **no-op unless the saved-exists flag is set** |
| `0x40020898` | `memcpy(dst, src, n)` — the primitive every blob/live/part copy goes through |

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

### Pattern SCALE / LENGTH trailer — and the `SCALE_MODE` fork

> source: our own RE, derived **independently by two threads** (DIRECT JUMP Session 79
> cont.33; RELOAD Session 89) and corroborated a third way by stock's own load-time
> clamp `FUN_4009a670`. confidence: **C**.

Pattern slab = `0x400e21e0 + bank*0x9b340 + pattern*0x8ed8`. Its trailer carries the
scale/length fields, **outside every track record**:

| slab off | abs (bank 0, pat 0) | field | clamp in `FUN_4009a670` |
|---|---|---|---|
| `+0x8e51` | `0x400eb031` | MASTER LENGTH, steps | — |
| `+0x8e52` | `0x400eb032` | MASTER SCALE index | ≤ 6 |
| `+0x8e53` | `0x400eb033` | pattern LENGTH, steps | 2 … 64 (`0x4009aada`) |
| `+0x8e54` | `0x400eb034` | pattern SCALE index | 0 … 6 (`0x4009ab06`) |
| `+0x8e55` | `0x400eb035` | **`SCALE_MODE`** — see the two modes below | ≥ 0 |
| `+0x8e57` | `0x400eb037` | pattern → Part link, `[0..3]` | — |

**The two modes.** Always name them by the flag value, never by an invented adjective:

| `SCALE_MODE` (`+0x8e55`) | name to use |
|---|---|
| `== 0` | **NORMAL** |
| `!= 0` | **PER TRACK** (or per-track) |

A track's **own** length / scale live *inside* its record at `+0x50` / `+0x51`
(audio: `0x400e2230` / `0x400e2231` + patOff + `t*0x91a`; MIDI: `0x400e6ad8` /
`0x400e6ad9` + patOff + `m*0x8b0`).

**⚠️ The fork that has now bitten two separate features.** Which byte governs depends
on `SCALE_MODE`, and reading one unconditionally is wrong half the time:

| | **NORMAL** (`SCALE_MODE == 0`) | **PER TRACK** (`SCALE_MODE != 0`) |
|---|---|---|
| a track's length | pattern `+0x8e53` (shared by all 8) | the track's own `+0x50` |
| a track's scale | pattern `+0x8e54` (shared) | the track's own `+0x51` |
| master length | pattern `+0x8e53` | MASTER `+0x8e51` |
| master scale | pattern `+0x8e54` | MASTER `+0x8e52` |

Stock's own selector is visible twice: the step engine's re-home at `0x400a2720`
(`tstb` the flag, then `+0x8e52` vs `+0x8e54` into `SCALE_IX 0x8000663d`), and the
switch-commit D7 setup at `0x400a4802`–`0x400a4826`.

Both failures were the same shape:
- **DIRECT JUMP** read `+0x8e54` unconditionally, so after a jump between patterns of
  differing MASTER SCALE the master wrap check used the wrong ticks/step — the
  "pattern plays past its own length" symptom. Fixed by gating on `SCALE_MODE`
  (`patch_directjump.s`, five sites); fixture DJTEST2 A08 was built to separate
  `+0x8e52` from `+0x8e54`.
- **RELOAD** copied only the track slice, so a per-track reload restored `+0x50`/`+0x51`
  and therefore worked in PER TRACK mode, but never restored `+0x8e53`/`+0x8e54` and so
  silently ignored the saved step count in NORMAL mode.

> **Terminology.** The two modes are **NORMAL** (`SCALE_MODE == 0`) and **PER TRACK**
> (`SCALE_MODE != 0`) — the device's own names, and the only ones to use in new work.
> `patch_directjump.s` currently writes `unif` / `djd7_unif` / "uniform mode" in its
> comments and labels for the `== 0` case; that word is an invention, not OT
> terminology, and should be read as **NORMAL**. It is kept in this note only so that
> grepping the existing source finds this entry — search `PAT_SMODE` or `0x8e55`, which
> appear in both threads.

### The scale tables — ticks/step and quantise lengths (new 2026-09-24)

> source: `refs/octemu/re/coldfire.syms` @ `6a9ff68` · fetched 2026-09-24.
> confidence: **C** for the table contents and addresses (octemu ships an emulator
> that runs on them); **L** for our reading of what they imply for DIRECT JUMP.

**These two tables are the missing numbers for the open DIRECT JUMP non-1x thread**
(`reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md`). We had the `SCALE_MODE` fork and
the trailer bytes; we did not have the tick arithmetic they index into.

| Addr | size | What |
|---|---:|---|
| `0x400aba50` | 0x20 | **`seq_scale_table` — MIDI-clock ticks per step, by scale byte 0..6: `{3, 4, 6, 8, 12, 24, 48, 96}`.** Index **2 = 1x = 6 ticks**. |
| `0x400d80dc` | 0x44 | **`seq_quant_length_table` — chain/change quantise lengths in steps, 17 longs: `{-1, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256}`.** Indexed by the pattern chain-quant byte (slab `+0x8e56`) or the project default at `0x8000004e`. |

Consumers octemu names, and why each matters to us:

| Addr | What |
|---|---|
| `0x400a3cee`, `0x400a3e14`, `0x400a3ff8` | the **wrap comparands** — the three sites that compare against a scale-derived length |
| `0x400a42d0` | **step phase**: the ticks/step value `× 2,646,000` |
| `0x800065b2` | **`seq_master_step_addr`** — the pattern-level step counter, **u16**; observed advancing `0x000a → 0x000d` during PLAY |
| `0x400a44a0` | **`seq_pattern_commit`** — "where a pending pattern becomes current": copies `0x800065be → 0x800065c1` and `0x800065bd → 0x800065c2`. **The pattern-change quantisation point.** |
| `0x4009a846` | `seq_pattern_validator` — clamps per-step fields, returns a repair count |
| `0x4009aa4a` | `seq_trailer_validator` — returns a repair count |
| `0x4009abdc` | `seq_trailer_init` — **the source of the trailer defaults** |
| `0x4009c550` | `seq_tempo_publish()` — copies project or per-pattern tempo into `0x80001814`/`0x80001818` under IPL 7 (the same pair `FUN_40009094` writes, above) |
| `0x4009c708` | `set_tempo(raw)` — clamps to **720..7200** |
| `0x4009c7c4` | `set_tempo(bpm, tenths)` — `remsl #10`, the UI entry to the 720..7200 raw scale |
| `0x80000024` | `0` = one project tempo, nonzero = **per-pattern** tempo |
| `0x8000004e` | project default chain-quant index into `0x400d80dc` |

**Why this bears on our S88 regression.** Our note records that Hook P "wrote the
position in the MASTER-step domain", and the S88 fix was reverted because it broke the
1x baseline. `0x800065b2` is confirmed as *the* master-step counter and
`0x400aba50[scale]` is the exact ticks/step multiplier, with `× 2,646,000` at
`0x400a42d0` converting to step phase. Any domain conversion should be written against
these three facts rather than re-derived — and the three wrap comparands
(`0x400a3cee`/`0x400a3e14`/`0x400a3ff8`) are the sites to audit for which domain each
one is actually comparing in. **Not yet applied to the patch** — this is the input to
the next attempt, not a fix.

⚠️ **Master length is a u16, and `-1` means INF.** octalab reads the scale page
(`0x40047d08`) as: `pattern + 0x8e55` scale mode (0 normal, 1 per track), `+0x8e53`
length, `+0x8e54` scale in normal mode, per-track `TRAC + 0x50`/`+0x51`, and
**`pattern + 0x8e50` the master length — a short, with `−1` = INF**. Our trailer table
above lists MASTER LENGTH as a *byte* at `+0x8e51`. Big-endian, the low byte of a u16 at
`+0x8e50` **is** `+0x8e51`, so both readings are consistent — but the field is 16-bit
and has an **INF sentinel** our byte-wise reading would misread as 255. Treat
`+0x8e50` as `u16` from now on. (source: `refs/octalab/docs/FINDINGS.md` @ `e0dc56d`,
marked 🟡 "code read" there; our own two threads derived the byte view independently.)

Also new, same source (confidence **C**, octemu):

| Addr | What |
|---|---|
| `0x46107918` | **16 × u32 pattern-repetition counters** (audio 0-7, MIDI 8-15) — the **A:B trig-condition cycle counts**. Increment once per pattern cycle under PLAY, cleared on STOP. |
| `0x400a536c` | `advance_pattern_cycle(track)` — increments the above and latches pending FILL; called from the seq ISR at `0x400a3d98`/`0x400a3eb4` on a track step wrap |
| `0x46107969` | 16 × u8 per-track **pending FILL**, promoted to latched at the next pattern boundary (bound pinned by `cmpal #0x46107979` at `0x400a5490`) |
| `0x4009a670` | `seq_track_hdr_validator` — per-track header sanitiser: clamps LENGTH `+80` to **2..64** (`0x4009a698`–`0x4009a6b2`), then SCALE `+81` to **0..6** (`0x4009a6b4`–`0x4009a6ce`); strides `lea %a1@(2330)` for 8 tracks. Independent confirmation of our `0x91a` track stride and the clamp ranges. |
| `0x46c77bf6` | **`bank_reload_gate`** — PLAY is refused with a WAIT modal while this is zero. ⚠️ **WIDER than a byte**: reads as u32 `0x100` with the low bytes 0 on a booted, play-ready unit, **so test the full word, not byte 0.** |
| `0x4009b5c0` | `bank_reload_gate_read` — `movel bank_reload_gate,%d0; rts`, the 32-bit gate accessor; `play_button` (`0x40061778`) calls it first, and a zero gate posts the literal `WAIT` string at `0x400b68c2` |

⚠️ Note the adjacency: our KB labels **`0x4009b5c8`** as `FW_START_TRACK`. octemu puts
an 8-byte accessor at `0x4009b5c0` — i.e. `0x4009b5c0 + 8 = 0x4009b5c8`. These are
consistent (two adjacent functions), **not** a contradiction; but a hook placed by
counting backwards from `FW_START_TRACK` would land inside the gate accessor.

### Step records, trig words and the lock stores (new 2026-09-24)

> source: `refs/octabam/docs/firmware/PARAM_PAGES.md` §5g @ `111fd76` (crediting octalab,
> MKI, 13 Sep 2026) · fetched 2026-09-24. confidence: **C** except as marked.

The **parameter semantics** of the 64 × 32-byte step records (layout in
[`file-format.md`](file-format.md)): byte *k* is the p-lock of **scene parameter *k***:

| bytes | parameters |
|---|---|
| 0..5 | PLAYBACK |
| 6..11 | LFO |
| 12..17 | AMP |
| 18..23 | FX1 |
| 24..29 | FX2 |
| 31 | **sample lock** |

`0xff` = not locked. Full address `bank + p*0x8ed8 + t*0x91a + 0x78 + (s−1)*0x20`.

| Addr | What |
|---|---|
| `TRAC + 0x89a + (s−1)*2` | **the trig word** — bits **15-13** trig count − 1, **12-7** micro-timing ±23, **6-0** condition. Labels at `0x400b2588`. ⚠️ **In the bank FILE it is one byte earlier (`+0x899`)** — a RAM/file offset skew to respect in any tool that reads both. |
| `0x40040ee0(slot)` | **sample-lock store** — steps from `0x460d174a`, page base `0x460d174c`; writes the bank byte **plus the `0x1001614e` copy**, dirty flags, and bitmaps via `0x400339d8` → `0x46c7d48c[step]`. Works when called from outside the picker (octalab, HW). |
| `0x4004f5f8(track, param, value)` | **p-lock store** — **returns early unless a trig key is down** (`FUN_4003171c`). Dirty flags `bank+0x9b332` / `0x100f8598` / `0x40027e00`; refresh `0x4009da20`. |
| `0x400526e4` | descriptor defaults: page-1 at `desc + 0x5e`, page-2 at `desc + 0x64` |

⚠️ **Contested label:** the `+0x10` step mask. octabam reads it ✅ as the *trigless-lock*
mask ("exactly the locked steps without a trig", four patterns byte-diffed); **nordseele
lowered their own label for it to 🟡 on 22 Sep 2026.** This matters to us because stock's
pattern-content predicate `FUN_4009a464` **skips exactly `+0x10..0x17`** (verified here by
disassembly: it ORs `+0x00..0x0f` then `+0x18..0x37`) — which is the sharpened root cause of
our Bug-2 pattern-LED fix. Our fix scans the lock **arrays** rather than that mask, so it is
correct whichever way the dispute lands. See `reference/MERGE.md` "Audit of the finished set".

**Part payload offsets** (from `part = bank + 0x8ed80 + part*0x18b2`) — corroborates and
extends the `param_snapshot_base` sub-blocks below:

| offset | field |
|---|---|
| `+0x22 + track` | machine type |
| `+0x2a + track*30 + machine*6` | PLAYBACK page 1 |
| `+0x11a + track*24 + page*6` | LFO / AMP / FX1 / FX2 page 1 |
| `+0x2f2 + track*30` | LFO PMTR ×3, then WAVE ×3 |
| `+0x662 + (scene*8 + track)*0x20` | scene locks |

LFO destinations 0..29 use the scene-byte numbering above.
🟡 `fx1_disallowed_effects` = **DELAY, PLATE, SPRING, DARK** ("confirmed on real hardware",
Bryan T via octabam) — relevant to SIDE-CHAIN, which donates SPRING REVERB's DSP space.

### The track recorders — three storage tiers and the tempo chain (new 2026-09-24)

> source: `refs/octabam/docs/firmware/RECORDER.md` @ `111fd76` (Bryan T's five sessions,
> re-read against octabam's image) · fetched 2026-09-24. confidence: **C** for the control
> path, 🟡 for the tiers as marked there.

**This is the mechanism behind the Session 49 report "recorder SRC/RLEN carries over".**
🟡 Three tiers hold the same recorder settings:

| tier | address |
|---|---|
| bank | `+0x8f382 + part*6322 + track*12`, via `[0x46c82456]` |
| SRAM | `0x100a54d0 + …` |
| **published** | `0x80000cf4 + track*12 + page*96` — **refreshed per frame from `0x80000c94`** |

So a stale recorder setting after a Part change is a *publish* problem, not a storage one —
consistent with our own causal proof (`tools/check_reccache_causation.py`).

| Addr | What |
|---|---|
| `0x400d3c74` | recorder page descriptor (entry 8): `INAB INCD RLEN TRIG SRC3 LOOP / FIN FOUT AB QREC QPL CD`; defaults at `+0x96`, min `+0xa2`, count `+0xd2`, formatter `+0x11a` → `0x4003b18c` |
| `0x400d80e0` | **QREC/QPL ladder**, 16 entries `{1,2,3,4,6,8,12,16,24,32,48,64,96,128,192,256}`, with an `0xFFFFFFFF` sentinel immediately before — i.e. **the same table octemu names `seq_quant_length_table` at `0x400d80dc` ("17 longs, first = −1")**. Two independent readings of one table from opposite ends; it serves **both** QREC/QPL and chain/change quantise. |
| `0x400d8120` | one-hot class table, 17 entries |
| `0x4000ca94..cabc` | **the tempo chain**, publisher call `0x4000cac2`: `1814→181c`, `1818→1824`, `d1 = 0x80000000 ÷ [181c] → 1820` |
| `0x80001814` | **BPM × 24** (clamped 720..7200) — corroborates octemu's `set_tempo(raw)` clamp |
| `0x80001820` | **`−2³¹ / tempo24`** (negative; `4c42 1801` is `DIVS.L`, which objdump prints as `remsl`) |
| `0x400ab63a` | FIN/FOUT step ladder, `992250 × L`, 113 entries |
| `0x4006e3b2` | RLEN conversion — `(raw+1) × 63504000`, `remul` by `[0x80001814] << 2`, floor 64 |
| `0x40005ff0` | recorder **arm caller** — gate `[0x100b14cf]*6322 + [0x46c82456] + track + 0x8eda2 == 4`; nets to `round(table[FOUT] / tempo24)`. ❓ why the PICKUP arm reads the FOUT slot is open upstream. |
| `0x40005178` | **QREC scheduler** — staged `0x800018be/de`, immediate `0x46c7e9fa`, comparator `0x4000b308`, class mask `[0x46c7fe94]` |
| `0x100b14f0 + id*1096` | the 136-entry object arena; **recorder buffers are ids 128–135**, control records `0x46c922c4 + id*44`, **armed by opcode `0x25`** on the engine queue |

**Why `FUN_40009094` writes four tempo words** (see "The part-apply family" above): those are
exactly this chain's inputs and outputs — `0x80001814`/`0x80001818` in, `0x8000181c`/`0x80001824`
out. The heavy part-apply re-runs the tempo derivation; the light variants do not.

Recorder lengths are 44.1 kHz samples; RLEN raw+1 is sequencer steps (`661500 / BPM` samples
per 16th); the 64 floor is four frames. ❌ Upstream retraction worth noting because it matches
our own KB: `0x80000003` / `0x100b14cf` are the current **PART**, not pattern; `[0x80000004]`
is the pattern.

### Scene locks and the crossfader morph — the address set (new 2026-09-24)

> source: `refs/octemu/re/coldfire.syms` @ `6a9ff68` · fetched 2026-09-24.
> confidence: **C** (octemu's emulator runs on these), **L** for our S49 relevance note.

Relevant to the S49 "scene-morph / scene-data gaps" the handoff marks as SOLID — these
give the store geometry explicitly.

| Addr | What |
|---|---|
| `0x40031f44` | **`scene_param_get(scene)`** — resolves the scene p-lock block as `bank_base(0x46c82456) + cur_part(0x100b14cf)*6322 + (scene*8 + track)*32 + 0x8f3e2`. **`0xff` = "not locked in this scene"**. Two aux arrays follow at `+0x903e2` and `+0x903eb`. |
| `0x40034a44` | `scene_ab_state_builder` — per-track loop; on a hit seeds scene A/B selection `(0,1)` with a lock-present flag, else `(15,15)` cleared |
| `0x400339d8` | `scene_lock_collect` — builds two per-track 64-byte **presence masks** (`0x46c7d48c`, `0x46c7d2e4`) by scanning the active pattern's scene p-lock rows at `0x46c82456 + cur_pattern(0x100b14d0)*0x8ed8`, 32 params/row, ORing a per-track bit where the value != `0xff` |
| `0x4000c202` | `scene_morph_frame` — **inside the frame ISR**; packs 32 (A,B) byte pairs per track into `0x80000ed4 + track*64`. Scene A/B indices come from the snapshot byte at `0x4017122a + track`. |
| `0x80000ed4` | per-track 64 B = 32 `(sceneA, sceneB)` pairs — the crossfade endpoints. **This is the same `0x80000ed4` `0x40009094` copies scenes A/B into** (octalab, MKI) — the two findings meet here. |
| `0x4000cc60` | `scene_level_morph` — **inside the frame ISR**; EMAC `msacw` crossfade of the A/B LEVEL pairs by the crossfader coefficients (`0x80003c60`) into `0x80000c80` and `0x800010d4`. Gated by `0x80000006` (morph enable) and `0x80000007` (a full-scale `0x7f00` bypass fill). |
| `0x80000c80` | per-track scene/crossfader level, `+ t*2` — **a volume-curve INDEX** (`curve[0] == 0`), not a level |
| `0x40170f60` | `param_snapshot_base` — live per-track parameter snapshot; record stride `part*0x18b2 + bank*0x9b340`. Sub-blocks: `+0x10` machine/SRC values (written by the part-apply family at `0x40009e1c`), `+0x22` machine-id + flags, `+0x2a` the block the frame publisher copies to voice wb, `+0x11a`, `+0x1da` |

### The arrangement — a data model we had not mapped at all (new 2026-09-24)

> source: `refs/octemu/re/coldfire.syms` @ `6a9ff68` · fetched 2026-09-24. confidence: **C**.

Entirely new territory for this project (`COVERAGE.md` has no arranger entry).

`arranger_object = 0x10000004` — **the arrangement lives in battery NVRAM**, with a
pointer to it at `0x10000000`. Header `+16` u16 (reads 1), **`+18` u16 row count**;
rows at `+20`, **22 bytes each, 48 cap**.

| row field | meaning |
|---|---|
| `+0` | row **TYPE** — 0 = pattern row; turning the PAT column below A01 selects specials (2 displays `REM:`) |
| `+1` | pattern byte, `bank<<4 | pat` (A02 → `0x01`, measured) |
| `+2` | repeat — display `REP` = byte + 1 |
| `+8` / `+9` | scene A / B (`0xff` = none; byte = display − 1) |
| `+10` | u16 `OF` start offset |
| `+12` | u16 `Ln` row length in steps (default `0x10` = displayed 016) |
| `+3..7`, `+14..21` | not yet attributed (M column, loop target/count for LOOP rows) |

`arranger_goto = 0x4004a5c0` reads the selected row and calls **`seq_goto_pattern`
(`0x400a0570`)** — so the arranger drives the *same* pattern-change path documented
above, and therefore inherits the same light-part-apply behaviour (`0x40009e00`). It
writes chain/loop scratch `0x80006908` and `0x800066a4` (repeat) and sets bit 3 of
`0x80006904` (arranger-changed). Per-pattern tempo/length come from the trailer region
`0x400eb038 + pattern*0x8ed8`.

**Persistence:** `arr01..arr08.work` / `.strd` on the card — **11,336 B**, a
`FORM`/`DPS1`/`ARRA` container, one file per arrangement slot. (Compare our `.strd`
handling in RELOAD2/3 — same `.work`/`.strd` pairing convention.)

**Editing path** (useful for a future feature): `ARR` → `YES` opens the ARRANGEMENT
EDITOR; `FUNC+DOWN` inserts a row (`arranger_row_editor` increments the count with
`movew a2@(18)`); LEFT/RIGHT pick the column; **ENC7 — the LEVEL knob, encoder index 6
— changes the value.**

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
| **arrow DOWN** | `0x21` | `0x4004b970` (same as UP) | **arrow RIGHT** | `0x33` | `0x400491a0` |
| **arrow LEFT** | `0x20` | `0x400491a0` (same as RIGHT) | | | |

Arrows — **CORRECTED Session 80 continued (6), hardware-derived; the previous pairing
(Session 43, confidence C, cross-checked against octabam MAINMENU.md §7 — which is
MKII-oriented, while this project is MKI-only) was WRONG.** It claimed UP `0x34` /
RIGHT `0x21` share `0x4004b970` and DOWN `0x33` / LEFT `0x20` share `0x400491a0`. A
RELOAD2 build gating `0x4004b970` on `0x34` and `0x400491a0` on `0x33` was flashed:
**UP worked, DOWN did not** — which falsifies the old pairing, since under it `0x33`
is DOWN and that gate passed `0x33`. The true pairing also matches the handlers' own
shape: **UP `0x34` / DOWN `0x21` share `0x4004b970`** (the VERTICAL pair, which is why
stock special-cases its two codes at `0x4004b9d6`), and **RIGHT `0x33` / LEFT `0x20`
share `0x400491a0`** (horizontal — that wrapper never examines the keycode at all,
treating both identically). Which of `0x33`/`0x20` is left vs right is still unverified
and does not matter to any current patch. Original (wrong) note retained for context:
**UP `0x34` / RIGHT `0x21` share `0x4004b970`**;
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
| `0x46c7d8de` | C | runtime key-state table, stride **24**, one record per keycode ≤ 63, populated from the T1/T2 keymap by `set_key_state 0x40031734` (the sole per-key dispatcher: `set_key_state(code,event)` → calls the record's press/release handler with `(code@4, event@8)`). Record `+16` = held flag → `is_key_held(code)` = `FUN_4003171c` = `*(u32*)(0x46c7d8ee + code*24)`. `+8` (u16, from the keymap `flags` field) = hold/repeat delay. **CORRECTED (Session 80 continued (3), measured by walking T1 `0x400bfc10` / T2 `0x400c01f4` in 26-byte strides — the two tables are identical here):** the earlier claim that this is `0` for trig / track / PLAY / REC / PTN / BANK is **wrong**, and it conflated two distinct fields. Record `[22..23]` = **hold delay**, `[24..25]` = **repeat interval**; they are independent. Measured: trigs `0x00-0x0f` delay `0x10`; track keys `0x10-0x17` and `0x22-0x26` delay `0x1e`; **PTN (keycode `0x2e`, not `0x1c`) delay `0x1e`**; **BANK `0x2f` delay `0x1e`** — all with repeat `0`. Only `YES 0x31` / `NO 0x32` have delay `0` (and hold handler NULL). Repeat is nonzero **only** for the arrows: **UP `0x34` and RIGHT `0x21` share handler `0x4004b970` with delay/repeat `0x1e`/`0x1e`; DOWN `0x33` and LEFT `0x20` share handler `0x400491a0` with `0x0f`/`0x04`** — so LEFT/RIGHT are not distinct keys to a handler *and* they auto-repeat, which any detour on those two handlers must expect. |
| `0x80000000` | C | current audio track (byte; UI mirror `0x100b14cc`). `0x80000012 != 0` = MIDI mode (page resolution adds +8). FUNC is **not** a plain keymap record — its held-flag was not located (Session 21). |
| `_DAT_460e5cd0` | C | `!= 0` ⇒ a `FUN_4006d57c` dialog is open (that ctor bails on it at entry). Gate a new global combo on `== 0`. |

### Input maps — screens own keys and knobs in LAYERS (new 2026-09-24)

> source: `refs/octalab/docs/FINDINGS.md` + `INPUT.md` @ `e0dc56d` · fetched
> 2026-09-24. confidence: **C** — "Run on a MKI", same hardware as us.

The keymap tables above are the *stock static* layer. On top of them, **a screen owns
keys and knobs by registering an input map, and maps are a stack**:

| Addr | What |
|---|---|
| `0x40031494` | **register an input map** (the `off` / unregister entry is `0x4003146c`) |
| `0x46c7d8de + code*0x18` | the live **keys** table, rebuilt by every registration |
| `0x46c7dede + enc*0x14` | the live **encoders** table, rebuilt by every registration |

Rules, all MKI-verified:

- **The last map registered wins.** Every registration rebuilds both RAM tables.
- **A key field of `-1` lets the layer below through** — the pass-through idiom.
- **An encoder listed with a null handler is *swallowed*** — this is exactly how a
  popup locks the knobs over the page behind it.
- An encoder handler is called as `(encoder, delta)`.
- **Encoders: A..F = 0..5, LEVEL = 6.** Their **press** codes are `0x38..0x3e`.
- Arrows `0x33 0x20 0x34 0x21`, ENTER `0x31`, EXIT `0x32` — the same set our
  hardware-corrected table above carries (independent corroboration of the set; octalab
  does not disambiguate which arrow is which, so our Session-80 pairing stands).
- Taking a map off returns the tables to stock.

**⚠️ The hazard that matches our own RELOAD3 picker/overlay experience.** Holding a trig
registers the stock trig-held input map *over any other*. If a map is left behind and
**swallows the trig's release**, `0x460d174a` stays set and **the trig is held for
good** — REC then offers TRIG COPY and the sequencer will not stop. Related state:
grid recording is `0x460d1736 != 0` (the trig-key dispatcher is `0x40060ce0`, which our
table above already names). The LOCK picker's steps come from
`0x460d174a`/`0x460d174c`.

This is the mechanism behind "a picker that must be dismissed cleanly". Our RELOAD3
work replaced a picker with two direct chords; if any future overlay registers a map,
**unregistering it on every exit path is not optional.**

**Callable SETUP-window drawing primitives** — the frame, the dotted 3 × 2 grid and
centred text, usable for a page of one's own: `0x400570b8`, `0x40011a58`, `0x40012004`,
`0x40013904`; the eight font records at `0x400ba812..`. (Directly relevant to the S87
RELOAD3 "titled, centred, self-dismissing card".)

**Stock audio-editor entry, for chord features:** `[BANK]` ignores held trigs; stock
`[TRACK]+[BANK]` opens the audio editor via `0x4006de34(type, slot)` + `0x4006e160()`;
the bookkeeping that keeps a held trig in place after an edit is `FUN_4004f5f8`'s.

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

`0x80000110` / `0x80000310` → tracks 5–8, `0x80000210` / `0x80000410` → tracks
1–4. 128 halfwords each = **32 per track**, one DSP word per halfword. (This
source's own "core 0"/"core 1" labels are inverted from `dsp56300.md`'s
settled labelling — payload A = tracks 5–8 there, hardware-proven via our own
SIDECHAIN3 `@KADJ@` math; track groupings agree everywhere, only the two
labels disagree depending which octabam doc you're reading. Go by track
numbers, not by "core 0/1", when cross-referencing sources.)

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

> **⚠️ `0x800000d4` — three sources, and the disagreement is a METHOD artefact. Read
> this before using it, but do not treat it as proven-taken.** Re-examined 2026-09-24:
>
> | source | says | method |
> |---|---|---|
> | this file, Session 20 | **0 ColdFire refs** | absolute-long scan |
> | our own sweep, 2026-09-24 | **0 refs to any of `0x800000d4..df`** — including `0x800000dc`, which MUTE MODE ships on | absolute-long scan of the whole image |
> | `reference/MERGE.md` (B1 note) | "`0x800000d4` **is** referenced once in stock" | **unstated** |
> | `refs/midisc/.../memory_map.py` @ `63ca127` | "Never 0x800000D4 (OS refs)" | unstated (another project's judgement about its own build) |
>
> **The decisive structural fact:** `0x80000070` is the base of the PERSONALIZE block and
> stock reaches its settings by **base + displacement**, so an absolute-long scan cannot
> see *any* of them — which is why our sweep finds zero references even to words stock
> certainly does use. The sweep is therefore **inconclusive, not exonerating**, and
> MERGE.md's own B1 text says exactly this about `0x800000f8`.
>
> **But stock's own restore length settles the PERSONALIZE question:** the boot restore is
> `memcpy` length **`0x64`**, covering `0x80000070..0x800000d3` — it **stops one byte short
> of `0x800000d4`**. So `0x800000d4` is *not* one of stock's PERSONALIZE settings. For it
> to be taken, stock would have to use it for something unrelated, for which there is no
> evidence in two scans.
>
> **Practical guidance:** `0x800000d4` is *probably* free; MERGE.md's "referenced once"
> claim is **unsubstantiated and contradicted by our own sweep** — do not propagate it as
> fact. Still **prefer `0x800000d8`** for new state, simply because `0xd4`/`0xd5` are
> already spoken for as `patch_softmute`'s `OTFX_PROBE` diagnostic words (verified
> 2026-09-24: the shipping 970-byte `DT_MODE=1` build contains **no** reference to either;
> only the 986-byte diagnostic build does). **To settle it properly**, use the method
> MERGE.md prescribes for `0x800000f8`: an emulator read/write watchpoint across a stock
> boot plus a few minutes of ordinary operation. Until someone runs that, treat every word
> in `0x80000070..0x800000df` as "reachable by displacement, so a scan proves nothing".
>
> ⚠️ **The live consequence is the one MERGE.md B1 already names**, and it is not about
> `0xd4`: MUTE MODE widens the restore `0x64` → `0x70`, so a **merged** build would also
> restore `DJ_MODE` (`0x800000d8`) from battery SRAM `0x100fff68` — a word nothing
> maintains — and **DIRECT JUMP could come up ON**. That is a real merge blocker with a
> resolution already chosen (move `DJ_MODE` out of the span); it is unaffected by how the
> `0xd4` question lands.

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
