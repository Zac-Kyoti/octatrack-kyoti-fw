# Elektron Octatrack firmware architecture (OS 1.40C)

Architecture document consolidated from the educational reverse engineering of the
firmware. It brings together everything that has been verified: hardware, OS format, kernel,
storage, audio engine, sequencer, and the memory map. It complements `NOTES.md` (chronological
log) and the scripts in `tools/`.

Elektron ships **one OS 1.40C image for the Octatrack MKI and MKII**; a boot-time
probe (`0x46c8d18c`) adapts the few unit-specific details. All hardware testing in
this repository is on a MKI.

> **Scope and honesty**: everything marked ✓ is verified (checksum from the firmware itself,
> byte-exact decompilation, or direct disassembly). Anything marked ~ is a strong inference but
> not confirmed byte by byte. No Elektron firmware is redistributed; only analysis.

---

## 1. Executive summary

The Octatrack is an 8-track sampler/sequencer. Its firmware runs on a
**Freescale ColdFire** CPU (68k family, big-endian, ~266 MHz) assisted by a **Freescale
DSP56xxx** DSP for real-time audio. On top of the hardware runs a proprietary preemptive
**Elektron microkernel** (not a commercial RTOS). The OS is loaded from **CompactFlash** via the
ColdFire's on-chip **ATA** controller.

The architecture is uniformly **producer/consumer decoupled by buffers in RAM**:
the same kernel message-queue pattern appears in storage I/O and in the
audio pipeline.

---

## 2. Hardware

| Component | Detail | Confidence |
|---|---|---|
| CPU | Freescale **ColdFire** (prob. MCF5445x, 32-bit, big-endian, ~266 MHz) | ~ (forums + corroborated by the on-chip ATA controller in the firmware) |
| Audio DSP | Freescale **DSP56xxx** | ~ |
| Storage | **CompactFlash** (FAT16/32), OS and data; boots to DEMO without CF | ✓ (official) |
| Expansion bus | FlexBus (chip-selects for ATA, DSP, RAM) | ✓ (from the firmware) |

The firmware **corroborates the ColdFire CPU**: it uses the on-chip ATA controller (registers in
the MBAR space `0xFC04_51xx`) that characterizes the MCF5445x family.

---

## 3. OS format and update chain ✓

Elektron distributes a ZIP with **two transports of the same OS**: a `.bin` and a `.syx`.
Both wrap the same compressed container, which decompresses to the **MAIN OS** (1,112,560 B,
SHA256 `164f3122…`, ColdFire code).

```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK( aPLib( MAIN OS ) ) ) + checksum
.syx  = SysEx 7-bit(              ELEK( aPLib( MAIN OS ) )              )
```

- **ELUP layer** (`.bin`): XOR obfuscation with feedback (fixed embedded constants
  `0x9E3B16A2`/`0x764E28CA`, mixes `C3=0x360FA955`/`C7=0xEF4A9AB6`) + additive checksum.
  Reimplemented in `tools/bin_decode.py`; **the firmware checksum validates** → correct.
- **ELEK layer**: proprietary container with a section compressed in **aPLib**.
- **No cryptographic signature** in any layer → firmware is analyzable and modifiable
  (which is why `elektron-firmware-tool` can rebuild `.syx` with recalculated checksums).

**OS validation on update** (`FUN_4007f748`), with its error codes:
`-1` IO · `-2` not a valid OS · `-3` length · `-4` checksum · `-5` MK1 not allowed (`<"0156"`)
· `-6` cannot downgrade version (`<"0178"`).

The `-5` check is a *version-string floor* (`<"0156"`), not a live unit-model
gate: a 1.40C-derived image keeps the stock internal code `"0178"` (the `-V`
version field is a separate display string) and passes. The Bug-1 build has been
flashed to a MKI and runs — see `NOTES.md` "Session 7".

**UI → write flow** (all decompiled):
```
OS UPGRADE menu → confirm → os_upgrade (stops audio, "WORKING PLEASE WAIT", enqueues task)
 → scans the CF, validates → os_apply_flash (critical section) → writes the CF via ATA → reboot
```

---

## 4. Kernel: proprietary preemptive microkernel ✓

It is not MQX/ThreadX/VxWorks (zero third-party signatures; only banner `ElektronOctatrack DPS-1`).
It is a custom microkernel with all the classic components:

- **Task Control Block (TCB)**: state @`0x13` (0=blocked, 1=ready), priority @`2`, list pointers
  @`0`/`1`. Current task = `_DAT_800068fc`; top priority = `_DAT_800068d8`.
- **Per-priority ready queues** (doubly-linked circular lists per level).
- **Context switch via `TRAP #0`** (`FUN_40000818`, wait/yield).
- **Message queues with blocking receive** (`FUN_40000c3c`, post): wakes the task
  that is waiting and forces a reschedule with `0xFC04_C010 |= 0x800` (ColdFire interrupt controller).

**Scheduler / context switch core** ✓ (`FUN_4000056e`, reached by `TRAP #0` and by the timer):
1. Saves ALL of the current task's registers (D0–D7, A0–A6, SR) into its TCB `_DAT_800068fc`
   at offsets `0x0c`–`0x48` (hence the TCB layout: saved context at `0x0c`+, SP at `0x38`).
2. Takes the highest-priority ready task (head of the queue at `_DAT_800068d8`).
3. Clears the reschedule bit (`0xFC04_C010 &= ~0x800`) and **re-arms the ColdFire PIT timer
   `0xFC08_0000` (reload `0xb3f`)** = the time-slice quantum → **time-preemptive** scheduler.
4. Switches `_DAT_800068fc` to the new task and restores its context.

This kernel **unifies the whole firmware**: the ATA "async queues" and the audio "voice mailboxes"
ARE its message queues. Scheduler double trigger: `TRAP #0` (voluntary yield)
+ PIT `0xFC080000` (temporal preemption).

---

## 5. Storage: ATA/CompactFlash stack ✓

```
filesystem → async command queue (FUN_4001568c, +event) → dispatcher (FUN_40015098)
 → dispatch by ATA opcode → handler → ATA task-file registers @ 0x90000000 (PIO)
```

- **ATA commands** dispatched: `0x20` READ SECT · `0x30` WRITE SECT · `0xC8` READ DMA ·
  `0xCA` WRITE DMA · `0xE0` STANDBY.
- **Driver with vtable** (`FUN_40015e28` sets it up) and **hardware variant detection**
  by reading an IDENTIFY-type descriptor.
- **ATA task-file registers** @ `0x9000_00xx`: data `a0`, seccount `a8`, LBA `ac/b0/b4`,
  device `b8` (`|0xE0` = LBA mode), command `bc`, status `d8` (BSY/DRDY/DRQ).
- ATA host (control) in the ColdFire MBAR `0xFC04_51xx`.

---

## 6. Audio engine and sequencer ✓

Engine data structures (all in the `0x80000000` RAM window):

| Structure | Address / layout |
|---|---|
| Per-track voice state (audio) | base `0x800049d8`, stride `0xA8`, ×8; byte[0]=active |
| MIDI track state | `0x80006500[t]`, global `0x800065b8` |
| Voice command mailboxes | `0x46c7e9fa` / `0x800018be` / `0x800018de` `[t*4]` |
| Per-track pattern data | `_DAT_46c82456 + pattern*0x18b2 + track*0xc` |
| Globals | current track `0x100b14cc`, current pattern `0x80000003` |

**Audio pipeline (control path)**:
```
sequencer trig
 → FUN_40005178 writes voice mailbox (RAM)
   → FUN_4000c8a4 (frame builder, control-rate): consumes mailboxes, updates 8 voices,
      assembles a parameter FRAME in a DOUBLE BUFFER in shared RAM 0x80000000 (ping-pong 0x800000e0)
     → handshake with the DSP via registers @ 0x20000000
       → DSP56xxx reads the frame and synthesizes (playback, time-stretch, filters, FX)
```

**DSP interface: MMIO at `0x20000000`** (revealed by radare2):
- `0x2000_0000` control command (`0x81` = start DSP, `0x8C` = swap frame)
- `0x2000_0004` command/status (write, poll bit7 busy)
- `0x2000_0008` status/ready (bit `6`: DSP ready — polled at boot and on every transfer)
- `0x2000_0014`/`0x18`/`0x1c` data port (the 3 bytes of each 24-bit word)

**DSP boot** ✓ (`FUN_40001d4c` = DSP program loader): uploads the program to the DSP
**3 bytes at a time = 24-bit words** through the `0x20000014/18/1c` port, with a handshake on the
ready bit of `0x20000008`, and starts the DSP by writing `0x81` to `0x20000000`. The **24-bit**
word size confirms that the DSP is a Freescale DSP56xxx (hardware fact deduced from the firmware
itself). Args: `param_1`=program, `param_2`=length, `param_3`=load address in the DSP.

**Trig → voice** ✓ (`FUN_400977cc`, dispatched by machine type): given a trig on a track, it reads its
machine state (`FUN_40097168` → 0–4) and, depending on the event type, emits the voice command via
`FUN_40005178` with flags (`0x80` start, `0x10`/`0x8010`/`0xf010` = one-shot/hold/stop/retrig).
It is the bridge "there is a trig on the step" → "the voice sounds".

**Work split**: ColdFire = control (RTOS, sequencer, assembles parameters).
DSP56xxx = signal (real-time audio). Synchronized by double buffer + handshake.

---

## 7. Consolidated memory map

| Window | Use |
|---|---|
| `0x40000000` | SDRAM: code (OS image @ `0x40000400`) |
| `0x46000000` | SDRAM: data/BSS and app objects |
| `0x20000000` | **Audio DSP coprocessor** (cmd `04`, status `08`, frame idx `1c`) |
| `0x80000000` | Fast/shared RAM: voice state, kernel TCBs, **double-buffer DSP frames** |
| `0x90000000` | ATA task-file (CompactFlash) via FlexBus |
| `0x100b0000` | Small globals (current track/pattern) |
| `0xFC000000` | ColdFire on-chip peripherals (MBAR): ATA host `FC0451xx`, IRQ ctrl `FC04C010` |

**Image load base**: `0x40000400` (determined empirically: 1441 string pointers
resolve with that base). Image data/BSS ~`0x400bxxxx`.

---

## 8. Project tools (`tools/`, all reproducible)

| Script | What it does |
|---|---|
| `fetch-os.sh` / `analyze.sh` | downloads the official OS, entropy + binwalk + decompression |
| `bin_decode.py` | decodes the ELUP `.bin` (deobfuscates + validates checksum) |
| `decode_elek.c` | decompresses the ELEK container (aPLib) → MAIN OS |
| `find_base.py` | determines the load base by pointer→string correlation |
| `string_func_map.py` | function→UI-strings map (619 functions) |
| `disasm.sh` | radare2 with correct arch/base (m68k BE @ 0x40000400) |
| `Ghidra*.java` | headless decompilation scripts (Ghidra 12, Coldfire language) |
| `build_*.py` | the guarded binary-patch builders, one per feature, plus `build_bugbuilds.py` for the composites — see [`BUILD_KYOTI.md`](BUILD_KYOTI.md) |
| `patch_*.s` / `patch_sc_dsp3.asm` | the ColdFire and DSP56300 patch sources each builder assembles into a code cave |
| `emu_*.py` | Unicorn emulators running the real image bytes, one per feature; `emu_rtos.py` wraps a full-firmware run (real scheduler, tasks, CF card) |
| `diag_*.py` | targeted measurement harnesses — the tools that settle "what does stock actually do here", usually against real hardware-exported projects |
| `dsp56300_xcore/` | a dual-core DSP56300 host used to validate the cross-core side-chain under lock-step and timing-skew fuzzing |
| `refs/sync.py`, `refs/whatsnew.py` | clone + track the external Octatrack-RE repos distilled into `reference/kb/` |

---

## 9. Open fronts

Two of the original four are closed:

- ~~**Sequencer clock**~~ ✅ — the audio frame ISR (`0x4000aad0`) drives it through a
  `2³¹/tempo` phase accumulator and wakes the sequencer task via a kernel queue. The step
  engine below it is mapped too: the per-clock-tick body reached from `0x400a1e0c`,
  `LEN_TBL` as a **ticks-per-step** table, `0x800065b6` as master ticks-within-step and
  `0x800065b2` as the master step, and the pattern commit at `0x400a44d0` with its
  per-track rebuild tail.
- ~~**DSP program load**~~ ✅ — located and extracted (`out/dsp_region.bin`, DSP56300,
  ~188 KB), with **two payloads**: A serves tracks 5–8, B serves tracks 1–4. The module
  dispatch table is mapped and individual modules have been replaced in place.
- **Remaining ATA handlers**; large functions the ColdFire decompiler does not lift (read
  in ASM). Note that "corruption" in the notes means Ghidra failing to decompile a dense
  function, not damaged data.
- **Extract the vector table** (`0x400` preamble, not in this section) for the ISR map.
- **The signal plane.** 16 of the 17 effects and all of timestretch remain untouched DSP
  code; see [`COVERAGE.md`](COVERAGE.md) for the full matrix.
