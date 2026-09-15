# RE Log — Octatrack

Record of findings. Each run of `analyze.sh` leaves evidence in `out/`.

> **New session? Read `START_HERE.md` first.** This log is chronological and starts at
> 2026-07 recon — do NOT read top-to-bottom. Jump to the newest `## Session N` section and
> its `STATE OF PLAY` / `NEXT` blocks. Section index: `grep -nE '^## ' NOTES.md`.


> **Scope.** Phases 0–3 below are the shared reverse-engineering **foundation**
> — hardware, container/update chain, kernel, memory map, DSP, the PERSONALIZE
> menu, CF-card flashing — cross-checked with octamax and the external-RE KB
> (`reference/kb/`). The **OT Kyoti FW work log starts at *Bug 1* ("Session 4"
> onward)**. octamax's own behaviour-mod design notes (scenes, LED, lazy Part
> transitions, arp key-scales, live bank paging) have moved to
> `reference/upstream-notes.md` — they are not part of this firmware.

## Phase 0 — Static recon of the public OS  [COMPLETED ✓ 2026-07-26]

Goal: decide whether the payload is **compressed** (feasible) or **strongly encrypted** (blocking),
and identify where the real ColdFire code lives. **Result: compressed. Firmware obtained.**

Checklist:
- [x] Download official OS 1.40C + record sha256
- [x] Entropy of `.bin` and `.syx`
- [x] elektron-firmware-tool on `.syx` → extracts the raw section, checksums OK
- [x] Confirm container: Octatrack uses **ELEK** (within the supported family)
- [x] Save the decompressed raw as a candidate for disassembly
- [ ] binwalk on the `ELUP` `.bin` (optional; the `.syx` already yielded the raw)

### Results

- **Artifacts** (`OCTATRACK_OS1.40C_dist.zip`, sha256 `370c55a3…73ff0`):
  - `.bin` (459 KB): magic `ELUP`, entropy **uniform ~8.0** (compressed end to end).
  - `.syx` (641 KB): `F0 00 20 3C` (SysEx + Elektron ID) wrapping the **`ELEK`** container.
- **elektron-firmware-tool `-i`**: `device: Octatrack (0x05)`, `version 1.40C`,
  container `ELEK` 469834 B, **section id 3 "MAIN OS" → 1,112,560 B decompressed**, checksums OK.
- **Decompressed raw** `out/raw/section_3_MAIN_OS.bin` (1,112,560 B):
  - Mean entropy **5.5** (real code+data, NOT encrypted); only 3.8% of windows are high.
  - **2908 readable strings**: UI menus, error codes, `/octatrack_factory_os.bin`.
  - m68k big-endian disassembly OK: prologue `lea -0x1c(a7),a7` + `movem.l d2-d7/a2,(a7)`.

### Memory-map clues (from absolute refs in the code)

- **Data/BSS in SDRAM base `0x40000000`** (refs to `0x400b9650`, `0x400b9654`, `0x400dea48`).
- Initial stack loaded from ~`0x48000000`.
- **Code load** base: still to be determined (the raw starts in code, not in a vector table).
  Strategy: locate where the code references its own strings to fix the base address.

## Phase 1 — Static disassembly  [IN PROGRESS]

- Target: **ColdFire / m68k, big-endian**.
  - radare2: `./disasm.sh` (already configured with base and arch).
  - Ghidra: processor `68000`, big-endian, base `0x40000400`; then run
    `tools/ghidra_import.py` to define strings/pointers and populate xrefs.

### BASE ADDRESS DETERMINED ✓  =  `0x40000400`

Empirical method (`tools/find_base.py`, not an assumption): correlate the offsets of
the 2607 strings in the file against the absolute 32-bit pointers (high byte 0x40).
The sweep of candidate bases gave an unambiguous peak:

| candidate base | strings with a direct pointer |
|---|---|
| **0x40000400** | **1441** |
| 0x400003dc | 291 |
| 0x40000424 | 290 |

- Peak 5× over the second → solid base. Image in SDRAM `0x40000000` + `0x400` of
  header/vectors; the decompressed MAIN OS section maps at `0x40000400`.
- Data/BSS at `~0x400bxxxx` (consistent: `0x400b9650 - 0x40000400 = 0xb9250`, inside the image).
- Verified in r2: at `0x40000400` the prologue `lea -0x1c(a7),a7` + `movem.l` appears,
  and there is code `move.l #0x400b3349,d0` loading pointers to strings as immediates.
- Artifacts: `out/base.txt`, `out/pointers_to_strings.csv` (**1993 sites** ptr→string).

### Function → UI-strings map ✓  (`tools/string_func_map.py` → `out/string_function_map.txt`)

Detects string-pointer loads in the code (`pea`/`lea`/`move.l #imm`) and walks back
to the function prologue (`LINK`/`lea -n(a7),a7`). **619 functions** anchored to strings,
1060 refs in code. Key functions already identified by name:

| Function | What it is (by its strings) |
|---|---|
| `0x40086d7a` | **Serializes project settings** — 58 keys (`MIDI_CLOCK_SEND`, `MASTER_TRACK`, `MAIN_LEVEL`…) |
| `0x4001fc1e` | **Error handler** — 49 strings (`WAV/AIFF PARSE ERROR`, `SAMPLE NOT UNLOADED`…) |
| `0x400867e0` | Writes the `[SAMPLE]` section of the project file (OctaLib format) |
| `0x40069424` | `FORMAT CARD` handler |
| `0x400645ce` | `SAVE PROJECT` handler |
| `0x40022fdc` | `COLLECT SAMPLES` handler |

This **connects the firmware to the already-documented file format**: the settings
function emits exactly the project-file keys in plain text.

### Decompilation in Ghidra ✓  (12.1.2, language `68000:BE:32:Coldfire`, base 0x40000400)

Project in `out/ghidra_proj`. Scripts: `tools/GhidraDecompile*.java` (Ghidra 12 doesn't ship
Jython → use Java). Logs: `out/ghidra_decompile*.log`.

**Finding: shared dialog constructor `FUN_4006d57c`**
Reconstructed signature: `(title, num_options, char **options, default, confirm_callback)`.
Creates a popup (measures text with the font at `DAT_400ba876`, window via `FUN_4005829c`) and
stores the confirmation callback. Every action menu calls it with its label.

**OS UPGRADE flow traced end to end** (`FUN_400636bc`):
```c
if (FUN_400448dc() == 0)   FUN_40063660(0);          // no playback -> direct upgrade
else {                                                // with playback:
    opts = {"PLAYBACK WILL BE", "STOPPED. CONTINUE?"};
    FUN_4006d57c("OS UPGRADE", 2, opts, 3, FUN_40063660);  // dialog; on confirm -> FUN_40063660
}
```
→ **`FUN_40063660` = the actual OS update routine** (next target to decompile).

**ColdFire hardware registers identified** (in the init/main function `~0x4001fc1e`):
- `0x20000008` — status register polled at boot (`while ((*0x20000008 & 6)==0)`).
- `0xfc04xxxx` — on-chip peripheral space (MBAR) of the ColdFire (init writes).
- App data/BSS at `0x460exxxx` and `0x46c8xxxx` (in addition to the `0x400bxxxx` of the image).

**Known limitation**: the ColdFire decompiler fails ("Cannot properly adjust input
varnodes") on large functions with complex frames (e.g. `project_settings_serialize`
5388 B, `project_sample_section` 1434 B). The disassembly does work; analyze them at the ASM level.

### Complete OS UPGRADE chain (decompiled) ✓  — logs `out/ghidra_{osupgrade,flashwriter,apply,program}.log`

```
OS UPGRADE menu
  └─ FUN_400636bc   confirms "PLAYBACK WILL BE / STOPPED. CONTINUE?" (via FUN_4006d57c)
      └─ FUN_40063660 (os_upgrade)  stops audio, "WORKING PLEASE WAIT", QUEUES a deferred task:
          └─ FUN_4006370c  scans the CF, picks the OS file, validates existence
              └─ FUN_40080434 (os_apply_flash)  critical section + calls the loader and maps errors
                  └─ FUN_4007f748 (os_file_program)  << THE CORE: parses/deobfuscates/verifies >>
```

**`FUN_4007f748(path, mode)` — OS file format (`.bin`, magic ELUP):**
- `fopen`; if it fails → `-1 IO_ERROR`. Reads size; `payload = filesize - 0xC` (12 B header).
- `payload > 0x100000` (1 MiB) → `-3 LENGTH_ERROR`.
- Header (words): `[0]`=magic (`== DAT_400a966c`), `[1]`=feedback seed,
  `[3]`=flags (bit `0x800000` selects variant) + checksum, `[4]`=version material. Payload from `[2]`.
- **Obfuscation = XOR cipher with feedback** (not compression, not real crypto):
  each word: `p ^= 0x9E3B16A2` (or `0x764E28CA` if flag) → rotate/byteswap → `k ^= prev_cipher ^ x`.
  Constants **fixed and embedded** → the `.bin` is fully decodable offline. (This explains the
  uniform ~8.0 entropy of Phase 0: it's this XOR stream, not compression.)
- **Integrity = additive checksum** (sum of deobfuscated words) compared with the stored value;
  mismatch → `-4 CHECKSUM_ERROR`. **There is NO cryptographic signature** (confirms Phase 0: modifiable firmware).
- **Model/version gating**: `< "0156"` (0x30313536) → `-5 MK1_OS_NOT_ALLOWED`;
  `< "0178"` (0x30313738) → `-6 CAN_NOT_DOWNGRADE`. Version = packed ASCII.
- `mode=1` → only returns the version (for the pre-scan). `mode=0` → deobfuscate+verify (commit).
- On successful completion: `FUN_4007fe80(0xffffffff,...)` finalizes/reboots into the new OS.

### Offline `.bin` decoder ✓✓✓  (`tools/bin_decode.py` + `tools/decode_elek.c`)

Reimplementation of `FUN_4007f748`. Constants extracted from the OS image:
`magic=0x454C5550 ("ELUP")`, `C3=0x360FA955`, `C7=0xEF4A9AB6`, XOR `0x9E3B16A2`/`0x764E28CA`.

**Double validation:**
1. `bin_decode.py` deobfuscates the `.bin` and **the additive checksum matches** (`0xa85be7ef`) — the
   SAME check the firmware performs → deobfuscation demonstrably correct.
2. The deobfuscated payload is an **`ELEK0178`** container (identical to the one in the `.syx`). `decode_elek.c`
   (reuses the tool's `ap_depack`/aPLib) decompresses it → **1,112,560 B, SHA256 `164f3122…`**,
   **byte-identical to the MAIN OS extracted from the `.syx`**.

**Full chain reconstructed and verified end to end:**
```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK(aPLib(MAIN_OS)) ) + checksum
.syx  = SysEx 7-bit( ELEK(aPLib(MAIN_OS)) )
                                    → both → the SAME MAIN OS (164f3122…)
```
No cryptographic signature at any layer: reversible XOR obfuscation + additive checksum + aPLib.

### Full storage stack (decompiled) ✓ — logs `out/ghidra_{commit,hw,drv,fac,prim,txn,disp,ata}.log`

Traced from the UI down to the ATA registers. **The OS "flash" = writing to the CompactFlash (ATA)**;
the driver is the ColdFire ATA block stack, NOT an internal NOR flash.

```
os_apply_flash (FUN_40080434)
  └─ FUN_400323a0   dispatches via driver vtable: (*(obj+0x10))(0)   [obj=_DAT_460d16cc]
      └─ FUN_400158cc  = method +0x10 → sends ATA command 0xE0 (STANDBY IMMEDIATE: flush/park before reboot)
          └─ FUN_4001568c  QUEUES the command (async ring, 0x16 B entry) + reserves event (_DAT_460babfc) + waits
              └─ FUN_40015098  DISPATCHER: drains the queue and dispatches by ATA opcode:
                    0x20 READ SECT · 0x30 WRITE SECT · 0x87 · 0xC0 · 0xC8 READ DMA · 0xCA WRITE DMA · 0xE0 STANDBY
                    └─ FUN_40014c48 (0x30 WRITE SECTORS)  ← ATA task-file registers @ 0x90000000 (FlexBus)
```

- **Factory driver** `FUN_40015e28`: builds the vtable at `&DAT_46c85c76` (methods 0x400157xx/0x400158xx)
  and **detects the hardware variant** by reading an IDENTIFY-type descriptor (offsets 0x62/0x6a/0x146/0x7e/0xb0).
- **Confirmed hardware map**:
  - ATA host registers (control/config) in ColdFire MBAR: `0xFC04_51xx`, status `0xFC0A_4039`.
  - ATA task-file (data/LBA/cmd/status) in FlexBus window `0x9000_00xx`
    (data=0xa0, seccount=0xa8, lba=0xac/b0/b4, dev=0xb8, cmd=0xbc, status=0xd8).
  - **The MCF5445x has an on-chip ATA controller → corroborates the ColdFire CPU from Phase 0.**
- **RTOS confirmed (not bare-metal)**: async I/O via command queue with event-based completion
  (bit pool at `_DAT_460babfc`), a worker that drains the queue. There are tasks and synchronization.

## Musical layer — audio/sequencer engine (decompiled) — logs `out/ghidra_{play,trk,voice,voice2}.log`

Engine data map (all in the RAM window `0x80000000` = hot state):

| Structure | Address / layout | What it is |
|---|---|---|
| Per-track voice state | base `0x800049d8`, stride `0xA8`, 8 tracks | live audio voice; byte[0] = active |
| "Active voice" query | `FUN_40000ee0(t)` reads `0x800049d8[t*0xA8]` | 0=inactive, 1/2 per `0x8000184a` |
| "Something sounding" query | `FUN_400448dc` walks the 8 tracks | used by OS-upgrade to block |
| MIDI tracks state | `0x80006500[t]`, global `0x800065b8` | MIDI mute/active flags |
| Voice command mailboxes | `0x46c7e9fa`/`0x800018be`/`0x800018de` `[t*4]` | `FUN_40005178` queues per-track commands |
| Per-track pattern data | `_DAT_46c82456 + pat*0x18b2 + trk*0xc` (+0x8f385) | sequenced data (trigs/params) |
| Globals | current track `0x100b14cc`, current pattern `0x80000003` | live selection |

**Confirmed architecture — same pattern as storage**: `FUN_40005178` (command voice)
writes mailboxes in RAM, consumed asynchronously by an ISR/feeder that feeds the DSP56xxx.
Hardware (DSP) behind an async boundary, just as ATA was behind the command queue.
→ reinforces the RTOS model: producer (sequencer) / consumer (audio ISR) decoupled by RAM.

## RTOS identified: Elektron's PROPRIETARY microkernel ✓ — log `out/ghidra_kern.log`

Not MQX/ThreadX/VxWorks/Nucleus. Negative evidence: **zero** copyright/version/API strings
of a commercial RTOS. Only banner: `ElektronOctatrack DPS-1 0002 / FROM WWW.ELEKTRON.SE`
(DPS-1 = internal Elektron platform, shared across their ColdFire machines).

Positive evidence — preemptive priority-based microkernel, decompiled primitives:
- **`FUN_40000818` (wait_event)**: if `*ev < 1`, links the current TCB into a wait list, state
  `TCB[0x13]=0` (blocked), and executes **`TRAP #0`** = context switch via m68k software trap.
- **`FUN_40000c3c` (post/queue)**: writes ring buffer; if a task is waiting, marks it `TCB[0x13]=1`
  (ready), inserts it into the **priority ready queue** (doubly-linked circular lists), and forces
  reschedule with `0xFC04_C010 |= 0x800` (ColdFire interrupt controller).
- **TCB**: state@0x13, priority@2, list pointers@0/1. Current task = `_DAT_800068fc`.
  Top-priority pointer = `_DAT_800068d8`.

**Unifies everything above**: the ATA stack's "async queues" and the audio engine's "voice mailboxes"
ARE this kernel's message/event queues. A single microkernel, used throughout the firmware.

## DSP interface and audio pipeline ✓ — logs `out/ghidra_{dsp,frame}.log`, r2 disasm

**Physical DSP interface: MMIO at `0x20000000`** (revealed by r2; Ghidra's ColdFire module
fails on this hot-path code). Handshake registers:
- `0x2000_0004` command/status (writes `0x8C`, polls busy bit7 until ack)
- `0x2000_0008` status ("DSP ready": boot polled `while ((*0x20000008 & 6)==0)`)
- `0x2000_001c` frame index reported by the HW → selector of the double buffer `0x800000e0`

**Full pipeline (control path):**
```
sequencer trig
 → FUN_40005178 writes voice mailbox (0x46c7e9fa / 0x800018be) in RAM
   → FUN_4000c8a4 (frame builder, control-rate) consumes mailboxes, updates 8 voices,
      assembles a parameter FRAME in a double buffer in shared RAM 0x80000000 (ping-pong 0x800000e0)
     → handshake via 0x20000000 (reads frame idx 0x1c, writes cmd 0x8C to 0x04, polls busy)
       → DSP56xxx reads the frame from 0x80000000 and synthesizes (samples, time-stretch, filters, FX)
```

**ColdFire↔DSP split**: ColdFire = control (RTOS, sequencer, assembles voice parameters).
DSP56xxx = signal (real-time audio). Synchronized by **double buffer + register handshake**.

### Consolidated memory map
| Window | Use |
|---|---|
| `0x40000000` / `0x46000000` | SDRAM: code (img @0x40000400) + app data/BSS |
| `0x20000000` | **Audio DSP coprocessor** (cmd 0x04, status 0x08, frame idx 0x1c) |
| `0x80000000` | Fast/shared RAM: voice state, mailboxes, **double-buffered DSP frames** |
| `0x90000000` | ATA task-file (CompactFlash) via FlexBus |
| `0x100b0000` | Small globals (current track/pattern) |
| `0xFC000000` | ColdFire on-chip peripherals (MBAR: ATA host, interrupt ctrl 0xFC04C010, etc.) |

## Sequencer clock ✓ — logs `out/ghidra_clock.log`, r2 disasm

**The sequencer has NO timer of its own: it is clocked by the DSP's audio FRAME interrupt**
(sample-accurate sequencing). Phase accumulator:
- Tempo → `_DAT_80001814`; per-frame increment `_DAT_80001820 = 2³¹ / tempo`
  (seen in `FUN_4000c8a4`: `_DAT_80001820 = -0x80000000 / _DAT_80001814`).
- `FUN_4009c550` sets the tempo period from the pattern data (`_DAT_46c82456 + pat*0x8ed8`).
- The **frame ISR** (`0x4000aad0`, fires on reading the frame index at `0x2000001c`) accumulates the phase;
  on overflow it advances the step and **posts to a kernel queue** (`FUN_40000c3c`) to wake the
  sequencer task → trigs → `FUN_400977cc` → voice command. Refs to tempo/phase at `0x4000axxx`.

## DSP program: located and extracted ✓ — `out/dsp_region.bin`

**DSP56300 (24-bit), at the TAIL of the MAIN OS image** (`~0x400e2000 .. 0x4010fdf0`, ~188 KB
= ~62,600 24-bit words). Confirmed: `f803 00bb …` = DSP56k opcodes, loaded 3 bytes at a time.
- Loaders: `FUN_40001d4c` → **P** memory (24-bit stream, starts with `0x20000000=0x81`);
  `FUN_40001b18` → **X/Y** data. Uploads in sections to DSP `0x31000`, `0x32000`, …
- Blobs from init: `0x400e21e0`(len 0x96→0x31000), `0x400e2276`(0xae→0x32000), `0x400e2324`, `0x400f59ef`.
- **For the FX/timestretch**: disassemble with target **DSP56300** (Ghidra/r2 don't ship it; a56/dsp56k
  or community SLEIGH modules). Separate project.


## Phase 2 — Hardware (only if needed)  [PENDING]

- UART on the PCB → boot logs (cheap, low-invasive).
- ColdFire uses **BDM** (Background Debug Mode), not ARM JTAG → live flash dump.
- Desolder flash + external programmer = last resort.

## Open questions

- Exact RAM and DAC/ADC codec (undocumented; require teardown/PCB photos).
- Do MKI (DPS-1) and MKII share the OS container format?
- Is there signature/encryption beyond checksums? (resolved by Phase 0)
- Is there any flash dump or community Ghidra project beyond OctaLib/ot-tools-io/elektron-firmware-tool?

## Sources

- Elektron support: https://www.elektron.se/support-downloads/octatrack-mkii
- elektron-firmware-tool: https://github.com/mischa85/elektron-firmware-tool
- OctaLib (Research.md): https://github.com/snugsound/OctaLib
- Elektronauts CPU thread: https://www.elektronauts.com/t/octatrack-cpu-chip-model/93304
- Modding firmware thread: https://www.elektronauts.com/t/modifying-elektron-firmware/36228
- EFF RE FAQ (legal): https://www.eff.org/issues/coders/reverse-engineering-faq

---


## PERSONALIZE menu structure — logs `out/ghidra_{personalize,flags,settingsblock,settertbl}.log`

OS 1.40C has **16 items**, not the 12 in the 1.40A manual (added: `SHORT SAMPLE NAME`,
`RECORD QUICK MODE`, `EXT LEN GRID-REC`, `LED BRIGHTNESS`). Three parallel arrays:

| array | address | entries |
|---|---|---|
| labels | `0x400b2a34` | 16 |
| value getters | `0x400b2a74` | 16 |
| `LED BRIGHTNESS` values (`LOW`/`MID`/`MAX`) | `0x400b2ab4` | 3 |
| setters | `0x400b2ac0` | 16 |

Contiguous, `0x400b2a34`–`0x400b2aff`, immediately followed by unrelated FILE MANAGER data
— so **they cannot be extended in place**.

- `FUN_40068e00(win)` renders: label `[i]`, then calls getter `[i]` for the right-hand
  column. Count `_DAT_460e4678`, cursor `_DAT_460e4670`, scroll `_DAT_460e4668`.
- `FUN_40068fd0(key)` handles input: calls setter `[cursor]`. Setters take `(delta, flag)`
  on the stack, add to the current value and clamp.
- Each setting is its **own 32-bit word**, not a bit in a shared mask:
  `MUTE FOCUSES TRK` `0x80000090`, `QUANTIZE LIVE REC` `0x800000ac`,
  `DIS. PAGE AUTOCOPY` `0x800000c0`, `EXT LEN GRID-REC` `0x800000cc`,
  `LED BRIGHTNESS` `0x800000d0`.
- **Free words inside the block**: `0x800000a8`, `0x800000d4`, `0x800000d8`, `0x800000dc`
  (zero references anywhere).
- No settings word is referenced by the project serializer `FUN_40086d7a`, yet the settings
  survive power cycles → the block lives in **battery-backed RAM** (consistent with the
  Startup Menu's EMPTY RESET, which the manual describes as clearing settings). A new flag
  in a free word should therefore persist with no file-format change. *Inferred, not yet
  verified on hardware.*

To add items: relocate all three arrays to the cave with more entries, repoint the
references, write a getter/setter pair per item, and raise the count.

**Item count** — `FUN_40068fa8` is the list init:

```asm
tstl 0x46c8d18c ; sne d0 ; mvsb d0,d0 ; moveq #15,d1 ; subl d0,d1   -> 15 or 16
movel d1,-(sp) ; pea 5 ; pea 0x460e4668 ; jsr 0x4007ec60            -> list_init(list, rows, count)
```

Raising the immediate to 17 gives 17 or 18 and **preserves the conditionality** of the
16th item (which depends on `0x46c8d18c`). One byte.

**Careful**: the getter and setter arrays are reached by `lea`, but the label array is
loaded as an **immediate into D5** (`move.l #0x400b2a34,%d5` at `0x40068efc`). A sweep
for `lea` alone misses it.

Implemented in `tools/patch_menu.s` + `tools/patch_flags.s`: `NO BANK/PTN TIMER`
(`0x800000d4`) and `LAZY TRANSITIONS` (`0x800000d8`, one switch for lazy part apply +
GUI-in-transition + sticky scenes + both dirty indicators). Both default to unchecked, so
an unconfigured unit behaves exactly like stock — every patch got an early-out gate.
Glyphs: `0x400b5e90` checked, `0x400b5e8e` unchecked. Setters are `(flag + delta) & 1`,
which turns both [YES] and the arrows into a toggle.


## CF-card flashing — `tools/make_bin.py`

MIDI SysEx takes minutes at 31250 baud. The manual's §8.5.2 OS UPGRADE path reads a `.bin`
from the root of the CF card instead. Decoding the official `.bin` showed the ELUP payload
is simply:

    [4-byte BE length][ELEK container]

— exactly the container `elektron-firmware-tool` already builds, so no new format work was
needed, only the forward direction of the obfuscation `tools/bin_decode.py` already
reverses. `rot16` and `bswap` are involutions, so inverting is direct:

    encode: x = k ^ mixer ^ p ;  c = rot16(x) ^ XOR_A   (variant 0, k & 0x800000 == 0)
                                 c = bswap(x) ^ XOR_B   (variant 1)

with the feedback `k` being the previous **cipher** word.

Getting the patched container out: the `.syx` is 7460 SysEx messages each with its own
framing, so rather than reverse that transport, `EFT_EMIT_CONTAINER=<path>` was added to the
vendored tool (5 lines) to dump the container it already builds internally.

**Validation**: `make_bin.py` regenerates Elektron's official `.bin` **byte-for-byte** from
that file's own container. Nothing about the format is inferred. Confirmed working on
hardware.

One caveat: a container whose size is not a multiple of 4 needs the payload padded to a word
boundary (ours needed 2 bytes; the official happened to align). The device reads the declared
length and ignores the tail. `FUN_4007f748` validates the checksum and returns an error code
*before* touching flash, so a malformed `.bin` is rejected rather than half-applied.


## Session 4 — Ghidra headless decompilation now runnable in-sandbox (no macOS host needed)

Previous sessions noted `analyzeHeadless`/JDK "live only on the host Mac, not in this
environment" and treated real Ghidra decompilation as blocked until run manually there.
That's no longer true for the Linux device-bridge sandbox specifically (still true for the
plain cloud container, which has no access to `octamax/` at all): it has Java, network
egress to github.com/api.github.com/pypi.org (but NOT ports.ubuntu.com, deb.debian.org,
ftp.gnu.org, conda channels — those 403/timeout through the sandbox's proxy), gcc/g++, and
the mounted project folder — enough to build and run headless Ghidra end to end.

### Recipe (portable JDK 21 + Ghidra 12.1.2, built for linux_arm_64, no root)
The sandbox is aarch64 Linux; Ghidra 12.1.2's release zip only ships a `decompile` native
binary for `linux_x86_64`/`mac_arm_64`/`mac_x86_64`/`win_x86_64` — none run on aarch64
Linux (no qemu-user available either). Built it from Ghidra's own bundled source instead:

1. `curl` a portable Temurin JDK 21 tarball (`OpenJDK21U-jdk_aarch64_linux_hotspot_*.tar.gz`
   from the `adoptium/temurin21-binaries` GitHub releases — the Adoptium API itself
   (`api.adoptium.net`) 403s through this proxy, but GitHub releases work) and extract.
2. `curl` `ghidra_12.1.2_PUBLIC_*.zip` from the `NationalSecurityAgency/ghidra` GitHub
   releases and extract. Both downloads complete in ~15s each at ~40MB/s — no need to
   background them (see gotcha below).
3. `Ghidra/Features/Decompiler/src/decompile/cpp/Makefile` only special-cases
   `x86_64`/other(→ treated as 32-bit x86) under Linux — no aarch64 branch. Patch it:
   `ARCH_TYPE=` (empty) and `OSDIR=linux_arm_64` for `ifeq ($(ARCH),aarch64)`. All the
   bison/flex-generated `.cc` files (`grammar.cc`, `pcodeparse.cc`, `slghparse.cc`,
   `slghscan.cc`, `xml.cc`) ship pre-generated in the release zip — no bison/flex needed.
4. Don't build the `decomp_opt` target (the standalone console decompiler) — it pulls in
   `analyzesigs.cc`/`loadimage_bfd.cc` via the Makefile's `EXTRA` wildcard, which need
   `<bfd.h>` (binutils-dev headers, not installed, apt has no root here anyway). The
   target Ghidra's Java side actually shells out to is **`ghidra_opt`**
   (`CORE+DECCORE+GHIDRA` sources only, no bfd dependency). Also blank `BFDLIB=-lbfd` at
   the top of the Makefile (only `libbfd-2.38-system.so` is present, no `-lbfd`-resolvable
   dev symlink, and `ghidra_opt`'s link line doesn't need it once `EXTRA` is out of the
   picture anyway).
5. `make ghidra_opt -j6` — clean build, ~80 objects, done in one pass (~1 min). Copy the
   resulting `ghidra_opt` binary to
   `Ghidra/Features/Decompiler/os/linux_arm_64/decompile` (create that dir; it doesn't
   ship in the zip).
6. Ghidra project ownership: opening a project created by a different OS user throws
   `ghidra.util.NotOwnerException: Project is owned by <original-user>` — the sandbox's
   shell user doesn't match. Fix: `export GHIDRA_JAVA_OPTIONS="-Duser.name=<original-user>"`
   before calling `analyzeHeadless` (the script forwards this env var straight into the
   JVM's `-D` args; overrides `System.getProperty("user.name")`, which is what Ghidra's
   ownership check reads).
7. Then the documented invocation from the `GhidraResolveNN.java` header comments works
   as-is (just point `JAVA_HOME`/`PATH` at the extracted Temurin instead of the
   homebrew paths those comments assume):
   ```
   export JAVA_HOME=<path>/jdk-21.0.12.1+1
   export PATH="$JAVA_HOME/bin:$PATH"
   export GHIDRA_JAVA_OPTIONS="-Duser.name=<original-user>"
   <ghidra>/support/analyzeHeadless ~/Documents/octamax/ghidra_project octamax \
     -process "section_3_MAIN_OS.bin" -noanalysis \
     -scriptPath ~/Documents/octamax/tools -postScript GhidraResolveNN.java
   ```
   Full run (JVM start + project open + 4-function decompile) took **6.4s** — cheap enough
   to just re-run per script, no need to keep a session open.

**Gotcha — nothing backgrounded survives between sandbox shell calls.** `nohup ... &`,
`disown`, and even `setsid` all get reaped the moment the invoking call returns (tested
directly: a `setsid`-detached `sleep 25` was gone with no trace by the next call, ~20s
later). Large downloads/builds have to either complete inside one call's ~45s window, or be
genuinely resumable (`curl -C -`, `make`'s object-file caching) so a second call in the same
shell-less style continues the work rather than restarting it. In practice both the JDK
(196MB) and Ghidra (546MB) downloads and the `ghidra_opt` build finished in a single call
each, so this only matters if egress is slower next time.

Local build products (`jdk-21.0.12.1+1/`, `ghidra_12.1.2_PUBLIC/`) live in the sandbox's own
scratch home, not under `~/Documents/octamax` — they don't persist across sessions and
aren't part of this repo. Re-running the recipe above from scratch takes about 3 minutes.

### Confirmed via real decompilation: FUN_400a1eea's `a0` precondition, and where DIRECT is read

Two things session 3 part 4 could only infer from disassembly are now decompiler-confirmed:

- **`a0` is a genuine implicit input**, not something the function sets up itself: Ghidra's
  decompiler independently flags `byte *in_A0;` as a live-in register and the function's
  very first action is `*in_A0 = ~*in_A0;` (byte-complement-in-place — a flag/state toggle
  at entry, matching the raw `not.b (a0)` instruction that faulted when called cold).
  Corroborates: `FUN_400a1eea` cannot be called without first finding and replicating
  whatever caller sets up `a0`.

- **DIRECT (`TRIGQUANT`, blob-relative `+0x48fe`) has exactly one static/register-relative
  runtime reader in this function**, at `puVar45[uVar20*0x8b0 + 0x48fe]` inside a per-track
  loop (`uVar20` = track 0..7, `0x8b0` = the confirmed per-track stride), itself gated by
  `DAT_800065b6 == 0` (a sub-step counter reset every full step — this block runs once per
  step, not every tick). Full excerpt in `out/ghidra/GhidraResolve26_session4.txt` (search
  `0x48fe`), decompiled C:
  ```c
  if (DAT_800065b6 == '\0') {
    cVar11 = puVar45[uVar20 * 0x8b0 + 0x48fe];      // DIRECT/quantize-index byte, this track
    if (uVar20 * 0x8b0 == 0) {                       // TRACK 0 ONLY — different path, no skip-check
      if (puVar45[CONCAT22(cVar11 >> 7,0x8e55)] == '\0') { iVar15 = (int)(char)puVar45[0x8e53]; }
      else { iVar15 = (int)(char)puVar45[0x48f8]; }
    } else {
      if (cVar11 < 1) goto LAB_400a37f0;             // TRACKS 1-7 — DIRECT(-1) same as index-0: skip
      iVar15 = *(int *)(&DAT_400d80dc + cVar11 * 4);  // else: quantize-index -> step-length table
    }
    if (0 < iVar15) { ... quantize-window / note-reschedule logic, gated on a step counter
                          (_DAT_800065b2) modulo iVar15 ... }
  }
  LAB_400a37f0:
  ```
  Two things worth chasing next session, in order of how cheap they are to check:
  1. **Track 0 is handled asymmetrically from tracks 1-7.** Tracks 1-7 skip this whole
     block identically for DIRECT and quantize-index-0 (`cVar11 < 1`). Track 0 never takes
     that skip at all — it always evaluates a different sign-of-`cVar11` branch reading
     `puVar45[0x8e53]`/`puVar45[0x48f8]` instead. If the user's repro pattern happens to sit
     on track 0, this asymmetry is a very plausible bug site; if not, it's likely unrelated
     and the tracks-1-7 skip path is the one to trace against PLAYS_FREE.
  2. `puVar45[uVar20*0x8b0 + 0x48f9]` (blob-relative `+0x48f9`, i.e. exactly the
     unidentified "`-3(a1)`" field flagged in session 3 part 4) is read a little further
     down in the *same* `DAT_800065b6`-gated block (line ~1117 of the log) — so that
     mystery byte and DIRECT are consumed together here, not in unrelated code paths.
  This block is quantize/reschedule logic, not obviously the "manual trig key" handler
  itself — but it's the confirmed, and only, place DIRECT is read at runtime in the
  function session 3 already identified as the heaviest MIDI-track-state user, so it's the
  strongest concrete lead so far for how DIRECT actually influences sequencer behavior.

Next step: find `FUN_400a1eea`'s real caller (xref search on `0x400a1eea` — not yet done
this session) to learn the real `a0` value/type, so the emulator can call it with a valid
precondition and single-step both the track-0 special case and the tracks-1-7 skip path
with PLAYS_FREE toggled, watching for where behavior actually diverges.


## Session 4 continued (part 2) — SCALE_MODE located, and a correction to the earlier
## FUN_400a1eea reading

New test pair supplied by the user (real hardware exports, same track/pattern/trig as all
prior tests): `test1_PFD_scale` = `test1_PFD` (Plays Free ON, Direct selected) with track
scale mode ALSO set to "per track" in the OT UI. This is the user's confirmed **known-good
repro of the actual bug** (all three preconditions: Plays Free + Direct + per-track scale
mode). Diffed against `test1_PFD` the same way as every prior pair.

### Finding 4: SCALE_MODE is a new byte at blob `+0x48fd` / file `0x4964`, completing the
tight per-track MIDI-trig header

`project.work`/`.strd` differ by 3 bytes (`MIDI_CLOCK_RECEIVE`, `MIDI_TRANSPORT_RECEIVE`
0→1, `MIDI_MODE` 1→0) — incidental setup for a playable repro (feeding it live MIDI), not
scale mode; ignore for this purpose. `bank01.strd`/`.work` differ by exactly 2 content bytes
+ the checksum trailer (delta +2, consistent with 2 bytes each `+1` — Finding 2 holds for a
4th data point). Ran `tools/emu_bankdeserialize.py` on both (now installable in-sandbox:
`pip3 install --user --break-system-packages unicorn`) to get real, firmware-computed
blob-relative offsets rather than hand-mapping file offsets:

```
test1_PFD vs test1_PFD_scale — 2 differing bytes (blob-relative):
  0x48fd (18685): 0x00 -> 0x01
  0x8e55 (36437): 0x00 -> 0x01
```

`+0x48fd` sits **immediately between** the already-confirmed `PLAYS_FREE` (`+0x48fc`) and
`TRIGQUANT`/DIRECT (`+0x48fe`) — resolves the "constant `0x00` spacer, role unknown" byte
flagged in session 3 part 1. The tight per-track/per-pattern MIDI-trig header (file-relative
in this test bank; add the usual bank/pattern offsets for the general case) is now:

```
0x4962: 0xFF          (still unidentified — unchanged across all 5 test projects now)
0x4963: PLAYS_FREE    (0/1)
0x4964: SCALE_MODE    (0/1) -- NEW, this session
0x4965: TRIGQUANT/DIRECT (-1=DIRECT, 0-16=index)
```
(blob-relative, bank 0 / pattern 0: `+0x48fc`/`+0x48fd`/`+0x48fe` respectively, same layout
just shifted, per the file↔blob correspondence established in session 3 part 3.)

### Correction to session 3 part 4 / session 4 part 1: the "track-0 special case" in
### FUN_400a1eea is NOT gated on track index — it's gated on TRIGQUANT==0, for every track

Session 4 part 1's Ghidra decompile of `FUN_400a1eea` rendered a branch as
`if (uVar20 * 0x8b0 == 0)` (read at the time as "only for track 0"). Wrote a second script
(`tools/GhidraResolve27.java`) to pull the **raw disassembly** around every instruction
referencing `0x48fc/0x48fd/0x48fe/0x8e52-0x8e55/0x48f8/0x48f9` in this function, specifically
to check that reading against real asm rather than the decompiler's algebraic rendering —
good thing, because it was wrong. The actual instructions (per-step loop, gated on
`DAT_800065b6==0` same as before):

```asm
tst.b   (DAT_800065b6).l
bne.w   LAB_400a37f0                    ; once-per-step gate, same as before
move.l  #0x8b0,D0
muls.l  D7,D0                           ; D0 = track_index(D7) * 0x8b0
lea     (0x0,A4,D0*1),A0                ; A0 = per-track pointer (A4 = this pattern's blob base)
mvs.b   (0x48fe,A0),D0                  ; D0 = sign-extended TRIGQUANT/DIRECT byte, THIS track
bne.b   LAB_400a3662                    ; if D0 != 0 (i.e. NOT quantize-index-0, incl. DIRECT=-1): skip to the DIRECT/index handling below
move.w  #-0x71ab,D0w                    ; D0==0 path (quantize-index 0): D0.w = 0x8e55 (D0's high word was already 0 from the sign-extended-0 byte above, so this is a compact way to set D0=0x00008e55)
tst.b   (0x0,A4,D0*1)                   ; test blob[A4 + 0x8e55]  <-- the newly-confirmed byte
beq.b   LAB_400a3656
mvs.b   (0x48f8,A0),D2                  ; blob[0x8e55]!=0: D2 = PER-TRACK byte at A0+0x48f8 (4 bytes before PLAYS_FREE)
bra.b   LAB_400a3672
LAB_400a3656:
move.l  #0x8e53,D0
mvs.b   (0x0,A4,D0*1),D2                ; blob[0x8e55]==0: D2 = PATTERN-level byte at blob+0x8e53
bra.b   LAB_400a3672
LAB_400a3662:
tst.l   D0
ble.w   LAB_400a37f0                    ; D0<0 (DIRECT): skip, unchanged from before
lea     (0x400d80dc).l,A1
move.l  (0x0,A1,D0*0x4),D2              ; D0 in 1..16: quantize-index -> step-length table (unchanged)
```

The branch that matters is `bne.b LAB_400a3662` on **the TRIGQUANT byte itself being
nonzero**, not on track index — `D0` had briefly held `track_index*0x8b0` two instructions
earlier, but is fully overwritten by the `mvs.b (0x48fe,A0),D0` load before the branch. The
decompiler's `uVar20 * 0x8b0 == 0` rendering conflated these two unrelated uses of the same
register into a spurious algebraic identity. **This block runs identically for all 8 tracks**
whenever that track's TRIGQUANT byte is exactly `0` (quantize-index 0) — there is no
track-0-only special case. Retracting the "track 0 handled asymmetrically" lead from the
session 4 part 1 handoff; it doesn't hold up against raw disassembly.

What actually happens, correctly stated: when a track's TRIGQUANT is DIRECT (`-1`) OR any
nonzero quantize index (`1..16`), behavior is as already documented (DIRECT skips this
quantize-window block entirely; nonzero index looks up a step-length table). Only when
TRIGQUANT is exactly `0` does **SCALE_MODE (blob `+0x8e55`, a per-pattern-scoped byte
distinct from but correlated with the per-track `+0x48fd` byte found above) decide where
the fallback quantize-window length comes from**: the pattern-shared byte at `+0x8e53` when
SCALE_MODE is 0, or this specific track's own byte at `+0x48f8` when SCALE_MODE is nonzero —
i.e., literally "does the quantize-index-0 default come from the pattern or from this
track", which is exactly what a PER-PATTERN vs PER-TRACK scale-mode toggle should mean
semantically. Good independent confirmation that `+0x8e55` is the real "scale mode" bit
consumed at runtime, not just a coincidentally-correlated flag.

**Open question, not yet resolved**: the per-track `SCALE_MODE` byte found at `+0x48fd` this
session is used **nowhere** in `FUN_400a1eea` — a literal-target search across the whole
function (all 9 candidate offsets, `tools/GhidraResolve27.java`) found zero references to
`0x48fd`. Only the pattern-scoped `+0x8e55` copy is read here. So either `+0x48fd` is
write-only bookkeeping the UI keeps for its own display purposes, or it's read by a
still-unidentified different function — worth an image-wide literal search for `0x48fd`
next (same technique as the earlier `0x48fe` dead-end, so also check for register-relative
access the way `+0x8e55` needed raw disassembly to find, not just a literal-byte scan).

There is also a SECOND, independent read of `+0x8e55` earlier in `FUN_400a1eea`, well before
the per-step loop (`adda.l #0x8e54,A2` / `tst.b (0x1,A2)` at `0x400a1fbc`/`0x400a1fc2` — this
is pattern-load-time-shaped setup code (computes `A2 = bank_base + current_pattern*0x8ed8 +
0x8e54`, i.e. blob-relative `+0x8e54`, then tests the next byte = `+0x8e55`), gating a loop
that seeds a per-track byte array from a lookup table at `0x400aba50` when SCALE_MODE is
nonzero — same "seed a per-track array once, only when a flag is on" shape session 3 already
found for `PLAYS_FREE` seeding `0x80006508[track]` at pattern load. Not fully traced this
session; flagging the shape since it's the same pattern as a confirmed real mechanism.

Full raw disassembly context for every hit saved to
`octamax/out/ghidra/GhidraResolve27_session4.txt`.

### Updated next step
1. Find `+0x48fd`'s actual runtime reader (whole-image search, expect it needs
   register-relative reasoning like `+0x8e55` did — a plain literal-byte scan already missed
   it once for DIRECT and would likely miss it again).
2. Still outstanding from part 1: find `FUN_400a1eea`'s real caller to get a valid `a0` for
   emulation.
3. Once both land, re-run the emulator/decompiler trace with all three flags (PLAYS_FREE,
   SCALE_MODE, DIRECT) set exactly as `test1_PFD_scale` has them (the user's confirmed real
   repro) and compare against single-flag-off variants to find where behavior actually
   diverges into the bug.


## Session 4 continued (part 4) — likely found the manual-trig key handler itself, and a
## coherent end-to-end mechanism for the bug

Continuing directly from part 2/3: whole-image operand scan (`tools/GhidraResolve28.java`,
186,343 instructions, every function in the program) for who reads
`PLAYS_FREE`/`SCALE_MODE`/`DIRECT` (`+0x48fc`/`+0x48fd`/`+0x48fe`) turned up `FUN_4009f3a4`
reading `PLAYS_FREE` and `DIRECT` directly (outside the sequencer's per-step loop) — sitting
inside the `0x4009be00-0x4009f650` region session 3 part 4 already flagged as hosting an
unnamed function tied to MIDI track state, but never pinned down. Decompiled it
(`tools/GhidraResolve29.java`), found its callers (`tools/GhidraResolve30.java`), and
decompiled the biggest caller (`tools/GhidraResolve31.java`). Together these resolve the
"where is `+0x48fd` read?" open question from part 2 and give a coherent, traceable path
from a manual key press through to the DIRECT-consuming logic.

### `FUN_40044584(track, pressOrRelease)` — very likely THE manual-trig key handler

`param_1` = track index (0-15: 0-7 audio, 8-15 MIDI via `param_1-8`), `param_2` = 0 or 1
(rejects anything else). For MIDI tracks, reads a 3-valued byte at exactly
`+0x48fd` (blob-relative, via `_DAT_46c82456 + pattern*0x8ed8 + track*0x8b0 + 0x48fd` —
**this is `SCALE_MODE`, confirmed live-read at runtime**, resolving part 2's open question)
and dispatches on it. For audio tracks the analogous byte lives at a *different* offset in a
*different* per-track region (`+0x55` within a `0x91a`-strided block, not the `0x8b0`-strided
MIDI header) — scale mode is stored per track-type, not at one canonical offset.

Simplified MIDI-track logic (full raw decompile in
`out/ghidra/GhidraResolve31_session4.txt`):

```c
uVar4 = track - 8;
if (_DAT_80000012 != 0) {                        // MIDI-mode gate (role TBD)
  cVar1 = SCALE_MODE[track];                       // 0, 1, or 2 -- see open question below
  if (isRelease) {                                 // param_2 == 0
    if (cVar1 == 2) FUN_4009f3a4();                 // only value 2 does anything on release
    return;                                          // 0 and 1: no-op on release
  }
  // isPress (param_2 == 1):
  if (cVar1 == 1) {
    if (FUN_4009b290(track) == 1)                    // "is this track already active?"
      { FUN_4009f3a4(track); goto setKeyBit; }        // already active -> re-trigger path
    // else falls through to FUN_4009b5c8(track) below (not yet active -> normal start)
  } else if (cVar1 != 2) goto setKeyBit;             // cVar1==0: skip straight to setKeyBit
  FUN_4009b5c8(track);                                // "normal" trig-start (not decompiled yet)
  setKeyBit: _DAT_460d1794 |= (1 << track);
  return;
}
/* _DAT_80000012 == 0: entirely different path -- direct MIDI note-on/off scheduling via
   FUN_40005030/FUN_40042d1c/FUN_4004271c. Not the bug's precondition (PF+Direct+ScaleMode
   presumably requires the _DAT_80000012 != 0 branch); not traced further this session. */
```

`FUN_4009b290(track)` is a one-line accessor: returns `DAT_80006500[track]` (the
already-documented MIDI mute/active array) — i.e. **"is this track already active/playing
right now?"** So for `SCALE_MODE == 1` (our confirmed test value — see open question,
this may not be literally "per track") on a **press**, `FUN_4009f3a4` only fires when the
track is *already active*; otherwise the normal start path (`FUN_4009b5c8`) runs instead.
This is exactly the shape of a manual **re-trigger while already playing** — which lines up
with Plays Free being a precondition (a Plays Free track is the kind you'd press again while
it's still sounding, since it isn't locked to the step grid).

### The likely end-to-end bug mechanism, now traceable start to finish

```
FUN_40044584(track, press=1)                          -- manual key press, MIDI track
  SCALE_MODE[track] == 1                               -- per-track scale mode (our repro)
  FUN_4009b290(track) == 1                              -- track already active
    -> FUN_4009f3a4(track)
         gated on PLAYS_FREE[track] != 0                -- Plays Free ON (our repro)
         reads DIRECT[track]
           if DIRECT == -1 (selected, our repro) OR pattern-loaded-flag != 1:
             -> CLEARS DAT_80006500/0x800064d0/0x800064f0/0x800064e0/... (the track's
                active/playing state arrays) entirely
             -> FUN_400a539c(track)  (resets more per-track note/voice scratch state,
                                       sets a "release" flag to 1 for that track)
             -> FUN_40000c3c(0x460d17ae, ...)  (posts an event/message -- the same
                                                  "wake consumer task" primitive used
                                                  elsewhere for async work, per session 3)
           else:
             -> just flips bits in _DAT_80006680/_DAT_80006682 (the SAME bitmask pair
                FUN_400a1eea's per-step quantize-window logic reads/clears)
```

Read plainly: with all three of the user's confirmed preconditions active, a manual
re-trigger of an already-playing MIDI track routes into the DIRECT-selected branch of
`FUN_4009f3a4`, which **wipes the track's active-state bookkeeping and posts a generic
event, instead of taking the bit-flip path that (via `_DAT_80006680`/`_DAT_80006682`)
`FUN_400a1eea`'s step engine is set up to consume.** That's a plausible, concrete mechanism
for "manual trig silently does nothing / stops the track" under exactly the reported
conditions — though **whether the clear-and-post-event branch is actually wrong, or is
supposed to properly restart the note through some effect of the posted event that just
hasn't been traced yet, is not yet confirmed.** `FUN_40000c3c(0x460d17ae, ...)`'s effect and
`FUN_4009b5c8`'s behavior (the "normal start" path this whole thing is an alternative to)
are the natural next things to decompile.

### Open question: is SCALE_MODE really binary, or a 3-way enum?

`FUN_40044584` dispatches on `SCALE_MODE` having 3 distinct values (`0`, `1`, `2`), each with
different behavior, on both audio and MIDI tracks. Our confirmed diff only exercised a
`0x00 -> 0x01` transition (the user's "per track" setting). It's not yet established whether
the OT UI's scale-mode setting genuinely has a 3rd state (`2`) reachable some other way (a
3-position menu?), or whether `1` and `2` are actually the same conceptual "per track" mode
reached via different code paths for unrelated reasons, or something else. Worth asking
the user directly what OT UI options exist for this setting, and/or exporting a 3rd test
variant to see if a byte value of `2` is reachable at all. This matters because our repro's
observed behavior (value `1`, gated through `FUN_4009b290`'s activity check) may not be the
same path a value-`2` project would take (value `2` skips the `FUN_4009b290` gate entirely
on press, and behaves differently on release too).

### Next step
1. Decompile `FUN_4009b5c8` (the "normal start" path `FUN_40044584` takes instead of
   `FUN_4009f3a4` for tracks that aren't already active) and `FUN_40000c3c`'s target at
   `0x460d17ae` — need both to know what SHOULD happen on a normal re-trig, to confirm the
   DIRECT branch in `FUN_4009f3a4` is actually the divergence point and not intentional.
2. Resolve the value-`1`-vs-`2` SCALE_MODE question (ask the user about the real UI, or get
   a 3rd test export).
3. `_DAT_80000012` (gates whether this whole code path runs at all) and `DAT_8000004c`
   (checked in the `else` branches) are both new, unidentified globals worth naming.


## Session 4 continued (part 5) — user correction: it's not "scale mode", it's the manual-
## trig response mode (ONE/ONE2/HOLD); and the actual bug mechanism is now traceable

Two corrections from the user, both important:

1. **The 3-valued byte at blob `+0x48fd` (file `0x4964`) found in part 2/4 is NOT scale
   mode.** It's Elektron's own manual-trig-key **response mode** setting, with three named
   options: **"ONE"** (retrigger the track every press — what all our test projects are set
   to), **"ONE2"** (toggle: one press starts, the next press stops), and **"HOLD"** (plays
   only while the key is held down). Renaming this field `TRIG_MODE` going forward (still
   at the same confirmed offset — the location and the fact that it's read in `FUN_40044584`
   are unaffected, only its *meaning* was misidentified). "Scale mode" as a concept may not
   exist at this offset at all; if the user's OT project also has a real scale/track-length
   setting, it lives somewhere else, not investigated this session.

2. **A Plays-Free MIDI track manually triggered should start running even when the OT's
   overall sequencer transport is stopped.** This is expected/correct behavior, not a bug —
   and it directly explains why `_DAT_800065b8` matters here.

### `_DAT_800065b8` is very likely per-pattern "sequencer actually stepping" state, not a
### static "loaded" flag

Whole-image write search (`tools/GhidraResolve32.java`): all 3 writes to `_DAT_800065b8`
are `move.l Dn,(0x800065b8).l` — full 32-bit writes — and **all 3 sites are inside
`FUN_400a1eea`** (the per-step sequencer engine), not at pattern-load time as session 3
assumed ("MIDI pattern loaded" flag). Given it's written by the step engine itself and
tested as `!= 1` (not a simple zero check), the better working theory is that it reflects
whether the sequencer is actively stepping this pattern right now — which would explain
exactly why the user's point (2) matters: **when the overall transport is stopped, this
would plausibly read something other than `1`**, and both functions below treat
`_DAT_800065b8 != 1` as equivalent to DIRECT being selected. Not fully confirmed (would
need to watch it live across a transport stop/start), but it now has a much more precise
role than "loaded".

### The bug, traced concretely: `FUN_4009f3a4`'s restart path is missing the activation step
### that `FUN_4009b5c8` (the real "start" function) performs

`FUN_40044584`'s `TRIG_MODE == 1` ("ONE") press-handler logic (part 4) calls
`FUN_4009b290(track)` — "is this track already active?" (`DAT_80006500[track]`) — and
branches: **already active → `FUN_4009f3a4(track)`; not active → `FUN_4009b5c8(track)`.**
Decompiled `FUN_4009b5c8` this round (the "not active, so start it" path) and it is
unmistakably the Plays-Free start sequence: for MIDI tracks it checks PLAYS_FREE first
(non-Plays-Free tracks bail to a different function, `FUN_4009b95a`, not yet examined),
reads DIRECT, and:

```c
if ((cVar5 != -1 /* not DIRECT */) && (_DAT_800065b8 == 1 /* sequencer stepping */)) {
    // normal quantized case: just flip the step-engine bitmask, defer to FUN_4009b95a
    ...
    FUN_4009b95a();
    return;
}
// DIRECT selected, OR sequencer not actively stepping (transport stopped): full start --
(&DAT_46c77b89)[track] = DAT_800065be;    // save current pattern/bank
... [a large block: copies pitch/note/timing scratch state, initializes per-track buffers]
FUN_400a539c(track);                        // per-track note/voice reset
(&DAT_80006500)[track] = 1;                 // <-- ACTIVATES the track
FUN_40000c3c(0x460d17ae,&DAT_400abac8);     // posts the same event as FUN_4009f3a4
```

Compare directly against `FUN_4009f3a4`'s equivalent branch (part 3), same gating condition
(`cVar1 == -1 || _DAT_800065b8 != 1`), reached when the track is **already active**:

```c
(&DAT_80006500)[track] = 0;                 // <-- DEACTIVATES the track (opposite!)
... [clears the other per-track state arrays to 0]
FUN_400a539c(track);                        // same call
FUN_40000c3c(0x460d17ae,&DAT_400abac8);     // same event
```

**Both functions call the identical pair `FUN_400a539c(track)` +
`FUN_40000c3c(0x460d17ae,...)` in this branch. `FUN_4009b5c8` additionally does the full
state re-initialization and sets the track active (`DAT_80006500[track] = 1`) before that
pair; `FUN_4009f3a4` only clears state and sets it inactive (`= 0`) before the same pair.**
Given "ONE" mode is supposed to *restart* an already-playing track — i.e. conceptually
stop-then-immediately-start-again — `FUN_4009f3a4`'s branch does the "stop" half and never
does the "start" half. The track goes silent and stays silent, instead of restarting.

This lines up with every reported precondition and the user's point (2) simultaneously:
DIRECT selected and/or the transport being stopped both land in the exact same "clears
instead of restarts" branch (they're OR'd together in the gating condition), and Plays Free
is required simply because it's what makes `FUN_4009f3a4`/`FUN_4009b5c8` reachable for MIDI
tracks at all (non-Plays-Free tracks take the `FUN_4009b95a` path entirely). **This is now
the leading, well-evidenced candidate for the actual bug mechanism**, not just a lead.

### Open items
- Exact `TRIG_MODE` value mapping: `1 = ONE` is confirmed (user-stated + test data). Value
  `2`'s dispatch (press → unconditional `FUN_4009b5c8`; release → `FUN_4009f3a4`) reads more
  like **HOLD** (press starts, release stops) than "ONE2", contrary to the initial guess
  last round. Value `0` (press → unconditional `FUN_4009b5c8`, no active-check; release →
  no-op) doesn't obviously match either remaining name from the code alone — a toggle
  ("ONE2") would need state persisted *across* separate press events, which might live
  inside `FUN_4009b95a` (not yet decompiled) rather than in this dispatcher. Worth a 3rd
  test export (`TRIG_MODE` = the untested value) to pin this down definitively, same
  methodology as every other field this project has confirmed.
- `FUN_4009b95a` (the non-Plays-Free / normal-quantized path both functions defer to) is
  still undecompiled — likely holds the ONE2 toggle logic if that guess above is right.
- Not yet proposed a fix — the natural one (`FUN_4009f3a4`'s branch should call
  `FUN_4009b5c8` instead of/after clearing, rather than only clearing) needs the full
  register/stack context checked before treating it as safe; flagging as the shape of the
  fix, not a confirmed patch.


## Session 4 continued (part 6) -- DAT_80000012 identified as project-level "MIDI_MODE"
## setting (likely bug precondition #3); FUN_40044584 ground-truthed via raw disassembly;
## HOLD (=2) confirmed exactly; value 0 still unresolved; FUN_4009b95a is an empty stub

Two threads pursued: (1) fully ground-truth the TRIG_MODE dispatch in `FUN_40044584` against
raw disassembly (not just decompiled C, given the earlier decompiler-misrender lesson from
part 3), and (2) chase down `DAT_80000012`, the single global that gates whether the entire
TRIG_MODE-based dispatch even runs for MIDI tracks -- a strong candidate for the real
"scale mode = per track" bug precondition #3, since our confirmed per-track TRIG_MODE byte
turned out not to be scale mode at all (see part 5).

### `DAT_80000012` = a project-state boolean sourced from a text config key literally named
### "MIDI_MODE"

`DAT_80000012` has exactly **one write site** in the whole image (found earlier via
`GhidraResolve32`'s write-scan): inside `FUN_400866c4`, a ~7100-byte function that is
unmistakably a **text-based project/state-file line parser** (it reads lines byte-by-byte,
splits on `=`, and switches on section headers `SAMPLE`, `SETTINGS`, `STATES`, `META`, then
on a long chain of `KEY_NAME` string compares within the `STATES` section: `RELOAD_BANK`,
`PASTE_PATTERN`(bank index), `ARRANGEMENT`, `ARRANGEMENT_MODE`, `MIDI_MODE`, `RENAME_PART`,
...). This is very likely the parser for the project's saved/live-state text blob (separate
from the binary bank-file format this project has focused on so far).

The `MIDI_MODE` case, decompiled:
```c
iVar2 = FUN_40013e14(local_12d, s_MIDI_MODE_400b7e8b);   // strcmp against "MIDI_MODE"
if (iVar2 == 0) {
    ...
    iVar2 = FUN_400144c4(puVar3);      // parse the value after '='
    if (bVar10) {
        if (iVar2 < 0) {
            _DAT_100b14de = 0;
            _DAT_80000012 = 0;
        } else {
            _DAT_100b14de = iVar2;
            _DAT_80000012 = iVar2;
            if (0 < iVar2) {            // clamp to boolean
                _DAT_100b14de = 1;
                _DAT_80000012 = _DAT_100b14de;
            }
        }
    }
}
```
So `DAT_80000012` is a **boolean project setting, loaded once from a `MIDI_MODE=` line in a
text state/config blob**, clamped to 0 or 1. It is read (never written) everywhere else,
always as the outer gate in `FUN_40044584`:
```c
tst.l (0x80000012).l
beq.w 0x40044710      // MIDI_MODE == 0: entirely different code path (direct MIDI-out
                       // scheduling, does NOT read TRIG_MODE at all)
// falls through when MIDI_MODE != 0: reads TRIG_MODE (+0x48fd) and dispatches through the
// FUN_4009b5c8 / FUN_4009f3a4 pair analyzed in part 5 -- i.e. THIS is the whole codepath
// the bug lives in.
```
**This is a strong candidate for bug precondition #3.** The internal firmware name
("MIDI_MODE") doesn't obviously match the user's own description ("track scale mode = per
track"), but functionally it fits perfectly: it's a single global boolean, set once from
project state (not per-step, not per-track), and it gates whether the ONE/ONE2/HOLD
TRIG_MODE dispatch (where the actual bug lives) is reachable at all vs. an entirely
different, separately-implemented direct-MIDI-scheduling path when it's off. Whatever the
UI calls it, this is almost certainly the flag the user was describing -- flagging the name
mismatch explicitly rather than asserting the UI label, since that hasn't been directly
confirmed (would need a project text-state export to see the literal `MIDI_MODE=` line and
correlate it against the known-good/known-bad UI setting).

### `FUN_40044584` ground-truthed via raw disassembly (not just decompiled C)

Given the part-3 lesson about a decompiler misrender, the TRIG_MODE dispatch was re-checked
against raw disassembly end to end (`GhidraResolve33`). It confirms the decompiled structure
from part 5 exactly, with one addition -- the MIDI-track press dispatch (D3=track 8-15,
D4=press(1)/release(0), D0=TRIG_MODE byte sign-extended) is:

```
press (D4==1):
  D0 == 0  -> unconditionally call FUN_4009b5c8 (start), NO active-state check first
  D0 == 1  -> call FUN_4009b290(track) [active?]; if active -> FUN_4009f3a4 (the buggy
              clear-only path); if not active -> FUN_4009b5c8 (start)
  D0 == 2  -> unconditionally call FUN_4009b5c8 (start), NO active-state check first
              (same call as D0==0 -- these two share the exact same call site)
release (D4==0):
  D0 == 0  -> no call (falls straight to generic tail/no-op)
  D0 == 1  -> no call
  D0 == 2  -> call FUN_4009f3a4 (stop)
```

**Value `2` matches HOLD exactly and unambiguously**: press always (re)starts, release
always stops. Confirmed, not just inferred.

**Value `1` is bulletproof as ONE** (hardware test-data ground truth from every export this
project has). Its dispatch is the odd one out: it's the only value that bothers to check
active-state via `FUN_4009b290` before deciding whether to start or hand off to the
clear-only stop path. Conceptually this is exactly "restart if already playing, start if
not" -- i.e. correct ONE intent -- but the "restart" half is implemented as a bare stop
(`FUN_4009f3a4`'s clear-without-reactivate branch, per part 5) instead of stop-then-start,
which is the bug.

**Value `0` remains unresolved.** By elimination it should be ONE2 (toggle: first press
starts, second press stops), but the dispatch code doesn't match a toggle at all -- it just
unconditionally calls `FUN_4009b5c8` on every press with no active-state check, and does
nothing on release. Checked whether `FUN_4009b5c8` itself might contain the toggle/active
check (in case it was hiding there instead of in the dispatcher) -- it does not: its full
decompile (recovered from the `GhidraResolve32` log) has no active-state read anywhere;
it either defers to `FUN_4009b95a` (quantized/non-DIRECT case) or unconditionally does the
full re-init-and-activate sequence (DIRECT-or-not-stepping case), regardless of whether the
track was already active. So value 0's press behavior would, if anything, always sound like
a correct **restart-every-press**, not a toggle -- more like a second flavor of "ONE" than
"ONE2". Possibilities, none confirmed: (a) value 0 is simply never emitted by the real UI
(reserved/default-only) and ONE2 is actually value... there is no 4th value though, so this
seems unlikely; (b) ONE2's toggle-off check happens further upstream, before
`FUN_40044584` is even called (e.g. the caller only invokes this dispatcher on transitions,
suppressing the "off" press before it gets here) -- not yet checked; (c) our identification
of which named mode maps to which value is simply wrong in some way not yet apparent from
static analysis alone. **Next concrete step to resolve this: a third real test export with
TRIG_MODE set to ONE2 specifically (not just "the untested byte value"), so the byte value
can be read directly via the emulator deserializer the same way every other field in this
project has been confirmed** -- guessing further from code alone isn't productive past this
point.

### `FUN_4009b95a` is a literal empty stub

Both `FUN_4009b5c8`'s and `FUN_4009f3a4`'s "quantized / not DIRECT / sequencer stepping"
branches defer to `FUN_4009b95a()` after flipping bits in `_DAT_80006680`/`_DAT_80006682`.
Decompiled in full this session: `void FUN_4009b95a(void) { return; }` -- a true no-op, 10
bytes (entry + rts, effectively). This rules it out as a hiding place for ONE2 toggle logic
or any other quantized-path state machine; the real work in the quantized case is entirely
the bit-flip that happens just before the call, consumed later by `FUN_400a1eea`'s per-step
engine. Likely vestigial (a hook point that no longer does anything in this firmware
version) rather than a bug.

### Also fully confirmed this round: `FUN_4009b290`

```c
uint FUN_4009b290(uint param_1) {
  if ((int)param_1 < 0) return _DAT_800065b8;
  return (uint)(byte)(&DAT_80006500)[param_1 & 0xf];
}
```
Simple active-state getter: `DAT_80006500[track]` per-track (the same array `FUN_4009b5c8`
sets to 1 on activate and `FUN_4009f3a4`'s buggy branch sets to 0 on deactivate), or
`_DAT_800065b8` itself when called with a negative sentinel. No new information beyond
part 5's earlier partial view, but now the full body is confirmed rather than summarized.

### Open items (updated)
- **Precondition #3 identity**: `DAT_80000012`/"MIDI_MODE" is now the strongest candidate,
  but the internal name doesn't confirm the UI label the user used ("scale mode = per
  track"). Not confirmed against a project state-text export yet.
- **TRIG_MODE value 0**: still unresolved; needs a 3rd real test export with ONE2 selected,
  same methodology as every other confirmed field.
- Fix shape is unchanged from part 5: `FUN_4009f3a4`'s DIRECT-or-not-stepping branch clears
  and deactivates a track but never re-runs the reactivation sequence `FUN_4009b5c8`
  performs in its equivalent branch. Still not proposed as a concrete patch pending full
  register/stack verification.


## Session 5 (Claude Code, on the user's Mac) — toolchain moved to native macOS; Open Item 1
## resolved (dead end); handoff-5's "SCALE_MODE not in the trig chain" claim is WRONG;
## step-engine quantize handler fully mapped

Environment change: this session runs as Claude Code directly on the user's Apple-Silicon Mac
(OS user `kyoti_m4`), not the old Cowork Linux sandbox. Consequences:

### Toolchain (replaces the from-source `ghidra_opt` build recipe in the Session 4 intro)
- **Ghidra**: Homebrew formula at `/opt/homebrew/Cellar/ghidra/12.1.2/` →
  `analyzeHeadless` = `/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless`.
  The official `mac_arm_64` native `decompile` binary ships and works
  (`.../libexec/Ghidra/Features/Decompiler/os/mac_arm_64/decompile`) — **no from-source
  build needed**, exactly as handoff-5 predicted.
- **JDK 21**: `/opt/homebrew/Cellar/openjdk@21/21.0.12/libexec/openjdk.jdk/Contents/Home`.
- Invocation that works (headless run ≈ 4 s, JVM + project open + scripts):
  ```
  export JAVA_HOME=/opt/homebrew/Cellar/openjdk@21/21.0.12/libexec/openjdk.jdk/Contents/Home
  export PATH="$JAVA_HOME/bin:$PATH"
  /opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless \
    ~/Documents/octamax/ghidra_project octamax -process "section_3_MAIN_OS.bin" \
    -noanalysis -scriptPath ~/Documents/octamax/tools -postScript GhidraResolveNN.java
  ```
  `GHIDRA_JAVA_OPTIONS="-Duser.name=kyoti_m4"` is **not** needed (running as the project
  owner). The "Could not determine local host name" and `DuplicateFileException` benign
  errors from the old sandbox do **not** appear here.
- **macOS TCC gotcha (cost ~an hour at session start)**: `~/Documents` is TCC-protected and
  the process that actually touches the FS is Anthropic's `claude` binary
  (`com.anthropic.claude-code`, separately Developer-ID-signed), **not** VS Code. Granting
  VS Code Full Disk Access does nothing. Fix: add
  `~/.vscode/extensions/anthropic.claude-code-<ver>-darwin-arm64/resources/native-binary/claude`
  to Full Disk Access (path is version-stamped → re-add after each extension update), or run
  `claude` from Terminal.app instead. Test project folders (`test1_*`) also exist as copies
  on `~/Desktop` (readable without the grant).

Scripts this session: `tools/GhidraResolve36.java` … `GhidraResolve38.java`. Raw logs:
`out/ghidra/GhidraResolve3{5,6,7,8}_session5.txt`.

### Open Item 1 RESOLVED — `FUN_4009a670` is a load-time bounds-CLAMP, not on the trig path

Decompiled in full (`GhidraResolve36`). It walks all 8 audio tracks (stride `0x91a`), then all
8 MIDI tracks (stride `0x8b0`), then the pattern-level fields, **clamping every field to its
legal range** and returning the count of corrections made. Callers (all load/init-time, none
runtime):
- `FUN_4008cebc` — the bank deserializer, calls it once on the freshly-loaded blob.
- `FUN_4009abdc` — the pattern **initializer** ("new empty pattern" defaults), tail-calls it.
- `FUN_40025770` — bulk "validate all 16 patterns of a bank" loop (`adda.l #0x8ed8,A2`).

**Not reachable from `FUN_40044584` / the manual-trig path at all.** Dead end for the bug
mechanism — but it hands us authoritative field ranges (blob-relative, per track for the
per-track ones):
| offset | field | clamp range |
|---|---|---|
| `+0x48f8` | per-track quantlen | `[2, 0x40]` |
| `+0x48f9` | (unnamed, MIDI) | `[0, 6]` |
| `+0x48fa` | (unnamed, MIDI) | `[0, 0x1e]` |
| `+0x48fb` | (unnamed, MIDI) | `[-1, 1]` |
| `+0x48fc` | **PLAYS_FREE** | `[0, 1]` |
| `+0x48fd` | **TRIG_MODE** | `[0, 2]` (⇒ 3 states ONE/ONE2/HOLD, consistent) |
| `+0x48fe` | **DIRECT/TRIGQUANT** | `[-1, 0x10]` |
| `+0x48ff` | (unnamed, MIDI) | `[0, 1]` |
| `+0x8e50` | pattern length (u16) | `[2, 0x400]` |
| `+0x8e52` | pattern scale idx | `[0, 6]` |
| `+0x8e53` | pattern fallback quantlen | `[2, 0x40]` |
| `+0x8e54` | pattern "scale offset" (see below) | `[0, 6]` |
| `+0x8e55` | **SCALE_MODE** | `[0, 1]` — **binary at pattern level** (settles part-4's "is it 3-valued?" — no) |
| `+0x8e56` | (pattern) | `[-1, 0x10]` |
| `+0x8e57` | (pattern) | `[0, 3]` |
| `+0x8e58` | (pattern, i32) | `[0x2d0, 0x1c20]` else `0xb40` |

`FUN_4009abdc` init defaults: pattern `+0x8e50=0x10, +0x8e52=2, +0x8e53=0x10, +0x8e54=2,
+0x8e55=0, +0x8e56=0, +0x8e57=0, +0x8e58=0xb40`; per-track (both types) first 8 bytes
`{0x10, 2, 0, 0xff, 0, (u8)_DAT_80000094, 0, 0}`.

### CORRECTION to handoff-5 Open Item 2 — `FUN_4009b5c8` **does** read SCALE_MODE (`+0x8e55`)

Handoff-5 states `+0x8e55` "is not read anywhere in the manual-trig-key dispatch chain
(`FUN_40044584`, `FUN_4009b5c8`, `FUN_4009f3a4`)". **`FUN_4009b5c8` reads it.** It was
already visible in the `GhidraResolve32` decompile and is now confirmed against **raw
disassembly** (`GhidraResolve38`, `0x4009b6d0`–`0x4009b704`, in the function's full-init
tail which Ghidra has split off as a separate `candidate_4009b64e` listing):
```asm
; D1 = 0x400e21e0 + bank*0x9b340 ;  D6 = current pattern ;  D3 = track index (0..15)
move.l #0x8ed8,D2 ; muls.l D6,D2 ; move.l D1,D0 ; add.l D2,D0
movea.l D0,A0 ; adda.l #0x8e54,A0        ; A0 = pattern-block + 0x8e54
lea (-0x7fff99c2).l,A1                    ; A1 = 0x8000663e  (&DAT_8000663e)
tst.b (0x1,A0)                            ; <-- SCALE_MODE, pattern-level +0x8e55
beq.b .normal
  move.l #0x91a,D0 ; muls.l D3,D0 ; add.l D2,D0   ; D0 = track*0x91a + pattern*0x8ed8
  movea.l D1,A0 ; lea (0x51,A0,D0*1),A0           ; A0 = blob + bank + that + 0x51
.normal:
move.b (A0),(0x0,A1,D3*1)                 ; DAT_8000663e[track] = *A0
```
The whole-image operand scan (`GhidraResolve35`) missed it because `+0x8e55` is reached as
`[regA + 0x8e54] + 1` — register-relative, the documented blind spot (3rd time now:
DIRECT read, the earlier `+0x8e55` read in `FUN_400a1eea`, and this one).

So SCALE_MODE's effect on the trig path: in `FUN_4009b5c8`'s **full-init branch only**, it
picks the *source byte* copied into `DAT_8000663e[track]`:
- SCALE_MODE == 0 (Normal): pattern-level byte `+0x8e54`.
- SCALE_MODE != 0 (per-track): per-track byte at `blob + pattern*0x8ed8 + track*0x91a + 0x51`.
  **Note the `0x91a` (audio) stride applied to a raw track index that is 8–15 for MIDI** —
  for MIDI track 8 that resolves to blob-relative `+0x4921` (inside MIDI-track-0's sub-block
  but not at a named field). Present identically in raw asm and decompile — not a misrender.
  Looks anomalous (audio stride on a MIDI index); could itself be a firmware bug or the
  per-track scale byte for MIDI genuinely lives in a `0x91a`-strided shared array. **Unverified.**

`FUN_4009f3a4` still does **not** reference `+0x8e55` in either branch (re-confirmed against
full decompile + raw asm, `GhidraResolve37`).

### `DAT_8000663e` fully characterised — it's a per-track "scale offset", consumed by the
### step engine's quantize handler

`DAT_8000663e[track]` is written by exactly two places:
1. `FUN_4009b5c8` full-init branch (seed, SCALE_MODE-gated, above).
2. `FUN_400a1eea` (the per-step engine), inside its once-per-step quantize handler
   (`DAT_800065b6 == 0` gate), in the `_DAT_80006680` "soft (re)start at boundary" sub-block
   — with the **same SCALE_MODE gate**:
   ```c
   if (puVar45[0x8e55] == '\0')  *scaleoff = puVar45[0x8e54];               // Normal: pattern byte
   else                          *scaleoff = puVar45[track*stride + 0x51/0x48f9];  // per-track byte
   cVar = tbl[*scaleoff] - tbl[DAT_8000663d];      // tbl = DAT_400aba50[]
   DAT_800065db/cb[track] = clamp(...);
   if (tbl[DAT_8000663d] - tbl[*scaleoff] < 1) { DAT_80006508[track] = 1; FUN_400a539c(track); }  // REACTIVATE
   else                                          _DAT_80006684 |= bit;                              // pending
   _DAT_80006680 &= ~bit;
   ```
   (`DAT_8000663d` is a separate single byte one address below — a global "current/target
   scale offset". `DAT_400aba50` is a small translation table, same one part 2 flagged.)
It is **read** only via the on-stack pointer table `FUN_400a1eea` builds (`lea 0x8000663e,An
; move.l An,(slot,SP)` at `0x400a292a` / `0x400a2970` / `0x400a3cb4` — these are *address
stashes*, not content reads; the content reads are the `*pcStackNN` derefs above).

### The step engine's quantize handler is **entirely skipped when DIRECT is selected**

`FUN_400a1eea`'s per-track quantize block (both the `_DAT_80006680` soft-restart and the
`_DAT_80006682` soft-stop sub-blocks) begins:
```asm
mvs.b (0x48fe,A0),D0      ; DIRECT byte, this track
bne.b  .handleNonZero     ; != 0
 ... (D0==0, quantize-index 0): SCALE_MODE picks +0x8e53 vs +0x48f8 as the window length ...
.handleNonZero:
tst.l D0
ble.w  LAB_400a37f0       ; D0 == -1  (DIRECT selected)  -> SKIP the whole handler for this track
 ... (D0 in 1..16): table lookup ...
```
So with DIRECT selected, the step engine does **nothing** for the track's soft
restart/stop — it neither papers over nor re-creates the missing reactivation.

### Where this leaves Open Item 2 (still open, but sharper)

On paper the bug should reproduce on **DIRECT + PLAYS_FREE + ONE + MIDI_MODE alone**,
independent of SCALE_MODE:
- `FUN_4009f3a4` takes its clear branch because `cVar1 == -1` (DIRECT) — deactivates, posts
  event, never reactivates, never touches `_DAT_80006682`.
- `FUN_400a1eea` skips the track (DIRECT) — no recovery.
- SCALE_MODE is absent from both paths; its only role is choosing the *seed value* of
  `DAT_8000663e[track]` at first start, and `DAT_8000663e` is only consumed by the
  step-engine handler that DIRECT already causes to be skipped.

Yet the user has confirmed on real hardware that pattern-scale = **Per Track** is required
(A1 Per-Track shows the bug, A2 Normal doesn't, all else identical). Unreconciled. Leading
hypotheses now, none verified:
1. The anomalous `track*0x91a + 0x51` MIDI seed read in `FUN_4009b5c8` (audio stride on a
   MIDI index) lands on a byte whose value flips some *other* downstream decision when
   SCALE_MODE is per-track — needs the emulator to see what's actually at `+0x4921…+0x49xx`
   for the repro banks and who else reads it.
2. There is a second SCALE_MODE consumer still hidden behind register-relative addressing
   (the operand scan has now demonstrably missed `+0x8e55` reads **twice**). A dedicated
   pass that walks every `adda/lea #0x8e5x` / `#0x8e40..0x8e60` immediate and every
   `(disp,An)` with `disp` in that window, across the whole image, is warranted before
   trusting "only these N functions read it".
3. `_DAT_800065b8` ("stepping") and/or `DAT_800065b6` (sub-step gate) are computed
   differently under per-track scale, changing which `FUN_4009f3a4` branch is taken. Not
   traced.
4. Mapping error somewhere (e.g. "trigger quantization = Direct" is not `+0x48fe == -1` in
   the per-track-scale case, because `+0x48fe`'s meaning shifts with scale mode — cf. the
   `+0x8e53`-vs-`+0x48f8` swap the step engine already does for quantize-index 0).

### Next steps (revised priority)
1. **Extend `emu_bankdeserialize.py` into an actual execution harness** for `FUN_4009f3a4`
   and the `FUN_400a1eea` quantize handler: load a real repro bank blob into RAM at
   `bank_blob_base`, set `DAT_800065bd/be` (bank/pattern), `_DAT_800065b8`, then call
   `FUN_40044584(8, 1)` twice and watch `DAT_80006500[8]` / `DAT_80006508[0]` /
   `_DAT_80006680/82/84` / `DAT_8000663e`. Run it once with `test1_PFD_scale` (bug repro)
   and once with `test1_PFD` (per-track scale OFF) and diff the RAM trace — this is the
   direct way to see what SCALE_MODE actually changes, rather than more static staring.
2. Whole-image **register-relative** scan for `+0x8e54/+0x8e55` (immediates `0x8e40..0x8e60`
   in `adda/lea/addi/movea`, plus `(disp,An)` displacements in that window). The operand
   scan is confirmed unreliable for this offset.
3. Decompile `FUN_4009f2f8` (called by `FUN_4009f3a4`'s MIDI clear branch, `param = track-8`)
   — small, not yet looked at; the only sub-call in the buggy branch besides `FUN_400a539c`
   and `FUN_40000c3c` that hasn't been read.
4. Still outstanding from part 6: 3rd hardware export with **TRIG_MODE = ONE2** to resolve
   value `0`.
5. Fix shape unchanged; still blocked on items 1–2.


## Session 5 part 2 — [SUPERSEDED BY PART 3 — the `+0x48fd`/ONE2 story below is NOT the
## reported bug; kept for the byte-level facts and the harness build-out only]
## ~~BUG REPRODUCED IN EMULATION. Root cause is the `+0x48fd` dispatch byte~~

Built `tools/emu_trigbug.py` — a Unicorn execution harness (reuses `emu_bankdeserialize.py`'s
file-read hook to deserialize a real bank, writes the blob to the real base `0x400e21e0`,
sets the ~8 globals the trig path reads, then calls the real `FUN_40044584(track, press)`
**twice** to simulate re-pressing an already-playing track's trig key). Run log:
`out/ghidra/emu_trigbug_session5.txt`. Notes on the harness:
- Unicorn m68k faults (`UC_ERR_EXCEPTION`) on the privileged `move SR,Dn` / `move #imm,SR`
  / `move Dn,SR` critical-section guards. Handled at runtime: a `UC_HOOK_CODE` callback
  detects those encodings (`w & 0xFFC0 in {0x40C0,0x42C0,0x44C0,0x46C0}`) and advances PC
  past them. Safe for a single-threaded trace.
- Stubbed to `rts`: `FUN_40000c3c` (event post), `FUN_40010bc8` (MIDI send), `FUN_400108b0`.
  Left real: `FUN_4009b290`, `FUN_4009b5c8`, `FUN_4009f3a4`, `FUN_4009b95a`, `FUN_400a539c`,
  `FUN_4009f2f8`.
- `FUN_40044584` uses a **different** blob pointer + pattern index than the b5c8/f3a4/1eea
  trio: it reads the blob base from the pointer at `_DAT_46c82456` and the pattern index
  from `DAT_100b14d0` (byte), NOT `0x400e21e0` / `DAT_800065bd`/`be`. Harness sets all of
  them (`[0x46c82456] = 0x400e21e0`, `[0x100b14d0] = 0`, `[0x800065bd/be] = 0`,
  `[0x80000012] = 1` MIDI_MODE, `[0x800065b8]` = stepping flag).

### Ground truth from deserializing all 5 real test banks (`scratchpad/insp_banks.py`)

Pattern 0, MIDI track 0 (= track index 8) header bytes, and pattern-level `+0x8e55`:

| project | +0x48fc PLAYS_FREE | +0x48fd | +0x48fe DIRECT | +0x8e55 SCALE_MODE |
|---|---|---|---|---|
| test1_PF_        | 1 | **0** |  0 | 0 |
| test1_PFD        | 1 | **0** | -1 | 0 |
| test1_PFD_scale  | 1 | **1** | -1 | **1** |
| test1nil         | 0 | **0** |  0 | 0 |
| test1nil_scale   | 0 | **0** |  0 | **1** |

Key: `test1nil_scale` has pattern SCALE_MODE `+0x8e55 = 1` but `+0x48fd = 0` — so **`+0x48fd`
is NOT a mirror of the pattern scale-mode bit.** Only `test1_PFD_scale` (the confirmed
hardware repro) has `+0x48fd = 1`. `test1_PFD` vs `test1_PFD_scale` still differ by exactly
2 bytes: `+0x48fd` 0→1 and `+0x8e55` 0→1.

### The emulation result (identical for `stepping = 1` and `stepping = 0`)

```
test1_PFD  (+0x48fd = 0):
  press #1:  DISP -> B5C8(start)                          -> active[8] = 1
  press #2:  DISP -> B5C8(start)                          -> active[8] = 1   (restarts, keeps playing) OK
test1_PFD_scale  (+0x48fd = 1):
  press #1:  DISP -> B290(inactive) -> B5C8(start)        -> active[8] = 1
  press #2:  DISP -> B290(ACTIVE)   -> F3A4(retrig)
                    -> F2F8(note-off sweep) -> 4x midisend -> A539C(reset) -> C3C(event)
             -> active[80006500][8] = 0  AND  active[80006508][0] = 0        (fully de-activated) BUG
```

Matches the user's behavioural description exactly: after the buggy re-press the track is
fully de-activated (both the audio-indexed `DAT_80006500[8]` and the MIDI-indexed
`DAT_80006508[0]` go to 0), so it neither sounds nor advances — "only the step-1 C ever
fires, the step-2 C# never does."

### Root cause, now concrete and demonstrated

`FUN_40044584`'s MIDI-track press handler dispatches on the byte at
`blob + pattern*0x8ed8 + (track-8)*0x8b0 + 0x48fd`:
- **`+0x48fd == 0`**: `if (cVar1 != 0)` is false → falls straight through to
  **`FUN_4009b5c8(track)` unconditionally, with no active-state check**. A re-press of an
  already-playing track therefore re-runs the full start/re-init → the track restarts. **No bug.**
- **`+0x48fd == 1`**: calls `FUN_4009b290(track)` first; **track already active → `FUN_4009f3a4(track)`**,
  whose DIRECT branch (`+0x48fe == -1` ⇒ `cVar1 == -1`) clears `DAT_80006500`/`DAT_80006508`
  and the other per-track arrays, sweeps note-offs (`FUN_4009f2f8`), calls `FUN_400a539c`,
  posts the event — and **never re-activates**. Track goes silent and stays silent. **Bug.**
- `+0x48fd == 2` (HOLD): press → unconditional `FUN_4009b5c8`; release → `FUN_4009f3a4`.
  (Not the bug — press always restarts.)

So the **necessary-and-sufficient trigger is `+0x48fd == 1` together with `+0x48fe == -1`
(DIRECT) and `+0x48fc == 1` (PLAYS_FREE)**. `_DAT_800065b8` (stepping / transport) does
**not** matter — DIRECT alone forces `FUN_4009f3a4` into the clear-only branch.
`+0x8e55` (pattern SCALE_MODE) is **not** in the mechanism at all — its only role is
picking the `DAT_8000663e` seed source (Session 5 part 1), and that value is only consumed
by the step-engine quantize handler which DIRECT causes to be skipped. It is a **passenger**
that happens to co-vary with `+0x48fd` in the `test1_PFD_scale` export.

### RESOLVED (user-confirmed): `+0x48fd` IS TRIG_MODE; the mapping is 0=ONE, 1=ONE2, 2=HOLD

User: *"It was somehow set to ONE2. I missed that."* So `test1_PFD_scale` differs from
`test1_PFD` by **two** independent UI changes — pattern scale → Per Track (`+0x8e55`, a **red
herring**, plays no role) and the MIDI track's trig mode → **ONE2** (`+0x48fd`, the actual
cause). Confirmed TRIG_MODE value map (corrects parts 4–6, which had guessed `1 = ONE`):

| `+0x48fd` | mode | `FUN_40044584` press behaviour | release |
|---|---|---|---|
| 0 | **ONE**  | unconditional `FUN_4009b5c8` (restart every press) | no-op |
| 1 | **ONE2** | active? → `FUN_4009f3a4` : `FUN_4009b5c8` | no-op |
| 2 | **HOLD** | unconditional `FUN_4009b5c8` | `FUN_4009f3a4` |

ONE2 is the only mode that calls `FUN_4009f3a4` on *press*, and only when the track is
already playing — i.e. a manual **re-trigger while playing**. With Direct selected that
lands in `FUN_4009f3a4`'s clear-only branch → silence. Open Item 2's "why does scale mode
matter" puzzle is fully dissolved: it never did. Open Item 3 ("value 0 isn't a toggle") too:
value 0 is ONE, not ONE2.

**Updated bug preconditions (all 4 required, superseding the handoff's list):**
1. MIDI track.  2. Plays Free (`+0x48fc == 1`).  3. Trig quant = Direct (`+0x48fe == -1`).
4. **Trig mode = ONE2** (`+0x48fd == 1`).  *(Not pattern scale; not `_DAT_800065b8`.)*
Plus `_DAT_80000012` / MIDI_MODE must be on for the whole TRIG_MODE dispatch to run.

### (historical) the ambiguity that led here — what is `+0x48fd` and why did it flip?

`+0x48fd` is Elektron's per-MIDI-track manual-trig **response-mode** byte (part 5: ONE / ONE2
/ HOLD), clamped `[0,2]` by `FUN_4009a670`. The emulated dispatch says:
- value 0 → "restart every press" — behaviourally this is **ONE**.
- value 1 → "if already playing, hand to `FUN_4009f3a4`" — the buggy one; behaviourally a
  **toggle-ish / ONE2**.
- value 2 → HOLD (confirmed earlier).
This is the **opposite** of the part-4/5 assumption that `1 = ONE`. Under the emulated
behaviour, `0 = ONE` and `1 = ONE2`, which also dissolves the part-6 "value 0 doesn't act
like a toggle" puzzle (it isn't ONE2, it's ONE).

**Open question for the user** (the last thing blocking a clean writeup): when `test1_PFD_scale`
was exported from `test1_PFD`, which OT UI setting(s) changed? If the MIDI track's trig mode
was set to **ONE2** at that time, everything is consistent and the bug is simply "ONE2 +
Plays Free + Direct MIDI track: manual re-trigger stops instead of toggling/restarting". If
*only* "pattern scale → Per Track" was changed, then enabling Per-Track scale has a side
effect of also writing `+0x48fd = 1`, and the two are genuinely linked in the firmware's
save path (would need to trace the pattern-settings writer, `FUN_4008a6fc`/serializer side).

### Candidate fix — 1 byte, validated in the harness

The bug is entirely in `FUN_40044584`'s ONE2 press dispatch calling `FUN_4009f3a4`
(stop-only) where it needs a restart. Fixing `FUN_4009f3a4` itself is wrong — HOLD *release*
also calls it and must stop. So fix the call site:

```
             0x400446a2   beq.b 0x400446c8      67 24     "ONE (+0x48fd==0): unconditional FUN_4009b5c8"
  patch ->   0x400446a2   bra.b 0x400446c8      60 24     make ONE2 fall through to the same call
```

**One byte: file offset `0x442a2` (= `0x400446a2 - 0x40000400`), `0x67` → `0x60`.**
Effect: ONE2 press now always routes to `FUN_4009b5c8` (start/restart every press) — exactly
like ONE — instead of `active ? FUN_4009f3a4 : FUN_4009b5c8`. HOLD is unaffected (HOLD press
already lands on `0x400446c8`; HOLD release is on the separate `D4==0` path). ONE and ONE2
become behaviourally identical.

Harness validation (`out/ghidra/emu_trigbug_fix_session5.txt`), `active[8]` after presses 1/2/3:

| bank (track 8, pattern 0) | mode | stock | patched |
|---|---|---|---|
| test1_PFD        | ONE  | `1 1 1` | `1 1 1` (unchanged) |
| test1_PFD_scale  | ONE2 | `1 0 1` ← **bug** | `1 1 1` ← **fixed** |
| test1_PF_ (stepping=0) | ONE, not Direct | `1 1 1` | `1 1 1` (unchanged) |
| test1_PF_ (stepping=1) | ONE, not Direct | `0 0 0`* | `0 0 0`* |

*`test1_PF_` has DIRECT=0 (quantize-index 0), so `FUN_4009b5c8` takes the "soft" path
(`_DAT_80006680 |= bit`, defer to step engine) and never sets `active[8]` directly — the
harness doesn't run `FUN_400a1eea` so it stays 0. Correct behaviour, not a regression.

**Caveat / open question for the user:** this makes ONE2 press-on-playing *restart* instead
of *toggle-off*. If ONE2 is meant to be "retriggerable one-shot" (the reading that makes
this a bug at all), that is exactly right and ONE2==ONE is acceptable. If ONE2 is genuinely
meant to *toggle* (press on / press off) and the only defect is that the toggle-off path is
a hard clear rather than a clean stop, then the fix instead needs `FUN_4009f3a4`'s clear
branch to stop the track *cleanly enough that the step engine or transport can restart it* —
a bigger change needing free-space for a trampoline (no room to inline stop-then-start at
the call site: the pushed `FUN_4009f3a4` arg can't be reused without also widening the
shared `addq.l #4,SP` at `0x400446d0`, which other press paths reach with only one arg).

### Audio tracks: same prerequisites, NO bug (user-confirmed) — why

`FUN_40044584`'s audio path (`param_1 < 8`) has the **same** `cVar1==1 → already-active →
FUN_4009f3a4` dispatch shape as MIDI, reading the mode byte from the audio struct at
`+0x55` (within the `0x91a` stride) instead of `+0x48fd`. Two candidate reasons audio is
immune, not yet disambiguated:
1. The audio dispatch is gated behind `(DAT_8000004c & 1) != 0`; when that bit is 0, a
   manual audio-track trig goes to `FUN_4003f3a8(track, track+0x18, 0x7f)` entirely — it
   never touches `FUN_4009f3a4`/`FUN_4009b5c8`. (MIDI, by contrast, is gated on
   `_DAT_80000012` / MIDI_MODE, which the repro has set.)
2. Even if `FUN_4009f3a4` does run for an audio track and de-activates it, an audio track
   is locked to the step grid — the next sequencer step re-triggers it from the pattern's
   own trig data, so the missing reactivation is invisible. A **Plays Free** MIDI track has
   no such safety net (that is *why* PLAYS_FREE is a precondition), so the de-activation
   sticks.
Worth a quick check of `DAT_8000004c`'s meaning and the audio `+0x55` byte's value in the
test exports, but this doesn't change the MIDI root cause.

### Next steps
1. Get the user's answer on the `+0x48fd` question above (ONE2 vs a scale-mode side effect).
2. Extend the harness to drive `FUN_400a1eea` a few steps after the re-press (needs the `a0`
   precondition + more globals) to show C then C# firing for `test1_PFD` and nothing for
   `test1_PFD_scale` — a full behavioural repro, not just the active-flag proxy.
3. Draft the `FUN_4009f3a4` patch and validate it in `emu_trigbug.py`.


## Session 5 part 3 — user disclosed two things that overturn part 2's conclusion; the REAL
## root cause is a MIDI stride bug in `FUN_4009b5c8`'s per-track-scale read

Two facts from the user:
1. *"It was somehow set to ONE2 [`+0x48fd == 1`]. I missed that."* — so `test1_PFD_scale`
   differs from `test1_PFD` by **two** UI changes, not one.
2. **On real hardware the bug reproduces with Plays Free + Direct + per-track scale for
   ALL THREE trig modes (ONE, ONE2, HOLD)** — trig mode is *not* a precondition.
3. Audio tracks with the identical settings are fine.

Part 2's `+0x48fd`/ONE2 → `FUN_4009f3a4` story is therefore **not the reported bug** (it's
trig-mode-specific, which #2 rules out). It's a real secondary code smell — keep it filed,
but it is not this. Part 2's byte-level facts still stand: `+0x48fd` = TRIG_MODE
(0=ONE/1=ONE2/2=HOLD), confirmed; `test1_PFD_scale` has `+0x48fc=1, +0x48fd=1, +0x48fe=-1,
+0x8e55=1`.

### The real mechanism — `FUN_4009b5c8` reads the MIDI per-track scale byte with the AUDIO stride

`FUN_4009b5c8`'s full-init branch, SCALE_MODE(`+0x8e55`)-gated seed (Session 5 part 1 quoted
this and under-weighted it). Raw asm `0x4009b6f2`–`0x4009b704`:
```
D3 = param_1 (track; 8..15 for MIDI)   D2 = pattern*0x8ed8   D1 = 0x400e21e0 + bank*0x9b340
if (blob[pattern-block + 0x8e55] != 0):          # SCALE_MODE = "Per Track"
    D0 = D3 * 0x91a                               # <-- AUDIO track stride, on a MIDI index
    A0 = D1 + D0 + D2 + 0x51                       # = blob + track*0x91a + 0x51
DAT_8000663e[D3] = *A0                             # D3 = 8..15  ->  writes DAT_80006646[0..7] (aliased)
```
For an **audio** track (`param_1` 0–7) `blob + track*0x91a + 0x51` is that audio track's real
scale byte — and `FUN_400a1eea`'s audio loop reads the exact same expression, so audio is
self-consistent → **audio has no bug** (matches fact #3).

For a **MIDI** track (`param_1` 8–15) the audio stride `0x91a` on index 8 lands at blob
`+0x4921` — `0x21` bytes into MIDI track 0's *trig data*, not any scale field — and it
drifts a further `0x6a` per track. The correct MIDI read (what `FUN_400a1eea`'s MIDI loop
uses) is `blob + pattern-block + (track-8)*0x8b0 + 0x48f9`. `FUN_4009b5c8` never added the
MIDI branch for this one read.

Harness proof (`emu_trigbug.py` → `scale_evidence()`, log `out/ghidra/emu_trigbug_scale_session5.txt`):

| bank | SCALE_MODE | `FUN_4009b5c8` reads | → `DAT_80006646[0]` after press | `DAT_400aba50[idx]` |
|---|---|---|---|---|
| test1_PFD       | 0 (Normal)   | pattern byte `+0x8e54` = 2 | **2** (valid) | `[2]` = 6  ✓ |
| test1_PFD_scale | 1 (Per Track)| `blob[+0x4921]` = **0xff** | **255** ← out of range | reads 0x3fc past a 13-entry table = garbage |

`DAT_400aba50` = `int32[13]` = `{3,4,6,8,12,24,48,96,48,24,12,6,0}` (step-length table,
valid indices 0–12).

### Why all four preconditions are needed, and why trig mode is not

- **Per Track** (`+0x8e55 == 1`): only then does `FUN_4009b5c8` do the buggy audio-stride
  read. Normal scale uses pattern `+0x8e54` (a valid small index).
- **Direct** (`+0x48fe == -1`): needed *twice over*. (a) `FUN_4009b5c8`'s soft path
  (`cVar5 != -1 && stepping`) returns **before** the corrupting seed write — only the
  Direct/full-init path reaches it. (b) In `FUN_400a1eea`'s MIDI per-step loop, a Direct
  track hits `if (cVar11 < 1) goto LAB_400a37f0` and **skips the block that would recompute
  `DAT_80006646[track]` from the correct `+0x48f9` source** — so the garbage is never healed.
- **Plays Free**: the gate that lets a MIDI track reach `FUN_4009b5c8` at all (non-PF →
  `FUN_4009b95a` stub).
- **Trig mode**: `FUN_4009b5c8` never reads `+0x48fd`. ONE / ONE2 / HOLD all call
  `FUN_4009b5c8` on the first manual trig of a PF+Direct track → all three corrupt
  `DAT_80006646[track]` identically. ✓ matches fact #2.

### Why "C fires, C# never does"

`FUN_400a1eea` has a second MIDI loop (uVar20 = 8..15, `pcVar34 = &DAT_80006646` incrementing)
whose per-track step-advance gate is:
```c
if (DAT_80006508[track]==1 && DAT_400aba50[DAT_80006646[track]] <= (byte)(subcounter+1)) {
    ... advance to next step, emit its note ...
    if (SCALE_MODE!=0) DAT_80006646[track] = blob[(track-8)*0x8b0 + 0x48f9];   // heal -- but only AFTER an advance
}
```
- Normal: `DAT_400aba50[2] = 6 <= subcounter+1` → true once per 6 ticks → advances, step 2's
  C# fires.
- Bug: `DAT_400aba50[255]` = a huge garbage int → `huge <= (byte)(...)` is **always false**
  → the track never advances past step 1, and the heal line (which needs a successful
  advance) never runs. **Permanent stall after the first note.** The initial C is emitted by
  the manual-trig start path itself; step 2's C# needs this loop, which is wedged.

### The fix — in `FUN_4009b5c8`, not the dispatcher

`FUN_4009b5c8`'s per-track-scale seed must use the MIDI stride/offset for MIDI tracks:
`blob + pattern-block + (param_1-8)*0x8b0 + 0x48f9` instead of `+ param_1*0x91a + 0x51`.
No room to do the different address math in the 18 bytes at `0x4009b6f2`–`0x4009b704`
(and `D3` can't be clobbered — it indexes the destination store at `0x4009b704`), so this
needs a trampoline to a code cave. **Patch not yet drafted.** The old part-2 one-byte
`+0x48fd` patch is **withdrawn** — it addressed the wrong path.

`emu_trigbug.py`'s `scale_evidence()` gives a direct pass/fail for any candidate:
after a press, `DAT_80006646[0]` must be a valid index (0–12), not 255.

### Still worth doing
- Full `FUN_400a1eea` run in the harness for the end-to-end C/C# behavioural repro (the
  static trace above is strong but not executed).
- Confirm the drifting per-track offset for MIDI tracks 1–7 (`blob + track*0x91a + 0x51`).
- A hardware export with Plays Free + Direct + per-track scale + trig mode **ONE** would
  nail fact #2 against the byte layout (all current exports with the bug config happen to
  also be ONE2).


## Session 6 (Claude Code) — the fix: drafted (`tools/patch_trigscale.s`), emulator-validated,
## built into TWO flashable images (A: stock+fix, B: +MAXOLYDIAN mods), reproducible-packaged,
## drift confirmed for all 8 MIDI tracks, and a flash-failure playbook written. Not yet flashed.
## [SUPERSEDED by Session 7: Build A flashed to a real Octatrack MKI 2026-08-28 — fix confirmed, no regression.]

### The patch

Detour + code cave, exactly as Session 5 predicted (no room in place — 18 bytes at
`0x4009b6f2`–`0x4009b703`, `D3` live as the store index at `0x4009b704`).

- **Detour** `0x4009b6f2` (6 bytes, replaces `move.l #0x91a,D0` precisely): `jmp 0x400d7b00`.
  The 3 instructions after it (`0x4009b6f8`–`0x4009b703`, 12 bytes) are left orphaned —
  unreachable, and nothing branches into them: the SCALE_MODE==0 path is the
  `beq 0x4009b704` at `0x4009b6f0`, which lands *past* them with `A0` already set to
  `&blob[pattern-block + 0x8e54]` from `0x4009b6e0` (unchanged Normal-scale behaviour).
- **Cave** `0x400d7b00` (62 bytes, in the `0x400d64da..0x400d7c3c` zero cave `build.py`
  already uses; `patch_arp` ends at `0x400d7224`, so there's a wide gap):
  ```
  moveq #7,D0 ; cmp.l D3,D0 ; blt .midi          ; 7 < track -> MIDI (8..15)
  ; audio (0..7): unchanged -- A0 = D1 + D3*0x91a + D2 + 0x51 ; jmp 0x4009b704
  .midi: D0 = D3-8 ; D6 = 0x8b0 ; D0 *= D6 ; D0 += D2 ; D0 += 0x48f9
         A0 = D1 ; A0 += D0 ; jmp 0x4009b704       ; = blob + pat*0x8ed8 + (trk-8)*0x8b0 + 0x48f9
  ```
  `D6` (pattern index) is dead past `0x4009b6d6`, reused as the multiply scratch — ColdFire
  `muls.l` wants a register source, and `D0` holds the running product. `0x48f9` is folded
  into `D0` with `addi.l` because ColdFire indexed addressing only has an 8-bit displacement
  (`lea (0x48f9,A0,D0)` won't assemble; `lea (0x51,A0,D0)` in the audio arm is fine).
  Assemble: `m68k-elf-as -mcpu=5407` (cfv4), same as every other stub.

### Validation (`tools/emu_trigbug.py`, `scale_evidence()` extended; `FIX_SCALE` patch-dict)

`out/ghidra/emu_trigbug_fix_session6.txt`:

| bank | SCALE_MODE | STOCK `DAT_80006646[0]` after press | FIXED | audio `DAT_8000663e[0]` stock/fixed |
|---|---|---|---|---|
| test1_PFD       | 0 | 2 (valid, `aba50[2]=6`)        | 2 (unchanged — Normal path bypasses the detour) | 0x00 / 0x00 |
| test1_PFD_scale | 1 | **255** (OOB → garbage step len → stall) | **2** (valid, `aba50[2]=6`) | 0x00 / 0x00 |

Also ran the harness with `IMG_PATH` pointed at the real built `out/mainos.bin` (fix
compiled in, no patch dict): `test1_PFD_scale` → `DAT_80006646[0] = 2`, identical to
`test1_PFD`; audio untouched. `python3 tools/build.py` applies cleanly (EXPECT guard
`203c0000091a` at `0x4009b6f2`; cave verified free).

### Open item 3 — DONE. `emu_trigbug.py drift_check()` (`--drift`), log appended to
`out/ghidra/emu_trigbug_fix_session6.txt`.

The buggy `track*0x91a + 0x51` read lands a different amount past each MIDI track's real
scale byte (`(track-8)*0x8b0 + 0x48f9`): drift = `0x91a - 0x8b0 = 0x6a`/track, so the buggy
offset for MIDI trk N is `0x48f9 + 0x28 + N*0x6a` (blob-rel, bank/pat 0):

| MIDI trk | buggy off | correct off | buggy − correct |
|---|---|---|---|
| 0 | 0x4921 | 0x48f9 | +0x28 |
| 1 | 0x523b | 0x51a9 | +0x92 |
| 2 | 0x5b55 | 0x5a59 | +0xfc |
| … | … | … | +0x6a each |
| 7 | 0x88d7 | 0x85c9 | +0x30e |

Emulated what-if (RAM blob forced `+0x48fc=1`/`+0x48fe=0xff` on all 8 MIDI tracks, press
each): STOCK → `DAT_8000663e[8..15]` all 255 (these test tracks are empty so every drifted
offset happens to read 0xff = "no trig"; a populated track would give assorted non-index
garbage). FIXED → every MIDI track gets its own valid `+0x48f9` byte (2). No audio regression.

### Flash prep — DONE. TWO builds, both carrying the identical always-on fix (no PERSONALIZE gate).

**Build A — fix on otherwise-stock 1.40C** (version field untouched, stays `1.40C`):
- `tools/build_trigscale_only.py` (new) applies just the detour+cave to stock →
  `out/mainos_trigscale_only.bin` (72 bytes vs stock: 2 hunks).
- `.syx`: `out/OCTATRACK_OS1.40C_PLAYSFREEFIX.syx` (EFT `-c 3 …` **no `-V`**; checksums ok;
  section 3 decompresses byte-identical; only 0x4009b6f2 / 0x400d7b00 differ from stock).
- `.bin`: `out/OCTATRACK_PLAYSFREEFIX.bin` (`make_bin.py out/elek_pffix.bin`; ELUP ok).
- JSON: `sysex/patches/playsfreefix-r1.json` (2 hunks, `display_version: null`).
- `apply_patch.py -p playsfreefix-r1.json` → sha-identical to the EFT build (`a2f5d5bd…`).

**Build B — fix + the octamax mods** (historical: at the time, `tools/build.py` bundled
the fix with Maxolydian's mods into `OCTATRACK_OS1.40C_MAXO_R13`). *This is no longer
part of OT Kyoti FW — during the 2026-09 reorg the octamax mod tooling moved to
`tools/attic/` and the `maxolydian-*.json` hunk files were removed. See
`reference/upstream-notes.md`.* The Bug-1 fix itself is unchanged and ships in every
current Kyoti build.

Tooling notes:
- `sysex/gen_patch_json.py` (new) diffs stock vs a built image and emits the hunk JSON +
  hashes; `--trigscale-only` / `--name` / `--display-version keep` for build A.
- `apply_patch.py` now skips `-V` when `display_version` is null/empty (keeps the stock
  version field byte-identical — that's how build A's `.syx` stays "otherwise stock").
- `FLASHING.md`: build A documented, plus a step-by-step hardware repro/fix/
  regression test (PLAYS FREE + Direct + Per-Track scale, step-1/step-2 MIDI trigs, manual
  trig, sequencer stopped → stock plays only C, fixed plays C then C#).

### Failure playbook — DONE (`FLASHING.md` §6)

`FLASHING.md` §6 "If flashing fails, or the flashed OS misbehaves" covers: always-recover-first
(STARTUP MENU → MIDI UPGRADE → stock `.syx`); classify into (a) transfer never completed →
transport, not the patch (slow SysEx, re-copy CF, re-verify the local file with
`elektron-firmware-tool -i` / `bin_decode.py`); (b) flash finished but OS won't boot → flash A
if B was flashed (isolates the fix from the mods); if A also bricks, the fix fails on real
silicon → code change needed; (c) OS runs but fix inactive / regression → re-run the repro,
check A vs B. Plus a "Debugging the fix" checklist (D6 liveness, orphaned bytes, cave
executability at 0x400d7b00 — fallback 0x400d7300, ISA, bisect via a no-op cave).

### Still open

- Flash a build to the real unit and confirm the stall is gone (`FLASHING.md` "Testing the
  MIDI manual-trig fix"). Expect the user to try build A first. Recovery net: hold [FUNC] on
  boot → STARTUP MENU → [TRIG 3] MIDI UPGRADE → send
  `downloads/extracted/OCTATRACK_OS1.40C.syx`.
- (nice-to-have) Full behavioural `FUN_400a1eea` run in the harness — deferred; the function
  is huge (A0 struct live-in, `[A0+0x6632]` word, many globals + sub-step counters, calls
  FUN_4009cf4c/d1e8/e884/33968/4a668). The static trace + `scale_evidence`/`drift_check`
  already pin the mechanism and the fix.
- (nice-to-have) Hardware export with trig mode **ONE** (all bug-config exports so far ONE2).
- The withdrawn part-2 ONE2 oddity — only if the user reports it independently.


## Session 7 (Claude Code) — HARDWARE CONFIRMED. Build A (stock 1.40C + Plays-Free fix)
## flashed to a real Octatrack **MKI** unit; the MIDI manual-trig stall is gone and no
## regression observed. The fix is now hardware-validated.

**2026-08-28** — the user flashed `out/OCTATRACK_OS1.40C_PLAYSFREEFIX.*` (Build A: fix on
otherwise-stock 1.40C, no MAXOLYDIAN mods) to an actual **Octatrack MKI**. Result: the unit
boots normally, OS version still reads `1.40C` (Build A leaves the version field untouched
by design), and the previously-reproducible bug — a Plays-Free MIDI track with trig quant
Direct + pattern scale Per Track stalling after step 1 on a manual trig — **no longer
occurs**. Works without issue; no regression reported.

Notes:
- Elektron ships the same OS 1.40C image for the Octatrack MKI and MKII, so the RE (done
  against the MKII `.syx`) and the fix apply to both. This is the first on-hardware
  confirmation and it happened on an **MKI**.
- Only Build A has been flashed. Build B (`OCTATRACK_OS1.40C_MAXO_R13.*` = fix + MAXOLYDIAN
  mods) is unchanged and still carries the identical fix; its non-fix mods were already
  hardware-confirmed in earlier sessions, but the R13 bundle as a whole has not been
  re-flashed since adding `patch_trigscale`. If flashing B later, the §6 playbook still
  applies (flash A to isolate the fix from the mods).
- The emulator-green-≠-hardware-good caveat is now discharged for the fix itself (Build A).

### Status roll-up

- MIDI manual-trig bug: **root-caused, fixed, built, emulator-validated, and hardware-confirmed
  on MKI (Build A).** Done.
- Deferred nice-to-haves (full `FUN_400a1eea` behavioural harness; a trig-mode-ONE hardware
  export; the withdrawn part-2 ONE2 oddity) remain deferred — none are needed now that the
  fix is confirmed on real hardware.

---

# Session 8 (2026-08-28) — NEW BUG: MIDI-track LFO SETUP knobs transmit CC on the wrong channel

## The bug (Elektronauts thread 87588, reported 2019 on MKI OS 1.30B)

Editing **SPD / DEP on a MIDI track's LFO SETUP page** makes the Octatrack transmit the
6 LFO CCs (**CC 28–33** = LFO Speed 1-3 / Depth 1-3) on the MIDI channel assigned to the
**twin audio track** (audio track N), not the MIDI track's own channel.
- Without MIDI loopback: stray CC 28–33 on audio track N's channel (confirmed with a MIDI
  monitor by sezare56).
- With loopback: those CCs come back in and drive **audio track N's** LFO depth/speed →
  the audio track audibly cuts out. This is how the user originally noticed it.
- Only the **LFO SETUP** page, only **twin tracks**, not bidirectional, audio/MIDI channels
  must differ. Normal LFO (MAIN) page reportedly unaffected.
Target for our fix: **OS 1.40C** (behaviour assumed to persist; not yet reproduced on 1.40C).

## Manual facts (OS 1.40C MKII manual, `tool-results/otmk2.txt`)

- Audio LFO: **LFO MAIN** page = SPD1-3, DEP1-3 (§11.4.7). **LFO SETUP** page (FUNC+LFO) =
  per-LFO PMTR, WAVE, MULT, TRIG, SPD, DEP (§11.4.8). SPD/DEP are **mirrored** on both pages.
- MIDI LFO MAIN / MIDI LFO SETUP "work just like" the audio ones (§15.4.5/6). MIDI LFO PMTR
  can target the MIDI track's own MAIN-page params (note/vel/len/PB/AT/CC1-10).
- Appendix C.7 (audio CTRL CHANGE MAPPINGS): CC 28–33 = "LFO param #1-6 (Speed 1-3, Depth
  1-3)", flagged **TRN + REC** — but transmit only when PROJECT>MIDI>CONTROL>**AUDIO CC OUT**
  = EXT / INT+EXT (default INT = no send). Explicit opt-in.
- Appendix C.8 (MIDI MODE CTRL CHANGE MAPPINGS): "the auto channel **responds to**…" CC 28–33
  = "MIDI LFO param #1-6" — listed **REC only**. **There is no "MIDI CC OUT" setting.** So per
  the manual a MIDI track has no business *transmitting* CC 28–33 when you touch an LFO knob.

## Agreed fix direction (user, this session)

**Suppress** CC transmission from the MIDI LFO SETUP page's SPD/DEP encoders (rather than
"fix the channel"): the emitted CCs are undocumented, ungated, wrong-channel, and nobody can
rely on them. Kills both the no-loopback noise and the loopback glitch. Verify first whether
LFO MAIN transmits at all / on which channel; if it legitimately does on the MIDI track's own
channel, make SETUP match MAIN instead of pure-suppress.

## RE progress (Ghidra headless, `tools/GhidraLfo*.java`, project already analyzed, 2194 fns)

Load base 0x40000400. `_DAT_80000012` = audio(0)/MIDI(≠0) selector. `DAT_100b14cc` = current
track, `DAT_100b14cf` = displayed pattern, `DAT_80000000`/`80000003` = active track / sounding
pattern, `_DAT_46c82456` = live project blob base, pattern stride 0x18b2.

### Page plumbing — CONFIRMED
- **LFO SETUP page** shared audio+MIDI. Title strings: `"MIDI LFO SETUP"` @0x400b47d5,
  `"LFO SETUP"` @0x400b47da (tail of the same bytes).
- **Page descriptor** @~0x400bc030: `+0x24`=title(0x400b47da), `+0x54`=open FUN_40058390,
  `+0x58`=teardown FUN_40055de0, `+0x5c`=renderer **FUN_400572e8**, `+0x80`=FUN_4003ad8c.
- **FUN_40058390** = page-open. Installs the param table via
  `FUN_400326d4(&DAT_400d37f6 [audio] | &DAT_400d4162 [MIDI], 0xffffffff, &DAT_400bbc72)`.
- **Param-descriptor structs**: audio LFO page @**0x400d37f6**, MIDI LFO page @**0x400d4162**.
  Each holds **12 params**: 0-5 = LFO MAIN (SPD1-3,DEP1-3), 6-11 = LFO SETUP (PMTR,WAVE,MULT,
  TRIG,SPD,DEP). 6-byte labels start at struct+0x16 (0x400d380c / 0x400d4178). Struct also
  has min array @+0x6a, range @+0x9a, and FUN_400a6994 inputs @+0x18a/+0x18e.
- Renderer FUN_400572e8: audio blob offsets 0x90482 / 0x8f072 / 0x8f3e2; MIDI 0x90512 /
  0x8f268 / 0x8f26b. LFO **designer waveform** editors (no MIDI TX): FUN_400381c8 (set step),
  FUN_40037f40 (interp mask), FUN_400383e4 (rotate), FUN_40038148 (invert).

### Encoder-edit path — PARTLY MAPPED
- Main UI event loop = **FUN_40061a94**. Param-page encoder turn = **case '?'** (event 0x40):
  ```
  iVar17 = (pcVar6[2] % 6) + DAT_400a7280[pcVar6[2] / 6] * 6;   // <-- param-index remap table
  uVar10 = DAT_80000000; if (_DAT_80000012 != 0) uVar10 += 8;   // MIDI mode -> track idx +8
  FUN_40054cd8(uVar10, iVar17, delta);                          // apply
  ```
  `DAT_400a7280` (small per-page base table) NOT yet dumped — **next step**.
- **FUN_40054cd8(track, paramIdx, value)** = generic param apply.
  - `page = paramIdx/0x24`, `sub = paramIdx%6`.
  - `if (track < 8)` audio branch: writes blob, **NO MIDI transmit** (only FUN_4009da20).
  - `else` MIDI branch (track-8 = midi slot): writes blob @0x8f162 region, then
    **`FUN_4009eec8(midiSlot, paramIdx, value, 0)`** then `FUN_4009da20(track)`.
- **FUN_4009eec8(midiSlot, paramIdx, value, 0)** = MIDI-track param → live MIDI out. Acts
  ONLY for `paramIdx == 0x12` (PB → 0xE0), `0x13` (AT → 0xD0), `0x14..0x1d` (CC1..CC10 →
  0xB0, CC# from CTRL setup table). Channel = `*(byte)(… midiSlot*0x24 + 0x40171442) - 1 & 0xf`
  = the **MIDI track's own** channel. Does NOT itself handle LFO params (0x1e+).
- Other transmit siblings: **FUN_400438fc**, **FUN_40055008** (both call FUN_4009eec8);
  **FUN_400a14f0** (called from case 'H' with the *audio* active-track index, forces
  `FUN_40054cd8(track+8, 0x14+i, …)` and can emit a raw `chan|0xB0` via FUN_40010bc8).
- MIDI byte-out primitive: **FUN_40010bc8(nbytes, *bytes)**, 59 refs.

### Where the bug most likely is (hypotheses, unproven)
1. `DAT_400a7280[page]` for the LFO SETUP page remaps `iVar17` into the **0x14..0x1d** window,
   so FUN_40054cd8's MIDI branch → FUN_4009eec8 treats an LFO SPD/DEP edit as a CC1..CC10
   send. (Would explain "CC" but not obviously "CC 28-33" / "audio channel".)
2. A transmit sibling (FUN_400438fc / FUN_40055008 / FUN_400a14f0) resolves the channel from
   an **audio-track** table indexed by track number while the LFO SETUP edit is in flight.
3. The "audio channel" symptom = FUN_4009eec8 style code indexing `0x40171442` with the wrong
   base when `_DAT_80000012`/`DAT_80000002` (part) state points at the twin audio track.

### Immediate next steps
1. Dump `DAT_400a7280` (bytes) + the param-id ranges the LFO MAIN vs LFO SETUP encoders emit.
2. Decompile FUN_400438fc, FUN_40055008, FUN_4009da20 — find the CC-28..33 / audio-channel path.
3. Reproduce in the emulator (adapt `tools/emu_*`): drive case '?' with an LFO-SETUP paramId
   for a MIDI track whose twin audio track has a different channel; capture FUN_40010bc8 args.
4. Then design the suppression patch (likely a guard in FUN_40054cd8's MIDI branch, or in
   FUN_4009eec8, skipping transmit when paramIdx is an LFO param / page == LFO SETUP).

Scratch dumps: `scratchpad/lfo{2..13}.txt`. Manual text: `tool-results/otmk2.txt`.

---

## Session 8 continued — LIKELY ALREADY FIXED IN 1.40C (emulation-backed)

### The transmit mechanism, fully traced
- **FUN_400409f4** = polled "AUDIO CC OUT" transmitter (runs off HW timer `DAT_fc078xxx`).
  For each set bit `ch` in `_DAT_46c7e0de` (a **MIDI-channel** mask), for each set param bit
  in `[ch*0x10 + 0x46c7d7d8]`, transmits `CC (col*0x20 + bit) = value[ch*0x80 + 0x46c7bf2c + ...]`
  with status byte `(ch | 0xB0)`.
- **FUN_40033e3c(track, ccNum, value)** = the enqueue. Gated by `DAT_8000004a & 2` (= AUDIO
  CC OUT enable; INT clears it). Resolves `ch = *(char*)(0x8000003f + track)` — the **audio
  track's assigned MIDI channel** — skips if that channel collides with a MIDI track's
  channel, else stores value at `[ch*0x80 + ccNum + 0x46c7bf2c]` and sets `_DAT_46c7e0de` bit `ch`.
- **CC number for a param edit = `enc + 0x10 + DAT_400a72a8[_DAT_460d1684]*6`.** Empirically
  (emu sweep) `_DAT_460d1684`: 0→playback CC16-21, **1→LFO CC28-33**, 2→amp CC22-27,
  3→FX1 CC34-39, 4→FX2 CC40-45. (Matches manual Appendix C.7.)

### The shared SETUP-page encoder handler
- **FUN_400554e0(block)** (called by every param-SETUP page-open) does
  `_DAT_460d1684 = block; FUN_400326d4(def, 0, &DAT_400c085a)` — installs the encoder handler
  table @0x400c085a: encoders 0-5 → **FUN_40055008**, encoder 6 → FUN_4004eb24.
- Page-open → block: LFO SETUP (FUN_40058390) → **block 1**; PLAYBACK/MIDI-NOTE → 0;
  MIDI-CTRL1/EFFECT1 → 3; MIDI-CTRL2/EFFECT2 → 4.
- **FUN_40055008(enc, delta)**:
  - `if (_DAT_80000012 == 0)` (**audio mode**): writes param, then
    `FUN_40033e3c(DAT_100b14cc, enc + 0x10 + DAT_400a72a8[_DAT_460d1684]*6, value)`
    → for block 1 that's **CC 28-33 on DAT_100b14cc's audio channel**. (Correct AUDIO CC OUT.)
  - `else` (**MIDI mode**): `FUN_4009eec8(DAT_100b14cc, _DAT_460d1684*6 + enc, value, 0)`.
    FUN_4009eec8 only emits for param 0x12..0x1d (PB/AT/CC1-10). For the LFO block that's
    param **6..11 → FUN_4009eec8 does nothing.**

### Emulation result (`tools/emu_lfocc.py`, unicorn)
Drove FUN_40055008 for every `enc`×`_DAT_460d1684`×{audio,midi}. Faithful:
- audio + block 1 → `FUN_40033e3c(0, 28..33, val)`  ✅ audio CC out fires (expected).
- **midi + block 1 → FUN_4009eec8(0, 6..11, val, 0) → nothing transmitted.** ✅ no bug.
- midi + block 3/4 (CTRL pages) → FUN_4009eec8 param 18..29 → PB/AT/CC1-10 DO transmit
  (correct — that's the point of the CTRL pages).
Also swept all 13 `FUN_40033e3c` callers: only FUN_40055008 ever uses CC 28-33; the rest
use CC 0x31-0x7f (mute/solo/cue/arm/scene). **No page-enter bulk LFO-CC dumper exists.**

### Conclusion
On **OS 1.40C** there is no code path by which editing a MIDI track's LFO SETUP SPD/DEP
transmits CC 28-33 — the `_DAT_80000012` (MIDI-mode) gate in FUN_40055008 sends MIDI-track
edits down the FUN_4009eec8 path, which ignores LFO params. The 2019 report was against
**MKI OS 1.30B**; this looks **already fixed** (most plausibly: the `_DAT_80000012` guard
was added to FUN_40055008 in the 1.31/1.40 line). Could not obtain a 1.30B binary to diff.

### Recommended confirmation (hardware, user has the gear)
On the real Octatrack (1.40C): PROJECT>MIDI>CHANNELS set MIDI trk1→ch1, audio trk1→ch9;
PROJECT>MIDI>CONTROL set AUDIO CC OUT = EXT (or INT+EXT); MIDI monitor on the OUT.
MIDI mode → MIDI track 1 → LFO SETUP page → turn SPD / DEP. If **no** CC 28-33 appear on
ch9, the bug is fixed and this task is closed. If they DO appear, the repro is live and the
fix target is the missing `_DAT_80000012` guard / a second path — resume from here.

### Residual (if pursuing further)
- Emulate the full [MIDI]→open MIDI-LFO-SETUP→turn-SPD chain (page-open FUN_40058390 +
  event loop) rather than calling FUN_40055008 directly, to rule out an open-time emit.
- Obtain OT OS 1.30B/1.31 and diff FUN_40055008 to confirm what the fix was and when.

---

## Session 9 (2026-08-28) — Feasibility: "soft" audio-track mute (decay + FX tails, like trig mutes)

Goal: make FUNC+TRACK audio mute enter the amp release phase and let delay/reverb tails ring,
instead of the instant hard cut. Longstanding Elektronauts wish. User's hypothesis: the soft
behaviour already exists in the arranger-mute path. Scripts: `tools/GhidraMute{1..7}.java`;
dumps `out/ghidra/GhidraMute{1..7}_session9.txt`.

### Map of the mute subsystem (verified by decompile + byte-search for address constants)
- **Audio-track mute mask** = 8-bit `_DAT_460fab40` (bit t = track t muted). Managed by a
  self-contained "mute mode / QUICK MUTE" module at `0x40083480..0x40083f??`.
  - `FUN_40083480` → getter (used by LED refresh FUN_40030a6c/c60/e6c).
  - `FUN_40083ab4(keycode,phase)` → **mute a track**: `uVar1 = keycode-0x10`; `_DAT_460fab40 |=
    1<<uVar1`; if phase==1 → `FUN_400836d8()`.
  - `FUN_40083e40(keycode,phase)` → **unmute a track**: `_DAT_460fab40 &= ~(1<<...)`; → `FUN_400836d8()`.
  - `FUN_400836d8(arg,phase)` = re-evaluate all 8 voices after a mask change (phase 1=mute,0=unmute).
  - `FUN_40083544(track,phase)` = single-track version; **the arranger calls THIS** (see below).
- **Byte-search confirms `0x460fab40` is referenced ONLY inside `0x40083482..0x40083e86`.**
  The DSP frame builder / mixer / trig→voice path never read the raw mute mask.
- **Derived masks actually consumed by the audio engine**:
  - `_DAT_46c803d4` : low byte = CUE mask, high byte = MUTE mask. Also drives MIDI CC-out
    (FUN_40033e3c CC 0x34 cue / 0x35 mute / 0x36 mute-all, via FUN_4005e294 & FUN_4000e79c).
  - `_DAT_46c7ff64` : "silenced in MAIN out" mask (same <<8 layout). Read by `frame_builder`
    (FUN_4000c8a4 @0x4000c93e) and a sibling voice-cmd gate @0x4000b936, plus 0x4000ac44.
  - `FUN_400834d8(_,phase)` = the mute-page **commit** handler (ptr pair @`0x400d15e4`):
    phase 1 → `_DAT_46c803d4 |= _DAT_460fab40<<8; _DAT_46c7ff64 |= _DAT_460fab40<<8; CC 0x35`;
    phase 0 → `_DAT_46c7ff64 = 0`.
- In `frame_builder` the mute mask is applied by **gating pending voice commands**: `btst #8,cmd`
  then `... & ~_DAT_46c7ff64 ...`, and it *synthesises* a command `uVar10 = (cmd & 0xf000) |
  per_track_byte(0x800017f6) | 0x210` into the per-track slot — i.e. it forces flag 0x10 (the
  stop/one-shot bit) while **preserving the existing mode nibble**; it does not force 0xf000.

### The "soft release" machinery already exists (and is used elsewhere)
- `FUN_40008f84(track)` : start a graceful release — sets `DAT_8000184a |= 1<<t` (voice state
  "2" = releasing, per FUN_40000ee0), writes release param `0x2d`, calls FUN_4000672c.
- Consumed by `FUN_400068e4` (control-rate voice updater): on the release bit it writes
  **ramp targets** `0xf0000000/0xf0000000/0xf0000000` to voice+0x24/0x28/0x2c and `0xe0000000`
  to voice+0x40 (envelope-segment slope registers — a fast *ramp*, not a zero), then
  `FUN_40005c7c`/`FUN_40095ee0`/`FUN_4000432c` push it to the DSP frame amp.
- `FUN_40008fe4(track)` wraps it (also sets `DAT_8000184c=0xff`); `FUN_40008fe4(0xffffffff)` =
  "release ALL voices", called from transport STOP and every CHANGE SET / SYNC TO CARD flow
  (FUN_40063660/778/930/e28, FUN_4006437c, FUN_4006cc54) — so a clean fade on state change.
- `FUN_40083a7c` already does exactly the wanted thing (`for t in muted: FUN_40008fe4(t)`) but
  has **no discoverable caller** (dead, or dispatched — worth chasing).

### What FUN_400836d8 / FUN_40083544 actually do on mute
For **FLEX (machine 0) / STATIC (1)** with the **default** mute settings (mute-quantise/retrig
nibble `uVar6 == 0`): muting a *currently-sounding* voice sends **no stop/release command at
all**. Only machine types ≥2 (THRU/NEIGHBOR/PICKUP) get a `0x8040` command. The re-eval logic
only fires when a mute-retrig nibble is set (the STARTS SILENT / ONE / ONE2 / HOLD option).
→ The instant silence of a sustained sample under mute therefore comes from the
`_DAT_46c7ff64`/`_DAT_46c803d4` gate in the frame builder + whatever the DSP does with the
0x?10 command — **not** from the ColdFire voice logic.

### Arranger vs FUNC+TRACK
The arranger row-command interpreter is `FUN_40061a94` (switch over a command-byte stream;
handles TEMPO/SCENE/MUTE/… and sets the mute-retrig nibbles `_DAT_460d179a/9e/a2`). Its MUTE
command calls the **same `FUN_40083544`**. → There is **no separate softer arranger-mute path**
at the voice level. User's hypothesis not confirmed. The only arranger-specific knobs are the
shared mute-quantise nibble and the retrig-on-unmute mode.

### Feasibility verdict
Plausible, scoped like the Bug-1 fix, with ONE real unknown that is DSP-side:
1. The release primitive we want (`FUN_40008f84`, ramp targets `0xf0000000`) **already exists**
   and is call-ready. A detour at `FUN_40083ab4` / `FUN_400836d8` could, on mute (phase 1),
   additionally call `FUN_40008f84(track)` for FLEX/STATIC sounding voices; on unmute do nothing.
2. **Open question**: is the FX send tapped **pre** or **post** the mute gain? If pre (send is a
   fixed tap off the voice pre-mute-level), then killing the amp with a release already lets the
   tail ring — easy win. If post, tails die regardless of amp release and we'd need a frame/mixer
   routing change (harder; frame_builder is dense ColdFire that r2 mis-decodes, Ghidra partial).
3. Also need: does the DSP's 0x?10 "stop" do an instant cut or honour an envelope release? DSP
   program is DSP56300, located **inside the MAIN OS image** at ~`0x400e2000..0x4010fdf0`
   (~188 KB) — patchable in principle but needs a DSP56300 disassembler.

### Next steps if pursued
- Emulate (unicorn, like emu_trigbug) the mute of a sounding FLEX voice: watch voice+0x20..0x44
  and the frame amp slot for that track — instant 0 vs ramp — and see if a separate "send level"
  slot stays non-zero.
- Locate the per-track MAIN-mix and SEND-mix level words in the DSP frame double-buffer
  (`_DAT_800000e0 * 0x180` / `* 0x200` regions filled at the end of frame_builder) and check
  which the mute mask zeroes.
- Chase callers of `FUN_40083a7c` (already the desired loop).
- If pre-send tap confirmed: prototype a detour `FUN_40083ab4`→cave that calls `FUN_40008f84`
  on mute for sounding FLEX/STATIC, gated by a PERSONALIZE flag ("SOFT MUTE").

### Emulation results — `tools/emu_mute.py` (unicorn), log `out/ghidra/emu_mute_session9.txt`
Drove the real handlers against a synthetic "track 0 = sounding FLEX voice" pre-state.

**S1 — `FUN_40083ab4(0x10, 1)` (real FUNC+TRACK mute), FLEX voice sounding, default settings:**
the ONLY write is `_DAT_460fab40 = 0x01`. No voice command, no amp write, `_DAT_46c803d4`/
`_DAT_46c7ff64`/`DAT_8000184a` untouched. `FUN_400836d8` runs but is a no-op for FLEX/STATIC.
**S2 — arranger `FUN_40083544(0, 1)`** for FLEX / STATIC / NEIGHBOR: no writes at all. Confirms
the arranger mute path is identical (and equally inert on a sustained voice).

**S3/S5 — the release is one flag away.** `FUN_40008f84(t)` sets `DAT_8000184a |= 1<<t` (release
*state*) but NOT the ramp trigger. The ramp trigger is **`DAT_8000184c |= 1<<t`**. With that bit
set, the very next `FUN_400068e4` tick (the control-rate voice updater, already running every
audio frame) does, for that track:
```
pcurs[t]+0x24 = 0xf0000000   pcurs[t]+0x28 = 0xf0000000   pcurs[t]+0x2c = 0xf0000000
pcurs[t]+0x40 = 0xe0000000        (envelope-segment slope regs = steep negative = release)
-> FUN_40005c7c(t, pcurs[t], level, 0, 1, 0)
   -> FUN_40095ee0(0x80+t, level, ...) -> FUN_40099090(vframe[0x80+t], level, slope)
      writes AMPseg[0x80+t] +0x114=target(clamped >=0x2d0 floor) +0x118/+0x11c/+0x120=ramp
```
i.e. it ramps the **AMP stage** (per-track voice `vframe[0x80+t]`, `pcurs` struct base 0x80004f1c
stride 0x54) down to the 0x2d0 floor. That's upstream of the track insert-FX + mix routing.
(`FUN_40008fe4(t)` = `FUN_40008f84(t)` + `DAT_8000184c = 0xff`; that's why transport STOP /
CHANGE-SET, which call `FUN_40008fe4(-1)`, fade cleanly. `FUN_400972fc` sets a single bit
`DAT_8000184c |= 1<<t` for PICKUP.)

**S6 — the hard mute gate is NOT an amp ramp.** Pushing `_DAT_460fab40<<8` into
`_DAT_46c803d4`/`_DAT_46c7ff64` (via `FUN_400834d8`, the mute-page commit) then ticking
`FUN_400068e4` produced *no* release fingerprint — the instant silence must be the
voice-command injection in `frame_builder` (`(cmd & 0xf000) | ... | 0x210`, flag 0x10) and/or
the DSP's handling of it. So the two mechanisms are independent stages:
`AMP release` (pcurs/vframe, ramped, pre-FX)  vs  `mute gate` (voice-cmd/DSP, instant).

### Feasibility verdict (updated) — GREEN for a small detour patch
The wanted behaviour = **on mute, run the AMP release instead of relying on the instant gate**.
Emulation shows the release machinery is complete, already ticking, and triggered by one bit.

**Proposed fix**: detour `FUN_40083ab4` (mute-set; and/or `FUN_40083e40`/`FUN_400836d8`) → code
cave that, on phase==1, for each newly-muted track whose voice is sounding
(`(&DAT_800049d8)[t*0xA8+1] != 0`) does:
  `DAT_8000184c |= (1 << t);`  and  `FUN_40008f84(t);`
and (open design choice) suppress the frame-builder's injected stop for those tracks so the
sample tail + its FX feed decay naturally rather than being cut mid-release. Gate the whole
thing behind a PERSONALIZE flag ("SOFT MUTE"), same pattern as the other MAXOLYDIAN mods.
Unmute path unchanged (the existing STARTS-SILENT / ONE / ONE2 / HOLD logic still applies).

**Still unverified (needs DSP RE or hardware):** whether suppressing the injected stop is even
necessary — if the DSP treats `0x?10` on an already-releasing voice as "let the envelope
finish", the amp-release alone may be enough and no frame-builder change is needed. The DSP
program is DSP56300 at ~`0x400e2000..0x4010fdf0` inside the MAIN OS.

**Recommended validation before writing the patch:** extend `emu_mute.py` to also drive a few
frames of `frame_builder` (FUN_4000c8a4) with the mute mask live + the `DAT_8000184c` bit set,
and confirm the per-track `framelvl_46c938d4[t]` / `vframe[0x80+t]` amp actually ramps (not
snaps) and that the injected `0x?10` command doesn't zero it first.

### Frame-builder emulation — `emu_mute.py` scenario 7 (enter the per-track loop at 0x4000c87c)
The real frame-builder task is `FUN_4000b8f0` (5068 B, no callers → kernel/ISR-dispatched, full
decompile fails). Its per-track command-resolution loop is 0x4000c87c → 0x4000ca94 (then the
EMAC frame-assembly tail, un-emulatable). Drove just the loop with a still-sounding *sustained*
voice on track 0 (`(0x800017b8)[t]!=0`, `refresh_46c7faa4[t,0]` bit 0x20 set):

| pre-state | result for trk0 |
|---|---|
| unmuted | emits refresh cmd `0x2210` into `RESOLVEDCMD_46104d26[0]` |
| `_DAT_46c7ff64` bit8 set (force-mute) | emits the **same** `0x2210` — voice kept alive; the cut is the DSP **output** mute (post-FX) applied from `_DAT_46c7ff64` elsewhere in the frame |
| `_DAT_8000184e` bit8 set, `46c7ff64` clear | **clears `refresh_46c7faa4[t,0]`, emits nothing** — the voice just stops being fed and decays naturally |

So the two silencing stages are now fully characterised:
- `_DAT_8000184e` (silenced-set) → "stop refreshing" → natural decay, no injected stop.
- `_DAT_46c7ff64` (main-out silence) → DSP post-FX output mute → **instant, kills FX return too**
  = the behaviour the community wants gone.
- `DAT_8000184c` bit → `FUN_400068e4` AMP-envelope release ramp (pre-FX).

### Refined fix design — detour `FUN_400836d8` (the common apply-mute fn)
`FUN_400836d8` is called by every mute path (plain FUNC+TRACK via `FUN_40083ab4`; the
CUE/MUTE/SOLO key handlers `FUN_40030a6c/c60/e6c`; arranger via `FUN_40083544`'s sibling).
Detour it (behind a PERSONALIZE "SOFT MUTE" flag) so on phase==1, for each newly-muted track
`t` whose voice is sounding (`(&DAT_800049d8)[t*0xA8+1] != 0`) and machine is FLEX/STATIC:
```
DAT_8000184c   |= (1 << t)          ; kick the AMP release (FUN_400068e4 ramps vframe[0x80+t])
_DAT_8000184e  |= (1 << (t + 8))    ; stop the sustain-refresh -> looped samples wind down
```
and **suppress the `_DAT_46c7ff64` bit `(1<<(t+8))`** for those tracks (clear it after the
normal mute code sets it, or gate the setter) so the track's FX/mix output stays open and
delay/reverb tails ring out while the amp decays. Unmute: clear the `_DAT_8000184e` bit and let
the existing STARTS-SILENT/ONE/ONE2/HOLD re-trig run.

Open refinements for patch dev (not blockers): (1) `_DAT_46c7ff64` also carries the CUE mask
and drives MIDI mute-CC-out — make sure clearing the mute bit doesn't disturb cue or the CC.
(2) `FUN_40030a6c/c60` also XOR the mute state into the pattern blob (`blob+0x28/+0x30`) and
toggle `_DAT_460d10d4/d8` — confirm SOFT MUTE interacts cleanly with a saved/recalled pattern.
(3) find where `_DAT_46c7ff64`/`_DAT_46c803d4` actually get set from `_DAT_460fab40` on the
plain path (`FUN_400834d8` is the QUICK-MUTE commit; the plain path's setter is likely inside
`FUN_40030984` / `FUN_400839dc` — decompile those next).

### emu_mute.py scenario 8 — the decay honors the AMP-envelope RELEASE knob
There are **two** independent "stop a voice" primitives and they behave differently:

| primitive | set by | mechanism | fade shape |
|---|---|---|---|
| `DAT_8000184a` (bit/track) | `FUN_40008f84(t)` | frame_builder @`0x4000bd3c` reads it, OR's **bit 0x10 (note-off/gate-release)** into the voice command, then clears the bit. Same flag as a STATIC-machine note-off. | **DSP runs the voice's AMP-envelope RELEASE stage → the user's REL setting is honored.** `FUN_400068e4` writes *no* fixed slope for this path (emu-confirmed). |
| `DAT_8000184c` (bit/track) | `FUN_40008fe4(t)` / STOP / CHANGE-SET | `FUN_400068e4` writes fixed `0xf0000000` envelope slopes | hard ~ms declick fade, **AMP env ignored** |

So the SOFT MUTE detour must use **`FUN_40008f84(t)`**, *not* `DAT_8000184c`. Then muting a
sounding track = a note-off: the sound decays over its AMP RELEASE time (short REL → quick
fade, long REL → long fade), and delay/reverb tails ring from the FX buffers throughout.

**Watchdog caveat:** `FUN_40008f84` writes `0x2d`(=45) to `relparam_46c7dfba[t]`, a per-track
frame countdown (decremented in the `FUN_40052290` per-frame loop). When it reaches 0, a voice
still in release state 2 is force-freed (`FUN_40000ee0(t)==2` → `FUN_40006820(t)`). So a REL set
to "infinite"/very-long will NOT sustain forever after a mute — it is cut at ~45 control frames
(exact ms = 45 × audio-control-frame period, not yet measured; likely tens–low hundreds of ms).
The FX tail is unaffected (it lives in the FX buffers). If genuinely-infinite mute-sustain is
wanted, the same detour can also skip re-arming / neutralise that watchdog for soft-muted
tracks — a one-line addition.

Unmute semantics with this design (user-confirmed choice = "trig mute"): the voice is released
and then freed, so there is nothing playing underneath — **the track returns from the next
sequencer trig**, not mid-sample. (Stock OT mute resumes mid-sample because it keeps the voice
alive under a DSP output-mute; SOFT MUTE deliberately does not.)

### emu_mute.py scenarios 9 & 10 — CORRECTION to S1 + stock-mute command
S1 was **under-seeded**: the real MUTE key handler sets a mute-quantize word
(`_DAT_460d10d4`/`d8`/`d0` = 1, three modes) *before* calling `FUN_400836d8`, and S1 left those
at 0, which is why `FUN_400836d8` looked inert. With the quantize word set:

- `FUN_400836d8` (FLEX, mute, sounding) writes a **voice command to the `46c7e9fa` mailbox**:
  `0x1040 / 0x2040 / 0x4040` (bit `0x40` + the quantize nibble `<<12`). STATIC gives
  `0xa040`, or `voice_cmd(t, 0x80, 1)` (a *restart*) in the branch where the pending nibble
  already matches the voice's current one.
- Ran all three real key handlers (`FUN_40030a6c` / `c60` / `e6c`) end-to-end against a
  sounding FLEX voice. **None of them set `_DAT_46c7ff64`, `_DAT_46c803d4`, `_DAT_8000184a`,
  `_DAT_8000184c` or `_DAT_8000184e`.** Their only voice-engine effect is the `0x?040` mailbox
  write via `FUN_400836d8`.

So on the **plain FUNC+TRACK path**, `_DAT_46c7ff64` (the DSP output mute) is apparently **not
set at all** — the silencing is the `0x?040` mailbox command (bit `0x40`) resolved by the
frame builder / DSP. `_DAT_46c7ff64` is set by the **QUICK MUTE screen commit** (`FUN_400834d8`)
and the CUE/solo focus path (`FUN_4005e294`), not by track-key mute.

**Open (decides the exact patch):** what does the DSP do with a `0x?040` (bit-0x40) command —
instant cut, or deferred-to-quantize then cut, and does it kill the FX return? Bit `0x40` vs
bit `0x10` (note-off) vs `0xf000` (hard stop) semantics still not disassembled (DSP side).

### Revised patch plan
Two candidate detour strategies, to decide by building + emulating:
1. **Augment**: keep the stock `0x?040` command, additionally call `FUN_40008f84(t)` +
   `_DAT_8000184e |= 1<<(t+8)` for sounding FLEX/STATIC. If the stock command turns out to
   already be release-like (deferred), this alone may give the wanted behavior.
2. **Replace**: in the `FUN_400836d8` FLEX/STATIC mute branch, swap the `mailbox = uVar6|0x40`
   / `FUN_40005178(t, uVar6|0x10, 1)` for `FUN_40008f84(t)` (+ the 8000184e bit), so the voice
   gets a clean note-off instead of the `0x40` command.
Both behind a PERSONALIZE "SOFT MUTE" flag. Next step: assemble a minimal detour (strategy 1),
run it in emu_mute.py watching the `46c7e9fa` mailbox + frame output + amp segments, iterate.

### PROTOTYPE BUILT — `tools/patch_softmute.s` (strategy 1, augment) + emu_mute.py S11
Detour: `0x400836d8` (`FUN_400836d8` entry) ← `jmp 0x400d7b40` + nop (8 B, covers the
`lea (-0x3c,SP),SP` + `movem.l {D2-D7,A2-A6},(SP)` prologue). Cave at **0x400d7b40** (242 B,
fits the 0x400d7b3e..0x400d7c3b free tail past `patch_trigscale`; 9 B spare). Gate byte
**0x800000dc** (next free PERSONALIZE word after 0xd4/0xd8), 0 = stock.
Cave logic: save d0-d7/a0-a6; if gate off or phase∉{0,1} → run displaced prologue, resume at
`0x400836e0`. phase 0 (unmute): `SILENCED &= ~((~mask & 0xff) << 8)`. phase 1 (mute): for each
track in the mask that is FLEX/STATIC (`blob +0x8f385 ≤ 1`) and sounding
(`FUN_40000e50(t)`→`*(a0+1) != 0`): `FUN_40008f84(t)` + `*(u16)0x8000184e |= 1<<(t+8)`.

emu_mute.py S11 (stock vs patched, FLEX + STATIC):
- stock  → only `mailbox_46c7e9fa[0] <- 0x2040` (FLEX) / `0xa040` (STATIC).
- patched → same mailbox write **plus** `FUN_40008f84(0)` runs: `DAT_8000184a=0x01` (note-off
  armed → DSP AMP RELEASE), `relparam_46c7dfba[0]=0x2d` (45-frame watchdog), and the cave
  writes `_DAT_8000184e=0x0100`. Detour completes cleanly, no crash.
- unmute round-trip: `_DAT_8000184e` 0x0100 → 0x0000. ✓
Gate verified: `softmute=False` runs are byte-identical to stock.

**What emulation can't decide (needs a hardware flash):** whether the retained stock `0x?040`
command still hard-cuts on top of the note-off (→ switch to "replace": null the
`mailbox = D3|0x40` / `FUN_40005178(t, D3|0x10, 1)` stores in the FLEX/STATIC branches), and
whether the FX tail audibly survives. Build A candidate = stock 1.40C + this detour only.

### FLASHABLE BUILD — `tools/build_softmute.py` → "Build C" (2026-08-28)
Stock 1.40C + `patch_trigscale` (Bug 1, always-on, **bytes identical to `build_trigscale_only.py`**
— verified by diff) + `patch_softmute` (**always-on**, assembled with `--defsym ALWAYS_ON=1`
which drops the `tst.b 0x800000dc` gate; gated cave = 242 B, always-on cave = 232 B).
Caves: patch_trigscale @0x400d7b00 (62 B), patch_softmute @0x400d7b40 (232 B) — adjacent, no
overlap, end 0x400d7c28 < free-zone end 0x400d7c3c. 272 bytes changed vs stock, only at
`0x400836d8` (8-B detour) + `0x4009b6f2` (trigscale detour) + the two caves.
Outputs: `out/mainos_softmute.bin`, `out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.syx` (622742 B,
version field stays "1.40C", EFT checksum + round-trip OK), `out/OCTATRACK_SOFTMUTE_PFFIX.bin`
(445820 B, CF-card path). Not yet hardware-flashed. FLASHING.md "Build C" + "Testing SOFT MUTE".

### V1 augment FLASHED → hard cut still won (user, 2026-08-28). V2 = REPLACE.
emu_mute.py check: after V1 (note-off + `_DAT_8000184e` bit + stock `0x?040` left in place),
frame_builder's per-track loop still resolves `RESOLVEDCMD[t] = 0x2040` → the stock deferred-mute
command reaches the DSP and hard-cuts. So the note-off never gets a chance.

**patch_softmute V2** (`tools/patch_softmute.s` rewritten): now *deletes* the stock command.
The detour is a `jmp`, so `(0,SP)=caller_ret` on entry. When there is work to do it saves
`caller_ret`, overwrites `(0,SP)` with `&post`, runs `FUN_400836d8`'s body (which still writes
`mailbox[t] = 0x?040`), and the body's `rts` then lands in `post`, which zeroes `0x46c7e9fa[t]`
and `0x800018be[t]` for every handled track and `jmp`s to the real `caller_ret`. Net for a
soft-muted sounding FLEX/STATIC track: only `FUN_40008f84(t)` (note-off) + `_DAT_8000184e` bit
reach the engine; the hard-cut command is gone. Mute mask (`_DAT_460fab40`) is untouched, so
the mute is remembered; LED / getmask paths see the real mask.
emu S11 (V2): stock → `RESOLVEDCMD[0] = 0x2040`/`0xa040` (hard cut). patched → `46c7e9fa[0]=0`,
`8000184a=0x01`, `460fab40=0x01`, `RESOLVEDCMD[0] = 0xeeee` (nothing emitted → voice decays).
Always-on flash cave (GATE byte = 0) verified: FLEX + STATIC fire, not-sounding tracks don't,
no crash. Cave moved to **0x400d7400** (330 B; the 0x400d7b40 slot ran past the free-zone end).

### Rebuilt Build C (V2)
`out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.{syx,bin}` — caves patch_softmute @0x400d7400 (330 B) +
patch_trigscale @0x400d7b00 (62 B); detours 0x400836d8 (8 B) + 0x4009b6f2 (18 B); your bug
fix bytes still identical to `build_trigscale_only.py`; version field "1.40C"; EFT round-trip OK.
**Still not hardware-tested.**  If V2 still hard-cuts on hardware → the DSP note-off (bit 0x10)
does not produce a release for a FLEX one-shot mid-playback, and the fix has to force the AMP
envelope into its RELEASE segment directly (a DSP-frame `vframe[0x80+t]` / `pcurs` manipulation).

### V2 FLASHED → still hard-cuts, BOTH FLEX and STATIC (user, 2026-08-28).
So neither the stock `0x?040` command (deleted by V2, emu-confirmed) nor the note-off is the
operative mechanism. The FUNC+TRACK mute silences the track through a path not yet found —
candidates: (a) `_DAT_46c7ff64` DSP output mute set somewhere I stubbed; (b) the pattern/kit
param repush — `FUN_40030a6c/c60/e6c` XOR an 8-byte region at `blob + pat*0x8ed8 + trk*0x91a
+ 0x30` with `_DAT_460d10e2/e6` then call `FUN_40027e00` (repush to audio engine) — this path
was always stubbed in emu and doesn't decompile; (c) the FUNC+TRACK key path might route
through `FUN_40083ab4` (qmode 0) so `FUN_400836d8` emits *nothing* and the `0x?040` analysis
was a red herring for that entry point. `FUN_40027e00` has 258 refs; `_DAT_460d10e2` refs
cluster at `0x4002ea..0x40030` (FUN_4002exxx — the kit/scene param engine).

### DIAGNOSTIC D1 FLASHED → still hard-cuts, tails still die (user, 2026-08-28).
`build_softmute.py --d1` = patch deletes ONLY the stock `0x?040` mailbox command, nothing else.
Deleting it changed nothing → **the `FUN_400836d8` / `0x?040` mailbox command is NOT the mute
mechanism.** The whole 12-scenario `emu_mute.py` line of investigation was chasing the wrong
code path. Files `out/OCTATRACK_OS1.40C_SOFTMUTE_D1_PFFIX.{syx,bin}` kept (harmless; MIDI fix
intact).

### The ACTUAL mute mechanism (found via minimal-stub emu of FUN_40030c60)
FUNC+TRACK mute of an audio track runs `FUN_40030c60` (0x40030c60; a6c/e6c are the sibling
CUE/SOLO handlers). On phase 1 it:
1. `puVar1 = blob + pat*0x8ed8 + trk*0x91a + 0x28` — an **8-byte per-track FLAGS field** in the
   audio-track parameter block (the 0x91a-stride block).
2. `*puVar1 ^= _DAT_460d10e2 ; puVar1[1] ^= _DAT_460d10e6` — toggle the MUTE bit(s). The mask
   `_DAT_460d10e2/e6` is dynamic, owned by the **SCENE / parameter-override engine**
   (`FUN_4002exxx` cluster) — it is 0 in a bare emu call, set up by whatever enters "mute
   context". The MUTE-LED routine at ~0x4002ed00 lights the LED when
   `(_DAT_460d10e2 & param[+0x28]) | (_DAT_460d10e6 & param[+0x2c]) != 0`.
3. mirror to RAM `0x10016176 + pat*0x8ed8 + trk*0x91a` (8 B).
4. set dirty flags `*(blob + 0x9b332) = 1`, `_DAT_100f8598 = 1`.
5. `FUN_400836d8()` — the `0x?040` cosmetic quantize command (proven irrelevant by D1).
An **async param-sync task** (polls `_DAT_100f8598` / `+0x9b332`, 461 refs) then repushes the
whole track param block to the audio engine → the mute flag is applied, instantly, post-FX
(kills the send/return → no tail).

### Scope reassessment — this is NOT a Bug-1-sized detour
The mute is a **scene/parameter-override flag** (`FUN_4002exxx`, the SCENE engine — COVERAGE.md
marks Scenes "⬜ untouched, the OT's flagship feature") toggled in the track param block and
repushed by an async sync to the audio engine, which applies it in the (non-decompiling)
ColdFire frame-fill and/or the DSP.  Making it "trig-mute" style needs RE of the scene engine
+ the audio param-sync + likely the DSP mute-flag handling — a multi-session effort in the
hardest, least-decompilable subsystem, with an uncertain payoff (may bottom out at "the DSP
does it").

### V3 — narrowed goal: "mute = a per-track STOP" (user's chosen target)
User: *"the same behavior that occurs with a single stop command … sample audio cuts, but the
fx tails still ring."*  So: don't try to make the dry signal decay musically — just do what a
single STOP does to that one track.

The three CUE/MUTE/SOLO handlers each XOR an 8-byte flag field in the audio-track param block
(emu-confirmed offsets): `FUN_40030e6c` → +0x20, `FUN_40030c60` → **+0x28**, `FUN_40030a6c`
→ +0x30.  The MUTE-LED routine (~0x4002ed00) tests `_DAT_460d10e2 & param[+0x28]` → **+0x28 =
MUTE = `FUN_40030c60`.**

`tools/patch_softmute.s` rewritten (V3): **detour `FUN_40030c60`** (prologue `4fefffe8
48d7047c`, 8 B). When SOFT MUTE is on, for a non-PICKUP current track (`DAT_100b14cc`), on the
key press (phase 1): keep a patch-owned 8-bit soft-mute mask at `0x80006c66` (+ valid byte
`0x80006c67`=0x5a), toggle this track's bit, and —
  - now-muted  → `DAT_8000184c |= 1<<t` + `FUN_40008f84(t)`  (exactly a per-track STOP: the
    `FUN_400068e4` tick fast-fades the AMP; the FX inserts keep ringing)
  - now-unmuted → just clear the bit
  - then `rts` — **the stock `FUN_40030c60` body never runs**, so the post-FX param-mute flag
    is never set → the FX return stays open.
PICKUP tracks + phase-0 (key release) → run the stock body unchanged.
Trade-off (test build): mute state not written to the pattern (no save/recall persistence),
MUTE LED does not light.

emu (`emu_mute.py` `_softmute_patch` now points at 0x40030c60): press1 t2 → `DAT_8000184c`
bit2, `DAT_8000184a` bit2, `SMASK=0x04`, param+0x28 untouched (stock skipped); press2 →
`SMASK=0`; press3 → `SMASK=0x04`; PICKUP → stock. Cave 204 B @0x400d7400.

Build: `python3 tools/build_softmute.py` → `out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.{syx,bin}`
(+ the MIDI manual-trig fix, bytes identical to Build A; version "1.40C"; EFT round-trip OK).
247 bytes changed vs stock. **Not yet hardware-tested.**

If FUNC+TRACK behaviour is *unchanged* after flashing → `FUN_40030c60` isn't the FUNC+TRACK
path; retry with the detour on `FUN_40030e6c` (+0x20) or `FUN_40030a6c` (+0x30).

### V3 FLASHED → "no change" (user).  V4 — hooked the real per-frame mute gate.
Minimal-stub emu of the real FUNC+TRACK path (`FUN_40040250(trackkey,1)`, button table at
0x400bfc30 → all track keys dispatch here → `FUN_40083ab4` → `FUN_400836d8`): the ONLY state
write is `_DAT_460fab40 |= 1<<t`.  Nothing else.  A periodic task then syncs that into
**`_DAT_80000008`** (bit 8+t = muted, bit 16+t = cued — same bits the LED painter `FUN_40083eb0`
reads).

**`FUN_40004dbc`** (entry 0x40004db8) is the per-frame mute gate: `D5 = _DAT_80000008`; per
track it writes several 16-bit level words into the DSP-frame double-buffer (`_DAT_80003c10`),
and for a muted track it `clr.w`s them — a **post-FX cut** (kills the FX return).  Source
arrays `0x80000c60` / `0x80000c80` / `0x8000485a`.  SOLO uses a separate branch gated by
`_DAT_80000037`.

**patch_softmute V4**: detour the one instruction that loads `_DAT_80000008` into D5
(`2a39 80000008` @0x40004dc6, exactly a 6-byte jmp).  Cave (66 B @0x400d7400): loads D5;
unless SOLO is active, for `muted = (D5>>8) & 0xff`:
  - `DAT_8000184c |= muted`  → `FUN_400068e4` fast-fades those AMPs (dry cuts, like STOP)
  - `D5 &= ~(muted<<8)`      → `FUN_40004dbc` keeps their frame level words → FX inserts
    still reach the mix → tails ring
The global `_DAT_80000008` is untouched (LED still shows muted).  emu: `_DAT_80000008`
unchanged, `DAT_8000184c` gets the muted bits, no crash.

### V4 FLASHED → track stays FULLY audible (no muting) but LED/UI mute indicator toggles.
Confirms: `FUN_40004dbc` **is** the gate (clearing the D5 mute bit un-mutes completely), and
`_DAT_80000008` bit 8+t **is** the per-track mute flag on the FUNC+TRACK path.  But V4's
per-frame `DAT_8000184c |= muted` did NOT fade the AMP — that byte is a one-shot STOP command;
re-writing it every frame just re-arms `FUN_400068e4`'s "restart release from current level"
(and `pcurs+0xc = 0`, the position reset) each tick → no convergence, sample keeps playing.

### V5 — edge-triggered note-off + maintained release state
`patch_softmute.s` V5: same hook (`move.l 0x80000008,D5` @0x40004dc6).  Cave (132 B): shadow
of the muted mask in patch RAM `0x80006c66`; unless SOLO:
  - `newly = muted & ~shadow` (0→1 edge) → `jsr FUN_40008f84(t)` **once** per newly-muted track
  - every frame: `DAT_8000184a |= muted` (maintain the release-state bit; frame_builder
    @0x4000bd3c consumes+re-arms it, the way a held note-off is maintained)
  - `D5 &= ~(muted<<8)` → `FUN_40004dbc` keeps the frame level words → FX inserts reach the mix
emu: `_DAT_80000008` untouched, `DAT_8000184a` bit set on the edge + maintained frame 2,
`FUN_40008f84` called once (edge only).  183 B changed vs stock.  **Not yet hardware-tested.**

If V5 STILL leaves the sample audible → the note-off (`DAT_8000184a`→frame_builder `cmd|0x10`)
does not close the AMP for a freely-looping voice, and the fix has to write the AMP envelope
segment registers directly (`pcurs[t]+0x20..0x44`, base 0x80004f1c stride 0x54 +bank 0x2a0) or
the per-voice frame `vframe[0x80+t]` — a bigger job, and possibly a DSP-side one.  That would
be the point to reassess whether this is worth continuing.

### V5 FLASHED → FX-tail goal WORKS.  Dry hard-cuts (clean, no click) even with AMP REL maxed
→ the note-off (`DAT_8000184a`→`cmd|0x10`) does a fast declick fade, does NOT run the AMP
envelope RELEASE segment.  User: this is fine ("fast but smooth"), ship it — it's the
Digitakt "quiet mutes" behaviour.  Residual: a ~1-frame trig attack blip on muted tracks.

### V6 (SHIP CANDIDATE) — `python3 tools/build_softmute.py [VERSTR]`
`patch_softmute.s` = two hooks, one cave (228 B @0x400d7400):
  - `pre`   @ FUN_40004dbc 0x40004dc6 (`move.l 0x80000008,D5`): unless SOLO — for muted tracks,
    0→1 edge → `FUN_40008f84(t)` once; every frame `DAT_8000184a |= muted` + `D5 &= ~(muted<<8)`
    (keep the frame level words → FX inserts ring).  shadow @ 0x80006c66.
  - `pre_v` @ FUN_40005178 0x40005178 (voice-cmd queue, prologue `4feffff4 48d7001c`): drop
    "start" commands (bit 0x80 set, bit 0x10 clear) for a muted audio track → **no trig blip**.
    STOP/retrig (0x10 set) and unmuted tracks pass through.  Returns D0=1.
`_DAT_80000008` untouched → MUTE LED + pattern-stored mute state still work.  SOFT MUTE
ALWAYS ON (no PERSONALIZE toggle — deferred; menu-array surgery is brick-risky).
emu-verified: hook1 sets the release bit / edge note-off; hook2 drops muted-START, passes
STOP/retrig/unmuted.  Manual-trig fix bytes identical to `build_trigscale_only.py`.

**Branding**: version string field is a fixed **10 chars** — `1.40C_KYOTI` (11) does NOT fit.
build_softmute.py defaults to **`140C_KYOTI`** (drop the `_`).  Pass a different 10-char
string as `argv[1]` to change it.  Internal version code `0178` stays intact.

Outputs: `out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.{syx,bin}` (version "140C_KYOTI", EFT ok,
259 B changed vs stock).  **Not yet hardware-tested.**
- If good → add the PERSONALIZE toggle for a shippable gated build (patch_notimer-style: add
  "SOFT MUTE" as a 3rd relocated menu entry; `moveq #15`→`#18`; `lbl_/get_/set_softmute`
  writing 0x800000dc) and fold into `build.py` (STUBS `("patch_softmute", 0x400d7b40)` +
  DETOUR `(0x400836d8, "patch_softmute", "pre", "apply-mute funnel")`, EXPECT `4fefffc448d77cfc`).
- QUICK MUTE screen edge: it also sets `_DAT_46c7ff64` on a confirm/page action — with our
  `_DAT_8000184e` bit set too, S7 says the frame builder keeps emitting (voice stays alive).
  May want the detour to also clear `_DAT_46c7ff64` bit `1<<(t+8)` for soft-muted tracks.
- Optional: neutralise the 45-frame `46c7dfba` release watchdog for soft-muted tracks so a
  max-REL setting genuinely sustains.

### Does the fix also cover QUICK MUTE?  — almost certainly yes
Track-key handler for the mute modes = `FUN_40040250(track, evt)` (0x40040250): does double-tap
/ hold detection (`_DAT_400c0aac` last-key, `_DAT_460d5de0` hold count) then:
 - single press  → `FUN_40083ab4(track, 1)` → sets `_DAT_460fab40` bit + `FUN_400836d8()`
 - double-tap    → `FUN_40083ab4(track, 3)`
 - evt==2        → `FUN_40083ab4(track, 2)`
 - else          → `FUN_40083e40(track, ...)` (unmute) → `FUN_400836d8()`
This is the same handler for FUNC+TRACK live mute AND the QUICK MUTE screen — both land on
`FUN_400836d8` + the `0x?040` voice command. So a detour on `FUN_400836d8` covers both by
default. The QUICK MUTE screen additionally has `FUN_400834d8` (→ `_DAT_46c7ff64`) and
`FUN_40083488` (→ `_DAT_46c7fe22` → `_DAT_8000184e` via `FUN_4000ac18`) wired to a
page-descriptor / confirm action — need to check during patch build whether either independently
hard-mutes on top of the `0x?040` path (if so, one extra small hook; if the `0x?040` command is
itself the instant cut, nothing more needed). Keeping QUICK MUTE *instant* while changing only
FUNC+TRACK would actually be the harder option (they share the code path).

---

## Session 9 — STATE OF PLAY (read this first next time)

### SOFT MUTE — WORKING, shipped as a test build.  `140C_KYOTI`.
Goal: audio-track mute should let delay/reverb tails ring out instead of the stock instant
post-FX cut.  **Done** (V6).  Muting an audio track (FUNC+TRACK / MIXER menu / QUICK MUTE) now
behaves like a single STOP for that track: dry cuts with a fast clean fade (~few ms, no click,
does NOT honour the AMP REL knob), the track's FX inserts ring their tails, and a muted track's
sequencer trigs are silent.

**How** — `tools/patch_softmute.s`, two hooks in one 228-B cave @0x400d7400, built by
`tools/build_softmute.py` (folds in the EFT wrap + make_bin + `-V`).  Mechanism: the per-frame
mute gate is **`FUN_40004dbc`** — it reads **`_DAT_80000008`** (bit 8+t = track t muted) and
`clr.w`s that track's level words in the DSP frame double-buffer.
  - `pre`   @ 0x40004dc6 (`move.l 0x80000008,D5`): unless SOLO — for muted tracks, keep the
    frame level words (`D5 &= ~(muted<<8)`), maintain `DAT_8000184a |= muted` every frame, and
    `FUN_40008f84(t)` once on the 0→1 edge (shadow byte @ 0x80006c66).
  - `pre_v` @ 0x40005178 (voice-cmd queue): drop "start" commands (bit 0x80 set, 0x10 clear)
    for a muted audio track.
`_DAT_80000008` is never modified → MUTE LED + pattern-stored mute state keep working.

**Flashable:** `out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.{syx,bin}` — also carries the MIDI
manual-trig fix (`patch_trigscale`, bytes identical to Build A / PLAYSFREEFIX).  Version field
`140C_KYOTI` (10-char max; `1.40C_KYOTI` = 11, won't fit).  259 B changed vs stock, all in the
3 hook sites + 2 caves.  ALWAYS ON (no PERSONALIZE toggle).  Revert = flash stock 1.40C.

**Flash history this session (all on the user's Octatrack MKI — the only unit used for
on-hardware testing in this repo; the user does not own a MKII):**
V1/V2/D1 hooked `FUN_400836d8` / its `0x?040` voice command — no effect (not the mute).
V3 hooked `FUN_40030c60` (the +0x28 mute-flag key handler) — no effect (not the FUNC+TRACK path).
V4 hooked `FUN_40004dbc` + per-frame `DAT_8000184c` — track stayed fully audible (184c is a
one-shot; per-frame re-write stutters).  V5 = V4 + edge note-off/maintained `DAT_8000184a` —
**FX tails rang, dry cut fast+clean, faint 1-frame trig blip**.  V6 = V5 + `pre_v` trig-blip
fix + `140C_KYOTI` branding.  **V6 not yet flashed.**

### NEXT SESSION — pick up here
1. **User flashes V6.**  Confirm: FX tails ring, no trig blip, boot screen says `140C_KYOTI`,
   MIDI manual-trig fix still works, SOLO still hard-cuts, other tracks unaffected.
2. **SOLO extension** (user asked; not started).  Make solo also let the non-soloed tracks'
   FX tails ring.  Same function (`FUN_40004dbc`), same technique — V6 currently bails on
   `tst.b 0x80000037` (SOLO flag).  Plan: emulate the SOLO path, confirm whether soloing sets
   the same `_DAT_80000008` mute bits for non-soloed tracks (likely) and whether
   `FUN_40004dbc`'s solo branch (0x40004dd4) uses the same frame-word layout as the normal
   branch (0x40004e3a).  If yes → remove the SOLO bail + make `pre_v` treat solo-muted tracks
   as muted.  Solo mask may instead be `_DAT_8000000c` (LED painter `FUN_40083eb0` reads it in
   the solo branch @0x40083eee; `_DAT_80000037` setters @0x40065172/8e, 0x400654e0/fc).
   Estimate: 1 emu pass + a V7 build.  Low brick risk.
3. **PERSONALIZE toggle** (deferred).  Add "SOFT MUTE" as a menu entry writing `0x800000dc`
   (patch_softmute.s already has the `.ifndef ALWAYS_ON` gate on that byte).  patch_notimer-
   style: relocate the 3 PERSONALIZE arrays (`OLD_LBL 0x400b2a34` / `OLD_GET 0x400b2a74` /
   `OLD_SET 0x400b2ac0`, 16 entries) to a cave with 17, repoint the REFS (see build.py lines
   70-78), bump `moveq #15` @0x40068fb2 → `#16`.  Provide `lbl_/get_/set_softmute` (glyphs
   0x400b5e90 on / 0x400b5e8e off).  Menu-array surgery is the one thing that has bricked this
   unit before — do it carefully, verify the 16 stock entries still render.
4. Optional refinements: dry-decays-over-REL (needs writing AMP env segment regs
   `pcurs[t]+0x20..0x44` @0x80004f1c stride 0x54 +bank 0x2a0 directly — bigger); cap the
   number of simultaneous ringing tails in solo.

### Session 9 tooling (all uncommitted)
`tools/patch_softmute.s`, `tools/build_softmute.py`, `tools/emu_mute.py` (11 scenarios — most
test the V1/V2 dead-end approach on `FUN_400836d8`, kept as the investigation record; the
`_softmute_patch()` helper now points at the V6 hook), `tools/GhidraMute{1..8}.java`,
dumps `out/ghidra/GhidraMute*_session9.txt` + `out/ghidra/emu_mute_session9.txt`.
The scattered V1-V5 narrative above this section is the working log; THIS section is current.

---

## Session 10 — MUTE MODE PERSONALIZE entry (test build, not yet flashed)

### What shipped this session
A new **test build** that puts SOFT MUTE behind a PERSONALIZE toggle instead of ALWAYS_ON.
The shipped V6 artifacts (`out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.*`, ALWAYS_ON) are **untouched**.

  `python3 tools/build_mutemode.py`  ->
     out/OCTATRACK_OS1.40C_MUTEMODE.syx   (MIDI DIN)
     out/OCTATRACK_MUTEMODE.bin           (CF card, PROJECT -> OS UPGRADE)
     version string  `140C_KYOTI`
     589 bytes changed vs stock 1.40C

Stock 1.40C  +  patch_trigscale (MIDI manual-trig fix, byte-identical to Build A)
             +  patch_softmute V6 hooks, assembled **gated** (no ALWAYS_ON)
             +  patch_mutemode (the menu entry)

### PERSONALIZE menu deep dive (full writeup: this section + `out/ghidra/GhidraMenu1_session10.txt`)
Renderer `FUN_40068e00`, input `FUN_40068fd0`, list-init `FUN_40068fa8`.  Three parallel
16-entry arrays, contiguous, followed by unrelated data -> not extendable in place:
  labels  0x400b2a34   `char*`             ref: `move.l #imm,%d5` @0x40068efe  (IMMEDIATE, not lea)
  getters 0x400b2a74   `char*(*)(void)`    ref: `lea …,%fp`       @0x40068f0a
  setters 0x400b2ac0   `void(*)(int d,int wrap)`  refs: `lea …,%a0` @0x40069022 / 0x4006903e / 0x40069056
  (LED-BRIGHT value strings 0x400b2ab4 — LOW/MID/MAX — addressed absolutely, not relocated)
A **getter just returns a `char*`** drawn in the right column (x=0x4d).  Checkbox items return
a 1-glyph string (0x400b5e90 on / 0x400b5e8e off); **LED BRIGHTNESS returns "LOW"/"MID"/"MAX"** —
i.e. a multi-value text option is already a stock, shipping pattern (getter `FUN_40068c80`,
setter `FUN_4006907c`).  Setter ABI: `delta` @4(sp), `wrap` @8(sp) — [YES]=(+1,wrap), [RIGHT]=
(+1,clamp), [LEFT]=(-1,clamp).  Same ABI as `set_notimer`.
Count `FUN_40068fa8`: `moveq #15,%d1 ; sub %d0,%d1`, `%d0 ∈ {0,-1}` from `tst.l 0x46c8d18c`
=> **15 items, or 16 when 0x46c8d18c != 0**.  `0x46c8d18c` is the boot-time MKI/MKII probe
(set to 1 on the MKII path, 0 on the MKI) — `LED BRIGHTNESS` (index 15) is the one item gated
on it, which is why the user's **MKI shows 15 PERSONALIZE items, no LED BRIGHTNESS**.
**Nothing in the firmware keys off an absolute PERSONALIZE index** — every ref to the menu's
cursor/scroll/count/rows globals (0x460e4670/68/78/74) lives inside the 0x40068e00..0x40069074
block.  So the splice position for a new entry is entirely free.

### The surgery (build_mutemode.py — proven build.py technique)
1. Copy all 3 arrays into the free cave (LBL 0x400d7700 / GET 0x400d7760 / SET 0x400d77c0,
   68 B each) with **MUTE MODE spliced at index 2** — right after "PREVIEW WITHOUT FX":
      [0] QUANTIZE LIVE REC  [1] PREVIEW WITHOUT FX  [2] MUTE MODE  [3] MUTE FOCUSES TRK …
      … [15] EXT LEN GRID-REC  [16] LED BRIGHTNESS  (stays last, stays behind the MKII gate)
2. Repoint the 5 refs from the linker symbol table (guarded on the original bytes).
3. `moveq #15` @0x40068fb2 -> `moveq #16`  =>  16 items on the MKI (15 stock + MUTE MODE,
   LED BRIGHTNESS still hidden), 17 on a MKII.  Adds exactly the one new item on either.
`patch_mutemode.s` = `lbl_mutemode` "MUTE MODE" + value strings "OT"/"OT+FX" + `val_tbl` +
`get_mutemode` (return `val_tbl[clamp(0x800000dc,0,NMAX)]`) + `set_mutemode` (clamp on
[LEFT]/[RIGHT], wrap on [YES], over [0,NMAX]).  `.equ N_MODES,2` — bump to 3 + add `vm_2` for
the 3rd mode later.

### Flag word 0x800000dc == patch_softmute's GATE
0 = "OT" (stock instant post-FX cut)   1 = "OT+FX" (soft mute: dry cuts, FX inserts ring).
Free battery-backed PERSONALIZE word; default 0 => a fresh flash is stock.  OS upgrade resets
PERSONALIZE.  Persistence across power cycles is inferred, not yet hardware-verified — TEST IT.

### Two fixes to patch_softmute.s this session (affects a fresh build_softmute.py too)
- **gate now reads the 32-bit word** (`move.l GATE,%d0 ; cmpi.l #1,%d0 ; bne`), was
  `move.b GATE,%d0 ; beq`.  The `.ifndef ALWAYS_ON` gate path was never on hardware (V1–V6
  all ALWAYS_ON) and had a **big-endian bug**: the LED-BRIGHTNESS-style setter writes a full
  word, so `move.b` at 0x800000dc read the MSB (always 0) — the soft path would never engage.
  Also: `!= 1` (not `!= 0`) so a future mode 2 falls to the stock cut until implemented.
- **`pre` movem fixed**: `movem.l %d0-%d3/%a0` (5 longs = 20 B) into a `lea (-0x10,%sp)` frame
  (16 B) scribbled 4 B of `FUN_40004dbc`'s frame every call — latent in V1–V6.  `a0` is unused
  in `pre`; dropped it -> `movem.l %d0-%d3`.  A fresh `build_softmute.py` (ALWAYS_ON) now
  differs from the flashed V6 by exactly these 2 mask bytes (010f->000f, ×2).  `pre_v` was
  already safe (3 longs into 16 B — wasteful, not corrupting; left as-is).

### Verified (static + Unicorn) — `tools/emu_mutemode.py` : ALL GOOD
relocated arrays = stock[0:2]+MUTE MODE+stock[2:16]; 5 refs repointed; `moveq #16`; 3 detours
hit their symbols; `get_mutemode` returns OT/OT+FX for MUTE_MODE ∈ {-1,0,1,2,99}; `set_mutemode`
clamps/wraps correctly over [0,1]; gated `pre` engages the soft path only for MUTE_MODE==1.

### NEXT — hardware test on the MKI
Flash `out/OCTATRACK_MUTEMODE.bin` (CF) or `.syx` (MIDI).  Confirm:
1. PERSONALIZE lists **16 items**, `MUTE MODE` is 3rd (after PREVIEW WITHOUT FX), shows `OT`.
2. The other 15 stock items still render + behave (esp. the neighbours: QUANTIZE LIVE REC,
   PREVIEW WITHOUT FX, MUTE FOCUSES TRK).
3. LEFT/RIGHT/YES cycle `OT` <-> `OT+FX`.
4. `OT`  -> mute = stock instant cut.   `OT+FX` -> mute lets FX tails ring, dry cuts clean,
   no trig blip; SOLO still hard-cuts; MIDI manual-trig fix still works.
5. Set `OT+FX`, power-cycle -> setting persists.  OS re-flash -> back to `OT`.
6. Boot / SYSTEM STATUS shows `140C_KYOTI`.
Then: 3rd mute mode (user has a design in mind — separate session); SOLO extension still open.

### Session 10 tooling (uncommitted)
`tools/patch_mutemode.s`, `tools/build_mutemode.py`, `tools/emu_mutemode.py`,
`tools/GhidraMenu{1,2}.java`, dumps `out/ghidra/GhidraMenu{1,2}_session10.txt`.
`tools/patch_softmute.s` modified (2 fixes above).

---

## Session 11 — SOFT MUTE extended to SOLO (patch_softmute V7, in the MUTEMODE test build)

> **Branch note (2026-09-01):** everything from here on (V7 solo, Session 12 DT) is
> **emulator-verified only, never flashed**. It was moved off `main` to the
> **`wip/mute-mode`** branch. `main` ships `patch_softmute.s` V6b (the Session-10
> flashed build). To continue this work: `git checkout wip/mute-mode`.

**MKI HW status: the Session 10 MUTEMODE build flashed and works well.** V7 rebuilds it with
solo support folded into the OT+FX mode — no separate toggle.  `python3 tools/build_mutemode.py`
-> same outputs, version `140C_KYOTI`, now **630 B vs stock**.

### The frame builder's SOLO branch (deep dive: `out/ghidra/GhidraSolo{1,2}_session11.txt`)
`FUN_40004db8` (hook site 0x40004dc6) branches on **`tst.b 0x80000037`** (the SOLO-mode flag,
set to 1 @0x400654de / cleared @0x400654fa; the solo-engage handler does NOT touch
`_DAT_80000008`).  `_DAT_80000008` layout: **bits 0..7 = per-track SOLO, 8..15 = MUTE,
16..23 = CUE** (confirmed via the AUDIO-CC-OUT emit in case 'L': CC49=mute bit8+t, CC50=solo
bit t, CC51=cue bit16+t).
- **not-solo branch** (0x40004e3a): per track, `clr.w` the mute-gated frame word iff bit 8+t set.
- **solo branch** (0x40004dd4): per track — bit t set (SOLOED) -> keep both words; else the
  words are AND-ed with **D1 = `(D5.low8 == 0) ? -1 : 0`** (the "is anything soloed?" mask) ->
  silenced; a non-soloed **and muted** track -> `clr.l` instead.
  It only ever tests D5 bits 0..15 (D3 starts at 0), never the cue bits.

### V7 mechanism (`tools/patch_softmute.s`, one shadow byte, no new RAM)
`pre` now computes a single **`silenced`** audio-track set per frame (D2, bits 0..7):
- not solo: `silenced = mute mask`  ->  clear those mute bits from D5 (as V6).
- solo + >=1 soloed: `silenced = ~soloed & 0xFF`  ->  **`D5 &= 0xFFFF0000`** so every track
  hits the "& D1" keep path AND D1 becomes -1 -> FUN_40004db8 keeps *every* track's frame
  words -> all FX returns ring.
- solo + none soloed: `silenced = 0` (stock; nothing cut yet).
Then (shared path): shadow-edge -> `FUN_40008f84(t)` once per newly-silenced track;
`REL_STATE |= silenced` every frame.  MUTE MODE == OT -> `clr.b SHADOW` + bail (byte stock).
`pre_v` drops a bare "start" voice-cmd for a silenced track: muted, OR (solo active AND
>=1 soloed AND this track not soloed).  Retrigs (stop bit set) always pass.
The shadow at 0x80006c66 is **reused** (widened from "muted mask" to "silenced set"); it is
now written every frame (incl. 0) so an OT->OT+FX switch or a solo release never leaves it
stale.  `pre` movem stays `%d0-%d3` (4 longs / 16 B — the Session 10 fix).

Behaviour: soloing overrides mute (stock); a non-soloed track's dry fades (note-off, does NOT
honour AMP REL) while its FX inserts ring; its trigs are silent while solo is held; releasing
solo resumes on the next trig (a held note does not come back — same trade-off as direct
soft mute, which the user is happy with).

Cave layout (build_mutemode.py): patch_softmute V7 330 B @0x400d7400; patch_mutemode moved to
0x400d7600; menu arrays 0x400d7700/60/c0; patch_trigscale 0x400d7b00.  (ALWAYS_ON build =
288 B; a fresh `build_softmute.py` would now also carry V7 solo support — the shipped V6
`OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.*` on disk are untouched.)

### Verified — `tools/emu_solo.py` : ALL GOOD (25 checks)
Runs the real image bytes.  `pre`: not-solo mute path unchanged; solo+1-soloed -> silenced =
other 7, REL_STATE=0xFE, D5 bits 0..15 cleared, one note-off each; solo+none-soloed -> no-op;
solo+also-muted -> still handled; edge de-dupe; OT bail clears shadow; OT->OT+FX keeps the
first note-off.  `pre_v`: drops muted / solo-non-soloed starts, passes soloed / retrig / OT.
`tools/emu_mutemode.py` still ALL GOOD.

### NEXT — hardware test on the MKI (in addition to the Session-10 checklist)
1. Solo a track with `MUTE MODE = OT+FX`: the non-soloed tracks' FX (delay/reverb) tails ring
   out instead of cutting instantly; their dry stops; their trigs are silent while solo held.
2. Release solo -> non-soloed tracks resume (on their next trig).
3. Solo a **muted** track -> it plays (solo overrides mute), stock behaviour.
4. `MUTE MODE = OT` -> solo cuts instantly, exactly stock.
5. Re-confirm the direct-mute soft behaviour + MIDI manual-trig fix are unregressed.
Then: the 3rd mute mode (user has a design in mind).

### Session 11 tooling (uncommitted)
`tools/GhidraSolo{1,2}.java` + dumps `out/ghidra/GhidraSolo{1,2}_session11.txt`,
`tools/emu_solo.py`.  `tools/patch_softmute.s` rewritten V6->V7.  `tools/emu_mutemode.py`
updated (REL_STATE write detected via a mem-write hook, not a hard-coded address).

---

## Session 12 (2026-09-01) — "DT" MUTE MODE (3rd option; built, emu-verified, NOT flashed)

**User away from the MKI for ~2 weeks — build + emulate only this session.**

### What "DT" is (user's spec, clarified mid-session)
A third `MUTE MODE` value after `OT` and `OT+FX`.  DT = **a pure Digitakt-style trig mute**:
muting an audio track (or a track silenced by SOLO) does **nothing to the voice engine** —
the voice that is already sounding keeps playing under **its own amp envelope** exactly as if
you never muted (fades to silence, sustains, or loops forever, whatever ATK/HOLD/REL +
LOOP say).  The **only** effect of the mute is that **new sequencer/manual trigs are
suppressed** until unmute.  FX rings naturally because the whole track keeps running.
Explicitly **NOT** wanted: forcing the voice into its release phase on mute (that was the
earlier design guess — rejected by the user).

### Why this is low-risk (vs the 6 HW iterations OT+FX needed)
DT = **V4's hardware-confirmed behaviour** ("clear the D5 mute/solo bits -> FUN_40004db8
keeps every DSP-frame level word -> track stays fully audible, voice + FX untouched") **+
V6's hardware-confirmed `pre_v`** ("drop bare 'start' voice-cmds for a silenced track ->
no new trigs") **MINUS V5's note-off** (`FUN_40008f84` / `DAT_8000184a`).  Both halves are
already proven on the user's MKI; DT just runs them together with *less* intervention than
OT+FX.  No voice-struct / envelope / DSP poking at all.

### The patch (`tools/patch_softmute.s`, compile-gated behind `--defsym DT_MODE=1`)
Only difference from OT+FX, inside the existing `pre` (@0x40004dc6) + `pre_v` (@0x40005178):
| step | OT+FX (GATE==1) | DT (GATE==2) |
|---|---|---|
| compute `silenced` set, clear D5 mute/solo bits (keep frame words) | yes | yes (identical) |
| `FUN_40008f84(t)` note-off on the shadow edge | yes | **no** |
| maintain `DAT_8000184a \|= silenced` every frame | yes | **no** |
| `pre_v` drops bare-"start" voice-cmds for `silenced` tracks | yes | yes (identical) |
`pre` gate now `beq p1_active` on `#1` **or** `#2`; the DT branch at `p1_edge` does
`clr.b SHADOW` (so a live DT->OT+FX switch re-asserts every note-off) + `bra p1_done`.
`pre_v` gate widened `subq.l #1 ; cmpi.l #1 ; bhi v_stock` (accept modes 1,2).
All new code is `.ifdef DT_MODE` — a plain `build_mutemode.py` is **byte-identical** to
before (verified: md5 `6d9ff8ba…` unchanged after the source edits).

### Menu (`tools/patch_mutemode.s`, also `.ifdef DT_MODE`)
`N_MODES 2->3`, value strings `OT / OT+FX / DT`, `val_tbl` 3rd entry `vm_2`.  Getter/setter
already parametric on `NMAX` — clamp/wrap now over [0,2].

### Build — `python3 tools/build_mutemode_dt.py [VERSTR]`  (default `140C_KYOTI`)
Copy of `build_mutemode.py`; assembles patch_softmute + patch_mutemode with `--defsym
DT_MODE=1`; **separate outputs** so the Session-10/11 artifacts are untouched:
  `out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx`  (MIDI DIN)
  `out/OCTATRACK_MUTEMODE_DT.bin`          (CF card, PROJECT -> OS UPGRADE)
659 B changed vs stock; 394 B differ vs `mainos_mutemode.bin`, **all confined to the
patch_softmute cave + patch_mutemode cave + relocated menu arrays + the pre_v detour word**
(build script asserts this — OT/OT+FX/solo paths bit-unchanged).  Caves: patch_softmute
368 B @0x400d7400, patch_mutemode 130 B @0x400d7600, menu arrays 0x400d7700/60/c0,
patch_trigscale 62 B @0x400d7b00 — no overlap, ends < 0x400d7c3c.  Manual-trig fix bytes
identical to `build_trigscale_only.py`.  EFT round-trip OK, version `140C_KYOTI`.

### Verified — `tools/emu_dt.py` : ALL GOOD (runs the real DT image bytes)
- menu: `get_mutemode` -> OT/OT+FX/DT for MUTE_MODE ∈ {-1,0,1,2,3,99}; `set_mutemode`
  clamps [0,2] on LEFT/RIGHT, wraps on YES.
- DT `pre` (gate 2): D5 mute/solo bits cleared, **no `FUN_40008f84`**, `DAT_8000184a`
  untouched, `SHADOW` cleared; solo+1-soloed -> D5 bits 0..15 cleared; solo+none -> no-op.
- regressions in the DT image: OT+FX `pre` (gate 1) still note-offs + maintains REL_STATE;
  OT `pre` (gate 0) bails with the mute bit left set.
- DT `pre_v` (gate 2): drops muted / solo-non-soloed bare starts; passes retrig / soloed /
  unmuted; OT+FX still drops, OT still passes.
`tools/emu_solo.py out/mainos_mutemode_dt.bin` : ALL GOOD (OT+FX + solo unregressed).
(`tools/emu_mutemode.py` stays pointed at `out/mainos_mutemode.bin` — its N_MODES=2 cases
are meant for that image; run `emu_dt.py` for the DT build.)

### NEXT — hardware test on the MKI (when the user is back with the unit)
Flash `out/OCTATRACK_MUTEMODE_DT.bin` (CF) or `.syx` (MIDI).  In addition to re-running the
Session 10/11 checklists (OT, OT+FX, solo, MIDI manual-trig fix, `140C_KYOTI` boot string):
1. PERSONALIZE -> MUTE MODE now cycles `OT` <-> `OT+FX` <-> `DT` (LEFT/RIGHT/YES).
2. `DT`, one-shot sample, medium REL: mute mid-note -> the note **finishes its own amp
   release** (not the fast OT+FX declick), FX rings; the muted track's trigs are silent;
   unmute -> silent until the next trig.
3. `DT`, LOOP sample, HOLD/REL at max: mute -> **the loop keeps sounding indefinitely**;
   new trigs suppressed; unmute -> loop still going, trigs resume.
4. `DT` + SOLO: non-soloed tracks' currently-playing voices ride out their envelopes; their
   trigs silent while solo held; release solo -> resume on next trig.
5. Switch `DT` -> `OT+FX` while a DT-muted voice is ringing -> it should get the OT+FX
   note-off on the next frame (the `clr.b SHADOW` re-assert).
If DT leaves a *plain FLEX one-shot* audible with no envelope motion at all (i.e. the voice
never advances because something about mute stalls the per-frame updater) -> unlikely
(FUN_40004db8 is downstream of the voice updater) but the fallback is to also `clr` the
`46c7ff64` output-mute bit for DT tracks.

### Session 12 tooling (uncommitted)
`tools/build_mutemode_dt.py`, `tools/emu_dt.py`.  `tools/patch_softmute.s` +
`tools/patch_mutemode.s` gained `.ifdef DT_MODE` blocks (plain builds byte-unchanged).
`build_mutemode_dt.py` links its stubs as `out/patch_*_dt.elf` (distinct intermediates -- it
never clobbers `build_mutemode.py`'s `out/patch_*.elf` that emu_mutemode / emu_solo read
back).  `tools/emu_solo.py` now picks `patch_softmute_dt.elf` when handed a `*_dt.bin` image.
Outputs `out/OCTATRACK_*MUTEMODE_DT.*`, `out/mainos_mutemode_dt.bin`, `out/elek_mutemode_dt.bin`.
Run order no longer matters: `emu_mutemode.py` on the 2-mode image, `emu_dt.py` +
`emu_solo.py out/mainos_mutemode_dt.bin` on the DT image, all ALL GOOD in any sequence.

---

## Session 13 (2026-09-01) — SCOPING ONLY: "auto-remove an emptied trigless lock" (no work done)

**User idea, feasibility-scoped this session. No RE, no build. This block is the brief for
whoever picks it up.**

### The wish (user's words, lightly tightened)
In **LIVE REC** mode, with the sequencer running (recording), the user erases parameter
locks with **`[NO]` + knob** (the live "clear as the playhead passes" erase). Today, once
every p-lock has been erased from a step that only ever held p-locks (a "trigless lock" /
dim-red lock), **the lock stays lit on the 16-step row** — pure visual noise. Wish: when an
erase pass takes a trigless lock's lock count from 1 -> 0, the trigless lock itself is
**removed from the pattern** (LED off, step inert).

Constraints from the user:
- **Only** the pure-p-lock trigless lock. Do **not** touch: trigless trigs that retrig
  LFOs / one-shot FX envelopes ("green"), sample/audio trigs, MIDI trigs, one-shot trigs,
  recorder trigs, slide trigs, anything else.
- Multi-pass semantics: 2 params locked on a step -> one erase pass clearing one param
  leaves the lock lit; the second pass clearing the last param deletes it.
- The user can still **place** an empty trigless lock by the normal methods and it must
  persist — "empty" trigless locks are legal. The deletion fires **only** as the 1->0
  transition of an erase op, never as a global sweep of empty locks.
- Gesture is specifically the `[NO]`+knob **LIVE REC** live-erase. (Earlier in the chat the
  user said GRID REC by mistake, then corrected to LIVE REC.) Whether GRID-mode erases
  (`[TRIG]`+`[NO]`, CLEAR) should also trigger the deletion is an **open user decision** —
  default to narrowest (LIVE `[NO]`+knob only).

### Verdict: FEASIBLE, but a real RE project in an untouched subsystem
Comparable in size to the soft-mute effort: **~3-5 sessions + HW iteration + exported test
banks**. Brick risk LOW (data-model read + one hook; no PERSONALIZE menu-array surgery).
The hard part is *behavioural correctness* — the "this trigless lock now holds nothing"
predicate must never fire on a trig the user wanted to keep.

### What we already have (starting material)
| Piece | State |
|---|---|
| Project DB base `_DAT_46c82456`, pattern stride `0x18b2` | solid, used throughout |
| Per-track sequenced-data region `base + pat*0x18b2 + trk*0xc` near `+0x8f385` | named "trigs/params" in the engine map (NOTES ~L197); **internal layout NOT mapped** |
| Trig->voice (`FUN_400977cc`, `FUN_40005030`) | reads "which sample" per step; does not expose the trig-type / p-lock bytes |
| Trig-LED painter family (`FUN_40083eb0/fdc`, `FUN_400132c4(id,state)` -> 2-bit LED buf `0x460ba98c`) | mapped for **scene** trig lighting only, not normal trig-type LED logic |
| Scene p-lock blocks `base + pat*0x18b2 + scene*0x100 + 0x8f3e2`, `0x20`/param-group stride | shape hint only; scenes != per-step p-locks |

`COVERAGE.md`: "Trig types / p-locks / sample locks" and "conditional locks / micro timing"
are both **untouched (unmapped)**. No RE yet on where a step's p-lock bitmap lives, how the
trig-type flags are encoded, or which handler clears a p-lock live.

### Work plan (when someone picks this up)
**Phase 0 — model the per-step trig data (1-2 sessions).** Export-and-diff on the MKI
(mandatory per START_HERE: real exported banks only). User builds targeted patterns:
a pure trigless lock w/ 2 p-locks; a trigless-trig w/ LFO retrig + 1 p-lock; a manually
placed empty trigless lock; a sample trig w/ p-locks; recorder + MIDI trig rows. Diff the
blobs to pin:
  1. trig-type flag bits (sample / trigless-trig-with-retrig / pure-lock / one-shot / slide;
     plus the separate recorder-trig and MIDI-trig layers),
  2. the "which params are locked" bitmap (audio pages + sample-slot lock + LFO p-locks +
     FX p-locks — OT locks span several param pages),
  3. anything else attachable to a lock step (trig condition, micro-timing, slide).

**Phase 1 — find the LIVE-REC `[NO]`+knob p-lock-clear handler + hook it (1 session + emu).**
One detour, *after* the clear: if `trig_type == pure trigless lock` AND locked-bitmap `== 0`
AND no sample-slot lock AND nothing else attached -> clear the step's trig-type flag. LED
painter + sequencer then ignore it for free. Predicate must be **conservative**: delete only
when the step is unambiguously a bare lock; when in doubt, keep it.

**Phase 2 — build + HW iterate (1-2 flash cycles).** Same build scaffold as the mute work
(guarded binary patch, cave, EFT round-trip, `140C_KYOTI`).

### Risks / open items
- **Predicate is the whole ballgame.** If trig-type flag and p-lock bitmap aren't
  independent bits, or we miss a lock category (LFO-designer lock, FX lock, condition),
  we could delete a wanted trig. Conservative predicate + HW verification mitigate.
- **Confirm the gesture/handler.** Rock-solid OT live-erase is `[NO]`+knob in LIVE REC;
  pin that exact routine in Phase 1.
- **User decision:** LIVE `[NO]`+knob only, or also grid `[TRIG]`+`[NO]` / CLEAR? Default
  narrowest.
- **Sample-slot-only lock:** does a trigless lock whose only remaining lock is a sample
  lock count as "empty"? Default: treat sample lock as a lock -> keep the trig.

### Cheaper fallback (offered, not chosen)
Cosmetic-only: patch the trig-LED painter to not light a trigless-lock step whose lock
bitmap is empty. Zero data risk, reflash-reversible, kills the visual-noise complaint — but
the trig still exists in the pattern (saved, occupies the step, reappears on edit). Still
needs Phase 0's data model, so not free; could ship first to de-risk. User did not pick this
— they want actual deletion.

### PERSONALIZE toggle?
Not discussed. If this ships it would likely want to be opt-in (a 4th behaviour alongside
MUTE MODE, or its own entry) — but that's menu-array surgery again (the one thing that has
bricked the MKI before). Decide later.

---

## Session 14 (2026-09-01) — RE for a 4th MUTE MODE: "instant cut + FX tails + resume at playhead"

**Branch `wip/mute-mode`. RE + emulation only — nothing built or flashed. User away from MKI ~2 wks.**

### The ask
A mode that combines the best of OT and OT+FX: mute cuts the dry **instantly**, the track's
FX-insert tails **ring out**, AND unmute **resumes the sample where the playhead would be**
(like stock OT), not "silent until the next trig" (OTFX-T / DT-T).  Menu goes 3 -> 4 values.

**Names decided by the user (2026-09-01).**  Taxonomy: no suffix = unmute resumes at the
playhead (like OT); `-T` = trig-mute (only a new trig restarts).

| MUTE MODE value | `GATE` (0x800000dc) | behaviour |
|---|---|---|
| `OT`     | 0 | stock -- instant cut, FX tails die, unmute resumes at playhead |
| `OTFX`   | 1 | **new (this session)** -- instant dry cut, FX tails ring, unmute resumes at playhead |
| `OTFX-T` | 2 | the current V6b/V7 OT+FX -- instant dry cut (note-off), FX tails ring, **trig-mute** |
| `DT-T`   | 3 | the current DT -- voice rides its own amp envelope, FX tails ring, **trig-mute** |

Renumbering vs the `wip/mute-mode` build (0=OT, 1=OT+FX, 2=DT): old 1 -> 2, old 2 -> 3.  OS
upgrade resets PERSONALIZE so no migration issue.  `OTFX-T` is 6 chars -- `OT+FX` (5) rendered
fine on the MKI (Session 10); the value column at x=0x4d should hold ~8, but verify against
`FUN_40068e00` at build time and fall back to `OTFXT` if it clips.

### Why the four behaviours differ — the mute lever, pinned down
`FUN_40004db8` (the per-frame mute/solo/cue gate, HW-confirmed as *the* gate) was fully
disassembled (`m68k-elf-objdump -m m68k:5407`, the r2/Ghidra decompiles were both wrong on the
inner branch) and re-run on real bytes (`tools/emu_otfx.py` — ALL GOOD).  Per track it writes
**4 u16 words** (8 B/track) into the buffer at `0x80003c10`, from three source arrays
`A=0x80000c60` (stride 4), `B=0x80000c80` (stride 2), `C=0x8000485a` (stride 8):

| word | value | gate |
|---|---|---|
| `frame[8t+0]` | `A[t].word1` | **CUE** bit (16+t) — CUE-send level |
| `frame[8t+2]` | `A[t].word0` | soloed(t) → keep; else **MUTE** bit (8+t) → **0**; else any-track-soloed → 0 — **MAIN mix level** |
| `frame[8t+4]` | `B[t]` | **ungated** (pan) |
| `frame[8t+6]` | `C[t].word0` | **ungated** (pan) |

So **mute's only lever in this function is zeroing the post-FX MAIN-mix word** (`frame[8t+2]`).
Stock OT does exactly that and nothing else → voice untouched (cursor + envelope keep running
→ resume works) but the FX-return dies because it shares that one post-FX bus word.  V6/V7's
`D5 &= ~(muted<<8)` keeps `frame[8t+2]` open (→ tails reach MAIN) and then kills the dry
*upstream at the voice* via `FUN_40008f84` note-off — which frees the voice (45-frame
`46c7dfba` watchdog) → no resume.  DT keeps the word open and does nothing else → a sustained
voice stays audible through the "mute".  **There is no pre-FX voice control in `FUN_40004db8`;
+4/+6 are pan and useless here.**

### The candidate mechanism for the new mode
Keep `frame[8t+2]` open (the V6 `pre` D5-trick, like DT) **and** force the **per-voice
pre-FX amp level to 0** for muted tracks — without touching the voice struct, so its sample
cursor keeps advancing and unmute just restores the level.

The per-voice amp array is **`0x46c7ff42`** (stride 4, 8 voices; sits right below
`_DAT_46c7ff64` the post-FX MAIN mute).  It is filled **every frame** by `FUN_4000d16c`'s
voice loop: `d0 = FUN_400068e4(t, DAT_800000e0, cmd&0xf, 0x10)` (returns voice-struct `+0x18`
= the current amp-envelope output) then **`0x4000d36e: move.l %d0,(%a2)+`** with `a2 = 0x46c7ff42`,
`d3 = t`.  `FUN_400068e4` is the control-rate envelope updater (voice struct base `0x80004f1c`,
stride `0x54`, +`0x2a0` double-buffer; env slopes at +0x24/28/2c, position at +0xc).

**Hook (3rd site, gated on the new mode only):** detour `0x4000d36c` (8 B: `jsr (a3)` +
`move.l d0,(a2)+` + `movea.l (160,sp),a1`) → cave: run the `jsr FUN_400068e4`, then if track
`d3` is muted (`0x80000008` bit 8+d3) or solo-silenced → `moveq #0,d0`, then the displaced
`move.l d0,(a2)+` / `movea.l (160,sp),a1`, resume `0x4000d374`.  Because `0x46c7ff42[t]` is
recomputed every frame, zeroing it is non-destructive — unmute (stop zeroing) restores it.

Companion changes for the new mode (`OTFX`, `GATE == 1`):
- `pre` (0x40004dc6): clear D5 mute/solo bits (keep MAIN word) — **no** note-off, **no**
  `REL_STATE` — identical to the `DT-T` branch.  (Gate branches renumber: `OTFX-T` = the old
  note-off path moves to `GATE == 2`; `DT-T` to `GATE == 3`.)
- `pre_v` (0x40005178): **do NOT drop** bare starts (unlike `OTFX-T`/`DT-T`) — a trig fired
  while muted should start a voice that advances silently (amp-zeroed) so unmute picks it up
  mid-sample, matching stock OT.

### Two unknowns that only a hardware flash can settle
1. **Is `0x46c7ff42` pre- or post-insert-FX?**  If post-FX, zeroing it = stock OT (tail dies)
   and the mode is pointless.  Believed pre-FX (amp envelope is classically pre-FX; the array
   is per-*voice* not per-*track*, distinct from the post-FX `46c7ff64`).
2. **Does the DSP keep advancing the voice's sample cursor while `0x46c7ff42[t] == 0` for
   many frames**, or does it treat zero-amp / non-refreshed as "free the voice"?  If it frees
   it → collapses to OT+FX-TRIG (no resume).
   Fallbacks: write a tiny non-zero amp (e.g. `1`) instead of `0`; or also keep the
   `46c7faa4[t]` refresh slot alive.
3. Minor: an abrupt 0 may click — may need a 1-frame ramp.

### Recommendation: flash DT first
**DT rests on the *same* unknown #2** (Session 12 NEXT, "does the DSP keep advancing a plain
FLEX one-shot while the frame words flow untouched").  Flashing the existing
`OCTATRACK_MUTEMODE_DT.bin` answers it:
- DT loop-sample test (item 3) shows the voice audibly keeps running → unknown #2 = **YES**,
  and this new mode becomes low-risk (build it next).
- DT shows the voice stalls → this mode needs the fallback path and both need a rethink.

So the order is: **flash DT → confirm the voice keeps advancing → then build the new mode**
as menu value 1 of `OT / OTFX / OTFX-T / DT-T`.

### Menu / naming caveat
Values (user-chosen): `OT` / `OTFX` / `OTFX-T` / `DT-T`.  Value column (renderer
`FUN_40068e00`, x=0x4d) — stock values there are ≤5 chars (`LOW/MID/MAX`), our shipped
`OT+FX` = 5 rendered fine on the MKI (Session 10).  **`OTFX-T` = 6** — the column at x=0x4d
should hold ~8 glyphs but VERIFY against `FUN_40068e00` at build time; fall back to `OTFXT`
if it clips.  Menu-array surgery itself is unchanged (still one spliced entry, still
`moveq #15→#16`); only `N_MODES 4` + the value strings + the `pre`/`pre_v` gate branches change.

### Session 14 tooling (uncommitted)
`tools/emu_otfx.py` (runs the real `FUN_40004db8` — ALL GOOD),
`tools/ghidra/attic/GhidraOTFX{1,2,3}.java`, dumps `out/ghidra/GhidraOTFX{1,2,3}_session14.txt`.
No `patch_*` / `build_*` changes yet.

---

## Session 15 (2026-09-02, `wip/mute-mode`, RE / feasibility only) — "DIRECT JUMP" pattern-change mode

### The ask (user)

An Elektron-style **Direct Jump** option for manually sequencing patterns: selecting a new
pattern switches to it **immediately** (not quantised to the pattern boundary), and playback
**continues from the step position the previous pattern was at** instead of restarting at
step 1. The new pattern's **Part loads instantly** on the switch (opposite of the shelved
LAZY PART mod — and note LAZY PART is *not* in the current `build_mutemode.py` build, so
instant Part load is already the stock behaviour here).

### Verdict: FEASIBLE, medium effort. All in already-mapped territory (sequencer engine,
### Sessions 3–6). No DSP RE, no new subsystem.

### Function / global map found this session (Ghidra headless, `tools/ghidra/attic/GhidraDirectJump{,2,3,4,5}.java`)

| symbol | role |
|---|---|
| **`FUN_400a0570(bank, pat, loopStart, loopEnd, p5)`** | **the cue-pattern primitive — single choke point for every pattern change** (manual trig, arranger, chain). If `_DAT_800065b8==1` (sequencer running): stashes the pending pattern in `DAT_800065bf/c0`, loop points in `_DAT_80006630/34`, posts a kernel event, returns — the actual switch happens later in the step engine. If stopped: writes the ACTIVE `DAT_800065bd/be` directly + tempo + Part path. Called from `FUN_4004a100` (arranger row) and `FUN_4004a654`; the manual PTN-key path funnels here too. |
| `DAT_800065bd` / `DAT_800065be` | **ACTIVE** (playing) bank / pattern |
| `DAT_800065bf` / `DAT_800065c0` | **CUED** (pending) bank / pattern |
| `DAT_800065bc` | plays-free per-track "SEQ SYNC PICKUP" pattern (`FUN_400618d8`, `FUN_4004b040`) — NOT the general cue |
| **`_DAT_800065b4`** | **master step position — reset to 0 in every pattern-reload block** |
| **`_DAT_800065b6`** | current pattern length − 1 (reloaded from the scale tables `DAT_400aba50` / `DAT_400e21e0+…+0x8e54` in every reload block) |
| `_DAT_800065b2` | secondary / loop-region counter (reset to 0 or `_DAT_8000663a`) |
| `_DAT_800065d3 .. _DAT_800065e3` | per-track step positions (8 bytes), reset in the same blocks |
| `DAT_80006687` ← `DAT_80006688` | CHAIN-AFTER countdown / its reload value |
| `_DAT_80006514` | second countdown (chained-list / arranger path) |
| `_DAT_46c8028a` | "reload now" flag — gates the **immediate** reload block in the step engine |
| **`FUN_400a1eea`** (per-step engine, 12 KB) | holds **3+ near-identical pattern-reload blocks**, gated respectively on `DAT_80006687→0`, `_DAT_80006514→0`, `_DAT_46c8028a≠0`. **Each block: `_DAT_800065b4 = 0` (step reset) + reload `_DAT_800065b6` (length) + re-init per-track note/voice scratch + load Part/scene arrays** from `DAT_400e21e0 + bank*0x9b340 + pat*0x8ed8`. |
| `FUN_400a1030(bank, pat)` | commit-pattern-to-active, called from the step engine's boundary handler `candidate_400a10d2` |
| `FUN_400a0ef8` / `FUN_400a0734` | compute `DAT_80006688` (the countdown) from the CHAIN AFTER value / arrangement row (`param_1*6` units) |
| `FUN_400866c4` | project text-state parser; has the `PATTERN_CHANGE_CHAIN_BEHAVIOR=` case (also `PATTERN_CHANGE_AUTO_SILENCE_TRACKS`) |
| menu strings (file offsets) | `0xb5b28` "PATTERN CHANGE", `0xb5b37` "CHAIN AFTER", `0xb5b43` "SILENCE TRACKS", `0xb7487` "CHAIN BEHAVIOR", `0xb74d6` "PLAYS FREE" |

### Why it's feasible

1. **One choke point.** `FUN_400a0570` is where *every* pattern cue lands — one hook covers
   manual trigs, chains, arranger.
2. **The reload machinery already exists** (3 copies in `FUN_400a1eea`). Direct Jump does not
   need new switch logic; it needs to (a) make a reload fire *now* instead of at the boundary,
   and (b) not zero `_DAT_800065b4`.
3. **Step position is a plain fast-RAM global** (`_DAT_800065b4`, + the 8-byte per-track
   array). Save/restore-with-modulo around the reload block is exactly the stub idiom already
   used by LAZY PART (`tools/patch.s`) and sticky scenes (`patch_scene2.s`).
4. **Instant Part is free** — the reload block loads the new Part as part of a normal pattern
   change, which is what the user wants.
5. **Menu surgery is proven** — the MUTE MODE PERSONALIZE entry (Session 10,
   `patch_mutemode.s` + `build_mutemode.py`: relocate label array, bump count, splice entry)
   is the template.

### DEEP TRACE (2nd pass, same session) — the real pattern-switch path

The 3 countdown-gated reload blocks in `FUN_400a1eea` (`DAT_80006687→0`, `_DAT_80006514→0`,
`_DAT_46c8028a≠0`) are the **arranger / RELOAD / chained-list** paths. A **plain manual
pattern change while running does NOT use them.** It is handled inline in the **main per-step
handler** of `FUN_400a1eea` (~`0x400a3f80`–`0x400a4bd0`):

```
per-step tick:
  DAT_800065b6 = DAT_800065b6 + 1                       ; advance master step   (0x400a3fa? )
  if (DAT_800065b6 >= DAT_400aba50[DAT_8000663d])       ; >= pattern length
      DAT_800065b6 = 0                                   ; wrap
  if (DAT_800065b6 == 2)  -> FUN_4009e884(pending)       ; 2-steps-early PART preload
  else if (DAT_800065b6 == 0) {                          ; *** pattern boundary ***
      _DAT_800065b4 = _DAT_800065b2 ; _DAT_800065b2++    ; bar counter
      DAT_8000663d  = pattern scale index (reloaded)
      iVar19 = DAT_400d80dc[ chainBehaviour ]            ; CHAIN AFTER interval  (table below)
      iVar5  = (pending pattern != active)               ; "real change pending"
      if ( switch-point reached, gated on _DAT_800065b2 % iVar19 ) {
          DAT_800065c1/c2 = old active pat/bank          ; remember outgoing (for "keep source part" test)
          DAT_800065be = DAT_800065c0                    ; *** COMMIT pending -> active pattern ***  (~0x400a43xx)
          DAT_800065bd = DAT_800065bf                    ;                       bank
          _DAT_80006628 = _DAT_80006630 (= loop start)   ; base for the per-track position math
          _DAT_8000662c = _DAT_80006634 (= loop end)
          FUN_40000c3c(0x460d17ae, &DAT_400d8167/69/6b)  ; notify UI (pattern/part LEDs)
          ... rebuild scene masks, mute masks ...
          iVar6 = _DAT_80006628 * patternLen             ; absolute tick base  (~0x400a4a??)
          for t in 0..7 (audio) then 0..7 (MIDI):        ; recompute per-track positions
              DAT_800065e4[t] (audio step-in-track), DAT_800065f4[t] (MIDI),
              companion arrays DAT_80006604/14, DAT_800065c3/cb   ; all from iVar6 % trackLen
          _DAT_800065b2 = _DAT_8000662a
          DAT_800065b6 = 0                               ; *** master step reset to 0 ***
      }
  }
```

**`DAT_400d80dc` (CHAIN AFTER lookup, u32):**
`[0]=-1(PLEN) [1]=1 [2]=2 [3]=3 [4]=4 [5]=6 [6]=8 [7]=12 [8]=16 [9]=24 [10]=32 [11]=48
[12]=64 [13]=96 [14]=128 [15]=192 [16]=256` (then a MIDI-clock variant `[17..]`). Global
setting = `DAT_8000004e`; per-pattern override = pattern blob `+0x8e56` (used if ≥ 0).
`-1`/PLEN → gate uses the pattern's own length; `N` → gate is `barCounter % N == 0`.
**No stock value switches mid-pattern** — the commit is unconditionally inside the
`DAT_800065b6 == 0` (boundary) branch.

**Corrected global roles:**
- **`DAT_800065b6`** (byte) = **master step position** (0..len-1, wraps). *This* is the one to
  preserve. (Earlier pass mislabelled `_DAT_800065b4` as the step counter.)
- `_DAT_800065b4` (word) = latched bar counter (`= _DAT_800065b2` at each boundary).
- `_DAT_800065b2` (word) = running bar counter.
- `DAT_800065d3..e2` (16 B) = per-track "step limit" (len-1), filled by the countdown blocks.
- `DAT_800065e4[8]` / `DAT_800065f4[8]` (u16) = per-track current step (audio / MIDI),
  recomputed at the boundary from `_DAT_80006628 * len`.
- `_DAT_80006628` / `_DAT_8000662c` = active loop-region start / end (in bars);
  `_DAT_80006630` / `_DAT_80006634` = the *pending* loop region (set by `FUN_400a0570`).

### Design (concrete)

**Trigger:** PERSONALIZE toggle `PTN CHG : NORM / DIR` — free battery-backed bit near
`0x800000dc` (MUTE MODE word). MUTE MODE menu surgery is the template
(`patch_mutemode.s` + `build_mutemode.py`).

**One detour, in the main per-step handler of `FUN_400a1eea`**, placed right after the
`DAT_800065b6 + 1` / wrap logic and before the `== 0` boundary test:

```
if (g_directjump_mode && sequencer running && pending pattern set && pending != active) {
    curStep = DAT_800065b6                      ; where we are right now
    DAT_800065b6 = 0                            ; force the boundary branch THIS tick
    _DAT_80006630 = <curStep expressed in the loop-start units>   ; so the per-track
    _DAT_80006628-feeding path                                    ; math resumes at curStep
    (bypass the CHAIN-AFTER gate: shadow chainBehaviour = index 1 / value 1, or
     patch the branch, for this one tick only)
}
```

Then an **exit stub** after the boundary handler: it has just set `DAT_800065b6 = 0` and the
per-track arrays for "start of pattern". Overwrite `DAT_800065b6 = curStep % newLen` and, if
the `_DAT_80006630` trick above did not already place them, fix
`DAT_800065e4[t]` / `DAT_800065f4[t]` = `curStep % trackLen[t]`. Clear the one-shot.

**Best case** (needs a build to confirm): setting `_DAT_80006630`/`_DAT_80006628` to the
current position *before* the boundary handler runs lets the firmware's own per-track math
(`iVar6 = _DAT_80006628 * len`, then `% trackLen` per track) produce the right positions —
then the exit stub only has to fix the master `DAT_800065b6`. That would make the whole
feature ≈ one detour + a ~15-instruction stub.

**Instant Part / scene:** free — the boundary handler already loads them on the commit. (And
LAZY PART is not in the `build_mutemode.py` build, so nothing to fight.)

**"Instant" vs "next step":** forcing the wrap makes the switch land on the next step tick
(≤ 1/16 at scale 16). Audibly identical to truly-instant for the sequencer (trigs fire on
step edges anyway); only a still-ringing voice from the old pattern differs — same as a
stopped→pattern-change on stock OT.

### Open items before a build

1. **Exact detour address + displaced bytes** in `FUN_400a1eea`'s per-step handler
   (`~0x400a3fa0`, just after the `DAT_800065b6++`/wrap). Needs a clean Ghidra *listing*
   (not decompile) of `0x400a3f80–0x400a4060` with bytes — the r2 disasm desyncs here
   (ColdFire), and `GhidraDJ10`'s listing-dump approach returned nothing (fix: disassemble
   the function first, iterate `getInstructions(body)`).
2. **CHAIN-AFTER gate bypass** for the forced mid-bar boundary — cleanest is a per-tick
   shadow of `DAT_8000004e`/`+0x8e56` = index 1; confirm nothing else reads it in that window.
3. **`_DAT_80006630` units** — is it bars, steps, or ticks? Determines whether the
   "feed current position as loop-start" shortcut works or the exit stub must rebuild the
   per-track arrays. Read the boundary handler's `iVar6 = _DAT_80006628 * len` site and
   `FUN_4009e884`.
4. **Per-track PLAYS-FREE / per-track-scale tracks** — those keep independent positions
   (`DAT_800065d3..e2` limits, separate advance); decide whether DIRECT JUMP preserves them
   (same modulo) or lets them re-home.
5. **Scope v1** to manual pattern selection only — do not change ARRANGER or pattern CHAIN
   (their commits share this handler but are gated differently; the `g_directjump` check must
   also require "not in arranger mode": `DAT_800065bc == -1` / arranger-active flag).
6. Emulation harness (`tools/emu_directjump.py`) before flash, per project norm — though
   `FUN_400a1eea` has Unicorn-unsupported instrs (like the frame builder), so the harness may
   only be able to exercise the stub in isolation with a hand-built state, as `emu_otfx.py` did.

### Staged build plan

- **S1 — menu toggle only.** `PTN CHG : NORM/DIR` PERSONALIZE entry, stored + read back, does
  nothing yet. Independently flashable, zero audio risk. Confirms the menu surgery (value
  column width: `DIR` = 3 chars, fine).
- **S2 — crude trigger, no position preservation.** Detour forces the immediate boundary
  when DIR + pending. Expect: pattern switches instantly but restarts at step 1 (like DIRECT
  START). HW-test that the switch is glitch-free and the Part swaps.
- **S3 — position preservation.** Add the `_DAT_80006630` pre-set + exit stub. HW-test that
  playback continues at the playhead, incl. shorter destination pattern.
- **S4 — polish.** Per-track plays-free handling, arranger/chain exclusion, edge cases.

### Session 15 continued — address-level map of the per-step switch, and S1 built

**Full listing of `FUN_400a1eea`'s per-step handler** (`out/ghidra/GhidraDJ12_session15.txt`,
via `GhidraDJ12.java` — the working listing-dump recipe: `dec.decompileFunction` first to
force disassembly, then `lst.getInstructions(body)`):

| addr | what |
|---|---|
| `0x400a3f94` | `moveq #1,D0 ; cmp.l (0x800065b8).l,D0 ; bne.w 0x400a4d36` — bail unless running |
| `0x400a3fdc` | `move.b (0x800065b6).l,D0 ; addq.l #1,D0 ; move.b D0,(0x800065b6).l` — **advance master step** |
| `0x400a3ff8` | `cmp.l (0x0,A0,D1*4),D0` (A0=`0x400aba50`, D1=`DAT_8000663d` scale idx) `; blt 0x400a4006` |
| `0x400a3ffe` | `clr.b D1 ; move.b D1,(0x800065b6).l` — **wrap step → 0** |
| `0x400a4006` | `tst.b (0x8000667e).l ; beq.w 0x400a412e` — `8000667e`≠0 = "stop after this pattern" path |
| `0x400a412e` | `move.b (0x800065b6).l,D1 ; moveq #2,D4 ; cmp.l D0,D4 ; bne.w 0x400a421a` — step==2? |
| `0x400a413e`–`0x400a421a` | **step==2**: CHAIN-AFTER gate (below); on switch-point → `FUN_4009e884(pendBank,pendPat)` @`0x400a4210` = **2-steps-early Part preload**, then `bra 0x400a4b9a` |
| `0x400a421a` | `tst.b D1 ; bne.w 0x400a4b9e` — **step==0?** (D1 = step); else it's a mid-pattern tick → `LAB_400a4ba0` |
| `0x400a4220`–`0x400a4466` | **step==0**: latch bar ctr (`800065b4=800065b2`, `800065b2++`), rebuild the same CHAIN-AFTER gate |
| `0x400a4310` | `D1 = A4[0x8e56]` (per-pattern CHAIN override, `<0` → use global `mvs.b (0x8000004e).l`) |
| `0x400a4316` | `D4 = DAT_400d80dc[D1*4]` — CHAIN interval value |
| `0x400a4358`–`0x400a439c` | gate: `divsl.l D4,D0:D1` → `(barctr+1) % interval == 0` → switch; PLEN (D4≤0) → `len <= barctr+1` |
| `0x400a4466` | `mvs.b (0x800065c0).l,D0 ; cmp #-1 ; bne 0x400a44a0` — pending pattern set? |
| **`0x400a44d0`** | `move.b D1,(0x800065be).l` / `0x400a44dc: move.b (800065bf),(800065bd)` — **THE COMMIT** (pending pat/bank → active). `800065c1/c2` first hold the *outgoing* pat/bank. |
| `0x400a44e2` | `_DAT_80006638 = _DAT_80006628 = _DAT_80006630` ; `_DAT_8000662c = _DAT_80006634` — loop region ← pending loop region (set by `FUN_400a0570`, normally start=0) |
| `0x400a4548`,`0x400a459a` | post UI msgs `0x400d8167` (pattern LED), `0x400d8169` (part LED, part idx = `DAT_400eb037[bd*0x9b340 + be*0x8ed8]`) |
| `~0x400a4700`–`0x400a4a40` | *(gap not dumped)* sets `DAT_800065b6 = 0`, computes `iVar6 = _DAT_80006628 * patternLen`, per-track loop base = stack local `0x3c(SP)` |
| `0x400a4aa2` | `move.l (0x3c,SP),D0 ; divsl.l D1,D0:D0 ; move.w D0,(A0)` — **per-track step** (`DAT_800065f4[t]` MIDI, `DAT_800065e4[t]` audio) = base / trackLen; remainder → `DAT_80006614[t]` |
| `0x400a4b9e` | `clr.l D6` |
| **`0x400a4ba0`** | `LAB_400a4ba0` — **common tail, reached from switch AND no-switch**: per-track loop that decrements `DAT_800065c3[t]`, fires `FUN_400a536c(t)` (trig) when it hits 0, refills `DAT_800064d0[t]` |

**`_DAT_80006628`/`_DAT_80006630` are in units of *loop repeats*** (`base = _DAT_80006628 *
patternLen`), so they cannot express "resume at step N" directly — the per-track math is
loop-granular; step-within-loop lives only in `DAT_800065b6` + the per-track step counters.
→ **position preservation = an exit stub** that, after the boundary handler has homed
everything to step 0, rewrites `DAT_800065b6 = savedStep % newLen` and the 16 per-track
`DAT_800065e4[]`/`DAT_800065f4[]` (+ companions `DAT_800065c3[]`, `DAT_80006604/14[]`).

**Storage word for DIRECT JUMP = `0x800000a8`** — the last free battery-backed PERSONALIZE
word (0xd4/d8/dc taken); **zero refs in the stock image** (verified). 0 = stock.

### S1 BUILT (menu only) — `tools/patch_directjump.s` + `tools/build_directjump.py`

`PERSONALIZE → DIRECT JUMP : OFF / ON`, stored in `0x800000a8`, read back — **no behaviour
change yet**. Same menu surgery as `build_mutemode.py` (3 arrays relocated to
`0x400d7600/60/c0`, one entry spliced at index 2, `moveq #15→#16` @`0x40068fb2`, 5 refs
repointed from the symbol table). Carries the Bug-1 fix (`patch_trigscale`, byte-identical).
→ `out/OCTATRACK_OS1.40C_DIRECTJUMP.{syx,bin}` (`140C_KYOTI`), 385 B changed vs stock,
round-trip checksum ok. **Not flashed.** Purpose: confirm the menu + the new storage word on
the MKI before the audio hooks go in.

### MIDI Program Change on a pattern change (RE'd) — `FUN_4009e884(bank, pat)`

Stock: the step engine calls `FUN_4009e884` from the **step == 2** branch (`0x400a4210`),
i.e. **2 steps before** the pattern boundary, only when the CHAIN-AFTER gate says a switch
is coming. `FUN_4009e884`:
- gated on `0x8000002b` bit 1 = `MIDI_PROGRAM_CHANGE_SEND`; channel from `0x8000002c`
  (`MIDI_PROGRAM_CHANGE_SEND_CH`, -1 = AUTO → derived from the sounding tracks' channels).
- absolute pattern number = `pat + bank*16`, `& 0x7f`.
- emits **Bank Select CC** (`0xB0|ch`, from `0x400d80d8`, 3 B) then **Program Change**
  (`0xC0|ch`, from `0x400d80d6`, 2 B) via `FUN_40010bc8`.
- **de-duplicates per channel** (`46c7a9b6[ch]` PC cache, `46c76100[…]` bank cache) — a
  repeated PC for the same channel is suppressed.

**DIRECT JUMP handling (S2):** forcing the switch skips the step==2 branch, so Hook A sends
the PC itself. It sends **once per distinct pending pattern**, on the first tick it sees the
cue, and forces the actual switch on the **next** tick → the PC leads the audio switch by
one step (~30–125 ms). Rapidly flipping A→B→C before the switch: each new pending pattern
gets its PC (`FUN_4009e884` dedup means an unchanged one is a no-op), and only the pattern
that is still pending when the commit fires actually engages.

### S2 + S3 BUILT — `tools/patch_directjump.s` (3 hooks) + `tools/build_directjump.py`

The `DIRECT JUMP` toggle now gates three detours into `FUN_400a1eea`. Free scratch
`0x80006a40..42` (`G_ARMED` / `G_STEP` / `G_PCPAT`). All inert when the toggle is 0, when
the arranger (`0x460d1aec`) is running, or when a pattern chain (`0x80006546`) is running.

| hook | site | displaced | what it does |
|---|---|---|---|
| **A** `dj_a` | `0x400a4006` | `tst.b (0x8000667e).l` (6 B → jsr) | `movem` all regs. If DJ on + real pending manual switch: send the Program Change once per distinct pending pattern (`jsr FUN_4009e884`), keep `G_STEP` = current `DAT_800065b6` fresh. Tick 1 → set `G_ARMED`. Tick 2 (armed) → `clr.b DAT_800065b6` so the step==0 body runs this tick. Restore regs, run the displaced `tst.b`, `rts` (Z flag intact for the caller's `beq.w`). No pending / DJ off → `clr G_ARMED`. |
| **B** `dj_b` | `0x400a42fa` | `move.l #0x8e56,d0` (6 B → jsr) | If `G_ARMED`: overwrite the jsr return address with `0x400a43a0` (the "switch confirmed" label) and set `D6 = 1` — bypasses the CHAIN-AFTER gate (incl. the per-pattern `+0x8e56` override) for this one tick. Else: run the displaced `move.l #0x8e56,d0`. |
| **C** `dj_c` | `0x400a4840` | `clr.b d0 ; move.b d0,(0x800065b6).l` (8 B → jsr+nop) | Not armed → `DAT_800065b6 = 0` (stock). Armed → `newLen = LEN_TBL[ PAT_SCALE[newBank*0x9b340 + newPat*0x8ed8] ]`; set both `D7` and `DAT_800065b6` to `G_STEP % newLen`. Because the switch body derives every per-track position from `D7` (`D5=D7-1`, `(0x3c,SP)=D7-1`, `divsl trackLen`), overriding `D7` resumes all 16 tracks at the playhead (each mod its own length) — no need to touch the per-track arrays. `clr G_ARMED`. |

**PC timing:** Hook A sends the PC on tick 1 and forces the switch on tick 2 → 1 step of
lead (~30–125 ms). Tunable (add a 2nd arm phase for a 2-step lead like stock).

**Verified — `tools/emu_directjump.py` : ALL GOOD.** Each stub run in isolation on a
hand-built state (`FUN_400a1eea` won't run under Unicorn): OFF path, arranger/chain guards,
2-tick arm→commit, PC send + dedup + resend-on-flip, register save/restore, gate-bypass
return rewrite + `D6`, playhead resume incl. shorter/longer destination pattern.
(unicorn-m68k doesn't set CCR on `tst.b (abs).l` — the caller's `beq.w` Z flag is correct by
construction: `dj_a`'s last op before `rts` is the verbatim stock `tst.b`.)

Build: `python3 tools/build_directjump.py` → `out/OCTATRACK_OS1.40C_DIRECTJUMP.{syx,bin}`
(`140C_KYOTI`), 684 B vs stock, round-trip ok, Bug-1 fix byte-identical. **NOT FLASHED.**

### HW-only unknowns for the S2/S3 flash

1. **Register liveness across Hook B's skip.** Armed path jumps `0x400a42fa → 0x400a43a0`,
   skipping `0x400a4300–0x400a439c` (pure CHAIN-gate computation — no memory writes, only
   `jsr FUN_40033968` which is a plain read). A2 (ping-pong ptr) and A3 are set *before*
   `0x400a42fa`; D0–D4 are reloaded at `0x400a43a0+`. Believed safe; confirm no glitch/hang.
2. **`FUN_4009e884` from Hook A's context** — it's already called from this same handler at
   `0x400a4210`, so the context is fine; confirm the PC actually goes out and lands on the
   right channel with `MIDI_PROGRAM_CHANGE_SEND` on.
3. **Per-track PLAYS-FREE / per-track-length patterns** — Hook C's `newLen` ignores the
   `DAT_400eb035` per-track-length flag; worst case the master step is briefly out of range
   and the next tick's wrap (`0x400a3ff8`) clamps it. Confirm no audible artefact.
4. **`G_ARMED` power-up garbage** — Hook A runs before B/C every playing tick and disarms
   when there's no valid pending, so B/C never see stale garbage. Confirm.
5. **Feel** — is 1 step of PC lead / next-tick switch the right "in time" behaviour, or does
   it want the 2-step lead?

### Session 15 tooling (uncommitted)

`tools/ghidra/attic/GhidraDirectJump{,2,3,4,5}.java`, `GhidraDJ{6..14}.java`;
`tools/patch_directjump.s`, `tools/build_directjump.py`, `tools/emu_directjump.py`. Scratch
dumps `dj{1..13}.txt` + `a1eea.txt` in the session scratchpad. Committed dumps
`out/ghidra/GhidraDirectJump{1..4}_session15.txt`, `out/ghidra/GhidraDJ12_session15.txt`.


## Session 17 (2026-09-02, `wip/mute-mode`, RE / feasibility only) — external side-chain (key-track) input for the DynamiX COMPRESSOR

### The ask (user)

Add **side-chain compression** to the stock OT compressor. The user's vision: on a track that
has COMPRESSOR in an FX slot, pick **one of the 8 audio tracks as the "key"** whose level
drives the gain reduction on the target track; integrate the UI into the compressor FX
page(s); and offer an option to let the **key track feed the detector even when the key
track is muted**.

### What side-chain compression is (for the record)

A compressor lowers gain when its **detector** (a.k.a. sidechain) input rises above THRS.
Normally detector = the signal being compressed. *Side-chain / key* compression feeds the
detector from a **different** signal, so track A ducks in response to track B's dynamics —
the classic kick-keys-the-bass/pad "pumping". Real side-chain follows the key **audio's
envelope** continuously (responds to level, not just note events), and usually offers a
key filter / "listen". That last point is what separates it from Route 1 below.

### The hard structural fact — this is a DSP feature, not a ColdFire one

The DynamiX COMPRESSOR runs **on the DSP** (DSP56721, 2 cores), not the ColdFire. Confirmed
via octabam (`refs/octabam/docs/DSP.md` @ e1dcfa9): dispatch id `0x18` → process `P:0x01ab1`,
**180 words at `P:0x01aa4`**, control-flow contained (not a record-spanner). The ColdFire OS
— everything this repo patches — **never touches PCM samples**: it assembles per-track voice
parameters and DMAs frame blocks to the DSP (`0x400031a0` frame routine; `FUN_40001d4c`
uploads the DSP program at boot). Which signal the detector listens to is chosen *inside*
those 180 DSP words, from the effect's own track buffer.

⇒ **There is no ColdFire-only lever that changes what the detector hears.** You cannot build
an envelope follower on a CPU that never sees the audio. A *true* audio side-chain requires
**DSP56300 assembly** + a DSP build/flash pipeline — exactly the scope `COVERAGE.md` fences
off as "a separate project," and which **octabam has already built out** (for a reverb/delay
send bus), MKII-flashed only. Our own `out/dsp_region.bin` is extracted but **never
disassembled**.

### Three routes, ascending cost

**Route 1 — ColdFire-only "trig-synced ducking" (NOT real side-chain).**
The ColdFire *does* know when a track fires a trig (sequencer, mapped Sessions 3–6). Add a
per-track `DUCK FROM Tn / DEPTH / RELEASE` that applies a downward volume envelope to the
target, re-triggered by the key track's trigs — automation of the existing per-track AMP VOL
in the shipped patch style (menu + detour), no DSP work.
- ✗ It is *trigger* ducking, not *signal* ducking: fixed shape regardless of the key's actual
  level/content; nothing for a THRU/external key with no trigs, or a key whose loudness
  varies p-lock to p-lock; and it doesn't "feed the compressor" — it side-steps it.
- Does **not** match what the user described, but it is the only route that is cheap
  (~2–4 sessions) and carries no brick risk.

**Route 2 — DSP side-chain, key & target in the SAME bank of four (real, big).**
Reuse octabam's proven "fake a bus in shared Y scratch" mechanism (`refs/octabam/docs/BUS.md`,
`XBUS.md`):
1. **Key tap** — publish each track's pre-FX audio block into a per-track slot in absolute Y
   scratch (≥ `0x800`, the region octabam proved safe in both payloads). Cheapest: extend the
   **passthrough stub** `P:0x007c9` (runs for every FX slot set to `NONE`, id 0) to also do
   `in → keybus[myTrackSlot]`. Then the constraint is just "key track has one FX slot = NONE"
   (usually true). Alternatives: a dedicated `SC SEND` insert (costs a real FX slot on the
   key track, octabam-`send`-style), or — bigger — hook the frame builder so every track taps
   unconditionally.
2. **Modified COMPRESSOR module** — same 180-word engine, detector reads `keybus[KEY]` instead
   of / blended with `r0` when the new `KEY` param ≠ OFF. Needs the disassembly to find the
   detector tap point and to check the ~200-word / 2,724-word-payload budget for the extra
   branch + a one-pole key HP.
3. **ColdFire menu** — add page-2 params to the COMPRESSOR descriptor (`E = 0x400d5a4a`,
   `E_0x96 = 0x400d5ae0`). Page 2 currently holds only `RMS` at slot index 6; ~5 page-2
   encoder slots are free — **pure data** per octabam `PARAM_PAGES.md` §5 (names, ranges,
   the per-parameter enable bitmap at `P+0x18a`/`P+0x18e`, `P = E + 0x38`). Add `KEY`
   (OFF / T1..T8) and optionally `SC SRC` (PRE / POST-mute).
- **Same-core constraint**: core 0 = tracks 5–8, core 1 = tracks 1–4 (octabam, measured,
  inverted from the natural guess). A pair split across that boundary needs the **cross-core
  accumulator** with octabam's 4-rotating-buffer race fix — three hardware-only race bugs,
  months of MKII bring-up (`XBUS.md`). So v1 = "key and target must both be in T1–4, or
  both in T5–8."
- **"Feed even when muted" is essentially free and is the natural behaviour.** Stock mute
  only zeroes the post-FX MAIN output word (`FUN_40004dbc`, our soft-mute finding, Session 9);
  the muted voice still renders and its pre-FX audio still exists on the DSP. Tap pre-mute-gate
  ⇒ a muted key still keys. The `POST` option (mute also kills the key) is the one that would
  need the extra gate.
- **Effort**: this is the largest single piece of work in the project's history. Prereq:
  stand up a DSP56300 toolchain — disassemble `out/dsp_region.bin` (octa-bt-pt points at
  `vendor/dsp56300/.../dsp56kDisassemble -le`; octabam has a full assembler + `tools/dsp_host`
  emulator + collision-checked build). Then module dev + emu + **DSP flash to the user's
  only MKI** — untested territory: octabam DSP images are MKII-flashed only, though the stock
  1.40C file is **byte-identical MKI/MKII** (our `ARCHITECTURE.md` + octabam `FLASHING.md`),
  so addresses should line up and the image is "plausibly compatible" — an MKI owner is the
  test pilot. Estimate **8–15+ sessions**, with brick risk that the ColdFire menu patches
  don't carry.

**Route 3 — full any-key → any-target (8×8).** Route 2 + octabam's cross-core XBUS machinery.
Much more; the cross-core races are only diagnosable on hardware.

### Recommendation

- Want it soon / low-risk → **Route 1**, sold honestly as trig ducking, not side-chain.
- Want the real thing → **Route 2, scoped to same-bank pairs.** It is a "commit to a DSP
  toolchain" decision. Best done leaning on octabam's existing toolchain rather than
  rebuilding it. **Cheap first step, worth doing regardless of route:** disassemble
  `out/dsp_region.bin` / run octa-bt-pt's `dsp_modmap.py` against
  `out/raw/section_3_MAIN_OS.bin`, locate our COMPRESSOR's 180 words, confirm octabam's
  `P:0x01aa4` lines up in our image.

### Open questions before any Route-2 build

1. Confirm MKI DSP payload addresses == octabam's MKII numbers (stock file byte-identical ⇒
   very likely; verify `P:0x01aa4` COMPRESSOR against our own extract).
2. Does a DSP effect know its own track index (to index `keybus[slot]`)? octabam derives
   dispatch *position* from `r7` (`r7 == 0x6200` = core-0 position 0); need the full
   `r7 → track` map including the core split.
3. Detector tap point inside the 180 words + is there program-space headroom for the
   source-select branch and a key filter (2,724 words/payload shared budget).
4. COMPRESSOR page class is `0x400328e4` (shared with DJ EQ / reverbs / LO-FI) — confirm a
   new page-2 slot renders + p-locks like RMS does.

### Session 17 continued — the "cheap first step" DONE: octabam's DSP map lands 1:1 on our MKI image

Ran octabam's `tools/dsp_modmap.py` (self-contained, dep-free — only needs
`out/raw/section_3_MAIN_OS.bin`) unmodified against our image. Results:

- **Our stock image SHA256 = `164f31224bf61181e3f50e7dec40df9afcae5b16dbf6e4c0d0cc5e986af0a84e`**
  — the same hash NOTES L150 recorded, and the same bytes octamax/octa-bt-pt/octabam
  analysed. MKI and MKII ship the byte-identical 1.40C file (confirmed, not just inferred).
- The load-map parser consumes **100 %** of both DSP payloads (A @ `0x400e2324`, 79 563 B,
  98 modules, 26 221 words · B @ `0x400f59ef`, 77 061 B, 91 modules, 25 408 words). Field
  order `ac` = `(addr, count)`.
- **Dispatch table `X:0x215` (64 words = 32 init @ `0x215` + 32 process @ `0x235`) decodes
  cleanly and matches octabam's `DSP.md` table entry-for-entry** in payload A:

  | id | init | process | effect | | id | init | process | effect |
  |---|---|---|---|---|---|---|---|---|
  | 0x04 | P:0x007d1 | P:0x007dd | FILTER | | 0x14 | P:0x01000 | P:0x01055 | PLATE |
  | 0x05 | P:0x00aa8 | P:0x00ab2 | SPATIALIZER | | 0x15 | P:0x01252 | P:0x012be | SPRING |
  | 0x0c | P:0x00bad | P:0x00bb2 | EQUALIZER | | 0x16 | P:0x01679 | P:0x0171b | DARK |
  | 0x0d | P:0x01d71 | P:0x01d7d | DJ EQ | | **0x18** | **P:0x01aa4** | **P:0x01ab1** | **COMPRESSOR** |
  | 0x10 | P:0x00cc7 | P:0x00cd8 | PHASER | | 0x19 | P:0x007c8 | P:0x007c9 | MULTIBCOMP → null stub |
  | 0x11 | P:0x00d96 | P:0x00da3 | FLANGER | | 0x1c | P:0x01b58 | P:0x01b75 | LO-FI |
  | 0x12 | P:0x00eb7 | P:0x00ed7 | CHORUS | | 0x08 | P:0x007c8 | P:0x007c9 | DELAY → null stub |
  | 0x13 | P:0x01eca | P:0x01edc | COMB | | 0x00 | P:0x007c8 | P:0x007c9 | (null passthrough stub) |

- **COMPRESSOR module confirmed**: `P:0x01aa4`, **180 words** (image `0x400f47d1`) in payload
  A; `P:0x01864`, 180 words (image `0x40107722`) in payload B. Both dispatch tables point at
  it for id `0x18`. Payload B's whole effect block sits `0x210` lower than A's (smaller
  prologue) but is otherwise the same layout — octabam's "B differs in address, not
  structure" holds.
- The **null passthrough stub** octabam's Route-2 key-tap idea wants to extend is confirmed
  present at `P:0x007c8` (init) / `P:0x007c9` (process) in payload A — 9 words — the target
  of ids 0x00, 0x08 (DELAY), 0x19 (MULTIBCOMP) and every other unimplemented id.

**Verdict on the cheap step: octabam's entire DSP address map transfers to our MKI image
verbatim. No re-derivation needed.** A Route-2 build can reuse octabam's `dsp_modmap.py` /
`dsp_disasm_all.py` / `dsp_host` toolchain directly.

**Not done (belongs to Route 2 proper):** instruction-level disassembly of the 180
compressor words — needs the DSP56300 disassembler (`vendor/dsp56300/.../dsp56kDisassemble`,
the Virus-emu tool; octabam's `make setup` builds it: Homebrew + cmake + clone/build the
`dsp56300` C++ emulator). That build is the real first task of Route 2, not part of the
confirmation.

### Artifacts (all gitignored under `out/dsp/`, regenerable)

- `out/dsp/payload_A.mem`, `payload_B.mem` — flat `<u8 space><u32 addr><u32 count>` + u32
  words per module, terminator `space==0xff` (octabam `--dumpmem` format; feeds `dsp_host`).
- `out/dsp/A_P01aa4_compressor.bin` (540 B), `out/dsp/B_P01aa4_compressor.bin` — the raw
  180-word COMPRESSOR module, LE 24-bit words. Disassemble once the toolchain exists:
  `dsp56kDisassemble -in out/dsp/A_P01aa4_compressor.bin -pc 1aa4 -le`.
- Regenerate: `python3 refs/octabam/tools/dsp_modmap.py [--dumpmem A out.mem | --extract A 1aa4 out.bin]`
  from the repo root (needs `refs/` synced — `python3 tools/refs/sync.py`; octabam pinned
  at `e1dcfa9`).

### Session 17 continued (2) — DSP56300 disassembler built + the COMPRESSOR fully reversed

**Toolchain:** built `vendor/dsp56300/build/source/disassemble/dsp56kDisassemble` from
`github.com/dsp56300/dsp56300` (`--depth 1`, no patches, target `dsp56kDisassemble` only —
minimal surface; the MPYRI emu-patch + `dsp_host` are only needed for *emulation*, add later
if Route 2 goes ahead). Build script: scratchpad `dsp_toolchain_setup.sh`; log
`out/dsp/toolchain_setup.log`. Ran by the user in Terminal (auto-mode blocks the clone/brew).
`vendor/` is gitignored.

**Full disassembly saved:** `out/dsp/A_P01aa4_compressor.asm` (payload A, `-pc 1aa4 -le`),
`out/dsp/B_P01864_compressor.asm` (payload B — byte-identical logic, relocated). 180 words,
one `rts`-terminated init + one process routine, ABI = octabam's stub contract
(`r0` in / `n7` samples / 2 interleaved channels; writes output back in place via `r0`).

**Null passthrough stub `P:0x007c9`** (the Route-2 key-tap host) disassembled — confirms
`move r0,r1 ; do n7 { a=x:(r0)+ ; b=x:(r0)+ ; x:(r1)+=a ; x:(r1)+=b } ; rts`. 9 words,
in-place, exactly the ABI spec.

#### COMPRESSOR process routine — the six stages (`0x1ab1`–`0x1b57`, payload A)

| # | addr | what | params read |
|---|---|---|---|
| 0 | `1ab1` | `move r0,n6` — **anchor the true input pointer** (used again in 4 & 6) | — |
| 1 | `1ab3`–`1ab9` | **detector input**: `x:(r0)+` stream → square (`mpy x0,x0`) → running pair-max (`maxm`) → write n7 power samples to **Y:0x61+** | — (reads `r0` audio) |
| 2 | `1aba`–`1ac2` | read page-2 param, `asr #$10` → 0..127, index one-pole coeff `x:(param+$7811)` | **`r6+$c`** = RMS (detector time-constant) |
| 3 | `1ac3`–`1aca` | leaky-integrator RMS smoother `a += k·(det−a)` over Y:0x61 → smoothed 48-bit env to **Y:0x62+**; state in `r7+$15/$19` | — |
| 4 | `1acb`–`1afb` | **gain curve**, per sample: `clb/normf` + `LOG[$6c00+m]` → log(env); `− THRS·k`; `× RAT-slope` (`maci #$c04000`); `clr ifmi` (knee floor); `EXP[$7400+frac]` → linear; store gain → Y:0x62+ | **`r6+$2`=THRS, `r6+$3`=RAT** |
| 5 | `1afb`–`1b1c` | attack/release ballistics on the gain: coeff `ATK=X[$7811+p·$80]` (`r6+$0`), `REL=X[$7891+p·$80]` (`r6+$1`); `cmp`→pick ATK if gain rising else REL; one-pole; state `r7+$11/$12` | **`r6+$0`=ATK, `r6+$1`=REL** |
| 6 | `1b1d`–`1b57` | `move n6,r0` (**re-anchor**); wet = in·gain → Y:0x40+; makeup `r6+$4`²; dry/wet from `r6+$5`; per-block coeff ramp (Y:0xc8+, `r7+$1a/$1b`, first-block gate `r7+$f` bit0); mix wet+dry → **write back to `r0` in place** | **`r6+$4`=GAIN(makeup), `r6+$5`=MIX** |

**Parameter map (confirms octa-bt-pt registry):** `r6+$0` ATK · `+$1` REL · `+$2` THRS ·
`+$3` RAT · `+$4` GAIN · `+$5` MIX (page 1) · `+$c` RMS (page 2, slot 6).
Coeff tables (payload-A X): `0x7811` attack/RMS, `0x7891` release, `0x6c00` log, `0x7400` exp.
State block: `r7+$f` flags (bit0 = first-block), `+$10` const `0x20c5`, `+$11/$12` gain
ballistics, `+$13` unused?, `+$15/$19` detector env (48-bit), `+$1a/$1b` mix ramp.

#### ⇒ The Route-2 sidechain tap point is now known

Stage 1's detector reads **`x:(r0)+`** (the effect's own input). The dry/wet path in stages
4 & 6 does **not** use r0's post-loop value — it re-loads `move n6,r0` — so **detection and
gain-application are independent passes over the buffer.** Redirecting *only* stage 1's read
(`0x1ab3` + the `x:(r0)+` in the `0x1ab6/0x1ab7` loop) to a shared-Y `keybus[KEY]` buffer
keys the compressor off another track **with zero effect on its dry signal** — the cleanest
possible tap. DSP-side delta ≈ a handful of words: a source-select branch gated on a new
`KEY` param (free page-2 slot `r6+$d`), plus optionally a 1-pole HP on the key. Fits the
180-word module or a small cave (payload budget ~2,724 words).

**Still open (unchanged):** (a) the *publish* side — who fills `keybus[t]` with track t's
pre-FX audio. Extending the null stub `P:0x007c9` is trivial (`a,y:(r_kb)+`) but only fires
for FX slots = NONE; unconditional tap = frame-builder hook (bigger, unmapped). (b) same-DSP-
core constraint (key+target both T1–4 or both T5–8). (c) `r7 → track index` map for
`keybus[slot]`. (d) MKI DSP flash is untested territory.

### Session 17 continued (3) — user design constraints for the side-chain build

**1. MKI DSP flash de-risked.** User saw a MKI owner flash octabam (a DSP-patched image)
with no problems. Open item (d) "MKI DSP flash is untested territory" downgraded from a real
risk to "very likely fine" — the stock 1.40C file is byte-identical MKI/MKII and now there's
a field data point. Still our own first DSP flash, so treat with the usual care, but not a
blocker.

**2. Key filter — LOW-pass, not the reflexive high-pass.** My earlier "1-pole HP on the
key" was the *internal* side-chain convention (comp keys off its own full-range signal →
HPF the detector ~80–150 Hz so bass energy doesn't dominate). This feature is an **external
key**, and the user's instinct is right: keying off a full-spectrum drum loop and wanting
*only the kick* to drive the ducking calls for a **LPF / band-pass around the kick band**
(~50–120 Hz), rejecting hats/snare. Decision: **one bipolar `KEY FLT` knob** — `64` = off,
turn down = LPF sweeping ~2 kHz→40 Hz (isolate the thump), turn up = HPF sweeping
40 Hz→2 kHz (the classic detector HPF, still available for whoever wants it). Covers both
in one page-2 slot. DSP: 2-pole (12 dB/oct) state-variable on the key stream ≈ 20–30 words
(1-pole is too gentle to pull a kick out of a loop with hats). Formatter shows
`LP 120` / `OFF` / `HP 200`.

**3. Dynamic KEY chooser — same-core tracks only, and that's all it can reach.** FEASIBLE.
Mechanism (octabam `PARAM_PAGES.md` §7 + `FUN_40031da4`):
- `KEY` param `E+0xd2` count = **5** (`OFF` + 4). Value stored = **core-relative index 0–4**.
- Custom A-formatter (`E+0x11a`, sig `fmt(char *buf, int value)`, *may read globals*): read
  the current edit-track number; value 0 → `"OFF"`; values 1–4 → `"T1".."T4"` when track ∈
  1–4, `"T5".."T8"` when track ∈ 5–8. `B`-widget = 0 (plain dial prints the A text).
  ~20-byte code cave (proven pattern; cave region `0x400d7000–0x400d7c3c`, and our build
  already ships/pins a ColdFire cave).
- DSP resolves `keybus[coreBaseTrack + (value − 1)]` where coreBase = 1 or 5.
- Result: a compressor on T3 can only ever select `OFF/T1/T2/T3/T4` — **disconnected tracks
  are not merely hidden, they are unreachable.** Exactly the user's ask.
- Own-track *is* offered (harmless — `KEY=own` + `KEY FLT` = the internal-side-chain-filter
  case, a bonus).
- Future-proof: if the cross-core bus (octabam XBUS) is ever adopted, bump count to 9 and
  the formatter shows all 8 — the design doesn't fight that later.
- **To find at build time:** the "current edit-track" global (a caller of `FUN_40031da4`
  passes it; candidates near `0x46c7dd26` — the word the page-class handler already checks).

**Proposed page-2 layout** (packed from `r6+$c`; octabam warns page-2 r6 offsets are
"less certain — verify"): `RMS`(existing, `r6+$c`) · `KEY`(`+$d`) · `KEY FLT`(`+$e`) ·
`KEY GAIN`(`+$f`, key drive into the detector — a loop's kick may be quiet) ·
`SC LISTEN`(`+$10`, OFF/ON monitor the filtered key) · one spare.

**4. Self-key (`KEY = own track`) — analysed.** Not a bug, not a feedback loop: the
detector always reads an input-side signal, the compressed output is only written back at
the very end (`0x1b53`), and `keybus[t]` is never fed from the compressor's output. Worst
case a gain-bounded 1-frame wobble, never instability. `KEY = own` is **"internal
sidechain"**: `KEY FLT` centred → identical to `KEY = OFF`; `KEY FLT` engaged → detector
hears a filtered copy of the track's own signal while the full signal is compressed (the
classic de-ess / stop-the-bass-pumping move). Keep it selectable.
- **But it exposes the tap-placement trap.** If `keybus[t]` is filled by extending the NONE
  passthrough stub, the tap sits wherever the NONE slot is: compressor in **FX1** + FX2 =
  NONE → the FX2 stub runs *after* the compressor and would publish the **compressed**
  output, so self-key (and any same-track dependency) keys off a 1-frame-delayed feedback of
  the comp's own output. Messy, not dangerous.
- ⇒ **Prefer the frame-builder / dispatcher tap** (pre-FX, unconditional) so `keybus[t]` is
  always the clean track input regardless of FX-slot layout. Belt-and-braces: DSP
  short-circuits `KEY == ownTrack` to read `r0` directly (still filtered). This firms open
  item (a) toward "map the per-track pre-FX tap point," away from the stub hack.

### Session 17 continued (4) — DSP per-track dispatcher mapped; publish injection point found

Disassembled the DSP frame engine's per-track FX loop (payload A): modules `P:0x002bf` +
`P:0x003a1` (setup) + `P:0x0041e` (dispatcher, 429 w) + `P:0x005cb` (per-track
filter/AMP/env). Key structure:

**Per-track loop** `func_000385` → `0x53c bne func_000385`, **4 iterations** (`x:0x418`
counter `0x20 → 0x80`, `+0x20`/track) = **4 tracks per DSP core** (confirms octabam).
Per iteration:
- `0x385`–`0x39f`: pick this track's param descriptors (`x:0x415`/`x:0x416` + track offset
  → `x:0x208` a-side, `x:0x419` b-side); decode split point `a = x:(r2+$1e)>>8 & 0xf` →
  `x:0x20c`=split, `x:0x20d`=`0x10-split`, `x:0x20e`=`split*2` (buffer offset for the 2nd
  segment).
- `0x3a1`–`0x41d`: unpack the compact per-track FX param block (`x:0x209`, stride **0xA8**)
  into the working param area (`X:0x40+` and the `r6` blocks).
- `0x426`–`0x4a6`: frame-context setup + **crossfader/scene param morph**; a 16-tap input
  filter at `0x498` writes the track's audio into **`X:0x0000`** (crossfade path). Tracks
  the crossfader doesn't touch `beq func_0004a7` — skip straight to dispatch, `X:0` already
  holding their input.
- **`func_0004a7`**–`0x50d`: **the dispatch.** FX1 (id `x:(r6+$1b)`) then FX2 (id
  `x:(r6+$1c)`), each: optional `INIT_TABLE[id]` (`x:(r1+$215)`) call on id-change, then
  `PROCESS_TABLE[id]` (`x:(r1+$235)`) — called **twice** for a split block (a=0 seg with
  `r0=0`, then a=1 seg with `r0=x:0x20e`), once (`r0=0`) otherwise. `r6` advances `+6`
  (`n6`), state ptr `x:0x20a` advances `+0x100` per effect.
- `0x50e`–`0x53c`: mix `X:0` working buffer → per-track output slot `x:0x206` (stride
  **0x40**); advance `x:0x420` (**per-track counter**, +1), `x:0x209 += 0xA8`,
  `x:0x206 += 0x40`, `x:0x418 += 0x20`; loop.

**⇒ Publish injection point for `keybus[t]`: `func_0004a7` (`P:0x004a7`).** At that PC
`X:0x0000` is guaranteed to hold the track's FX-chain input (FX1's process reads it on the
very next call; both the crossfade path — 16-tap filter at `0x498` — and the skip path have
finalised it by `0x4a7`). Inject ~10 words: `copy X:0 (2·n7 words) → keybus[coreBase +
idx]`, `idx` from `x:0x420`. **No dependence on how `X:0` was filled upstream** — by
definition it is the chain input at that instant. Sidesteps the octabam "stock buffer
convention is hard to fully reconstruct" problem (`refs/octabam/docs/DSP.md` §6b).

**`keybus`**: absolute Y at `0x800+` (octabam's proven-safe-in-both-payloads region), e.g.
`Y:0x800`, 8 slots × 0x20 w. Each core writes its own 4 slots, the compressor reads any of
its **same-core** 4 → **no cross-core traffic, none of octabam's XBUS race machinery
needed.**

**Build-time unknowns still to nail (all small):**
1. `x:0x420` exact semantics — 0-based? per-core (0–3) or absolute (0–7 / 4–7)? where reset
   each block? (Determines `coreBase` arithmetic.)
2. **Which 4 tracks each payload serves** — octabam measured A=T5–8 / B=T1–4 but flags it
   "settle empirically" (octa-bt-pt disagrees). Confirm on our image / HW before indexing.
3. Free page-2 `r6` offset for `KEY` (octabam: page-2 offsets "less certain — verify").
4. ColdFire: the "current edit-track" global for the dynamic KEY formatter (caller of
   `FUN_40031da4`).
5. Program-space budget: payload ~2,724 w shared; compressor 180→~230, dispatcher +~10,
   `KEY FLT` filter +~30 → need a cave / reclaim (octabam reclaims the 3 FX2 reverbs; we
   only need ~70 w, much less drastic).

### Proposed build order (each a checkpoint, emulate-then-flash)

1. **Menu-only, no DSP:** add `KEY`/`KEY FLT` page-2 params to the COMPRESSOR descriptor +
   the dynamic formatter; DSP ignores them. Proves the ColdFire side + the formatter on HW.
2. **keybus plumbing:** dispatcher tap at `0x4a7` + compressor detector redirect, `KEY`
   only (no filter). Emulate with `dsp_host`, then HW: kick on T1 keying a pad's comp on T2.
3. **`KEY FLT`** (2-pole SVF on the key stream) + `KEY GAIN`.
4. **`SC LISTEN`** monitor + polish.

### Session 17 continued (5) — BUILD STEP 1 DONE: KEY parameter on the COMPRESSOR page (menu only, emu-clean, NOT flashed)

`tools/patch_sidechain.s` + `tools/build_sidechain.py` + `tools/emu_sidechain.py`.
Output: `out/OCTATRACK_OS1.40C_SIDECHAIN.{syx,bin}` (`140C_KYOTI`), 154 B vs stock.
Base = stock 1.40C + `patch_trigscale` (Bug-1 fix, byte-identical to
`build_trigscale_only.py`). **The DSP is untouched — KEY does nothing audible yet.**

**COMPRESSOR descriptor RE'd in full** (`E = 0x400d5a4a`, entry size `0x192`, 31-entry
table `0x400d2e52…0x400d5f00`). Layout (E-relative, confirms octabam PARAM_PAGES §2 +
corrects §7's P-offset confusion — there is **no separate enable bitmap**, a slot is
visible iff its name is non-blank):

| off | field |
|---|---|
| `E+0x3b` | u8 effect id (`0x18`) |
| `E+0x3c` / `E+0x41` | abbr / full name, NUL-term |
| `E+0x4e` | 12 × 6 B param names (6 pg1 + 6 pg2), blank = hidden encoder |
| `E+0x96` | 12 × u8 default |
| `E+0xa2` | 12 × u32 min |
| `E+0xd2` | 12 × u32 **value count** (128 = 0–127 continuous, N = an N-way select) |
| `E+0x102` | 12 × u32 **A** = per-slot text formatter `void fmt(char *buf,int val)` |
| `E+0x132` | 12 × u32 **B** = per-slot widget drawer (`0` = plain dial, prints A's text) |
| `E+0x162` | 12 × u32 **C** = per-slot page-class handler (`0` = default; else `0x40032814` / `0x400328e4`) |

Stock COMPRESSOR params: `[0]ATK [1]REL [2]THRS [3]RAT [4]GAIN [5]MIX` (pg 1) ·
`[6]RMS` (pg 2) · `[7..11]` blank-named, vestigial (counts 2/128/2/128/128).

**Step-1 edits — all data pokes on slot 7 + one formatter cave:**
| addr | was → now |
|---|---|
| `0x400d5ac2` name[7] | `000000000000` → `"KEY\0\0\0"` |
| `0x400d5b38` count[7] | `2` → `5` (OFF + 4) |
| `0x400d5ae7` default[7] | `1` → `0` (OFF) |
| `0x400d5b68` A[7] | `0` → `key_fmt` (`0x400d7000`) |
| `0x400d5b98` B[7] | `0x400475f8` → `0` (plain dial) |
| (`0x400d5b08` min[7] asserted `0`; C[7] left `0`) |

**`key_fmt`** (80 B cave @ `0x400d7000`): `fmt(buf,val)` — `val 0` → rewrite stack args
+ tail-`jmp` `sprintf`(`0x40013a08`)`(buf,"OFF")` (mimics stock `FUN_4003c14c`); `val 1..4`
→ `sprintf(buf,"T%d", coreBase + val - 1)` where `coreBase = 1` if `*(u8)0x100b14cc` (current
edit-track) `< 4` else `5`. So a compressor on T3 shows only `OFF/T1/T2/T3/T4`, one on T6
only `OFF/T5/T6/T7/T8` — **disconnected tracks are unreachable, per the design ask.**

**Validation:** build round-trips (aPLib + ELEK checksum OK); manual-trig fix byte-identical;
adjacent descriptor entry (MBC) intact. `emu_sidechain.py` (real cave under Unicorn, sprintf
stubbed) — **ALL GOOD**: 8 tracks × values 0–4 all format correctly, both "chooser set"
checks pass.

**HW test (`NOTES` build-order step 1):** flash `OCTATRACK_OS1.40C_SIDECHAIN.syx`. Put
COMPRESSOR in an FX slot → FX SETUP **page 2** → the encoder after `RMS` is `KEY`. Confirm:
(a) shows `OFF` by default, scrolls `OFF→T1→T2→T3→T4` on tracks 1–4 and `OFF→T5..T8` on
5–8; (b) p-locks + survives PART save / project reload; (c) nothing else on the compressor
page changed; (d) no crash/glitch entering the page or turning the knob. Revert = flash
stock `downloads/extracted/OCTATRACK_OS1.40C.syx`. **Then → step 2 (keybus plumbing).**

### Session 17 continued (7) — STEP 2 DSP code written + assembles clean (38 words/payload); dsp_asm+dsp_host built

**Toolchain complete:** `vendor/dsp56300/build/.../dsp_asm` + `dsp_host` built (octabam's,
staged from `refs/octabam/tools/dsp_host/`). `dsp_asm` constraints found the hard way:
**no directives / no constants / no `jmp` / no `jcc`** — only relative b-forms, labels
substituted textually (as `$disp` for branches). So the code uses literals, a build-time
`@KADJ@` token, and **ends each routine with `rts`** (the build hand-encodes `jsr <cave>`
at the detour sites; control returns via `rts`, no branch-back).

**`tools/patch_sc_dsp.asm`** — assembled at `-org 1da0` for the payload-B variant,
**38 words**, round-trips clean through the disassembler:
- `sctap` (12 w): `x:$420 → idx*$80`; `r1 = Y:$800 + that`; `do #$20 { X:0 → Y:(r1)+ }`;
  displaced `move x:>$208,r6` + `move #$6,n6`; `rts`.
- `scdet` (26 w): displaced `move r0,n6`; `b = x:(r6+$d)` (KEY) `>>16`; `tst b; beq` → if 0,
  `move #$61,r4`; `rts` (stock self-detect). Else `@KADJ@` (`sub #1,a` B / `add #3,a` A →
  abs track); `r1 = Y:$800 + abs*$80`; `do #$20 { Y:(r1)+ → X:$40 }`; `move #$40,r0`;
  `move #$61,r4`; `rts`.
- Both payloads = 38 words (`@KADJ@` is one instruction either way).

**Detour encoding (build, hand-written bytes):**
- dispatcher `func_0004a7` (A) / `func_00029c` (B) — **byte-identical** stock (`move x:>$208,r6`
  `66f000 000208` + `move #$6,n6` `3e0600`): `jsr sctap` (2 w) + `nop` (1 w) over the 3-word
  span... wait, that span is `move x:>$208,r6`(2w) + `move #$6,n6`(1w) = 3 w. `jsr` long = 2 w
  + 1 `nop`. Cave reproduces both moves then `rts` → lands at `func_..+3`.
- COMPRESSOR proc+0 `0x1ab1` (A) / `0x1871` (B) — byte-identical (`move r0,n6` `221e00` +
  `move #$61,r4` `346100`): `jsr scdet` (2 w) exactly over the 2-word span. Cave `rts` →
  `proc+2`.

**Placement — donor still required.** 38 > payload A's 33 free words. A `bsr kbslot` refactor
saves only ~2 w (36). Confirmed there is no quick win:
- payload B free space (~600 w) is **not loader-record-backed** → needs payload-stream surgery.
- the dead-bootstrap tail (`P:0x30048+`) is a HW-only safety question (shared-window), not a
  desktop probe.
So a flashable step 2 needs a donor module in **both** payloads (overwrite its words in
place + point its dispatch-table init/proc entries at the null stub). Recommend SPATIALIZER
(`0x05`, 261 w). This can't be deferred to step 3 after all.

**Step-2 hooks VALIDATED in isolation** — `tools/emu_sc_dsp.py`, dsp56kEmu, **ALL GOOD**:
- `sctap`: for track idx 0/3/7, `keybus[idx]` (Y:`0x800 + idx*0x80`) == the 32 words of `X:0`
  after the run; the rest of the ring untouched.
- `scdet`: `KEY=0` → `X:$40` untouched (stock self-detect); `KEY=1` → `X:$40` == `keybus[0]`
  (CORE_BASE 0, abs = KEY−1); `KEY=4` → `X:$40` == `keybus[3]`.
- The `jsr scdet` detour byte-patch (`0bf080 <org>` over `move r0,n6` + `move #$61,r4`) is
  asserted against the real payload-B COMPRESSOR module inside the harness.

**dsp_host can't run the stock COMPRESSOR end-to-end** (it sets `r7=0x200`, targets octabam's
own effects) — so the full "detector's gain reduction tracks keybus" chain is a **hardware**
test, not a desktop one. The isolation harness covers the hook mechanics; the audio outcome
is HW.

**Page-2 param packing found (octabam `PARAM_PAGES` / dsp_host, "cost months"):** each page-2
descriptor word holds **two** controls — slot 6→`r6+$c` bits16-23, slot 7→`r6+$c` bits8-15,
slot 8→`r6+$d` bits16-23, slot 9→`r6+$d` bits8-15, … So **step 1's KEY moved from descriptor
slot 7 → slot 8** (`r6+$d` knob = what `scdet`'s `asr #$10` reads). RMS stays slot 6; slot 7
blank → a stock-normal page-2 gap (CHORUS/EQ do the same). `build_sidechain.py` updated,
`emu_sidechain.py` re-passes, image re-built (150 B vs stock).

**Still to do for step 2:** (1) donor pick (37 w > payload A's 33 free — a `bsr` refactor
saves ~2 w, not enough); (2) `build_sidechain2.py` — DSP-payload patcher: assemble
`patch_sc_dsp.asm` per payload (`@KADJ@` = `add #3,a` A / `sub #1,a` B), place at the donor
`-org` (`jsr` short-form-reachable, ≤ `$fff`), hand-encode the 2 detours (`jsr` short =
`0d0<addr>` 1 w; long = `0bf080 <addr>` 2 w), retarget the donor's `X:0x215`/`X:0x235`
dispatch entries to the null stub; (3) `keybus` Y-region runtime-safety (inherit octabam
§11, watch on HW); (4) HW validation.

Doc note for users: `X:0` at the tap point is **post-AMP-VOL** — mute keeps a key track
keying (mute is downstream), but AMP VOL 0 kills the key. Silence a key track with mute.

### Session 17 continued (8) — STEP 2 BUILT (SPATIALIZER donor, both payloads); emu-clean; NOT flashed

`tools/build_sidechain2.py` → **`out/OCTATRACK_OS1.40C_SIDECHAIN2.{syx,bin}`** (`140C_KYOTI`,
**380 B vs stock**). = stock 1.40C + Bug-1 fix + step-1 KEY menu (slot 8) + the step-2 DSP
hooks. User picked **SPATIALIZER (`0x05`) as the donor.**

**DSP patch, per payload (A / B):**
| target | file A / B | change |
|---|---|---|
| SPATIALIZER P region (`0xaa8` / `0x868`, 261 w) | `0xf1371` / `0x1042c2` | first 37 w overwritten with the `sctap`+`scdet` cave (assembled per payload, `@KADJ@` = `add #3,a` / `sub #1,a`); the other 224 w become dead code |
| dispatcher FX1 entry `func_0004a7` / `func_00029c` | `0xf008d` / `0x10307d` | `move x:>$208,r6` (2 w) → `jsr <sctap>` (`0d0aa8` / `0d0868`, 1 w) + `nop`; the following `move #$6,n6` left in stock |
| COMPRESSOR proc+0 `0x1ab1` / `0x1871` | `0xf43f8` / `0x107349` | `move r0,n6` + `move #$61,r4` (2 w) → `jsr <scdet>` (`0d0ab7` / `0d0877`) + `nop` |
| dispatch table `X:0x215[5]` init / `X:0x235[5]` proc | `0xe1f45`+ / `0xf5610`+ | SPATIALIZER's id-`0x05` entries → null stub (`0x7c8`/`0x7c9` A, `0x588`/`0x589` B) — SPATIALIZER now passes audio through |

**SPATIALIZER is removed from both FX choosers** (not just degraded) — it was bad UI to
leave a dead entry selectable. Mechanism (octabam `PARAM_PAGES` §5e): the two chooser lists
are NUL-terminated arrays of `E+0x38` descriptor pointers — `FX1 = 0x400d6060` (11 entries),
`FX2 = 0x400d6090` (15) — SPATIALIZER at position 7 in both. Drop its pointer, shift the
rest up, move the terminator. Then rebuild `ID2POS = 0x400d6150` (`u32[id]` → cursor
position): `id 0x05 → 0` (a legacy project that still stores SPATIALIZER lands the chooser
cursor on NONE) and every id past position 7 shifts down one. Result: FX1 10 entries, FX2 14
— both well above the renderer's fixed 7-row viewport, so no garbage rows. A legacy project
with SPATIALIZER still *shows* "SPAT" on the slot (id-lookup table untouched) and passes
audio through (null stub); re-selecting anything drops it.

**Verified:**
- byte-diff vs stock: **exactly 2 words** changed at each detour site, all surrounding stock
  code byte-identical; SPATIALIZER word 37+ untouched (harmless dead).
- FX1/FX2 chooser lists after: `NONE FLTR EQ DJEQ PHSR FLNG CHOR COMB COMP LOFI [DEL PLTE
  SPRG DARK]` — no SPAT; `ID2POS` consistent with the new positions.
- both patched payloads still parse **100%** (`dsp_modmap`); image round-trips (aPLib+ELEK
  checksum OK); Bug-1 fix byte-identical to `build_trigscale_only.py`.
- **`emu_sc_dsp.py --patched`** (real cave at SPATIALIZER `0x868`, real detour in the
  compressor module, regenerated payload-B `.mem`) — **ALL GOOD**: `sctap` copies `X:0` →
  `keybus[idx]`; `scdet` KEY=0 leaves the detector, KEY=1→`keybus[0]`, KEY=4→`keybus[3]`.

**NOT verified — hardware only** (dsp_host can't run the stock compressor):
1. the compressor's detector actually producing gain reduction *driven by* the keybus signal;
2. the `do #<$20` copy count vs the real frame's `n7` (isolation copied a fixed 32 correctly);
3. `Y:0x800–0xBA0` keybus region runtime-safe in both payloads (octabam §11 says ≥`0x800`
   is safe — watch for hash/instability);
4. muted-key behaviour (design says free — mute is downstream of the `X:0` tap);
5. SPATIALIZER→passthrough is graceful on a project that still selects it;
6. no glitch on the first FX1 dispatch of a split block.

### Session 17 continued (8) — HW test plan (do this after flashing SIDECHAIN2)

1. **No-regression:** every existing check (OT/OT+FX mute — wait, MUTEMODE is NOT in this
   build; it's stock+trigscale+sidechain — so: Bug-1 manual-trig, boot string `140C_KYOTI`,
   all stock FX except SPATIALIZER unchanged, SPATIALIZER now = clean passthrough).
2. **KEY menu** (step-1 checklist): `COMPRESSOR` → FX page 2 → `KEY` after `RMS`, `OFF` +
   `T1..T4` / `T5..T8` per bank, p-locks, survives save/reload.
3. **The feature:** kick loop on T1, pad on T2 with `COMPRESSOR` (THRS low, RAT high,
   ATK fast, REL ~med), `KEY = T1`. Expect the pad to duck on every kick. Sweep the
   target across T2/T3/T4 and the key across T1/T2/T3/T4.
4. **Muted key:** mute T1 — ducking should continue. Then set T1 `AMP VOL` 0 — ducking
   should stop (tap is post-AMP-VOL; documented).
5. **Cross-bank is inert:** `COMPRESSOR` on T2, `KEY = T3` works; there is no way to pick
   T5–T8 from T2 (formatter). A compressor on T5 keyed by T5–T8 also works (payload A).
6. **Stress:** compressors on several tracks all keyed; FX2 slot also in use; split trigs;
   listen for clicks / hash / runaway on the ducking envelope.

### Session 17 continued (6) — STEP 2 DESIGN: keybus plumbing, quad-buffered from day one

Design for the DSP side: publish each track's pre-FX audio to a shared Y ring, and
redirect the COMPRESSOR's detector to read a chosen track's ring instead of its own input.
**Cross-core assessed (`XBUS.md`): octabam hardware-confirms it works.** Our case drops 2 of
octabam's 3 race classes (no accumulate ⇒ no clear ⇒ no clear-vs-read / clear-vs-write); only
the torn-read race remains, fixed by quad-buffer + read-2-back + a per-core rotation counter
seeded at init. **Step 2 ships same-core only; the ring is laid out quad-buffered now so v2
(any-core) is additive, not a rewrite.**

#### Confirmed this session

- **`x:0x420` = the absolute 0-based track index (0..7)** during the per-track dispatch,
  valid at `func_0004a7`, `+1` per track. Payload A inits it to **4** (`P:0x000381`
  `move #$4,x0; move x0,x:>$420` → tracks 5–8); **payload B inits it to 0** (`P:0x00017a`
  → tracks 1–4). This is an independent, instruction-level confirmation of octabam's
  marker-flash result: **payload A serves T5–8, payload B serves T1–4.**
- Effects' audio buffer is **`X:0x0000`** (`r0 = 0` for a normal block; `r0 = x:0x20e` =
  `2·splitpoint` for a split block's 2nd segment). Detector in COMPRESSOR reads `x:(r0)+`.
- **P-space is the wall.** Payload A P code ends at `0x01fdf` — **33 free words** (octabam
  `CHIP.md`). Payload B ends at `0x01d97` — ~617 free. No general free pool.

#### `keybus` — the ring (Y memory, absolute)

```
KB_BASE   = Y:0x800                     (octabam: abs-Y >= 0x800 is the region proven
                                         safe across both payloads' module maps, DSP.md §11)
per track : 4 buffers x 32 words (16 stereo samples = one max block, interleaved L/R)
layout    : slot(track, gen) = KB_BASE + track*0x80 + (gen & 3)*0x20
extent    : 8 tracks * 0x80 = 0x400 words  ->  Y:0x800 .. Y:0xC00
rotation  : KB_GEN_A = Y:0xC00 (byte), KB_GEN_B = Y:0xC01   (v2 only; step 2 leaves them 0)
```
Y:0x800–0xC00 is unclaimed in both payload module maps (largest stock Y module is
`Y:0x290`, 1024 w, ending `0x690`; then `Y:0x715`). Build asserts it.

#### Donor for the code — **DECISION NEEDED**

~32 w (step 2) → ~130 w (through v2) of P-space code. Payload A has only 33 free words, so
reclaim one stock effect's P region and point its dispatch entries at the null stub (graceful
passthrough, octabam's pattern for absent effects). **Proposed: SPATIALIZER** (id `0x05`,
`P:0x00aa8` A / `P:0x00868` B, **261 words**, self-contained — octabam verified max CF target
`0x00baa` is inside). It is the least-used OT stock effect and 261 w covers all four steps
plus v2. Alternatives: COMB (`0x13`, 277 w) or LO-FI (`0x1c`, 537 w). Reclaimed region =
`SC_CAVE`. (Payload B could instead use its 617 free words and keep SPATIALIZER on T1–4, but
the asymmetry isn't worth it.)

#### Hook 1 — the publish tap (dispatcher, both payloads)

Detour at **`func_0004a7`** — replace `move x:>$208,r6` + `move #$6,n6` (payload A; the
equivalent 2 instrs in B) with `jmp SC_CAVE:tap`. At that PC `X:0x0000` holds this track's
FX-chain input and `x:0x420` = its absolute index. `tap`:
```
  r1 = KB_BASE + x:0x420 * 0x80 + (KB_GEN[core] & 3) * 0x20     ; step 2: gen = 0
  r0 = 0                                                        ; X:0 source
  do #16 { move x:(r0)+,a  x:(r0)+,b ; move a,y:(r1)+  b,y:(r1)+ }   ; 32 words, mono-safe
  move x:>$208,r6 ; move #$6,n6                                 ; displaced originals
  jmp func_0004a7 + <len of displaced>
```
~12 words. Runs once per track per block, for every track regardless of its FX assignment —
so any track can be a key.

#### Hook 2 — the detector redirect (COMPRESSOR process, both payloads)

Detour at **`0x1ab1`** — replace `move r0,n6` + `move #$61,r4` (0x1ab1–0x1ab2) with
`jmp SC_CAVE:detect`. `detect`:
```
  move r0,n6                       ; (0x1ab1) dry path anchor -- UNCHANGED, keeps dry clean
  move x:(r6+$d),a ; asr #$10,a,a  ; a = KEY param 0..4        (page-2 slot 7)
  beq  d_own                       ; KEY 0 -> stock: detector reads X:0 (own track)
  add  #CORE_BASE-1,a              ; CORE_BASE = 0 (payload B) / 4 (payload A)  -> abs track
  r1 = KB_BASE + a*0x80 + (readgen & 3)*0x20    ; step 2: readgen = 0 ; v2: KB_GEN[core]-2
  move #$40,r0                     ; stage the key block into X:0x40..0x60 (free during
  do #16 { move y:(r1)+,x0 ; move x0,x:(r0)+   (x2 for L/R) }   ;  detection; wet uses it later)
  move #$40,r0                     ; detector now streams from the key copy
d_own:
  move #$61,r4                     ; (0x1ab2) displaced
  jmp  0x1ab3
```
~20 words. **The dry/wet path is untouched** — it re-anchors via `n6` at `0x1b1f`/`0x1b46`,
so redirecting only the detector has zero effect on the compressed signal. `X:0x40..0x60` is
free during detector stages 1–5 (COMPRESSOR first writes `X:0x40` in stage 6, `0x1b1e`).

**`CORE_BASE`** is a per-payload build constant (`--defsym CORE_BASE=4` for A, `=0` for B),
because the KEY param stores a core-relative `1..4` and the ColdFire formatter already renders
it as the right absolute track. Same-core is therefore enforced structurally — a `1..4` value
can only ever resolve to one of this core's own 4 ring slots.

#### Step 2 vs v2 (any-core)

| | step 2 (same-core) | v2 (any-core) |
|---|---|---|
| ring layout | quad-buffered (built now) | unchanged |
| `gen` in both hooks | constant 0 | `KB_GEN[core]`, read side `- 2` |
| rotation counter | — | `KB_GEN_A/B`, `+1` once per block per core at the first dispatch (housekeeping hook, seeded at init — octabam: "NOT self-healing") |
| KEY param count | 5 (`OFF`+4) | 9 (`OFF`+8), `CORE_BASE` drops out, DSP reads `keybus[value-1]` |
| formatter | core-aware `T1..T4`/`T5..T8` | shows all 8 |
| validation | `dsp_host` (single-core, exact) + HW | HW **track×track sweep** (octabam: races relocate) |

#### Word count — step 2 does NOT fit payload A's 33 free words

Hand-estimate: `tap` ≈ 17 w, `detect` ≈ 17 w → **~34 words inlined** (no shared helper) in
payload A, which has **33 free**. Payload B (617 free) is fine. So step 2 is **right on the
edge** — 1–7 words over depending on how tight the golf is. Not the clean "single-core needs
no donor" it looked like; it needs either a couple of words shaved or a few spare words from
outside the 33. Step 3 (the `KEY FLT` 2-pole SVF, +~30 w) is where a donor becomes
unavoidable. Options:
- **(a) reclaim the donor now** (SPATIALIZER 261 w etc.) — clean, unblocks steps 2–4 + v2.
- **(b) dead bootstrap region** — `P:0x30048+` (payload A) / `P:0x38000+` (B) hold stock
  bootstrap code that is dead after boot (octabam: "`0x31000`/`0x32000` bootstraps … dead
  after boot"; but `0x30000–0x30047` is live per-frame staging — off-limits). ~100 dead
  words if it verifies. Costs no effect. Risk: in the shared window; needs a probe.
- **(c) hand-golf to ≤33 w** — inline, drop the helper, copy `n7·2` not a fixed 32; fragile.

Recommend (a). User picked "decide later" before this count was known — revisit.

**(d) — read an existing per-track buffer instead of tapping — RE'd, DOES NOT PAN OUT.**
Traced the per-track audio flow:
- **`X:0` is a single reused working buffer.** Per track: raw playback audio arrives in `X:0`
  → `func_0005d0`→`func_0006b7`→`func_0006f7` filters + amp-envelopes it **in place**
  (`x:(r0)+` → `x:(r1)+`, both `r0=r1=0`) → optional crossfade/scene pass (also in place) →
  FX1/FX2 (in place) → `func_00055a` mixes `X:0` into the per-track out slot. `X:0` is
  overwritten by the next track. **No per-track-persistent pre-FX copy exists.**
- The crossfade path (`0x468`–`0x472`) does read a raw per-track input via
  `r0 = x:0x202 − 0xc0 (+0x240 wrap)`, but `x:0x202/203/205/207` are **rolling** frame-DMA
  pointers set by the ISR/frame-context routine, not per-block-stable per-track arrays.
- `x:0x206` (per-track out, stride `0x40`) IS persistent but is **post-FX** and its block
  base is a rolling pointer (advanced `0x100`/block in the prologue + `0x40`×4 in the loop) —
  usable only after more RE, and post-FX isn't the wanted signal.

⇒ **The tap (hook 1) is unavoidable.** Step 2 = ~34 w in payload A, 33 free. Since **step 3
(the `KEY FLT` filter) needs a donor no matter what**, the clean call is **take the donor
now** (option a — SPATIALIZER) rather than golf step 2 into 33 w and then donor step 3
anyway. Golf (c) was a bad suggestion — retracted. Dead-bootstrap (b) stays a fallback if
the user wants to keep every stock effect: `P:0x30048+` (~99 w after the live `0x30000–47`
staging), needs a runtime probe, shared-window aliasing risk.

#### Build-time still-open

1. Payload B's `func_0004a7` equivalent PC + the exact 2 instrs to displace (disasm
   `B_P00221.asm` around the 6 `jsr (r2)` block).
2. Confirm `Y:0x800–0xC00` untouched at runtime in both payloads (octabam's §11 proof
   inherited; watch in the HW test).
3. `dsp_host` harness for step 2: seed `X:0`, run the tap + a COMPRESSOR instance with
   `KEY` set, assert its detector consumed the seeded key block (adapt octabam
   `tools/dsp_host` `-pokey`/`-peeky`).
4. Donor decision (SPATIALIZER / COMB / LO-FI / dead-bootstrap-region probe).

### Session 17 tooling

`out/dsp/` (gitignored): `payload_{A,B}.mem`, `{A,B}_P01aa4/01864_compressor.{bin,asm}`,
`A_P007c8_stub.bin`, `A_P0041e_dispatch.asm`, `A_P00{282,2bf,3a1,5cb,6f4}.asm`,
`B_P00{167,1a4,221}.asm`, `toolchain_setup.log`. `vendor/dsp56300/` (gitignored) — the built
disassembler. Scratchpad: `dsp_toolchain_setup.sh`. **Committed:** `tools/patch_sidechain.s`,
`tools/build_sidechain.py`, `tools/emu_sidechain.py` (step 1). No Ghidra runs.
Sources: `refs/octabam/docs/{DSP,BUS,XBUS,PARAM_PAGES,CHIP,MODULES,FLASHING}.md` +
`tools/dsp_modmap.py` @ e1dcfa9, `refs/octa-bt-pt/patch_tool/registry.json` +
`addresses.json` @ e970dd0, `reference/kb/{dsp56300,memory-map}.md` (on `main`), our
`COVERAGE.md` / `ARCHITECTURE.md`.

## Session 18 (2026-09-06) — ems-octakit open-sourced; distilled into the KB (no firmware work)

**KB ingest only. No RE of our own, no build. `main` branch.**

emuyia/ems-octakit ("Octakit" — 4 Parts/Bank -> 256 Kits/Project) was closed-source
(README + issue templates). Commit `ca3b527` ("add octakit source and build tools",
newer than the `1817ffb` we had pinned) published the whole toolchain. Contributor
added to `CREDITS.md`; `refs/MANIFEST.lock` bumped to `ca3b527` (ems-octakit only —
octamax/octabam left where the last distillation pinned them).

### What we took (all in `reference/kb/octakit-abi.md`, new file)
- `runtime/abi.inc` — ~500 `.equ` symbols. `GK_STOCK_*` = named stock-firmware
  addresses; `GK_*` = struct-offset / enum constants. Curated ~70 of them by
  subsystem; full list stays in the gitignored `refs/` cache.
- `runtime/firmware.json` — 598 SHA-guarded patch sites (`{offset,length,sha256,
  writes}`) + 411 `m68k-relocate`/`stock-copy` ops. The OS SHA-256 it guards is
  `164f3122…` — an independent 598-point confirmation of our image.
- Toolchain: `m68k-elf-gcc 16.1.0 -mcfv4e -Os`; Rust patcher; `sparse-public-write-v3`
  + `authenticated-stock-local-reconstruction-v1` (no stock bytes embedded).
- **Licence: no `LICENSE` file** — same posture as octamax. Facts + small excerpts
  only; not its `.S` / `abi.inc` in bulk.

### Confirms our RE
`GK_STOCK_BANK_POINTER 0x46c82456` = `_DAT_46c82456`; `GK_STOCK_BANK_DESERIALIZE
0x4008ded0` = `FUN_4008ded0`; `GK_STOCK_ENGINE_PART_LOAD 0x40009094` =
`FUN_40009094`; `GK_STOCK_PATTERN_STRIDE 0x8ed8`; `GK_PART_PAYLOAD_SIZE 0x18b2`;
`GK_STOCK_BANK_SIZE 0x9b4d1` = the factory DEMO `bank01.work` size exactly.

### New, and relevant to the Session 13 backlog
- `.work`<->`.strd` store/restore choke points: `0x4008eda4` (banks store),
  `0x4008f0b0` (banks restore), `0x4008ee74` / `0x4008f180` (project).
- Per-parameter-page payload offsets into the part payload: PLAYBACK `0x1da`,
  AMP `0x2f8`, FX1 `0x2fe`, FX2 `0x304`, twelve-byte `0x602`, slice-lock `0x2ca`.
  -> the starting point for turning `file-format.md`'s p-lock `record[step][p]`
  byte offsets into a parameter map.
- `GK_STOCK_SEQUENCER_PART_STEP_OFFSET 0x1832` / `_CONDITION_OFFSET 0x1822` —
  per-step + per-step-trig-condition data inside the part payload.
- `GK_STOCK_PATTERN_HAS_CONTENT 0x4009a464` (is-pattern-non-empty predicate),
  `GK_STOCK_PATTERN_CLEAR_CURRENT 0x4003a244`.
- `GK_STOCK_APLIB_DEPACK 0x400e0aca` (from `loader.S`) -> `container-format.md`.
- Watch: `GK_STOCK_PATTERN_PART_OFFSET 0x8e57` vs OctaLib `+0x8EE7` — different
  framing, reconcile before any write.

### Docs touched
`reference/kb/octakit-abi.md` (new); `kb/{file-format,memory-map,container-format,
techniques}.md`; `reference/EXTERNAL_RESEARCH.md`; `reference/UPSTREAM_INBOX.md`;
`refs/MANIFEST.{toml,lock}`; `CREDITS.md`; `START_HERE.md` §5-6.

## Session 19 (2026-09-06) — MUTE MODE now PERSISTS across power cycle (no-flash; build + emu)

**`main` branch. Build + emulator only — the user is still away from the MKI. Flash-ready.**

### The bug (latent in the shipped MUTEMODE build)
`whatsnew.py` after a re-sync surfaced octamax `c78ff70`
("PERSONALIZE toggles persist — write the battery-SRAM shadow"). It root-causes what our
[NOTES L3263] only *inferred*: **`0x800000xx` is volatile DSP shared RAM**, re-imaged from
ROM on every boot (`FUN_4000f938`, sole caller `0x40000512`: `0x401086f4` → `0x80000000`,
0x3e88 B, then zero-fill to `0x80004000`). So our `move.l %d0,MUTE_MODE` setter was
writing a word that is wiped at the next power-on — **the flashed MUTE MODE setting
silently reverted to `OT` on every boot.** (Not noticed because the user sets it once per
session.)

### The mechanism (octamax's, verified against our image)
The durable PERSONALIZE store is a checksummed 0x100-byte block in **battery SRAM at
`0x100fff00`** — magic `'ANDY'` @ `+4`, version 36 @ `+0xe`, checksum over 252 B from `+4`
(`FUN_4001f23c`; validate `FUN_4001f340`, defaults/zero-fill `FUN_4001f298`). Boot
restores runtime ← shadow with **`memcpy(0x80000070, 0x100fff00, 0x64)`** at three sites
(all confirmed in our `section_3_MAIN_OS.bin` as `48780064 4879 100fff00 4879 80000070
<jsr/lea memcpy>`):

| site | role |
|---|---|
| `0x4001f322` | boot restore |
| `0x4001f3be` | validate-path restore |
| `0x4001fb24` | defaults-path restore |

`0x64` ends at `0x800000d3` — **one byte short of MUTE MODE at `0x800000dc`**. Stock
setters write both copies; the PERSONALIZE key handler re-checksums after every setter
(`jmp 0x4001f23c` at `0x40069074` — confirmed `4ef9 4001f23c 4e75` in our image).

### The fix (`tools/patch_mutemode.s` + `tools/build_mutemode.py`)
1. `build_mutemode.py`: each `pea 0x64` → `pea 0x70` at the three restore sites (asserts
   the stock `48780064` first). Now `0x800000d4..df` ride the restore; end `0x800000df`
   stops one short of the DSP frame selector `0x800000e0` (octamax's boundary).
2. `patch_mutemode.s` `set_mutemode`: after `move.l %d0,MUTE_MODE`, also
   `move.l %d0,SH_MUTE_MODE` where `SH_MUTE_MODE = 0x100fff6c` (= `0x100fff00 + 0x800000dc
   - 0x80000070`). Checksum recompute is free via the existing key-handler `jmp`.
   Patch grew 122 → 128 B in the `0x400d7600` cave (no overlap; well within `0x400d7c3c`).
3. Getter and `patch_softmute`'s GATE read are unchanged — they read the runtime word,
   which is now correctly restored at boot.

Fresh unit / post-OS-upgrade: the defaults path zero-fills the whole block →
`0x100fff6c = 0` → `MUTE MODE = OT` = stock. `get_mutemode` also clamps to `[0,1]`, so
even a stale shadow byte can only read as a valid mode.

### Verified — `tools/emu_mutemode.py` : ALL GOOD
Added: static asserts the 3 restore sites are `pea 0x70` (and stock was `pea 0x64`) and
that `set_mutemode` carries `move.l d0,0x100fff6c`; emu asserts the setter writes **both**
runtime and shadow for every clamp/wrap case; and a boot-restore simulation
(`memcpy(0x80000070, 0x100fff00, 0x70)`) shows `0x800000dc` now lands — and that a `0x64`
copy would still miss it. Existing menu/detour/gate checks unchanged, still green.

### Build
`python3 tools/build_mutemode.py` → `out/OCTATRACK_OS1.40C_MUTEMODE.{syx,bin}` `140C_KYOTI`.
597 bytes changed vs stock (was ~591). **NOT flashed** (no MKI access).

### HW test to run when the MKI is back (adds to the Session-10 checklist)
- PERSONALIZE → MUTE MODE → `OT+FX`; **power-cycle**; PERSONALIZE → MUTE MODE still reads
  `OT+FX` and soft-mute behaviour is active without re-entering the menu.
- Set back to `OT`, power-cycle, still `OT`.
- Re-flash stock 1.40C, confirm PERSONALIZE is back to defaults.

### For the `wip/mute-mode` pickup
Same fix is needed there for **DT** (3rd mode, same word `0x800000dc`) — trivial, `build_mutemode_dt.py`
gets the identical 3-site `pea` patch. **DIRECT JUMP uses `0x800000a8`** — see the
Session 20 "DIRECT JUMP `0x800000a8`" note below for the check + the fix (move to `0x800000d8`).

### Also seen in the re-sync (actioned in Session 20)
octamax +114 (OCTAMAX 2.x); octabam +243 ("RTOS" fork). Re-distilled into `reference/kb/`
in Session 20 below.

## Session 20 (2026-09-06) — KB re-distillation + Session-13 p-lock groundwork (no-flash, `main`)

**No firmware change. Re-synced the 6 refs (`MANIFEST.lock` bumped: octamax
`7d9debc`, octabam `2f241e1`; others unchanged) and folded the new octamax +
octabam research into `reference/kb/`.**

### What went into the KB

**`memory-map.md`:**
- Descriptor table — corrected bounds `0x400d2e52..0x400d5f00` (31 × `0x192`),
  full entry layout (`E+0x96` defaults / `+0xa2` mins / `+0xd2` counts / `+0x4e`
  names / `+0x11a` fmt / `+0x176` class), **added MULTIBCOMP id `0x19` @
  `0x400d5bdc`** (missing from the octa-bt-pt reading), master-track entry −1 @
  `0x400d2e52`, page-class handlers `0x40032814`/`0x400328e4` gating on `0x800000a0`.
- **Track-recorder page** — 3-tier storage (bank blob `[0x46c82456]+0x8f382+
  part*6322+track*12` · SRAM mirror `0x100a54d0` · published `0x80000cf4+track*12+
  [0x800000e0]*96`), part idx `0x100b14cf`. (Bryan T via octabam.)
- **New "Kernel / RTOS"** — scheduler `0x40000550` (trap 0 + PIT0 vec 171), TCB
  layout (`a7` at `+0x48`), current-TCB `0x800068fc`, top-prio `0x800068d8` into
  `0x800068dc[8]`, vector install `0x40000d50`, VBR `0x40000000`, frame handler
  `0x4000aad0` (INTC0 src 1 lvl 5), seq tick `0x400a1e0c` (src 32, INTFRC-delivered
  while masked), 11 tasks + priorities.
- **New "Per-step sequencer data"** — the 8 TRAC step masks, consumers
  `0x4009d1e8` / `0x4009d382..0x4009da12`, flag word `0x46c7a6c0`.
- **New "PERSONALIZE persistence"** — the `'ANDY'` block (from Session 19),
  `FUN_4000f938` boot re-image, restore sites, free-word table with shadow addrs
  and the `0x800000a8` DIRECT-JUMP caveat.
- Cross-confirmed: `0x800065bd/be` = the sequencer's own playing bank/pattern
  (octabam RTOS §8.3 ↔ our Session 15 DIRECT JUMP).

**`file-format.md`:** rewrote the TRAC layout table with octabam's HW-confirmed
mask map — masks `0x00..0x38` at tag-offsets `+0x09..+0x41`; **recorder trigs
REC1/REC2/REC3 = masks `0x20/0x28/0x30` = offsets `+0x29/+0x31/+0x39`** (our old
"delimiter @+0x49" was mis-read — it's two more per-step byte arrays). Added the
**p-lock byte→parameter map hypothesis** (32-B record ≈ `[PLAYBACK|AMP|LFO|FX1|
FX2]` × 6 + 2-B tail; cross-checked vs the DEMO filter-sweep: `0x12` = FX1 p0 =
FILTER cutoff, `0x00` = PLAYBACK PITCH, `0x09` = AMP VOL — confidence **L**), a
**Phase-0 `pattern-diff` test-pattern plan**, and the **Phase-1** handler-hunt
plan. Confirmed disk↔RAM strides survive as `disk − header` (`0x8ed8` / `0x91a`).

**`techniques.md`:** `emu_rtos.py` (the dynamic-analysis tool NOTES L413 asked
for), `emu_check.py` (Unicorn diff-vs-stock pre-flash gate), `ot_project.py`
(`pattern-trig`/`pattern-diff`), the menu-state-table-grow recipe (`0x400cbdac`,
16→17, for adding a whole screen), the cave-ceiling lesson (`0x400d8000`; the OS
`.bss` tail ~`0x40108800` is *not* free), the ANDY persistence recipe, OCTAMAX
2.x dual-256 relocation techniques (noted, not adopted).

**`dsp56300.md`:** `dsp_host` single-core caveat (cross-core bugs never repro
off-unit); post-upgrade warm-up tag → power-cycle. **`FLASHING.md`:** added the
"garbled audio after upgrade → power-cycle first" note + corrected the
"battery-backed RAM" line to point at the ANDY mechanism.

### Session-13 p-lock groundwork — state after this session

- **Data model**: the TRAC block is now C-confident down to the mask level. The
  p-lock array's internal parameter map is **L** (hypothesis in `file-format.md`).
- **Still needs the MKI** — a `pattern-diff` pass over the 6 test patterns in
  `file-format.md` "Phase 0" (30-min job; pins the trigless-lock mask bit + the
  byte→param offsets in one go).
- **Still needs RE** — the LIVE-REC `[NO]`+knob erase handler. Best path:
  vendor octabam's `emu_rtos.py` and watch what a `[NO]`+knob event touches near
  `[0x46c82456] + pat*0x18b2`. Porting `emu_rtos` is its own multi-session task
  (brings octabam's kernel + card models) — not started.

### DIRECT JUMP `0x800000a8` — collision check DONE (no brick risk anywhere)

Whole-image scan of `section_3_MAIN_OS.bin` for `0x800000a8`: **zero ColdFire
references** — no stock code reads or writes it. Also scanned the full stock
PERSONALIZE word set (disassembled all 16 getters/setters):
`0x8c 90 94 98 9c a0 a4 ac b0 b4 b8 bc c0 c4 c8 cc d0` — `0xa8` is not among them.
So `0x800000a8` does **not alias** any stock setting.

What "inside the restore span" actually means: the stock boot does
`memcpy(0x80000070, 0x100fff00, 0x64)` = `0x80000070..0x800000d3`, and `0xa8` is
in that range. DIRECT JUMP's setter writes only the runtime word `0x800000a8`,
never the shadow `0x100fff38`, so **every boot overwrites `0x800000a8` from the
shadow** → on a clean flash (ANDY defaults path zero-fills) that's 0 = `OFF`.
Net effect: DIRECT JUMP's `ON` state does not persist across a power cycle
(resets to `OFF`) — the same non-persistence bug Session 19 fixed for `0xdc`.
**No corruption, no aliasing, no brick.**

**Brick risk: none.** (1) DIRECT JUMP patches the PERSONALIZE menu arrays + 3
sequencer hooks in `FUN_400a1eea` — it does not touch the bootloader. The
Startup-Menu / MIDI-recovery bootloader is a separate flash sector that no OT OS
update writes. (2) `0x800000a8` is volatile work RAM — nothing written there
persists or can corrupt anything. (3) The ANDY block is self-healing: bad
checksum at boot → `FUN_4001f340` → `FUN_4001f298` zero-fills it → PERSONALIZE
resets to factory, recoverable in-menu or via EMPTY RESET. (4) DIRECT JUMP does
not touch the checksum fn, does not extend the restore length, does not write the
shadow region.

**Fix when `wip/mute-mode` is picked up:** move `DJ_MODE` from `0x800000a8` to
**`0x800000d8`** (also 0 refs; shadow `0x100fff68`), and give it the Session-19
treatment — setter writes `move.l %d0,0x100fff68`, and since MUTE MODE's build
already extends the 3 restore `pea 0x64 → 0x70`, `0xd8` rides along for free when
the two features share a build. One-line changes to `patch_directjump.s` +
`build_directjump.py`. Until then DIRECT JUMP just doesn't remember its toggle —
harmless, and it has never been flashed.

### Pre-flash gate recommendation (#5)
Our per-feature `tools/emu_*.py` already cover the "does this splice compute the
same effects as stock" question that `emu_check.py` formalises — keep them, but
adopt its **diff-patched-vs-pristine-STOCK** structure if the count keeps growing.
`emu_rtos.py` is the bigger prize (full task/interrupt interleaving) but is a
port project; flagged in `techniques.md`, not scheduled.

### Pushed
`main` → `origin/main` this session (was 1 commit behind since Session 18):
Session 18 KB commit + Session 19 persistence fix + this Session 20 re-distillation.

## Session 21 (2026-09-06, `wip/mute-mode`, RE / scoping only) — DIRECT JUMP: front-panel toggle, no menu

**User re-scope: DIRECT JUMP activation must NOT live in PERSONALIZE. It should be a
front-panel key combo that toggles `OFF`/`ON`, each press flashing a small transient
overlay "DIRECT JUMP ON" / "DIRECT JUMP OFF" that auto-dismisses after ~0.7 s.**

No flashing available — this session is the design + the RE inventory. Nothing built yet.

### Why this is also a safety win

The current `patch_directjump.s` does the **PERSONALIZE menu-array surgery** (relocate the
3 parallel 16-entry arrays, `moveq #15 → #16`, repoint 5 refs). That surgery is the single
thing that has bricked the MKI before (Session 10 pre-fixes). A key-combo toggle **deletes
all of it** — no array move, no count bump, one code pointer repointed. Strictly lower risk
than the menu version.

### Storage — move `DJ_MODE` to `0x800000d8` + persist it properly

- `0x800000a8` → `0x800000d8` (Session 20 `main` scan: 0 ColdFire refs image-wide; its two
  byte-matches are inside the appended DSP payloads). `0x800000a8` is *inside* the stock
  `0x64` ANDY restore span so its value is clobbered from the (zero) shadow every boot —
  `0x800000d8` is outside it.
- Apply the Session-19 persistence pattern: setter writes shadow `0x100fff68`
  (= `0x100fff00 + 0x800000d8 - 0x80000070`); the build extends the 3 restore
  `pea 0x64 → pea 0x70` at `0x4001f322 / 0x4001f3be / 0x4001fb24`. If DIRECT JUMP and
  MUTE MODE ever share a build the `0x70` extension is done once and `0xd8` rides along.
- **Re-checksum:** the PERSONALIZE dispatcher's `jmp 0x4001f23c` at `0x40069074` is what
  re-checksums the ANDY block after a stock setter. A key-combo toggle does NOT go through
  that path, so our toggle stub must `jsr 0x4001f23c` (`FUN_4001f23c`, the checksummer)
  itself after writing the shadow. One call, no args (it reads `0x100fff04`).
- Default 0 = `OFF` = byte-identical stock, same as today.

### Key infrastructure (RE inventory — `section_3_MAIN_OS.bin`, this session)

- **Physical-key jump table `0x400d2d54`** — keycode-indexed, entries invoked directly as
  `action(edge)` (`edge` 1 = press, 0 = release). Walked 0..39:
  `[0..7]` distinct (track keys), `[8..15]` = default `0x4000184c`, `[16..34]` mixed
  (`[27]=0x4000a274` REC, `[28]=0x4000a200` PLAY, `[29]=0x4000a1e0` STOP; `[17..26,30..32]`
  = a cluster of 4-byte `0x400019xx` micro-stubs = "simple" keys), `[35..39]` = default
  `0x400019f4`. (octabam RTOS §9.3 named REC/PLAY/STOP here.)
- **Page-key path** — `FUN_4005578c(keycode, edge)`, page keys `0x22..0x26`
  (BANK/PTN/PAGE/FX1/FX2 "kind"), remapped through the u32 table `0x400a7280 = {0,2,1,3,4}`.
  (octabam MAINMENU.md.)
- **Keymap records** — 26-byte `{u8 code, 0, press, release, h3, aux, 0, u16 flags}` in two
  tables `0x400bfbf6..` and `0x400c01f4..0x400c0840`. (octabam MAINMENU.md.)
- **Hook precedent 1** — the shelved bankpage patch hooked `FUN_4004ffc4` (`[PAGE]`
  handler) at its entry, replicating the displaced `lea -0x10,SP ; movem` prologue, gating
  on `edge == 1` and swallowing the key with `rts` (NOTES "S3/S3b").
- **Hook precedent 2** — octabam's FX2 shortcut: repoint one jump-table / keymap pointer to
  a ~15-instruction stub invoked as `action(0)`, only `d0` live, check a global, act, done.
- **"No popup open" guard** — `_DAT_460e5cd0 == 0`.
- **Current audio track** = byte `0x80000000` (mirror `0x100b14cc`); MIDI mode = `0x80000012`.

### Transient-overlay primitives (RE inventory)

| primitive | shape | fit |
|---|---|---|
| `FUN_4006d57c(title,nLines,lines,3,handler)` | **blocking** YES/NO dialog | ✗ wrong — modal, needs a keypress to dismiss |
| `FUN_40059f8c(text, ticks, enable, on_timeout)` | auto-dismiss window; **but hardcodes `0x460d1e54 = 4` countdown boxes** and stores its handle in `0x460d1e5c` = the SELECT-BANK/PTN window global (other code keys off it, incl. our own bankpage detect) | ~ usable with a short `ticks`, but the 4 boxes are the SELECT-window look and hijacking `0x460d1e5c` is a side-effect risk |
| `FUN_400808bc`-style overlay via `FUN_4005829c` (window ctor: `x,y,w,h,?,close_cb`) + `FUN_40012f30` (measure text) + `FUN_40057008`/`FUN_40013904` (draw) + a scheduled close | **build our own** — full control of look + lifetime; ~40–60 B of stub | ✓ recommended; matches the user's "small window, disappears fairly quickly" |
| the stock COPY/PASTE/CLEAR/UNDO toast (strings `0x400b4e81/8d/99/a4`) | the real fire-and-forget op-notification | ✓ if found — display fn not yet located (strings are referenced by computed offset; `0x40058ce0` is only the option-list *draw*, not the toast trigger) |

### Open RE tasks before this can be built (needs a Ghidra session)

1. **Pick the combo + confirm it's globally unbound.** Candidates, mnemonic to "pattern
   jump": `[FUNC]` + `[BANK]`, `[FUNC]` + `[PAGE]`, or a double-press of `[PAGE]`. Verify
   against the keymap tables (`0x400bfbf6`, `0x400c01f4`) + the jump table that the chosen
   gesture has no stock action in the base sequencer view (and ideally nowhere).
2. **The `[FUNC]`-held global** (if a FUNC combo) — find the byte the firmware sets while
   `[FUNC]` is down. (octabam may already have it; not in our notes yet.)
3. **Locate the stock op-toast display fn** (task 4's row 4) — or commit to the custom
   overlay (row 3) and pin `FUN_4005829c`'s exact signature + the close path + how stock
   auto-closes a timed overlay (probably a countdown in the UI tick `0x40056c40` /
   `FUN_40056ab8` family).
4. **Choose the hook site** — the jump-table entry for the key, or the keymap record's
   press pointer. Jump-table repoint is the cleaner one-pointer edit.

### Plan for the build (once the above is closed)

- `patch_directjump.s`: **delete** the menu label/getter/setter + keep only the 3 sequencer
  hooks (unchanged) + add `dj_toggle` (the key stub) reading/writing `0x800000d8` + shadow
  `0x100fff68` + `jsr FUN_4001f23c` + the overlay call.
- `build_directjump.py`: **delete** the array relocation / count / ref repointing; add one
  jump-table (or keymap) pointer repoint + the 3-site `pea 0x64→0x70`.
- `emu_directjump.py`: add cases for `dj_toggle` — writes both `0x800000d8` and
  `0x100fff68`, wraps 0↔1, only fires on the gated combo + `edge==1`, swallows the key.
- HW test: press the combo → overlay reads `DIRECT JUMP ON`, disappears ~0.7 s; press
  again → `OFF`; power-cycle → the setting persists; the combo's stock function (if any in
  another view) still works there; DIRECT JUMP behaviour matches Session 15's S2/S3.

### Session 21 continued — RE closed + BUILT (emu-clean, NOT flashed)

**Combo = [PTN] + [YES].** FUNC turned out NOT to be a plain keymap entry (no discoverable
"FUNC held" flag in the time budget), so the user's fallback was taken — and it's
genuinely clean: **no stock key handler reads `0x460d1742`** (the "[PTN] held" flag), so
`[PTN]` + anything is entirely free as a chord.

**Keymap RE** (26-byte records `{code, 0, press:u32, release:u32, h3:u32, aux:u32, 0,
flags:u16}`; two tables T1 `0x400bfc10..` / T2 `0x400c01f4..`, selector structs at
`0x400c090c` / `0x400c0920`). Keycodes: trig 1–16 = `0x00–0x0f` (`0x40060ce0`); track
keys `0x10–0x17` (`0x40040250` → mute `FUN_40083ab4`); param-page keys `0x22–0x26`
(`FUN_4005578c`, via `0x400a7280 = {0,2,1,3,4}`); **PTN = `0x2e`** (`FUN_4005a044`);
**BANK = `0x2f`** (`0x4007af80`); **PAGE = `0x1b`** (`FUN_4004ffc4`); **YES = `0x31`**
(`0x4005e4c8`); **NO = `0x32`** (`0x4005e25c`); MKII MAIN MENU = `0x1c`.

**PTN handler `FUN_4005a044(keycode@4, event@8)`**: event 1 = press → `0x460d1742 = 1`,
clear `0x460d173e`; event 0 = release → opens SELECT PATTERN (`FUN_40059f8c(0x400b484e,
0xf0, 1, 0x40043418)`) **only if `0x460d173e == 0` and `0x460d1ab2 != 0`**. So a chord
partner that sets `0x460d173e` makes the chooser never appear.

**YES handler `0x4005e4c8(keycode@4, event@8)`**: checks arranger `0x460d1aec`
(→ `jmp 0x4004903c`), then `0x800000b8` (`DISABLE YES/NO ARM`) → `rts`, else `bra
0x4005e294` (arm). Does **not** read `0x460d1742`. First 8 bytes = `222f0004 202f0008`
(`move.l 4(sp),d1 ; move.l 8(sp),d0`) — displace 8 with `jmp + nop`, resume `0x4005e4d0`.

**Overlay:** `FUN_4005a0e0(text)` is a **bare text-popup builder** (own handle
`0x460d1e64`, small font, no timeout) that is **DEAD CODE in stock 1.40C** (0 callers) —
noted for a v2. **v1 uses `FUN_40059f8c(text, 0x28, 1, 0)`** — titled window with 4
countdown boxes that drain in ~0.66 s, auto-closes via the existing `FUN_40056ab8` tick.
Handle in `0x460d1e5c` (SELECT-window global) — the only side effect for < 1 s; the
"in SELECT BANK" test also needs `0x460d1e60 == 0x4007b408` which we don't set.

**`FUN_4001f23c`** (the ANDY re-checksum): self-contained, no args, sums `0x100fff04`
+252 B, `+= 514`, writes `0x100fff00`, `rts`. `dj_toggle` `jsr`s it after writing the
shadow — mirrors the PERSONALIZE dispatcher's `jmp 0x4001f23c @ 0x40069074`.

**`dj_toggle` @ `0x4005e4c8`**: `event == press` AND `0x460d1742 == 1` AND `0x460d1aec ==
0` AND `0x460e5cd0 == 0` → `DJ_MODE ^= 1` @ `0x800000d8`, write shadow `0x100fff68`,
`jsr FUN_4001f23c`, `FUN_40059f8c("DIRECT JUMP ON"/"OFF", 0x28, 1, 0)`, `0x460d173e = 1`,
`rts` (swallow). Otherwise replay the 2 moves and `jmp 0x4005e4d0`.

**Build** — `patch_directjump.s`: menu (label/getter/setter/value-table) **deleted**,
`dj_toggle` added, `DJ_MODE` `0x800000a8` → `0x800000d8` + `SH_DJ 0x100fff68`. The 3
sequencer hooks (`dj_a/b/c`) unchanged. `build_directjump.py`: **all menu-array surgery
removed** (no relocation, no `moveq #15→#16`, no ref repoint); adds one detour
(`0x4005e4c8`, 8 B, `jmp`) + the 3-site `pea 0x64 → 0x70` (identical to `build_mutemode.py`
Session 19). → `out/OCTATRACK_OS1.40C_DIRECTJUMP.{syx,bin}` `140C_KYOTI`, **522 B changed
vs stock** (was 684), round-trip ok, Bug-1 fix byte-identical, `patch_directjump` 498 B @
`0x400d7400`. **NOT flashed.**

**Verified — `tools/emu_directjump.py` : ALL GOOD.** New `test_toggle` (7 cases):
OFF→ON / ON→OFF (DJ_MODE + shadow + re-checksum + right string + `0x460d173e` set + YES
swallowed), PTN-not-held → stock resume, release event → stock, arranger up → stock,
popup open → stock. `dj_a/b/c` tests unchanged, still green. (`emu_directjump.py` now
reads the stub offsets from `out/patch_directjump.elf` via `nm` instead of hardcoding.)

### HW test (adds to Session 15's list)

- Base sequencer view: hold `[PTN]`, tap `[YES]` → "DIRECT JUMP ON" flashes ~0.7 s, no
  SELECT PATTERN window. Tap again → "DIRECT JUMP OFF".
- `[PTN]` tapped alone still opens SELECT PATTERN normally (4-second countdown intact).
- `[YES]` alone still arms/disarms the sequencer; `[YES]` in a confirm dialog still works.
- Power-cycle → the ON/OFF setting persists (this is the Session-19 mechanism on `0xd8`).
- With DIRECT JUMP ON, the Session-15 S2/S3 behaviour (next-step switch, playhead resume,
  PC ~1 step ahead) is unchanged.
- Re-flash stock 1.40C → gone, no residue.

### Still open / v2

- ~~The 4 countdown boxes under the text read as a SELECT-window~~ → **BUILT, Session 35**
  (`build_directjump_v2.py`).
- `[PTN]` + `[YES]` shadows the (obscure) stock "arm while a pattern is cued" — acceptable
  per the re-scope, but worth a note in the manual/README for this build.

## Session 35 (2026-09-07, `wip/mute-mode`) — DIRECT JUMP v2 (box-free toast), its own build

**BUILT + emu-clean, NOT flashed.** v1 and v2 are two separate binaries from the same
`patch_directjump.s` (`.ifdef DJ_V2`).

### The overlay difference

| | v1 `FUN_40059f8c(text, 0x28, 1, 0)` | v2 `FUN_4005a0e0(text)` |
|---|---|---|
| look | titled window, h=30px, **+ 4 draining countdown boxes** (the SELECT-BANK/PTN window's own look) | bare 18px text box, **no boxes** |
| handle | `0x460d1e5c` (the SELECT-window global — other code, incl. our bankpage detect, keys off it) for <1 s | `0x460d1e64`, private, dead-code in stock (0 callers) |
| dismiss | boxes drain via `FUN_40056ab8` (~0.66 s) | **`dj_tick2`** frame countdown |

### `dj_tick2` — the auto-dismiss

`FUN_4005a0e0` has no timeout, so v2 adds a countdown. Hooked at **`0x400522ca`**
(displaces `lea 0x46c7dfba,%a2`, 6 B) inside the engine per-control-frame handler
(fn `@0x40052200`, called from `0x40061e8e`; the one that decrements the SOFT MUTE
release watchdog `0x46c7dfba` — so it ticks every frame, playing or stopped).
`dj_tick2`: `G_TOAST` (`0x80006a44`, 4 B, volatile) counts down from `TOAST_FRAMES`
(`--defsym`, default `0xc0`); at 0 → `jsr FUN_40056bc0` closes `0x460d1e64`; then the
displaced `lea` + `rts`. D0 dead here (=119 from the `bge`); D0-D1/A0-A1 saved around
the close (kernel post clobbers them); D2-D7/A2..A6 untouched.

⚠️ `FUN_40056ab8` (the SELECT-window tick, "confirmed on HW" per the Session-2 countdown
note) and `FUN_40052200` both have **0 locatable callers** in a byte scan —
`FUN_40052200` is reached by fallthrough inside its enclosing fn (real caller
`0x40061e8e`); `FUN_40056ab8` is genuinely 0-ref (registered somewhere the scan
misses). v2 uses `FUN_40052200` because its enclosing fn is provably live.

### `djt_show` (v2 branch)

`move.l %a0,-(%sp); jsr FUN_4005a0e0; addq #4,%sp; move.l #TOAST_FRAMES,G_TOAST`
(replaces v1's 4-arg `FUN_40059f8c` call). Everything else in `dj_toggle` — the
`DJ_MODE`/shadow/re-checksum, PTN-chooser suppression, YES swallow — is shared.

### Build + verify

- `tools/build_directjump_v2.py` — same PATCHES as `build_directjump.py` + the
  `0x400522ca` detour + `--defsym DJ_V2=1,TOAST_FRAMES=0x..`. Cave: `patch_directjump`
  546 B @ `0x400d7400` (was 498; +48 for `dj_tick2` + the `djt_show` swap). Divergence
  check: v2 touches only what v1 touches + `0x400522ca` (the dj_a/b/c stubs shift, so
  their detour target words move — expected). → `out/OCTATRACK_OS1.40C_DIRECTJUMP_V2.{syx,bin}`
  `140C_KYOTI`, 572 B vs stock. It also drops `out/patch_directjump_v2.{bin,elf}`.
- `tools/emu_directjump_v2.py` — `dj_tick2` (0/5/1/negative `G_TOAST`, close-clobber
  reg preservation, displaced `lea`) + the v2 `dj_toggle` path (`FUN_4005a0e0` not
  `FUN_40059f8c`, `G_TOAST := 0xc0`). **ALL GOOD.** `emu_directjump.py` now refuses a
  DJ_V2 stub (run `build_directjump.py` to restore v1). v1 emu still ALL GOOD.

### HW test (in addition to Session 21's list — do BOTH binaries)

- v2: `[PTN]`+`[YES]` → plain "DIRECT JUMP ON" box, **no boxes**, gone in ~0.6 s.
  If it lingers / vanishes too fast: rebuild `build_directjump_v2.py 140C_KYOTI 0xNN`
  (the `0x40052200` frame rate is unmeasured).
- Compare the two looks; keep whichever the user prefers as the primary.

## Session 22 (2026-09-06, `wip/mute-mode`) — merge `main`, and DT/SOLO persistence

**No new RE. Merge + a one-line consistency fix.**

### Merged `main` → `wip/mute-mode`

`wip` was 8 commits behind: the Session-18/19/20 knowledge base (kernel/RTOS map,
step-mask map, keymap/keycodes, descriptor-table corrections, `octakit-abi.md`) and the
**MUTE MODE `'ANDY'`-shadow persistence** (Session 19). Conflicts resolved:
- `patch_mutemode.s` — union: the `DT_MODE` `.ifdef` (wip) + `SH_MUTE_MODE` equ + the
  shadow write in `sm_store` (main). `set_mutemode` now writes both `0x800000dc` and
  `0x100fff6c` in every build.
- `NOTES.md` / `START_HERE.md` — kept both sides' session logs (14/15/17/21 from wip,
  18/19/20 from main), wip's §6 frontier as the base.

### DT + SOLO now persist too

`build_mutemode_dt.py` gained the same 3-site `pea 0x64 → 0x70` restore extension as
`build_mutemode.py`. Its "vs build_mutemode.py" divergence check now reports **0 bytes
outside the DT delta** (was 3 — the restore-length bytes). So all three MUTE MODE builds
on `wip` (`build_mutemode.py` OT+FX+SOLO, `build_mutemode_dt.py` +DT) carry the Session-19
persistence, and DIRECT JUMP's `0x800000d8` rides the same extended restore.

### Verified

`emu_mutemode.py` / `emu_dt.py` / `emu_solo.py` / `emu_directjump.py` — **all ALL GOOD**
post-merge. (`emu_solo.py`'s earlier 7-fail is gone — clean here.) Builds:
`MUTEMODE` 639 B, `MUTEMODE_DT` 668 B, `DIRECTJUMP` 522 B vs stock; manual-trig fix
byte-identical across all. Nothing flashed.

## Session 23 (2026-09-06, `wip/mute-mode`) — wire up octabam's full-firmware emulator

**No firmware change. Tooling: `tools/emu_rtos.py`.**

### What

octabam's route-A emulator (`refs/octabam/tools/emu_rtos.py` + `emu_bringup.py` +
`emu_card.py`, ~3700 lines) runs the OS's own scheduler / tasks / interrupts / CF card /
LOAD PROJECT / sequencer. Rather than vendor it (licence posture: `refs/` is a disposable
cache, and it's ~3700 lines), `tools/emu_rtos.py` is a **thin wrapper** — same pattern as
`build_sidechain2.py` loading `dsp_modmap.py` from `refs/`. It runs octabam's script in
place with `--image` pointed at our `out/raw/section_3_MAIN_OS.bin` and `--project`
defaulted to the factory OT DEMO export.

### Verified on our image (SHA `164f3122…`, identical to octabam's pin)

- Plain `unicorn 2.1.4` decodes the CFV4E ops — no special build; octabam's `emu` extra
  is just `unicorn>=2.1`.
- **M6a** `--ms 800 --until-gate` → M6a gate **PASS** (11 tasks created, scheduler runs).
  ⚠️ needs `--ms 800`, not 200 — `main`'s init `memclr` eats the first ~500 ms of budget.
- **M6b** `--load-project` → **PASS** — reads the DEMO `bank01.work` PART FX ids through
  the real storage stack (`PART_PTR=0x400e21e0`, matches `inspect_bank.py --parts`).
- **M6c** `--sequencer --via-key` → starts the transport, steps the bank. **Slow**:
  ~10 s wall per 200 emulated ms; a 400-frame run is minutes.

### The lever for Session 13 Phase 1

`press_key_live(handler_addr, edge)` (M6d) calls **any** key handler as `action(edge)`
via `call_as_main` — parameterised, not hardcoded to PLAY/REC/STOP. So:

1. `--load-project` a bank with a p-locked step (DEMO P11 t2 has filter-sweep locks on
   *regular* trigs — good enough to find the writer even though they're not trigless).
2. Drive into LIVE REC + running (`press_rec_live` / `press_play_live` + `--sequencer`).
3. `press_key_live(0x4005e25c, 1)` — the `[NO]` handler — then call the encoder handler
   (`0x4004eb24` writes the Part-data byte; the p-lock path is a sibling) with a delta.
4. `--watch-mem` the sequenced-data RAM near `[0x46c82456] + pat*0x18b2 + 0x8f385` →
   the function that writes `0xFF` into the p-lock record is named.
5. RE **that one function** statically; design the "if record[step] all-`0xFF` and the
   step is a bare trigless lock, clear its mask bit" detour.

### NEXT

Build the Phase-1 scenario in a `tools/emu_plock.py` (wraps `emu_rtos` with the
load → LIVE REC → `[NO]`+knob → watch sequence). Needs the encoder/knob handler pinned
first (from the keymap: which keycode is a param encoder, and its handler) — a short
Ghidra/disasm task on `0x4004eb24` and neighbours.

## Session 24 (2026-09-06, `wip/mute-mode`) — p-lock RE: RAM address CONFIRMED via emu_rtos

**No firmware change. Tooling: `tools/emu_plock.py` + KB `file-format.md`.**

### `tools/emu_plock.py --confirm` — the RAM p-lock array is exactly the disk layout

Boots our image in octabam's `emu_rtos`, mounts + loads the factory OT DEMO through the
real storage stack, and diffs the RAM p-lock region against `bank01.work`:

**`[0x46c82456] blob + pattern*0x8ed8 + track*0x91a + 0x59`, 64 × 32 B — byte-identical
to the disk `TRAC+0x62` array.** (P11 t2: param header `10 02 00 ff …` and every locked
step / record-offset / value match.) So the disk map *is* the RAM map — the deserialiser
does **not** repack the p-locks. `file-format.md` "RAM p-lock array" upgraded L → **C**.

Blob base was `0x400e21e0` (the M6b "load ends on bank A / engine reset-time select-bank-0"
artefact — RTOS_FORK §7; the data is still correct for the read).

### `FUN_40033e3c` / `FUN_400409f4` are the MIDI-CC-lock layer, not the audio store

RE'd both (30 / few callers). They manage a triplet:
- `0x46c7bf2c` — locked **values**, `[param*128 + step]`
- `0x46c7d7d8` — locked **bitmap**, `param*4` longs, bit `step % 32`
- `0x46c7e0de` — per-param "any lock" flag, `|= 1<<param`

`FUN_40033e3c` writes them (gated on `0x8000004a` **bit 1** = "a trig is held for editing");
`FUN_400409f4` reads each set bit, sends the value out as **MIDI CC** (`FUN_40010bc8`) and
clears the bitmap. So this is the **MIDI-track CC p-lock** send path. The audio per-step
p-lock writer is elsewhere — it writes the blob array above.

### `0x8000004a` — the "what does a knob turn do" bitfield

Read by the encoder handler `0x4004eb24` (bit 0 → write Part data) and `FUN_40033e3c`
(bit 1 → the CC-lock path). 11 refs total. Its writer(s) set the mode when you enter
GRID REC / hold a trig / etc.

### NEXT — finish `emu_plock.py --watch`

The `--watch` scaffold hooks the confirmed audio array + the CC triplet but only runs a
plain playback (baseline: 0 writes). To name the audio-p-lock writer, inject the gesture:
1. `press_key_live(<REC-mode toggle>, 1)` → GRID REC   (find the keycode/handler — it's
   in the keymap; `0x2b/0x2c/0x36` → `0x40030e6c/c60/a6c` are the mute family, not this)
2. `press_key_live(0x40060ce0, 1)` with a trig keycode `0x00..0x0f` in the arg → hold `[TRIG n]`
3. `call_as_main(0x4004eb24, args=(<a1>, <delta>))` → turn a knob
Then `rt.mem_writes` names the function. RE that + its `[NO]`-held erase sibling → design
the "record[step] all-`0xFF` + bare trigless lock → clear the mask bit" detour.

### Session 24 continued — the p-lock RAM structures mapped (4 of them)

Static RE + `emu_plock.py` runs pinned the structures. The **auto-remove feature's
target is #1** (the blob TRAC record); #2–#4 are downstream copies.

| # | Addr | Shape | Role |
|---|---|---|---|
| 1 | blob `TRAC+0x59` (`[0x46c82456]blob + pat*0x8ed8 + trk*0x91a + 0x59`) | `record[step][32]`, `0xFF` = unlocked | **stored** p-locks. RAM == disk `TRAC+0x62` (`--confirm`). Persisted on save. |
| 2 | `0x46c7ab30` / `0x46c76ac0` / `0x46c75fa0` | `[track*32 + param]` values ×2 + `[track*4]` bitmap | sequencer's **live per-track working set** — engine + step handler `0x4009d1e8` read it; per-frame apply `0x4000bad4` copies it into the DSP compute buffer. |
| 3 | `0x46c7aa24` / `0x46c77c32` / `0x46c7a874` | same `[track*32]` shape | **scene** p-lock storage (step handler's `d2 == -1` case). |
| 4 | `0x46c7bf2c` / `0x46c7d7d8` / `0x46c7e0de` | values `param*128+step` / bitmap / flag | **MIDI-track CC-lock** SEND queue — `FUN_40033e3c` writes (gate `0x8000004a` bit 1), `FUN_400409f4` sends each set bit as MIDI CC (`FUN_40010bc8`) then clears it. |

- `FUN_4009b220` fills #2 with `0xFF` (reset) — from boot `0x4001f95c` + project load `0x400238a8`.
- `0x4009b84c` / `0x4009c02c` — 32-byte copy loops splicing #3/pattern → #2 on pattern-enter.
- step handler `0x4009d1e8`: `blob = 0x400e21e0 + bank*0x9b340`, pattern `*0x8ed8`, track `*0x91a`.
- `0x8000004a` = "knob turn does what": bit 0 → Part-data value (encoder `0x4004eb24`); bit 1 → CC-lock.

### `emu_plock.py --watch` — status

Gesture steps run (`--rec` REC press · `--trig N` hold trig · `--knob D --param P` encoder)
and per-PC p-lock writes are captured. **Not settled:** the first `--trig` run watched
oversized windows and reported noise (neighbouring LED buffers at `0x46c7cxxx`); windows
narrowed to `0x400`. The encoder call (`0x4004eb24(param_idx, delta)`) hung with a bad
arg — the a1 convention is a small param index 0–5 via `FUN_4003249c(idx, delta)`, not a
pointer; a knob turn also needs a **staged parameter page** (`0x46c7d244 + idx*20`).

### NEXT (Session 25)

1. `--watch --trig N` with the narrowed windows → confirm trig-hold populates #2 for the
   held step (baseline).
2. Get the encoder call working: stage a page first (or drive the page-select key), then
   `0x4004eb24(3, 5)`; watch #1 (`blob TRAC+0x59 + step*0x20 + param`) for the write →
   names the audio-p-lock **writer**.
3. `--no` (add a `[NO]` press before the knob, keycode `0x32` handler `0x4005e25c`) →
   watch #1 for `0xFF` stores → names the **eraser**.
4. RE the writer + eraser; design the "record[step] all-`0xFF` + bare trigless lock →
   clear the trigless-lock mask bit" detour.

## Session 25 (2026-09-06/07, `wip/mute-mode`) — EMAC-patched Unicorn; FUN_40033e3c is the MIDI-CC path, not audio p-locks

### A: re-sync + the EMAC fix (no-flash tooling)

octabam pushed 21 commits (`2f241e1` → `47f6cc5`, RTOS 10.13–10.16). Headline: **stock
Unicorn 2.1.4's ColdFire fractional `macl` is half of hardware's** (unsigned product
`>> 32` vs signed `<< 1` then `>> 31`) — every `2^31/N` reciprocal idiom (recorder block
walk, PCM pool `0x40095c46`, tempo/timing) was wrong, and octabam's `emu_rtos` now refuses
route A on it. Also: MAC-vs-MSAC is *extension*-word bit 8, not opcode bit 8.

Built the patched Unicorn here: `( cd refs/octabam && PY=$(command -v python3) bash
scripts/build_unicorn.sh )` → `refs/octabam/.venv/lib/unicorn-emac/libunicorn.2.dylib`
(gitignored, native arm64, ~2 min). `emu_bringup` auto-detects it via `LIBUNICORN_PATH`;
`emac_selftest` = **OK**; `emu_rtos` M6a + `emu_plock --confirm` both still pass.
`tools/emu_rtos.py` + `emu_plock.py` now check for the dir and print the build command.

Distilled into `kb/`: the EMAC fix (`techniques.md`), machine-type byte values
**0=STATIC / 1=FLEX / 4=PICKUP** (octabam RTOS §10.13 — corrects the old FLEX/STATIC
guess), the **5-byte per-track slot record** (`part-record +0x2d3 + 5*track + type`),
`0x80004f1c` = the per-track recorder state record (16×84 B double-buffered),
`0x80003c20 + 16*type` block-table reciprocals.

### B: p-lock writer hunt — FUN_40033e3c ruled out

`emu_plock.py --watch --rec --trig 4 --call3e3c 1` (calls `FUN_40033e3c(track, 0x2e, 100)`
directly, after grid-rec + trig-hold): **it writes ONLY `0x46c7bf2c` (#4, CC values) +
its bitmap/flag, and `FUN_400409f4` immediately flushes+clears them.** Nothing to #1
(blob), #2 (`0x46c7ab30`), or #3 (scene). So **`FUN_40033e3c` is the MIDI-track CC-lock
path, not the audio p-lock writer** — settled empirically.

`FUN_40033e3c(track@16, param@20, value@24)`: guard at `0x40033ea4` — `[0x8000003f +
track]` must equal a held trig (`[0x46c76de0]` = the held list) or it bails. Writes
`0x46c7bf2c[param + heldStep*128] = value`, sets `0x46c7d7d8` bit, `0x46c7e0de |= 1<<param`.
The `[NO]` handler calls it with params `0x34–0x36` (`0x4005e164` / `e1a8` / `e1d2`).

Also confirmed (with the windows narrowed to `0x400` — the first run's `0x2200` windows
caught neighbouring LED/TCB buffers and reported noise): **grid-rec + trig-hold alone
write nothing** to the p-lock structures.

### Ruled out for the `[TRIG]`-hold + knob → #1 write

- encoder handler `0x4004eb24` bit-0 branch: writes the *Part* value
  (`[0x46c82456] + part*6322 + …`), not a per-step p-lock.
- bit-1 branch → `FUN_40033e3c` → #4 (MIDI CC).
- the full `0x4004eb24` call hangs under `call_as_main` (it redraws; the UI task can't
  interleave).

### NEXT (Session 26)

Working model: the knob edits **#2** (`0x46c7ab30`) for the held step; a
**commit-on-trig-release** (or commit-on-step) copies #2 → #1`[step]`. So:
`emu_plock.py` — grid-rec, hold trig, poke a value into #2 by hand, **release the trig**
(`TRIG_HANDLER(kc, 0)`), watch #1. The PC that copies #2→#1 is the writer; find its
`[NO]`-held / erase sibling; then design the auto-remove detour.

### No-flash to-do board (Session 25 → onward)

1. **[BLOCKED on MKI / DECISION] trigless-lock feature.** 9 sessions (S26–34).
   Model + detour core action **solid** (S31/S32: trigless lock ≡ `#1[step] !=
   0xFF && TRAC+0x00 clear`; `clear #1[t][step] + 0x400339d8` → LED off, zero
   collateral). **The gap**: the `+0x4900` (LIVE working view) → `#1` (store)
   merge — it's not on the edit path (`0x40041bc4` never writes `#1`; S33/S34),
   it must be in the SAVE serialiser. S34 confirmed the LIVE `[NO]`+knob path is
   too UI/sequencer-state-dependent to drive headless. **Best path = Session 13's
   original Phase 0: HW export-and-diff on the MKI** (build targeted test
   patterns, export, diff banks) — blocked on the MKI being back. Alt: trace
   `0x400645ce` (SAVE) + `0x40025xxx` for the merge (~2–3 emu sessions). NOTES
   "Session 34".
2. ~~**DIRECT JUMP v2**~~ — **BUILT (Session 35)**, `build_directjump_v2.py` →
   `out/OCTATRACK_OS1.40C_DIRECTJUMP_V2.{syx,bin}`, emu-clean, NOT flashed. Box-free
   `FUN_4005a0e0` toast + `dj_tick2` countdown @ `0x400522ca`. HW-test both DJ binaries
   and tune `TOAST_FRAMES` if needed (NOTES "Session 35").
3. ~~**Side-chain step 3 DSP**~~ — **BUILT (Session 36)**: `KEY GAIN` scaler +
   `KEY FLT` 2-pole SVF (`tools/patch_sc_dsp3.asm`) + `SC LISTEN` third hook
   (`sctail`), `tools/{sc_tables,build_sidechain3,emu_sc_dsp3}.py` →
   `out/OCTATRACK_OS1.40C_SIDECHAIN3.{syx,bin}`. `emu_sc_dsp3.py` (isolation +
   `--patched` end-to-end) ALL GOOD, NOT flashed. NOTES "Session 36".
   **⚠️ Session 40:** KEY/KEY FLT/KEY GAIN/SC LISTEN are page-2 params; octabam's
   HW-verified §7 (`kb/memory-map.md` "Parameter value → the engine") shows page 2
   has NO DSP post — it rides only the per-frame copier lane. `emu_sc_dsp3` pokes
   `r6` so it can't see this. First HW check on SIDECHAIN2/3: **turning KEY must
   move `x:(r6+$d)`** (verify the copier forwards our new page-2 slots as it does
   RMS). Also: adding page-2 slots to COMPRESSOR risks the "older slot layout →
   sequencer stalls" trap for existing projects — flash notes need a default guard.
4. **(blocked on MKI)** flash sequence DT → SIDECHAIN2 → SIDECHAIN3 → DIRECTJUMP
   (v1 or v2); the p-lock Phase-0 `pattern-diff` pass; Bug 2 HW confirm.
5. ~~**merge-conflict audit + combined build**~~ — **DONE (Session 45).**
   `tools/build_merged.py` → `out/OCTATRACK_OS1.40C_KYOTI_ALL.*` (all five final-scoped
   mods), `tools/emu_merged.py` ALL GOOD, `reference/MERGE.md` = the allocation map.
   The `[YES]` `0x4005e4c8` collision (DIRECT JUMP vs RELOAD2) is resolved by a
   trampoline (`patch_reload2.s` `.ifdef MERGE`). **Not flashed** — combined image is
   gated behind the per-feature HW passes in item 4. DIRECT JUMP overlay resolved to
   **v3** (`build_directjump_v3.py`, `FUN_4005a2b8` self-timing toast — no boxes, no
   extra hook, no shared handle); flash v3 for the DIRECTJUMP slot of item 4. Remaining
   no-flash: `reload` vs `reload2` still open (build uses `reload2`); port the `MERGE`
   block to `patch_reload.s` if the 3-item wins.

   Nothing no-flash remains on this board except item 1's alt (trace SAVE for the
   `+0x4900`→`#1` merge, ~2–3 emu sessions).

Housekeeping: `emu_rtos` / `emu_plock` need the EMAC-patched Unicorn — run once per
machine: `( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )`.
wip→main KB sync recipe: `git checkout main -- reference/ tools/emu_*.py refs/MANIFEST.lock`.

## Session 26 (2026-09-06, `wip/mute-mode`) — p-lock writer hunt: synthetic calls blocked; static RE of the real clusters

`m68k-elf-objdump` (`/opt/homebrew/bin/`, `-b binary -m m68k:5407 --adjust-vma=0x40000000`)
is on this machine — use it for quick disasm without spinning Ghidra.

### The emulation attempts, and why they didn't name the writer

`emu_plock.py` gained `--release` and `--applyknob PARAM VALUE` (both under `--watch`).

1. **`--release`** (grid-rec → hold trig 4 → poke sentinel `0x2a` into #2
   `0x46c7ab30[1*32+3]` + its companion + bitmap → `TRIG_HANDLER(4,0)` release →
   watch #1): **zero writes** anywhere, blob step 4 unchanged. The
   commit-on-trig-release model is **not reproduced** by this path.

2. **Root cause found**: `emu_plock.py`'s `TRIG_HANDLER = 0x40060ce0` and
   `KEY_REC = 0x4000a274` are from the **unreliable `0x400d2d54` jump table**
   (KB already flagged the "physical-key" labels as unconfirmed). Disasm:
   - `0x4000a274`: `bras 0x4000a2ca` → builds a 3-byte MIDI message, `jmp 0x40010bc8`
     (serial TX). It is a **MIDI-note/CC out helper**, not grid-rec.
   - `call_as_main(0x40060ce0,(4,1))` returns `d0=0x11`, sets `[0x8000003f+1]=1`
     and a held-list byte at `0x46c76de0+4`, but leaves the p-lock editor gates
     `0x460d172e` / `0x460d174a` / `0x460d174c` **all 0**, and `(4,0)` release does
     **not** clear the held state. Wrong / incomplete handler.

3. **`--applyknob 3 90`** — poked the gates by hand (`0x460d172e=1`,
   `0x460d174a=1<<4`, `0x460d174c=0`, `0x800000cc=1`) then
   `call_as_main(0x4004eb54, (3, -1, 90))`: **runs away in the scheduler**
   (`pc 0x40000560`, ~111k writes to the TCB save area) without reaching its
   store. The sub's guard chain (`jsr 0x4002ea84` → `0x4002ea2c` does MIDI /
   `0x4007e81c` work) or its redraw tail can't complete in borrowed-main context
   (same class as Session 25's "the full `0x4004eb24` hangs — it redraws").

### What the static RE established (confidence C, disassembled)

**`0x100b14d0` = current PATTERN byte** (`mvzb` → `0x0a` = DISK_PAT). `0x100b14cc`
= current track (octakit `GK_STOCK_CURRENT_*_PRIMARY` = `0x100b14cc`=track,
`…cf`=?, `…d0`=pattern).

**p-lock editor gate state** (all in the `0x460d17xx` UI-scratch page):
| addr | role |
|---|---|
| `0x460d172e` | **armed** flag (`!= 0` ⇒ a p-lock edit is in progress). Reader `0x40033970` (returns it in d0). |
| `0x460d174a` | **16-bit held-step bitmap** (bit p ⇒ step = `0x460d174c + p`). |
| `0x460d174c` | held-step **base** (long; cleared when `0x460d174a` goes to 0). |
| `0x460d1746` | pointer/offset for the currently-held step's record, **stride 0x10 per step** (`a5 = step<<4 + base`, set at `0x40050bd0`). |
| `0x46c7d2e4` | per-step `|= 1<<param` **locked bitmap** the knob sub maintains. |

**The real grid-rec trig handler = the cluster `0x4005f260 .. 0x4006071a`.**
- press path `0x40050bac`: `0x460d174a |= 1<<d3` (d3 = trig index), sets
  `0x460d1746`, then at `0x40050c0c` / `0x4005127a` sets `0x460d172e = 1`
  (`0x80000012` = MIDI-mode split: audio path vs MIDI path).
- release path near `0x4005f7a0`: `0x460d174a &= ~(1<<d7)`; if it hits 0,
  `clr.l 0x460d174c`; then `0x4005f7f2` / `0x4005fd96` `clr.l 0x460d172e`.
- both paths touch the blob (`0x46c82456`) via a **PART-payload / working view**
  at pattern offsets `0x2470` (16-bit mask array, `track*0x458`),
  `0x2880` (`+[0x460d1746]`), stride `0x476c` (18284) per pattern — **NOT** the
  `pat*0x8ed8` pattern-record view that holds #1.

**The knob → p-lock writer family = `0x4004d??? .. 0x4004f4??`** (reads
`0x460d174a`, writes the blob). `0x4004eb54` = "apply value to every held step":
`[0x46c82456] + pattern*0x8ed8 + 0x4900 + step*0x20 + param*0x8b0` (bytes `+2`,`+3`),
gated on `0x800000cc` (EXT LEN GRID-REC PERSONALIZE) **and** slot currently `0xFF`,
maintains `0x46c7d2e4[step] |= 1<<param`. Siblings at `0x4004ed24`, `0x4004f2xx`
read `+0x4900`/`+0x4903`/`+0x4904` (multi-byte per slot).

**Key open contradiction**: `0x4900 + step*0x20 + param*0x8b0` is **pattern-global
and param-major**; #1 (proved `== disk` by `--confirm`) is **per-track**
(`trk*0x91a + 0x59`, 32 B/step). They do not alias. So either (a) `0x4004eb54` is
the MIDI-track knob path (MIDI tracks don't have TRAC p-locks the same way), or
(b) there is a param-major working cache at `+0x4900` that a commit/serialise step
repacks into the per-track TRAC arrays. `--confirm` only proves #1's *final*
state matches disk — it doesn't prove #1 is what the editor writes live.

### NEXT (Session 27)

1. **Fix the handler addresses.** Decode the grid-rec REC-key + trig-key entries
   from the **26-byte keymap** (T1 `0x400bfc10`, T2 `0x400c01f4`; `{u8 code,0,
   press:u32, release:u32, h3:u32, aux:u32, 0, u16 flags}`) — trig code `0x00-0x0f`
   should point into `0x4005f260..`. Also find the byte that means "GRID REC mode
   active" (not `0x800066a0` — that's audio-recorder arm).
2. Then in `emu_plock.py`: drive the **real** grid-rec trig press
   (`call_as_main(<real trig handler>, (kc, 1))`), confirm `0x460d172e` /
   `0x460d174a` arm, `watch_mem` the **whole pattern block** + `0x46c7d2e4`, turn
   the knob via the smallest inner write sub, and read off the writer PC + offset.
   Compare the offset to #1 (`trk*0x91a + 0x59 + step*0x20`).
3. `[NO]`-held erase sibling: same family, params `0x34-0x36`
   (`0x4005e164/e1a8/e1d2`) per Session 25 — but that was the MIDI-CC path; the
   audio erase is likely in `0x4004f2xx` or the `0x4005f2xx` cluster's
   `andl`-with-mask stores (e.g. `0x4005fd58` `movew %d3,%a0@(…)` with d3 masked).
4. If `+0x4900` turns out to be a working cache, find the repack (serialise) step
   — likely in the `SAVE` / `CHANGE PATTERN` flow (`0x400a0???` sequencer, or the
   `0x40025???` project serialiser that already shows `pat*0x8ed8` + `trk*0x91a`).

## Session 27 (2026-09-06, `wip/mute-mode`) — the 0x400 objdump error; knob → p-lock writer LOCATED

### ⚠️ Every fresh fn address in "Session 26" was 0x400 low

`emu_bringup` loads the image at **vaddr `0x40000400`** (`BASE = ENTRY = 0x40000400`,
"load base = 0x40000000 + 0x400 header"). Session 26's objdump used
`--adjust-vma=0x40000000`, so every function address it derived is 0x400 short of
the real one, and the bytes it disassembled at a given "vaddr" were the *previous*
0x400 bytes. **Correct: `m68k-elf-objdump -b binary -m m68k:5407
--adjust-vma=0x40000400`.** (RAM addresses `0x46xxxxxx` / `0x8000xxxx` and code
*immediates* like `0x8ed8` / `0x4900` / `0x8b0` were read correctly — they don't
shift. Only PC-space labels moved.) The KB's existing addresses (from earlier
sessions) are fine; only Session 26's are off.

Proof: emu memory at `0x40060ce0` = `22 2f 00 04 20 2f 00 08 4a b9 46 0d 17 36 …`
(`move.l (4,sp),d1; move.l (8,sp),d0; tst.l 0x460d1736`) — the real
`handler(keycode@4, event@8)`. The `2f 02 48 78 …` Session 26 disassembled there
lives at file offset `0x60ce0` = **vaddr `0x400610e0`**.

### The real grid-rec trig chain (corrected)

- keymap: trig keys are **keycodes `0x01..0x10`**, 26-byte records at `0x400bf9d8`
  (`{press:u32, release:u32, hold:u32, 0, 0, u16 h3=0x10, u16, u8 keycode, u8 0}`),
  all three edges → `0x40060ce0`.
- `0x40060ce0(keycode@4, event@8)`: if `0x460d1736 != 0` → `0x40060b58` (alt);
  else → `0x400501d8` (dispatches on `0x460d16f0` 0..5) **and** the grid-rec trig
  dispatcher `0x40060bXX` which routes on event: **1 (press) → `0x40050f20`**,
  2 (hold) → `0x400587d4`, 0 (release) → `0x4005fb44` then `0x4003146c`.
  Bails for PICKUP-machine tracks (`blob+part*6322+track+0x8eda2 == 4` && `!midi`
  && `0x460d5db4==0`).
- **`0x40050f20(step@4, 1@8)`** — the arming fn. `call_as_main` runs it CLEAN
  (d0=0x11). Sets, for the held step:
  `0x460d172e = 1` (armed, audio path `0x4005100c`) · `0x460d174a |= 1<<step`
  (u16 held bitmap, `0x40050fb8`) · `0x460d174c = basestep<<4` (u16,
  `basestep = [0x460d1e04]`) · `0x460d1746 = basestep<<4 + step`.
  Gate to reach the held-bit set: `0x460d5db4 ∈ {0, 3}` (0 at rest).

### The knob → p-lock writer — LOCATED (`0x4004ef54`)

Session 26's "`0x4004eb54`" corrected = **`0x4004ef54(param@d7, matchval@fp, newval@a2)`**
("apply value to every held step"). Drove it in `emu_plock.py --watch --trig 4
--applyknob 3 90` after arming via `0x40050f20`, `0x800000cc` forced to 1. It
wrote **exactly two things**:

| PC | target | value |
|---|---|---|
| `0x4004f062` | `blob + pat*0x8ed8 + 0x4900 + step*0x20 + param*0x8b0 + 2` | 90 (the new value) |
| `0x4004f09e` | `0x46c7d2e4[step] \|= 1<<param` | bit 3 (step 4 → `+4` = 8) |

`param 3, step 4` → offset `0x4900 + 4*0x20 + 3*0x8b0 + 2 = 0x6392` ✓ (matches the
captured write `pat-blk + 0x6392`). **Nothing** to #1 (`TRAC+0x59`), #2
(`0x46c7ab30`), or the `0x1001aa50` mirror.

### `+0x4900` is a transient live-edit buffer, not the store

`emu_plock.py --s27` reads `blob + 10*0x8ed8 + 0x4900 + …` for the saved DEMO
pattern → **all `0xFF`**, while #1 (`TRAC+0x59`) holds every DEMO lock (step
0/2/4/6/8 at rec-offset `0x12`, steps 10/12/14 at `0x0`/`0x13`), and `0x46c7d2e4`
is all zero. So: **live p-lock edits land in the param-major `+0x4900` buffer +
the `0x46c7d2e4` per-step bitmap; a serialise repacks `+0x4900` → per-track TRAC
`+0x62` (#1) on save / pattern-change; load goes TRAC → #2 working set (not
`+0x4900`).**

Other `+0x4900` writers (byte stores `11 4N 49 0x`): value `0x4004f062`; the
`+0x4900` companion slots `0x4004f2a4` / `0x4004f3ac` / `0x4004f4d4` / `0x4004f830`;
grid-rec `0x400505f4` / `0x40050b98`; **release `0x4005fdc6`**.

## Session 28 (2026-09-06, `wip/mute-mode`) — the p-lock op dispatcher + the LED-bitmap rebuild

### `0x4004ef54`'s arg0 = TRACK, not param

The real caller `0x40062a82` passes `0x4004ef54(track = [0x80000000], a2@2, a2@8)`.
Inside, `d7 = arg0`, and `d5 = 0x8b0 * d7`, `a4 = 1<<d7`, bitmap
`0x46c7d2e4[step] |= 1<<d7`. So **`d7` is the track** (0–7). `--applyknob 3 90`
passed `3` and got a write at `3*0x8b0` because it doesn't matter *what* d7 is —
it's the stride. Corrected: `+0x4900` is **per-track** (`track*0x8b0`, step
`*0x20`), and `0x46c7d2e4[step]` bit = **which track** has a live lock on that
step. The 32-B step record's bytes `+0`,`+2`,`+3`,`+4`,`+5` are the **5 encoders**
of the current param page (`0x4004ef54` writes `+2`; sibling `0x4004f124` `st`s
`0xFF` into `+0`/`+3`/`+4`/`+5`).

### The p-lock knob op dispatcher (`~0x40062a00`)

A message handler; the event struct is in `a2` (`a2@0` = opcode, `a2@2` param /
matchval, `a2@3`, `a2@4`, `a2@8` value/ptr). Each opcode: **if `0x460d172e != 0`
(armed)** → a p-lock op; **elif `0x460d172a != 0`** → a non-armed sibling:

| armed op | from | non-armed sibling |
|---|---|---|
| `0x4004f124(track, a2@2, a2@3)` — **eraser** (`st`→`0xFF` into `+0`/`+3`/`+4`/`+5`) | `0x40062a1c` | `0x40041bc4` |
| `0x4004ef54(track, a2@2, a2@8)` — **writer** (`+2` value) | `0x40062a82` | `0x40041784` |
| `0x4004f5f8(track, a2@2, a2@3, a2+8)` — third op | `0x40062afc` | — |

`0x460d172a` = a second armed-ish flag (companion to `0x460d172e`).

### `0x400339d8` — rebuilds the "step has a lock" bitmaps

Zeroes `0x46c7d2e4[0..63]` and `0x46c7d48c[0..63]`, then for every track 0–7 ×
step 0–63 × byte 0–31:
- if the **live `+0x4900`** record byte `!= 0xFF` → `0x46c7d2e4[step] |= 1<<track`
- if the **stored** record byte (`blob + pat*0x8ed8 + track*0x91a + step*0x20 +
  59`) `!= 0xFF` → `0x46c7d48c[step] |= 1<<track`

So **`0x46c7d2e4` = live-edit lock presence, `0x46c7d48c` = stored lock presence**,
both `byte[step]` = track bitmap. These are the UI "does this step have a p-lock"
indicators (LED / trig display). `0x400339d8` is the natural **detour anchor** for
the auto-remove feature (it runs after edits to refresh the display).

### Encoder `0x4004eb24` is the PART-param editor, not p-locks

`0x4004eb24(desc@20, delta@24)`: audio path reads/writes `blob + part*3161 +
track + 0x476c9` (the Part-data value), `[blob+0x95048] |= 1<<part`. Gated on
`0x8000004a` bit 0. Not the p-lock path.

### Encoder disp printing — `objdump` quirk

`m68k-elf-objdump` prints a **brief-format** `lea (d8,An,Xn)` displacement as its
raw hex value with **no `0x`** (e.g. `lea %a0@(58,%d3:l)` = disp `0x58` = 89, not
decimal 58), while a 16-bit `(d16,An)` disp prints signed decimal (`sp@(-44)`).
The `0x400339d8` "TRAC + 59" scare in Session 28's plan was this: `lea (0x58,...)`
then `lea (1,a3,a0)` = `+0x59` = **exactly #1**. No offset discrepancy.

## Session 29 (2026-09-06, `wip/mute-mode`) — `0x400339d8` = the lock-bitmap rebuild, RECONCILED

`emu_plock.py --s27` rewritten: dumps #1 / `+0x4900` / the TRAC masks / both lock
bitmaps, then `call_as_main(0x400339d8)` with a write hook on
`0x46c7d48c`/`0x46c7d2e4`.

**`0x400339d8` reads #1 at `TRAC + 0x59`** (brief-disp `0x58` + 1) — confirmed by
matching `emu_plock`'s independent read. It runs clean under `call_as_main`
(64+64 clear writes at `0x400339f0`/`f4`, then `0x40033a38` sets
`0x46c7d48c[step] |= 1<<track` for every non-`0xFF` stored record;
`0x40033a4c` does the same into `0x46c7d2e4` from the live `+0x4900` buffer).

**The scare** (`0x400339d8` first lit `{0,16,32,48}` not `{0,2,4,6,8,10,12,14}`):
the harness's `rt.run(until=MAIN_SPIN)` before the call lets `sys` apply the
engine reset's "select pattern 0", so `[0x100b14d0]` drifted `0xa → 0` and the
rebuild read **pattern 0**. Re-asserting `[0x100b14d0] = DISK_PAT` right before
the call → `0x46c7d48c` bit 1 lights exactly `{0,2,4,6,8,10,12,14}` = #1's
locked steps. (`--s27` now does this re-assert.)

**So `0x46c7d48c[step] = per-step bitmap of which tracks have a STORED p-lock**
(`0x46c7d2e4[step]` = same for LIVE `+0x4900` edits). E.g. DEMO P11:
`0x46c7d48c[0] = 0x13` (tracks 0,1,4), `[4] = 0x43` (0,1,6). **This is the detour
anchor** for the trigless-lock auto-remove.

## Session 30 (2026-09-06, `wip/mute-mode`) — the LIVE-REC gesture handler, and the multi-view p-lock reality

Re-read Session 13's brief: the feature's gesture is **LIVE REC `[NO]`+knob**
(the "clear as the playhead passes" live erase), NOT grid rec. That path is the
`0x460d172a != 0` (LIVE-REC edit active) branch of the `~0x40062a00` dispatcher:
`0x40041784(track,a2@2,a2@4,a2@8)` = LIVE write, **`0x40041bc4(track,a2@2,a2@3,
a2@4)` = LIVE write/erase** (grid-rec's `0x4004ef54`/`0x4004f124` are the
`0x460d172e`-armed siblings).

### `0x40041bc4` — the LIVE-REC p-lock write/erase (the feature's hook target)

`linkw fp,#-64`. Gate `0x460d172a != 0` && `0x460d1a90 == 0`. Decodes
(track,param,…) via `0x4009b290` / `0x4009b2d4` → `d6`=bank `d5`=pattern
`d4`=param-ish. It updates p-lock state across **several parallel views**, all
keyed `blob(0x400e21e0) + bank*0x9b340 + pattern*0x8ed8 + track*{stride} + off`:

| view | off | track stride | shape |
|---|---|---|---|
| `+0x48d8` param bitmap | `0x48d8` / `0x48e0` | `0x8b0` | 2×u32 "which params locked" + `0x1001aa26`/`aa2e` mirrors |
| `+0x4900` value records | `0x4900` | `0x8b0` | bytes `+0/+1/+3/+4/+5` `st`'d to `0xFF` on erase, written on write; `0x1001aa4e` mirror |
| `+0x2880` PART-payload | `0x2880` | `0x458` (pat `0x476c`, bank `0x4d9a0`) | `& 0x1f` / `& 0x80` byte pair + a 6-bit field at bits 7-12 of a u16 + `0x1001614e` mirror |
| `0x46c7d2e4[step]` | — | — | `\|= 1<<track` (marks the step live-touched) |

Plus dirty flags `[0x4017d512+…] = 1` and `[0x100f8598] = 1`.

**It does NOT check "lock count → 0" and does NOT touch any trig-type / trig mask.**
So the emptied trigless lock persists — exactly Session 13's complaint. The
detour must add that check + the trig-type clear.

### The step handler reads `TRAC + 0x0a`, not just #1

`0x4009d740`+ (per-param loop `0x4009d7dc`, 32×): consults a 64-bit param bitmap
at `blob + pat*0x8ed8 + track*0x91a + 0x0a` (`a3@(10,d0)` + `@(0x0e)`) AND the
`#1` value records at `TRAC + 0x59` (`sp@(92)`/`sp@(96)` ptrs). So `TRAC + 0x0a`
(8 bytes, param-indexed) = "which params are locked" for playback; `#1` = the
values.

### Reality check — this is bigger than the Session 13 estimate

p-lock data now has **≥5 live representations** (`#1` TRAC+0x59 values ·
TRAC+0x0a param bitmap · +0x48d8 param bitmap · +0x4900 value records ·
+0x2880 PART-payload · +0x2470 16-bit view · the #2/#3/#4 working sets) and the
serialize/deserialize graph between them is not mapped. The **trig-type flag**
Session 13 needs is still not located — `0x40041bc4` doesn't write it, so a
separate "place trigless lock" path sets it. **The "predicate is the whole
ballgame" risk is real.**

## Session 31 (2026-09-06, `wip/mute-mode`) — a trigless lock is DERIVED, not flagged

`emu_plock.py --trigless`: copies the DEMO, clears **P11 t2 step 4's note-trig
bit** on disk (`bank01.work` off `+0x59e88`: `0x55 → 0x45`) while leaving its
p-lock (`#1[4][0x12] = 0x14`) — then loads it and dumps every view for step 4
(trigless) vs step 0 (note + lock).

Result — **step 4 is now a trigless lock, and it is created by NOTHING but the
absence of a note bit**:
- `TRAC + 0x00` note mask: step 4 gone (`{0,2,6,8,10,12,14}`).
- `#1[4]` unchanged: `[0x12] = 0x14`.
- **`0x46c7d48c[4] = 0x43`** (bit 1 set) — byte-identical to the un-patched
  note+lock case. So `0x400339d8`'s rebuild (→ the dim-lock LED) lights step 4
  the same either way: **the LED is driven purely by `#1[step]` being non-`0xFF`,
  and does not care about the note bit.**
- `TRAC + 0x08 / 0x10 / 0x18 / 0x0a` masks and `+0x48d8` / `+0x4900`: all **empty
  at load**. So there is **no separate "trig-type flag" for a pure p-lock
  trigless lock** — it is exactly `#1[step] != 0xFF && TRAC+0x00 bit clear`.

**Revised model** (consistent with everything):
- `#1` (`TRAC + 0x59`, param-indexed value records) = **the store**, filled by
  the deserialiser on load. `TRAC + 0x0a` param bitmap and `+0x48d8` / `+0x4900`
  are **runtime/working views, empty until an edit populates them lazily**.
- The dim-lock LED = `0x46c7d48c[step]` bit `track`, rebuilt by `0x400339d8`
  from `#1[step]` non-`0xFF`.
- `0x40041bc4` (LIVE `[NO]`+knob erase) clears the working views (`+0x48d8`,
  `+0x4900`, `+0x2880`) but **NOT `#1`** → the emptied lock survives in `#1`,
  the LED stays lit, and it re-serialises on save. **That is Session 13's
  complaint, fully explained.**

### The detour (Option B — designable now)

Hook `0x40041bc4`'s exit. When the call was an **erase** that took the working
param-bitmap for `(track, step)` to **0** (i.e. `+0x48d8`/`+0x48e0` both 0 for
that track+step) AND the step is a **pure trigless lock**
(`TRAC+0x00`[step] bit clear, and `TRAC+0x08/0x10/0x18`[step] bits clear — no
note / recorder / other trig) → **clear `#1[track][step]`** (write `0xFF` to its
32 bytes) and let `0x400339d8` refresh (LED off, step inert, save writes empty).

Still needed for the build (Session 32):
1. **`0x40041bc4`'s step/track/param decode** — it calls `0x4009b290` /
   `0x4009b2d4` and reads tables `0x46c7d4cc/d4cd`; pin which locals hold
   `track` (`fp@8`), `step`, `param`, and the erase-vs-write discriminator.
2. **The `+0x4900` → `#1` serialise** (still unlocated) — needed to confirm
   "clear `#1` + mark dirty" is enough, or whether the working view must be
   cleared too (it already is, by `0x40041bc4` itself).
3. The predicate's conservatism: exclude sample-slot locks, LFO/FX locks on
   other pages, trig conditions — check whether those live in `#1`'s 32 bytes or
   a separate per-page record (`0x40041784` writes `+0x4902` for *one* page; the
   OT locks span several pages → `#1` is likely per-(page) not global).

## Session 32 (2026-09-06, `wip/mute-mode`) — detour core action VALIDATED; decoder + lazy-load mapped

### The detour's core action works (`emu_plock.py --trigless`, extended)

On the trigless-lock test bank (P11 t2 step 4 = p-lock, no note): wrote
`#1 t1 step 4 = 32×0xFF` by hand, re-asserted the pattern, called `0x400339d8`:
`0x46c7d48c[4]` went **`0x43 → 0x41`** — bit 1 (track 1) **cleared**, bits 0/6
(other tracks) preserved, step 0 unchanged. **So: clear `#1[track][step]` +
`0x400339d8` = the dim-lock LED goes off, cleanly, no collateral.** And `#1` is
what the step handler reads for playback and what serialises → the fix sticks.

### `0x400339d8` (the rebuild) callers

`0x40029bbc`, `0x4003ebf2`, `0x40040f70`, **`0x40041744`** (right before the LIVE
writer `0x40041784`), `0x4004c912`, `0x4005063e`, `0x40050876`, `0x40061bbc`,
`0x40062160`, `0x4006242e`, `0x4007351c`, `0x40073806`. The erase path
(`0x40062a4e → 0x40041bc4`) does **not** call it directly — it calls `0x40045614`
then redraws. So the detour must call `0x400339d8` itself (or the `#1` write +
a redraw is enough — TBD).

### `0x40043c7e` = the `#1` → RAM working-copy lazy-load

`lea (0x58, a0, d5:l); lea (1, a2, a0:l)` → walks `#1[step][0..31]`, copies each
non-`0xFF` byte to **`0x46c7dfda + page*32`** (a 4th working array, distinct from
`#2` `0x46c7ab30` / `+0x4900` / `+0x48d8`). Gated on `0x400a6904` (param
locked?) + `a4 != 0`. So the editor lazily materialises a step's `#1` record into
`0x46c7dfda` when you land on it.

### `0x4009b2d4` = the param-address resolver (not a step decoder)

Maps `(param-page, param-index)` → a byte offset across the blobs, via tables
`0x46c7756c/759c/75bc/75ce/757c`, `0x400aba50`, `0x400eb034`, `0x400e2230`,
`0x400e6ad8` and constants `0xd728` / `0x285f00` / `0x1ae50`. It does **not**
carry the step — the LIVE-erase step is the **sequencer playhead position** for
the track (still to be located; the step handler `0x4009d1e8` indexes it).

### `+0x4900` stride puzzle (unresolved)

`0x4004ef54` (grid) addresses `+0x4900 + param*0x8b0 + step*0x20 + 2`;
`0x40041bc4` (LIVE) addresses `+0x4900 + track*0x8b0 + param*0x20 + {0,3,4,5}`.
The `0x8b0` stride is on **param** for one and **track** for the other, and the
`0x20` stride is **step** vs **param**. One reading is wrong; the LIVE one
(`track*0x8b0`, from the caller pushing `[0x80000000]` = track as arg0) is more
likely right. Doesn't block the detour (which targets `#1`, not `+0x4900`).

### NEXT (Session 33) — the build

1. Locate the **per-track playhead step** global (from `0x4009d1e8`).
2. Pin `0x40041bc4`'s erased-**param index** (the `fp@(-2)` / `a3` local; maps to
   `#1`'s 0–31 index).
3. Detour design: hook `0x40041bc4` exit (detour its `jsr` at `0x40062a4e`) →
   `param = <decoded>; step = playhead[curtrack]; if TRAC+0x00/08/10/18[step]
   bits all clear (pure trigless) { #1[curtrack][step][param] = 0xFF; if
   #1[curtrack][step] now all-0xFF: (nothing — rebuild handles it) } ; call
   0x400339d8`. This does the per-param `#1` clear the firmware skips → multi-pass
   falls out naturally.
4. Build `tools/patch_triglock.s` + `tools/build_triglock.py` → `140C_KYOTI`,
   cave in `0x400d7400`+, EFT round-trip, `emu_plock` regression.

## Session 33 (2026-09-07, `wip/mute-mode`) — the `0x4009b2d4` decode; and the wall

### `0x4009b2d4` — what it returns

Writes **4 output bytes** at `(a3)` (= `&fp@-4` for the LIVE handlers):
`(a3)@0 = d2` (blob/bank selector, `0x46c7759c`/`758c`/`755c`[track+8]),
`(a3)@1 = d1` (pattern selector, `0x46c775bc`/`75ac`[track+8]),
`(a3)@2 = d5` (param-page descriptor, `0x46c7754c`/`753c`/`755c`[track+8]),
`(a3)@3 = d3` (a `remul`-derived sub-index 0–23).
Internally `d5 = [0x46c775ce] − a2@4` is the **step** (`0x46c775ce` = an
edit/playhead step base, written by `0x4009c3e0` + the `0x400a2xxx` display code),
but the step is folded into a huge linear address (`×0xd728`, `×0x285f00`,
`×0x1ae50`) and only survives as the mod-result `(a3)@3` — **not** returned as a
clean `#1` step index.

So `0x40041bc4` gets `(bank, pattern, param-descriptor)` from the decode and
`(a3)@3` as a 6-bit field; the step it operates on is implicit.

### The wall: `+0x4900` ↔ `#1` has no bridge in the paths seen

- `0x400e6ae0` (= `blob + 0x4900`) is referenced **only** by `0x40041f02` /
  `0x40041f72` / `0x40042546` / `0x40042642` — all inside the LIVE
  write/erase cluster. The sequencer (`0x4009xxxx`) never reads it.
- The LIVE cluster writes `+0x4900`, `+0x48d8`, `+0x2880`, `0x46c7d2e4`, the
  `0x1001aaXX` mirrors, and dirty flags — **never `#1` (`TRAC+0x59`)**.
- `#1` is filled by the deserialiser on load; `+0x4900` is left empty
  (`--trigless` / `--s27`).
- The step handler `0x4009d1e8` reads `#1` + `TRAC+0x0a`; it does **not** read
  `+0x4900` or the armed-param bitmap `0x46c7d344/d348`.

**So how a LIVE `[NO]`+knob edit reaches playback / disk is still unaccounted
for.** Candidates for the missing `+0x4900` → `#1` merge: the SAVE serialiser
(`0x400645ce` / `0x40025xxx`), a pattern-change / STOP commit, or a per-frame
apply reading `+0x48d8`/`+0x2880` (not `+0x4900`) that I have not traced.

### Honest status

8 sessions in (26–33). Model + the detour's core action (`clear #1[t][step]` +
`0x400339d8` → LED off) are **solid**. But the hook needs a clean `(track, step,
param)` and the `+0x4900` ↔ `#1` relationship, and both are proving deep — the
decode returns no clean step, and the working-view → store merge is unlocated.
This is materially past the Session-13 "3–5 session" estimate. **Decision point
for the user**: keep drilling (find the merge — likely 2–3 more sessions), or
bank the (substantial) subsystem RE and move to another item.

### NEXT (Session 34, if continuing)

1. Trace the SAVE path (`0x400645ce`) and a pattern-change commit for a read of
   `+0x4900` / `+0x48d8` / `+0x2880` that writes `#1` or the disk `TRAC` block.
2. OR drive the full LIVE gesture in `emu_plock` (transport running + REC + poke
   `0x460d172a`) and watch `#1` across several frames — see empirically when/if
   a live edit reaches `#1`.

## Session 34 (2026-09-07, `wip/mute-mode`) — the LIVE-erase drive: not tractable headless

`emu_plock.py --s34`: loads the trigless bank, pokes the LIVE gates
(`0x460d172a = 1`, `0x460d1a90 = 0`, `0x46c775ce = 4`) + the per-track gate
`[0x80006508 + trk] = 1` (`0x4009b290(track+8)` must return 1), then calls
`0x40041bc4` and watches `#1` / `+0x4900` / `+0x48d8` / the armed bitmap.

**With the gate poked, `0x40041bc4` runs (`d0 = 0x1ff`) but writes only:**
- `0x40041f70` → `0x46c7d344 |= <bit>` (arm a param)
- `0x4004210e` → `0x46c7d2e4[a3] |= 1<<track`, with **`a3 = 0`**

**No write to `#1`, `+0x4900`, or `+0x48d8`.** And `a3 = 0`, not step 4 —
`0x40041bc4`'s working index is the `remul` sub-index out of `0x4009b2d4`
(0–23), which collapses to 0 because the decode's inputs
(`0x46c775bc[track+8]` = per-track pattern, `0x46c7759c[track+8]` = blob
selector, the param cursor `0x800064e8+trk`) are all **0 / unset** in a headless
boot. `0x100b14d0` (cur-pat) also drifts to 0; poking it doesn't help because
the LIVE decode uses the per-track tables, not `0x100b14d0`.

**Conclusion**: the LIVE `[NO]`+knob path is too UI/sequencer-state-dependent to
drive synthetically without reconstructing the per-track pattern/blob tables, the
param-page cursor, the playhead, and the record state — and even the partial run
shows `#1` is never touched by `0x40041bc4`. The `+0x4900` (and the other working
views) → `#1`/disk merge is **not** on the edit path; it must be on **SAVE** (or
a STOP / pattern-exit commit).

### Real status / decision (unchanged direction, firmer)

The trigless-lock feature needs the `+0x4900` → `#1` merge, and that lives in the
serialiser. Options, in order of likely payoff:
1. **HW export-and-diff** — Session 13's original Phase 0. Build the targeted
   test patterns on the MKI, export, diff the banks. This is the intended method
   and sidesteps all the emu state problems. **Blocked on the MKI being back.**
2. **Trace `0x400645ce` (SAVE PROJECT) + `0x40025xxx` (bank serialise)** for a
   `+0x4900`/`+0x48d8` read that feeds `#1`/`TRAC`. ~2–3 sessions, emu-only.
3. **Shelve** — 9 sessions of subsystem RE banked in `kb/file-format.md`; the
   remaining gap is one well-defined merge in the save path.

The detour's **core action stays validated** (S32): whenever we can identify a
pure trigless lock that just lost its last lock, `#1[t][step] = 0xFF` +
`0x400339d8` cleans it with zero collateral.

## Session 36 (2026-09-07, `wip/mute-mode`) — side-chain STEP 3 DSP: KEY GAIN + KEY FLT (2-pole SVF) + SC LISTEN

No-flash to-do board item 3. Steps 1–2 (Session 17) put `KEY` on the COMPRESSOR
page and wired `keybus` + the detector redirect; step 3 makes the other three
page-2 controls do their DSP work. **Built + emu-clean (isolation *and* end-to-end
against the built image), NOT flashed** — the whole side-chain stack is still
HW-gated on flashing `SIDECHAIN2` first.

### What ships

`tools/patch_sc_dsp3.asm` — a **superset of `patch_sc_dsp.asm`**: ~182 words of
code + a 16-word gain table + a 32-word f table = **230 / the SPATIALIZER donor's
261** (31 to spare). The build appends the two tables to the assembled cave, so
the `230` it reports already includes them.

Three hooks now (was two):
- `sctap`  — unchanged publish tap (dispatcher FX1 entry).
- `scdet`  — detector redirect **+ KEY GAIN + KEY FLT**. After staging
  `keybus[key]` into `X:$40`:
    * **KEY GAIN** (`x:(r6+$e)` bits 16-23, 64 = unity): index a 16-word table
      (`KGAIN>>3`) of `gain/64` in Q23, `mpy ; asl #6` per sample. ~±24 dB,
      ~3 dB/step. `tools/sc_tables.py::gain_table()`.
    * **KEY FLT** (`x:(r6+$d)` bits 8-15, 64 = bypass, <64 LP, >64 HP): one
      Chamberlin state-variable filter, **damping q = 1** (so the `-bp` term
      needs no multiply), coefficient `f = 2·sin(π·fc/fs)` from a 32-word
      exp-spaced table (fc 40 Hz … 2.2 kHz). LP idx = `KFLT>>1`, HP idx =
      `(KFLT-64)>>1`. State (lp, bp) in the compressor's own `r7+$16 / r7+$17`
      (RE: unused by the stock module); warm-start gated on `r7+$f` bit 0 (the
      stock first-block flag) so **no init hook is needed**. Input is `(L+R)/2`,
      output written to both L and R slots. One shared loop; `n0` marks LP vs HP
      for the per-sample output select.
- `sctail` — **NEW** third hook, `jsr` spliced over the COMPRESSOR's proc-end
  `move m0,x:(r7+$f)` (`P:0x1b55` A / `P:0x1915` B). When **SC LISTEN** (`MON`,
  `x:(r6+$e)` bits 8-15) is ON and a KEY is set, overwrite the wet output (the
  `n6` buffer) with the processed key stashed by `scdet` at `keybus[key]` gen 1
  (`+$20`). "Listen to exactly what's driving the detector."

`tools/sc_tables.py` — the two tables, shared by the build and the emu so they
can't drift. `tools/build_sidechain3.py` — reworked from menu-only to
**`build_sidechain2` + the 3 extra descriptor slots + `patch_sc_dsp3` + the
`sctail` splice**; `@GTAB@`/`@FTAB@` resolved in a first sizing pass; asserts the
cave ≤ 261 and round-trips it (rejects `mpysu`/`macsu`).
Output `out/OCTATRACK_OS1.40C_SIDECHAIN3.{syx,bin}` (`140C_KYOTI`, 1585 B vs
stock). Both payloads parse 100% (`dsp_modmap`, module counts identical to stock);
manual-trig fix byte-identical; formatters (`emu_sidechain.py`) pass.

### dsp56kEmu / DSP quirks found the hard way (all fixes are HW-correct too)

1. **`move x:(rN+$disp),a`** (2-word displacement form, **dest a**) reads the
   *wrong* word under dsp56kEmu — `scdet`'s `move x:(r6+$d),a` came back with the
   `KGAIN|MON` word instead of `KEY|KFLT`. **Dest `b` is fine.** Every param read
   in the cave now goes to `b`, then `move b1,a`.
2. **`move #imm,x0`** (short form, into a data ALU reg) is **left-aligned** —
   `move #$40,x0` gives `x0 = 0x400000`, not `0x40`, so `cmp x0,a` never matched.
   Use **`cmp #>$40,acc`** (right-aligns).
3. **`asr #n,acc,acc`** for field extraction leaves the shifted-out bits in
   `acc0`, and `tst` / `cmp` see the **full 56-bit accumulator** (real 56k
   behaviour — stock code always follows with `move acc1,Rn`, never `tst`).
   Normalise with **`move acc1,otheracc`** before any `tst`/`cmp`.

`tools/emu_sc_dsp3.py` — isolation harness (each hook run as its own `-proc`,
seeded `.mem`, read back) checked **numerically against a Python SVF reference**:
KEY copy / KEY=0 no-op / KEY GAIN ×5 levels / KEY FLT LP+HP (≤1 LSB) / SVF state
persistence across blocks / SC LISTEN stash — **ALL GOOD**. `--patched` rebuilds
payload B's `.mem` from `out/mainos_sidechain3.bin` (octabam's `dsp_modmap` only
dumps the stock image, so its `dumpmem` is replicated inline) and reruns every
test against the **real** cave over the real SPATIALIZER donor with the live
`jsr` detours — **ALL GOOD**. Also seeds `x:0x20c = 15` because dsp_host's
context routine can't run headless (empty RX read) → `n7` stays 0 → `do n7`
loops never execute.

### Still HW-only (unchanged from step 2, plus step-3 items)

- the compressor's gain reduction actually *tracking* the keybus signal
  (`dsp_host` can't run the stock COMPRESSOR end to end);
- `r7+$16/$17` genuinely free for our SVF state on the real module (RE says yes;
  worst case the first-block-zero gate hides a stale value for one block);
- musical calibration: gain law (±24 dB / ~3 dB steps), filter range
  (40 Hz–2.2 kHz), and whether q = 1 (Butterworth, no resonance) is the right
  character — all easy table edits in `sc_tables.py` after a listen;
- `sctail`'s `n6` still points at the dry/wet buffer at proc-end (RE: yes — the
  compressor re-anchors `move n6,r0` at stages 4 and 6 and doesn't touch n6
  after; `sctail` only reads it).

### HW test additions (append to "Session 17 continued (8)")

7. **KFLT**: `COMPRESSOR` on a pad, `KEY = T1` (kick). Turn `KFLT` left → the
   ducking should follow only the kick's low thump (hats/snare stop triggering
   it); centre = same as before; right → only high content ducks.
8. **KGAIN**: with a quiet key, turn `KGAIN` up → deeper ducking; the bipolar
   readout should roughly match the audible change.
9. **SC LISTEN = ON**: the compressor's output should be replaced by the
   filtered/gained key signal (mono, both channels) — sweep `KFLT` and listen to
   the filter. Turn it OFF → normal compression returns. (Requires `KEY` set;
   `KEY = OFF` + `SC LISTEN` does nothing.)
10. **No SVF instability**: hold `KFLT` at the extremes with a loud key for a
    while — no runaway / self-oscillation / DC.

## Session 37 (2026-09-07, `wip/mute-mode`) — the SAVE serialiser: `+0x4900` has its OWN disk chunk, no repack into `#1`

No-flash board item 1's alternative — "trace the SAVE serialiser for the
`+0x4900` → `#1` merge". **Answer: there is no merge in save.** The bank
serialiser writes `#1` and `+0x4900` to `bankNN.work` as *separate chunks*,
each read verbatim from RAM.

### The bank-record serialiser = `~0x4008a740` (p-lock section `0x4008ac20`–`0x4008b0d6`)

Serialises one pattern record to the open bank file. Registers: `a5` = the RAM
pattern base (`blob + bank*0x9b340 + pattern*0x8ed8`; confirmed — `+0x91a*trk +
0x59` = `#1`, `+0x8b0*trk + 0x4900` = `+0x4900`, `+0x8e50` = pattern trailer),
`d3` = file handle, `d2` = track loop 0–7. Two write callbacks: `0x400166b8`
(`f(handle, src, len)`) and an `a2`/`a4` variant; a running 16-bit checksum at
`0x460fab5c` is fed every byte.

**Loop 1 (per track) — the TRAC chunk:**
| src | len | = |
|---|---|---|
| `a5 + 0x91a*trk + 0x59` | `0x800` | **`#1`** — the 64×32 stored p-lock array, byte-for-byte |
| `a5 + 0x91a*trk + 0x859` | `0x40` | aux (64×1) |
| `a5 + 0x91a*trk + 0x89b` | `0x80` | aux2 (64×2) |

**Loop 2 (per track) — a SEPARATE per-track chunk:** 4-byte tag from
`0x400d169c`, 4 bytes from `0x460fab76`, the track byte, then
| src | len |
|---|---|
| `a5 + 0x8b0*trk + 0x48d0` | 8 | param bitmap the LIVE writer *sets* |
| `a5 + 0x8b0*trk + 0x48d8` | 8 | param bitmap the LIVE writer *clears* on erase |
| `a5 + 0x8b0*trk + 0x48e0 / 0x48e8 / 0x48f0` | 8 each | |
| `a5 + 0x8b0*trk + 0x48f8 … 0x48ff` | 1 each | |
| **`a5 + 0x8b0*trk + 0x4900`** | **`0x800`** | **`+0x4900`** — the LIVE-REC value records, byte-for-byte |
| `a5 + 0x8b0*trk + 0x5100` | `0x80` | |

⇒ `#1` is written **verbatim** (`0x4008ac32`, unconditional `f(handle, #1, 0x800)`),
never masked or filled from `+0x4900`. And `+0x4900` has its **own on-disk home**
(`0x4008b054`). **The Session-27 / `kb/file-format.md` model that "a serialise
repacks `+0x4900` → `#1` on save" is refuted.** (It's still consistent with
`--s27`'s observation: the DEMO was never LIVE-edited, so its `+0x4900` *disk
chunk* is all-`0xFF`, and the deserialiser fills `+0x4900` RAM with that.)

### `tools/emu_plock.py --save` — the experiment

Plants two sentinels on P11 t2 step 0 — `0x77` into `#1[0]`, `0x33`×32 into the
`+0x4900[0]` record (+ `+0x48d8`=`0xff`, `0x46c7d2e4[0]|=1<<trk`, armed bitmap) —
then posts SAVE PROJECT (`0x40023630(name)`, the opcode-9 poster) and lets the
storage task run. Hooks READS+WRITES on `#1(t2)` and `+0x4900(t2)`, keyed by
`card.writes`, and spies `card._commit_sector`.

- **Serialiser SOURCE reads, all in one pass (`card.writes==1340`):**
  `0x4008ac4c` reads `#1` (`0x800`); `0x4008b07a` reads `+0x4900` (`0x800`);
  `0x4008adde…0x4008b044` read the `+0x48d0…+0x48ff` header bytes. → it reads
  **both** structures, into **different** file chunks.
- The trailing pattern-reset (`0x4009acec` fills `#1`, `0x4009add0` fills
  `+0x4900`, `0x4009b23a` fills `#2` — all `0xFFFFFFFF`) is the LOAD-PROJECT-style
  reset the emulator's SAVE call also triggers (the known "sys resets to bank A"
  quirk); `#1[0] after` reads all-`0xFF` because of it, not the serialiser.

### Where the merge actually is → Session 38

Not in save. It must be on **LOAD** (the deserialiser `~0x4009ac00` clears then
re-fills `#1` / `+0x4900` / `#2` — does it fill `#1` from the `+0x4900` disk
chunk?) or at **pattern-enter** (`0x4009b84c` / `0x4009c02c` build `#2`).

But the practical read: a LIVE-erase's clear of `+0x4900` **does** persist
(own chunk), so the erased lock is (almost certainly) already gone for
**playback**; only the **LED** — `0x46c7d48c`, rebuilt by `0x400339d8` purely
from `#1` non-`0xFF` — stays lit. That's exactly Session 13's complaint
("the lock stays lit … pure visual noise"). So the fix is likely the SMALL one:

- **(b)** make `0x400339d8`'s `0x46c7d48c` (LED) build agree with playback —
  it already reads `+0x4900` (→ `0x46c7d2e4`); gate `0x46c7d48c[step] |= 1<<trk`
  on the step also being "live-present" (or never-live-touched). One function,
  no `0x40041bc4` decode, no `#1` write.
- (a) stays the fallback: hook `0x40041bc4` to also clear `#1[trk][step]`
  (Session 32's validated action) — needs the hard headless decode.

**NEXT (Session 38):** trace the deserialiser's `#1`/`+0x4900`/`#2` fill + the
pattern-enter `#2` build (do the working views mask `#1`?) → decide (a) vs (b),
then design the detour on the winner. `emu_plock.py --save` is the harness;
add a `--load` mode that hooks the deserialiser after a bank whose `+0x4900`
disk chunk was hand-cleared for one step.

## Session 38 (2026-09-07, `wip/mute-mode`) — playback reads `#1`, not the working views; the `+0x4900`→`#1` commit is on mode-exit

Static follow-up to Session 37: which structure drives **playback** and the
**LED** after a LIVE edit, and where is the working-view → `#1` commit.

### Playback = `#1`, unconditionally (step handler `0x4009d1e8`)

Per-param loop `0x4009d7dc`–`0x4009d848`:
- `sp@(92)` = a per-`(track, step, param)` byte, addressed with the **`0x91a`
  TRAC stride** + `step<<5` (so: `#1`-family, `TRAC + …`).
- `0x4009d7e0`: read the byte. `!= 0xFF` → `0x4009d7ee` writes it straight to
  `sp@(100)` = **`#2` (`0x46c7ab30`)** — the value the engine applies. **No check
  of `+0x4900` / `+0x48d8` first.**
- `0x4009d830`: separately AND-tests the `TRAC + 0x0a` param bitmap into `d4`
  (used downstream), but the `#1 != 0xFF → apply` above is not gated on it.

So the step handler pushes `#1` into the playback set every step. **A LIVE edit
reaches playback only once it is committed to `#1`.**

### Pattern-enter splices SCENE → `#2`, not `#1` → `#2`

`0x4009b842` / `0x4009c020` (per track): `moveb` loop copies **`#3`
(`0x46c7aa24`, SCENE)** → `#2` (`0x46c7ab30`) + `#3`-second (`0x46c77c32`) →
`#2`-second (`0x46c76ac0`), 32 B; then `[#2 bitmap 0x46c75fa0] = [#3 bitmap
0x46c7a874]`. (`kb/file-format.md`'s "splice #1/#3 → #2" was imprecise — it's
`#3 → #2`; `#1 → #2` is the per-step step-handler path above.)

### The LIVE cluster never writes `#1` — full disasm of all three

`0x40041784` (LIVE write), `0x40041bc4` (LIVE write/erase, ends `0x40042156`),
`0x40042480` (LIVE, ends `0x40042718`): each writes only `+0x4900` / `+0x48d0` /
`+0x48d8` / `+0x2880` / `0x46c7d2e4` / `0x46c7d344` / the `0x1001xxxx` mirrors +
dirty flags, and calls `0x40027de4` (2-word clear) / `0x400418e0` (status
redraw) / `0x4009da20` (working-set rebuild, from `0x40041784` only). **No `#1`
(`0x91a` stride + `0x59`) store anywhere.**

### The `+0x4900` → `#1` commit = the `~0x40062120` mode-exit cluster (not yet pinned)

`0x40062120`-ish (p-lock-edit / screen exit) calls, in order: `0x4004d870`,
`0x4004d640`, `0x4004d948` (p-lock draw family) · **`0x400339d8`** (LED rebuild
from `#1`) · `0x400418e0` · then `clrl 0x46c7d344` + `clrl 0x46c7d348`
(**clears the armed-param bitmap** — "these edits are committed") · `0x40020898`
· `0x4009da20` (working-set rebuild) · lots more.

The only other places that clear `0x46c7d344/d348`: `0x40062196` (here) and
`0x40083cc8` (load-time). So the arm-bitmap lifecycle is: `0x40041bc4` **sets** a
bit on a LIVE edit → `~0x40062120` **clears** it on exit. A `+0x4900` → `#1`
commit would ride exactly that "clear on exit" — read `+0x4900` for each armed
`(track, step, param)`, write `#1`, clear the arm bit.

**⇒ Because `#1` drives both playback and the LED, the trigless-lock fix
almost certainly needs the `#1` clear (Session 32's validated action), not a
LED-only change.** Best delivery: **hook the commit** (`~0x40062120` / whatever
does `+0x4900` → `#1`) to make it **symmetric** — propagate `+0x4900 == 0xFF`
→ `#1 = 0xFF` as well as `!= 0xFF` → `#1 = value`. That fires for every LIVE
edit (write *and* erase), needs no `0x40041bc4` step decode, and the
"1→0 trigless lock" case falls out because `0x400339d8` rebuilds the LED from
`#1` immediately after. Session 13's bug is then explained as: today's commit is
**add-only** (a LIVE erase's `0xFF` in `+0x4900` is treated as "no edit here",
so `#1` keeps the stale lock).

**NEXT (Session 39):** pin the commit instruction — search `~0x40062120` /
`0x4009da20` / the `0x4004d???` family for "reads `blob+0x4900` (`0x400e6ae0`,
`0x8b0` stride), writes `#1` (`0x91a` stride + `0x59`)", and check whether it's
add-only. Dynamic: `emu_plock.py --commit` — load DEMO, plant a `+0x4900`
sentinel + arm bit, `call_as_main(0x40062120)` (or the real exit), watch `#1`.

## Session 39 (2026-09-07, `wip/mute-mode`) — the playback chain is `#1`-only; the `+0x4900`→`#1` commit is not in any edit/release/save path

Hunted the `+0x4900` → `#1` commit (Session 38's open question). **Did not find
it** — and mapped enough to know it is not where it "should" be.

### The full playback chain — `+0x4900` is nowhere in it

`#1` (`TRAC+0x59`) → **step handler `0x4009d1e8`** (per-param loop, reads
`#1[step][param]`, `!= 0xFF` → writes `#2` `0x46c7ab30`) → **per-frame apply
`0x4000bad4`** (reads `#2` bitmap `0x46c75fa0`, applies to the engine). Both
disassembled; neither reads `blob+0x4900` (`0x400e6ae0`) or the LIVE bitmap
`0x46c7d2e4`. The `lea @(0x58,Xn); lea @(1,An)` in the step handler = `TRAC+0x59`
exactly (`0x58` is *hex* — brief-format displacement — earlier "+59 decimal"
was a misread).

### Nothing writes `#1` from `+0x4900`

Fully disassembled and checked for a `#1` (`0x91a` stride + `0x59`) write that
reads `+0x4900`:
- **edit** `0x4004ef54` (grid-rec knob writer) → writes `+0x4902` + `0x46c7d2e4`,
  calls `0x400369c8` (encoder-display preview — reads `+0x4900..+0x4905`, no
  write), `0x4009da20`, `0x400418e0`. No `#1`.
- **`0x400369c8`** — display only (fills `sp@20..44` with the 5 encoder values
  to show, from `+0x4900` + the `pat*0x18b2` PART-view). No `#1`.
- **release** `0x4005fb44` (grid-rec trig release, full disasm) → draws
  (`0x4002ce54` / `0x4002cef0` → `0x400356a8` + `0x40041760` "get held step") +
  clears the `+0x2470` 16-bit view + clears `+0x4900` to `0xFF` (`0x4005fdc6`) +
  clears `0x46c7d2e4`/mirrors. **No `#1` write, no `+0x4900` → `#1` copy.**
- **`0x4009da20`** (working-set rebuild, ran after every edit) — reads
  `TRAC+0x50/0x51` (param header) + `#1`, builds `#2` / scheduled events /
  `0x46c7a8xx`. Does not touch `+0x4900`; does not write `#1`.
- **`blob+0x4900` (`0x400e6ae0`) has exactly 4 refs image-wide** — all in the
  LIVE cluster (`0x40041f02/f72`, `0x40042546/642`). Nothing else, anywhere,
  reads or writes it by that literal.

### So the commit is on transport (STOP/PLAY) or a loop-wrap / deferred task

LIVE edits *do* reach playback on hardware, and playback is `#1`-only, so a
`+0x4900` → `#1` commit exists — just not in the edit / release / save /
pattern-enter / step-handler / frame-apply paths. Remaining candidates:
`FW_TRANSPORT` `0x4009b964` (STOP or PLAY case — complex, not yet traced),
a pattern-loop-wrap commit, or a deferred/idle task. `0x40062120` (p-lock-mode
exit) stays a candidate too — it clears the arm bitmap `0x46c7d344/d348`.

### Honest status / decision (11 p-lock sessions: S26–34, S37–39)

The data model is now **deeply mapped** (5 RAM structures, the disk chunk
layout, the serialiser, the playback chain, every edit path). The one missing
piece — the working-view → `#1` commit — has resisted a full static sweep of
the cheap leads. Finding it is ~1–2 more emu sessions (trace `FW_TRANSPORT`'s
stop path + a running-transport `emu_plock` that stops and watches `#1`), then
design + build is ~2 more.

**Recommendation: shelve the build until the MKI is back and do Session 13's
Phase 0** — export targeted test patterns (pure trigless lock w/ 2 locks; after
a LIVE erase of one; after erasing both; a manually-placed empty trigless lock;
etc.) and diff the banks. That settles the commit + the "trigless lock ≡ ?"
predicate directly and in one HW session, vs. several more emu sessions
chasing the commit. All the RE is banked in `kb/file-format.md`. The detour
core action (`clear #1[t][step] + 0x400339d8` → LED off) is already validated
(S32) and will slot straight in once Phase 0 names the hook point.


## Session 40 (2026-09-08, `wip/mute-mode`) — KB ingest: octabam ColdFire port + page-2 publish path + efw-tool (no firmware work)

`whatsnew.py`: octamax up to date; **efw-tool +5**, **octabam +126** (ColdFire
port O1–O12, one-aux bus, RTOS 10.17–10.18). Synced both to tip
(`refs/MANIFEST.lock`: efw-tool `065d18f`→`a5bce9a`, octabam `47f6cc5`→`04b8512`;
octamax left at its last-distil pin). Distilled the parts that touch our two
active threads; the bus/reverb/xbus/recorder-seam work stays out of scope
(`UPSTREAM_INBOX.md` Pending).

### What went into `kb/`

- **`memory-map.md` "Parameter value → the engine"** (NEW) — the full page-1 vs
  page-2 publish path, hardware-verified by octabam over 12 flashes
  (`midi_re_cc.md` §7). Generic writer `FUN_40054cd8(track, flat, value)`;
  page-2 editor `P2EDIT 0x4003a474`; page-2 Part store
  `DB + part*6322 + 0x8ef5a + track*30 + page*6 + slot2` (`page = 0` for FX2);
  **mandatory bookkeeping flags** (`DB+0x95048|=1<<part`, `0x100b145e|=1<<part`,
  `DB+0x9b332=1`, `0x100f8598=1`) or the store is inert; live lane
  `0x80000830 + track*72 + slot2`; **page 2 has NO DSP post** — it rides only the
  per-frame copier `0x4000cae8` (twin `0x40003d14`); page 1 *does* post a
  kind-0x0f record to DSP queue `0x460d17ee` (consumed `0x4009204c`). Dial reads
  `0x8f084 + track*30 + slot`. **Supersedes** NOTES S17's "page-2 r6 offsets less
  certain — verify".
- **`memory-map.md` "Per-voice DSP record"** (NEW) — `0x80000110/0x310` (core 1) /
  `0x210/0x410` (core 0), 32 halfwords/track: `+0..5` AMP, `+6..11` FX1 pg1,
  `+12..17` FX2 pg1 (`value<<8`; page-2 select in the low byte), `+27/+28` ids.
  Copier `0x4000cae8` from pre-image `0x80000a50 + track*64`. FILTER coeff block
  `X:0x2c0` = FX2 instance / `X:0x3a0` = FX1 (`r6` base `X:0x2c3 / 0x3a3`).
- **`techniques.md` "the ColdFire PORT"** — octabam's `tools/ot_emu`: headless C++
  ColdFire V4e + both DSP cores + ESAI audio + CF load (O1–O12); O11 found a real
  HW bug (dispatcher bumps `r7` ×3/track, third unconditional after FX2). Traps:
  "load part ≠ play part", "dsp_host pokes r6 → a slot can publish nothing",
  "part saved under an older slot layout → sequencer stalls on first play".
- **`container-format.md`** — efw-tool: ELEK version field is a **fixed 10-byte
  right-justified field at `0x08`** (was `0x0D`); aPLib offset-bias underflow is
  deliberate; `--emit-container`. Our `140C_KYOTI` tag is exactly 10 chars → fine.
- **`file-format.md` p-lock Phase 1** — octabam names **`0x4000c42c–0x4000c5a0`
  "the p-lock applier"** (trig-run coverage diff; armed-bitmask check
  `0x4000bd14`); `emu_rtos.py` now runs the full transport/sequencer with a
  unit-saved card + `--start --poke-trig --internal-clock`; transport
  `FW_TRANSPORT 0x4009b964` start case `0x4009c458`.

### Relevance to WIP — the headline

**Side-chain (Sessions 17/36).** KEY / KEY FLT / KEY GAIN / SC LISTEN are all
**page-2** params on the COMPRESSOR descriptor, and our DSP hooks read them from
`x:(r6+$d/$e)`. octabam's HW-verified §7 says page 2 has **no DSP post** — it
reaches the engine *only* via the per-frame copier's `+0x20` lane
(`0x80000830 + track*72 + slot2`). So:
  1. our `emu_sc_dsp3.py` passing is **not** evidence the KEY bytes arrive at
     `r6` on hardware — `dsp_host` pokes `r6` directly ("a slot can publish
     nothing"). The stock **RMS** page-2 slot (`r6+$c`) proves the mechanism
     *exists* for COMPRESSOR, but our added slots need the same lane path.
  2. **when SIDECHAIN2/3 is flashed, the first HW check must be "does turning KEY
     actually change `r6+$d`":** confirm the copier forwards our new page-2 slots
     (it forwards RMS; slots are positional so it very likely does, but verify).
  3. p-locking KEY: the `0x80000db4` slew-marker packer covers **page-1 bytes
     0..31 only** — page-2 params p-lock via a different path; check before
     promising KEY as p-lockable.
  4. adding page-2 slots to COMPRESSOR hits the "**older slot layout → sequencer
     stalls on first play**" trap for existing projects that use COMPRESSOR —
     the flash notes need a `stamp-defaults`-style step or a safe-default guard.

**p-lock / trigless-lock (Sessions 24–34, 37–39).** Session 34's "not tractable
headless" wall predates the current `emu_rtos.py`, which now runs transport +
sequencer + step handler end to end with a unit-saved card. Combined with
octabam's named `0x4000c42c` p-lock applier and the `FW_TRANSPORT` start-case
map, the emu-only route to the `+0x4900`→`#1` commit is more open than S39
implied — a running-transport `emu_plock` that `--start`s, does a LIVE edit,
then STOPs and watches `#1` is now buildable. Doesn't change the S39
recommendation (Phase 0 HW diff is still fastest once the MKI is back), but it's
a real alternative if HW stays out of reach.

### Follow-up (same session) — three questions answered

**Bryan T (`octa-bt-pt`).** Repo is static — 4 commits, last 2026-08-22. His
*live* RE (Echo-Freeze delay, recorder architecture, timestretch, EMAC/MACSR,
the clickless-loop primer + spreadsheet) is shared on **Discord** and reaches us
only as it's folded into octabam's `docs/EXTERNAL.md` (§1, §6–§8) — which the
`04b8512` sync brought current. All of it is recorder / delay / timestretch —
none touches our threads; the relevant bits (EMAC fix, recorder-page 3-tier
storage, machine-type values) were already in `kb/`. So: nothing new to ingest
from Bryan for now, and `whatsnew.py octa-bt-pt` will stay quiet — watch octabam.

**Slice number display (octamax SLICE PLAYHEAD).** octamax is at tip, so the
material was already in the `refs/` cache — but only "noted, not adopted". Now
**distilled the reusable RE** from `DESIGN_SLICEVIEW.md` into
`kb/memory-map.md`: the `0x800049d8` voice-struct field map (+8 SETTINGS ptr,
+23 loop mode, +32 slice index, +36 rate, +48/+52 window, +68 play position),
`FUN_40007960` (the ColdFire-side playback-position engine), the slice table
(`SETTINGS + 312 + n*12`, count `+1092`), the screen primitives + surface
`0x400bf10a`, and **the `0x40056c92` periodic-repaint hole** (post UI event 78 →
`0x40062d04` redraw; fires even with no TIMER). The octamax-specific parts (its
menu-array relocation `0x400d6a00`, its cave budget) stay in the cache. The
feature itself is octamax's, not ported.

**Why p-lock KEY (or any new page-2 param)?** It was never a feature goal —
it's a **parity check**. The Session-17 checklists say "confirm a new page-2
slot renders + p-locks *like RMS does*": RMS is the stock page-2 slot on the
COMPRESSOR, page-2 FX params are p-lockable on the OT as a platform fact, and a
slot added to the descriptor inherits that machinery. The check is "did adding
our slot break the stock p-lock path, or does it behave like its neighbour" —
not "we want per-step key-source automation" (which would be an odd thing to
want). octabam's §7 finding sharpens *how* to check: since page-2 has no DSP
post and the slew-marker packer is page-1-only, page-2 p-lock plumbing differs
from page-1 — so if **RMS itself** turns out not to p-lock cleanly to the DSP
under the copier lane, KEY won't either, and that's stock parity, not a Kyoti
regression. Item 3 on the to-do board is really "match RMS", nothing more.


## Session 42 (2026-09-08, `wip/mute-mode`, RE / feasibility only — no repo code) — "RELOAD FROM PROJECT": per-pattern reload from the CF card without stopping playback

> Session numbering note: NOTES's last entry was "Session 40" (= memory's
> "Session 41" — the two numberings drifted at the 2026-09-07 repo reorg). This
> entry is "Session 42" in both from here on.

### The idea

Adapt the Digitone's **RELOAD FROM PROJ** (manual §14.3.5) for the OT. On the DN
it reloads the active pattern's data from the +Drive with three granularities:
WHOLE PATTERN (sequence + the 4 Sounds), SOUNDS DATA, SEQUENCE DATA — each behind
a menu entry + a YES/NO prompt. User wants it surfaced to the OT front panel: a
key combo opens a small menu, pick one of three, `[YES]` confirms.

**OT option names (user, this session):** `WHOLE PATTERN` / `ALL PARTS` /
`SEQ DATA`. "Sounds" → "Parts" (DN Sound ≈ OT Part; a bank has 4).

**The point of the feature — what stock OT cannot do:** revert a pattern (or its
parts, or its sequence data) to the **CF-card-saved state** *without stopping the
sequencer*. Stock `RELOAD BANK` does a card reload but (a) is whole-bank — all 16
patterns + 4 parts — and (b) stops audio (the confirm pre-step `FUN_400a10c8`
resets per-track note/voice scratch synchronously, and the end re-sync
`FUN_400238a4` cuts again a few steps later — both hardware-observed in the
bankpage RE, `reference/upstream-notes.md` "RELOAD BANK call chain"). There is no
pattern-level reload at any granularity in stock 1.40C (the project/state parser
`FUN_400866c4` knows `RELOAD_BANK`, `PASTE_PATTERN`, `RENAME_PART`… — no
`RELOAD_PATTERN`).

### Is a single-PART reload already covered by stock OT? — mostly yes

Stock **PART → RELOAD** reverts the *active* part to its last **SAVE PART**
snapshot, live, no transport stop (parts are designed to switch during playback;
the .work file carries 4 live + 4 saved part copies — `kb/file-format.md`). So
the common "I nudged the filter, put it back" case is a stock button already.

What that stock path does **not** give you, and what the three options add:

| gap | covered by |
|---|---|
| revert to the **card `.strd`** state (SAVE BANK), not the SAVE PART snapshot — a different, often older/newer point | `ALL PARTS`, `WHOLE PATTERN` |
| revert **all 4 parts** at once | `ALL PARTS` |
| revert **sequence data** (trigs, p-locks, length, scale) to the card state — no stock equivalent below whole-bank | `SEQ DATA`, `WHOLE PATTERN` |
| do any of the above **without stopping playback** | all three |

Conclusion: **no dedicated single-part option.** `ALL PARTS` covers the
multi-part case, `WHOLE PATTERN` the combined case; one-part-at-a-time stays on
the stock PART RELOAD button. (Worth a quick emu/HW confirm that stock PART
RELOAD is genuinely transport-non-stop — consistent with how parts switch, but
not yet verified in this repo.)

### What already exists (the reuse story)

- **Background bank-load task `FUN_4008445c`** (prio 1, own stack) — hardware-
  proven (bankpage) to run `FUN_4008ded0` deserialisation into a bank's RAM
  region *concurrently with playback, no stop*. Takes a 16-bit bank mask.
  Job posted via `FUN_40022778` → queue `0x460d17ce` → soft-IRQ wake.
- **`FUN_4008ded0`** — bank deserialiser (file → `0x400e21e0 + bank*0x9b340`).
- **`.strd` vs `.work`** understood: stock reload = `FUN_4008f0b0` copies
  `.strd`→`.work` then `FUN_400905d4`→`FUN_4008ded0` deserialises `.work`. We
  **skip the copy** and redirect the *open* `.work`→`.strd` — same hook class as
  bankpage's `g_redirect` project-dir redirect (`FUN_40025230 @ 0x40025244`).
- **`FUN_400a1eea`'s reload blocks** — the arranger/RELOAD path already re-homes
  the active pattern from the blob (step reset + length reload + per-track
  voice-scratch re-init + **Part/scene array load**) **without stopping audio**.
  DIRECT JUMP repurposed it. Gate: `_DAT_46c8028a ≠ 0` ("reload now").
- **Non-playing bank RAM regions are safe scratch** (bankpage, HW-confirmed) —
  lazily reloaded on next access.
- **`emu_rtos.py`** runs the full storage stack + LOAD PROJECT + transport +
  sequencer against our image → this feature is **end-to-end emulator-testable**
  before any flash.
- **Custom overlay + keymap-chord toolkit** — DIRECT JUMP v2's box-free toast
  (`FUN_4005a0e0` + a frame countdown spliced into `0x40052200`), the 26-byte
  keymap records, the catalogued free chords (`[PTN]`+X is free bar
  `[PTN]`+`[YES]`). **No PERSONALIZE menu-array surgery** — the only thing that
  has ever bricked the MKI is avoided.

### Proposed architecture

1. **Combo → 3-item overlay** (`WHOLE PATTERN` / `ALL PARTS` / `SEQ DATA`),
   up/down + `[YES]` / `[NO]`. Custom overlay, not a PERSONALIZE screen.
2. **On YES**, post a background job (new msg type on the `FUN_4008445c` queue):
   - Existence/validity check on `<proj>/bankNN.strd` via the firmware's own open
     helper `FUN_40016864` (bankpage's validated method). **Rule from bankpage
     RE: never open a handle the firmware holds open for playback** — `.strd` is
     not held open (only `.work` is), so this is safe; verify at build. This is
     the OT analogue of the DN's "must have saved at least once".
   - `FUN_4008ded0(bankNN.strd)` → a **scratch bank region** S (`(curbank+8)&15`,
     or the top unused bank index).
   - `memcpy` the selected slice(s) from scratch pattern P → live blob pattern P
     (`0x400e21e0 + curbank*0x9b340 + P*0x8ed8`):
     - `SEQ DATA`: the `P*0x8ed8` TRAC region — 8 × `0x91a` per-track blocks
       (trigs at `+0x00`, masks `+0x08..0x38`, p-locks `+0x59`, param hdr `+0x50`)
       + the pattern header (length `+0x8e54`, scale `+0x8e55`, part index
       `+0x8e57`/`+0x8ee7`). Sub-ranges mostly mapped from the p-lock work
       (`kb/file-format.md`); confidence C for masks, L for the p-lock internal
       param map — but a whole-region copy doesn't need the internal map.
     - `ALL PARTS`: the 4 part payloads (`part*0x18b2`, base region ~`+0x8f04a` /
       `part*6322` — **needs pinning at build**).
     - `WHOLE PATTERN`: both.
   - If P == active pattern: set `_DAT_46c8028a` → `FUN_400a1eea`'s immediate-
     reload block re-reads the (now byte-patched) blob for P next step, no audio
     stop. If P ≠ active: do nothing — picked up on the next switch.
   - Invalidate/restore scratch region S (post a stock type-6 reload for index S,
     or clear its "loaded" flag so next access refills it).
3. **Overlay auto-dismisses** (frame countdown, DIRECT JUMP v2 style).

### Which saved snapshot?

`.strd` (SAVE BANK) for all three, for coherence — `WHOLE PATTERN` then means
"seq + parts from one consistent point", matching the DN's "from +Drive". Note
`ALL PARTS`-from-`.strd` is genuinely distinct from repeating stock PART RELOAD
even for the active part, because PART RELOAD targets the *SAVE PART* slot, a
different snapshot. **Cheaper phase-1 alternative for `ALL PARTS` only:** copy the
4 in-RAM saved part slots → the 4 live slots (pure RAM, no file I/O, no scratch) —
but that's the SAVE PART snapshot, not the card state, so it breaks the "one
consistent point" story for `WHOLE PATTERN`. Recommend `.strd` for all three.

### Open questions to resolve in the first RE session

1. Can `FUN_4008ded0` be pointed straight at `.strd` into an arbitrary bank
   region, or does it key off `.work` naming / bank-state bookkeeping?
2. Exact byte sub-ranges: the parts base offset + stride in the blob (pin
   `part*0x18b2` vs `part*6322` and the base — `0x8f04a` / `0x8f382` seen in
   different notes), and the full TRAC-region extent per pattern.
3. Does `FUN_400a1eea`'s reload block fully re-apply **part params** for the
   active pattern, or is a `FUN_40009094` (part-by-event) nudge also needed for
   `ALL PARTS` / `WHOLE PATTERN`?
4. Position on reload-while-playing: stock immediate-reload zeroes
   `_DAT_800065b4` (step-0 restart). Accept for MVP, or reuse DIRECT JUMP's
   modulo position-preserve.
5. Combo choice — pick a free chord, confirm globally unbound against the keymap
   tables.
6. Scratch-region choice when the project uses all 16 banks (fall back: copy the
   other 15 patterns out, do a full reload, copy them back).

### Effort, risk, recommendation

- **Effort:** ~2–4 RE/design sessions (pin Qs 1–6) + ~2–3 build/emu sessions
  (`emu_rtos` covers it) + 1–2 flashes. Bigger than DIRECT JUMP by the file-I/O
  layer; smaller than the DSP side-chain.
- **Brick risk:** moderate — comparable to DIRECT JUMP, well below the DSP flash.
  No menu-array surgery. Worst realistic failure = audio glitch / hang needing a
  power cycle. The one real hazard is deserialising into the wrong RAM region /
  touching a held FS handle → mitigated by the bankpage rules (scratch = a
  non-playing bank index; only ever open `.strd`).
- **MVP:** `SEQ DATA` first, as a single combo (skip the overlay-menu build).
  That is the entirely-new capability and the smallest slice. Add the 3-way
  overlay + `ALL PARTS` / `WHOLE PATTERN` as phase 2.
- Build now (emulator-testable), flash later — fits the MKI-gated queue. Shares
  deserialiser/serialiser RE with the trigless-lock backlog.

### Ready to develop?

Ready to start the **RE session** now (drive `emu_rtos`: confirm `FUN_4008ded0`
can target `.strd` + a scratch region, pin the parts offset, check whether
`FUN_400a1eea`'s reload block covers parts, pick the combo). **Not** ready to
write patch code until that lands — Qs 1–3 gate the design. No `tools/` files
this session.

### RE session (same day) — Qs 1–3 answered from static disasm; design holds

Disassembly base `0x40000400` (`m68k-elf-objdump --adjust-vma=0x40000400`).

**Q1 — can `FUN_4008ded0` target `.strd` + an arbitrary region? YES.**
`FUN_4008ded0(fileHandle @fp+8, destRegion @fp+12, 0)` — takes an already-open
buffered-file handle and an explicit destination pointer; streams the file in
4-byte reads via `0x40016564`, checksum into `0x460fab5c` vs `0x400d1670` /
`0x460fab54`. Nothing wired to `.work` naming or bank-state. The type-6 consumer
`FUN_400905d4(mask)` (called from the bg task `FUN_4008445c`) shows the full
recipe per bank bit:
- `jsr 0x40025230(0,0)` → project dir (the bankpage `g_redirect` gate is inside,
  at `0x40025244`);
- `sprintf(buf, "%s/bank%02d.work", dir, bank+1)` — **format string
  `0x400b86c7 = "%s/bank%02d.work"`; the `.strd` twin `0x400b86d8 =
  "%s/bank%02d.strd"` is already in the image, 17 bytes along.** Redirect = swap
  the `pea 0x400b86c7` operand at `0x40090676` to `pea 0x400b86d8` (or build our
  own sprintf with `0x400b86d8`);
- `FUN_40016864(handle@a4, path, "r" @0x400b3289, buf @0x460a8f60, 0x10000)` —
  buffered open;
- `FUN_4008ded0(handle, destRegion, 0)` — `destRegion = d6`, seeded
  `0x400e21e0` and `+= 0x9b340` per bank ⇒ **the cold blob base for a bank is
  `0x400e21e0 + bank*0x9b340`**, confirmed;
- `FUN_4001677c(handle)` close;
- ENOENT (`d2 == -12`) path sets `blob + 0x9b332 = 1` (the "bank invalid" flag).

**Q2 — blob layout, pinned exactly** (from `FUN_40009094` + `FUN_4000faf0`):

| region | offset in bank | stride / len |
|---|---|---|
| 16 pattern slabs | `0` | `pat*0x8ed8` (36568), 0..15 |
| 4 part payloads | **`0x8ed80`** (= `16*0x8ed8` exactly) | `part*0x18b2` (6322), 0..3 → `0x62c8` total |
| end of parts | `0x95048` | (= the `DB+0x95048|=1<<part` bookkeeping byte) |
| bank stride | — | `0x9b340` (635712) |

`FUN_40009094(bank, part)` reads part data from `0x40170f60 + bank*0x9b340 +
part*0x18b2` — and `0x40170f60 == 0x400e21e0 + 0x8ed80`, i.e. the parts region of
the cold blob (it also derives `0x40170f8a` / `0x4017107a` — the memory-map's
"frame-builder refreshers" — which are `parts_base + 0x2a` / `+ 0x11a`).
`FUN_4000faf0(bank)` is "make bank current": `memcpy(0x1001614e, blob +
bank*0x9b340, 0x8ed80)` (all 16 slabs → live copy) + `memcpy(0x100a4ece,
parts_base + bank*0x9b340, 0x62c8)` (parts → live) + 5 small per-bank
flag/shadow copies. So:
- **SEQ DATA** = `memcpy(live_blob + curbank*0x9b340 + P*0x8ed8, scratch + P*0x8ed8, 0x8ed8)`
- **ALL PARTS** = `memcpy(live_blob + curbank*0x9b340 + 0x8ed80, scratch + 0x8ed80, 0x62c8)`
- **WHOLE PATTERN** = both.

The cold blob `0x400e21e0` **is the working store** — p-lock edits land there
(Session 27's `+0x4900` writer, `emu_plock --confirm`), so other patterns'
unsaved edits sit in their own `pat*0x8ed8` slabs and a single-slab copy leaves
them untouched. `0x1001614e` / `0x100a4ece` are a downstream live cache that
`FUN_4000faf0` refills from the cold blob (all-16, but only the reloaded slab
differs, so it's safe to call).

**Q3 — does the seamless reload path cover the pattern? YES for sequence; parts
need `FUN_40009094`.** `_DAT_46c8028a` ("reload now") is polled every step by
`FUN_400a1eea` at `0x400a2530` (`tstl … ; beq`); the block `0x400a253a–0x400a28ce`:
`d2 = [0x800065bd]*0x9b340 + 0x400e21e0` (**active bank's cold blob**),
`d3 = [0x800065be]` (active pattern), stride `0x8ed8` — then rebuilds, from that
slab: per-track voice/note scratch (loop over `fp = slab+0x36` audio stride
`0x91a` / `a5 = slab+0x48fc` MIDI stride `0x8b0`), master + per-track pattern
length & scale (`slab+0x8e52/0x8e54`, `0x400aba50` scale table → `0x800065b6`,
`0x800065d3[]`), the per-track pattern/bank pointer tables (`0x46c775bc` /
`0x46c775cc/cd` — the p-lock decode inputs from S33/34), `0x8000663d` scale
index, and zeroes `0x800065b4` / `0x800065b2` (step → 0). It does **not** touch
Parts (purely sequencer-side) and does **not** rebuild the p-lock working set
`#2` — but the step handler `0x4009d1e8` re-reads `#1` from the blob every step
and rewrites `#2` unconditionally (S38), so trigs + p-locks adopt on the next
playhead pass. The setter I found (`0x4000aea6`, `move.l #1,0x46c8028a` + soft-IRQ
`0xfc048010`) is the plays-free PICKUP-sync auto-reload — too context-bound to
reuse, but the flag is a plain global: **our worker just does `move.l #1,
0x46c8028a`** and the running step engine adopts the patched slab. Parts: after
an ALL PARTS / WHOLE copy, call the stock reload tail for the playing bank —
`FUN_4000faf0(bank)` + `FUN_400a1030(bank,[0x80000004])` + `FUN_40009094(bank,
[0x80000003])` (exactly what `FUN_400905d4` does at `0x400907b8` when
`[0x80000002]==bank`).

**Refined build plan**

1. **Combo → 3-item overlay** (`WHOLE PATTERN` / `ALL PARTS` / `SEQ DATA`),
   arrows move the highlight, `[YES]` / `[NO]`. Custom overlay (DIRECT JUMP v2
   toast primitives `FUN_4005a0e0` / `FUN_5829c` + a frame countdown). Combo:
   sibling of DIRECT JUMP's `[PTN]`+`[YES]` — candidates `[PTN]`+`[BANK]`
   (`0x2e`+`0x2f`) or `[PTN]`+`[PAGE]`; confirm unbound in the keymap tables at
   build. (`[PTN]` press sets `0x460d1742`, read by nothing → free chord; set
   `0x460d173e=1` to swallow the SELECT-PATTERN-on-release.)
2. **YES → post a job** on the `FUN_4008445c` queue (new msg type, carries {which
   of the 3, pattern P, "P == active?"}). Worker:
   - `sprintf(buf,"%s/bank%02d.strd", dir, curbank+1)` via `0x400b86d8`;
     existence = `FUN_40016864` opens it (`d0 >= 0`), else toast "NOT SAVED" and
     bail. **Only ever open `.strd` — never `.work` (FW holds it open; bankpage
     rule).**
   - `FUN_4008ded0(handle, 0x400e21e0 + S*0x9b340, 0)` into scratch bank index
     `S` (`(curbank+8)&15`); `FUN_4001677c` close.
   - `memcpy` the SEQ slab and/or the parts region scratch→live (offsets above).
   - restore scratch S: post a stock type-6 reload for bit `1<<S` (reads
     `bankS.work` back into `0x400e21e0 + S*0x9b340`) — or, if S is beyond the
     project's bank count, skip.
   - if P == active: `move.l #1,0x46c8028a` (seq); for parts also
     `FUN_4000faf0`/`FUN_400a1030`/`FUN_40009094` as above. If transport stopped
     (`[0x800065b8]==0`), the step engine isn't ticking → call the reload
     directly or `FUN_400a1030(curbank,P)` to re-commit.
   - toast "RELOADED" ~0.7 s, auto-dismiss.
3. **MVP:** `SEQ DATA` only, single combo, active-pattern only, playing only —
   ~1 detour + a ~120-word cave + the queue msg. Phase 2 adds the overlay +
   `ALL PARTS` / `WHOLE` + stopped-transport + non-active P.

**Still build-time (emu-verifiable, not design-blocking):** does the per-step
trig/p-lock handler read the cold blob or `0x1001614e` (decides whether the
`0x46c8028a` block alone refreshes SEQ, or we also need `FUN_4000faf0`);
`FUN_4000faf0` glitch risk on the playing bank (bankpage never tested it without
the pre-step); scratch-bank restore latency; exact combo. `emu_rtos` (Session 23,
runs the storage stack + transport + sequencer) covers all of these.

Tools next session: `tools/emu_reload.py` (drive the worker in `emu_rtos`:
load DEMO, edit pattern P live, run the worker, assert P reverts + other
patterns' edits survive), then `tools/patch_reload.s` + `tools/build_reload.py`.

### `tools/emu_reload.py` (same day) — the core mechanic is PROVEN in `emu_rtos`

`--slice` : **ALL GOOD.** Load DEMO (curbank 0, `PART_PTR == 0x400e21e0` — blob
geometry confirmed live), `seq_select_live(0, 10)`, start the transport, then
while playing: scribble trig-mask + p-lock bytes into both pattern 10's slab
*and* pattern 0's slab in the blob, `memcpy` pattern 10's saved slab back, poke
`0x46c8028a = 1`, run 400 ms of frames. Result: **pattern 10 reverted, pattern
0's edit survived, `0x46c8028a` consumed by the running step engine,
`0x800065b6` (pattern length−1) reloaded 0→1, step kept advancing, transport
stayed at 1, no fault.** ⇒ the SEQ-DATA mechanic (slice-copy into the blob +
fire the reload-now flag) works live, is bystander-safe, and needs no transport
stop.

`--strd` : the async storage-task job runs end to end — `call_as_main(
FUN_40022778, 1<<curbank)` (a pure post, safe) → the real `FUN_4008445c`
dequeues → `FUN_400905d4` → `FUN_4008ded0` → the blob is re-deserialised (a
0xAB scribble across `#1` is wiped and the array refilled from a bank file).
Stock pulled from `bank01.work` (the 0x14 case's `.strd`→`.work` copy step
didn't take in the emu without its `0x100b14f0` context) — the FEATURE build
redirects the open to `bank01.strd` (`0x400b86c7`→`0x400b86d8`) and skips that
copy, so `.strd`-vs-`.work` is a patched-image / HW check, not a blocker.

`call_as_main(FUN_40016864, …)` (synchronous open) **faults** `rte would return
to user mode` — the buffered open blocks, confirming the file layer MUST run on
the storage task, not a synchronous cave (the design already routes through
`FUN_4008445c`).

### Storage-task job model (RE this session, for the build)

`FUN_40022778(mask)` builds a msg at `0x460bd912` `{[0]=type 0x14, [2]=mask(w),
[4]=beginFn 0x40023230, [8]=doneFn 0x40023bf4, [0xc]=fn3 0x40022dc4}` and posts
it to the storage queue `0x460d17ce` via `0x40000c3c`. `FUN_4008445c` main loop:
`0x40000d00` blocking-dequeue → `d0 = msg[0]` (type, ≤45) → word jump table at
**`0x40084870`** (`jmp (0x40084870, type*2 : word)`). Type 0x14 case
`0x40085864`: `FUN_4008f0b0(0x100b14f0, mask, &outA, &outB)` (`.strd`→`.work`
copy, posts type 6); type 6 case `0x40084eee`: `FUN_400919e4(0x100b14f0, mask,
…)` → per-bank `FUN_400905d4`-equivalent → `FUN_4008ded0`. `0x40023230`
(the job's `begin`) just shows the non-modal "RELOADING BANK" overlay
(`FUN_400808bc`). **The FEATURE hooks: (1) combo → set `G_KIND`/`G_PAT`, post
`FUN_40022778(1<<curbank)`; (2) type-0x14 case entry `0x40085864` → if `G_KIND`,
jump to a self-contained worker cave (runs on the storage task, may block):
sprintf `.strd` via `0x400b86d8`, `FUN_40016864` open, `FUN_4008ded0` into
`scratch = 0x400e21e0 + ((curbank+8)&15)*0x9b340`, `FUN_4001677c` close,
`memcpy` the SEQ slab and/or the parts region into the live blob, restore the
scratch bank (post a stock type-6 for `1<<S`), `move.l #1,0x46c8028a`, show +
schedule-dismiss the toast; else fall through to stock.** No `FUN_400a10c8`
pre-step and no `FUN_400238a4` re-sync are ever invoked → no audio stop.
`tools/patch_reload.s` + `build_reload.py` next session; then `emu_reload.py
--patched` (post the real combo, let the real worker run).

### Session 42 continued (same day) — build attempt 1, scratch-bank design REJECTED, redesigned

**`patch_reload.s` v1 (scratch bank) — built, but the design is wrong.** The
worker deserialised `bankNN.strd` into bank `S=(curbank+8)&15`'s resident blob
(`FUN_4008ded0` into a whole-bank region), sliced pattern P out, then "restored"
bank S from `bankS.work`. **User rejected it (correctly): plenty of people keep
real work on bank S; a feature that reverts one pattern must never risk another
bank's data.** Also caught: a fabricated "~0.01% torn-read odds" — retracted, the
window is real and needs a real answer, not a hand-wave. `emu_reload.py --slice`
proved the *mechanism* (slab-copy + `0x46c8028a` → seamless revert, bystander
patterns safe); `--strd` proved the async job path runs; `--patched` v1/v2 hit a
combo bug: **`tst.b 0x800065b8` read the always-0 MSB of the big-endian LONGWORD
transport state** (every firmware access is `.l`) → the "only while playing" gate
always bailed. Fixed → `tst.l`. Also dropped a cargo-culted `NO_DISABLE` gate.

**The simpler decomposition (user's push):**

- **ALL PARTS** = **`FUN_4004aab4(0); (1); (2); (3);`** — the exact stock
  "RELOAD PART" (behind `"PART %d RELOADED"` / `"SAVE PART FIRST!"`), disassembled
  this session: copies the saved part slot → live, **in both the blob
  (`+0x9504a` → `+0x8ed80`, `0x18b2` B) and the working copy `0x100a4ece`**, sets
  every dirty flag (`+0x95048` bit, `0x100b145e`, `+0x9b332`, `0x100f8598`), and
  re-applies to the engine if it's the current part (`FUN_40009848` +
  `FUN_400972fc` ×8). Returns 0 for a never-saved part. Stock "SAVE ALL PARTS"
  (`0x4002dcd0`) already loops it 0..3. **Pure RAM, no file I/O, no scratch, runs
  in the key handler.** The per-part "saved" flags at `blob + 0x9b312[part]` are
  set by both `FUN_4004a908` (SAVE PART) and `FUN_4008ded0` (deserialiser, from
  the file) → works on a freshly-loaded project.

- **SEQ DATA** = still a card read (patterns have **no** in-RAM saved copy — only
  parts have the 4+4 slot layout), but targeted. `FUN_4008ded0` is built from a
  **per-pattern chunk parser `FUN_4008cebc(fh, destSlab, verWord)`** (called 16×,
  `dest = bankbase + i*0x8ed8`) + a per-part parser (`FUN_4008be2c`, 4×+4× at
  `+0x8ed80` / `+0x9504a`). Bank-file header (hexdump): `FORM····DPS1BANK` +
  `0x10` 4 B + **`0x14` 2-byte version word** (`FUN_4008cebc` arg3 — VARIES:
  DEMO 0x16, PRJ_01/CASCADE 0x15) + `0x16` `PTRN`. `FUN_4008cebc` reads its
  chunk's `PTRN`/`TRAC` tags itself and does **not** self-validate the rolling
  checksum `0x460fab5c` (only `FUN_4008ded0`'s whole-file tail does). Disk PTRN
  stride measured `0x8EE8` (≠ OctaLib's `0x8EEC`) → **don't seek by offset;
  parse sequentially** and discard patterns 0..P-1. Scratch = `0x460a8f60`
  (loader's 64 KB buffer, idle while our worker holds the task): 28 KB open
  buffer + 36 KB pattern scratch. **No other bank, no `.work` touched.**

- **WHOLE PATTERN** = ALL PARTS + SEQ DATA.

**Guards (RE'd):** `.strd` files are **not created until the first SAVE BANK**
(fresh projects have none). Stock RELOAD BANK opens `bankNN.strd`, gets ENOENT
(`-12`), and shows `"THIS BANK HAS NEVER BEEN SAVED! NOTHING TO RELOAD!"`
(`0x400b988c` via `FUN_40023bf4`). **Our SEQ worker gets this for free:** on
open-fail, exit the 0x14 case with `d0 = -12` → the done-dance (`FUN_40023bf4`)
shows that stock dialog. No new strings, no dialog code. ALL PARTS: count
`FUN_4004aab4` successes → "N PARTS RELOADED" / reuse `"SAVE PART FIRST!"`.
**No confirm prompt** — matches stock PART RELOAD; the two-key combo is the
intent (user's call, agreed).

**`patch_reload.s` v3 (SEQ DATA emu-validated + phase-2 picker) — BUILT.**
1198-word cave, `OCTATRACK_OS1.40C_RELOAD.{syx,bin}` 952 B vs stock, Bug-1 fix
byte-identical, `patch_trigscale` unaffected. **Four detours:**
- `rl_combo` @ NO handler `0x4005e25c` — `[PTN]`+`[NO]` (playing / no arranger /
  no popup): open the picker (bare-text popup `FUN_4005a0e0`: `RLD SEQ` /
  `RLD PARTS` / `RLD WHOLE`, `G_MENU`/`G_SEL` at `0x80006a52/53`) or cycle the
  selection if already open. `tst.l RUNNING` (the transport state `0x800065b8`
  is a big-endian LONGWORD — `tst.b` read the always-0 MSB, the v1/v2
  combo-never-armed bug). Swallow NO.
- `rl_yes` @ YES handler `0x4005e4c8` — `[PTN]`+`[YES]` with the picker open:
  close it (`FUN_40056bc0`), then PARTS/WHOLE → `rl_parts` = `FUN_4004aab4(0..3)`
  + the stock RELOAD PART UI refresh (`0x46c7c72c=1`, `FUN_4004d948(-1)`, +6
  redraw fns) here in the key handler; SEQ/WHOLE → arm `{G_KIND=1, G_PAT=active}`
  + post `FUN_40022778(1<<curbank)`. Toast (`FUN_4005a2b8`) + swallow YES.
- `rl_tick` @ `0x400522ca` (jsr detour, the DIRECT JUMP v2 per-control-frame
  splice — displaces `lea 0x46c7dfba,%a2`) — counts `G_TICKS` (`0x80006a54`)
  down; at 0 closes the picker + clears `G_MENU`. ~1.5 s (`0x1e0` frames).
- `rl_job` @ storage `0x14` case `0x40085864` — the SEQ worker (unchanged):
  open `bankNN.strd` (28 KB of the loader's buffer) → 22-B header → verWord =
  `hdr[0x14..0x15]` → `FUN_4008cebc` ×(P+1) into `SCRATCH` (`0x460aff60`) →
  `FUN_40020898` SCRATCH→live slab → `0x46c8028a` if P active → rejoin
  `0x400858a8` (`d0=-12` on ENOENT → stock "never saved"). `0x460fab5c`
  saved/restored via a cave word. Inert unless `G_KIND==1`; latches+clears it
  on entry so a real RELOAD BANK is unaffected.

**emu validation (`tools/emu_reload.py`):**
- `--slice` **ALL GOOD** (Session 42 earlier) — the slab-copy + `0x46c8028a`
  seamless-revert mechanism, bystander patterns untouched, transport running.
- `--strd` — the async `FUN_40022778` → `FUN_4008445c` → deserialiser path runs
  end to end (whole-bank stock path; kept as a sanity check).
- **`--combo` — the whole picker PASSES.** Single-steps `rl_combo` + `rl_yes` in
  isolation (gates forced, no scheduler, firmware fns stubbed): `[PTN]`+`[NO]` ×4
  opens then cycles `G_SEL` 0→1→2→0 (`FUN_4005a0e0` shown each time, `PTN_USED`
  set); `[PTN]`+`[YES]` per selection — SEQ → close + `G_KIND=1` + `G_PAT`=active
  + `FUN_40022778` posted, no `FUN_4004aab4`; PARTS → close + `FUN_4004aab4` ×4,
  no post, `G_KIND` stays 0; WHOLE → close + `FUN_4004aab4` ×4 AND arm + post.
  `[PTN]` released → falls to stock `[NO]`. Every branch correct.
- **`--patched` — the FULL SEQ worker PASSES end to end.** Boots
  `mainos_reload.bin`, loads the DEMO, forces `RUNNING` (harness doesn't start
  the transport on the patched image), scribbles pattern 0 (target) + pattern 10
  (bystander) in both the blob and the live copy, sets `G_MENU=1`/`G_SEL=0` and
  drives `rl_yes(0x31, press)` (the way `[PTN]`+`[YES]` on SEQ does), drains the
  storage task. The chain runs: `rl_yes` → post → `rl_job` → `FUN_40016864` open
  `bank01.strd` → **exactly one** `FUN_4008cebc` (P=0) → `FUN_40020898` into the
  live slab → `0x46c8028a` → rejoin `0x400858a8`. Result: **no fault**;
  `G_KIND` armed then cleared; **pattern 0's p-lock array == `bank01.strd`
  byte-for-byte**; **pattern 10 untouched** (a write-hook caught only the *stock*
  deserialiser's PCs `0x4009abca..` — the worker writes `SCRATCH` + pattern 0's
  slab, no overlap); `0x46c8028a` fired and was consumed; transport still `1`.
  (The stock whole-bank deser that reverts everything in a long drain is the
  emu's 10 MB initial load finishing — NOT `[PTN]`+`[NO]`, which never posts a
  type-6 job; the test halts it on entry so the worker is seen in isolation.)
- **Hardware-only from here:** `FUN_4008cebc` against a real CF card; the discard
  loop for P > 0; `FUN_4004aab4` + the 7 UI-refresh fns from the YES key handler
  (stock context, but our call site is new); the `FUN_4005a0e0` picker render +
  `rl_tick` auto-close; toast + reload timing.

**Bugs found + fixed this session:** the scratch-bank design (retracted — put a
bystander bank's data at risk, user caught it); a fabricated "~0.01% torn-read
odds" (retracted); `tst.b` on the big-endian LONGWORD transport state
`0x800065b8` (→ `tst.l`); a cargo-culted `NO_DISABLE` gate (dropped).

**Where it stands:** **the full feature is built** — `patch_reload.s` v3
(SEQ + PARTS + WHOLE + the 3-way picker), `OCTATRACK_OS1.40C_RELOAD.{syx,bin}`
952 B vs stock, Bug-1 fix byte-identical. **SEQ DATA + the picker are
emu-validated end to end** (`--combo` + `--patched`); `FUN_4004aab4` (the PARTS
path) is the stock RELOAD PART. Flash-ready — same posture as DIRECT JUMP
(emu-clean, HW pass pending). FLASHING.md §4.7 has the HW procedure. HW risk:
a storage-task hang needing a power cycle (recoverable, flash stock to revert);
SEQ writes only pattern N's live slab, never disk; PARTS is the stock path.
Queue: behind DT / SIDECHAIN2 / SIDECHAIN3 / DIRECTJUMP (all also unflashed).

## Session 43 (2026-09-09, `wip/mute-mode`) — RELOAD FROM PROJECT: a scaled-down 2-option sibling build + a stay-open modal picker UX for BOTH builds

Two things this session, both on top of Session 42's built-but-unflashed RELOAD.

### Part 1 — the scaled-down sibling (`build_reload2.py`)

User wants a **smaller** RELOAD as a **separate build**. Session 42's
`patch_reload.s` / `build_reload.py` stay — a new triple was added:

- **`tools/patch_reload2.s`** — 2-item picker: **`SEQ DATA`** / **`PART + SEQ DATA`**.
  * `SEQ DATA` — byte-identical mechanism to `patch_reload.s`'s `SEQ` (`rl_job` /
    `rl_openstrd` copied verbatim: async worker parses one pattern from
    `bankNN.strd` → live slab → `0x46c8028a`).
  * `PART + SEQ DATA` — `SEQ DATA` + `rl_part`: `move.b 0x80000003,%d2` then
    `FUN_4004aab4(d2)` **once**. `0x80000003` = the Part the sounding pattern is
    assigned to (octakit-abi `GK_STOCK_CURRENT_PART_MIRROR`). Confirmed:
    `FUN_400905d4 @ 0x400907b8` passes `[0x80000003]` as the *part* arg to
    `FUN_40009094(bank, part)`; `FUN_4004aab4` compares `[0x80000003]` to decide
    "re-apply to engine" (so it re-applies live). **`0x80000002` = current
    BANK**, not "active part" — `reference/upstream-notes.md` L26/L150 mislabel
    it; octakit-abi is right.
  * Dropped vs `patch_reload.s`: `ALL PARTS` (the `FUN_4004aab4(0..3)` loop) and
    the "PARTS only → skip the SEQ post" branch.
- **`tools/build_reload2.py`** — clone of `build_reload.py`; → `out/mainos_reload2.bin`,
  `OCTATRACK_OS1.40C_RELOAD2.{syx,bin}` `140C_KYOTI`.
- **`tools/emu_reload2.py`** — thin shim over `emu_reload.py`: repoints the
  image/elf and overrides `COMBO_ITEMS` (2 items). `emu_reload.py` gained a
  module-level `COMBO_ITEMS` table so its `cmd_combo` is data-driven.

### Part 2 — stay-open modal picker (patch_reload.s AND patch_reload2.s)

Session 42's picker required holding `[PTN]` the whole time and tapping `[NO]`
to cycle. New UX (user's spec):

    [PTN]+[NO]  opens the window; release [PTN], it stays open.
    arrows      move the highlight (UP/RIGHT = prev, DOWN/LEFT = next, wrapping).
    [YES]       execute the highlight + close.
    [NO]        close, execute nothing.
    While the window is open [YES]/[NO] act ONLY on the picker (rl_yes/rl_no
    fully swallow the key — the stock handlers never run).  Other keys are not
    intercepted.  ~10 s no-input auto-close (rl_tick, re-armed on each arrow) is
    a walk-away safety.

Both builds now use **6 detours** (was 4): `rl_no` @ `0x4005e25c`, `rl_yes` @
`0x4005e4c8`, **`rl_arr_a` @ `0x4004b970`**, **`rl_arr_b` @ `0x400491a0`**,
`rl_tick` @ `0x400522ca`, `rl_job` @ `0x40085864`.

- **Arrow-key RE** (folded into `kb/memory-map.md`): the 26-byte keymap tables
  (T1 `0x400bfc10`, T2 `0x400c01f4`; selector structs `0x400c090c` / `0x400c0920`
  chosen by `0x46c8d18c` in the event loop `FUN_40061b60` @ `0x40061bca`) map
  **`0x34` (UP) / `0x21` (RIGHT) → `0x4004b970`** and **`0x33` (DOWN) / `0x20`
  (LEFT) → `0x400491a0`** (the DOWN/LEFT wrapper falls to `0x40049114`; cursor
  `0x460d16e4`, scroll `0x460d16e8`). Consistent with octabam MAINMENU.md §7
  (HW-tested: "0x34 the UP arrow moves up, 0x33 moves down").
- **Arrow detour shape:** `tst.b G_MENU` — closed → replay the displaced
  prologue (`lea -12(sp),sp ; movem.l d2-d3/a2,(sp)` for A, resume `0x4004b978`;
  `move.l d2,-(sp) ; movea.l 8(sp),a0` for B, resume `0x400491a6`) and fall
  through, behaviourally invisible; open → `G_SEL = (G_SEL ± 1) mod N_ITEMS`,
  `jsr rl_draw`, `rts` (swallow, stack untouched on entry). New `rl_draw`
  subroutine = the `FUN_4005a0e0` redraw + `G_TICKS` re-arm, shared by `rl_no`
  and both arrows.
- **`rl_yes`:** drops the `tst.l PTN_HELD` gate; tests **`G_MENU` first** so a
  merged DJ+RELOAD build routes window-open → RELOAD execute, window-closed →
  (PTN held) DJ toggle. The DJ toggle will also need a `tst.b G_MENU / bne
  stock` guard. Also dropped the trailing `PTN_USED = 1` (PTN is long released
  by [YES] time).
- **`rl_no`:** press with `G_MENU==1` → close (`FUN_40056bc0`), execute nothing,
  swallow. Press with `G_MENU==0` + [PTN] held + gates → open. Else stock.
- `MENU_FRAMES` `0x1e0` → `0xc80` (~10 s).

### emu

- **`emu_reload.py --combo` (3-item) ALL GOOD** — open; arrow B cycles
  0→1→2→0→1, arrow A from 0 wraps to 2, each redraws; arrows fall through
  cleanly when closed; `[YES]` per item (SEQ post-only / PARTS ×4-only / WHOLE
  both); `[NO]` cancels (no post, no `FUN_4004aab4`); `[YES]`/`[NO]` closed →
  stock.
- **`emu_reload2.py --combo` (2-item) ALL GOOD** — same, cycling 0↔1.
- **`emu_reload.py --patched` + `emu_reload2.py --patched` ALL GOOD** — SEQ
  worker end to end for both: `rl_yes` (G_MENU=1) → post → `rl_job` → open
  `bank01.strd` → one `FUN_4008cebc` (P=0) → slab memcpy → `0x46c8028a` fired +
  consumed; no fault; pattern 0's p-lock array == `bank01.strd`; bystander
  pattern 10 untouched; transport still `1`. (`cmd_patched`'s stale
  `PTN_USED == 1` assertion relaxed to `[YES] armed the SEQ job` — `rl_yes` no
  longer sets `PTN_USED`.)

### HW-only (adds to Session 42's list)

Whether an arrow press reaches `rl_arr_a`/`rl_arr_b` while the `FUN_4005a0e0`
popup is up (base-view arrow routing). If not, the fallback is a hook in the
event dispatcher `FUN_40061b60` (78-way jump table at `0x40061cfa`). Also: the
`FUN_4005a0e0` picker render, the `PART + SEQ DATA` column width, toast/timing,
`FUN_4008cebc` vs a real card, the discard loop P > 0.

Docs: `patch_reload{,2}.s` / `build_reload{,2}.py` / `emu_reload{,2}.py` headers,
`kb/memory-map.md` (arrow keycodes), `README.md`, `BUILD_KYOTI.md`,
`FLASHING.md` §4.7, `START_HERE.md`. First-attempt in-place scaled-down edit was
reverted (`git stash@{0}`). **NOT committed, NOT pushed** as of session end.

## Session 44 (2026-09-09, `wip/mute-mode`) — RELOAD FROM PROJECT: OT-native UX (hold [PTN], no timeout)

Session 43's picker was a hybrid — a menu (arrow nav, sticky) wearing a transient
overlay's clothes (10 s silent auto-close), entered by `[PTN]`+`[NO]`, which
collides with the reflex "cancel SELECT PATTERN" gesture. Reworked both builds
(`patch_reload.s` 3-item, `patch_reload2.s` 2-item) to match stock idioms.

### RE — the [PTN] key handler `FUN_4005a044(keycode@4, event@8)`

Disassembled (`0x4005a044`): event **1** = press (sets `0x460d1742=1` "held",
clears `0x460d173e`), event **0** = release (opens SELECT PATTERN via
`FUN_40059f8c` **unless `0x460d173e != 0`**), event **2** = HOLD (stock does
almost nothing — `0x460d1ab2 = 1` then `jmp 0x40027de4`). **So the OS delivers a
hold event to PTN** — the same mechanism `[PAGE]`-hold uses; the threshold is the
OS's own. Tail is the clipboard reset `0x40027de4`.

### The change

- **Entry: hold `[PTN]`.** New detour `rl_ptn` @ `0x4005a044` (displaces
  `202f0008 7201`). On `event==2` + gates (`G_MENU==0`, no popup `0x460e5cd0`,
  no arranger `0x460d1aec`, `RUNNING`, `G_KIND==0`): open the picker, set
  `0x460d173e=1` so the release doesn't also pop SELECT PATTERN, then
  `jmp 0x4005a0d2` (stock hold tail — keeps `0x460d1ab2=1` + the clipboard reset).
  Non-hold / gated-out: replay `moveq #1,d1` and `jmp 0x4005a04a`. **A quick
  `[PTN]` tap is byte-for-byte stock.**
- **No timeout.** Deleted `rl_tick` (the `jsr` splice at `0x400522ca` *inside*
  the per-control-frame handler `0x40052200`, which displaced `lea 0x46c7dfba,a2`
  — the SOFT-MUTE release-watchdog var, a latent coupling). Deleted `G_TICKS`,
  `MENU_FRAMES`, `TICK_ORIG`. `rl_draw` no longer arms a countdown; `rl_no` /
  `rl_yes` no longer clear one. The window is a sticky menu — `[YES]` executes,
  `[NO]` cancels, nothing else closes it. Matches every stock OS menu.
- **`rl_no` simplified** — lost its entire open path (that's `rl_ptn` now); it's
  just "window open + `[NO]` press → close, swallow; else stock."
- **DJ decoupled.** RELOAD no longer touches `[PTN]`+`[YES]`. `rl_yes` only acts
  while `G_MENU==1`; DIRECT JUMP's `[PTN]`+`[YES]` is free of it. (A merged build
  still wants a `tst.b G_MENU / bne stock` guard on the DJ toggle for a stray
  `[YES]` with the RELOAD window open.)

Detour count still 6 each, but `rl_tick` (hot-path splice + softmute var) →
`rl_ptn` (cold key handler). Caves shrank: `reload` 1294→1226 B, `reload2`
1270→1202 B.

### emu (`tools/emu_reload.py` / `emu_reload2.py`)

`cmd_combo` rewritten to drive `rl_ptn(0x2e, 2)` for the open; new cases:
- **`--combo` (3-item + 2-item) ALL GOOD** — hold `[PTN]` opens (end
  `PTN_HOLDTAIL(stock)`, `G_MENU=1`, `POPUP2` shown, `PTN_USED=1`); **quick tap
  (`event 1`) → `PTN_RESUME(stock)`, window not opened**; **hold while stopped →
  gated out, `G_MENU` stays 0**; arrows wrap + redraw; arrows fall through clean
  when closed; `[YES]` per item (SEQ post-only / PARTS ×4-only / WHOLE both);
  `[NO]` cancels; `[YES]`/`[NO]` closed → stock.
- **`--patched` (both) ALL GOOD** — the SEQ worker end to end on the built image:
  `rl_yes` → post → `rl_job` → open `bank01.strd` → one `FUN_4008cebc` → slab
  memcpy → `0x46c8028a` fired + consumed; no fault; pattern 0's p-lock array ==
  `bank01.strd`; bystander pattern 10 untouched; transport still running.
- `--slice` / `--strd` exercise the *unchanged* worker mechanism (slab-copy +
  async job) — not re-run in anger this session; the worker code is cosmetic-only
  diffs from Session 43 and `--patched` drives the same path.

### HW-only (adds to Session 42/43's list)

- the OS hold-event threshold + feel for `[PTN]` (same as `[PAGE]`-hold);
- a quick `[PTN]` tap still opens SELECT PATTERN;
- whether an arrow reaches `rl_arr_a/b` while the `FUN_4005a0e0` popup is up
  (fallback: hook the event dispatcher `FUN_40061b60`);
- that `FUN_4005a044` is *only* the PTN key handler.

### Open (unchanged from Session 43): the two-build split

`patch_reload.s` (493 B) and `patch_reload2.s` (495 B) still differ by ~94 lines
(N_ITEMS, one `FUN_4004aab4` loop vs one call, menu strings) for ~24 B of cave.
A genuinely minimal RELOAD would be SEQ-only, hold `[PTN]` → one confirm, no
picker (~2 detours). Decide whether to keep both, keep only the 3-item, or add a
no-picker minimal. Not done this session.

## Session 45 (2026-09-09, `wip/mute-mode`) — merge-conflict audit + a mechanized combined build (no-flash)

Goal: does every *final-scoped* mod compose into one firmware? Audited each scoped
build (`RELOAD2` not `RELOAD`, `SIDECHAIN3` not `1`/`2`, DIRECT JUMP **v1**) —
actual bytes, caves, detour sites, shared globals, DSP. Then mechanized the merge so
it's a guarded build, not a hand-splice. **Reference: `reference/MERGE.md`** (the
authoritative allocation map — keep it current).

### Findings

**One real code collision, one mechanical cave clash, everything else composes.**

1. **`[YES]` handler `0x4005e4c8`** — DIRECT JUMP (`dj_toggle`, `[PTN]`+`[YES]`
   toggle) *and* RELOAD2 (`rl_yes`, answers the picker) detour the identical 8 bytes
   (`222f0004202f0008`). One `jmp` fits. Both source files already anticipate this
   (patch_reload2.s header "MERGE NOTE"; `rl_yes` routes "not the picker" through
   `jmp YES_RESUME`).
2. **Cave base `0x400d7400`** — MUTE MODE, DIRECT JUMP, RELOAD2 each `-Ttext` there.
   Mechanical; relocate.
3. **Space** — sum of the five caves + trigscale = ~2600 B into the 3132 B free zone
   `0x400d7000–0x400d7c3c`. Fits, **~526 B** headroom after packing.
4. **SIDE-CHAIN is ~orthogonal** — its DSP work is a different address space; its
   ColdFire footprint is the COMPRESSOR descriptor (`0x400d5ac8+`) + FX choosers
   (`0x400d607e+`), regions no other mod reads or writes. Only shared point:
   `patch_trigscale`, byte-identical everywhere.
5. **Compatible shared state** — MUTE MODE `0x800000dc`/shadow `0x100fff6c` vs DIRECT
   JUMP `0x800000d8`/`0x100fff68` (distinct, both need `pea 0x64→0x70`, idempotent);
   scratch globals `0x80006c66` / `0x80006a40–44` / `0x80006a50–53` disjoint; both
   MUTE MODE and DIRECT JUMP re-checksum the ANDY block (sequential, no race).
6. **DIRECT JUMP v1, not v2** — v2's `dj_tick2` splices `0x400522ca` (soft-mute
   release-watchdog fn) and shares `FUN_4005a0e0` + handle `0x460d1e64` with RELOAD2's
   picker. v1 avoids both.

### The `[YES]` trampoline

RELOAD2 is the outer hook; `rl_yes`'s "not the picker" path chains to `dj_toggle`,
which handles the combo or replays the prologue → `0x4005e4d0`.
`patch_reload2.s` gained an `.ifdef MERGE` block: standalone `rly_stock` replays +
`jmp YES_RESUME`; `--defsym MERGE=1 --defsym MERGE_DJ_TOGGLE=<addr>` makes it one
`jmp DJ_TOGGLE`. **`patch_directjump.s` unchanged** (`dj_toggle` sees the same stack
whether entered from a detour or from `rl_yes`). Standalone `build_reload2.py` output
is **byte-identical** with the guard inert (asserted).

### New tooling

- **`tools/build_merged.py`** → `out/OCTATRACK_OS1.40C_KYOTI_ALL.{syx,bin}`
  (`140C_KYOTI`, 3525 B vs stock). Auto-packs the ColdFire caves from `0x400d7000`
  (`patch_trigscale` pinned at `0x400d7b00`), wires all 12 detours (single `[YES]`
  hook), relocates the PERSONALIZE menu, runs `build_sidechain3`'s DSP + descriptor
  transforms verbatim (imports it as a module). Asserts: caves disjoint + in-zone;
  every displaced-byte guard; no detour-site collision; Bug-1 bytes identical to
  `build_trigscale_only.py`; every change is one a standalone feature also makes bar
  relocations; round-trip + checksum. SIDE-CHAIN DSP/descriptor bytes verified
  byte-identical to `build_sidechain3.py` (payload A+B 658 each, descriptor 40,
  choosers 36).
- **`tools/emu_merged.py`** — STATIC (every detour landed as the right branch into the
  relocated cave; `0x4005e4c8`→`rl_yes`; `rl_yes` contains `jmp dj_toggle`; pea 0x70;
  count `#16`; `KEY` at descriptor slot 8; caves disjoint) + DYNAMIC (drives `[YES]`
  at `0x4005e4c8` on the real merged bytes; verdict by which OS routine the trampoline
  reaches first — `CLOSE_CB`→RELOAD2, `CKSUM`→DIRECT JUMP, `YES_RESUME`→stock). All 6
  cases **ALL GOOD**: picker-open→RELOAD (even with `[PTN]` held); closed+`[PTN]`→DJ;
  closed/release/popup→stock.

### Not done / HW-only

- Combined image **not flashed** — flash the per-feature builds first (order in
  `START_HERE.md` §"Blocker & NEXT"), then this, then re-run every feature's checklist
  on the merged image + the `[PTN]` tap-vs-hold split + MUTE MODE with the picker open.
- Per-feature `emu_*.py` still run against standalone images (hardcoded `0x400d7400`
  cave asserts) — not adapted to the merged layout; `emu_merged.py` covers the
  merge-specific risk instead.
- `MERGE` block lives in `patch_reload2.s` only. If the 3-item `patch_reload.s` wins
  the Session-43 split decision, port the same `rly_stock` edit there.

Committed `75739ad` (`patch_reload2.s` MERGE block, `build_merged.py`, `emu_merged.py`,
`MERGE.md`, NOTES/START_HERE). NOT pushed.

### DIRECT JUMP v3 — the confirmation toast, done right (same session, commit follows)

**Why the countdown boxes were ever there:** they were never a DIRECT JUMP choice —
v1 (Session 15/21) reused `FUN_40059f8c`, the SELECT-BANK/PATTERN window, as the
cheapest way to show timed text, and the 4 draining boxes are what that routine
paints. At the time the only alternative was `FUN_4005a0e0` (bare box, but dead code
with no timeout → v2 bolted on the `dj_tick2` splice at `0x400522ca`). The proper
primitive — **`FUN_4005a2b8(text, dur)`**, the OS notification/toast (= ems-octakit
`GK_STOCK_NOTIFICATION_SHOW`, what stock uses for "PART n RELOADED") — was only found
during the RELOAD work, and `patch_reload2`'s `rl_yes` already uses it. Mnemonically
the boxes say "contemplate + commit"; wrong for a mode toggle already decided on.

**v3:** `patch_directjump.s` gained a third overlay branch under `.ifdef DJ_V3` —
`pea DJ_TOAST_DUR ; move.l %a0,-(sp) ; jsr 0x4005a2b8 ; addq #8,sp`. `DJ_TOAST_DUR`
default `0x44` (RELOAD2's dwell), `.ifndef`-overridable. No `dj_tick2`, no
`0x400522ca` hook, no window handle. Everything else (toggle logic, dj_a/b/c, ANDY
persistence) is v1's recipe verbatim.

- **`tools/build_directjump_v3.py`** → `out/OCTATRACK_OS1.40C_DIRECTJUMP_V3.{syx,bin}`
  (`140C_KYOTI`, 516 B vs stock; cave 490 B — smaller than v1's 498 / v2's 546).
  Asserts v3 touches **exactly** what v1 touches outside its own cave (0 stray),
  Bug-1 identical, round-trip + checksum OK.
- **`tools/emu_directjump_v3.py`** — `dj_toggle` OFF↔ON: `DJ_MODE` + shadow + re-cksum
  + `FUN_4005a2b8("DIRECT JUMP ON"/"OFF", 0x44)` + `PTN_USED` + YES swallowed; v1's
  `SHOW_MSG` and v2's `POPUP2` asserted **never reached**; PTN-not-held / release /
  arranger / popup → stock. dj_a/b/c asserted byte-identical to v1's stub. **ALL GOOD.**
- **`build_merged.py` now assembles `patch_directjump` with `DJ_V3=1`** — merged image
  3519 B vs stock (was 3525), `emu_merged.py` still ALL GOOD (the `[YES]` trampoline
  reaches `jsr CKSUM` before the toast, so the dynamic "DJ owns it" marker is
  unaffected).
- v1 (`build_directjump.py`) + v2 kept for the standalone line until v3 flashes.
  `emu_directjump.py` still covers dj_a/b/c (run after `build_directjump.py`).

## Session 46 (2026-09-09, `wip/mute-mode`) — QUANTIZE LIVE REC front-panel toggle: `[REC]` + double-`[PLAY]` (built, emu-clean, NOT flashed)

Surface the PERSONALIZE **QUANTIZE LIVE REC** row (the OT's all-or-nothing live-record
quantize — *not* the per-track 50% TRIG QUANT) to the panel, Digitone-style:
**hold `[REC]`, tap `[PLAY]` twice** to toggle, with a "QUANT LIVE REC ON / OFF"
toast that shows while `[REC]` is held and clears when it is released (**no timer** —
user's call).

### RE (against `out/raw/section_3_MAIN_OS.bin`, base `0x40000400`)

- **`QUANTIZE LIVE REC` = `0x800000ac`** (runtime word), PERSONALIZE menu **index 0**.
  Getter `0x40068ce0` (returns OFF-glyph `0x400b5e8e` / ON-glyph `0x400b5e90` — same
  checkbox glyphs Session 9 noted), setter `0x40068ca0`. **Plain boolean**, 0 = OFF.
- **Persistence is entirely stock.** `0x800000ac` is `+0x3c` inside the stock `0x64`
  `'ANDY'`-restore span (`0x80000070..0xd3`) → restored on boot with **no build
  change** (unlike MUTE MODE `0xdc` / DIRECT JUMP `0xd8`, which sit past `0xd3` and
  needed `pea 0x64→0x70`). The stock setter writes both `0x800000ac` and shadow
  `0x100fff3c` (= `0x100fff00 + 0xac − 0x70`), then the dispatcher re-checksums via
  `jmp 0x4001f23c @ 0x40069074`. Our toggle bypasses the dispatcher, so it mirrors the
  setter (write both words) **and** `jsr FUN_4001f23c` itself.
- **Panel PLAY/REC/STOP go through the 26-byte keymap, codes `0x28`/`0x29`/`0x27`** —
  *not* the `0x400d2d54[27..29]` jump table (that path is the MIDI/DIN "RECEIVE
  TRANSPORT" remote, gated on setting `0x80000029`; `0x4000a200`'s first insn is
  `tstb 0x80000029; beq rts`, and the `0x40001998` dispatcher only covers keycodes
  16–32). KB's hedge on that table was right. octabam's `emu_rtos` drives the remote
  path because its harness has `0x80000029` set.
  | key | keymap code | handler | notes |
  |---|---|---|---|
  | STOP | `0x27` | `0x4004aca4` | clears `0x460d172a` (live-rec) |
  | **PLAY** | `0x28` | `0x40061778` | press only (flags word `0` → no hold/repeat events) |
  | **REC** | `0x29` | `0x40048774` | press **and** release |
- **`0x460d1726` = "REC held"** (longword). Set to 1 at the end of *every* REC press
  (`0x40048830`), cleared on REC release (`0x4004883a: clr.l 0x460d1726; rts`). No
  other handler distinguishes it → a clean held-modifier flag. Also reachable as
  `is_key_held(code)` = `FUN_4003171c` → `*(u32*)(0x46c7d8ee + code*24)` (the runtime
  key-state table, base `0x46c7d8de`, stride 24, `+16` = held flag; populated for
  every keycode ≤ 63 by `set_key_state 0x40031734`, the sole per-key dispatcher, from
  the T1/T2 keymap). REC has no hold/repeat (`flags` = 0) so `0x40061778` fires once
  per physical PLAY press, event 1 only — the press counter is safe.
- **`0x40061778` (PLAY) already branches on `0x460d1726`**: REC held → start LIVE REC
  (`0x460d172a = 1`); not held → plain transport toggle. First insn is
  `jsr 0x4009b5c0` (the "project ready?" gate → "WAIT" toast). We detour that 6 B and
  resume the stock path at `0x4006177e`.
- **Persistent toast:** `FUN_4005a2b8(text, dur)` with **`dur = 0`** takes the
  `0x4005a334` branch → no auto-close countdown; handle in `0x460d1e70`. Close with
  **`0x40056bec()`** (no args, no-op if none open). (`dur > 0` = the self-timing
  "PART n RELOADED" path DIRECT JUMP v3 uses.)

### Design (2 detours, 1 cave @ `0x400d7400`, 200 B)

| Site | 6 B displaced | → |
|---|---|---|
| `0x40061778` | `jsr 0x4009b5c0` | `jmp qlr_play` |
| `0x4004883a` | `clr.l 0x460d1726` | `jmp qlr_recrel` |

`qlr_play`: REC not held → replay `jsr 0x4009b5c0` + `jmp 0x4006177e`. REC held →
`++G_CNT`; press 1 → stock (stock starts live rec — Digitone parity); even press
(2,4,…) → `0x800000ac ^= 1`, write shadow, `jsr FUN_4001f23c`, `FUN_4005a2b8(msg, 0)`,
set `G_OURS`, `rts` (swallow — transport untouched); odd press ≥ 3 → `rts` (swallow,
leave transport alone). `qlr_recrel`: `clr.l 0x460d1726` (displaced) + `clr.l G_CNT` +
if `G_OURS` → `jsr 0x40056bec` + `clr.b G_OURS`. Scratch: `G_CNT` `0x80006a5c` (long),
`G_OURS` `0x80006a60` (byte) — disjoint from MUTE MODE `0x80006c66` / DIRECT JUMP
`0x80006a40-44` / RELOAD2 `0x80006a50-53`.

### Tooling (`tools/`, committed)

- **`patch_qlrec.s`** — `qlr_play` + `qlr_recrel`, strings `"QUANT LIVE REC ON"` (17) /
  `"QUANT LIVE REC OFF"` (18) — kept ≤ 18 up front (`FUN_4005a2b8` window = `textpx+15`;
  the full "QUANTIZE LIVE REC OFF" at 21 ch overruns 128 px).
- **`build_qlrec.py`** — base = stock + Bug-1 fix (`patch_trigscale` @ `0x400d7b00`);
  `patch_qlrec` 194 B @ `0x400d7400`; 2 detours (guarded). Asserts `0x800000ac` is
  inside the stock restore span (no `pea 0x64` widen), Bug-1 bytes identical.
  → `out/OCTATRACK_OS1.40C_QLREC.{syx,bin}` (`140C_KYOTI`, 247 B vs stock).
  Round-trip + checksum OK.
- **`emu_qlrec.py`** — isolation-runs both cave routines on the assembled bytes (OS
  calls stubbed to `rts`): press-1 → stock; press-2 → flip 0→1 + shadow + cksum +
  `NOTIFY("…ON", 0)` + swallow; press-3 → swallow only; press-4 → flip 1→0 +
  `NOTIFY("…OFF")`; REC-not-held → stock resume; `qlr_recrel` clears both flags and
  closes the toast iff `G_OURS`. **ALL GOOD.**

### HW-verify (when the MKI is back) / open

1. **Toast width** — strings are `"QUANT LIVE REC ON/OFF"` (17/18 ch), chosen to fit
   (`FUN_4005a2b8` window = `textpx + 15`; the full "QUANTIZE LIVE REC OFF" at 21 ch
   overruns 128 px). Eyeball it on HW anyway.
2. **First `[REC]`+`[PLAY]` still starts live recording** (stock, intended). Confirm
   that feels right; the toggle gesture inherently enters live-rec.
3. **Odd presses ≥ 3 are swallowed** while `[REC]` stays held — so you can't stop
   live-rec with `[REC]`+`[PLAY]` again without releasing `[REC]` first. Confirm
   acceptable.
4. PLAY key has no auto-repeat (`flags` = 0) — verify no repeated press events under a
   long hold.
5. Persistence: toggle ON via the combo, power-cycle, PERSONALIZE row still checked;
   and toggling in the menu still reflects via the combo path.
6. **Merge:** not in `build_merged.py` yet. When added — no detour-site or ANDY-word
   collision (`0x800000ac` is stock, distinct from `0xd8`/`0xdc`); scratch words
   `0x80006a5c`/`0x60` need a `MERGE.md` row; cave packs like the others. The
   persistent-toast handle `0x460d1e70` is `FUN_4005a2b8`'s own (distinct from
   RELOAD2's picker `0x460d1e64` and DIRECT JUMP v3 which self-times) — but a stock
   "PART n RELOADED" up when you release `[REC]` would be closed early by
   `0x40056bec` (minor; `G_OURS` already gates it to the case where we opened one).

NOT flashed (user away from the MKI). Committed + **pushed** to `origin/wip/mute-mode`
(the same push carried the previously-unpushed Session 37/38/45 commits — the branch is
now in sync).


## Session 47 (2026-09-09, `wip/mute-mode`) — RELOAD2: per-track SEQ reload + faithful PART restore + renamed picker (built, emu-checked, NOT flashed)

**Confirmed to the user first:** RELOAD2's sequence reload IS a complete recall of
the pattern slab. `rl_job` runs `FUN_4008cebc` — the firmware's OWN per-pattern chunk
parser, the exact routine `FUN_4008ded0`/RELOAD BANK calls 16× — then memcpy's the
whole `0x8ed8` RAM slab (8 audio TRAC + 8 MIDI MTRA + trailer). Everything comes back:
regular trigs, the three trig-type layers (trigless/one-shot + the trigless-lock bit),
recorder trigs REC1/2/3, swing/slide, micro-timing (`+0x49` + aux `+0x862`), trig
conditions, per-track step count (`+0x59`), the full 64×32 p-lock array (`+0x62`),
MIDI trigs+locks, pattern length/scale (`slab+0x8e52/54`), part link (`slab+0x8e57`).
Source = `bankNN.strd` (last SAVE BANK / SAVE PROJECT). Emu-validated end to end
(`emu_reload2.py --patched`); the `#2` working p-lock view rebuilds from `#1` as the
playhead sweeps (S38), seamless.

### The build (this session)

**RAM slab geometry pinned** (from `FUN_4009a670`, the load-time bounds clamp — walks
8 audio tracks stride `0x91a`, then 8 MIDI stride `0x8b0`, then pattern fields;
`NOTES.md` L1067): audio track *t* at `slab + t*0x91a` (len `0x91a`); MIDI track *t* at
`slab + 0x48d0 + t*0x8b0` (len `0x8b0`, `0x48d0 = 8*0x91a`); part link `slab+0x8e57`
(1 byte, in the trailer past both track regions). `8*0x91a + 8*0x8b0 = 0x8e50` = where
the pattern fields start — exact. No emu dump needed; `emu_reload2.py --trk` re-checks it.

**`patch_reload2.s` — 3-item picker, window opens on TRK SEQ (item 0, least
destructive; [PTN]-hold then [YES] is a complete gesture, no arrows):**

| item | `G_KIND` | `rl_job` action |
|---|---|---|
| `TRK SEQ` | 3 | memcpy ONLY the currently-addressed track's region (audio `t*0x91a` / MIDI `0x48d0+t*0x8b0`) out of the parsed slab. Track from `0x80000000`; audio-vs-MIDI from `0x80000012`. Nothing else moves — other 7 tracks, both track types, pattern length/scale, part link all untouched. |
| `PTN SEQ` | 1 | memcpy the whole `0x8ed8` slab, then **restore the live `slab+0x8e57` byte** — a sequence reload must not silently re-point the pattern at a different Part. |
| `PART + PTN SEQ` | 2 | memcpy the whole slab INCLUDING `slab+0x8e57` (assignment reverts to saved), then read it → `0x80000003` + `FUN_40009094(bank, savedPart)` ("apply a Part by event" — the parts-switch path, proven safe on the storage task by stock `FUN_400905d4`'s post-deserialise tail) + `RDRAW=1`. Part params come from that Part's live slot (= its saved state unless SAVE PART'd since — matches stock "reload part"). |

- New scratch: `G_TRK 0x80006a54` / `G_TMIDI 0x80006a55` (RELOAD2 range now `0x80006a50–55`).
- `rl_yes` item 0 → `rl_arm_trk` (factored out, reads the track globals, arms `G_KIND=3`,
  posts). Items 1/2 → `G_KIND = selection index` (1 or 2), post. Toast: `T<n> SEQ` /
  `MT<n> SEQ` (sprintf) for TRK SEQ, `PTN SEQ` / `PART + PTN SEQ` static otherwise.
- Detour sites, `.ifdef MERGE` trampoline, all 6 hooks: **unchanged**. `FUN_4004aab4`
  (old `rl_part`) + the 7 key-context UI-refresh fns: **removed** — the Part work moved
  to `rl_job` on the storage task.
- **Power move ([PTN] + [TRACK], not built — kept open):** the chord IS available —
  track keys are keycodes `0x10..0x17` (dispatch `0x40040250` → `FUN_40083ab4` mute) and
  NO stock handler reads the `[PTN]`-held flag `0x460d1742`. To add: detour the track-key
  handler, on `0x460d1742 != 0` set `0x80000000 = keycode-0x10`, `jsr rl_arm_trk`, set
  `0x460d173e = 1`, `rts` (swallow — don't mute). `rl_arm_trk` is the entry point.
  Needs its own displaced-byte guard + a HW check. Documented in the `.s` header.

**`patch_reload.s` (RELOAD, the 3-item build) — kept, minimally touched:** picker
strings renamed `PTN SEQ` / `ALL PARTS` / `PARTS + PTN SEQ`; `rl_job` now also masks
`slab+0x8e57` (kept byte-aligned with RELOAD2's PTN SEQ core). ALL PARTS / WHOLE logic
unchanged (still the `FUN_4004aab4(0..3)` loop in the key handler).

**`build_merged.py`:** RELOAD2's cave grew ~1194→~1494 B and pushed the PERSONALIZE menu
arrays past the pinned `patch_trigscale` @ `0x400d7b00`. Fix: the packer now places the
menu arrays (pure data, 204 B) *after* trigscale at `0x400d7b40` (254 B free there), so
the growing stub region stays clear of the pin. Merged image re-packs + re-verifies
clean ("changes outside {feature diffs, relocated caves, detours}: 0"). `reference/MERGE.md`
updated (cave table, scratch range, headroom ~220 B).

**emu — all three modes validated:**
- `emu_reload2.py --combo` **ALL GOOD** — picker opens on TRK SEQ, arrows wrap the 3
  items, `[YES]` per item arms `G_KIND` 3/1/2 + posts, `[NO]` cancels, closed → stock.
- `emu_reload2.py --patched` **ALL GOOD** (`PATCHED_GSEL=1` → PTN SEQ) — `rl_job` runs
  once, one `FUN_4008cebc`, pattern 0's p-lock array reverts == `bank01.strd` byte-for-byte,
  bystander pattern untouched, `G_KIND` cleared, transport running. Confirms the Part-link
  mask + the whole-pattern path.
- New `emu_reload.py cmd_trk` (`--trk`, patch_reload2 only): scribbles a p-lock-array
  window of every audio + MIDI track + the part-link byte of P and a bystander Q, arms
  **TRK SEQ track 3** via `call_as_main(rl_arm_trk)`, drains the worker, asserts **only
  audio track 3's window reverts to `bank01.strd`** and every other track / MIDI track /
  the part link / pattern Q stay scribbled. Runs `worker: rl_job=1 FUN_4008cebc=1 G_KIND
  cleared`; all ten content checks pass.
- **Harness notes:** (1) don't stub `sprintf` (`0x40013a08`) — `rl_openstrd` uses it and a
  bare-`rts` stub wedges the storage task. (2) arm via `rl_arm_trk` not the full `rl_yes` —
  `rl_yes`'s TRK SEQ path runs a real `sprintf` (the `T3 SEQ` toast) that opens a window
  where the posted worker starts *inside* `call_as_main` and the borrowed idle slot never
  returns to `MAIN_SPIN` (harness limit, not a firmware issue; the `rl_yes → rl_arm_trk`
  route is covered by `--combo`).

### HW-only (adds to Session 42/43/44's list)
- `FUN_4009a670`'s slab geometry vs a real card parse (audio `0x91a` / MIDI `0x48d0`+`0x8b0`).
- `FUN_40009094(bank, part)` from the storage task with the transport running (stock only
  does it post-stop or post-deserialise) — glitch? part LED / name refresh timing.
- PART + PTN SEQ when the reassigned Part *was* edited before reassigning: those edits
  ride along (we apply from the live slot, not a per-part `.strd` re-parse). Acceptable
  gap; documented. Stock PART → RELOAD or `patch_reload.s`'s ALL PARTS covers it.
- Which track a `[TRACK]` key press reaches while the `FUN_4005a0e0` popup is up (retarget
  while the picker is open) — same class as the arrow-key HW unknown.

NOT flashed. Committed + pushed to `origin/wip/mute-mode`.

## Session 48 (2026-09-10, `wip/mute-mode`) — STOCK BUG FIX: "pattern with only p-locks shows as empty" (built, emu-validated stock-repro + patched-fix, NOT flashed, NOT committed)
User bug report: a pattern whose only content is parameter locks on the **MIDI-track**
side shows as empty — grid LED unlit under `[PTN]`, slot looks unused. Adding any p-lock
on the audio side lights it.

### Root cause — `FUN_4009a464(pattern, bank)` = `GK_STOCK_PATTERN_HAS_CONTENT 0x4009a464`
The "does this pattern have content" predicate that gates the pattern-grid LED. 3 callers
load its address into a register: `0x4000fd7e` (inside `0x4000fd78` = "does this *bank*
have content", loops 16 patterns), `0x400354f6` (chain/─ view painter, enclosing fn
`0x400353d4`), `0x4007b1f4` (PTN-page painter, enclosing fn `0x4007afe8`). The two UI
painters: `has_content(pat,bank); tst.l d0; bne` → LED bit **set** via `0x400131a0(bit)`
(`buf[bit>>3] |= 1<<(bit&7)`, LED framebuffer `0x460ba98c`) / **clear** via
`0x400131c8(bit)`. Both painters are event-driven page-draw handlers (dirty-gated:
`0x460e73c6` / `0x100b14ce`+`0x100b14d0`), not audio-thread, not a per-frame timer.

`FUN_4009a464` walks 8 track slots (`a0` = `0x400e21e0` + off, stride `0x91a`;
`a1` = `0x400e6ab8` + off = `blob+0x48d8`, stride `0x8b0`; `off = bank*0x9b340 +
pat*0x8ed8` — blob base **hardcoded** `0x400e21e0`, not `[0x46c82456]`) and ORs a fixed
longword set:
- audio TRAC: block `+0x00..0x0f` **and** `+0x18..0x37` (skips `+0x10..0x17`) — trig masks
- MIDI  MTRA: block `+0x00..0x0f` only — trig masks
It never reads **either** side's p-lock array, so a pattern with locks but no trig ORs to
zero → returns 0 → LED cleared.

### RAM layout (confirmed: serialiser `~0x4008a740` loop 1/2 + initialiser `FUN_4009abdc`
two fill loops `0x4009ac30` audio / `0x4009ad56` MIDI + a live `emu_rtos` load)
- audio p-lock array: `blob + bank*0x9b340 + pat*0x8ed8 + trk*0x91a + 0x59`, `0x800` B
- MIDI  p-lock array: `blob + bank*0x9b340 + pat*0x8ed8 + 0x4900 + trk*0x8b0`, `0x800` B
- `0xFF` = "parameter not locked on this step" (initialiser byte-fills `0xFF`; deserialiser
  loads `0xFF` for an empty track). The empty MIDI block also carries `0xAA` micro-timing
  defaults at `blk+0x18..0x1f` and a `10 02 00 ff 00 00 00 01` param header at `blk+0x28`
  — **neither is in the p-lock array range**, so the fix's array scan is not tripped by them.

### Fix — `tools/patch_pattern_led.s` + `tools/build_pattern_led.py`
Detour `FUN_4009a464` entry (6 B: `2f02 202f 0008` → `jmp <cave>`) to a **142-byte
cave** (standalone `0x400d7000`; `0x400d64da–0x400d7c3c` free). Cave: replay the
prologue's `move.l d2,-(sp)`; compute the pattern's blob offset from the args; scan the
16 p-lock arrays (8 audio `blob+off+trk*0x91a+0x59` + 8 MIDI `blob+off+0x4900+trk*0x8b0`,
`0x800` B each) for a longword `!= 0xFFFFFFFF` via the `addq.l #1; bne` sentinel trick
(`0xFFFFFFFF+1 → 0`). A hit → pop d2, `moveq #1,d0`, `rts`. No hit → `move.l 8(sp),d0`
(the detour swallowed the stock arg load too) + `jmp 0x4009a46a` = the rest of the stock
function (its own trig scan + epilogue) runs unchanged. So every trig-bearing pattern is
byte-for-byte stock behaviour and a genuinely empty pattern (all 0xFF, no trig) still
returns 0. Also fixes the symmetric **audio trigless-lock-only** pattern (same path).
Worst case (16 genuinely-empty patterns) ≈ 16 × 16 KB longword scan per grid repaint ≈
low single-digit ms, once, on an event-driven UI repaint — acceptable.
(First cut replicated the whole trig scan → 296 B; shrunk to the "scan then fall
through to the stock body" shape above so it fits the merge's pre-`patch_trigscale` gap.)

### Validation — `tools/emu_pattern_led.py` (stock + `--patched`), full-firmware `emu_rtos`
Pattern 15 reset to genuine stock-empty via `call_as_main(FUN_4009abdc, blob+15*0x8ed8)`
before each probe (so "empty stays empty" is real, not a zero-fill artefact).

| case | STOCK | PATCHED |
|---|---|---|
| all 16 DEMO patterns | 1 | 1 (unchanged) |
| reset-empty pattern 15 | 0 | **0** (no false positive) |
| MIDI p-lock only (trk3 step10), no trig | **0 (bug)** | **1 (fixed)** |
| audio trigless-lock only (trk2 step6), no trig | **0 (bug)** | **1 (fixed)** |
| MIDI note trig present | 1 | 1 (stock fast path unchanged) |

`out/mainos_patternled.bin` 245 B vs stock; wrap `OCTATRACK_OS1.40C_PATTERNLED.{syx,bin}`
`140C` version unchanged (`1.40C`), container round-trips (`payload ok, checksum ok`).
Base = **stock 1.40C only** (no Bug-1 fix, no other Kyoti mods — standalone single fix).

### Merge — DONE (S48), and QUANTIZE LIVE REC (S46) folded in at the same time
`build_merged.py` now composes **seven** mods (added `patch_pattern_led` **and** `patch_qlrec`).
- **`FREE_START` lowered `0x400d7000` → `0x400d6500`** — Bug-2 + QLREC overflowed the old zone
  (was 26 B free after Bug-2 alone). The whole `0x400d64da–0x400d7c3c` span is zero in stock.
  Seven caves now occupy `0x400d6500–0x400d70aa`, ~2.6 KB free to the pinned `patch_trigscale`.
- **Consequence:** `patch_sidechain`'s cave no longer lands at `0x400d7000`, so the COMPRESSOR
  descriptor's per-slot formatter pointers (`E+0x102+4*slot`) differ from `build_sidechain3.py`.
  Their *values* are still asserted vs `sc_syms`; the stray-byte check (section 8) now exempts
  those 4-byte pointer slots (`for slot … if isinstance(fmt, str)`).
- `patch_qlrec`: generic `CF_STUBS` entry, no defsym, two `jmp` detours (`0x40061778` [PLAY]
  press, `0x4004883a` [REC] release), shares no global with the other six (`0x800000ac` is
  stock and already inside the `0x64` restore span → no `pea 0x64→0x70` needed).
- `emu_merged.py`: asserts the Bug-2 detour + `jmp 0x4009a46a` tail + both QLREC detours;
  cave-zone check now `0x400d6500..`. `emu_pattern_led.py --image out/mainos_merged.bin`
  re-runs the full Bug-2 set on the relocated cave — **ALL GOOD**. QLREC cave logic covered
  by `emu_qlrec.py` on the standalone (same bytes, re-linked). `emu_merged.py` **ALL GOOD**.
- `changes outside {feature diffs, caves, detours}: 0`, round-trip + checksum OK, Bug-1 bytes
  byte-identical. `OCTATRACK_OS1.40C_KYOTI_ALL.{syx,bin}` = `KYOTI_V1.0`, 4041 B vs stock.

### Docs
README.md ("Bug 2" section + a QUANTIZE LIVE REC section — the latter was **missing entirely**
— + HW-status rows), BUILD_KYOTI.md ("What you get" + HW-status rows for Bug-2 and QLREC),
`reference/MERGE.md` (now "seven final-scoped mods": cave table, detour inventory, shared-state
table, the `FREE_START`-lowered / descriptor-pointer-exemption notes). **QUANTIZE LIVE REC:
user confirmed it IS the PERSONALIZE `QUANTIZE LIVE REC` row** (a momentary "not a PERSONALIZE
toggle" was a miscommunication) — `patch_qlrec.s` / NOTES S46 "PERSONALIZE menu index 0" stands.

### Open / next
- **HW confirm on the MKI**: create a real MIDI-track p-lock with no note (trigless), select
  its bank on the PTN grid, LED should now light; power-cycle-safe (pure code, no state).
- Candidate for the **upstream "already-in-1.40C findings"** list (it's a stock bug, not a
  behaviour mod) — but MKI-only RE, so offer as a report, not a PR, unless mxldyn wants it.

Committed + pushed to `origin/wip/mute-mode`. NOT flashed.

## Session 49 (2026-09-10, `wip/mute-mode`) — SCOPING a new stock bug: "Part params carry over after a pattern→Part change" (static RE only; emu repro NOT yet run; NOT built)

### The reports (Elektronauts "Octatrack OS Bug Reports" / "Playback gets carried over…")
1. **Open_Mike** — switch from a pattern on Part A (track T = **PICKUP** machine, pickup NOT
   running) to a pattern on Part B (track T = **FLEX**, sample-locked, STARTS SILENT): the new
   pattern triggers **Part A's pickup loop** on track T instead of Part B's assigned sample.
   A second user reproduces and adds: **only when Part B's machine is FLEX** — a **STATIC**
   machine on track T works as intended. Workaround: have the pickup loop running (muted if
   needed) before switching. Open_Mike also: **scenes** of the new Part still respond to the
   **old** pattern/Part's scene values.
2. **Open_Mike** — recorder trigs: after a pattern→Part change the **recorder source + RLEN
   from the old Part** are used even when locked on the new pattern. Workaround: make every
   Part's recorder buffer N settings identical across Parts.
3. **sezare56** — REC SETUP: last-tweaked value persists. P1/PartA SRC=T1, P2/PartB SRC=T2;
   tweak P1 SRC→T8, switch to P2 → **P2 records T8**, not T2.

All three = one family: **a pattern change that links a different Part does not fully
re-apply / re-publish that Part's per-track state.** STATIC works because STATIC lives in a
different sample arena (`0x100d5b30+id*1096`) from FLEX/PICKUP (both `0x100b14f0+id*1096`,
`memory-map.md`) → a PICKUP→STATIC type change crosses arenas and forces a rebind; PICKUP→FLEX
stays in the same arena with a still-valid (stale) slot id = the pickup recording buffer
(`128+track`, forced by `FUN_400972fc`).

### What static RE established this session (objdump, base `0x40000400`)

- **`FUN_40009094(bank@a5, part@fp)` = the per-track Part→engine apply** (octakit
  `GK_STOCK_ENGINE_PART_LOAD`). Confirmed: reads the machine-type byte at
  **`blob + part*0x18b2 + track + 0x8eda2`** (= part payload `+0x22 + track`; signed byte
  `mvsb`, `sp@84` walks +1/track), then copies machine-type-selected param groups
  (`mt*6`-indexed) into the per-voice DSP pre-image `0x80000a50+track*64` / records
  `0x80000110` / `0x8000082f`. Stores bank→`0x80001828`, part→`0x80001829`. It does **not**
  touch the voice struct `0x800049d8+track*0xA8` (SETTINGS ptr / slice / play position).
- **`FUN_400972fc(part@d5, track@d4)` = the PICKUP-only voice rebind.** Bails immediately if
  `blob+part*0x18b2+track+0x8eda2 != 4`. For a PICKUP track it forces the slot byte
  (`part payload +0x8f04e + …`) to `128+track` and sets the dirty set
  (`+0x9b332`, `0x100f8598`, `0x100b145e`, `0x9504a`), then `FUN_40027e00`.
- **The deferred change queue `0x460c80f0` (kind) + `0x460c80f4/f8/fc`, `0x460c8100/8104`
  (descriptor).** Enqueue/dequeue lives entirely in the `0x40025xxx–0x40026xxx` cluster
  (project/bank serializer + "apply pending change" drain; `FUN_40026664` = the
  match/filter). **Kind 5 → `FUN_4002b3b4`** = re-copy one TRAC block (cold blob → live
  `0x1001614e`, `0x91a` B) + `FUN_40029b9c(track)`. Called from the pattern path at
  `0x4005f002`. **Kind 4 → `FUN_4002b654`** = the Part apply: memcpy a batch of per-track
  Part sub-records (playback `+0x1da` 0x1e, slice-lock `+0x2ca` 5, amp `+0x2f2` 0x1e,
  twelve-byte `+0x602` 0xc, **recorder `+0x8f382 + part*6322 + track*12`, 0xc B**, plus
  30/24/5-byte records with a `-128` PICKUP adjust) cold blob ↔ live, then
  `FUN_40009094(0x80000002, part)`. So kind-4 **is** thorough on paper — incl. the recorder
  12-byte record.
- ⇒ The bug is most likely **(a) the pattern-triggered Part change never enqueues / drains a
  kind-4** (only manual PART select — `FUN_4004aab4` / the `0x4005exxx` PART UI — does), OR
  **(b) it enqueues but the drain lands after the recorder engine / voice has already latched
  the old value**, OR **(c)** for the pickup-loop case specifically, `FUN_40009094` +
  kind-4 don't re-resolve the FLEX voice's sample pointer when the machine *type* changed
  PICKUP→FLEX within the shared arena. The pickup-running workaround fits: an active pickup
  voice keeps `FUN_400972fc` / the plays-free PICKUP-sync auto-reload (`0x4000aea6`,
  `move.l #1,0x46c8028a`) firing, which forces the full reload.

### Repro plan (NOT yet run — needs either a real test project or an emu harness)

Emulator: `tools/emu_rtos.py` (octabam full-firmware). `emu_reload.py` already shows the
primitives — `er.stage_project` / `er.attach` / `rt.load_project_live` /
**`rt.seq_select_live(bank, pat)`** (drives a real pattern switch) / `rt.press_play_live` /
`rt.run(ms=)`.

Harness (`tools/emu_partswitch.py`, to write):
1. boot + load a project with **two patterns on two different Parts**, track T with a
   machine-type difference.
2. read machine types for all Parts from `blob + 0x8ed80 + part*0x18b2 + 0x22 + track`
   (blob = `PART_PTR`); read the live recorder record `0x80000cf4+track*12+[0x800000e0]*96`
   and the voice struct `0x800049d8+T*0xA8` (`+8` SETTINGS ptr, `+32` slice, `+8`→slot).
3. `seq_select_live` pattern A (Part A), `press_play_live`, run; snapshot the T voice +
   recorder record.
4. `seq_select_live` pattern B (Part B), run; **assert** the T voice SETTINGS ptr now
   resolves to Part B's FLEX slot (not `128+T`) and the recorder SRC/RLEN == Part B's.
5. control case: start a pickup voice on T first, then switch → expect it to work (matches
   the HW workaround).
6. also check whether a kind-4 (`0x460c80f0`) is ever enqueued across the switch
   (`--watch-mem 0x460c80f0,4`).

**Test data:** the factory **OT DEMO** links P1–4→Part0, P5–8→Part1, … (confirmed via
`scan_parts.py`), so P4→P5 is a real Part change — but it has no PICKUP/FLEX-on-same-track
difference and no divergent REC SETUP. Options: (i) **ask the user to export a purpose-built
project** from the MKI — 2 patterns, 2 Parts, T1 = PICKUP in Part A / FLEX+assigned sample
(STARTS SILENT) in Part B, and REC SETUP SRC differing between the Parts; or (ii) RAM-poke the
machine-type + slot bytes in `emu_rtos` (Session-48 precedent) on top of the DEMO. (i) is the
faithful one and also lets the user confirm the HW repro on their own unit.

### Fix sketch (if repro confirms) — effort ≈ DIRECT JUMP (medium), risk moderate

Detour the sequencer's pattern-change commit (`FUN_400a1eea` @ `0x400a44d0`, or the cue
choke `FUN_400a0570`) so that when the incoming pattern's Part link
(`slab+0x8e57` / disk `+0x8ee7`) differs from the current Part (`0x80000003` / `0x80000002`),
it forces a synchronous full Part apply for the new Part — enqueue+drain a kind-4
(`FUN_4002b654`) and/or call `FUN_40009094(bank,newpart)` + re-publish the recorder record
(`0x80000cf4…` from `+0x8f382`) + re-apply scenes. Gate behind a PERSONALIZE/-chord toggle
per house style (this is a behaviour change on a stock code path; some users may rely on the
current "hold last tweak" for live performance). No menu-array surgery. HW-only unknowns:
`FUN_40009094` from the sequencer tick context; glitch on the active voice; scene re-apply
path (`FUN_400972fc` siblings / `0x4005a676` / `0x40062204`).

### Emu probe #1 (`tools/emu_partswitch.py --probe`, DEMO as-is) — the Part change DOES run per-track work; `FUN_40062204` / `FUN_400972fc` are it

- DEMO machine types: **every track is FLEX** (T8 = THRU/STATIC). No PICKUP anywhere → the
  PICKUP→FLEX case must be RAM-poked (chose option ii).
- `seq_select_live(bank, 4)` (P1→P5 = Part 0→1): the **applied-part witness `0x80001829`
  went 0→1** and **`FUN_400972fc(part=1, …)` ran ×8 (once per track), from `0x4006220a` in
  the `sys` task**. So a pattern-triggered Part change is NOT inert — my "root cause (a)"
  guess is wrong. (My `watch_calls` single-address hooks missed `FUN_40009094`/kind-4 —
  hook-flush quirk; `0x80001829` moving proves a Part apply ran. `watch_pc` used from probe
  #2 on.)
- **`sys` message case `0x400621a6–0x40062284` = THE part-change handler.** On msg-byte
  `!= 0x80000003` (current-part mirror `0x100b14cf`): memcpy the current Part's 8
  machine-type bytes to a local (`fp-9` = **OLD types**); set `0x80000003 = 0x100b14cf =
  newPart`; **loop t=0..7: `FUN_400972fc(newPart, t, OLD_type[t])`**; then `FUN_400326a0`,
  `FUN_40078850(0)`, and a redraw burst (`0x4004d948/d870/d640`, `0x4002f2f8`, `0x40093468`,
  `0x4009da20`, `0x40097460`). It does **not** call `FUN_40009094` or the kind-4 handler
  here — the Part-apply that moved `0x80001829` is elsewhere in the same dispatch (probe #2
  to pin).

### `FUN_400972fc(newPart@d5, track@d4, oldType@sp+32)` — the per-track rebind, and its asymmetry

Reads NEW machine type (`blob + newPart*0x18b2 + track + 0x8eda2`).
- **NEW == 4 (PICKUP):** force the PICKUP slot (`blob + newPart*0x18b2 + track*5 + 0x8f04e`)
  to `128+track`, mirror to `0x100a519c[newPart*6322 + track*5]`, set dirty
  (`+0x9b332`,`0x100f8598`,`0x100b145e`,`+0x9504a`), `FUN_40027e00`. Then if **OLD != 4**
  (was not PICKUP): `FUN_40097290(newPart)` + **`0x8000184c |= 1<<track`** (the AMP-kill /
  release bit, Session 9) + `FUN_40001f18([0x100b14ce],[0x100b14cf],track)`.
- **NEW != 4 (STATIC/FLEX/THRU/NEIGH):** branch to `0x400973e6` — clears the plays-free
  SEQ-SYNC-PICKUP track (`0x800065bc`) if it was this track, updates `0x461054f8`
  ("current track is PICKUP? / 8"), **`rts`**. **Nothing re-resolves the voice slot, no
  `0x8000184c` kill, no param push.** ⇒ **OLD=PICKUP → NEW=FLEX leaves the voice/slot
  pointing at the PICKUP recording buffer `128+track`.** The FLEX slot from the new Part is
  never bound to that voice.
- **Why STATIC is fine:** STATIC's sample arena (`0x100d5b30+id*1096`) ≠ FLEX/PICKUP's
  (`0x100b14f0+id*1096`); the per-audio-frame voice-SETTINGS re-resolver rebinds on the
  arena change. PICKUP→FLEX stays in the same arena with a still-valid stale slot id →
  no rebind → pickup buffer plays. (To confirm in probe #2.)

### Emu probe #2 (`tools/emu_partswitch.py --repro`) — ROOT CAUSE CONFIRMED for report #1

Poked DEMO **Part 0 T1 machine → 4 (PICKUP)** + its PICKUP slot (`blob+0x8f04e`) → `128`,
Part 1 T1 stays FLEX; `seq_select_live` P1→P5 (Part 0→1). `watch_pc` on `FUN_400972fc`,
watched the T1 voice struct + slot mirror `0x100a519c` + pre-image `0x80000a50` + kill
bitmap `0x8000184c` + `0x80001829`.

- **`FUN_400972fc(newPart=1, track=0, oldType=4)` fired** — the exact PICKUP→FLEX transition
  (args read straight off the stack: `[ret 0x4006220a, 1, 0, 4]`). Tracks 1–7 fired with
  `oldType` 1/2 (FLEX/THRU), as expected.
- **Across the whole switch, for track 0: ZERO state change.** No write to the slot mirror.
  No write to the pre-image. **`0x8000184c` (voice-kill / re-trigger bit) stayed `0`** — the
  reverse transition (notPICKUP→PICKUP) *does* set it; PICKUP→FLEX does not.
  `FUN_40009094` (the full per-track apply) never ran for track 0. The **only** write in the
  watched set was `0x80001829 <- 1` from `FUN_40009e00 @ 0x40009e16` (seq-select's light
  part setup — records bank/part + FX descriptors, does **not** rebind the playback voice).
- ⇒ **On a pattern change that moves a track PICKUP→FLEX, nothing rebinds that track's
  playback voice.** It keeps the PICKUP recording-buffer slot (`128+track`) → the FLEX
  track sounds the pickup loop. STATIC escapes only because its arena differs
  (`0x100d5b30` vs `0x100b14f0`) and the per-frame SETTINGS re-resolver rebinds on the
  arena change. "Pickup running before the switch" works because an active pickup voice
  keeps the plays-free PICKUP-sync full reload (`0x46c8028a`) firing.
- Harness caveat: `press_play_live` did **not** start the transport in this setup
  (`0x800065b8 == 0`), so the *voice itself* couldn't be watched resolving a wrong pointer
  — not needed for the mechanism, but fix it before the fix-validation run (probe the
  DEMO's CLOCK-RECEIVE / `0x80000029` / add `FW_START_TRACK`, or drive `press_key_live`
  for PLAY + a trig).

### Fix — one detour on `FUN_400972fc`, ~Session-48 scale

On **`oldType == 4 && newType != 4`** (currently the `bne 0x400973e6` fast-path that does
nothing), also: (a) write the new machine type's real slot for that track from the Part
payload (`blob + newPart*0x18b2 + track*5 + newType`; `newType` 0 STATIC / 1 FLEX) into the
slot mirror `0x100a519c[newPart*6322 + track*5]` and the live per-track record, and
(b) set `0x8000184c |= 1<<track` so the next trig re-resolves + re-triggers the voice from
the correct slot (exactly what the notPICKUP→PICKUP arm already does via
`FUN_40097290` + the OR). ~1 detour + small cave. Gate behind a toggle (it changes a stock
code path).

### Reports #2 / #3 — the recorder-page config pipeline, RE'd (static)

The recorder page (SETUP RECORDING: `page1 INAB INCD RLEN TRIG SRC3 LOOP`, `page2 FIN FOUT
AB QREC QPL CD`) travels **editor → cache → per-frame publish → engine**:

| tier | address | writer |
|---|---|---|
| blob (persisted Part copy) | `blob + part*0x18b2 + 0x8f382 + track*12` | knob editor `FUN_4002ef28 @ 0x4002f03a`; kind-4 copies it in |
| SRAM mirror | `0x100a54d0 + track*12` | knob editor `@ 0x4002f042` |
| **UI cache** | **`0x80000c94 + track*12`** (8×12 B) | knob editor `@ 0x4002f0ca`; **`FUN_40009094 @ 0x40009176`**; RELOAD-PART `FUN_40009848 @ 0x40009928`; boot `0x40001f6e` |
| **published (engine reads this)** | **`0x80000cf4 + track*12 + [0x800000e0]*96`** | **the frame-builder, every DSP frame**: `0x4000cac2` `memcpy(0x80000cf4 + frame*96, 0x80000c94, 96)` (all 8 tracks, 96 B) |

Engine read sites: `FUN_40005ff0` / the `0x40006cc0` fn (recorder arm/trigger — read `pub[+7]`
→ `0x400ab63a` RLEN→block table → `macl` sample math) and `0x4006e3b2` (`lea 0x80000cf4`,
`pub[+2 + …]`).

**The gap:** the per-frame copier faithfully ships whatever is in the UI cache `0x80000c94`.
The cache is refreshed from a Part's blob record **only by `FUN_40009094` / `FUN_40009848`**
(the full manual PART apply / RELOAD PART) — **never by the pattern-triggered Part change**
(`sys` `0x400621a6`: `FUN_400972fc`×8 + `FUN_40078850(0)` display-only + redraws; probe #2
pinned the applied-part write to `FUN_40009e00 @ 0x40009e16`, and `FUN_40009e00` is **not**
in the `0x80000c94` writer set). ⇒ after a pattern→Part change the recorder engine keeps
the previous Part's recorder config, and any REC-SETUP tweak made before the change (which
wrote the cache directly) sticks — **exactly reports #2 (SRC/RLEN) and #3 (last-tweak
persists)**. Same family as #1: the pattern-change path is a partial re-apply.

### Fix for #2 / #3

Add to the same `FUN_400972fc` detour (or a single hook at the `sys` handler's post-loop
point `~0x40062216`): for each track, `memcpy(0x80000c94 + track*12, blob + newPart*0x18b2 +
0x8f382 + track*12, 12)` — re-seed the UI cache from the new Part's stored recorder record;
the frame-builder then publishes it next frame. Also refresh the SRAM mirror `0x100a54d0`
for consistency. (Matches what `FUN_40009094` already does — could instead lift/reuse just
that fn's recorder sub-copy.) Note: page 2 of the recorder page may live at a different cache
offset — verify the 12-B record covers both pages before shipping.

### Emu probe #3 (`--repro`, recorder rows) — #2 / #3 ALSO CONFIRMED

Poked Part 0 rec-blob `= 40..4b`, Part 1 rec-blob `= 60..6b`, stamped the UI cache
`0x80000c94[T] = AA*12` ("just tweaked"), switched P1→P5.
- Before: cache `AA*12`, published `0x80000cf4[T] = AA*12` (frame-builder shipped the
  marker faithfully).
- **After the Part change: cache still `AA*12`, published still `AA*12`, SRAM mirror
  unchanged, both blob records unchanged.** The `AA` marker survived the entire Part
  change — **nothing re-seeded the recorder cache from Part 1's stored record `60..6b`.**
- The only write in the whole watched set (incl. both blob records, cache, SRAM):
  `0x80001829 <- 1` from `FUN_40009e00`. **Zero recorder writes on the switch.**
⇒ reports #2 and #3 confirmed: the pattern-triggered Part change leaves the recorder-page
config (SRC/RLEN/…) at whatever the cache held — the previous Part's values, or a
pre-switch REC-SETUP tweak.

### Scene aspect (Open_Mike's aside) — RE'd, it's a real gap

There are two `sys` pattern/Part dispatch cases:
- **`0x400620fe`** — "select pattern N": derives the Part from the pattern link
  (`blob + pat*0x8ed8 + 0x8e56 → +1` = slab `+0x8e57`), sets `0x80000003` / `0x100b14cf`,
  runs a redraw burst (`0x4002e5ac`, `0x400339d8` LED rebuild, `0x4004d***`, …). **No
  `FUN_400972fc`, no recorder refresh, no scene morph.**
- **`0x400621a6`** — "select Part P": memcpy old machine types → local, set `0x80000003`,
  loop `FUN_400972fc(newPart, track, OLD_type)` ×8, `FUN_400326a0`, `FUN_40078850(0)`,
  redraws. (This is the case probe #1/#2 caught firing ×8 — the pattern change reaches it
  when the linked Part differs.)

**Neither calls the crossfader scene morph `FUN_4003f1b4`.** `FUN_4003f1b4`:
- reads scene A/B **selection** (`blob + [0x80000003]*0x18b2 + 0x8ed90/91`) and both scene
  **data blocks** (`blob + part*0x18b2 + scene*0x100 + 0x8f3e2`), per-track, interpolates by
  the crossfader position, posts **kind-0x0e** records to the DSP param queue `0x460d17ee`.
- **early-returns if the fader position `0x460d16c8` == its last-processed value
  `0x400c0c44`** (`0x4003f1bc`; `0x400c0c44` is written *only* by `FUN_4003f1b4` itself at
  `0x4003f394`, init `0xffff`).
- has exactly **two callers**: the `sys` crossfader-move case `0x400626de` and the
  arranger-exit handler `FUN_40055f18` (`0x40055fa4`, gated on `0x460d1aec`). **No periodic /
  per-frame caller.**

⇒ After a pattern→Part change with a stationary crossfader, the DSP keeps the **previous
Part's** scene-morphed parameter values (last `FUN_4003f1b4` output) until the fader is next
moved — then `FUN_4003f1b4` runs, reads the new Part's scenes (via the now-updated
`0x80000003`), and corrects. **Exactly Open_Mike's "scene behavior of new part might still
respond to the first pattern/part scenes"** — transient, clears on a fader touch.

**Fix (add to the same detour):** `move.l #-1, 0x400c0c44` (invalidate the morph dedup
guard) + `jsr FUN_4003f1b4` — re-posts the morph with the new Part's scene selection + data.
~1 instr + a jsr; `FUN_4003f1b4` is no-arg and already runs in `sys` context (the
crossfader-move case is in the same dispatch), so it's safe from the handler.

**The scene *parameter data* (not just the morph) is also stale — same root cause.**
`FUN_40002df4(bank, part, scene, slotAB)` = the scene-param stager: per track, if
`0x8000182a[track] == activeBank && 0x80001832[track] == activePart` (`0x80000002` /
`0x80000003`), copy 32 B of scene data from `blob + bank*0x9b340 + part*0x18b2 + scene*0x100
+ 0x8f3e2` (`0x401715c2` base) into the **live scene buffer `0x80000ed4 + track*0x40`**
(A/B interleaved, stride 2) **and** into the per-voice DSP record region (`0x80000110 + …
+ 0xfc4`). Called from the pattern-change redraw burst (`FUN_4004d640` → `FUN_40002df4`)
and the scene-edit menu. Frame-builder reads `0x80000ed4` (`0x4000c234` / `0x4000cc96` /
`0x4000cd6a`) → audio; the scene-edit/apply code (`0x40038xxx`, `0x40052xxx`) reads it for
display too.

**The gate `0x80001832[track] == activePart` is the whole bug.** `0x80001832[track]` (per
track, "the Part this track's staged engine + scene state reflects") / `0x8000182a[track]`
(bank) are:
- **set to `part` / `bank` by `FUN_40009094` in its per-track loop** (`0x40009396` bank,
  `0x4000939e` part — displacements `+0x171a` / `+0x1722` off `0x80000110+track`).
- reset to `0xFF` by `FUN_40004768` (project load) and `0x4004a394` (RELOAD-PART adjacent).
- **never touched by the pattern-triggered Part change** (`sys` `0x400621a6` / `0x400620fe`).

So: a manual PART apply / RELOAD PART / bank load runs `FUN_40009094` → marks every track
with the new part → the redraw burst's `FUN_40002df4` gate passes → `0x80000ed4` restages →
audio + display + LEDs all track the new Part. A **pattern-triggered Part change** doesn't
run `FUN_40009094`, so `0x80001832[track]` stays at the *old* part, `FUN_40002df4` skips
every track, and `0x80000ed4` keeps the **old Part's scene data** — feeding stale scene
values to the DSP (audio) and to the parameter display / scene LEDs. **This is the data /
audio / screen / LED mismatch, and it's the same missing `FUN_40009094` as #1/#2/#3.**

(`#3` `0x46c7aa24` — the step handler's `d2 == -1` scene-pseudo-track p-lock source, spliced
`#3 → #2` on pattern-enter but not reloaded from the blob — is a *separate* sequencer-side
scene representation. Not yet pinned to a loader; likely another face of the same gap.)

### The frame-builder ALREADY has a partial per-track re-stage — found while chasing the above

`FUN_4000c8a4` (frame builder), per track per frame (`0x4000bf3a`): compare
`0x8000182a/0x80001832[track]` (this track's staged bank/part) to the track's **currently
playing** bank/part (`sp@118/119`, computed from the sequencer's per-track pattern
pointers); set `d3` = "changed"; **write the playing bank/part back into
`0x8000182a/0x80001832[track]`** (`0x4000bf62/6a`). Then `0x4000c0ae: if (d3) { … }` — a
big inline re-stage block (`0x4000c0b4–0x4000c428`): re-copies the `mt`-indexed machine
params + the 30/36-byte param records + the **scene data → `0x80000ed4 + track*0x40`** +
the per-voice DSP records + the slot bytes `0x80000110 + track + 0xb40/0xb50`.

**So a *running* pattern→Part change DOES re-stage machine params + scene data per track —
but NOT:**
- the **recorder-page config** (`0x80000c94` / `0x8f382`) — not in the block → #2/#3 stand
  even while playing (emu `--repro` `0xAA` marker survived).
- a **PICKUP→FLEX voice-slot rebind** — the block writes the slot bytes to
  `0x80000110+track+0xb40` (same as `FUN_40009094`), yet the reported bug says the pickup
  loop still plays → writing those bytes is not enough to unstick a PICKUP voice from its
  recording buffer; the `0x8000184c` re-trigger is still needed → #1 stands.
- and it only runs **while the transport is playing** (frame builder is idle when stopped) →
  a *stopped* pattern→Part change re-stages nothing (emu `--repro` stopped: `0x80000ed4`
  `0xEE` marker + `0x80000c94` `0xAA` marker + `0x80001832` all survived).
- timing: the `sys` handler's redraw burst (which calls `FUN_40002df4`, gated on
  `0x80001832[track] == activePart`) fires *before* the frame builder updates
  `0x80001832[track]` → `FUN_40002df4`'s non-`0x80000ed4` outputs (per-voice + display) run
  with the stale gate.

⇒ the scene *audio* partly self-heals on a running switch, but the recorder config, the
pickup voice, the stopped-switch case, and the data/display/LED consistency do not. The
robust fix is to make the pattern→Part change do the **full** manual-PART-select work.

### Status — all four symptoms are ONE root cause: the pattern-triggered Part change never runs `FUN_40009094`

Static RE + four emu probes in `emu_rtos`. `tools/emu_partswitch.py` (`--probe` / `--repro`;
`--repro` now: `start_transport_live` [transport starts ✓, `0x800065b8=1`], poke PICKUP +
distinct recorder + distinct scene data per Part, STOP, switch, watch voice / slot mirror /
recorder cache / `0x80001832` / `0x80000ed4` / morph guard / `FUN_40002df4` / `FUN_4003f1b4`).
`scan_parts.py` in scratchpad. Nothing built/committed.

| symptom | what the manual PART apply does that the pattern-change doesn't |
|---|---|
| #1 pickup loop | `FUN_40009094` re-applies playback-machine params + marks `0x80001832[track]`; the notPICKUP→PICKUP `FUN_400972fc` arm sets `0x8000184c` (voice re-trig) |
| #2/#3 recorder | `FUN_40009094` writes the recorder UI cache `0x80000c94` (`0x40009176`) |
| scenes (data + audio + display + LED) | `FUN_40009094` marks `0x80001832[track]=part` → the redraw burst's `FUN_40002df4` gate passes → `0x80000ed4` restages; `FUN_40009094` also writes `0x80000ed4` directly (`0x4000943c`) |

**Cleanest fix — one call, covers all four:** detour the `sys` Part-change handler
(`~0x40062216`, after the `FUN_400972fc`×8 loop) to `jsr FUN_40009094(0x80000002, newPart)`
— exactly what a manual PART select runs — then `move.l #-1, 0x400c0c44` + `jsr
FUN_4003f1b4` (re-run the crossfader scene morph without waiting for a fader move).
`FUN_40009094(bank@sp+108, part@sp+112)` — 2 args on the stack, the `pea` convention.

**Pre-build tasks — done:**
- **Harness transport start:** `press_play_live()` left `0x800065b8 == 0` on the DEMO;
  **`rt.start_transport_live()`** (`FW_TRANSPORT(0)` + `FW_START_TRACK`×8 directly) works —
  `0x800065b8 = 1`, `frame_count` advances. `--repro` updated. (Note: a *running* pattern
  change defers to the step engine's pattern boundary — thousands of frames out — so the
  switch-probe STOPs first, which the reports also cover.)
- **Recorder record covers page 2:** the record is **12 bytes** = 12 params (page 1
  `INAB INCD RLEN TRIG SRC3 LOOP` + page 2 `FIN FOUT AB QREC QPL CD`), 1 byte each. The
  knob editor `FUN_4002ef28` writes slot `d4` 0–5, or `d4 += 6` for page 2 (gated on
  `0x460d115e`), into the same 12-byte record at `0x80000c94` / `0x100a54d0` / blob
  `+0x8f382`. The frame-builder copies 96 B (8×12). ⇒ the fix's `memcpy(…, 12)` covers
  both pages.

**Emu `--repro` #4 (STOP-then-switch, scene instruments):** `press_key_live(KEY_STOP)`
didn't stop the transport (still `1`), so the switch stayed *pending* and never committed
(`0x800065be` = 0 after). But it captured the frame-builder's per-track settle:
`0x8000182a/1832[track]` written from `0x4000bf62/6a` (the per-frame settle described
above), `TRK_PART` `ff 00 ff 00 00 00 ff 00` → `ff 00 00 00 00 00 00 00`. Everything else
(`0x80000ed4` `0xEE`, `0x80000c94` `0xAA`, slot mirror) unchanged. Need a working STOP
(double-press? edge=1? `FW_TRANSPORT(1)`?) or a long run past the pattern boundary to
observe a *committed* running switch — deferred.

**Decision: full `FUN_40009094` call, gated behind a PERSONALIZE toggle, default OFF.**
- Rationale: it makes a pattern→Part change identical to a manual PART select — the one
  behaviour users can already reason about. It drives audio + data + display + LEDs from
  one source (`FUN_40009094` writes `0x80000c94`, `0x80000ed4`, the pre-image, and marks
  `0x80001832[track]`; the handler's existing redraw burst then repaints from fresh state).
  A piecemeal fix would have to chase each representation separately and still race the
  frame-builder's own settle.
- Cost: `FUN_40009094` re-applies every param → possible envelope retrigger / LFO-phase
  reset / a click on live voices. This is precisely why stock (and octamax's "lazy Part
  transitions") *avoid* it. → toggle, default OFF (stock, smooth-but-wrong); ON = correct.

**Fix = detour `~0x40062216` (after the `FUN_400972fc`×8 loop), gated:**
1. `jsr FUN_40009094(0x80000002, [0x100b14cf])` — `pea` convention, 2 stack args.
2. per track where `oldType == 4 && newType != 4`: `0x8000184c |= 1<<track` (unstick the
   PICKUP voice — writing the slot bytes alone doesn't, per the report + the frame-builder
   evidence).
3. `move.l #-1, 0x400c0c44` + `jsr FUN_4003f1b4` — re-run the crossfader morph now.

**Still verify before building (HW, mostly):**
- the click magnitude from `FUN_40009094` on live voices — the toggle's whole reason to exist.
- `FUN_40009094` re-entrancy / safety from the `sys` task with the transport running
  (stock only calls it post-stop / post-deserialise / RELOAD-PART).
- whether step 2 is actually needed once `FUN_40009094` runs, or `FUN_40009094` +
  `0x8000184c` is belt-and-braces.
- does `FUN_40009094` re-stage BOTH recorder pages (the 12-B record — it should, per the
  page-2 finding above, but confirm it copies all 12).
- the `#3` `0x46c7aa24` sequencer-scene-plock loader (still unpinned) — check `FUN_40009094`
  or the redraw burst reloads it.

NEXT: emu — get a *committed running* switch (working STOP or long run) and confirm
`FUN_40009094`-in-the-detour clears all four; then build + validate S48-style
(stock-repro + patched-fix).

### FINAL DESIGN (supersedes both framings above) — reuse `FUN_40009094` as Elektron's own canonical Part-apply primitive, complete the two pieces nothing implements

User's call: use Elektron's intended mechanics, fix the incomplete implementation — not a
from-scratch reimplementation, not a blanket "avoid it, might click" retreat. Re-checked
`FUN_40009094` line-for-line against the frame-builder's inline block: it already does the
`mt`-indexed machine-param copy, the slot bytes, **the recorder cache `0x80000c94`** (`#2/#3`
covered), **the scene buffer `0x80000ed4`**, and marks `0x80001832`/`0x8000182a[track]` (fixes
the `FUN_40002df4` gate/race for the redraw burst). It touches no envelope, LFO-phase, or
play-position state anywhere in its body. It is not a bespoke "full reapply" risk — it is
**the single routine manual PART select, RELOAD PART, bank load, and project load all already
call**, on every real session, without incident.

The one real, narrow risk — not "resets everything," but precisely characterized from
octamax's *own* inherited notes on a different wish ("preserve volume when switching Part",
`reference/upstream-notes.md` "Go/No-Go"): the frame builder reads the active Part's params
continuously, so **a track with a voice actively sounding through the exact instant of the
switch may hear a discrete parameter jump** if the new Part's value differs. Silent tracks,
and tracks whose next trig lands at/after the switch, are unaffected. That's the honest
tradeoff to disclose, not a reason to avoid Elektron's own routine.

**Fix — detour `sys` `0x400621a6` (the site emulation confirmed a real pattern-driven Part
change reaches), right after its existing `FUN_400972fc`×8 loop, before `FUN_400326a0`:**

1. `jsr FUN_40009094(0x80000002, [0x100b14cf])` — Elektron's own routine, called as-is.
   Closes #2/#3 and the scene data/display/LED consistency (marks `0x80001832[track]` →
   the redraw burst's `FUN_40002df4` now passes its gate with fresh data).
2. Per track (old machine types are already buffered on the stack for the loop above —
   nothing new to compute): `oldType == 4 && newType != 4` → `0x8000184c |= 1<<track`.
   **Nothing in stock does this** — not `FUN_40009094`, not the frame-builder's lazy block,
   not `FUN_400972fc`'s own PICKUP branch. The one genuinely new piece; narrowly scoped to
   the exact transition report #1 describes.
3. Once: `move.l #-1, 0x400c0c44` + `jsr FUN_4003f1b4` — re-trigger the crossfader morph.
   Also nothing existing does this for a Part change. Small, self-contained — `FUN_4003f1b4`
   already runs from this same `sys` task context via the crossfader-move case.

**Scope note:** `FUN_400972fc` has two other callers (`0x4005a676`, `0x4005a8b0`, in the
`0x4005axxx` PART-select UI region) not yet audited — worth checking later whether manual
PART select has its own (smaller?) version of the pickup/scene-morph gaps, but that's outside
the four reported symptoms (all pattern-triggered) and not folded into this fix without
evidence.

**Build-time to confirm:** exact `pea`/stack-arg convention + byte offsets for the
`0x400621a6` case (re-disasm at build time, don't trust hand-counted displacements from a
reading pass); `FUN_40009094` reentrancy from `sys` with the transport running (it's already
called from `sys`-adjacent contexts per its 10 call sites, but confirm this specific one);
whether `#3` (`0x46c7aa24`) also gets refreshed as a side effect of `FUN_40009094` running
(still unpinned) or needs its own line.

Toggle: still gate behind a PERSONALIZE entry per house style (behaviour change on a stock
path) — but frame the description around the real, narrow tradeoff (a sounding voice may
jump on switch) rather than an overstated "full reset" risk.

### Verification pass — does `FUN_40009094` actually fix #2/#3? (user asked before building)

Re-traced the `0x4000917e` write cited above by hand and got an inconsistent *source*
address (looked like it read near Part-payload offset 0, not the recorder record's real
offset `0x602`) — so the specific instruction attribution in the table above is not
trustworthy as stated; don't cite `0x4000917e` specifically without re-deriving it at
build time. Rather than keep re-reading disassembly, settled the question that actually
matters empirically, in `emu_rtos` (`check_reccache.py` / `check_reccache2.py`,
scratchpad):

- **Plain check**: after a normal `load_project_live`, `0x80000c94[track]` for every track
  matched `blob+part*0x18b2+0x8f382+track*12` exactly — but all 8 tracks held identical
  default bytes, so this alone doesn't rule out coincidence.
- **Causation check (decisive)**: scribbled the cache to `0x99×12` for all 8 tracks, poked
  a distinctive record (`0x70..0x7b`) into the blob for all 8 tracks, called
  `call_as_main(FUN_40009094, (curbank, curpart))` directly, re-read the cache — **every
  track's cache slot came back holding exactly the poked bytes.** Causal, not coincidental.

**Confirmed: `FUN_40009094(bank, part)` does correctly refresh the recorder-page cache
`0x80000c94` (both pages, all 8 tracks) from the applied Part's stored record.** The
FINAL DESIGN fix (calling it from the `sys` Part-change detour) does close reports #2/#3,
on top of #1 and the scene aside. Exactly which instruction inside `FUN_40009094` performs
this copy is unresolved (my hand-traced attribution was wrong) — not needed to trust the
fix, since the causal behaviour is now proven directly; if a future session wants the exact
site (e.g. to understand page-2 coverage precisely rather than infer it), re-derive fresh
rather than reuse the `0x4000917e` claim above.

### REVISED FINAL DESIGN — don't touch/race Elektron's own lazy mechanism, only fill genuine gaps

User pushback (rightly): does calling `FUN_40009094` break the jump-avoidance the lazy path
was built for? Real, unresolved uncertainty: does the frame-builder's per-track catch-up
(`0x4000bf3a`→`0x4000c0b4` block) genuinely defer past a sounding voice's risk window (e.g.
until that track's next trig), or does it fire at essentially the same instant as the
pattern-boundary commit (no real timing advantage over a synchronous call, just narrower
scope)? **Not resolved — not worth guessing on a question this consequential.** Routed
around it instead of answering it:

- **Recorder cache (#2/#3):** standalone `memcpy(0x80000c94+track*12, blob+newPart*0x18b2+
  0x8f382+track*12, 12)`, all 8 tracks. Touches nothing machine/voice-state related; recorder
  settings aren't a continuously-audible parameter (they govern a not-yet-started recording,
  not a decaying/sustaining voice) → no jump-risk category, independent of the timing
  question, safe unconditionally.
- **PICKUP unstick (#1) and the scene-morph retrigger** — real, audible, but the risk is
  *inherent to the fix itself* (a voice stuck on the wrong buffer must be interrupted to
  correct it; scenes applying now instead of on next fader-touch means a discrete DSP push
  now) — not a side effect of choosing to reuse `FUN_40009094`. No version of "fixed" avoids
  this.
- **Machine params + scene buffer (`0x80000810`/`0x80000a50`/`0x80000ed4`) — LEFT ALONE.**
  Do **not** call `FUN_40009094` for this piece while the transport is running, and do
  **not** write the per-track marker `0x80001832[track]` either — writing the marker without
  also doing the copy would tell the frame-builder's own detector "already settled" and make
  it **skip its own catch-up**, which is strictly worse than today's bug (currently it lags;
  that would make it never happen). Whatever protection Elektron's existing per-track lazy
  mechanism has for these two fields, keep it completely intact and unraced.
- **Full `FUN_40009094` call — gated to `0x800065b8 == 0` (transport stopped) only.** The
  frame-builder never runs at all when stopped (confirmed empirically, `--repro` probes
  1/2) → zero catch-up ever happens on a stopped switch without this, AND zero jump risk
  exists (nothing sounding) → this is exactly the case where the full routine is both safe
  and necessary.

**Net design:** per track, always — recorder memcpy; on `oldType==4→newType!=4` — kill bit.
Once, always — scene-morph retrigger. Additionally, **only if `0x800065b8==0`** —
`jsr FUN_40009094(bank,newPart)` (covers machine params/scene buffer/marker for the stopped
case, where stock's lazy mechanism never would). While playing, machine-param/scene-buffer
timing is stock's, untouched, unmodified — cannot regress whatever jump-avoidance property
it has, known or unknown.

**Residual gap, accepted:** while playing, the display/LED consistency for `FUN_40002df4`'s
gate may lag by up to ~1 frame after a Part-crossing switch, same as it does today for
whatever else is lazily caught up — not eliminated, but not worsened, and self-corrects
within a frame once the frame-builder's own detector fires (unaffected by our fix, since we
never touch its inputs while playing).

Toggle: still gate the WHOLE thing (recorder + pickup + morph + stopped-case full-apply)
behind one PERSONALIZE entry, described around "recorder/pickup/scene correctness on a
Part-changing pattern switch; while playing, tracks with a currently-sounding voice may
interrupt/click on the pickup-unstick and scene-morph pieces specifically — inherent to the
fix, not this build's error."

NEXT (build-time): re-derive `0x400621a6`'s exact stack-arg offsets fresh (per the earlier
verification-pass lesson — don't trust a hand-counted read); confirm `0x800065b8` is
reliably read at the point of this detour; the stopped-case `FUN_40009094` call still needs
the reentrancy-from-`sys` check noted earlier.

## Session 49 — HANDOFF (read this first; everything above is the raw log, including two dead ends corrected in-line — this section is the current, authoritative status)

**Bug family scoped:** a pattern change that links a different Part doesn't fully re-apply
that Part's per-track state. Three Elektronauts reports + one aside, all traced to the same
underlying gap:
1. **Open_Mike** — track T = PICKUP machine in Part A (not running) → switch to a pattern on
   Part B where T = FLEX → T plays **Part A's pickup loop**, not Part B's sample. A second
   user confirms, and specifically narrows it: **only when the new machine is FLEX — a
   STATIC machine on the same switch works correctly.**
2. **Open_Mike** — recorder trig SRC/RLEN from the old Part is used even when locked on the
   new pattern.
3. **sezare56** — REC SETUP last-tweaked value leaks across a Part boundary (tweak P1's
   SRC→T8, switch to P2 whose stored SRC=T2 → P2 records from T8).
4. **(aside, Open_Mike)** — the new Part's scenes may still respond to the old
   pattern/Part's scene values.

### What's SOLID (static RE + emulator-confirmed, trust these)

- **The two `sys`-task dispatch cases that handle a Part change**: `0x400620fe`
  ("select pattern N" — derives the Part from the pattern link, sets `0x80000003`/
  `0x100b14cf`, redraws only) and `0x400621a6` ("select Part P" — loop
  `FUN_400972fc(newPart,track,oldType)` ×8, redraws). **`0x400621a6` is the one a real
  pattern-driven Part change reaches** (confirmed: `FUN_400972fc` fired ×8 in `emu_rtos`
  across a real `seq_select_live` switch). **Neither case calls `FUN_40009094`** (the full
  per-track Part-apply that manual PART select / RELOAD PART / bank load / project load all
  use) — confirmed by watching its entry point across a real switch: zero hits.
- **`FUN_40009094(bank, part)` does correctly refresh the recorder-page cache
  `0x80000c94+track*12` (both pages, all 8 tracks) from the applied Part's stored record —
  proven CAUSALLY**, not just by reading code: scribble the cache, poke a distinctive
  record into the blob, call the function directly, cache comes back holding exactly the
  poke. Reproducible via `tools/check_reccache_causation.py`. **This closes reports #2/#3**
  once the pattern-change path is made to call it.
- **The scene aside is real and has its own mechanism**: the crossfader morph
  `FUN_4003f1b4` (reads scene A/B selection + data from the blob keyed by the active Part,
  posts interpolated values to the DSP) has exactly two callers — the crossfader-move
  handler and an arranger-exit handler — **neither is the pattern-change path**, and it has
  a dedup guard (`0x400c0c44` vs fader position `0x460d16c8`) that skips the whole morph if
  the fader hasn't moved since its last run. So a Part-crossing pattern switch leaves the
  DSP holding the *previous* Part's scene morph until the fader is next touched.
- **The scene *data* (not just the morph) has a second, independent gap**: the scene-param
  stager `FUN_40002df4` is gated per-track on `0x80001832[track] == activePart` (and
  `0x8000182a[track] == activeBank`) — and **`0x80001832`/`0x8000182a[track]` are only ever
  set to the applied Part/bank by `FUN_40009094`** (never by the pattern-change path). So the
  live scene buffer `0x80000ed4+track*0x40` (what the frame-builder publishes to the DSP,
  and what other scene-consumer code reads for display) also stays stale.
- **The frame-builder (`FUN_4000c8a4`) has its own partial, running-only lazy catch-up**
  (`0x4000bf3a` per-track "did this track's playing Part change" detector →
  `0x4000c0b4-0x4000c428` re-stage block): it DOES re-copy machine params and scene data —
  but only while the transport plays, and it never touches the recorder cache and never
  unsticks a PICKUP voice.

### What turned out WRONG this session — don't repeat these

- **A specific instruction attribution inside `FUN_40009094`** (claimed to be "the" recorder-
  cache copy at `0x4000917e`) was hand-traced twice with two different, both-plausible-
  looking-but-inconsistent answers for its source address. **Don't trust either reading** —
  the *functional* claim (the routine refreshes the cache) is proven causally above; the
  *specific instruction* was never correctly pinned and isn't needed.
- **`FUN_40005030` is NOT the sequencer's per-step trig sample-resolver.** It looked
  promising (reads the active Part's machine type + slot fresh, maps to the right sample
  arena, matches octamax's old "trig helper, doesn't refresh Part params" description) — but
  a real, confirmed sequencer trig (via `install_trig_log`, landing on track 1 at frame
  ~1379-1593 from a cold pattern start) never once called it. Its 8 callers all trace to
  manual/UI gesture dispatchers, not the step-trig path. **The real per-trig resolver is
  still unidentified** — it's somewhere inside the step handler `FUN_4009d1e8` / its
  consumers `0x4009d382..0x4009da12`, not traced to instruction level.
- **The differential PICKUP→FLEX vs PICKUP→STATIC test (`tools/diff_flex_static.py`) has
  been run twice and both times failed to establish the bug's actual precondition** — a
  *real* prior trig has to genuinely bind the voice to the PICKUP arena entry before the
  track goes idle and the switch happens; a poked machine-type byte alone isn't the same
  state. Both runs used a 200-frame "bind" budget, but a real first trig from a cold pattern
  start doesn't land until ~1300-1600 frames — so neither run ever created the real
  precondition, and **both showed correct resolution in a state that was never actually
  buggy to begin with.** Fixed in the copy now in `tools/diff_flex_static.py` (waits for a
  genuine bind + asserts it before proceeding) — **not yet re-run with the fix.**

### Current fix design (REVISED — see "REVISED FINAL DESIGN" above for the full reasoning)

Per track, always: `memcpy(0x80000c94+track*12, blob+newPart*0x18b2+0x8f382+track*12, 12)`
(recorder, safe unconditionally). Per track, `oldType==4 && newType!=4`:
`0x8000184c |= 1<<track` — **this piece is UNVERIFIED and now suspect** (see below). Once:
`move.l #-1,0x400c0c44` + `jsr FUN_4003f1b4` (scene morph retrigger). Only if
`0x800065b8==0` (transport stopped): `jsr FUN_40009094(bank,newPart)` (covers machine
params/scene buffer/marker for the stopped case only, where the frame-builder's lazy
catch-up never runs anyway). Deliberately does NOT call `FUN_40009094` or write the
`0x80001832[track]` marker while playing, to avoid racing/disabling Elektron's own lazy
per-track catch-up (see the design conversation above for why).

**Open, real question on the `0x8000184c` kill-bit piece:** it was proposed by analogy (the
*reverse* transition, notPICKUP→PICKUP, also sets this bit) — never proven to actually
unstick a PICKUP voice. Per Session 9, this bit triggers an AMP envelope *release* ramp, not
a "re-resolve which buffer this voice reads" action, so the analogy may not hold. The
differential test above was specifically trying to settle this and hasn't yet, due to the
bind-phase bug (now fixed, not yet re-run).

### NEXT (prioritized)

1. **Re-run `tools/diff_flex_static.py`** (now fixed — waits for a genuine PICKUP bind +
   asserts it) for the real PICKUP(bound,idle)→FLEX vs →STATIC comparison. ~8-12 min wall.
   If it STILL shows correct resolution in both cases even with a genuine prior bind, the
   bug may specifically require a Part change committed **while the transport is running**
   (a live pattern-boundary commit) rather than the stop-switch-restart sequence every test
   this session has used — `seq_select_live` while playing only *queues* the change for the
   next pattern boundary (1000s of frames out, never reached this session). That needs its
   own harness (run playback for real until the *current* pattern's own step count is
   reached, not a fixed frame budget).
2. If the diff finally reproduces the bug, it will show WHICH memory location diverges
   between the FLEX and STATIC runs (the read/write watches are already in place, covering
   the 3 arena entries + the pre-image/cache/scene/marker band + the voice struct) — that
   directly names the real mechanism, replacing the `0x8000184c` guess with something
   verified.
3. Confirm the `#3` sequencer-side scene p-lock loader (`0x46c7aa24`) — still unpinned; no
   literal-address writer found. Lower priority than #1's mechanism.
4. Build-time (once #1's mechanism is settled): re-derive `0x400621a6`'s exact stack-arg
   offsets fresh (don't reuse any offset quoted earlier in this log without re-verifying),
   confirm `FUN_40009094` reentrancy from `sys` for the stopped-case call, then build +
   validate S48-style (stock-repro + patched-fix) before ever touching hardware.

### Tools (all in `tools/`, none in scratchpad — safe across a session boundary)

- `tools/emu_partswitch.py` — `--probe` (DEMO as-is) / `--repro` (poke PICKUP→FLEX + recorder
  + scene markers, drive the switch, dump before/after state). The main scoping harness.
- `tools/diff_flex_static.py` — the PICKUP→FLEX vs PICKUP→STATIC differential (fixed bind
  phase, not yet re-run — see NEXT #1).
- `tools/check_reccache_causation.py` — the causal proof that `FUN_40009094` refreshes the
  recorder cache. Re-run any time that claim needs re-confirming.
- `tools/scan_parts.py` — static bank-file pattern→Part link dump (reliable) + a machine-type
  guess (NOT reliable, known limitation documented in its own header).

## Session 49 — HANDOFF UPDATE (2026-09-10, same day, continued): the fixed bind phase found a bigger problem than the one it was fixed to catch

**Re-ran `tools/diff_flex_static.py` per NEXT #1 above.** Result: `BIND FAILED` —
zero trigs on T1 within the full 3000-frame ceiling (not "too slow to bind," literally
zero `FW_LIVE_NIBBLE` events on that track at all). This is a different, more
fundamental failure than the timing problem the bind-phase fix targeted, and it changes
the read on both prior (pre-fix) runs.

**Root-caused with two small throwaway probes** (`probe_trigs.py` / `probe_trigs_poked.py`,
scratchpad, not added to `tools/` — pure diagnostics, easily reproduced by any script that
loads OT DEMO, calls `seq_select_live(curbank, 0)`, and runs the transport):

- **Unpoked baseline** (no pokes at all, stock OT DEMO, pattern index 0 / Part 0):
  T1 (track 0) DOES trig — at frame 1 (an init write, value 0x10, shared by tracks
  0/1/3/4/5/7 simultaneously — not a real step trig), then **real** trigs at frame 1379
  (val 2, then 18) and frame 2757 (val 4, then 20). Interval ~1378 frames between real
  trigs — **sparse, not "nearly every step"** as this session's earlier notes claimed;
  that "1300-1600" figure was borrowed by analogy from a different investigation
  (the `FUN_40005030` probe) and the "nearly every step" characterization was never
  actually measured for this project/pattern. Correct the record: T1/P1 in OT DEMO trigs
  roughly once every ~1378 frames, first real trig at frame 1379.
- **Same setup, but with `diff_flex_static.py`'s exact poke applied first**
  (`machine_addr(blob,0) = 4` PICKUP, `slot_addr(blob,0,4) = 128`, i.e. Part0/T1 → PICKUP,
  slot 128 — the standard `128+track` PICKUP arena addressing the script itself uses):
  **T1 gets ZERO trig events for the entire 4000-frame run** — every other track (1-7)
  still fires at the exact same frames as the unpoked baseline (690, 1379, 2068, 2412,
  3446 — unaffected), but T1 is completely silent, and its voice struct
  (`0x800049d8`) never leaves `active=0x0, SETTINGS=0x00000000` the whole run — the voice
  engine never even touches it.
- **Why**: dumped the raw 1096-byte `FLEX_ARENA` entries. The REAL, loaded FLEX slot
  (Part1/T1, slot 20) holds a valid path string at its head (`../AUDIO/ELEKTRON/
  MDKICK.WAV`, 40 nonzero bytes total in the entry). **The PICKUP arena entry
  (slot 128+T, i.e. `FLEX_ARENA + 128*1096`) is essentially empty — only 12 nonzero bytes
  in the whole 1096-byte entry, no path string, nothing that looks like a loaded sample.**
  This is expected on a project where track 0 has never actually performed a PICKUP
  capture: unlike FLEX/STATIC, a PICKUP machine's arena entry isn't populated from a
  file on the card — it's populated by an actual on-unit PICKUP capture action, which
  this project has never done for T1. The firmware evidently checks something in this
  entry (a length, a valid/loaded flag — not yet located) before scheduling ANY trig for
  a track pointed at an unpopulated PICKUP slot, and skips the track entirely if it's
  empty — which is arguably correct, sensible stock behaviour (nothing to play, so don't
  schedule playback), not a bug.

**What this means for the differential test and for report #1 generally:**

- **A bare machine-type-byte poke to PICKUP can never produce the "genuinely bound,
  idle PICKUP voice" precondition the bug report describes**, because the firmware
  won't schedule any trig — let alone bind a voice to the PICKUP arena entry — for an
  empty PICKUP slot. This was true of BOTH pre-fix runs this session too: the "bind"
  phase in those runs (200-frame budget, no assertion) silently "succeeded" by doing
  nothing meaningful, same as this run's failure, just without the check that would
  have caught it. **All three runs of this test to date (two pre-fix, one post-fix)
  have failed to create the bug's actual precondition, for two compounding reasons now
  identified: insufficient bind time (fixed this session) AND an empty/unpopulated
  PICKUP arena entry that can never bind regardless of time (newly found, NOT fixed).**
- The real Elektronauts report describes a PICKUP machine that **has** been used —
  it has real captured audio, a real "loaded" state, and (per the report) is actively
  looping/playing before the switch. Reproducing that in the emulator needs the PICKUP
  arena entry to look genuinely populated, not a bare type-byte flip. Two ways to get
  there, neither tried yet:
  1. **Fabricate a populated-looking PICKUP entry** — e.g. clone a real FLEX entry's
     1096 bytes into the PICKUP slot (128+T) before binding, so whatever gate the
     firmware checks (probably a length or loaded-flag near the entry head, unlocated)
     reads as "populated." Fast to try, but risks being structurally wrong: a PICKUP
     entry may not share layout with a file-backed FLEX entry at all (PICKUP audio
     lives in a captured RAM buffer, not a WAV path) — if the firmware trusts the
     path string specifically, a cloned entry could bind to the wrong data, or bind
     to something that doesn't behave like a real PICKUP voice for the purposes of
     the actual test (whether a stale buffer is what a FLEX switch would inherit).
  2. **Drive an actual PICKUP capture in the emulator first** (whatever real gesture
     populates a track's PICKUP buffer on hardware — not yet identified in this
     project's RE), then let T1 genuinely bind to it, then do the switch. Higher
     fidelity, more RE work up front (need to find and drive the real capture path),
     probably several more sessions of static RE before it's emulator-drivable.
  Neither has been attempted. This is the fork in the road for how to proceed.

**User clarified the report's precondition directly** (quoting the original Elektronauts
text): the PICKUP machine is "already linked to a sample" (i.e. genuinely populated,
not a fresh empty slot) and simply not running before the switch. Decision: pursue
fabrication (option 1 above) as the faithful reproduction of this precondition, not
just a shortcut — tried it, and it's NOT sufficient on its own (see below).

**Tried: seed the PICKUP arena entry (slot 128+T) with a clone of a real, loaded FLEX
entry's 1096 bytes** (`tools/diff_flex_static.py` updated to do this before the bind
phase; also verified standalone in a throwaway sanity probe). **Result: still
`NOT BOUND` — T1 still gets ZERO trigs in 3000 frames, identical to the unseeded
case.** So whatever gates trig-scheduling for a PICKUP-machine track is **not** the
arena entry's content — cloning real sample bytes into it changed nothing. The gate
must be a separate flag/field, keyed on the machine type itself or on some other
per-track state we haven't located yet (candidates: something in the PART data near
`MACHINE_OFF` beyond the single type byte; a separate "has this track ever captured
pickup audio" bit; a length/valid field that lives outside the `FLEX_ARENA` table
entirely, maybe alongside the recorder cache at `0x80000c94+track*12` or similar).

**NEXT (supersedes the old NEXT #1 above):** find the actual gate via instruction-level
tracing — compare execution through the step handler (`FUN_4009d1e8` / consumers
`0x4009d382..0x4009da12`, per the existing "real per-trig resolver still unidentified"
note above) between a poked-PICKUP track (never trigs) and the same track left as its
stock FLEX machine (trigs at frame 1379) — same project, same pattern, only the
machine-type poke differs — to find where the two diverge. That divergence point names
the real gate. Old NEXT #2-4 (exact divergence mechanism for report #1 itself, `#3`
scene p-lock loader, build-time offset re-derivation) are unaffected and still pending,
now gated behind finding this gate first.

**FOUND — and it reframes the whole investigation.** The gate hunt succeeded, but the
gate turned out to be architectural, not content-related: `FW_LIVE_NIBBLE` (the signal
this session's whole test methodology has been using as "did this track trig") is
**structurally never written for a PICKUP-machine track, valid buffer or not.**

Method: (1) disassembled `0x4000b7xx-0x4000ba20` (the actual `FW_LIVE_NIBBLE` publish
routine, found by hooking writes to `FW_LIVE_NIBBLE` directly rather than guessing a
range — the earlier `FUN_4009d1e8` guess from the "per-trig resolver" note was wrong,
that address range never contains the write at all: real write PCs are `0x4000b910` /
`0x4000b9bc`). (2) Traced writes to its two guard structures (a 16-entry table at
`0x46c7e998`, and a per-track bitmask byte at `0x80001798+track`) across the exact
frame where T1's real trig lands (1379, from the unpoked baseline), poked vs unpoked.
Found: **at frame 1379, unpoked track 0 falls through the routine's NORMAL path to the
publish write; poked track 0 instead takes an early "clear and skip" branch at
`0x4000b8b8`**, which exits via a different address (`0x4000bc32`) that never reaches
the write. (3) That branch is gated on `btst #11` of the per-track table entry (clear
in both cases — not the differentiator) AND a bit in a single GLOBAL flag byte at
`0x46c7ff3e` (one bit per track, tested via `mvzb`+`andl` against the per-track
bitmask). Confirmed directly: this byte is `0x00` throughout the unpoked run, and
flips to `0x01` (bit 0 = track 0) in the poked run **immediately after
`seq_select_live`** — i.e. it's computed fresh at pattern/Part-apply time, not
per-step. (4) Found the setter via a static search (`grep` for `ff3e` across a full
disassembly of the image — cheap, no emulator run needed): `FUN_40097204`, an 8-track
loop that for each track reads `blob[activePart*0x18b2 + 0x8eda2 + track]` (this is
exactly `PARTS_OFF+MACHINE_OFF`, i.e. the track's machine-type byte) and:
```
if (machine_type == 4 /* PICKUP */) {
    flag |= (1 << track);                    // 0x40097250
    x = FUN_40000e50(track);                 // unexplored
    if (*(x+20) != 4) FUN_40006820(track);   // unexplored, "not PICKUP" cleanup?
} else {
    flag &= ~(1 << track);                   // 0x40097276
}
```
**This sets the bit purely from the machine-type byte — it never reads the arena
entry, a length, or anything that would distinguish "empty" from "really captured"
PICKUP content.** Every PICKUP-machine track gets this bit set, always, real capture
or not.

**Consequence: this whole session's differential-test methodology has been measuring
the wrong observable for a PICKUP track.** `FW_LIVE_NIBBLE` not firing for T1 is not
evidence of "empty buffer, never binds" — it's evidence that **PICKUP machines don't
use this trig-publish path at all**, by design, real capture or not. The
`voice_settings()[1] == pickup_entry` check `diff_flex_static.py`'s bind phase also
polls may have the same problem — if PICKUP voices are driven through the
`FUN_40000e50`/`FUN_40006820` pair (or whatever they call) into a different voice
mechanism entirely, the generic voice struct at `0x800049d8` may not be what a PICKUP
voice's binding shows up in either. **Neither has been checked yet.** This is a
genuine, still-open question, not assumed either way.

**NEXT (supersedes the immediately-preceding NEXT):** disassemble `FUN_40000e50` and
`FUN_40006820` (the two calls `FUN_40097204` makes for a PICKUP track) to find the
real PICKUP-specific trig/bind mechanism — that names the correct observable to poll
for "has this PICKUP voice genuinely bound" before any further emulator run is worth
doing. Until that observable is known, every future differential-test run against a
PICKUP track risks repeating this session's mistake (measuring a signal PICKUP
structurally bypasses) regardless of how faithfully the buffer content is fabricated.

**FOUND (static disassembly only, no emulator run needed) — and this decisively kills
the "fabricate a populated arena entry" approach.**

- `FUN_40000e50(track)` is trivial: returns `VOICE_BASE(0x800049d8) + track*VOICE_STRIDE(0xA8)`
  if track ≤ 7, else a fixed fallback pointer `0x46104e0e`. Just "get this track's
  voice struct pointer" — the same struct `diff_flex_static.py`'s `voice_settings()`
  already reads.
- `FUN_40006820(track)`, called by `FUN_40097204` only when `voice[track].+20 != PICKUP`
  (i.e. "this voice hasn't already been configured for PICKUP"): with track out of
  0-7 it recurses over all 8 tracks; for a real track it **clears `voice[track].+0`**
  (the "active" byte our probes have been reading as evidence of "never bound" all
  session), clears a 4-byte entry in an unrelated table at `0x80004898`, increments a
  counter at `voice[track].+144`, then calls `FUN_4000672C(track)`. **This runs
  unconditionally the first time a track's machine becomes PICKUP — real capture or
  not** — so `active=0x0` in every probe this session was this housekeeping reset
  firing, not evidence the buffer was empty.
- `FUN_4000672C(track)` — the real payoff. It reads `voice[track].+20` (same byte)
  and **only does anything if that byte already equals PICKUP AND
  `track == *(0x400d7c4c)`**; otherwise it's a no-op (jumps straight to return).
  **`0x400d7c4c` is a single GLOBAL 4-byte "which track currently owns the PICKUP
  buffer" variable — not a per-track slot.** The rest of the function (guarded on that
  match) manipulates a per-track enable bitmask at `0x461054ec`/`0x461054f0` and a
  small lookup table at `0x46c922d4+track*44`, consistent with transferring PICKUP
  "ownership" away from whichever track previously held it.

**Conclusion: PICKUP is architecturally a single shared, global capture buffer with one
owner at a time (`0x400d7c4c`), not a per-track resource the way FLEX/STATIC arena
slots are.** This fully explains why seeding `FLEX_ARENA[128+track]` with real sample
bytes (tried and failed earlier this session) could never work — that arena table has
nothing to do with PICKUP ownership or content; a track's PICKUP machine only has
"real" captured content when it is (or recently was) `*(0x400d7c4c)`'s value, set by
whatever the actual on-unit PICKUP-capture action does elsewhere (not yet located).
**The "fabricate a populated arena entry" path (Option 1 from the original fork) is
now confirmed non-viable, independent of how much more faithfully it's implemented —
wrong resource entirely.** Reproducing the report's precondition needs Option 2: find
and drive the real capture path (whatever sets `0x400d7c4c` and `voice[track].+20`
together, consistently), or at minimum fabricate BOTH of those in a self-consistent
way (set `0x400d7c4c = track`, `voice[track].+20 = 4`, and whatever the enable-bitmask
`0x461054ec` expects) rather than just the arena bytes.

**NEXT:** find what sets `0x400d7c4c` (the PICKUP-owner variable) and
`voice[track].+20` together — grep the full disassembly for `7c4c` (cheap, static,
no emulator run) to find every reader/writer, the same technique that found
`FUN_40097204` this round. That should lead to the real capture-assignment routine,
or at least reveal the minimal self-consistent set of pokes needed to fake ownership
without a real capture.

**FOUND the claim logic (static, `grep 7c4c` across the full disassembly — same cheap
technique).** Real hits (filtering disassembler noise): `0x40006754`/`0x400067da`/
`0x400067e4`/`0x400067f2` (already known, inside `FUN_4000672C`), plus three new ones
inside a large, not-yet-fully-mapped function spanning roughly `0x4000f000-0x4000f900+`
(true entry point not yet found — still reading backward from `0x4000f7d0` at the point
this note was written). The relevant fragment, guarded on `sp@(56) == 4` (this call's
target track's machine == PICKUP):
```
d1 = 0x400d7c4c                  ; current owner (-1 == unclaimed)
if (d1 >= 0) goto existing_owner_path;   // 0x4000f7e2: checks a bitmask at 0x461054ec,
                                          // only transfers ownership under further conditions
0x400d7c4c = candidate_track;    // 0x4000f7d0 — CLAIM, only reached when unclaimed
0x461054f0 = *(a5);              // a5 = a table row two entries further in, from a5+16
```
So on a fresh boot (never captured before, `0x400d7c4c` presumably `-1`), **the first
track whose machine becomes PICKUP and reaches this code claims the singleton
automatically** — no separate "capture" gesture is structurally required for a FIRST
claim, contrary to the assumption two paragraphs up. The surrounding function (still
being mapped) does dense loop-point/slice-boundary arithmetic (`macl`, table lookups at
`a4@(1092)` — note 1092, not 1096/`ARENA_STRIDE`, a different table) — this reads like
the actual per-voice sample/loop resolver, plausibly *the* function `FUN_40005030` and
`FUN_4009d1e8` were both wrongly suspected of being earlier this session.

**Open question, not yet resolved:** does the `0x46c7ff3e` skip-bit (set unconditionally
whenever machine==PICKUP, confirmed above) gate entry to THIS resolver too? If the
skip-branch in the step handler (`0x4000b8b8..0x4000bc32`) bypasses this resolver
entirely, PICKUP tracks would never bind at all while that bit is set — which cannot be
right, since PICKUP demonstrably works on real hardware. Two possibilities, neither
checked: (a) the skip-branch's own body (only partially read — it clears
`table[track]`, touches a byte-table at `0x46c7fe44`, then branches to `0x4000bc32`)
still leads into this resolver via a different route than the generic
`FW_LIVE_NIBBLE`-publishing normal path; or (b) something else clears the
`0x46c7ff3e` bit once a track's PICKUP voice is genuinely bound (`voice[track].+20`
becomes 4), and the bit is really "not yet bound" rather than a permanent PICKUP-vs-
everything-else router — in which case the correct experiment is to poll
`voice[track].+20` and `0x400d7c4c` over a longer run on the already-poked project to
see whether they ever change, independent of `FW_LIVE_NIBBLE` (which we now know is
never a valid signal for PICKUP either way).

**NEXT:** (1) find this resolver function's true entry point and its caller(s) — likely
resolves the open question above directly (if its caller is inside the step handler's
skip-branch itself, question (a) is confirmed; if its caller is elsewhere e.g. a
different per-frame path, question (b) is more likely). Cheap, static work — search for
`jsr`/`bsr` targets landing in `0x4000f000-0x4000f900`. (2) Once the true "did this
PICKUP voice bind" observable is known (candidate: `voice[track].+20 == 4`, possibly
combined with `0x400d7c4c == track`), re-run the differential test polling THAT instead
of `FW_LIVE_NIBBLE`/generic `SETTINGS` — this is the corrected version of `NEXT #1`
from several revisions back in this same session.

**PIVOT (user prompt): the `diff_flex_static.py` precondition-fabrication path never
needed to happen at all.** The actual root cause for report #1 was already fully
established and confirmed EARLIER in this same session's raw log (see "Emu probe #2
... ROOT CAUSE CONFIRMED for report #1" above, `tools/emu_partswitch.py --repro`), via
static RE + `watch_pc` on `FUN_400972fc` -- no genuinely-bound PICKUP voice, no real
capture, no `FW_LIVE_NIBBLE` observable ever needed. Everything from "FOUND -- and it
reframes the whole investigation" through the `0x400d7c4c` ownership-singleton
digression (this whole PICKUP-arena/ownership tangent) was answering a question -- "can
we fabricate a genuinely playing PICKUP voice in the emulator" -- that the fix doesn't
actually depend on. It is not wasted (the `FUN_400068e4`/kill-bit connection below is
real and useful), but it was the wrong next step at the time; re-reading the earlier
raw log first would have found the already-proven mechanism directly. Lesson for future
sessions: **the HANDOFF section is the authoritative *status*, but the raw log above it
can contain load-bearing technical answers the HANDOFF didn't restate** -- skim the raw
log for the specific mechanism in play before re-deriving it.

## Session 49 -- BUILD: `patch_partreapply` fix for report #1 + #2/#3, validated (emu A/B, NOT flashed)

**Confirmed the `FUN_400068e4` connection while chasing the fabrication tangent above is
real, not wasted**: static+emulator cross-reference (`grep` for `400068e4` across
earlier, pre-Session-49 raw log) shows it is the **same function** documented back then
as "the control-rate voice updater" that `DAT_8000184c` (the kill/re-trigger bit)
kicks -- confirming the kill-bit's target function does real per-voice arena/slot
resolution work (not *only* an AMP-envelope fade, as its narrower earlier
characterization suggested), lending confidence to the fix design below.

### The fix, built

`tools/patch_partreapply.s` + `tools/build_partreapply.py` -> `out/mainos_partreapply.bin`
(220 B cave, 6 B detour, `1.40C` version string unchanged). Implements the "REVISED
FINAL DESIGN" from earlier in this session exactly:
1. **Recorder memcpy, always** -- one 96-byte copy (`blob+newPart*0x18b2+0x8f382` ->
   `0x80000c94`), covers all 8 tracks' 12-byte records (both recorder-page halves) in
   one shot since both sides are contiguous per-Part blocks.
2. **Per track, `oldType==4 (PICKUP) && newType!=4`**: `0x8000184c |= 1<<track`.
3. **Once**: `move.l #-1,0x400c0c44` + `jsr FUN_4003f1b4` (scene morph retrigger).
4. **Only if `0x800065b8==0` (stopped)**: `jsr FUN_40009094(bank,newPart)`.

Detour: `0x40062216` (`jsr 0x400326a0`, the instruction right after the `sys` "select
Part P" handler's `FUN_400972fc`x8 loop) -> `jsr cave`; cave replays the displaced call
verbatim then `rts` (a "jsr"-kind detour per the house convention -- the site's own
return address resumes the caller correctly, no explicit resume `jmp` needed).

**Calling conventions re-derived fresh from real call sites** (per the standing "don't
trust a hand-counted read" caution): `FUN_40020898(dst,src,len)` -- 3 long stack args,
dst closest to the `jsr`; `FUN_40009094(bank,part)` -- 2 long stack args (each a
zero-extended byte), bank closest to the `jsr`; `FUN_4003f1b4()` -- no arguments. All
confirmed against real, unrelated call sites elsewhere in the image, not against
NOTES' own shorthand.

**Merge/interlock check (MERGE.md) before building**: detour site `0x40062216` and
every global touched (`0x8000184c`, `0x400c0c44`, `0x80000c94`, `0x800065b8`, the
`fp@(-9+track)` stack locals) appear in none of the 14 existing detour sites or the
shared/adjacent-state tables for the seven already-merged mods -- orthogonal, same
shape as Bug-2/QLREC ("detour one site nothing else touches, share no global"). Should
compose cleanly into `build_merged.py`'s cave-packing scheme when it's added there (not
done yet -- this session only produced the standalone build).

### Two assembler/build snags, fixed while building

- **GAS on this ColdFire target rejects `move.l #imm,<absolute>`** (immediate source +
  absolute-long destination) -- matches the REAL firmware's own avoidance of this form
  (`moveq #-1,d2 ; move.l d2,0x400c0c44` is what stock code actually does at the
  morph-guard reset site). Fixed the same way: load the immediate into a register first.
- None of the ColdFire-specific mnemonics needed (`mulsl`, the zero-extend idiom,
  `extb.l`, indexed addressing `-9(%fp,%d2.l)`) needed anything beyond GAS's normal
  m68k syntax once the right register-vs-immediate forms were used -- no CPU-support
  surprises despite the caution that would have been warranted.

### A pre-existing harness bug found and fixed while validating (not this fix's bug)

**`tools/emu_partswitch.py --repro`'s `press_key_live(KEY_STOP)` does not actually stop
the transport** (`0x800065b8` stays `1`) -- already flagged as a known, deferred issue
earlier in this session ("Emu --repro #4 ... Need a working STOP ... deferred"), but
never fixed before now. Consequence: with the transport left running, the switch below
it just gets *queued* for the step engine's next pattern boundary (thousands of frames
away) and never commits within the test's run budget -- `seq_select_live`'s own
readback kept showing pattern 0, not 4. **This made the very first fix-validation
attempt look like a total no-op on BOTH stock and patched images** (kill bitmap and REC
cache byte-identical, unchanged, in both) -- not because the fix was broken, but because
neither run ever executed a real switch at all. Diagnosed by watching PC hits at the
detour site directly (confirmed the cave *did* execute correctly, including the
kill-bit logic, in an isolated no-transport test) and then finding `seq now: ... pattern
0` in the full test's own printed output -- the switch commit itself was the untested
variable, not the fix. **Fixed**: replaced `rt.press_key_live(er.KEY_STOP)` with a
direct poke `rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")`, the same mechanism
every other probe this session already used reliably.

### Validated -- clean A/B, `tools/emu_partswitch.py --repro` (stock) vs `--repro
--patched` (patched), same PICKUP(Part0/T1) -> FLEX(Part1/T1) switch, transport
genuinely stopped before the switch (fixed harness), pattern confirmed committed
(`seq now: pattern 4`, `active part 0x80000003 = 1` in both runs):

| observable | stock | patched |
|---|---|---|
| kill bitmap `0x8000184c` | `0x00` (bug) | `0x01` (fixed) |
| REC cache `0x80000c94[T]` | `aa aa ...` marker survives (bug) | `60 61 62 63 64 65 66 67 68 69 6a 6b` -- Part 1's real record (fixed) |
| REC published `0x80000cf4[T]` | `aa aa ...` (bug) | `60 61 62 ... 6a 6b` (fixed) |
| `TRK_PART[0..7]` | `ff 00 ff 00 00 00 ff 00` (stale/mixed) | `01 01 01 01 01 01 01 01` (uniform -- bonus: step 4's `FUN_40009094` also fixes the scene/display consistency piece for every track, not just T) |
| `TRK_BANK[0..7]` | `ff 00 ff 00 00 00 ff 00` | `00 00 00 00 00 00 00 00` |
| `FUN_400972fc` fired for T (PC-HIT) | yes, x2 (both patterns' Part-apply loops) | yes, x2 -- unchanged, confirms the detour doesn't disturb the existing call |

Both runs confirmed via direct PC-hit hooks that the cave executes fully (detour ->
cave entry -> all 8 kill-check iterations -> cave return) with no crash, no hang, no
illegal instruction.

**Status: fix is emu-validated (stock-repro + patched-fix, S48-style), NOT flashed,
NOT added to `build_merged.py` yet.** Report #1 and #2/#3 (recorder) are both closed by
this build. The scene *aside* (Open_Mike's fourth report) and the `#3` sequencer-side
p-lock loader (`0x46c7aa24`, still unpinned) are covered by design (steps 3-4) but not
independently emu-confirmed this session -- lower priority, matches the original
HANDOFF's own prioritization.

**NEXT:** (1) add `patch_partreapply` to `build_merged.py`'s `CF_STUBS` list and
`reference/MERGE.md`'s allocation table (mechanical, per the interlock check above --
expect no conflicts). (2) HW pass once the MKI is back, per `FLASHING.md`'s ordering
convention. (3) if time allows, independently confirm the scene-morph retrigger
(step 3) and the `#3` p-lock loader with their own targeted emu probes, matching the
rigor applied to steps 1-2 here.

## Session 50 (2026-09-13, `wip`) -- HARDWARE PASS: Bug-2 CONFIRMED WORKING; PARTREAPPLY report #1's mechanism DOES NOT ADDRESS THE REAL BUG (stock == patched)

User has the MKI back and is working the flash queue in order (bug fixes first, per
the user's own priority pick, then DT -> sidechain -> DIRECTJUMP -> RELOAD). Two
toolchain/doc items first, then two flashes.

**Toolchain drift fixed:** `refs/octabam` had re-synced to a newer upstream commit
(`0ec42f3`) that reorganized `tools/` into group subdirs (`build/harness/emu/hw/verify`)
behind a new `toolpath.py` shim -- broke all 7 of our wrapper scripts that import
`emu_rtos`/`emu_card` the old flat way (`emu_rtos.py`, `emu_pattern_led.py`,
`emu_partswitch.py`, `emu_plock.py`, `emu_reload.py`, `diff_flex_static.py`,
`check_reccache_causation.py`). Fixed uniformly: each now does
`sys.path.insert(0, str(OCTABAM/"tools")); import toolpath` right after the chdir,
which lets octabam's own shim add the group dirs to `sys.path`; `emu_rtos.py`'s
`OCTA_RTOS` path also updated `tools/emu_rtos.py` -> `tools/emu/emu_rtos.py`. All
re-verified working post-fix (`emu_pattern_led.py --patched`, `emu_qlrec.py --patched`,
`emu_partswitch.py --repro[--patched]` all re-ran clean).

**`FLASHING.md` gained §4.8/4.9/4.10** (Bug 2 / PARTREAPPLY / QLREC hardware
checklists -- these three builds existed since Sessions 46/48/49 but had no HW test
procedure written down anywhere outside README's short blurbs). Quick-reference table
also gained their 3 rows.

### Bug 2 (pattern-LED) -- FLASHED, CONFIRMED WORKING, no regression

`OCTATRACK_PATTERNLED.bin` flashed via the CF-card path. User initially reported it
did NOT work (trigless-lock-only patterns still read as empty) -- this triggered a
deep re-investigation into the multi-view p-lock system (`#1` TRAC+0x59 vs the
`+0x4900` live-edit buffer vs `0x46c7d2e4`, revisiting the Session 24-39 "trigless
lock is derived, not flagged" thread) as the leading hypothesis (a live/uncommitted
lock wouldn't be in `#1`, which is all the fix scans) -- **but the user then retracted
the report: it was a false alarm, PATTERNLED is flashed and working as expected.**
README/FLASHING.md updated to "hardware-confirmed (MKI, 2026-09-13)". The p-lock
multi-view investigation was NOT completed/needed and produced no code changes; the
hypothesis (that a live, never-saved lock might not show because `#1` is only
disk-deserialiser-filled) remains an open, untested theory if this class of bug is
ever revisited, but is NOT currently believed to be a real problem.

### PARTREAPPLY -- FLASHED; report #1's fix mechanism does not touch the real bug

Before flashing, asked the user to recall + independently test the 3 Elektronauts
reports on **stock** firmware first. Result: **report #1 (PICKUP->FLEX stuck
loop) reproduces on stock; report #2 (recorder SRC/RLEN carryover) does NOT
reproduce; report #3 (REC SETUP last-tweak leak) reproduced once then stopped
manifesting after some save action** -- casting real doubt on whether #2/#3 are
genuine, reliably-reproducible stock bugs (the fix's evidence for them was a
scripted, single-path emulator test: `emu_partswitch.py --repro`'s poke-then-switch
proves the *mechanism* -- the pattern-change handler never touches the recorder
cache -- but not that this is what a real user hits, and #3 reproducing once then
"curing itself" doesn't match a deterministic always-broken code path at all).

User flashed PARTREAPPLY anyway and found a **new, more precise repro for report
#1**: T1 = PICKUP on Part A (silent, sample A "loaded"), FLEX + sample B on Part B.
**P1->P2: correct (plays sample B). P2->P1: correct. P1->P2 AGAIN: WRONG -- T1 now
plays sample A under the FLEX machine.** Works once, breaks on the *second* pass
through the same transition -- not the simple "always plays the old loop" the
original forum report implied.

This lands squarely on the piece the Session-49 HANDOFF had already flagged
UNVERIFIED/SUSPECT: `KILL_BIT` (`0x8000184c`) is documented in our own tooling
(`emu_partswitch.py`'s own comment) as a "voice AMP-kill / release trigger," and
`SLOT_MIRROR` (`0x100a519c`) is, per the same file's comment, normally written
**only** by stock's own PICKUP-entry branch (forcing `128+track`) -- our fix is the
only code path that ever writes a non-PICKUP slot number there. Built and ran a new
`emu_partswitch.py --repeat` mode (P1->P5->P1->P5 round trip against the factory
DEMO with the same PICKUP/FLEX poke, snapshotting the voice struct `0x800049d8+
T*0xA8` (`+0x50` bytes), `SLOT_MIRROR`, `KILL_BIT`, and applied-bank/part at both
arrivals at P5): **byte-identical between arrival #1 and arrival #2** -- rules out
those three registers going stale as the explanation, but is inconclusive on the
real mechanism because the probe only sits on the pattern and never drives an actual
trig; sample-buffer binding is almost certainly resolved DSP-side at trig time by
the still-unidentified "real per-trig resolver" (`FUN_40005030` was investigated
and ruled out in the original HANDOFF thread) -- something a ColdFire-only Unicorn
emulator cannot observe, same class of limitation as the side-chain compressor's
actual gain reduction.

**Asked the user to run the identical 4-switch round trip on STOCK. Result: stock
reproduces the EXACT same pattern -- good, good, then bug on the second P1->P2.**
**Clarified: the bug is a one-way LATCH, not a toggle** -- once it appears on the
second P1->P2, it stays broken on every subsequent P1->P2 (3rd, 4th, ...); it does
not alternate or self-correct. Consistent with some voice/buffer-binding state
getting permanently poisoned by the round trip through PICKUP, not a race that
happens to resolve correctly some of the time.
Separately, the user confirms no displayed-parameter discrepancy for #2/#3 on
either stock or the patched build (REC SETUP and other pages show correct values
consistently) -- another point against #2/#3 being real, reproducible bugs, on top
of the earlier stock-repro attempts failing/self-curing.

Stock and patched are **behaviorally identical** for this repro. Conclusion: **the
fix's report-#1 mechanism (kill-bit + slot-mirror write on the PICKUP->non-PICKUP
transition) does not address the real bug.** The original "confirmed on stock"
single-shot repro was almost certainly performed against an already-cycled
(non-fresh) track state, which is why it looked like a simple always-broken
symptom rather than this good-good-bug pattern. The fix is not harmful (matches
stock exactly on this test, doesn't make anything worse) but does not deliver the
value the HANDOFF's design intended for the case that actually matters.

**Status: PARTREAPPLY stays flashed** (harmless, and the recorder-cache /
scene-morph / stopped-full-reapply pieces are independent of this finding and
unaffected). **Report #1's real root cause is still open** -- needs fresh RE aimed
at the DSP-side / trig-time sample-buffer binding, not the ColdFire-side
Part-change handler this session's fix targeted. Reports #2/#3 remain unconfirmed
on stock and should not be assumed real without a cleaner repro. `tools/
emu_partswitch.py` gained `--repeat` (kept in `tools/`, not scratchpad).

**NEXT:** user's call -- either continue digging on report #1's real mechanism (a
new RE thread, likely needs driving an actual trig in `emu_rtos` post-switch and/or
a hardware register/memory dump at trig time), or shelve it and continue the
existing flash queue (QLREC next, then DT -> SIDECHAIN2/3 -> DIRECTJUMP v3 ->
RELOAD/RELOAD2). README/FLASHING.md's PARTREAPPLY status text needs a rewrite to
reflect this (currently still describes the original, now-superseded, "clean A/B"
framing) -- not yet done, flagged here so it isn't lost.

**User picked "move on" -- proceeded to flash QLREC next.**

### QLREC -- FLASHED, HUNG THE UNIT (recovered clean via power-cycle). Root cause FOUND.

Symptoms on real hardware: the toast opened (text visible, and reportedly showing
the *pre-toggle* value -- e.g. combo executed while PERSONALIZE read OFF produced
a toast saying "QUANT LIVE REC OFF", not ON) but **never closed, and the entire
front panel stopped responding to any key while the sequencer kept advancing** --
consistent with the UI/key-dispatch path being stuck, not a crash. User confirmed
the unit recovered cleanly with a plain power-cycle (no MIDI rescue needed -- the
flash image itself is fine, this was a runtime hang, not a corrupted OS). User
also confirmed the toggle-cycling INTENT is as designed: with REC held, repeated
PLAY double-taps should cycle QLR on/off/on/... (true of the built logic: every
even press flips, matching `patch_qlrec.s`).

**`tools/emu_qlrec.py`'s own validation could never have caught this** -- it maps
ONLY the two cave routines standalone and stubs `FUN_4005a2b8` (NOTIFY) and
`FUN_40056bec` (NOTIFY_CLOSE) to a bare `rts`, checking only that the cave CALLS
them with the right args. The real bodies were never executed. The "dur<=0 ->
persistent, no countdown, closed via `0x40056bec()`" characterization (NOTES
"Session 46") was pure static disassembly reading, never dynamically confirmed.

**Built `tools/emu_notify_probe.py`** to call the REAL `FUN_4005a2b8` in the
full-firmware emulator. First pass: both `dur=0x44` (the known-good self-timing
shape DIRECT JUMP v3/RELOAD2 use) and `dur=0` calls RETURNED (not an infinite
spin at the Unicorn level) -- but `dur=0x44` returned `d0=0x1` while `dur=0`
returned **`d0=0xffffffff`**, a real divergence worth chasing. (The probe's own
first-pass memory dump window was wrong -- centred on `0x460d1e00`, missing the
actual handle address `0x460d1e70` entirely by 0x70 bytes; showed nothing changed
because it was looking at the wrong bytes, not because nothing happened.)

**Real disassembly of `FUN_4005a2b8` (objdump, `out/raw/section_3_MAIN_OS.bin`,
base `0x40000400`) resolved it completely:**
- Entry: `d2`=text ptr, `d3`=dur. `tstl 0x460d1e70; beq skip; jsr 0x40056bec` --
  closes any EXISTING notification handle first (harmless, no-op if none).
- Opens a new window (`jsr 0x4005829c`), stores the returned handle into
  `0x460d1e70`, does some draw/text setup (`jsr 0x40057008`), sets a redraw flag
  `0x46c7c72c = 1`.
- `tstl %d3; bles 0x4005a334` -- **`dur <= 0` branches away BEFORE the normal
  return.** The `dur > 0` path (fall-through) stores the countdown into
  `0x460d1e6c` and does a plain `rts` with `d0` left at `1` from an earlier
  `moveq` -- matches the emulator's observed `d0=0x1`.
- **The `dur <= 0` path (`0x4005a334`) clears the countdown var, calls
  `0x40055d40`, overwrites its OWN stack argument slot with the constant
  `0x400ba9e0`, and TAIL-JUMPS (`jmp`, not `jsr`+`rts`) into `FUN_40031494`.**
  So our function's actual return value (the `0xffffffff` the emulator saw) is
  whatever `0x40031494` returns, not a value `FUN_4005a2b8` itself produces.
- **`FUN_40031494` is a linked-list INSERT into a global chain headed by
  `0x460d165c`** -- it takes the static struct at `0x400ba9e0` as a node, walks
  the list from the head, appends the node at the tail (or no-ops if it's
  already the head/already in the list), then `braw`s into `0x4003125c`. The
  `dur > 0` path never touches this list at all.

**Conclusion: `dur <= 0` doesn't produce a passive, always-visible banner --
it registers the notification on what looks exactly like a MODAL WINDOW /
OVERLAY STACK** (`0x460d165c` head, walked as a singly-linked list terminated
by clearing the new node's own next-pointer). The `dur > 0` self-timing path
(what DIRECT JUMP v3's toast and RELOAD2's toast both use, and what every
HW-confirmed prior toast in this project has used) never goes near this list.
**This is almost certainly why the whole panel stopped responding**: the OS's
real key/event dispatcher very likely routes input to the head of this modal
chain instead of the normal per-key jump table while it's non-empty, so our
own `qlr_recrel` detour -- itself hooked into the NORMAL per-key path at
`0x4004883a` -- never runs when REC is physically released, the close call
inside it (`jsr 0x40056bec`) never fires, the node never leaves the modal
chain, and nothing else responds either. The sequencer keeps advancing because
it's driven by a separate hardware-timer path, unrelated to this stuck
UI/key-dispatch chain -- exactly the observed symptom.

**This also likely explains, at least partly, the reported wrong-polarity
toast** -- though the assembly's own message-selection logic (`patch_qlrec.s`)
re-reads `QLR` AFTER the flip and picks the string for the NEW value, which is
correct on its face; a stuck modal chain from an EARLIER attempt during the
same confused hang session could easily throw off the user's tap count,
so this is not being treated as a separately-confirmed bug pending a clean
re-test.

**Root cause: `dur=0` was the wrong mechanism for "stays visible while a key is
held, no fixed timer" -- that specific requirement wants something that never
touches `0x460d165c`.** A `dur > 0` self-timing toast is the only path this
project has ever HW-confirmed as non-blocking. Candidate fix, NOT yet built:
**periodically re-arm a short positive `dur`** (re-issue
`FUN_4005a2b8(msg, small_dur)` every so often, e.g. from the same per-frame
splice DIRECT JUMP v2/RELOAD2's `rl_tick` used, refreshing the countdown before
it expires) while REC stays held, and simply STOP re-arming on release so it
dies on its own timer shortly after -- this stays entirely in the `dur > 0`
branch and never touches the modal list. Loses the "no timer at all, disappears
the instant REC releases" ideal (there'd be a brief tail after release) in
exchange for not hanging the unit. Alternative not investigated: is there a
genuinely different, confirmed-non-modal "status banner" primitive elsewhere in
the firmware better suited to an always-visible indicator.

**Status: QLREC build is UNSAFE as currently written (build_qlrec.py /
patch_qlrec.s unchanged since Session 46) -- do not reflash until the toast
mechanism is redesigned around a `dur>0` re-arm and re-validated.** New tooling
this session: `tools/emu_notify_probe.py` (kept in `tools/`).

**NEXT:** redesign `patch_qlrec.s`'s toast to a periodic `dur>0` re-arm (needs a
per-frame or per-tick splice to call NOTIFY repeatedly while REC is held --
`patch_reload2.s`'s `rl_tick` @ `0x400522ca` is the existing precedent for this
kind of splice); re-validate with `emu_qlrec.py` (isolation) AND a full-firmware
`emu_rtos` pass that actually drives the real NOTIFY/NOTIFY_CLOSE bodies (S48-style,
what this session's `emu_notify_probe.py` started); only then consider reflashing.

### QLREC REWRITE -- BUILT + VALIDATED (isolation + dynamic full-firmware), NOT YET REFLASHED

User asked to build the fix immediately. `tools/patch_qlrec.s` rewritten:

- **`qp_show` (qlr_play's flip branch):** now calls `NOTIFY(text, REARM_DUR)`
  (`REARM_DUR = 0x30`, a `.equ`, NEVER `dur<=0`) instead of `NOTIFY(text, 0)`.
  Also stashes the shown string pointer in new scratch `G_LASTMSG` and arms a
  new countdown `G_RTICKS := REARM_INTERVAL` (`0x18`), then sets `G_ARM` (the
  renamed `G_OURS` -- same address `0x80006a60`, meaning shifted from "we own a
  toast, close it on release" to "keep re-arming it").
- **New `qlr_tick`, detour of `0x400522ca`** (the engine's per-control-frame
  handler that decrements the SOFT MUTE release watchdog -- the exact site
  DIRECT JUMP v2's `dj_tick2` already uses, ticks every frame whether playing
  or stopped): if `G_ARM` is set, counts `G_RTICKS` down; at/below 0, re-issues
  `NOTIFY(G_LASTMSG, REARM_DUR)` and resets the counter, refreshing the toast
  well before its `dur` would expire. `jsr`-kind detour (site is inline code,
  not a function entry) -- replays the displaced `lea 0x46c7dfba,%a2` and
  `rts`s, matching `dj_tick2`'s exact convention including saving D0-D1/A0-A1
  around the `jsr NOTIFY` (that call may itself route through kernel post, the
  same reason `dj_tick2` protects those regs around `jsr FUN_40056bc0`).
- **`qlr_recrel` simplified:** no longer calls `NOTIFY_CLOSE` at all -- just
  clears `G_ARM` (stop re-arming). The current `dur` runs out on its own within
  `REARM_DUR` frames, the same self-close every other toast in this project
  already relies on. Net effect: toast shows while `[REC]` is held (refreshed
  before it can expire), fades a short bounded moment after release instead of
  clearing instantly.
- Hit the same GAS gotcha Session 49 already documented (`move.l #imm,<absolute>`
  rejected on this target) twice in the new code -- fixed the same way, load the
  immediate into a register first.
- New scratch: `G_RTICKS` `0x80006a64` (long), `G_LASTMSG` `0x80006a68` (long) --
  QLREC's claimed range is now `0x80006a5c-0x80006a6b`, still disjoint from
  MUTE MODE / DIRECT JUMP / RELOAD2 (not yet reflected in `reference/MERGE.md`,
  which still shows the old two-word range -- flagged, not yet fixed, since
  QLREC isn't folded into `build_merged.py` yet anyway).
- `tools/build_qlrec.py` gained the third detour
  (`0x400522ca`, `"45f946c7dfba"` = `lea 0x46c7dfba,%a2`, `jsr`-kind, matching
  `build_directjump_v2.py`'s exact convention for this same site). Builds
  clean: `mainos_qlrec.bin` 315 B vs stock (cave 262 B @ `0x400d7400`), round-trip
  + checksum OK, Bug-1 fix byte-identical, version stays `140C_KYOTI`.

**`tools/emu_qlrec.py` rewritten** (still isolation-only, the two/now-three cave
routines against real assembled bytes, OS calls stubbed to `rts`): `test_play`
now asserts `notify_dur == REARM_DUR` (never 0) and that `G_LASTMSG`/`G_RTICKS`/
`G_ARM` are armed correctly; `test_recrel` asserts `NOTIFY` is never called and
`G_ARM` clears; new `test_tick` covers not-armed passthrough, mid-countdown
decrement, the re-arm-at-zero case (including an already-negative/stale
`G_RTICKS`), and that the displaced `lea` always replays regardless of path.
**ALL GOOD.**

**`tools/emu_notify_probe.py` rewritten for a direct, unconditional dynamic
check** (first draft's "diff the modal list head" heuristic was flawed -- the
head `0x460d165c` is ALREADY non-null at boot from something unrelated, and
insertion happens at the list's TAIL, so the head never visibly moves either
way; not evidence of anything). Fixed by PC-hit-watching the modal-insert
function itself (`0x40031494`) directly across three full-firmware boots of
`mainos_qlrec.bin`:

| `dur` passed to `FUN_4005a2b8` | reached `0x40031494` (the modal-insert fn) |
|---|---|
| `0` (the ORIGINAL, hung a real MKI) | **YES** |
| `0x44` (DIRECT JUMP v3's known-safe dur) | no |
| `REARM_DUR` = `0x30` (what the rewrite actually uses) | **no** |

This is a clean, direct, dynamic confirmation -- not just the static disassembly
reading -- that the rewritten toast never executes the code path that hung the
unit, using the same real function bodies a flash would run. Combined with the
control-flow fact that `tstl %d3; bles <modal path>` is an unconditional branch
on the `dur` argument itself (so this result cannot be state-dependent luck),
this is about as strong a pre-flash guarantee as the emulator can give for this
specific failure mode.

**Status: fix built, isolation-validated, and dynamically confirmed off the
modal path. NOT YET REFLASHED.** `REARM_DUR` (`0x30`) and `REARM_INTERVAL`
(`0x18`) are conservative starting guesses -- the frame-to-ms ratio of the
`0x400522ca` tick was never pinned, so the actual on-screen refresh cadence and
the post-release fade delay need an HW eyeball pass and possibly a tuning
pass, same class of open item as DIRECT JUMP v3's `DJ_TOAST_DUR` "feel right on
HW" note. New tooling this session, all in `tools/` (not scratchpad):
`tools/emu_notify_probe.py`. FLASHING.md/README updated to describe the
rewrite; still marked as needing a fresh HW pass before calling it confirmed.

### QLREC -- Session 51 (same day): FLASHED, NO HANG. Six follow-up requests, four fixed, two scoped as follow-up RE.

The Session 50 rewrite (periodic `dur>0` re-arm) was flashed. **No hang** --
the fix works. User reported six refinements from real use:

1. **Double-tap timing feels wrong in a specific way**: an "extra slow" first
   pair of taps does NOT trigger, but a 3rd tap landing close to the 2nd then
   DOES -- so it can feel like "3 taps did it" when really it was taps 2+3.
   Took two rounds of clarifying questions to pin down (first framing
   suggested loosening an existing window; it turned out there was NO timing
   window anywhere in the Session 50 code at all -- G_CNT just counted
   absolute presses with zero time-awareness, so this was describing wanted
   behaviour, not a bug in existing behaviour). **Confirmed design: two
   presses count as THE double-tap only if the second follows the first
   within a pairing window; a too-slow pair is discarded entirely (no flip)
   and the late press becomes the start of a fresh pairing attempt** -- i.e.
   exactly "disregard both, wait for two more that are fast enough."
2. **Toast fade time ~1/3 too long** -- `REARM_DUR` `0x30`→`0x20`,
   `REARM_INTERVAL` `0x18`→`0x10` (kept at exactly half of `REARM_DUR`, same
   margin ratio as before).
3. **Occasional small textless square flashes where the toast was, right
   after it closes, self-clearing.** NOT chased this session. Most likely
   explanation: `FUN_4005a2b8`'s own entry always closes any existing handle
   before opening a new one (`tstl 0x460d1e70; jsr NOTIFY_CLOSE` if set) --
   this project is now the first mod to open/close this specific notification
   anywhere near as often (periodic re-arm, now also an explicit close on
   release per item 4), so a draw/erase-ordering quirk in the stock
   open/close sequence that was never visible before (single-shot,
   multi-second toasts elsewhere in this project) may simply be showing up
   now. Confirming this needs pixel-level RE of `0x4005829c`
   (open)/`0x40057008` (text setup)/`0x40056bec` (close), not attempted.
   Flagged as a known, benign, self-clearing cosmetic quirk pending further
   investigation if it turns out to matter.
4. **Toast should close instantly on `[REC]` release, not fade out.** Fixed:
   `qlr_recrel` now calls `NOTIFY_CLOSE` again (it did, pre-Session-50). Safe
   now in a way it wasn't before: the reason `NOTIFY_CLOSE` was dropped in
   Session 50 was never that calling it was unsafe -- it was that our
   `[REC]`-release handler never got a chance to RUN AT ALL once `dur<=0`
   registered the modal entry. Since `dur` is now never `<=0`, that modal
   registration never happens, so the release handler reliably fires (borne
   out by the Session 50 flash working without a hang) and the close call is
   exactly as safe as what `NOTIFY` already does internally before every
   open.
5. **Menu doesn't visually update while looking directly at the PERSONALIZE
   row that changed** (re-opening the menu shows the correct value -- this is
   a stale on-screen widget, not a stale stored value). NOT fixed this
   session. There's a known-safe redraw sequence elsewhere in this codebase
   (`patch_reload.s`'s `rl_parts`: `FUN_4004aab4` + `SCN_RFRSH`/`RFRSH1..6` +
   `RDRAW`), but it was built and validated for a call site reachable only
   from a dedicated picker overlay (`[YES]` while the RELOAD window is open)
   -- a narrow, known UI state. Our combo can fire from ANY screen, so
   blindly reusing that sequence risks a NEW, different hang from calling
   redraw machinery outside the UI context it assumes, which is not a risk
   worth taking for a cosmetic issue right after the Session 50 hang. Proper
   fix needs the specific "PERSONALIZE row N is dirty" mechanism, not a
   borrowed generic redraw combo -- scoped as follow-up RE, not attempted.
6. **Toast label was backwards vs the menu**: HW-confirmed the PERSONALIZE
   checked/unchecked glyph is the OPPOSITE of the Session 46 write-up's
   assumed "raw 0 = OFF" -- raw `0` actually draws as the row's checked/ON
   state. Fixed by swapping which string `qp_show` picks for a given raw
   value (`0` -> now shows `qlr_msg_on`, nonzero -> `qlr_msg_off`) -- the flip
   mechanics and the raw bit's meaning to the OS are completely unchanged,
   only the label was wrong. Worth propagating this correction if `0x800000ac`
   is ever referenced elsewhere as "0 = OFF" (a `kb/` grep found none as of
   this session).

**Implementation (`tools/patch_qlrec.s`):** new scratch `G_WINDOW`
(`0x80006a6c`, long) -- QLREC's range is now `0x80006a5c-0x80006a6f`, still
disjoint from every other mod (not yet reflected in `reference/MERGE.md`,
same pre-existing gap as the Session 50 `G_RTICKS`/`G_LASTMSG` addition;
QLREC isn't in `build_merged.py` yet). `qlr_tick` decrements `G_WINDOW` once
per frame whenever `REC_HELD` and a hold is in progress (`G_CNT != 0`),
independent of `G_ARM`/toast state -- this is what makes the window actually
expire over elapsed time rather than elapsed presses. `qlr_play`'s parity
check (odd/even press count) is GONE, replaced by a `G_WINDOW <= 0` check.
Hit a new assembler snag: `qlr_play` grew enough that its very first branch
(`beq.b qp_stock`) went out of 8-bit range -- fixed by dropping the `.b` size
suffix and letting GAS pick a wider encoding.

**Re-validated:** `tools/emu_qlrec.py` rewritten for the pairing-window model
(fast-pair flip / slow-pair discard-and-reset / window-independent-of-G_ARM
decrement / inverted label) -- **ALL GOOD**. `tools/emu_notify_probe.py`
re-run against the rebuilt image with the new `REARM_DUR`/message addresses --
[result pending / see below]. Builds clean: `mainos_qlrec.bin` 366 B vs stock
(cave 318 B @ `0x400d7400`), round-trip + checksum OK, Bug-1 fix
byte-identical, version stays `140C_KYOTI`.

**Status: built, isolation-revalidated. Items 1/2/4/6 addressed; items 3/5
explicitly scoped as follow-up RE, not attempted this session. NOT YET
REFLASHED** -- `MAX_GAP` (`0x10`) is a fresh, completely untuned guess (same
caveat as `REARM_DUR`/`REARM_INTERVAL`) and needs a real hardware feel-test,
likely several iterations, same as `DJ_TOAST_DUR` needed.

### QLREC -- Session 51-bis (same day): a real bug in item 1's fix, found before reflashing

User reported two more real-use symptoms against the Session 51 build (not yet
flashed, so these came from further scrutiny/description, not a fresh flash):

1. **"Sometimes after two fast taps and execute, a third fast tap will also
   execute."** Real logic bug, found on inspection: `qp_play`'s flip branch
   fell through into `qp_rearm_window`, which unconditionally re-armed
   `G_WINDOW` to `MAX_GAP` -- meaning immediately after a flip, the window
   looked exactly as "fresh" as it would for a genuinely NEW pending press.
   A fast press right after the flip would see `G_WINDOW > 0` and complete a
   "pair" **with the flip itself**, firing an unwanted extra toggle. **Fix:**
   new explicit `G_PEND` byte (`0x80006a70`) tracking "is a press genuinely
   waiting for its partner" as a state distinct from the window's numeric
   value. A flip now clears `G_PEND`; `qlr_play` checks `G_PEND` before ever
   consulting `G_WINDOW`; only `qp_rearm_window` (the "no pending press yet,
   or the pending one expired" path) sets `G_PEND`. `qlr_recrel` clears it
   too. `qlr_tick`'s window decrement is now gated on `G_PEND` instead of
   `G_CNT != 0` (more precise: right after a flip `G_CNT` is still nonzero
   but nothing is genuinely pending). Two more `beq.b`/`.b` branches went out
   of 8-bit range as the function grew again -- same fix as before, drop the
   size suffix.
2. **"Also, three slow taps will execute" / "Don't want that."** Distinct
   from item 1 -- this isn't the same re-arm bug (traced through both the old
   and new logic: a genuinely slow gap, exceeding `MAX_GAP` in real ticks,
   should never let a press complete a pair, before or after the G_PEND fix).
   Most likely explanation: `MAX_GAP` (`0x10` ticks) simply represents MORE
   real-world time than what the user considers "slow" -- there is no way to
   derive the real tick-to-ms ratio of the `0x400522ca` per-control-frame
   handler from here, so this was always going to need on-hardware iteration
   (flagged as such when `MAX_GAP` was first introduced). Cut to `0x08` (half)
   as the next guess -- explicitly presented to the user as a guess needing
   their feedback, not a confident fix.

**Re-validated:** `tools/emu_qlrec.py` gained explicit `G_PEND` coverage (a
flip clears it; a press with `G_PEND=0` can never flip regardless of how
"fresh" `G_WINDOW` looks; `qlr_tick`'s decrement only fires when `G_PEND=1`)
-- **ALL GOOD**. The modal-path safety property from Session 50/51 is
architecturally untouched by either fix (neither touches what `dur` value
reaches `NOTIFY`) -- `tools/emu_notify_probe.py` re-run against this exact
rebuild for the record anyway (matching message addresses/`REARM_DUR`
unchanged since neither fix altered code size in a way that moved them).

**Status: built, isolation-validated, NOT YET REFLASHED.** `MAX_GAP=0x08` is
still an unverified guess -- expect another round of feedback after this one.

### QLREC -- Session 51-ter (same day): the 0x08 guess was wrong direction, reverted

Flashed the Session 51-bis build. HW feedback: "Now it doesn't work at all -
no execution", then corrected to "it does work, but the double tap has to be
WAY too fast to execute." Confirms `MAX_GAP=0x08` was simply too tight --
real fast double-taps no longer land inside the window.

This also retroactively explains item 2 from Session 51-bis ("three slow taps
will execute"): that symptom was fully accounted for by the `G_PEND`
re-arm-on-flip bug fixed in the same session (a slow 3rd tap was pairing with
a *stale flip*, not exploiting a genuinely generous window) -- traced through
the logic at the time and never actually reproduced via a MAX_GAP-width
argument. Cutting `MAX_GAP` in half was an unnecessary second change riding
along with the real fix, and it broke normal use.

**Fix:** `MAX_GAP` reverted `0x08` -> `0x10` (the value already known to work
for genuine fast double-taps in the Session 51 hardware round, before this
detour). `G_PEND` fix is untouched/kept. Cave layout unchanged (single
immediate operand, same instruction size) so `tools/emu_notify_probe.py`'s
prior PASS result still holds without re-running. `tools/emu_qlrec.py`
re-run -- **ALL GOOD**.

**Status: built, isolation-validated, NOT YET REFLASHED.** Expect this to
behave like the pre-0x08 Session 51 build for tap feel, now without the
G_PEND-caused "3rd tap also fires" bug. If `0x10` still isn't quite right,
next tuning should treat "too fast to land" and "too easy to land" as the
signal to move `MAX_GAP` up/down respectively, independent of the G_PEND
fix -- the two are now decoupled.

**HW-CONFIRMED GOOD** (flashed, same day): double-tap timing, toast fade
timing/instant-close-on-release, and the ON/OFF label polarity all confirmed
correct on real MKI hardware. `MAX_GAP=0x10` + the `G_PEND` fix is the
keeper. Items 3 (occasional textless-box flash after toast close) and 5
(PERSONALIZE row doesn't live-redraw) remain parked as explicitly scoped
follow-up RE, not attempted -- user confirmed fine leaving both as known
cosmetic issues for now. QLREC is DONE for this pass.

---

## Session 52 (2026-09-13, `wip`) — MUTE MODE DT: real root cause of "DT does nothing" + "OT+FX blip is back"

First-ever hardware flash of `patch_softmute.s` V7 (the version on `wip/mute-mode` --
solo support + the DT 3rd mode -- previously emulator-verified only, per the Session 11
branch note). Flashed `build_mutemode_dt.py`'s output. HW report:

- **DT: "does not work at all. Muting on the HW does nothing."**
- **OT+FX: "partially working (hard cut + fx tails)... trigs on the track are still
  sounding a very short blip like the very first few samples are being played, even
  though the track is muted. I thought we identified this blip during earlier
  development and fixed it, so I'm confused why it's back."**

### Root cause (found by disassembling the real caller, not by guessing)

`pre_v`'s hook on `FUN_40005178` (the voice-command queue) decided "is this a fresh
voice start I should drop for a muted track?" purely from the `cmd` value's bits: bit
0x80 set AND bit 0x10 clear. That heuristic was **never actually correct** -- it happened
to work for whatever narrow case was tested at the time (V6, Session 9), and nobody had
disassembled the real caller to check it held in general.

Disassembled `trig_to_voice` (`0x400977cc`, `FUN_400977cc` -- the sequencer-step-trig to
DSP dispatch, `reference/kb/memory-map.md` L56). It reads the track's machine type via
`FUN_40097168` (`0=STATIC, 1=FLEX, 4=PICKUP`, memory-map.md L121) and encodes the voice
command **completely differently per machine type**:
  - **STATIC**'s own normal step-trig command is `(position-derived value) | 0x10` --
    bit 0x80 is CLEAR, so it never even reached the old "is this a start" check.
  - **FLEX**'s own normal step-trig command is `(position-derived value) | 0x8010` --
    bit 0x10 is SET, so the old filter's "bit 0x10 = a safe stop/retrig, let it through"
    assumption whitelisted it too.
  - Only a narrow fallback path (other/rare machine-type + trig-type combos) actually
    sends the literal `cmd=0x80` the filter was built around.
Net effect: **ordinary sequencer trigs on the two most common machine types never hit
the drop path at all.** DT (which relies on `pre_v` alone, no note-off) suppressed
nothing -- exactly "muting does nothing." OT+FX's `pre` hook still note-offs/cuts the
dry signal a frame later, so it isn't silent, but the attack the drop was supposed to
prevent gets through every time -- the blip was never actually fixed, regardless of what
the Session 9/10 write-up hoped; NOTES.md never actually recorded an explicit
hardware re-confirmation of "no blip" after V7 (solo support) rewrote this hook, and
this DT flash was the first time V7's `pre_v` ran on real hardware at all (branch note,
Session 11).

### Fix -- discriminate by CALLER, not by cmd bits

Scanned `trig_to_voice`'s body for every `jsr FUN_40005178` and found exactly two:
return addresses **`0x400978a2`** (the `iVar1==2, param_2==3` branch, paired with a
`FUN_40005030` reset call) and **`0x400978dc`** (the shared tail servicing every
STATIC/FLEX/PICKUP/etc. "start" case). Those two return addresses are the *only* two
places in the whole ROM that ask "make this track's machine do something in response to
a trig" -- everything else that calls `FUN_40005178` (`FUN_40083544` / `FUN_400836d8`,
the mute/solo/QUICK-MUTE UI bookkeeping, including "a track resumes on its next trig
after unmute/un-solo") is calling it for unrelated bookkeeping and must NOT be touched
(filtering those by accident would break unmute-resume).

`pre_v` now reads its own return address off the stack (`(0x10,%sp)`, since the caller's
args shift by the 0x10-byte register-save reservation) and only applies the mute/solo
drop when it equals one of those two addresses -- the cmd-bit checks (`btst #7`/`#4`)
are gone entirely. `.equ TTV_CALL1, 0x400978a2` / `TTV_CALL2, 0x400978dc` in
`tools/patch_softmute.s`. `pre` (the dry-cut/FX-ring/DT hook) is untouched -- this was
always a `pre_v`-only bug.

### The isolation tests had the same blind spot as the bug

`tools/emu_solo.py` and `tools/emu_dt.py`'s `run_v()` pushed a fake, arbitrary return
address (`0xDEAD0000`) for every test case -- meaning a caller-address-based fix and the
original caller-blind bug were *indistinguishable* to these tests; they would have
happily passed either way. Rewrote both: `run_v()` now takes an explicit `ret=`, default
`TTV_CALL2`. Added the tests that actually pin the fix down:
  - `STATIC_START=0x7010` / `FLEX_START=0x8010`-shaped cmds from a `trig_to_voice`
    return address on a muted track -> **must still DROP** (this is the exact case that
    slipped through before -- a regression test that fails loudly on the old filter).
  - Both real `trig_to_voice` return addresses independently drop correctly.
  - A call from an arbitrary non-`trig_to_voice` return address (stand-in for
    `FUN_40083544`/`FUN_400836d8`) on a MUTED track -> **must still PASS** -- proves the
    fix didn't overcorrect into breaking unmute-resume.
`tools/emu_solo.py` (plain + `--dt`) and `tools/emu_dt.py` -- **ALL GOOD**.
`tools/emu_mutemode.py` only ever targeted the plain 2-mode image (menu-array addresses
differ in the DT build); unaffected by this fix, re-run for the record -- ALL GOOD.

**Status: both `out/OCTATRACK_OS1.40C_MUTEMODE.syx` and
`out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx` rebuilt, isolation-revalidated. NOT yet
reflashed** -- this is a caller-address fix grounded in real disassembly, not a
guess, but the actual "does the blip fully close now, does DT actually suppress new
trigs now" answer is still a hardware question. Also worth re-checking on next flash:
the `0x400978a2` call site (cmd `0xf010`, paired with a `FUN_40005030` reset) is a rare
machine-type/trig-type combo whose real audible effect on a muted track was not
specifically hardware-exercised this session.

**SUPERSEDED same day (Session 53) -- the caller-address fix above was FLASHED and made
ZERO difference on hardware** (identical symptoms: DT still silent, OT+FX blip
unchanged). `trig_to_voice`/`FUN_40005178` turned out to be a real function that is
simply never reached by ordinary sequenced trigs at all -- see Session 53 below for the
actual mechanism and fix.

---

## Session 53 (2026-09-13, `wip`) -- the REAL per-trig voice-start, found by driving the firmware instead of re-reading decompiles

Session 52's fix changed nothing on hardware. Instead of re-reading static decompiles
again, drove the ACTUAL firmware in the full-firmware Unicorn emulator
(`refs/octabam`) through real LOAD PROJECT + real sequencer playback and watched what
genuinely happens on a real trig.

### Falsifying Session 52's whole premise

`tools/emu_mute_dynamic5.py`: booted the DT image, loaded the factory OT DEMO, played
for 6s. **79 real trig events fired across multiple tracks and `FUN_40005178` was
entered ZERO times** -- neither of the two "voice command mailbox" addresses its body
writes was ever touched. `trig_to_voice` -> `FUN_40005178` is real code, reachable from
somewhere (the mute/solo UI bookkeeping, `FUN_40083544`/`FUN_400836d8`), but simply
uninvolved in ordinary sequenced trigs. Session 52's fix was 100% correct engineering
aimed at 100% the wrong target -- which is exactly why reflashing it was a no-op.

### Finding the real path

Traced the actual trig signal (`FW_LIVE_NIBBLE`, `0x46104d15` -- the byte a real trig
genuinely flips, independently confirmed via `install_trig_log`) back through LIVE
EXECUTION by capturing the PC of the instruction that writes it
(`emu_mute_dynamic6.py`). That landed inside a sequencer step-evaluator around
`0x4000b700` -- real, but a dead end: no `jsr` to anything resembling a voice start
within ~0x700 B, and no `MUTE_STATE` test anywhere in it.

Went looking from the other end instead: `diff_flex_static.py`'s own bind-detection
logic already treats the per-track voice struct (`0x800049d8 + track*0xA8`) as the
"did a voice really start" ground truth. Watched writes to its `+0`(active)/`+8`
(SETTINGS) fields across a full 6s run (`emu_mute_dynamic7/8.py`) and found the field
that's actually written **at every one of the real trig frames** (not just once, as an
earlier truncated read of the log wrongly suggested): `+0x04`/`+0x08`, written from
`0x4000f4dc`/`0x4000f4e0`, and a separate `+0x90` per-track counter written from
`0x4000687c`.

Statically disassembling around those writer PCs (`m68k-elf-objdump -m 5307` -- **the
default `-m 68000` mis-decodes ColdFire's 4-byte 32x32 `muls.l`/`mulu.l` and cascades
2-byte-misaligned garbage for the rest of the function; use `-m 5307` for anything in
this ROM**) mapped the real call chain:

  - **`0x4000f454`-ish**: the arena-rebind step. Computes which `FLEX_ARENA`
    (`0x100b14f0`) / `STATIC_ARENA` (`0x100d5b30`) entry this track's machine should
    point at and writes it to the voice struct's `+0x04`/`+0x08` -- **runs
    unconditionally on every trig, muted or not, with no MUTE_STATE test anywhere**.
    This is harmless bookkeeping (a pointer-cache reassert), not itself audible.
  - If (and only if) the desired sample differs from what's currently bound in that
    arena slot, it calls `jsr FUN_40006820(track)`.
  - **`FUN_40006820`**: an 8-track fan-out -- `track<8` falls straight through to the
    real per-track work; `track==8` recurses over 0..7.
  - **`FUN_40006844`**: the REAL per-trig voice starter. Raises IPL
    (`movew sr,d2`/`movew #0x2700,sr`), clears the voice struct's `active` byte, bumps
    the `+0x90` counter (confirmed: increments every FRAME this track runs, not just on
    trigs -- an earlier read of the log mistook consecutive frame numbers for a trig
    counter), then **`jsr FUN_4000672c`** -- confirmed dynamically to be the actual
    "restart the sample" step (its own body reads the SAME `REL_STATE` word `pre`
    already maintains, `0x8000184a`) -- before restoring SR and returning. **No
    MUTE_STATE test anywhere in this whole chain.**

### The fix

`patch_softmute.s` hook 2 is now **`mt_trig`**, detouring `FUN_40006844`'s own entry
(its first two instructions, `movew sr,d2` + `movew #0x2700,sr`, exactly 6 B -- the
same lucky fit every other hook in this project has had). Same GATE/MUTE_STATE/
SOLO_FLAG logic as before, now correctly placed: for a silenced audio track, return
*before* the active-clear, the counter bump, or the `FUN_4000672c` call that actually
restarts the sample -- nothing left to blip. `pre_v` and its `TTV_CALL1`/`TTV_CALL2`
constants are gone entirely. `build_mutemode.py`/`build_mutemode_dt.py`'s detour list
updated (`0x40006844`, expected bytes `40c246fc2700`, 6 B).

### A real bug the isolated unit tests could not see, caught only by dynamic validation

First version of `mt_trig`'s "drop" path was a bare `move.l d3,-(sp)` / early `rts`.
**This crashed the emulator instantly the first time it ran against real playback**
(`unhandled exception 4` / illegal instruction) -- while every isolated unit test
(`emu_solo.py`, `emu_dt.py`) had passed. Root cause: `FUN_40006844` is reached from
`FUN_40006820`'s body via a plain `bccs` branch, not a fresh call -- so
`FUN_40006820`'s own prologue (`movel a2,-(sp)` / `movel d2,-(sp)`) is STILL live on
the stack underneath the real return address when our detour runs, and its real
epilogue (`movel sp@+,d2` / `moveal sp@+,a2` / `rts`) is what actually unwinds it. An
early `rts` that only popped our own scratch push left those 2 extra longs on the
stack, so `rts` jumped to garbage. The isolated tests missed this because they entered
`mt_trig` directly with a single bare return address and nothing simulating that
caller frame beneath it. Fixed: `mt_silenced` now pops the same 2 longs
(`FUN_40006820`'s saved D2/A2) the real epilogue would, before its `rts`. Rewrote both
harnesses to simulate that real stack frame (sentinel D2/A2 values, checked restored;
final SP checked against the exact expected depth) -- this exact bug is now a
regression test, not just a fixed instance.

### Decisive dynamic validation (not just isolation)

With the stack fix in place, re-ran the full real-playback scenario
(`emu_mute_dynamic9.py`, then a direct instrument of `mt_trig` itself --
`emu_mute_dynamic11.py` -- and finally a direct watch on `FUN_4000672c`'s own entry --
`emu_mute_dynamic12.py`) with the FLEX track muted *before* any trig fires:
  - No crash (confirms the stack fix).
  - `mt_trig` took the `silenced` branch **100% of the time** for the muted track,
    every single frame it ran, `pass` 0 times -- confirmed by direct instrumentation,
    not inferred.
  - `FUN_4000672c` (the actual sample-restart) was called **zero times** for the muted
    track across 18 real trigs and 6 s of playback, while the three other active
    tracks got 100,000+ calls between them in the same window -- **PASS**.
  - (The `+0x04`/`+0x08` arena-rebind writes DO still happen for a muted track every
    trig -- confirmed this is expected and harmless: that step runs unconditionally
    upstream of `mt_trig`'s check, has no audible effect on its own, and was never the
    thing this fix needed to gate.)

Isolation tests (`emu_solo.py` ×2 images, `emu_dt.py`, `emu_mutemode.py`) all rewritten
for `mt_trig` and re-verified -- **ALL GOOD**, including the new stack-frame regression
coverage.

**Status: both `out/OCTATRACK_OS1.40C_MUTEMODE.syx` and
`out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx` rebuilt with the real fix. Isolation-verified
AND dynamically verified against real playback (not just unit-tested in isolation this
time). NOT yet reflashed.** DT mode shares the identical `mt_trig` mechanism (same
GATE/MUTE_STATE logic, `gate==2` path covered by the same isolation tests) but has not
had its own dedicated dynamic full-playback validation run this session -- user asked
to fix OT+FX first and return to DT afterward.

**FLASHED (2026-09-13) -- STILL NO CHANGE.** Blip unchanged, DT still fully silent.
Confirmed this was not a stale-build or wrap/flash mismatch: decoded the actual `.syx`
back through `elektron-firmware-tool`'s own extract path and diffed the recovered
`section_3_MAIN_OS.bin` against `out/mainos_mutemode_dt.bin` (what the emulator
tested) -- **byte-identical**. The deployed firmware genuinely contains the validated
fix. User confirmed testing with both STATIC and FLEX machines, ruling out a
machine-type gap. Conclusion: `mt_trig`'s proof, while real and dynamically confirmed,
is CPU-side only -- this ColdFire-only emulator (`refs/octabam`) has no DSP model at
all, so it is structurally blind to whatever the DSP actually watches to decide
"restart this voice." Exactly the class of trap `refs/octabam/CLAUDE.md` warns about
generally ("a measurement can be structurally blind to the thing you are using it to
rule out") -- now hit specifically on the audio-trigger question.

### Session 53-bis (same day) -- `mt_rebind`: gate the one remaining unconditional DSP-visible write

User directed: try gating the arena-pointer rebind write too (the `0x4000f4dc`/`e0`
write inside the `0x4000f454`-ish caller, established in Session 53 to run
unconditionally on every trig with no MUTE_STATE test anywhere upstream of
`mt_trig`). Working hypothesis: the DSP may watch THIS write -- the only DSP-visible
state that changes on every trig regardless of what `mt_trig`/`FUN_4000672c` do -- as
its own independent restart signal, not anything CPU-side `mt_trig` already gates.

Re-disassembled the `0x4000f454` region with `-m 5307` (the ORIGINAL read of this
function, back in Session 53, used plain `-m 68000` and was silently garbled by the
same ColdFire 32x32-multiply mis-decode noted elsewhere in this project -- corrected
now, though the earlier read happened to still identify the right instructions).
Deliberately did NOT try to bail out of `0x4000f454`'s own entry (a much bigger,
riskier prologue than `FUN_40006844`'s simple 2-push case that already caused one
stack-corruption crash this session) -- instead detours only the two write
instructions themselves (`movel a5,a2@(4)` / `movel a4,a2@(8)`, 8 B, "jmp"-kind inline
site exactly like `pre`'s own convention). For a silenced track, skips both writes;
`%a5`/`%a4` stay correctly computed as registers either way, so the caller's own
downstream "does this need a fresh bind" logic (which reads the registers, not this
memory) is unaffected -- `mt_trig`'s protection there stays fully intact regardless.

**Isolation-tested** (`emu_solo.py` ×2 images, `emu_dt.py`) -- both writes correctly
skipped for a silenced track, correctly happen otherwise, across mute/solo/gate
combinations and all 8 tracks -- ALL GOOD. **Dynamically re-validated** against the
same real-playback scenario (`emu_mute_dynamic9.py`): with both hooks combined, the
muted track's real trigs now produce **zero** writes to `+0x04`/`+0x08`/`+0x90` at
all (down from the "0 for `+0x90`, still happening for `+0x04`/`+0x08`" result before
this hook), while the unmuted control track is completely unaffected (30360 writes,
identical shape to the pre-fix baseline). No crash.

**Explicit, stated caveat:** unlike `mt_trig`, this hook's real-world effect cannot be
proven end to end in this emulator -- there is no DSP to observe reacting (or not) to
the write being gated. This is the best-reasoned remaining CPU-side lever, grounded in
"this is the only DSP-relevant state left unguarded," not a decisive proof the way
`mt_trig` was for the CPU side. If HW still shows no change after this, the audio
trigger mechanism is not driven by CPU writes this investigation can find at all, and
would need a fundamentally different approach (DSP-side disassembly/analysis, which
this project has no tooling for yet).

**Status: both `out/OCTATRACK_OS1.40C_MUTEMODE.syx` and
`out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx` rebuilt with `pre` + `mt_trig` + `mt_rebind`.
NOT yet reflashed.**

---

## Session 55 (2026-09-14, `wip`) -- SIDECHAIN: KEY never appeared on any of the three
builds; root cause found and fixed (a per-parameter ENABLE BITMAP, separate from
name/count/default/formatter, that this project had never poked)

User flashed `SIDECHAIN`, `SIDECHAIN2`, and `SIDECHAIN3` in turn (first real HW test
of any of these -- the flash queue had them blocked behind DT/QLREC/PARTREAPPLY for
many sessions). Report: box looks and behaves exactly like stock (SPATIALIZER
correctly gone from both FX choosers, as designed) except **the `KEY` parameter never
appears on COMPRESSOR's FX page 2, on any of the three builds.**

### Root cause

`tools/build_sidechain{,2,3}.py` all poke the COMPRESSOR descriptor's name/
value-count/default/formatter fields for the new slot(s) (8 for KEY; 9-11 for
KFLT/KGAIN/MON in step 3), all correctly E-relative per `reference/kb/memory-map.md`'s
struct decode -- but **none of them ever touch the per-parameter ENABLE BITMAP**,
documented in `refs/octabam/docs/firmware/PARAM_PAGES.md` ("`P+0x18a` / `P+0x18e` --
the per-parameter ENABLE BITMAP"): a nibble per parameter (bit 0 = exists), gating
whether the generic page renderer (`FUN_400a6994(P+0x18a, P+0x18e, slot)`, called
from both `FUN_400326d4` staging and `FUN_40037590` drawing) stages OR DRAWS a knob
at all -- **independent of whether the knob's own name/count/default are valid.**
Octabam's own doc calls this out explicitly: "a clone copied as `E .. E+0x192`
(rather than `P .. P+0x192`) loses exactly the tail these two words live in, and the
effect appears in the menu with a correct name and not a single knob. That mistake
cost two hardware flashes to find." This project made the identical mistake a third
time, for the identical reason: **`P = E + 0x38`, NOT `E`** -- a different base than
every other field these builds poke (`build_sidechain2.py`/`3.py` already knew this
distinction for one *other* purpose, `SPAT_P = 0x400d4904 + 0x38` when derefencing
the FX-chooser list's descriptor pointer, but the connection to the enable bitmap was
never made).

**Confirmed directly against the ROM** (`out/raw/section_3_MAIN_OS.bin`), not just
by reading the doc: computed `P+0x18a` for stock COMPRESSOR (`E=0x400d5a4a`,
`P=0x400d5a82`, field at `0x400d5c0c`) reads `0x00000000` -- slot 8's bit is 0. Cross-
checked the method against two known-good worked examples from octabam's doc first
(SPRING REV's `P+0x18e=0x11111001` and NONE's all-zero pattern both reproduced
byte-for-byte from this ROM), then read COMPRESSOR's own `P+0x18e` (slots 0-7):
`0x01111111` -- slot 6 (RMS, visibly working in stock) has its bit set, slot 7 (the
stock-normal page-2 gap our build scripts' comments already expected) reads 0. This
is a clean, direct confirmation, not an inference from a possibly-stale doc.

### Fix

Added one more poke to all three build scripts, at `E + 0x38 + 0x18a = 0x400d5c0c`
(asserted `00000000` beforehand, matching the live-ROM read above):
  - `build_sidechain.py` / `build_sidechain2.py`: `-> 0x00000001` (slot 8 / KEY only).
  - `build_sidechain3.py`: `-> 0x00001111` (slots 8-11 / KEY+KFLT+KGAIN+MON).
All three rebuilt clean; the new poke's assert passed against stock on every build
(confirms the `0x00000000` reading above wasn't a one-off). Independently re-verified
by reading the four bytes at `0x400d5c0c` back out of each finished `mainos_*.bin`:
`SIDECHAIN`/`SIDECHAIN2` -> `0x00000001`, `SIDECHAIN3` -> `0x00001111`, exactly as
intended. `tools/emu_sidechain.py` (formatter-only, unaffected by this class of bug
by construction -- see caveat below) re-run for the record -- ALL GOOD, unchanged.

Also fixed in passing: `build_sidechain2.py`/`build_sidechain3.py` still pointed at
`refs/octabam/tools/dsp_modmap.py`, which moved to `refs/octabam/tools/build/
dsp_modmap.py` in the same upstream reorg Session 50 already patched seven other
tools around (`toolpath.py` shim) -- these two just hadn't been re-run since. Fixed
by updating the two hardcoded paths directly (no shim needed here, just an import
path). Both scripts now run to completion again.

### The isolation test's blind spot, once more

`tools/emu_sidechain.py` calls `key_fmt`/`kfilt_fmt` directly against a synthetic
stack frame -- it never boots the real firmware and asks whether the real page-2
renderer actually reaches slot 8 at all, so it could not have caught this (or
validated the fix) by construction. Same class of gap as `pre_v`'s cmd-bit guess
(Session 52) and the QLREC notify-modal hang (Session 50): a unit test that only
ever exercises the code we wrote proves nothing about whether the surrounding stock
code ever calls it. No dynamic full-firmware probe was built for this session's fix
(the static ROM read against two independently-known-good worked examples was
judged sufficient given how directly it lines up with the reported symptom -- slot 8
disabled, slot 6/RMS enabled, nothing else in the picture changed); if `KEY` still
doesn't show up after reflashing, that read is the first thing to distrust.

**Status: all three `out/OCTATRACK_OS1.40C_SIDECHAIN{,2,3}.syx` rebuilt with the
enable-bit fix. NOT yet reflashed.** Recommended order: reflash plain `SIDECHAIN`
first (smallest surface, cleanest single test of "does KEY appear now") before
moving to `SIDECHAIN2`/`3`. If `KEY` appears now, the DSP-side wiring in `SIDECHAIN2`/
`3` (never HW-exercised before this session either) is still an open question, per
the Session 40 page-2-copier warning already on record.

### SIDECHAIN3 flashed same day: KEY now showed up (enable-bit fix confirmed on HW).
`KGAIN` renamed to `KGN` on screen (user request, display-only, `build_sidechain3.py`
`SLOTS[10]` name bytes). Real bugs found: **zero ducking** (KEY never engages gain
reduction) and MON (SC LISTEN) audio described as "kills the track's audio entirely";
independently, KFLT/KGAIN show resonance/instability and volume jumps while sweeping,
and with MON on the audio alternates "normal for a bar" / "metallic pinging comb-filter
for a bar" in a pattern tied to sequencer step count (changes shape at other step
counts).

**Traced the detector-redirect plumbing by disassembling the REAL stock ROM (not
guessing from the design doc)**, `m68k...` no -- DSP56300 side, via
`vendor/dsp56300/build/source/disassemble/dsp56kDisassemble -m` (no `-m` flag needed,
DSP56300 has one instruction set) against `out/raw/section_3_MAIN_OS.bin`'s payload B
module dump (`refs/octabam/tools/build/dsp_modmap.py`). Confirmed three things
structurally sound, ruling them out as the bug:
1. The polyphase resampling loop immediately before `sctap`'s hook site (P:0x29c)
   writes exactly 32 fresh words to X:0x0000 for the CURRENTLY-DISPATCHING track,
   ending right before the hook fires -- `sctap` is reading live, correctly-timed
   per-track audio, not stale/wrong-track data.
2. `scdet`'s redirect (`r0 := $40` on return) points at exactly the register the
   REAL compressor's own squared-magnitude/peak detector loop (`P:0x1873`,
   `move x:(r0)+,x0` inside a `do n7` block) consumes -- the redirect targets the
   right thing.
2b. User confirmed on HW: with MON on and KEY pointed at a loud, clearly recognizable
   track, the monitored audio DOES resemble that track's content (filtered/weird, but
   related) -- rules out "no audio ever reaches the detector at all" as the explanation
   for the zero-ducking symptom; the hand-off chain (sctap -> keybus -> scdet) is
   delivering real signal.

**Found and fixed a real, confirmed-by-disassembly bug in the KEY FLT (SVF) state
gating**, independently pattern-matching a bug class `refs/octabam` fixed in their own
effects the SAME DAY (their commit `f94c816`, "Init zeroes every persistent slot":
"a station started from whatever the block held before it"). Disassembled the REAL
stock COMPRESSOR's own init routine (`P:0x1864`, the module entry before `proc` at
`0x1871`) and confirmed it zero-fills ONLY `r7+$11/$12/$13/$1a/$1b/$f` -- it never
touches `$14/$16/$17/$18`, the exact bytes this project's `patch_sc_dsp3.asm` reuses as
"unused by stock" SVF `lp`/`bp` state (`$16`/`$17`), gated on stock's `$f` "first-block"
bit. That gate is wrong: `$f` can legitimately go warm from ordinary stock compressor
activity (any block processed at all) BEFORE our own KEY FLT code has ever run a
single block -- e.g. `KFLT` parked at bypass (its default, 64) for a while, then turned
to a real LP/HP value for the first time. At that moment `$f` already reads "warm," so
the old code skipped the zero-seed and read `$16`/`$17` as prior state -- except our
code had never written them, so the integrator got seeded from whatever garbage sat in
that DSP memory (plausibly explaining sustained resonance/instability rather than a
clean start, given the SVF's own inherent Q=1-near-Nyquist sensitivity already
observed).

**Fix**: stopped gating on stock's `$f` entirely. `r7+$18` (confirmed untouched by
stock's init AND by every hook in this file) is now OUR OWN dedicated "have I ever
seeded lp/bp myself" latch -- set to 1 only after we write real `$16`/`$17`, checked
(not `$f`) to decide cold-vs-warm. `tools/emu_sc_dsp3.py` updated to seed/check `$18`
instead of `$f` throughout, and gained a new adversarial regression case mirroring
octabam's own `verify_dirtystate.py` method: stock `$f` forced warm + `$16`/`$17`
seeded with garbage (`0x7fffff`) + our own `$18` still 0 -> must still cold-start.
**This test caught the bug live**: before the fix, re-running the existing KFLT
numeric checks against the harness's own baseline `.mem` snapshot (which happens to
carry non-zero garbage at `$16`/`$17`/`$18`) failed 4/4 LP/HP cases with exactly the
"reading stale state" signature; after the fix, all pass, including the new
dirty-state case. `out/OCTATRACK_OS1.40C_SIDECHAIN3.syx` rebuilt (231/261 donor words,
still well clear of the SPATIALIZER budget); enable-bit fix and `KGN` rename both
reverified present in the same rebuild.

**Status: rebuilt, isolation + dirty-state-regression verified. NOT yet reflashed.**
Not yet explained by this fix alone: the exact cause of zero gain-reduction engagement
(the compressor's OWN threshold/attack-release/gain-curve math, `P:0x188d` onward, is
disassembled only partially -- got as far as confirming an envelope-smoothing stage
and several gain-curve LUT reads before stopping to report progress) and the specific
LP/HP resonance-at-sweep behavior beyond the dirty-state contribution (the Chamberlin
SVF topology itself is known to get peaky/unstable as cutoff approaches Nyquist/4;
worth checking `tools/sc_tables.py`'s FTAB range against that ceiling next, independent
of the state-gating fix). Recommend reflashing this build first (cheap, and the fix is
strictly an improvement/no-regression per the isolation suite) before deciding whether
further DSP RE on the gain-reduction chain is warranted.

### Same-day HW retest of the dirty-state-fixed SIDECHAIN3: ducking works, MON still rings

Reflashed. **Ducking now engages** (needed page-1 threshold/ratio/attack/release
tweaking by ear, as expected — the compressor's own gain-computation chain was never
touched by any of this session's fixes). **Filter sounds better** (consistent with the
dirty-state fix addressing real garbage-seeding, not a placebo). **MON (SC LISTEN)
still rings/alternates "normal for a bar, metallic pinging for a bar," cyclic with
pattern length.**

Narrowed hard with two on-hardware answers: (1) with MON off, ducking itself is
**clean** — no cyclic artifact — so the bug is NOT in the shared `sctap`/`scdet`
detector-and-filter chain (gen-0 of the keybus ring), which ducking alone exercises
and which now works. (2) the MON ringing happens **even with KFLT at bypass/OFF** —
so it is NOT the SVF filter either (rules out "dirty-state fix didn't go far enough").
By elimination this isolates the bug to the ONE mechanism ducking never touches: the
SC LISTEN gen-1 stash (`scdet` writes the processed key to `Y:$820+track*$80`) and
`sctail`'s read-back of it into the output buffer.

Checked two concrete failure theories by disassembling the real stock COMPRESSOR
module end to end (`out/dsp/comp_mod_stock.bin`, `P:0x1864..0x1915` for payload B) —
both ruled OUT:
- **`n6` register-clobber** (scdet saves the original `r0` into `n6` at proc+0;
  `sctail` reads it back at proc-end, ~140 instructions later): grepped every `n6`
  reference in the whole body — written ONCE (the original displaced instruction) and
  read back exactly twice, both by STOCK's OWN code (`P:0x18df`, `P:0x1906`) the same
  way `sctail` does. `n6` demonstrably survives the whole routine untouched; not a
  clobber bug.
- **A later gain-multiply re-processing the substituted output** (would explain
  metallic ringing as the key signal self-modulated by its own gain-reduction
  envelope, tracking its own rhythm): `sctail`'s splice site
  (`move m0,x:(r7+$f)`, `P:0x1915`) IS the literal last instruction of the module —
  confirmed by grep, nothing after it. Nothing re-touches the output post-splice.

**Status: root cause of the MON-specific ringing still open.** Both the address math
for the gen-1 write (`scdet`) and read (`sctail`) were re-derived and match (same
`$800 + track*0x80 (+ 0x20 for gen1)` formula, same `@KADJ@`-adjusted absolute track).
Next step if resumed: since gen-1's write-then-read is entirely intra-call (no
cross-hook timing dependency at all, simpler than gen-0's proven-working cross-hook
case), the mechanism SHOULD be the safest part of the design on paper — worth doubting
that reasoning itself next, e.g. by instrumenting `sctail`'s actual read values
dynamically (a `dsp_host` probe analogous to `emu_sc_dsp3.py`'s existing harness, but
driving `scdet`+`sctail` back-to-back with a real block boundary between them) rather
than further static re-derivation, which has now been done twice with no bug found.

### New bug reported, NOT YET INVESTIGATED further (user flagged as a later item):
copying the COMPRESSOR (with KEY/KFLT/KGN/MON) from FX2 to FX1, then double-tapping
FX1 to reopen its chooser, highlights **LO-FI**, not COMPRESSOR. Checked the ID2POS
rebuild math from Session 17 (`build_sidechain3.py`'s `ID2POS` loop) against the real
ROM twice and it holds up: dumped the actual stock `FX1_LIST`/`FX2_LIST` and confirmed
FX1 is exactly FX2's first 11 entries (`NONE FLTR EQ DJEQ PHSR FLNG CHOR SPAT COMB
COMP LOFI`, positions 0-10) — so a single shared `ID2POS` table is valid, and per the
rebuild COMP correctly lands at post-removal position 8, LOFI at 9. The stored table
values are not obviously wrong. Most likely explanations, neither confirmed: (a) the
OS's copy-and-reopen highlight logic doesn't do a plain `ID2POS[assigned_id]` lookup
the way the plain "open chooser fresh" path presumably does, or (b) this is a
pre-existing STOCK quirk (COMPRESSOR/LOFI have simply never sat adjacent to a
just-removed entry before, since this is the first time anything has ever been
removed from these lists) unrelated to our patch. **Cheapest next diagnostic**: does
the same wrong-highlight-after-copy reproduce on stock firmware with some other
effect pair — settles (a) vs (b) before touching any code.

### Same-day follow-up on both threads (user: "let's keep going on both")

**MON ringing — both register-survival theories now disproven by direct evidence,
isolated `sctail` logic proven correct dynamically; root cause still open.**

Built two new tools (kept in `tools/`, not scratchpad): `emu_sc_dsp3_sctail.py`
(isolated dynamic test of `sctail` alone — the one cave routine `emu_sc_dsp3.py`
NEVER actually calls as `-proc` anywhere; grep confirms every existing `base_mem()`
call passes `patch_tail=False`, so `sctail`'s own logic had **zero** dynamic coverage
before today, only static disassembly review) and `emu_sc_dsp3_fullbody.py` (attempts
to run the REAL, complete `COMP_PROC`→`COMP_TAIL` body via `dsp_host` against the
`--patched` image, not just our isolated hooks).

- `emu_sc_dsp3_sctail.py`: after fixing the stale `refs/octabam/tools/dsp_modmap.py`
  path (same Session-50-class drift as everywhere else, `dsp_modmap.py` now lives at
  `tools/build/dsp_modmap.py`), found `sctail` genuinely reads the seeded gen-1 signal
  correctly when it should (MON=1,KEY=1) and correctly leaves output untouched when it
  shouldn't run (MON=0, or KEY=0) — **ALL GOOD**, once two words of `dsp_host`-internal
  harness noise at X:0x13/0x14 (reproduced even with zero `-params`/`-pokey`, unrelated
  to this cave entirely) were identified and excluded rather than misread as a bug.
- Chased a new, more specific theory before this: `sctail` reads
  `x:(r6+$d)`/`x:(r6+$e)` for its own KEY/MON check, using `r6` — NOT `n6` (already
  proven to survive in Session 55's first pass). Since a general-purpose address
  register is far more likely to get reused across ~140 real instructions than the
  one-off anchor `n6` was, this looked like a strong candidate: if `r6` gets clobbered
  somewhere in the real gain-computation body between `scdet`'s entry and `sctail`'s
  exit, `sctail` would read garbage instead of the real MON/KEY state.
  **Disproven by grepping every `r6` reference in the full disassembled body
  (`out/dsp/comp_mod_stock.bin`, `P:0x1864..0x1915`): seven hits, ALL reads
  (`move x:(r6+$0/$1/$2/$3/$4/$5/$c),...`), zero writes.** `r6` is used purely as a
  stable params-block base throughout, exactly like `n6` — both register-survival
  theories are now ruled out by direct evidence, not just plausibility.
- `emu_sc_dsp3_fullbody.py` (run cold at `COMP_PROC` via `dsp_host`, seeding keybus
  gen-0 with a recognisable signal, MON=1/KEY=1/KFLT=bypass) came back with `X:0` all
  zero — a real discrepancy, but NOT trusted as evidence of a hardware bug given (a)
  `sctail`'s isolated logic just proved clean and (b) `r6`/`n6` both proven to survive
  the real body untouched, leaving no known mechanism for this cold, out-of-context
  invocation to go wrong other than a missing precondition in the probe itself (e.g.
  whatever real dispatcher setup establishes before jumping to `COMP_PROC` on actual
  hardware, not reproduced by jumping straight to `-proc COMP_PROC`). Flagged as
  inconclusive, not as a finding.

**Status: the individual mechanisms (scdet's stash, sctail's read-back, both anchor
registers) are now all independently proven correct. The MON ringing is not explained
by anything found so far.** Remaining candidates, in rough order of plausibility: (1)
something in the real per-frame dispatch context that a cold `-proc COMP_PROC` jump
doesn't reproduce (would need either a much more careful full-context probe or the
kind of real-playback dynamic driving Session 53 used on the ColdFire side — NOTES
already flags DSP-side realistic-playback simulation as a capability this toolchain
does not currently have); (2) a genuinely hardware-only phenomenon (cross-core timing,
real ADC/DAC behaviour) outside what any emulator here can observe, matching the
project's own previously-documented limitation for "the side-chain compressor's actual
gain reduction." Not a place to keep guessing from static reads alone — next progress
here most likely needs either a bigger tooling investment or further hardware
experiments (e.g., does the ringing's cyclic period change if the KEY track's OWN
sample content changes but its trig pattern doesn't, which would implicate audio-
content-dependent state over pure trig-timing).

**Chooser-highlight bug — narrowed hard, very likely NOT caused by our patch.**
Found the real ColdFire consumer of `ID2POS` via `m68k-elf-objdump` xref search for
`0x400d6150` (two hits, `P:0x4003770a` and `P:0x40059a84`). The second is the relevant
one: reads the current bank/part (`0x80000000`/`0x80000003`), computes the bank-blob
address for the current track's stored FX slot (`0x46c82456 + part*6322 + track +
0x8ed88`), reads the STORED effect id from there, then does TWO separate id-indexed
lookups: `ID2POS[id]` (`0x400d6150`) for the cursor/viewport position, and a SECOND,
previously-undocumented table `0x400d5fdc[id]` (id → `E+0x38` descriptor pointer,
confirmed a plain 32-entry array, unused ids defaulting to NONE's `P`) to stage the
highlighted effect's parameter page via `FUN_400326d4`.

**Dumped `0x400d5fdc` directly: id `0x18` (COMPRESSOR) → `0x400d5a82` (COMP's own `P`,
correct) and id `0x1c` (LOFI) → `0x400d5da6` (LOFI's own `P`, correct) — this table is
untouched by our SPATIALIZER removal and is NOT stale.** Combined with `ID2POS`
already being independently re-verified correct (Session 55, twice), BOTH tables this
highlighting path reads are provably right for the correct id. Since the id itself is
read from PERSISTENT BANK STORAGE (not anything our patch writes or could have
corrupted), the most likely remaining explanation is that **the COPY action itself
wrote the wrong id into that storage slot** — a stock mechanism, located elsewhere
(not yet found), that this session's work never touches. This makes "does it reproduce
on stock firmware" an even stronger next diagnostic than before — the RE now actively
points away from our code, not just fails to find a cause in it.

## Session 56 (2026-09-14, `wip`) — chooser-highlight bug: RESOLVED. Not stock, not the copy action — a second, un-rebuilt id->position table

User tested the stock-firmware hypothesis from Session 55's end and **ruled it out**:
the bug does NOT reproduce on stock, and has nothing to do with copying between FX
buses. Precisely isolated instead: **only in the Effect 1 chooser**, selecting COMB
highlights COMPRESSOR (the entry below); selecting COMPRESSOR highlights LOFI (the
entry below); selecting LOFI highlights nothing. No other entry is affected.

That precise pattern — "select X, highlight X+1," breaking completely at the very
last entry, isolated to FX1 only — pointed straight at a stale boundary/length
constant specific to FX1's shorter post-removal list, not a copy-action bug at all
(the earlier theory is retracted).

**Root cause**: `m68k-elf-objdump` xref search for FX1_LIST (`0x400d6060`) turned up
a second per-FX-bus highlight-setup routine (`P:0x40059bd0`) that is structurally a
TWIN of the one already found for FX2 (`P:0x40059a84`, Session 55) — same shape
(scan the list for its NUL terminator, `jsr 0x4007ec60` to init a 7-row viewport,
read the stored effect id from Part storage, look up a position, `jsr 0x4007edb0`
to apply it) but with every FX1-specific detail swapped in: `lea 0x400d6060` (FX1_LIST,
not FX2_LIST), its own viewport struct at `0x460d5c8c` (not FX2's `0x460d5ca0`), its
own storage offset `0x8ed80` (not FX2's `0x8ed88`) — **and, critically, `lea
0x400d60d0,%a0` for the id->position lookup, NOT `0x400d6150` (the table
`build_sidechain2.py`/`_3` had been calling `ID2POS` and treating as shared).**

**FX1 has its own, completely separate id->position table**, sitting exactly `0x80`
bytes (32 × 4-byte entries) before what turned out to be FX2's own copy. Dumped both
from stock: byte-for-byte identical values (`COMB`→8, `COMP`→9, `LOFI`→10, `SPAT`→7,
etc.) — which is exactly why this was never caught by comparing the two chooser
LISTS earlier (Session 55 confirmed `FX1_LIST == FX2_LIST[:11]`, correctly, but never
checked whether the id2pos tables were ALSO two copies rather than one shared table).
Session 55's rebuild loop only ever touched `0x400d6150` (FX2's copy) — `0x400d60d0`
(FX1's copy) was untouched, still holding the stale pre-removal values. Reading it
for COMB (`0x13`→8, stale) lands on position 8, which is now COMPRESSOR post-removal;
for COMPRESSOR (`0x18`→9, stale) lands on position 9, now LOFI; for LOFI (`0x1c`→10,
stale) lands on position 10, which doesn't exist in FX1's now-10-entry list at all —
matching all three reported symptoms exactly, including the complete breakdown at
the list's new end.

**Fix**: `build_sidechain2.py`/`build_sidechain3.py` gained `FX1_ID2POS = 0x400d60d0`
and apply the IDENTICAL rebuild transform (id `0x05`→0, every id at a position >
`SPAT_POS` shifts down 1) to both tables, not just `ID2POS`. Rebuilt both outputs;
independently re-verified by reading `FX1_ID2POS`/`ID2POS` back out of the finished
`mainos_sidechain3.bin` for `COMB`/`COMP`/`LOFI`/`SPAT` — both tables now agree
(`COMB`→7, `COMP`→8, `LOFI`→9, `SPAT`→0), matching their real positions in the
truncated list. `emu_sidechain.py` and `emu_sc_dsp3.py --patched` re-run for the
record (neither touches this ColdFire table, unaffected either way) — **ALL GOOD**.

**Status: both `out/OCTATRACK_OS1.40C_SIDECHAIN{2,3}.syx` rebuilt with the fix. NOT
yet reflashed.** Worth a final sanity pass on `reference/kb/memory-map.md` /
`reference/MERGE.md` if this thread is picked up again: both docs' "ID2POS" mentions
now need a "there are two, one per FX bus" caveat so this doesn't get missed a third
time in some future mod that touches these lists.

## Session 57 (2026-09-14, `wip`) — chooser bug HW-CONFIRMED FIXED; MON ringing disentangled into two separate phenomena, one theory disproven, one new lead

**Chooser highlight bug: user reflashed `SIDECHAIN3` and confirmed fixed.** Closed.

**MON ringing — user isolated it into two genuinely separate phenomena** (previous
sessions' "always present, not sample/trig-dependent" characterization conflated
them):

1. **"Ringing quality"** — a constant textural/metallic coloration, present in what
   MON plays regardless of trigs on EITHER track (confirmed: still present with
   ZERO trigs on the compressor track). Root cause still fully open.
2. **"Oscillation"** — a separate, tempo-locked rising/falling character (beats
   audibly at 120 BPM, reads as steady at 90/150) that ONLY appears when the
   **compressor track itself** has active trigs — not the key track (confirmed
   NOT trig-dependent on the key track, NOT sample-content-dependent on the key
   track, in earlier rounds this same session).

**Theory tried and DISPROVEN**: the compressor track's own AMP envelope
(Attack/Hold/Release) reshaping whatever audio flows through that track on each of
its own retrigs, independent of anything this project built — a completely
mundane, expected mechanism that would explain a tempo-locked beat via real-ms
envelope times interacting with a tempo-proportional trig interval. User flattened
the AMP page and the oscillation was unaffected. Ruled out cleanly.

**New lead, NOT yet tested**: `KEY FLT` is the only stage in `patch_sc_dsp3.asm`'s
`scdet` that uses the **dynamic** `n7` sample count (`do n7,>zz13`) — the keybus
copy-in, `KEY GAIN`, the `SC LISTEN` gen-1 stash, and `sctail`'s read-back all
hardcode a fixed `#<$20` (32) instead. `n7` is documented elsewhere in this project
(Session 17) as varying for a "split block" (a new trig landing mid-block only
gives that frame partial samples to work with). If the COMPRESSOR track's own
retrigger causes `n7 < 32` for that frame, `KEY FLT`'s SVF loop would only filter
the first `n7` samples of `X:$40`, while every other 32-hardcoded stage upstream/
downstream (including what `sctail` ultimately hands to MON) would still touch the
full 32 words — a real, trig-tempo-locked discontinuity at exactly the boundary a
split block would create. Consistent with "oscillation" being compressor-track-
trig-tied and NOT filter-independent (unlike the baseline "ringing quality," which
was confirmed present even at `KFLT` bypass, where this loop doesn't run at all —
so this theory targets ONLY the oscillation, not the ringing quality).

**Next diagnostic (not yet run)**: does "oscillation" specifically (not the
baseline ringing) still occur with `KFLT` at bypass, compressor-track trigs still
present? If it disappears at bypass, that confirms the `n7` mismatch and the fix is
to drive the gain-stage/copy-in/gen-1-stash loops off `n7` instead of a hardcoded
32 (matching what `KEY FLT` already does) — needs care: those stages currently
process a fixed 32-word chunk of `X:$40`/keybus regardless of block size, and
switching to `n7` changes their addressing/loop bounds, not just the count.

**Status: baseline "ringing quality" root cause still completely open (two failed
static/dynamic RE passes, Session 55). Oscillation has one untested, well-motivated
lead (the `n7` mismatch). No code changes this round.**

## Session 58 (2026-09-14, `wip`) — MON redesigned to bypass the compressor module entirely, instead of continuing to hunt for the mystery inside it

`n7` mismatch theory tested and DISPROVEN too (oscillation still occurs with `KFLT`
at bypass, where that loop never runs). Further isolated: not trig-dependent on the
key track, not content-dependent on the key track OR the compressor track (changing
the compressor track's own sample changes nothing about what's monitored -- confirms
`sctail`'s substitution was a clean, total replacement, never a mix), not explained
by the compressor track's AMP envelope (tested, no effect), and NOT a hard on/off
voice-gate (continuous, never silent). Every specific mechanism inside `scdet`/
`sctail` had already been independently verified correct by this point (register
survival, isolated dynamic tests, dirty-state guard). The user's question reframed
the actual problem: rather than find the one remaining bug in ~60 instructions of
unmapped stock compressor envelope/gain math, stop sharing that execution context at
all.

### The redesign

Traced the DISPATCHER (not the compressor module) to find a point downstream of
BOTH FX1 and FX2 having fully returned for a track. Found it: right after the
per-track FX1-then-FX2 call sequence (`P:0x29c`..`0x302` for payload B, `0x4a7`..
`0x50d` for payload A -- FX1 dispatched via `x:(r6+$1b)`, FX2 immediately after via
`x:(r6+$1c)`, identical structure both times), the dispatcher does ONE MORE thing
before advancing to the next track (`x:$420 += 1`, confirmed the same absolute
track-index counter this project already validated in Session 17): it reads
`x:>$206,r0` and calls a small "commit" subroutine (`func_00034f` in payload B /
`func_00055a` in payload A) that copies this track's now-fully-processed audio out
of the shared `X:0` scratch buffer into a per-track persistent output slot. That
`move x:>$206,r0` instruction, byte-identical in both payloads
(confirmed by disassembly: `60f000 000206`), is the new splice site.

Ruled out one detour before committing to this: whether `func_00038b` (a parallel
path branched to when a per-frame variable `x:$20e` is non-zero, at the very start
of the per-track cycle) might mean split-block frames skip the whole FX1/FX2
dispatch our existing hooks sit in entirely. Disassembled it: it's a per-voice
pitch/rate ramp setup routine (unrolled across several call sites with the same
`brset #$11 / lua / bra` shape), not a parallel FX dispatcher -- a dead end for that
specific worry, but not a blocker for the redesign, which doesn't depend on it
either way.

### Implementation

`tools/patch_sc_dsp3.asm`:
- `scdet` UNCHANGED in its core logic (detector redirect, KEY GAIN, KEY FLT, the
  gen-1 stash all stay exactly as before -- all independently proven correct).
  Added: when MON is checked (the old `zz10` block), it now ALSO publishes
  `MON_ON[track]` / `MON_KEY[track]` to `Y:(0x800 + track*0x80 + 0x40/0x41)` --
  the dead "gen-2" slot of THIS track's own keybus stride (never written by the
  gen-0/gen-1 mechanisms, so no new memory-safety question versus what Session 17
  already established safe). Published as ON+key-track when KEY!=0 and MON=1;
  explicitly published OFF on every other exit path (MON=0, or KEY=0) so a stale
  flag from an earlier frame can never linger. `track` throughout is `x:$420`,
  confirmed still holding the CURRENT track (not yet incremented) at every point
  `scdet` or the new hook can run.
- `sctail` DELETED. Replaced by `moncommit`, spliced at the dispatcher's commit
  step instead of the compressor's proc-end: replays the displaced
  `move x:>$206,r0`, reads `MON_ON[x:$420]`, and if set, independently re-fetches
  `MON_KEY[x:$420]` and copies keybus[key] gen 1 straight into `X:0` -- a fresh
  fetch every time, not a value carried across the compressor's own call, and
  running in a completely separate instruction stream from whatever the
  compressor's envelope/gain code does.

`tools/build_sidechain3.py`: `DSP` dict gained `commit_hook` (payload A `0x50e`,
payload B `0x303`) replacing `comp_tail`; the third detour now asserts/patches the
dispatcher's `move x:>$206,r0` (bytes `60f000 000206`) instead of the compressor's
proc-end `move m0,x:(r7+$f)`. `dsp_module_fileoff` already resolves any P-address
generically (not compressor-specific), so no new resolution logic was needed --
just a different address. Builds clean: 256/261 donor words (was 231; net growth
from adding `moncommit` and the publish code, still comfortably under budget).

### Testing

Rewrote `tools/emu_sc_dsp3.py`'s SC LISTEN section to add three new checks
(`MON_ON`/`MON_KEY` publish correctly for MON=1, MON=0, and KEY=0) -- ALL GOOD,
`scdet`'s existing checks (copy/KEY-select, KEY GAIN, KEY FLT, dirty-state guard,
persistence) all still pass unchanged, confirming the core logic wasn't disturbed.

Deleted `tools/emu_sc_dsp3_sctail.py` and `tools/emu_sc_dsp3_fullbody.py` -- both
tested the now-removed proc-end hook and would have silently tested nothing
meaningful against the new design (their setup drove page-2 params, which
`moncommit` never reads at all). Replaced with `tools/emu_sc_dsp3_moncommit.py`:
isolated test of `moncommit` alone, driven purely through `MON_ON`/`MON_KEY` and a
seeded gen-1 signal -- checks the substitution fires correctly when `MON_ON=1`,
stays inert when `MON_ON=0`, and (new coverage the old test never had) that one
track's `MON_ON` flag can never leak into a DIFFERENT track's commit. ALL GOOD,
including in `--patched` mode against the real built image (both `ensure_patched_mem`
functions updated to check the new dispatcher-level detour instead of the removed
proc-end one).

Full regression re-verified against `mainos_sidechain3.bin` after rebuild: enable
bitmap (`0x1111`), `KGN` name, and both chooser `ID2POS` tables (Sessions 55/56)
all still correct -- this redesign touched none of that.

**Status: `out/OCTATRACK_OS1.40C_SIDECHAIN3.syx` rebuilt with the redesign.
Isolation-verified (including in `--patched` mode against the real image).
NOT yet reflashed.** If the ringing/oscillation is gone or changed after this
reflash, that confirms the compressor module's own internal timing was the cause
(narrowing exactly where, still open, no longer matters for MON's correctness
either way, since MON no longer depends on it). If it PERSISTS even now, that
would be a genuinely new and important result: it would mean the artifact is
further upstream than anything this whole investigation has touched -- in
`scdet`'s own redirect/gain/filter math (already isolation-tested clean, but
never dynamically tested against a REAL, moving audio stream), or in the keybus
gen-0 publish tap itself (`sctap`, proven correct for DUCKING's purposes but
never stress-tested with MON's specific full-fidelity playback requirement).

---

## HANDOFF (2026-09-14) — MUTE MODE trig-suppression: read this before touching `patch_softmute.s`

**Read Session 52/53/53-bis above first (in order) for the full trail** — this is the
condensed status + the concrete next moves, written because the thread is genuinely
open and the next session should not restart from zero or re-guess what's already
been ruled out.

### Where this stands

The user's target naming (not yet applied to code/docs — asked to fix the bug first):
`OT` (stock hard cut) / `OTFX` (hard cut + FX tails, unmute resumes at playhead — not
built) / `OTFX-T` (= today's `OT+FX`, trig-mute style) / `DT-T` (= today's `DT`).
**The bug lives in the mechanism `OTFX-T` and `DT-T` share**: suppressing a *new*
sequencer trig while a track is held muted. `OTFX-T`'s dry-cut + FX-tail-ring already
works, hardware-confirmed. The open bug: a muted track's trig still produces a moment
of real audio (`OTFX-T`: a "blip" before the frame-level mute-gate catches it next
frame; `DT-T`, which has no dry-cut at all, so the trig is fully audible — "does
nothing").

**Three fixes built this session, each proven correct at the level it can be proven,
each shipped with ZERO hardware effect:**

1. **`pre_v`** (Session 52, now DELETED from the source) — detoured `FUN_40005178`
   (`trig_to_voice`), on the strength of an old, out-of-context Ghidra decompile.
   Flashed: no change. Root-caused: driving the real firmware in the full-firmware
   Unicorn emulator (`refs/octabam`, `tools/emu_mute_dynamic5.py`) proved
   `FUN_40005178` is entered **zero times** across 79 real sequencer trigs over 6 s.
   Dead code for this purpose. Removed entirely.

2. **`mt_trig`** (Session 53, still in `tools/patch_softmute.s`) — the REAL per-trig
   dispatch, found by tracing the actual trig-flag write (`FW_LIVE_NIBBLE`) back
   through live execution rather than re-reading static decompiles:
   `FUN_40006820` (8-track fan-out) → `FUN_40006844` (clears the voice's `active`
   byte, bumps a per-frame counter, calls `FUN_4000672c`) → `FUN_4000672c` (reads
   `REL_STATE`, the same word `pre` already maintains — this is what made it look
   like the right target). `mt_trig` detours `FUN_40006844`'s entry and returns
   before any of that runs, for a silenced track. **Isolation-tested AND dynamically
   proven**: direct instrumentation showed `mt_trig` takes the silenced branch
   **100% of the time** for a muted track across the whole run, and `FUN_4000672c`'s
   call count for that track drops to **exactly zero** while unmuted tracks got
   100,000+ calls in the same window (`emu_mute_dynamic11.py` / `_12.py`). A real
   stack-corruption bug in the first version of this hook (it entered from a plain
   `bccs` fallthrough inside `FUN_40006820`, which leaves 2 of ITS OWN saved
   registers live on the stack beneath the real return address — an early `rts` that
   didn't also unwind those crashed the emulator on first real-playback contact,
   despite passing every isolated unit test) was caught and fixed; the isolation
   tests now simulate that real caller stack frame and check it explicitly
   (`SENTINEL_D2`/`SENTINEL_A2`, exact SP arithmetic) so this exact class of bug is
   now a regression test, not a silent gap. **Flashed: no change** (confirmed NOT a
   stale-build/wrap mismatch — decoded the actual `.syx` back through
   `elektron-firmware-tool`'s own extract path and diffed the recovered
   `section_3_MAIN_OS.bin` against what the emulator tested: byte-identical). User
   confirmed testing both STATIC and FLEX — same null result either way.

3. **`mt_rebind`** (Session 53-bis, still in `tools/patch_softmute.s`) — gates the one
   remaining DSP-*visible* state change `mt_trig` doesn't touch: `0x4000f4dc`/`e0`,
   inside `FUN_40006844`'s own caller (`0x4000f454`-ish), unconditionally rewrites
   the voice struct's arena-entry pointers (`+4`/`+8`) on every trig regardless of
   mute state. Working hypothesis: the DSP may watch THIS write (the only thing that
   changes every trig no matter what the CPU-side `mt_trig`/`FUN_4000672c` chain
   does) as its own independent restart signal. Isolation-tested (both writes
   correctly skipped/happen across mute/solo/gate/all-8-tracks). Dynamically
   re-validated with `mt_trig` combined: the muted track now produces **zero**
   writes across all three tracked offsets (`+4`/`+8`/`+0x90`), unmuted control
   track fully unaffected, no crash. **Flashed: no change.**

**Explicitly stated at the time, worth repeating:** `mt_rebind`'s real-world effect,
unlike `mt_trig`'s, was never provable in this emulator at all — there is no DSP
model, so "gates the right memory location" and "actually stops the DSP from
restarting the voice" are different claims and only the first was ever checked.

**Ruled out along the way, so the next session doesn't re-check them:**
- Stale/wrong build flashed — no (verified via a full decode round-trip).
- Machine type (STATIC vs FLEX) — no, user tested both.
- DSP state not cleared after flashing (a real, documented Octatrack gotcha,
  `refs/octabam/reference/kb/dsp56300.md`: "power-cycle after every flash before
  judging anything") — no, user confirmed power-cycling before each test.

### The one piece of new research pulled this session — NOT yet reconciled

`python3 tools/refs/sync.py` pulled fresh `refs/octabam`. Its `docs/firmware/RTOS_FORK.md`
§10.13–§10.26 (their own, independent investigation, dated 6–9 Sep 2026 — about
**RECORDER ARM**, i.e. the REC1/live-sampling trigger, not general sample playback)
says, explicitly: **`0x4000672c` is "gated on machine type == 4/PICKUP," a
later/different follow-up mechanism — NOT the thing they were looking for.** Their
real "arm caller" address is **`0x40006238`**, reached via `tstb %d7 / bgew
0x40006238` at `0x4000607c`.

**This is `0x4000672c` — the exact function this session's `mt_trig` fix targets —
being characterized completely differently by an independent team.** Two ways this
reconciles, and the next session needs to actually determine which (or find a third):

1. `0x4000672c` is a shared, multi-purpose subroutine (something like "restart/update
   this track's amp/envelope state") called from BOTH octabam's recorder-arm-adjacent
   dispatch (where its behavior happens to matter only for PICKUP) AND from this
   project's independently-traced `FUN_40006844` path (which is NOT machine-type-gated
   in the disassembly this session read, and empirically fires ~30,000×/6s for FLEX
   and STATIC alike, dynamically confirmed, not inferred). Both readings could be
   correct simultaneously, about different callers.
2. OR this session's identification of `FUN_40006844`→`FUN_4000672c` as "the thing
   that makes a track produce audio" was subtly wrong from the start — real,
   frequently-executing, dynamically-confirmed CPU-side code, but not actually the
   step that gates whether the DSP renders sound — in which case `mt_trig`/`mt_rebind`
   suppressing it correctly on the CPU side would legitimately have ZERO audible
   effect, which is exactly the symptom observed. This would mean `0x40006238`
   (octabam's real "arm caller," for a DIFFERENT purpose than ours but a concretely
   different, unexamined address) or something in ITS vicinity is worth a direct look
   — not because recorder-arm is our bug, but because octabam's method (trace the
   REAL caller of the REAL gating decision via dynamic PC-watch, not static-only
   reading) is exactly the discipline that found `mt_trig`'s real target last time,
   and might turn up a second, previously-unexamined dispatch path for ordinary
   (non-recorder) trigs too.

**Recommended first move for the next session, cheapest and no new setup required:**
statically disassemble `0x40006238` (`m68k-elf-objdump -m 5307`, NOT plain `-m 68000`
— see the ColdFire 32×32-multiply mis-decode trap already on record) and its callers,
and dynamically instrument it the same way `emu_mute_dynamic11.py` instrumented
`mt_trig` — does it ever fire for an ORDINARY (non-recorder) FLEX/STATIC trig? If yes,
it may be a genuinely different, previously-unexamined dispatch path worth chasing. If
it's confirmed recorder-only (REC1-specific, per its own name), it's a dead end for
THIS bug and the reconciliation is answer (1) above — meaning the real gap is
elsewhere entirely, most likely on the DSP side (see below).

### The other real option: build DSP-capable emulation

`refs/octabam/tools/emu/ot_emu` is a genuine C++ ColdFire+DSP56300 co-emulator
(`dsp.cpp`, `machine.cpp`, `rtos.cpp` — boots the RTOS AND runs both real DSP cores,
renders actual audio) that could answer "does this track produce sound" directly,
which NOTHING used this session could do (the Python/Unicorn route, `tools/emu_rtos.py`
wrapping `refs/octabam/tools/emu/emu_rtos.py`, is ColdFire-only, no DSP model
whatsoever — ~120× slower than real time and structurally blind to the actual audio
engine).

**Blocker, not yet resolved:** `make emu-cf` (in `refs/octabam/`) fails —
`add_subdirectory` can't find `vendor/mc68k` or `vendor/dsp56300/source`. These are
NOT registered in `refs/octabam/.gitmodules` (only `modules/octakit/upstream` and
`modules/midi-scenes/upstream` are). `refs/octabam/CLAUDE.md` (freshly pulled this
session) describes a worktree workflow where `vendor/` and `.venv/` are "symlinks to
the main checkout's" — implying octabam's own contributors have a separate, already-
provisioned checkout elsewhere with these vendored (`vendor/mc68k` = a Musashi-based
ColdFire fork per `docs/firmware/COLDFIRE_PORT.md`; `vendor/dsp56300` = a DSP56300
core, GPLv3/vendored per that same doc) that this project's `refs/octabam` (a plain
fetch via `tools/refs/sync.py`, not a submodule-initialized clone of octabam's actual
dev setup) never received. **Not investigated: where to actually get these two
vendored trees from their original upstream sources**, whether they're large,
whether they build cleanly outside octabam's own dev environment, or how much total
setup time this really is. Could be modest (grab two repos, run cmake) or could be a
multi-hour yak-shave (version pinning, patches referenced in
`refs/octabam/CLAUDE.md`'s own trap list — e.g. `tools/patches/dsp56300.patch` for
the one-word-displaced-move assembler fix — a build dir, license/build-flag
mismatches). **If pursuing this path, budget time to find out before committing to
it**, and note the CLAUDE.md warning: never build in `refs/octabam` directly if it's
shared with other sessions — use a worktree.

### Do not revert `mt_trig`/`mt_rebind` without cause

Both are real, individually-correct, isolation-AND-dynamically-validated CPU-side
fixes — they stop code from running unnecessarily for a muted track and cause no
regressions in anything checked (`emu_solo.py` ×2 images, `emu_dt.py`,
`emu_mutemode.py` — all ALL GOOD). They just haven't been shown to fix the audible
symptom. Keep them in the build while investigating further; only remove either if a
future finding shows one of them is actively wrong (not just insufficient).

### Files touched this session (all current, all UNCOMMITTED on branch `wip` —
confirmed via `git status` at handoff time; nothing from this session has been
committed yet)

`tools/patch_softmute.s` (now: `pre` + `mt_trig` + `mt_rebind`, `pre_v` deleted),
`tools/build_mutemode.py` / `build_mutemode_dt.py` (3-detour `PATCHES` list, DT-diff
`allowed` spans updated for both new detour sites), `tools/emu_solo.py` / `emu_dt.py`
/ `emu_mutemode.py` (rewritten for `mt_trig`/`mt_rebind`, `pre_v` tests removed),
`tools/emu_mute_dynamic{1..12}.py` (the investigation scripts — kept, not scratch;
`_5`, `_9`, `_11`, `_12` are the ones worth re-running first if picking this back up;
`_1..4`, `_6..8`, `_10` are superseded intermediate steps, still functional but
lower-value to re-run). Build outputs: `out/OCTATRACK_OS1.40C_MUTEMODE{,_DT}.syx` /
`.bin`, current as of the last build in this session (both hooks included).

---

## Session 54 (2026-09-14) — `0x40006238` RESOLVED: CONFIRMED recorder-arm-only, a dead end for the mute-mode bug

Picked up the handoff's cheapest unresolved thread: is octabam's independently-traced
"real arm caller" (`0x40006238`, RTOS_FORK.md §10.13/§10.25) a second, previously
unexamined dispatch path for ORDINARY (non-recorder) FLEX/STATIC trigs, or is it
genuinely recorder-only as their own doc claims? Answered with both static
disassembly and a fresh dynamic run — no re-flash, no re-guess.

**First, a base-address trap caught before it could mislead anything.** This
project's own `tools/build_mutemode.py`/`build_mutemode_dt.py` both define
`BASE = 0x40000400` — the raw `out/raw/section_3_MAIN_OS.bin`'s byte 0 maps to VMA
`0x40000400`, NOT `0x40000000`. A first pass disassembling at the naive `0x40000000`
adjustment landed on plausible-looking but WRONG code at the addresses octabam
names (no `tstb %d7`/`bgew` pattern anywhere near where their doc puts it) — a false
mismatch that would have wrongly suggested the two projects were somehow looking at
different code. Re-run at the correct `0x40000400` base and every address octabam
cites lines up exactly, byte for byte.

**Static read of `0x40006238` (`m68k-elf-objdump -m 5307`, correct base) matches
their doc precisely:**

```
40006238: btst #4,%d7        ; bit 4 of the trig word = RECORDER-TRIG flag
4000623c: beq   0x400066bc   ; clear (ordinary trig) -> bail
40006240: tstl  %d4          ; set (recorder trig) -> machine-type check
40006242: beq   0x40006714   ; ... continues into the recorder-arm body (FUN_40097168
                             ;     call, the 0x00000101 record-header write at
                             ;     0x40006274 -- exactly §10.13's description)
```

An ordinary trig entering this function bails in 2 instructions, before touching
anything voice/audio-related. Traced the whole enclosing function
(`0x40005ff0`..`0x400066b0` roughly) and its sibling exit at `0x400066bc`
(`btst #6,%d7` — a second, different recorder-related flag, same immediate-bail
shape) — every substantial byte in it belongs to the same 84-byte-record
"RECORDER STATE" bookkeeping octabam's §10.13 point 4 already identified
(`0x80004f1c`, bank-indexed by `0x80004f18`), which is a completely different memory
region from the voice-struct arena (`0x800049d8+track*0xA8`) that
`FUN_4000f450`/`FUN_40006820`/`FUN_40006844`/`FUN_4000672c` (this project's own
`mt_trig`/`mt_rebind` targets, Session 53/53-bis) actually touch. Zero address
overlap between the two call graphs — confirmed by grepping the full disassembly
for cross-references, not just eyeballing.

**Found something the handoff hadn't traced yet: who calls `0x40005ff0` (the
function `0x40006238` lives inside), and when.** Only one xref in the whole image:
`4000d326: lea %pc@(0x40005ff0),%a4`, inside the FRAME BUILDER itself (the same
function as `0x4000d342`/`0x4000d36e`, already named in §10.13 as calling
`FUN_400068e4` "25,600 times in 1,600 frames"). The call sequence, per track per
frame:

```
4000d340: jsr %a3@              ; FUN_400068e4 -- composes/returns this track's trig word in d1
4000d348: andil #0xd0,d0        ; mask = bits 4,6,7 -- the SAME bits 0x40006238/0x400066bc test
4000d354: beq   0x4000d35e      ; none of those bits set -> skip entirely
4000d35a: jsr %a4@              ; only then call 0x40005ff0 (containing 0x40006238)
```

So there's a THIRD gate, upstream of both bits already found inside `0x40006238`
and `0x400066bc`: the frame builder itself only calls into this whole function when
the composed trig word already carries a recorder-related bit. An ordinary
FLEX/STATIC trig, whose word never sets bits 4/6/7, never reaches `0x40005ff0` at
all — not "enters and bails," genuinely never called.

**Dynamic confirmation (`tools/emu_mute_dynamic13.py`, new — same harness shape as
`_11`/`_12`, hooks `0x40006238` directly, no symbol table needed since it's stock
code): 6 s of real playback on the OT DEMO project (ordinary FLEX/STATIC trigs, no
recorder-armed track), watching for hits at `0x40006238` — 0 hits, for the entire
run.** Matches the static call-site finding exactly: not merely "reached but always
bails," but never reached at all, because the OT DEMO fixture never produces a trig
word with bits 4/6/7 set. Ruled out the obvious alternative explanation (hook
address wrong, or the caller condition not what static reading suggested) by first
verifying the correct-base disassembly's caller-condition trace above — the zero-hit
result is exactly what that trace predicts, not a surprise requiring a second
theory.

### Conclusion — the reconciliation question is settled

`0x40006238` is **CONFIRMED recorder-arm-only** (REC1/live-sampling specific, per
its own name and every gate on the path to it) and **a dead end for the mute-mode
trig-suppression bug**, which is entirely about ordinary FLEX/STATIC sequencer
playback. It is not "a second, previously-unexamined dispatch path for ordinary
trigs" in any sense — three independent gates (the frame builder's own `0xd0` mask
before even calling in, then `0x40006238`'s own `btst #4`, then `0x400066bc`'s
`btst #6`) all have to fail to reach it for a non-recorder trig, and the dynamic
run confirms none of them do.

This resolves the handoff's reconciliation question more precisely than either of
its two proposed answers: it's not that `0x4000672c` (this project's target) and
`0x40006238` (octabam's) are "the same shared subroutine, called from two different
places" (option 1) — they are two entirely disjoint functions serving two entirely
disjoint subsystems (recorder-arm bookkeeping vs. ordinary voice-start), with no
call-graph overlap at all. What DOES carry over is option 2's implication: this
session's `mt_trig`/`mt_rebind` targets (`FUN_40006844`/`FUN_4000672c`) were real,
frequently-executing, correctly-gated CPU-side code that nonetheless was never the
thing deciding whether a track's voice actually renders audio — and now there is no
remaining un-investigated CPU-side "arm caller" candidate left to blame. **Both
plausible CPU-side dispatch paths for this bug are now ruled out.**

### What's left, unchanged from the handoff, now the only two options

1. **Build the DSP-capable emulator** (`refs/octabam/tools/emu/ot_emu`) — the only
   tool that could show "does this track produce sound" directly. Still blocked on
   the two missing vendored C++ trees (`vendor/mc68k`, `vendor/dsp56300/source`),
   still not investigated where to get them or how much setup time that really is.
   This is now the more clearly-indicated path, since the cheap CPU-side static/
   dynamic leads are exhausted.
2. Keep `mt_trig`/`mt_rebind` in the build regardless (per the standing "do not
   revert without cause" guidance above — still real, still correct, still
   non-regressing) and look for a genuinely NEW CPU-side lead — but be aware none
   has been identified; inventing one without a concrete traced address to examine
   would be exactly the "re-guessing" the user has asked to avoid.

Files touched this session: `tools/emu_mute_dynamic13.py` (new, kept — not
scratch). No changes to `patch_softmute.s`, no rebuild, no reflash.

---

## Session 55 (2026-09-14) — `ot_emu` (the DSP-capable C++ port) IS NOW BUILT AND WORKING, and a first real DSP-level measurement raises a genuinely new question rather than closing the case

User asked to pursue the "build DSP-capable emulation" option Session 54 left as
the only remaining path, and specifically to check for and reuse octabam's own
existing tools before building anything new. Both paid off.

### The vendoring "blocker" was already solved by octabam's own `make setup`

Session 54's handoff described the two missing vendored trees
(`vendor/mc68k`, `vendor/dsp56300/source`) as unresolved — not registered as
git submodules, sourcing cost unknown. They didn't need investigating:
`refs/octabam/scripts/setup.sh` (the `make setup` target) already does exactly
this, unconditionally, idempotently: clones `vendor/mc68k` from
`joelanders/mc68k-md-mm` pinned to a specific commit, clones `vendor/dsp56300`
from `dsp56300/dsp56300.git` pinned to another, applies
`tools/patches/dsp56300.patch` (the shared-window / MPYRI / host-stepped-mode
patch CLAUDE.md's trap list already documents), and builds `dsp_asm`/
`dsp_host`/`dsp56kDisassemble`. Ran it (`cd refs/octabam && make setup`, ~2–3
min, all prerequisites — cmake, m68k-elf-gcc, brew — already present from
earlier sessions) — clean exit, no manual intervention. `vendor/mc68k`,
`vendor/dsp56300`, `vendor/elektron-firmware-tool` all present afterward, all
gitignored (confirmed: `git status` in `refs/octabam` stays clean).

Then `cmake --fresh -B out/emu -S tools/emu/ot_emu && cmake --build out/emu -j8`
(the exact `make emu-cf` recipe) — configured and built clean, zero errors
(only pre-existing upstream `-Wnontrivial-memcall`/`-Wformat-truncation`
warnings in vendored code). **This is the exact blocker Session 54 hit
("`add_subdirectory` can't find vendor/mc68k or vendor/dsp56300/source") —
now resolved in full, with tooling octabam already shipped.**

### The port is trustworthy: all four self-test gates pass against OUR OWN stock 1.40C

Staged `out/raw/section_3_MAIN_OS.bin` (our own project's, byte-identical
SHA-256 to what this project's own tools already use) into
`refs/octabam/out/raw/` (gitignored, not committed — matches "everyone builds
from their own 1.40C").

- `./out/emu/ot_emac_test` — **PASS**, every check (the EMAC gate CLAUDE.md
  calls the mandatory floor: "nothing this emulator computes is trustworthy
  until this passes").
- `./out/emu/ot_periph_test` — **PASS**, all peripheral models.
- `./out/emu/ot_rtos_test` — **PASS**: boots OUR stock image to the RTOS
  handoff, all ten tasks created and run, first 4831 serial bytes match route
  A byte-for-byte.
- `./out/emu/ot_dsp_test` — **PASS**: both DSP cores' boot ROMs and payloads
  upload and parse to their last byte, host round-trip counts match
  predictions exactly, both cores leave their bootstraps and run their
  payloads with no fault.

This is octabam's own C++ ColdFire+DSP56300 co-emulator, genuinely running,
genuinely rendering both real DSP cores, against this project's own firmware.
The thing Session 52–54 repeatedly needed and didn't have.

### First real measurement: staged our own project + our own patched build, muted a real sample-bearing track, and read back the DSP-shared audio feed directly

Reused route A's own staging (`tools/emu/ot_emu/stage_card.py`, which calls
the SAME `emu_rtos.stage_project` this project's own dynamic-probe scripts
already use — identical media either way, per `COLDFIRE_PORT.md`'s own rule
7). Found that route A's staging **never copies sample `.wav`/`.ot` files
onto the card by default** (`stage_card.py`'s own docstring: "route A stages
none by default, which is why every sample slot is empty and the DSP has
nothing to play") — the user's own "OT DEMO" project (used by
`emu_mute_dynamic11/13.py`) has an assigned FLEX/STATIC slot on every track
but literally nothing to play once staged this way, so a first attempt at
this exact measurement against it came back silent in BOTH the muted and
unmuted run — not evidence of anything, just no audio content to begin with.

Found a project in the user's own SET that DOES carry real STATIC sample
content (`ot_project.py report` against each project in
`~/Desktop/OT Backup/KYOTI/`): **`BOTLI`**, slot 1 = `BOTLI_CB2.wav`, bank A
part 1 track 1 = machine type FLEX... (see correction below) actually
STATIC/FLEX slot-byte 0 → pool slot 1, and T1 genuinely trigs and plays real
audio (confirmed both from the sequencer's own step-1 trig mask and from the
DSP's own rendered content). **Copied `BOTLI` to a scratch location before
touching anything** (`/private/tmp/.../scratchpad/BOTLI_TEST_SET/BOTLI` —
the original in the user's real backup was never opened for writing) and
staged its card with `--audio ".../AUDIO/BOTLI_CB2.wav:AUDIO/BOTLI_CB2.wav"`
(the exact path from the project's own `[SAMPLE] ... PATH=../AUDIO/BOTLI_CB2.wav`
record, relative to the SET folder, per `stage_card.py`'s own convention).

Ran `./out/emu/ot_emu` twice against **our own `mainos_mutemode_dt.bin`**
(this project's actual patched build, `mt_trig`+`mt_rebind` both active),
same card, same 150-frame sequencer run, `--dsp --main-level 64
--block-dump <file>` both times — once with no poke (control), once with
`--poke "0x800000df=1;0x8000000a=1"` (GATE=1 + MUTE_STATE bit 8 = track 0
muted, written after the load and before the transport starts, exactly
matching `patch_softmute.s`'s own `movel`-sized GATE/MUTE_STATE fields —
NOT a plain single-byte poke at the base address, which would have landed
in the wrong byte of the big-endian long).

Decoded T1's actual DSP-shared audio-feed record
(`0x80001c90`/`0x80002710`, the exact 84-word-per-track structure
`docs/firmware/COLDFIRE_PORT.md` Milestone O10 already validated
sample-exact against a real kick.wav) with octabam's own
`tools/scratch/o10_recloop.py` / `blockdump.py`. **First pass through their
`record_audio()` segment-header heuristic wrongly suggested a small residual
leak** (a repeating two-word blip surviving mute) — this turned out to be a
parsing artifact: that heuristic is tuned to octabam's own FLEX-on-recorder-
buffer fixture's exact header layout, and a two-word run of real early
audio-transient content in THIS track's record (values `16`, `302896`) just
happened to fail their header pattern-match too, so it fell into their
parser's raw-pairs fallback at the wrong offset. **Re-checked directly
against the RAW 84-word record, no parser in between:**

```
words[0:8]  IDENTICAL every frame, muted or not: [0,0,262144,0, 16,0,302896,0]
            -- this is the unconditional arena-rebind/bookkeeping header
            Session 53 already found and called harmless (the same "+4/+8"
            pointer-cache reassert that runs regardless of mute state) --
            now independently confirmed visible, at this exact position, in
            the DSP-shared record itself, not just in ColdFire RAM.
words[8:]   CONTROL: real, varying waveform content every frame (e.g. frame 2:
            0,0,-256,-256,-512,-512,-3840,-6144,...).
            MUTED:   flat ZERO, every single word, every single frame, for
            the entire 150-frame run. No leak, no blip, no residual --
            complete suppression from the very first audio sample.
```

149/150 captured frames differ at all between the two runs (only frame 1,
before any trig, is identical — both silent). The one frame that does NOT
differ in the header words (both write the same arena-rebind bookkeeping,
confirmed) but differs completely in real audio content, is a clean,
decode-independent result.

### What this means — and what it does NOT mean

**In this emulator, with this project, this exact firmware build, and this
exact mute timing (poked before the transport starts, i.e. before the
track's very first trig ever fires): `mt_trig`+`mt_rebind` produce total,
complete suppression of the DSP-fed audio content, with zero measurable
leak.** This is the first time in the whole investigation that a
DSP-observant tool has been able to check this claim directly rather than
inferring it from CPU-side register/memory state, and the fix passes
completely.

**This does not match the hardware report of "zero effect."** If this
record genuinely gates what reaches the analog output, and it shows perfect
silence here, hardware should have gone quiet too. It didn't. Two candidate
explanations, neither chased yet:

1. This specific `0x800xxxxx` DSP-shared-RAM record, while proven
   sample-exact for NORMAL playback (Milestone O10), might not be the whole
   story for a voice that's being CUT — the real DSP core could hold
   additional internal/latched state (an interpolator's own registers, a
   ring buffer position, an envelope already in flight) that this emulator
   models faithfully for continuous playback but that a mid-flight mute
   doesn't fully exercise in the same way real silicon's timing does. This
   is exactly the class of gap CLAUDE.md's own "a measurement can be
   structurally blind to what you're using it to rule out" warning names.
2. **More likely, and cheaper to check first:** this test muted the track
   BEFORE its first-ever trig — a clean, race-free mute. The real bug
   (NOTES.md's own framing: "suppressing a *new* sequencer trig while a
   track is HELD muted") may specifically need the track to have been
   PLAYING first, muted while already sounding, and then re-triggered —
   testing whether the SPECIFIC transition (unmuted-and-sounding →
   mute-engages → new trig arrives) behaves differently from
   muted-from-the-very-start. Untested this session. `--poke` only fires
   once, after the load; a live mid-run poke would need either a second
   `--poke-trig`-style CLI hook (none exists yet for MUTE_STATE) or scripted
   memory writes via a small wrapper — has not been attempted.

### Ruled out this session

- The vendoring blocker (see above) — fully resolved, not a blocker anymore.
- The port's basic trustworthiness against our own firmware — all 4 gates
  pass, not inferred.
- The very first, most obvious "is there a hardware-matching leak" reading —
  retracted after finding it was a decode artifact, not real. The corrected,
  raw-word reading is unambiguous: no leak in this exact scenario.

### Not yet done, concrete next steps in order of cost

1. **Cheapest:** re-run the same comparison but mute the track WHILE IT IS
   ALREADY PLAYING (start unmuted, let the DSP render real content for a
   frame or two, poke GATE/MUTE_STATE mid-run via a small change to
   `ot_emu`'s `--poke` timing or a direct scripted rebuild of this exact
   test with the poke moved into the frame loop) and re-trig — this is the
   scenario the fix's own name ("suppressing a *new* trig while a track is
   HELD muted") actually describes, and this session tested a materially
   different one.
2. If that still shows complete suppression: the gap is very likely
   somewhere this emulator's DSP model doesn't reach (real silicon timing,
   a latched register, an interrupt-boundary race) — at that point, hardware
   experimentation (not more emulation) becomes the only way forward, and
   should be discussed with the user before spending more session time on
   tooling.
3. Render actual audio (`--audio-out`) for a human-audible cross-check
   alongside the raw-record read, once the mute-while-playing scenario is
   built — not done this session (the raw-record read was decisive enough
   on its own not to need it yet).

### Environment/tooling now in place for next time (all gitignored, all local, nothing committed)

`refs/octabam/vendor/{mc68k,dsp56300,elektron-firmware-tool}`,
`refs/octabam/out/emu/{ot_emu,ot_emac_test,ot_periph_test,ot_rtos_test,ot_dsp_test}`
(built), `refs/octabam/out/raw/section_3_MAIN_OS.bin` (staged, our own
stock OS), `refs/octabam/out/mainos_mutemode_dt.bin` (staged, our own patched
build), `refs/octabam/out/botli_card.img` (staged BOTLI test card, real audio
included), `refs/octabam/out/botli_ctrl.dump` / `botli_muted.dump`
(block-dump captures from this session's comparison). The BOTLI copy used for
this test lives at `/private/tmp/.../scratchpad/BOTLI_TEST_SET/BOTLI` (session
scratchpad, not durable — rebuild from the user's own original + the exact
`--audio` flag above if picking this back up in a new session).

---

## Session 55 continued (same day) — THE LEAK FOUND: neither `mt_trig` nor `mt_rebind` is even reached for a REPEATED trig, and the raw DSP-fed voice content proves the sample fully restarts anyway. This is the "zero hardware effect" mystery, solved.

User: "Ok, proceed" — continued directly from the mid-play test's ambiguous
first read. Extended `ot_emu` itself (small, targeted C++ change, not a new
tool) to schedule pokes and forced trigs AT SPECIFIC FRAMES mid-run, instead
of only immediately after the load, then used that to build the ACTUAL bug
scenario end to end for the first time this whole investigation.

### `ot_emu` gained `--poke-at-frame` and `--poke-trig-at-frame`

`tools/emu/ot_emu/main.cpp`: `pokeAfterLoad`/`pokeTrig` used to apply once,
immediately after the load. Refactored into `applyPoke`/`applyPokeTrig`
lambdas plus a small sorted checkpoint schedule (`std::vector<pair<int,
function<void()>>>`) so either can be deferred to a given frame count
mid-run, in any order, then the sequencer run continues to `--frames`'
target from wherever it left off. Old behaviour (`pokeAtFrame`/
`pokeTrigAtFrame` both default `-1`) is byte-for-byte unchanged — verified
before touching anything else. Rebuilt clean (`cmake --build out/emu --target
ot_emu -j8`), no errors.

### First correction: the mid-play "zero effect" read from the last message was wrong — RMS/nonzero-count hid a real, working fade

Frame-by-frame (not aggregate) comparison of the CHAIN-OUTPUT readback
(`o10_recloop.readback_audio`, "the per-track chain output before the master
mix") for the mid-play-mute test showed the muted run's output DOES fall
away relative to control, starting ~4 frames after the poke and widening by
roughly 1–2 dB per frame (0.9 dB at +4 frames, 17+ dB by +24 frames) — a
smooth ramp-down, not silence and not "no effect". Checked the RAW
voice-source record (`track_audio`) for the same frames: **byte-identical
between muted and control, the whole time** — the underlying voice keeps
rendering completely normally; only the downstream chain output fades. This
is `pre` (the dry-cut/FX-tail-ring hook, `NOTES.md` line ~8041, "already
works, hardware-confirmed") doing exactly its documented job on a track that
was never re-triggered after the mute engaged. Not a bug — a working,
correctly-identified mechanism, and a useful calibration: aggregate
RMS/nonzero-count is too coarse to trust for any of these comparisons; every
finding below reads the frame-by-frame raw and chain-output records
directly.

### The real test: mute a track, let `pre`'s ramp fully settle, THEN force a genuinely NEW trig on the SAME already-muted track

The mid-play test above never re-triggered T1 — its pattern only has a step-1
trig, once per loop, thousands of frames away. `--poke-trig`/`--poke-trig-at-
frame` turned out not to help either: `rtos.pokeTrig()` just sets the
pattern's own step mask bit in RAM (route A's own established convention),
it doesn't fire an immediate trig — a bit set this way only fires once the
sequencer's own playhead naturally reaches that step. So instead: edited the
SCRATCH copy of BOTLI's pattern directly (`ot_project.set_pattern_trig(d, 1,
0, 0, 2, 0x00, guard=False)` — bank 1, pattern 1, T1, step 2 — the
`guard=True` default calls a `guard_backup()` that only recognises
octabam-author-specific backup paths and would abort here; `guard=False`
skips it since this is our own disposable scratch copy, never the user's
original) to give T1 a SECOND, reachable trig. Re-staged the card
(`out/botli_card2.img`), found the new trig lands at **frame 441** (measured
empirically from an unmuted control run's own `FW_LIVE_NIBBLE` log, not
assumed from tempo arithmetic).

Ran muted-from-frame-5 (well after T1's first natural trig at frame 0, well
before the pattern's frame-441 second trig) for 470 frames, block-dump
captured, and compared frame-by-frame against an unmuted control on the same
(edited) pattern:

```
frame   src_ctrl(dB)  src_muted(dB)    rb_ctrl(dB)  rb_muted(dB)
441          -27.0         -35.1           -41.7        -138.5   (T1 muted+decayed, ~silent)
443          -24.6         -24.6           -39.6        -138.5
444          -20.2         -20.2           -41.1         -41.3   <- raw source SNAPS to identical
445          -11.6         -11.6           -36.2         -36.2      chain output follows it too
446          -18.1         -18.1           -24.9         -24.9
447          -11.8         -11.8           -23.9         -24.2   <- chain output starts to
448          -10.7         -10.7           -29.2         -31.1      diverge again (pre re-engaging)
```

**From frame 444 the raw voice-source record is byte-identical to the
unmuted control** — the retrig fully re-binds and plays the sample, not a
partial leak, a COMPLETE, clean restart, indistinguishable from an unmuted
track. The chain output follows it almost exactly for ~3 frames before
`pre`'s ramp starts pulling it back down again. **This is the reported bug,
reproduced end to end for the first time in this whole investigation**: a
track held muted, re-triggered, produces real audio before anything catches
it — not a hypothetical, a directly observed, byte-level match to an
unmuted control.

### Why `mt_trig`/`mt_rebind` don't stop it: neither one is even the right gate for this trig

Watched (`ot_emu --watch-pc`, no rebuild needed, register dumps included)
`mt_trig`'s real entry (`0x40006844`) and its two branch targets
(`mt_silenced` `0x400d7526` / `mt_pass` `0x400d752e`, from `m68k-elf-nm
out/patch_softmute_dt.elf`) across the whole 470-frame run:

**`mt_silenced`: 0 hits. `mt_pass`: 1943 hits. And T1 (track index 0, whose
voice-struct base `0x800049d8` is directly visible in the register dump)
NEVER appears in mt_trig's 1943 calls at all** — only tracks 1, 3, 4 and a
recorder-buffer id (0x86) do, confirmed by their own voice-struct addresses
(`a2 = 0x80004a80` for d1=1, matching `0x800049d8 + 1×0xA8` exactly). **`mt_
trig`/`FUN_40006844` is simply never called for T1 in this whole scenario,
muted or not.** Session 53's whole causal chain (frame builder → `FUN_
40006820` → `FUN_40006844` → `FUN_4000672c` "the actual sample-restart step")
is real code, correctly gated — for tracks whose voice needs a FRESH bind.
T1's frame-441 retrig plays the SAME already-loaded static sample it played
at frame 0, so it never takes that path at all.

Then watched `mt_rebind`'s real detour site (`0x4000f4dc`) and its branches
(`mr_silence` `0x400d7584` / `mr_pass` `0x400d758a`) the same way: **7 total
site hits across the run, T1 appears exactly twice** — once at boot (frame
0's own trig, before the mute poke at frame 5, correctly took `mr_pass`,
register dump confirms `a2 = 0x800049d8` = T1's voice struct) and once at
timestamp 458584387 (frame ~441's retrig): **`a2 = 0x800049d8` (T1) →
`mr_silence`, with `d1 = 0x100` = exactly the MUTE_STATE bit this session
poked.** `mt_rebind` correctly recognises T1 is muted and correctly skips
its arena-pointer write for this exact retrig — **and the raw voice-source
record still shows a complete, clean restart four samples later regardless.**

**Both fixes are proven, directly, to be firing exactly as designed for this
retrig — mt_trig doesn't even apply here, and mt_rebind's own gate correctly
engages — and the DSP-fed audio content restarts anyway.** This is
Session 54's reconciliation option (2), now proven rather than inferred:
neither `FUN_40006844`/`FUN_4000672c` nor the `0x4000f4dc`/`e0` arena-pointer
write is the thing that actually decides whether a track's voice restarts
its playback. Both are real, both are correctly gated, and neither is load-
bearing for this bug. This is exactly why three flashes showed zero effect —
the fix was correctly implemented and had nothing to fix.

### Where the real gate almost certainly is — a concrete, already-partially-mapped next step

`mt_rebind`'s own detour site (`0x4000f4dc`/`e0`) sits INSIDE `FUN_4000f450`
— this session independently re-disassembled that whole function early on
(see the raw disasm captured this session, `0x4000f450`..`0x4000f560`) while
cross-checking the base-address convention, before realising it was already
Session 53/53-bis's own well-trodden ground. Its structure, now newly
relevant: it computes the track's target arena slot, writes the `+4`/`+8`
pointers (`mt_rebind`'s gate), **then branches on whether the arena slot
ALREADY holds the right content** (`0x4000f4e4..0x4000f514`): if NOT bound
yet, it calls `FUN_40006820` (mt_trig's own target — explaining why mt_trig
never fires for T1: its content is ALREADY bound, every single trig, since
it always plays the same static sample); if it IS already bound (T1's case,
every time), it falls into a **"reuse" path at `0x4000f526` onward** —
comparing stored content-ids, then (per this session's own partial read)
falling through toward `0x4000f54c` and beyond, never fully disassembled.
**This "reuse" path — reached on every repeat trig of an already-bound
voice, never touched by `mt_trig` or `mt_rebind`, and not yet disassembled
past `~0x4000f560`this session — is the strongest concrete candidate for
where the real restart signal lives.** No `MUTE_STATE` test has been found
anywhere in it yet, but it hasn't been fully read either.

### Ruled out this session, precisely, not by inference

- `mt_trig`'s gate is real and correctly implemented — for the case it
  actually covers (a fresh arena bind). It does not cover a repeat trig on
  an already-bound sample, which is what T1 (and very plausibly the user's
  real hardware scenario) does on every retrig.
- `mt_rebind`'s gate is real, correctly implemented, and directly observed
  firing correctly (`mr_silence` taken, with the exact expected `MUTE_STATE`
  value in a register) on the exact retrig that leaks. Its target write is
  provably not what gates DSP playback restart.
- The earlier "complete suppression, no leak at all" read (mute BEFORE the
  very first trig) is NOT evidence `mt_trig`/`mt_rebind` work for the bug's
  actual scenario — it's a DIFFERENT case (no voice ever bound at all, so
  nothing downstream had anything to restart) that this session initially
  conflated with the real "held muted, then retriggered" bug.
- `pre`'s dry-cut/FX-tail ramp is confirmed working correctly and is not
  part of this specific leak (it engages on the CHAIN OUTPUT a few frames
  after any trig, muted or not, matching its intended design of ducking one
  track's contribution before removing another factor).

### Not yet done

- Full disassembly of `0x4000f526` onward (the "reuse" path) — stopped at
  `~0x4000f560` this session, not because of a blocker, just time.
- A dynamic watch of whatever address that path branches to, to find the
  actual instruction that recomputes/resets the play position or triggers
  the DSP-side restart — the same `--watch-pc` technique used above applies
  directly, no new tooling needed.
- Once found: a gate on THAT address, isolation-tested and dynamically
  re-validated with this exact same BOTLI-retrig scenario (not the
  mute-before-first-trig one) as the acceptance test, since that's now
  proven to be the scenario that actually matters.

### Environment/tooling added this session (on top of the earlier Session 55 entry, all still gitignored/local)

`refs/octabam/tools/emu/ot_emu/main.cpp` modified (`--poke-at-frame`,
`--poke-trig-at-frame` — a real code change to a vendored tool, kept local,
not upstreamed, matches the project's own "everyone builds from their own
copy" posture already established for `vendor/`). `refs/octabam/out/
botli_card2.img` (T1 now trigs steps 1 AND 2), `out/botli2_ctrl.dump` /
`botli2_muted.dump` (the decisive comparison), `out/botli_muted_midplay.dump`
(the `pre`-ramp-only measurement, superseded for bug purposes but correct
and worth keeping as the `pre` regression reference). The scratch BOTLI copy
at `/private/tmp/.../scratchpad/BOTLI_TEST_SET/BOTLI` now has the edited
pattern (step 2 added) — rebuild it fresh (from the user's ORIGINAL, never
edited) plus the same `set_pattern_trig` call if picking this back up in a
new session, since `/private/tmp` is not durable across sessions.

---

### Exact prompt to start the next session with

```
Continue the MUTE MODE trig-suppression investigation in
~/Documents/octatrack-kyoti-fw. Read NOTES.md's "Session 55 continued" section
(at the very end of the file) first -- the bug is now REPRODUCED end to end
in the DSP-capable emulator (refs/octabam/tools/emu/ot_emu, built this
session via octabam's own `make setup`) and its cause is narrowed to a
specific, partially-disassembled function, not a mystery anymore. Summary:
muting a track, letting it settle, then forcing a genuinely NEW trig on the
SAME already-muted track (built via a small ot_emu extension,
--poke-at-frame / --poke-trig-at-frame, plus editing a scratch copy of the
BOTLI project's pattern to add a second trig -- never the user's original)
reproduces the reported blip exactly: the raw DSP-fed voice content fully
restarts, byte-identical to an unmuted control, four frames after the trig.
Direct --watch-pc register dumps PROVE both mt_trig (never even called for
this track/scenario -- it only fires on a fresh arena bind, and this track's
sample is always already bound) and mt_rebind (correctly detects the mute,
correctly takes its silence branch, confirmed via the exact MUTE_STATE value
in the register dump) are NOT what gates this. The concrete next step,
already half-mapped: finish disassembling FUN_4000f450's "reuse" path
(0x4000f526 onward, m68k-elf-objdump -m 5307, base 0x40000400) -- reached on
every repeat trig of an already-bound voice, never touched by either
existing hook -- then --watch-pc it dynamically the same way mt_trig/
mt_rebind were watched this session, to find the actual restart signal and
gate IT. Don't re-flash hardware until a new fix has been isolation-tested
AND re-validated against this exact BOTLI-retrig scenario (not the
mute-before-first-trig one, which is now known not to be the bug).
```

---

## Session 56 (2026-09-14, `wip`) — the "reuse" path fully disassembled, and its unguarded write DYNAMICALLY CONFIRMED to fire on T1's own leaking retrig

Picked up exactly where Session 55 continued's handoff left off. Scratch BOTLI
setup is not durable across sessions (`/private/tmp`), so rebuilt it fresh from
the user's real, untouched `~/Desktop/OT Backup/KYOTI/BOTLI` (never opened for
writing): copied to a new scratchpad location, re-applied the same
`ot_project.set_pattern_trig(d, 1, 0, 0, 2, 0x00, guard=False)` edit (bank 1,
pattern 0, T1, step 2 — gives T1 a second, reachable trig at frame 441, same as
last session), re-staged via `stage_card.py` to a fresh `botli_card2.img`.

### A tooling correction found first: the project's own `-m 5307` objdump convention is WRONG for this firmware

`tools/emu_mute_dynamic13.py`'s header comment (and by extension anything else
citing "m68k-elf-objdump -m 5307") names the wrong ColdFire variant.
`m68k-elf-objdump -D -b binary -m 5307 --adjust-vma=0x40000400 out/mainos.bin`
produces silently WRONG disassembly for a specific instruction class: any
`mvsb`/`mvzb`/`mov3q` (ColdFire ISA_B "move byte/word with sign/zero extend" /
"move 3-bit quick") opcode decodes as a bare `.short` (undecoded raw word) under
`-m 5307` (ISA_A only), which — because objdump still advances exactly 2 bytes
per undecoded word — does NOT desync alignment, but DOES silently hide real
instructions as inert data in the printed listing. `patch_softmute.s`'s own
header says the real target is `-mcpu=5407` (assembler side); the matching
**objdump flag is `-m 5407`**, confirmed: every `.short` in a raw `-m 5307` dump
of `FUN_4000f450` resolves cleanly under `-m 5407` (`mvsb`/`mvzb`/`mov3ql`), and
the two independently-known-correct anchors (`mt_rebind`'s own detour bytes at
`0x4000f4dc`, and the `jsr 0x40006820` "not yet bound" branch at `0x4000f51e`,
both already hard-verified against the project's own patch scripts) read
byte-identical either way, so this was purely a table-coverage gap, not a
misalignment. **Use `-m 5407` for all future static disassembly of this
firmware; `emu_mute_dynamic13.py`'s comment should be corrected too (not done
this session, flagging here so it isn't propagated further).**

### `FUN_4000f450`'s "reuse" path (`0x4000f526` onward), fully disassembled

Full listing in `/private/tmp/.../scratchpad/mainos_5407.dis` this session (not
durable — regenerate with the command above if picking this back up). Structure,
address range `0x4000f526`-`~0x4000f900`:

- `0x4000f526`-`0x4000f54c`: the content-id comparison Session 55 already read
  correctly (falls into "reuse" when the arena slot already holds this track's
  content — T1's case, every trig).
- `0x4000f54c`-`0x4000f672`: computes four flag/derived values (`d1`/`d3`/`d4`/
  `d5`/`d7`) from the track's machine-type byte, some part-config bytes, and a
  `0x3fff` bound check — feeds the position math below. Not fully named, but
  every value here is fed from the track's own PART/machine-type bytes, nothing
  from `MUTE_STATE`.
- `0x4000f672`-`0x4000f6da`: computes a work pointer (`a1` or `a0`, depending on
  a `d6==4` "recorder?" branch at `0x4000f68c`) into what looks like a
  per-machine-type 300-byte-stride table anchored off `a4` (a4 = a static base,
  `0x4000f484`-era `a2` is the VOICE_BASE+track*0xA8 struct; `a4` is a
  DIFFERENT, still-unnamed base — likely the ARENA/pool descriptor table, since
  `a4@(1092)`/`a4@(300..)` read like slot-count/slot-array fields).
  **CORRECTION mid-session**: this is the same region octabam's own CLAUDE.md
  flags as the recorder-length-converter/EMAC-fractional-multiply danger zone
  (`0x4000f700`: `macl %d1,%d0` — a genuine EMAC multiply) — did NOT chase this
  further; it's upstream of the writes that matter below and not itself a
  MUTE_STATE gap candidate (no mute-relevant test could sensibly live inside a
  pure arithmetic macro).
- `0x4000f700`-`0x4000f78a`: fixed-point start/end-point arithmetic (the `macl`
  at `0x4000f700`/`0x4000f732`, a `remsl`/`mulsl` pair at `0x4000f80a`/`f80e` —
  percentage-of-length math, consistent with computing START/END/LOOP sample
  positions from the track's TRIM/LOOP percentage bytes). Produces two values,
  left in `%d2`/`%a1`.
- **`0x4000f790`-`0x4000f7a4`: six unconditional `movel` writes into the voice
  struct** (`%a2@(0x2c)`, `%a2@(0x28)`, `%a2@(0x34)`, `%a2@(0x30)`, `%a2@(0x3c)`,
  `%a2@(0x38)` — three D2/A1 pairs, almost certainly START/END for two buffer
  halves or a normal+alternate pair). **No `MUTE_STATE` test anywhere before or
  between these.**
- `0x4000f7a8`-`0x4000f820`: a second position computation (current play
  pointer, `a0`), branching on machine-type/part-state bytes and a modulo
  (`remsl`/`mulsl` again at `0x4000f80a`-ish for a LOOP-wrap case).
- **`0x4000f820`-`0x4000f838`: five more unconditional writes** — `%a2@(0x40)`,
  `%a2@(0x44)`, `%a2@(0x48)` (all the same `a0`, the just-computed play
  pointer), `%a3@(0x38)` (**a THIRD struct pointer**, `a3` = `%sp@(50)`, i.e.
  the "current arena slot" pointer saved back at `0x4000f48e` — so this reaches
  outside the per-track voice struct into the shared arena-slot record too),
  **then `addql #1,%a2@(0x90)`** (`0x4000f834`) — **the EXACT per-track trig
  counter offset `patch_softmute.s` already named and dynamically confirmed
  (hook 2's own header comment: "VOICE_BASE+track*0xA8+0x90 -- confirmed
  dynamically: this exact location increments 1,2,3,4,... on every real
  trig")** — followed by `movel %a0,%a2@(0x98)` (`0x4000f838`, a 14th write).
  **This is a SEPARATE bump of the SAME counter field `mt_trig`'s own hook
  (`FUN_40006844`) was built around — from a completely different call site,
  never gated by either existing hook, and (per the disasm) unconditional on
  `MUTE_STATE` the entire way down from `0x4000f526`.**

### Dynamic confirmation: this whole tail fires for T1 on its own leaking retrig, muted the whole time

`refs/octabam/out/emu/ot_emu --image out/mainos_mutemode_dt.bin --card
out/botli_card2.img --set OCTABAM --project BOTLI --mount --sequencer
--internal-clock --frames 470 --dsp --main-level 64 --poke
"0x800000df=1;0x8000000a=1" --poke-at-frame 5 --watch-pc
"0x4000f834,0x4000f790,0x4000f794,0x4000f798,0x4000f79c,0x4000f7a0,0x4000f7a4"`
(GATE=1/OT+FX + MUTE_STATE bit 8 = track 0 muted, applied mid-run at frame 5 —
same convention as every earlier probe this thread).

14 hits total, in two clean groups of 7:
- **Group 1, instruction timestamps 446287027-446287046**: frame 0's own
  natural trig, BEFORE the mute poke (applied at frame 5) — expected, baseline.
- **Group 2, instruction timestamps 458584541-458584560**: frame 441's forced
  retrig — well AFTER the frame-5 mute poke. **`a2 = 0x800049d8` at every one
  of the 7 watched addresses** — T1's own voice-struct base
  (`VOICE_BASE + 0×0xA8`), the identical value Session 55 continued's
  `mt_rebind` watch confirmed on this exact same retrig (where `mr_silence` was
  correctly taken, `d1 = 0x100` matching `MUTE_STATE` bit 8).

**This proves the whole `0x4000f790`-`0x4000f838` write sequence — six START/
END-style position writes, five more play-pointer/arena writes, and the
per-track trig counter bump `mt_trig`'s own hook was named after — executes in
full for T1's frame-441 retrig, on the SAME call where `mt_rebind`'s gate
correctly recognised the mute and correctly skipped its own two writes.** This
is the missing piece Session 55 continued closed with as "the strongest
concrete candidate" — now dynamically verified, not just statically inferred.

### Proposed fix (NOT YET BUILT) — narrowest candidate: gate the counter bump only

Following this project's own established minimal-hook philosophy (gate the
smallest thing that plausibly matters, leave everything else's computation
untouched): detour the 8-byte pair at `0x4000f834`/`0x4000f838` (`addql #1,
%a2@(144)` + `movel %a0,%a2@(152)`, `52aa 0090 2548 0098`) — same 6-byte-`jmp`-
plus-2-bytes-spare budget every other hook in this project uses. In the cave:
test `MUTE_STATE`/`SOLO_FLAG` the same way `mr_silence` does (track number from
`%sp@(0x40)`, confirmed STILL the valid, unshifted argument slot this deep into
the function — the prologue's `lea sp@(-60),sp` + `moveml ...,sp@` never
pushes anything additional on the path that reaches here, and the one place
that does push/pop (`0x4000f514`-`0x4000f520`, the "jsr FUN_40006820" branch)
is a DIFFERENT branch that returns early and never reaches `0x4000f834` at
all); if muted (or solo-silenced), **skip only the `addql`**, always still
execute the `movel %a0,%a2@(152)` (unknown purpose, kept unconditional out of
caution — same reasoning `mt_rebind` used for leaving `%a5`/`%a4` computation
untouched while gating only their store). `%d0`/`%d1` confirmed free to clobber
at this exact point (`0x4000f83c` reloads `%d0` fresh, `0x4000f842` reloads
`%d1` fresh, neither's pre-hook value is read again first).

**Caveat, stated as plainly as `mt_rebind`'s own was**: this is the NARROWEST
plausible candidate, not a proven one. The dynamic watch proves all 7 addresses
fire unconditionally; it does NOT by itself distinguish whether the counter
bump, the START/END writes, or the play-pointer writes are the thing the DSP
actually keys its restart on. Gating only the counter is the cheapest single
change to isolation-test and dynamically re-validate first; if the BOTLI
retrig comparison (Session 55 continued's byte-identical-to-unmuted-control
test) still shows a full restart with only the counter gated, the next
candidate is the six `0x4000f790`-`0x4000f7a4` position writes.

### `mt_ctr` BUILT, isolation-proven at the CPU level, DSP-level A/B says it does NOT fix the bug

Built (`patch_softmute.s` hook 4, wired into `build_mutemode_dt.py`'s
`patch_softmute` detour list at `0x4000f834`, allowlisted in the vs-
`build_mutemode.py` consistency check). Assembled clean, all of
`build_mutemode_dt.py`'s own checks passed (manual-trig fix byte-identical,
0 stray bytes vs `build_mutemode.py` outside the new cave/detour, no cave
overlaps).

**CPU-level gate confirmed correct** (`ot_emu --watch-pc
"0x4000f834,0x400d75e0,0x400d75ea"`, same BOTLI card/scenario): frame 0's
natural trig enters `mt_ctr` and exits via `mc_pass` (unmuted, both writes
happen). Frame 441's forced retrig — muted since frame 5 — enters `mt_ctr` and
exits via **`mc_silence`**, with `d0=0x8` (track 0 + 8) and `d1=0x100`
(`MUTE_STATE` bit 8) confirming the gate fired on the right test, for the
right track. The hook behaves exactly as designed, same as `mt_rebind` before
it.

**DSP-level A/B (the real test) says this does NOT fix the leak.** Two fresh
`--block-dump` captures against the rebuilt `mainos_mutemode_dt.bin`
(`out/botli3_ctrl.dump` no poke, `out/botli3_muted.dump` same
mute-at-frame-5 poke as every prior probe), compared frame-by-frame on T1's
raw voice-source record (`track_audio`, same decode `o10_recloop.py` already
uses) from frame 435 to 460:

```
 frame  ctrl_peak_dB  muted_peak_dB  identical?
   441         -27.9          -27.9  True    <- pre-retrig, as expected
   442         -26.1          -26.1  True
   443         -28.8          -22.4  False   <- first frame to diverge
   444         -17.9           -5.6  False   <- muted run LOUDER than control here
   445         -14.1           -4.3  False
   446          -4.6           -4.5  False
   447         -10.3           -4.8  False
   448          -5.6           -4.8  False
   449          -4.3           -3.0  False
   ...content continues at -1 to -10 dB through frame 460, no decay trend
```

Two things are now established, precisely: (1) the content is **no longer
byte-identical to the unmuted control** past frame 442 — gating the counter
DID change something real, so the hypothesis that this call site matters is
not dead; but (2) the muted run is **not silence** either — it stays loud
(mostly -3 to -10 dB, occasionally louder than control at the same frame,
e.g. frame 444: muted -5.6 dB vs control -17.9 dB) with no visible decay
trend across the 16 frames sampled. **Gating only the counter bump trades a
clean restart for a DIFFERENT, still-substantial burst of audio — not a fix.**
Most likely explanation, not yet confirmed: the six START/END position
writes at `0x4000f790`-`0x4000f7a4` (still fully unconditional, ungated) and
the play-pointer writes at `0x4000f820`-`0x4000f830` still land fresh
position data in the voice struct every retrig regardless of mute, and
whatever DSP-side logic reads them evidently does not need this ColdFire-side
counter to notice new content — it may instead be edge-triggered on the
position values themselves changing, or on something in the still-untouched
arena-slot write at `%a3@(0x38)` (`0x4000f830`, a THIRD struct this session's
disasm flagged but did not chase).

**RULED OUT this session, precisely, not by inference**: the per-track trig
counter bump at `%a2@(0x90)` (`0x4000f834`, reached from `FUN_4000f450`'s own
"reuse" path) is NOT, by itself, the DSP's restart-detection signal. Gating
it changes the resulting audio (proving the call site is real and DSP-
visible in some way) but does not silence it.

### Not yet done

- **Next candidate, not yet tried**: gate the six position writes at
  `0x4000f790`-`0x4000f7a4` (three `movel` pairs into `%a2@(0x28/0x2c)`,
  `%a2@(0x30/0x34)`, `%a2@(0x38/0x3c)`) instead of, or in addition to, the
  counter. Same detour-pair technique; three separate 8-byte pairs (each is
  two consecutive 4-byte `movel`s) or one larger span if a single jmp can
  cover all six writes' address range cheaply — check the exact byte count
  and pick the narrowest cave that still fits a `jmp`.
  - Whether to leave `mt_ctr` (the counter gate) in place alongside a new
    position-write gate, or revert it first and re-test the position gate in
    isolation, is an open call — reverting first is cleaner for attributing
    which gate does what, but leaving both in is closer to "gate everything
    this session found unconditional" if the position writes alone don't
    fully silence it either.
  - Also worth a look, not yet disassembled in detail: the `%a3@(0x38)`
    write at `0x4000f830` (`a3` = the arena-slot pointer saved at
    `0x4000f48e`, a structure distinct from the per-track voice struct `a2`
    points at) — a THIRD struct touched unconditionally, not yet considered
    as its own candidate.
- Keep using the exact `track_audio`/`blockdump.py` frame-by-frame comparison
  `tools/cmp_botli_retrig.py` (saved this session:
  `python3 tools/cmp_botli_retrig.py CTRL.dump MUTED.dump [FIRST] [LAST]`)
  used — aggregate RMS is not enough, as Session 55
  continued already found once.
- Still do not reflash hardware until the DSP-level A/B comparison shows the
  muted run go convincingly quiet (not just "different"), matching the
  unmuted-control's decay-to-silence shape a working fix should produce.

## Session 56 continued (same day) — `mt_pos` BUILT and tested: the six position writes have ZERO measurable effect, ruling them out cleanly; next candidate identified

User: "Let's continue with Mute Mode." Built the next candidate exactly as
scoped above.

### `mt_pos` (hook 5): gates the six `0x4000f790`-`0x4000f7a4` START/END-style
writes as one 24 B block. Wired into `build_mutemode_dt.py`, `mt_ctr` (hook 4)
DISABLED for this round (commented out of the detour list, code left in
`patch_softmute.s` for reference) to isolate causality cleanly. Cave growth
forced `patch_mutemode`'s load address to move `0x400d7600` -> `0x400d7670`
(patch_softmute grew to 612 B and started overlapping it) — purely a cave-
layout fix, no behavioural change; still clears `LBL_AT` (`0x400d7700`) with
room to spare, all of `build_mutemode_dt.py`'s own consistency checks passed
(0 stray bytes vs `build_mutemode.py`, manual-trig fix untouched, no cave
overlaps).

**CPU-level gate confirmed correct** (`ot_emu --watch-pc
"0x4000f790,0x400d7640,0x400d7646"`, same BOTLI card): frame 0 takes
`mp_pass` (unmuted). Frame 441's forced retrig takes **`mp_silence`**, with
`d0=0x8`/`d1=0x100` matching track 0 + `MUTE_STATE` bit 8, exactly like
`mt_ctr` and `mt_rebind` before it — same gate-correctness pattern, third
hook running for three.

**DSP-level A/B: ZERO effect, cleaner (and more informative) than `mt_ctr`'s
partial one.** Fresh `--block-dump` pair (`out/botli4_ctrl.dump`,
`out/botli4_muted.dump`), compared with the now-`tools/`-resident
`cmp_botli_retrig.py` from frame 435 to 469 (extended range vs last time):
**every single frame reports `identical? True`**, muted vs control, all the
way through frame 469 — not just "close", byte-for-byte identical, same as
the original ungated leak. Skipping these six writes changes NOTHING about
the resulting DSP-fed audio.

**RULED OUT this session, precisely, not by inference**: the six START/END-
style position writes at `%a2@(0x28/0x2c/0x30/0x34/0x38/0x3c)` are NOT read
by whatever drives the DSP's immediate playback content — gating them is
completely inert. Combined with `mt_ctr`'s partial (content-changing but
non-silencing) effect, the emerging picture: the trig counter bump is
DSP-visible in SOME way (changes the resulting audio) but isn't itself the
"where to play from" signal; the position/loop-bound fields aren't DSP-
visible at all on this timescale. The likely remaining candidate is the
ACTUAL current-play-pointer write, `a0`-based and computed separately
(`0x4000f7a8`-`0x4000f820`'s own modulo/loop-wrap arithmetic), written at
`0x4000f820`-`0x4000f830` — a genuinely different register/value than the
`d2`/`a1` pair `mt_pos` gated.

### Next candidate: `0x4000f820`-`0x4000f830`, the play-pointer writes

Four writes, 20 B, `0x4000f820` to `0x4000f834` (right where the counter
bump — currently disabled — begins): `movel %a0,%a2@(0x40)`, `movel
%a0,%a2@(0x44)`, `movel %a0,%a2@(0x48)` (three copies of the SAME just-
computed play pointer into the per-track voice struct), and `movel
%a0,%a3@(0x38)` (a THIRD struct, `a3` = the arena-slot pointer, reloaded
fresh from `%sp@(0x32)` immediately before by `moveal %sp@(0x32),%a3` at
`0x4000f82c`). This is the strongest remaining candidate precisely because
`a0` here is the actual CURRENT PLAYBACK POSITION (the output of the
modulo/loop-wrap arithmetic just above it), not a cached bound — exactly
the kind of value a DSP-side player would read every frame to know where to
fetch the next samples from.

Design for the next hook (`mt_ptr`, not yet built): always execute the
`moveal %sp@(0x32),%a3` reload (harmless local-variable reload, no reason to
gate it); gate only the four `movel %a0,...` writes, same silenced-track
test as every hook above, same track-number source (`(0x40,%sp)`, still
valid this deep in). `%d0`/`%d1` clobbered by the gate check itself, same as
every hook so far — `mt_pos`'s own clean result (byte-identical unmuted
output, no corruption) is good empirical evidence this same
clobber-then-branch pattern is safe in this general vicinity of the
function, so no new liveness proof attempted by hand this time; verify
empirically instead (compare the new build's UNMUTED control run against
`out/botli4_ctrl.dump` — byte-identical there would confirm no register
corruption on the pass-through path, same check style already used).

### Not yet done

- Build `mt_ptr` (design above), wire into `build_mutemode_dt.py` (mind the
  cave-size growth again — check for a `patch_mutemode` collision before
  assuming the current `0x400d7670` load address still has room).
- Isolation `--watch-pc` check (silence branch taken on the T1 retrig, pass
  branch taken on frame 0 — same pattern as every hook so far).
- DSP-level A/B via `tools/cmp_botli_retrig.py` against fresh
  `out/botli5_ctrl.dump` / `out/botli5_muted.dump`. Also diff the new
  build's OWN unmuted control against `out/botli4_ctrl.dump` first, to rule
  out register-clobber corruption before trusting the muted-run comparison.
- If `mt_ptr` alone doesn't produce real silence either: the remaining
  unconditional writes past `0x4000f834` (currently untouched, `mt_ctr`
  disabled) are the counter bump and `movel %a0,%a2@(0x98)` — worth
  re-combining `mt_ctr` + `mt_ptr` together next, since `mt_ctr` alone did
  measurably change the output even though it didn't silence it.
- Still do not reflash hardware until the DSP-level A/B shows real silence,
  not just a difference from control.

### Environment/tooling this session

Corrected objdump invocation (`-m 5407`, not `-m 5307`) — see above; full raw
disasm at `/private/tmp/.../scratchpad/mainos_5407.dis` and
`/private/tmp/.../scratchpad/mainos_full.dis` (the original, `-m 5307`,
partially-garbled version — kept only as the before/after evidence for the
tooling-correction note above, not useful for further work). Neither survives
the session boundary; regenerate with `m68k-elf-objdump -D -b binary -m 5407
--adjust-vma=0x40000400 out/mainos.bin` if picking this back up.
`refs/octabam/out/botli_card2.img` rebuilt fresh this session (same recipe as
Session 55 continued, scratch BOTLI copy + `set_pattern_trig` + `stage_card.py`
— the scratch BOTLI project itself is also gone again at
`/private/tmp/.../scratchpad/BOTLI_TEST_SET/BOTLI`, rebuild the same way).

### Exact prompt to start the next session with

```
Continue the MUTE MODE trig-suppression investigation in
~/Documents/octatrack-kyoti-fw. Read NOTES.md's "Session 56" section (at the
very end of the file) first, ALL of it including the "mt_ctr BUILT... DSP-
level A/B says it does NOT fix the bug" subsection -- a fix was already tried
and dynamically disproven this session, don't repeat it. Summary: the "reuse"
path inside FUN_4000f450 (0x4000f526 onward, the same function mt_rebind
partially hooks at 0x4000f4dc) is now fully disassembled (use
`m68k-elf-objdump -D -b binary -m 5407 --adjust-vma=0x40000400 out/mainos.bin`
-- NOT -m 5307, that flag silently mis-decodes real instructions as inert
.short data). It writes six START/END-style position fields into the voice
struct (0x4000f790-0x4000f7a4), five more play-pointer/arena writes
(0x4000f820-0x4000f830, including a THIRD struct via %a3@(0x38), not yet
examined as its own candidate), and bumps the per-track trig counter
(%a2@+0x90, 0x4000f834) -- all completely unconditional on MUTE_STATE, all
dynamically confirmed firing on T1's real frame-441 leaking retrig
(ot_emu --watch-pc, out/mainos_mutemode_dt.bin + a freshly rebuilt
out/botli_card2.img -- rebuild the scratch BOTLI + card first, /private/tmp
doesn't survive a session boundary; exact recipe in the Session 55
continued / Session 56 text). A new hook, `mt_ctr` (patch_softmute.s hook 4,
wired into build_mutemode_dt.py), gates ONLY the counter bump at 0x4000f834.
It's built, and CPU-level (--watch-pc) proves its own gate fires correctly.
But the real test -- a DSP-level block-dump A/B on T1's raw voice-source
record, frame-by-frame (tools/scratch pattern: bd.classes(bd.read(dump)) +
o10_recloop.track_audio/record_audio, NOT aggregate RMS) -- shows the muted
run is no longer byte-identical to an unmuted control past frame 442 (so the
call site is real) but ALSO not silence: it stays loud (-3 to -10 dB,
sometimes louder than control) with no decay trend through frame 460. Gating
the counter changes the leak, does not fix it. The concrete next step,
already scoped in NOTES.md: gate the six 0x4000f790-0x4000f7a4 position
writes instead (or in addition -- open call, argued both ways in NOTES.md),
same detour-pair technique, then re-run the exact same frame-by-frame DSP-
level comparison (not just --watch-pc) and look for the muted run actually
trending toward silence, not just differing from control. Do not reflash
hardware until that comparison shows real silence.
```

## Session 56 continued (same day) — a methodology correction (compare READBACK, not just raw source), `mt_pos`/`mt_ptr` reconfirmed inert, `mt_ctr` found to make the blip WORSE, and a `pre`-side hypothesis tried and also ruled out. Build restored to the known-safe baseline.

User: "Let's continue with Mute Mode." Built and tested `mt_pos` (see above), then
pushed further this same continuation.

### A methodology gap found and fixed: `track_audio` (raw voice source) is the WRONG signal to judge audibility by itself

Every comparison up to and including `mt_pos`'s test used only
`o10_recloop.track_audio` (Session 55 continued's own "src" column) via
`tools/cmp_botli_retrig.py`. Re-reading Session 55 continued's ORIGINAL table
carefully (it has FOUR columns: `src_ctrl`/`src_muted`/`rb_ctrl`/`rb_muted`,
not two) exposed the gap: `track_audio` captures the voice generator's own
output, UPSTREAM of the track's FX chain and the mute-gate mixing that
happens after it (`o10_recloop.readback_audio`, "the per-track chain OUTPUT
before the master mix" — the "rb" column). A hook can leave `track_audio`
showing a full "restart" and STILL be completely silent at `readback_audio`,
if whatever gates audibility acts downstream of the voice generator. Fixed
`tools/cmp_botli_retrig.py` to print both signals side by side (`src=?` /
`rb=?` columns) — this is the tool to use from here on; a `src`-only reading
is not sufficient to judge whether a hook is helping.

### Every hook tested so far, RECHECKED with the corrected tool, against a properly-identified BASELINE

First re-ran the ORIGINAL ungated leak (`out/botli2_*.dump`, Session 55
continued's own capture, predates every hook this session added) through the
fixed tool. This is the correct comparison baseline — and it changes the
picture substantially:

```
 frame  src_ctrl  src_muted  src=?    rb_ctrl  rb_muted  rb=?
   440     -26.1      -28.8  False      -38.7    -138.5 False
   ...
   444     -17.9      -17.9   True      -38.4    -138.5 False   <- src "restarts" here (the
   445     -14.1      -14.1   True      -31.0     -30.8 False      finding Session 55 called
   446      -4.6       -4.6   True      -30.1     -30.0 False      "the bug") but readback is
   447     -10.3      -10.3   True      -17.9     -18.1 False      STILL near-silent (-138.5)
   448      -5.6       -5.6   True      -16.4     -16.5 False      through frame 444 -- the
   449      -4.3       -4.3   True      -22.3     -23.9 False      AUDIBLE blip is frames
   450      -4.5       -4.5   True      -18.8     -22.0 False      445-448, where rb_muted
   ...                                                             tracks rb_ctrl within ~0.2 dB
   456      -5.1       -5.1   True      -19.5     -31.7 False   <- by here `pre`'s own ducking
   460      -1.2       -1.2   True      -13.2     -30.7 False      has pulled rb_muted well
                                                                     below rb_ctrl again
```

This IS a real, audible ~4-frame blip (445-448, rb_muted within ~0.2 dB of
rb_ctrl) — confirms the bug is real, exactly where Session 55 found it — but
it clarifies the SHAPE: `rb` is silent through 444 regardless of any hook
(that part was never broken), the leak is specifically frames ~445-448, and
`pre`'s own ducking already pulls it back down by ~449-450 on its own, with
no help from any of hooks 4-6. **The useful metric going forward is the
`rb` delta specifically in frames 445-449, not "identical or not" over an
arbitrary wide window.**

Recomparing each hook against this baseline, `rb` column, frames 445-449:

- **`mt_pos` alone, `mt_ptr` alone**: `rb` values byte-for-byte IDENTICAL to
  the ungated baseline at every single frame checked (435-469). Confirms
  the earlier `src`-only "zero effect" reading was actually right for the
  RIGHT reason this time — these two are inert at both levels, cleanly
  ruled out.
- **`mt_ctr` alone**: `rb_muted` at 445/446/449 is **10-12 dB LOUDER** than
  the ungated baseline's own `rb_muted` at those same frames (e.g. frame
  445: baseline -30.8 dB, `mt_ctr` -22.4 dB; frame 449: baseline -23.9 dB,
  `mt_ctr` -16.3 dB). **`mt_ctr` makes the actual audible blip WORSE, not
  better.** This reframes the earlier "partial effect" reading (which was
  `src`-only and didn't know if the change was good or bad) into a clear,
  concrete negative: gating the trig-counter bump is actively
  counterproductive, not merely insufficient.
- **Combined (`mt_pos`+`mt_ptr`+`mt_ctr`)**: dominated by `mt_ctr`'s own
  effect, same pattern (some frames louder, e.g. 445 combined -18.6 dB vs
  baseline -30.8 dB), consistent with `mt_pos`/`mt_ptr` contributing
  nothing on top.

**RULED OUT this session, precisely, at the correct (readback) level**: none
of `mt_pos`, `mt_ptr`, or `mt_ctr` reduce the audible blip; `mt_ctr` actively
increases it in the critical frames. Build restored to disable all three
(commented out of `build_mutemode_dt.py`'s detour list, code kept in
`patch_softmute.s` for the record, matching this project's standing
convention of preserving ruled-out hooks with their own reasoning intact).

### A second hypothesis tried: `pre` only note-offs on the mute EDGE, never again for a later retrig — RULED OUT

Working theory: `pre` (hook 1) computes `D1 = newly-silenced (0->1 edge on
SHADOW)` and calls `F_NOTEOFF` only for tracks in `D1` — once, at the moment
a track is first muted. A track muted since frame 5 and retriggered at frame
441 creates no new edge (`SHADOW` is already 1), so `F_NOTEOFF` is never
called again for that retrig; the freshly retriggered voice's own envelope
might then ride through uncontested. Built as `--defsym ALWAYS_NOTEOFF=1`
(patch_softmute.s hook 1, cleanly gated, no effect unless the defsym is
passed): replaces the edge-only `D1` with the full currently-silenced set
`D2`, so `F_NOTEOFF` fires for every silenced track EVERY frame, not just
once.

**Readback-level A/B: also ruled out, cleanly.** `rb_muted` from frame 445
onward is **byte-for-byte identical** to the ungated baseline (`out/
botli2_muted.dump`) — zero effect on the blip whatsoever. Worse, it
introduced a NEW regression: frames 441-442 (well BEFORE the retrig, on the
original note that had already been muted since frame 5) got LOUDER, not
quieter (`src_muted` -8.2/-7.5 dB vs the baseline's own -27.9/-26.1 dB at
the same frames) — repeatedly calling `F_NOTEOFF` on an already-releasing
voice appears to disturb its decay rather than reinforce it, exactly the
risk flagged (untested) when this hook was written. **Confirmed bad on both
counts: no benefit, real regression.** Reverted (`build_mutemode_dt.py`'s
`patch_softmute` defsym back to plain `"DT_MODE=1"`, `ALWAYS_NOTEOFF` code
kept in `patch_softmute.s`, gated, inert by default).

### Where this leaves the investigation

**Six hypotheses tried and ruled out this session and last**: `mt_trig`
(dispatch never reached for this scenario), `mt_rebind` (correctly gated,
doesn't touch the real signal), `mt_pos`, `mt_ptr` (both fully inert),
`mt_ctr` (actively worse), `ALWAYS_NOTEOFF` (inert on the blip, regresses
the normal case). The blip is real, reproducible, and precisely bounded
(frames 445-448 of this exact scenario) — but nothing tried so far, on
either the ColdFire dispatch side (`FUN_4000f450`'s "reuse" path) or the
`pre` mixing-gate side, touches it.

**This suggests the actual mechanism may not be ColdFire-RAM-visible at
all** — consistent with Session 55's own earlier caution ("a measurement
can be structurally blind to the thing you're using it to rule out").
Every hook tried so far gates a ColdFire-side WRITE, on the theory that the
DSP reads that memory location to decide what to play. If the DSP instead
reacts to something else entirely — an unconditional host-port
block/command that fires on every trig regardless of content, an interrupt,
or DSP-program state that isn't seeded from any of the ColdFire addresses
examined — no ColdFire-side gate could ever fix it, no matter how narrowly
targeted.

**Concrete next step, not yet attempted**: use `ot_emu`'s DSP-side
instrumentation directly (`--dsp-pcwatch core:pc`, `--dsp-watch
core:space:addr`, `--dsp-map`/`--dsp-writes` for finding WHICH DSP words
change during the retrig transition) on the BOTLI retrig scenario, comparing
the DSP program's own behaviour frame-by-frame around 441-448 between a
muted and unmuted run — the same class of tool `refs/octabam` already used
to root-cause several of ITS OWN DSP-side defects (see its `CLAUDE.md`,
"traps that have already cost real work"). This requires first finding
WHERE in the DSP payload the per-track playback loop and its "read new
content" decision live (not yet located this session) — likely via
`--dsp-map`/`--dsp-writes`'s non-zero-word-change census on a muted vs
unmuted run, narrowing to the DSP addresses that only change around a real
trig, then disassembling that DSP code (`vendor/dsp56300/build/source/
disassemble/dsp56kDisassemble`, same tool `refs/octabam/tools/scratch/
peek_disasm.py` already wraps) rather than continuing to guess at ColdFire
write sites one at a time.

### Not yet done

- Locate the DSP-side playback/restart logic via `--dsp-map`/`--dsp-writes`
  census (muted vs unmuted BOTLI retrig run), not further ColdFire-side
  guesses.
- Disassemble whatever DSP region that census points to
  (`dsp56kDisassemble`, `peek_disasm.py`).
- Once a real DSP-side candidate is found: the fix likely has to live on
  the DSP side too (a DSP payload patch, a different discipline than every
  ColdFire hook built so far in this project) — worth flagging to the user
  before committing effort there, since it's new ground for this project.
- Current build state: `out/mainos_mutemode_dt.bin` is back to the
  known-safe baseline (`mt_trig` + `mt_rebind` only, byte-identical
  behaviour to before this whole "reuse path" investigation started) —
  confirmed via a clean rebuild. Safe to use as a reference point for
  future A/B tests.
- Still do not reflash hardware — no fix has been found yet, safe or
  otherwise.

### Exact prompt to start the next session with

```
Continue the MUTE MODE trig-suppression investigation in
~/Documents/octatrack-kyoti-fw. Read NOTES.md's "Session 56 continued"
section (the one titled "a methodology correction... Build restored to the
known-safe baseline", near the very end of the file) first. IMPORTANT
CORRECTION: when comparing `ot_emu --block-dump` captures, always use BOTH
signals `tools/cmp_botli_retrig.py` prints -- `src` (raw voice-source,
`o10_recloop.track_audio`) AND `rb` (readback/chain OUTPUT,
`o10_recloop.readback_audio`, what actually reaches the mix) -- `src` alone
is not sufficient and produced a misleading read earlier this same day.
Summary: SIX separate hypotheses for the mute-mode retrig blip (a real,
reproducible ~4-frame audible leak at frames 445-448 of the BOTLI T1-retrig
scenario, `rb_muted` within ~0.2 dB of `rb_ctrl`) have now been tried and
ruled out: mt_trig, mt_rebind (both from Session 55), mt_pos, mt_ptr, mt_ctr
(all three gate different unconditional writes inside FUN_4000f450's "reuse"
path, Session 56 -- mt_pos/mt_ptr are fully inert, mt_ctr makes the blip
LOUDER, not quieter), and ALWAYS_NOTEOFF (a `pre`-side hypothesis -- calling
F_NOTEOFF every frame instead of just on the mute edge -- inert on the blip
AND regresses the normal mute case). None of these ColdFire-RAM-side gates
touch the real mechanism. The concrete next step, not yet attempted: stop
guessing at ColdFire write sites and use `ot_emu`'s DSP-side instrumentation
directly (`--dsp-map`/`--dsp-writes` to find which DSP words actually change
during the muted-vs-unmuted retrig transition, then disassemble that DSP
region with `vendor/dsp56300/build/source/disassemble/dsp56kDisassemble` /
`refs/octabam/tools/scratch/peek_disasm.py`) -- the restart signal may not
be ColdFire-RAM-visible at all, which would explain why six different
ColdFire-side gates all failed to touch it. The build is currently at a
known-safe baseline (`out/mainos_mutemode_dt.bin`, just mt_trig + mt_rebind,
confirmed via a clean rebuild) -- nothing is broken, but nothing is fixed
either. Do not reflash hardware.
```

---

## Session 57 (2026-09-14, `wip`) — **THE LEAK IS FOUND AND FIXED.** It was never the voice: stock CLAMPS a silenced track's second level word to 6144 instead of zeroing it, and a retrig plays full-level straight into that open route.

User: "We HAVE to nail this." Nailed.

### First, two instrument corrections that unblocked everything

**(1) Neither `src` nor `rb` can see the mute at all.** Ran the retrig scenario in
stock OT mode (`GATE=0` + `MUTE_STATE` bit 8) and compared to an unmuted control:
**byte-identical in BOTH signals, every frame.** A genuinely hard-muted track is
indistinguishable from an unmuted one in `track_audio` (voice generator) and in
`readback_audio` (per-track chain output). Both capture points are UPSTREAM of where
the mute is applied. So every "it's inert / it's worse / it changed" reading taken
from those two signals in Session 56 was measuring something that structurally could
not show the fix. (Session 55's own `rb` blip IS real — it shows the track's
contribution — but it cannot show whether that contribution is then gated.)

**(2) The ESAI capture (`--audio-out`) is unusable here.** Captured real codec output
for control / stock-mute / OT+FX-mute. The **unmuted control contains zero non-zero
samples in the entire file** — the master/ESAI path is simply not exercised for this
project in the emulator. Any conclusion from it would have been backwards (the muted
run was the only one with audio). Ruled out as an instrument; do not use it for this
scenario without fixing the path first.

**The instrument that DOES work**: the per-track level words in the host-port feed —
core 1 block `0x80000110`, 64 bytes per track, `+2` and `+4` for track 0. This is the
firmware telling the DSP how loud each track is, and it is exactly where a mute lands.

### The mechanism, read out of stock code

`0x4000d0a4..0x4000d0dc`, a per-track loop that runs every frame, driven by **`REL_STATE`
(`0x8000184a`) — the very byte `pre` maintains** with `REL_STATE |= silenced`:

```
4000d0b6:  movew #6144,%d2           | the cap
4000d0ba:  mvzb 0x8000184a,%d0       | REL_STATE
4000d0c0:  asrl #1,%d0 / bccs        | per track: in release / silenced?
4000d0c4:  clrw  %a0@(2)             | YES -> dry level := 0     <- the mute you hear
4000d0c8:  clrb  %a0@(43)
4000d0cc:  cmpw  %a0@(4),%d2         | and the second word: if 6144 > it, leave it,
4000d0d0:  bgts  0x4000d0d6          | else CLAMP IT DOWN TO 6144 -- never to zero
4000d0d2:  movew %d2,%a0@(4)
```

A silenced track therefore keeps a **permanent −14.5 dB route to the mix**. That route
is the OT+FX feature — it is how the FX inserts go on ringing after the dry is cut.
Measured directly, T1 muted from frame 5: `+2` = 0 every frame (dry correctly cut),
`+4` = **exactly 6144 every frame**, from the mute right through the retrig and to the
end of the run.

**The bug:** a new trig plays the sample at FULL level straight into that still-open
6144 route. Nothing about the voice is wrong — stock never intended the grace to apply
to a note that started *after* the mute.

This also explains, precisely, why six previous hypotheses all failed: `mt_trig`,
`mt_rebind`, `mt_pos`, `mt_ptr`, `mt_ctr` and `ALWAYS_NOTEOFF` were all trying to stop
the VOICE, and every one of them was measured with instruments that sit upstream of
this word. They could not have shown a fix even if they had been right.

### The fix — `relcut`, hook 8 @ `0x4000d0c4`

For a track in a new **HARDCUT** set, zero `+4` instead of clamping it to 6144.
HARDCUT = "this track took a REAL trig while silenced", set by `mt_rebind`'s own
`mr_silence` path — the one site already proven (Session 55, `--watch-pc` register
dump) to fire exactly then and only then. `pre` masks HARDCUT down to the currently
silenced set every frame, so unmuting forgets it and the grace returns next time.

Net behaviour: **the FX-tail grace still belongs to the note that was sounding when the
mute engaged; a new trig gets no route out at all.**

### Validated (controlled A/B — same build, same card, relcut the only variable)

```
T1:                 dry (+2)   route (+4)
unmuted                32512        32512
muted, no fix              0   6144  ... every frame, forever
muted, +relcut             0   6144 until the retrig (f444), then 0 ... forever
```

- **Fix works**: the route closes at the retrig and stays closed.
- **Grace preserved**: 439 frames of ordinary muting before the retrig are untouched
  (6144 held), identical to no-fix.
- **Zero regression**: with nothing muted, relcut-on vs relcut-off is **byte-identical
  across every host-port block class** — provably no effect when no track is silenced.
- The emulator was confirmed **deterministic** first (same build twice = byte-identical),
  so these A/Bs mean what they say.

### Two real hazards found on the way (both worth keeping)

- **`0x80006c67` is NOT free patch RAM.** Stock writes a 16-bit `0xc8c` over `0x80006c66`
  from pc `0x4009882c` — so the byte next to SHADOW is the LOW HALF of a stock field.
  Using it for HARDCUT made even an UNMUTED run diverge. HARDCUT now lives at
  **`0x8000b000`**, chosen after censusing both writes AND reads over a full run (zero of
  either in `0x8000b000..0x8000b0ff`, unlike `0x80006a00/6b00/6c00/6d00/6e00/7000/7800`
  which are all busy). ⚠ "No traffic in THIS scenario" is not proof it is free under
  every feature (recorder, arranger, MIDI) — re-census before trusting it on hardware.
  **Note this also means SHADOW itself (`0x80006c66`) is occasionally clobbered by that
  same stock write — a pre-existing hazard in this project, not introduced here.**
- **Cross-build diffs are only meaningful with one variable changed.** A persistent
  "regression" chased for several rounds turned out to be the *baseline* capture
  (`botli5_ctrl`) having `mt_ptr` installed. Bisecting (relcut off, layout restored,
  dead code stripped) showed the diff was identical in every variant — i.e. not ours.
  Always A/B against the same build with the single hook toggled.

### Housekeeping

The ruled-out hooks (`mt_ctr`, `mt_pos`, `mt_ptr`, `fxcut`, `ALWAYS_NOTEOFF`) were
REMOVED from `patch_softmute.s` — they had grown the cave past the PERSONALIZE arrays,
forcing relocations that added noise to every comparison. A compact block in the file
lists each one, its address and its measured outcome, and points here. The cave is back
to its normal layout (patch_softmute 536 B, arrays at their original `0x400d7700/60/c0`);
`patch_mutemode` moved `0x400d7600` -> `0x400d7620`, the only layout change that remains.

New tool: `tools/cmp_botli_audio.py` (ESAI-level comparison; kept even though the ESAI
path is unexercised, since it is correct and will be useful once that is fixed).
`tools/cmp_botli_retrig.py` now prints both `src` and `rb` — but note correction (1)
above: neither can see the mute gate, so judge mute fixes by the level words instead.

### NOT yet done

- **Not flashed.** Standing rule respected — no hardware write this session.
- **The unmute-restores-grace path is reasoned, not measured**: `pre` masks HARDCUT with
  the silenced set every frame, so unmuting must clear it, but `ot_emu` only schedules
  ONE `--poke-at-frame`, so a mute→retrig→unmute→re-mute sequence could not be driven in
  a single run. Worth a small `ot_emu` extension (a second poke checkpoint) to close.
- **The SOLO path is not covered.** The release loop is shared, so `relcut` applies, but
  `pre`'s solo branch computes the silenced set differently and the solo case was not
  exercised here.
- **DT mode**: `pre` skips REL_STATE maintenance in DT, so this loop never processes the
  track and `relcut` never fires. DT's own retrig suppression is still unsolved — but it
  is now a much better-posed question: DT needs its own way into this same level word.

### Exact prompt to start the next session with

```
Continue MUTE MODE in ~/Documents/octatrack-kyoti-fw. Read NOTES.md "Session 57" (at the
end) first -- the retrig leak is FOUND and FIXED in the emulator, do not re-litigate it.
Root cause: the stock per-track release loop at 0x4000d0a4..0x4000d0dc (driven by
REL_STATE, the byte `pre` maintains) zeroes a silenced track's DRY level word (+2) but only
CLAMPS its second level word (+4) to 6144 -- a permanent -14.5 dB route to the mix, which
IS the OT+FX FX-tail-ring feature. A trig that arrives while the track is muted plays at
full level straight into that open route. Fix = hook 8 `relcut` @ 0x4000d0c4 in
patch_softmute.s: zero +4 instead of clamping, but ONLY for a track in the HARDCUT set
(0x8000b000, set by mt_rebind's mr_silence = "took a real trig while silenced", masked down
to the silenced set every frame by `pre`). Validated by controlled A/B (same build, same
card, relcut the only variable): route holds 6144 for 439 frames of ordinary muting then
goes to 0 at the retrig and stays there; and with nothing muted, relcut-on vs relcut-off is
byte-identical across every block class. IMPORTANT measurement rule: `src`/`rb` from
cmp_botli_retrig.py CANNOT see the mute at all (a stock hard-muted run is byte-identical to
unmuted in both) -- judge mute behaviour by the per-track LEVEL WORDS in the host-port feed
(core 1 block 0x80000110, 64 B per track, +2 dry / +4 route). The ESAI --audio-out path is
unexercised in this emulator (an unmuted control has zero non-zero samples) -- do not use
it. Next steps, in order: (1) flash and confirm on the MKI -- this is the first fix in this
whole thread with a measured mechanism behind it; (2) measure the unmute-restores-grace
path, which needs a SECOND --poke-at-frame checkpoint in ot_emu; (3) the SOLO branch and
(4) DT mode, which skips REL_STATE entirely so relcut never fires for it.
```

## Session 60 (2026-09-15, `wip`) — DIRECT JUMP flashed, did nothing: root cause found (stock, structural), v4 fix built + dynamically verified, NOT yet reflashed

**User report**: flashed `DIRECTJUMP_V3`. No effect whatsoever — no toast, no
toggle, the `[PTN]`+`[YES]` combo does literally nothing. Unit otherwise fine.

### Root cause — found by disassembling STOCK `section_3_MAIN_OS.bin`, not a patch

`[PTN]` press unconditionally runs `FUN_4005a044` → `jsr 0x4004346c` →
`pea 0x400bf0f2 ; jsr FUN_40031494`. This **pushes a small stock UI overlay
keymap layer** (26-byte records: trig 0x00-0x0f, NO=0x32, YES=0x31) onto a
layer list at `0x460d165c` (push = append at the tail; the list is walked
head→tail, so newest-pushed is processed LAST). That push triggers a full
rebuild (`FUN_40031494` → `braw FUN_4003125c`) of a flat, 24-byte-stride
runtime dispatch table at `0x46c7d8de` (`slot(code) = 0x46c7d8de + code*24`):
each active layer's press pointer for a key **unconditionally overwrites**
that key's slot as the layer is processed, so the *last*-processed (= most
recently pushed = topmost) layer's value always wins for as long as it's on
the stack.

The PTN-held overlay's own YES record (`0x400bf0f2` → entries `0x400bef04`,
record for code `0x31` @ `0x400bf0be`) has **press = NULL**. So the instant
`[PTN]` goes down, the runtime dispatch slot for `[YES]`
(`0x46c7dd76 = 0x46c7d8de + 0x31*24`) gets overwritten with `0` and **stays
0 until `[PTN]` is released** (the layer is popped by `0x40043418`).

**v1/v2/v3 all detour the stock `[YES]` *handler*, `0x4005e4c8`.** That
handler is only ever reached by whatever consults the flat dispatch table —
and while `[PTN]` is held, that table's `[YES]` slot is NULL, so the real
runtime code the detour lives inside is **never entered at all**. This is
entirely stock, structural firmware behaviour; none of DIRECT JUMP's own
sequencer hooks or persistence code are at fault, and it has nothing to do
with `DJ_V3`'s toast primitive specifically — v1 and v2 are equally dead.

Confirmed the base (non-overlay) keymap really does register YES → `0x4005e4c8`
at that same table slot: boot pushes the real base-keymap selector struct
(`0x400c090a`/`0x400c091e`, picked by `0x46c8d18c`) through the identical
`FUN_40031494` push+rebuild path (`0x40061bc4-0x40061bda`) — so outside a
`[PTN]` hold, `0x46c7dd76` correctly holds `0x4005e4c8`, matching that the
combo's *toggle*, if reachable, would be a legitimate override of stock YES.

### Fix — `patch_directjump.s` `--defsym DJ_KEYMAP=1`, `build_directjump_v4.py`

No detour on `0x4005e4c8` at all (`djt_stock`'s tail becomes a plain `rts`
under `DJ_KEYMAP`, since stock does nothing with `[YES]` in this layer
anyway). Instead the **build** writes `dj_toggle`'s address directly into the
overlay layer's own `[YES]` record press field (`0x400bf0f2+0xe` = record
`0x400bf0be`, offset `+2`; stock value asserted NULL first) — so the *same*
stock rebuild that used to zero the runtime slot now points it at
`dj_toggle`. Everything else (`DJ_MODE`/shadow/re-checksum, the `DJ_V3` toast,
`dj_a`/`dj_b`/`dj_c`) is byte-for-byte v3's. Build asserts v4's touched-byte
set = v3's cave + exactly that one 4-byte field (no stray edits) and that
`0x4005e4c8` itself is untouched. 501 B changed vs stock (v3 was 516 — the
detour + its `jmp` bytes are simply gone).

### Verification — real stock code, not just the hand-built dj_toggle stub

`tools/emu_directjump_v4.py` runs the **actual, unmodified firmware's own**
`FUN_4005a044` ([PTN] press) and `FUN_40031494`/`FUN_4003125c` (layer push +
table rebuild) under Unicorn against the finished images — first pushing the
real base-keymap selector struct (the same one boot uses) so the layer
ordering this depends on is the genuine one, not fabricated:

  * **v3 image**: after the push, the `[YES]` runtime dispatch slot reads
    `0x4005e4c8` (base registered correctly); after the real `[PTN]` press,
    the same slot reads **`0`** — reproducing the exact HW failure.
  * **v4 image**: after the same sequence, the slot reads `dj_toggle`'s
    address. The harness then **`jsr`s that live slot directly** (the same
    call the real per-key ISR would make) and confirms it runs `dj_toggle`
    for real: the re-checksum call fires, the `NOTIFY` toast call fires with
    the right args, and `DJ_MODE` flips 0→1 — end to end, through the real
    dispatch table, not a synthetic call to `dj_toggle`'s entry point.

(The `[PTN]`-press call's own stock tail trails off into kernel code past
`0x40027de4` that Unicorn can't run standalone — same class of limit already
documented for `FUN_400a1eea` — but that's after the layer push/rebuild this
test cares about has already completed, so it's an expected trailing
exception, not a failure.) `ALL GOOD`. `dj_a`/`dj_b`/`dj_c` re-confirmed
byte-identical to v1 (`emu_directjump_v3.py`, still green after rebuilding
each variant in its own build→emu pair — the shared `out/patch_directjump.*`
filename across all four build scripts means whichever was built *last*
is what an emu script not run immediately after its own build will see;
not a regression, just the existing project convention).

### ⚠️ Likely the same root cause hits RELOAD2 — NOT yet fixed, flagged only

`patch_reload2.s`'s `rl_yes` (the `[PTN]`-hold picker's `[YES]` confirm) also
detours `0x4005e4c8`, gated the same way on `PTN_MODE`. By this exact
mechanism its `[PTN]`+`[YES]` flow is very likely equally dead on hardware —
it just hasn't been flash-tested yet (queued behind DIRECTJUMP in the flash
order). `build_merged.py`'s whole `[YES]`-trampoline design (Session 45: DJ's
`dj_toggle` chained from RELOAD2's `rl_yes`, both hanging off the one detour
at `0x4005e4c8`) sits on the same dead hook. Worth the identical keymap-slot
treatment before RELOAD2 is ever flashed standalone or the merged build is
attempted — not done here, out of scope for "why doesn't DIRECT JUMP do
anything."

### Status

`out/OCTATRACK_OS1.40C_DIRECTJUMP_V4.syx` / `OCTATRACK_DIRECTJUMP_V4.bin`
built, emu-verified both ways above. **NOT yet reflashed.** `build_merged.py`
still wires `DJ_V3` (dead combo) into the merge — needs bumping to the
`DJ_KEYMAP` mechanism (and RELOAD2's own fix) before the merged build is
touched again; not done this session.
