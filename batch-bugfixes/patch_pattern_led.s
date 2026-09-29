| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_pattern_led -- stock bug: a pattern whose only content is parameter locks
| (no trigs anywhere) reads as EMPTY -> its grid LED stays unlit under [PTN], the
| slot looks unused.  Reported for MIDI-track p-locks; the same code path also
| mislabels a pure audio trigless-lock pattern.
|
| Root cause: FUN_4009a464(pattern, bank) is the "does this pattern have content"
| predicate that gates the pattern-grid LED (callers 0x4007b228 PTN page /
| 0x4003552c chain view: `has_content(); tst.l d0; bne` -> set LED bit 0x400131a0
| else clear 0x400131c8; also 0x4000fd78 "does this bank have content").  It walks
| 8 track slots and ORs a fixed set of longwords:
|   audio TRAC (stride 0x91a):  block +0x00..0x0f and +0x18..0x37  (trig masks)
|   MIDI  MTRA (stride 0x8b0):  block +0x00..0x0f                   (trig masks)
| It never looks at either side's p-lock array, so a trigless-lock-only pattern
| ORs to zero and the function returns 0 = empty.
|
| Confirmed in emu_rtos (tools/emu_pattern_led.py): a MIDI-track p-lock written
| into a loaded pattern's array (blob + pat*0x8ed8 + 0x4900 + trk*0x8b0) leaves
| FUN_4009a464 returning 0; the fix makes it return 1.
|
| RAM layout (bank serialiser ~0x4008a740 + initialiser FUN_4009abdc's two fill
| loops 0x4009ac30 audio / 0x4009ad56 MIDI + a live emu_rtos load all agree):
|   audio p-lock array  blob + bank*0x9b340 + pat*0x8ed8 + trk*0x91a + 0x59  (0x800 B)
|   MIDI  p-lock array  blob + bank*0x9b340 + pat*0x8ed8 + 0x4900 + trk*0x8b0 (0x800 B)
|   0xFF = "this parameter not locked on this step" (FUN_4009abdc byte-fills 0xFF;
|   the deserialiser loads 0xFF for an empty track).
|
| Fix: detour FUN_4009a464's 6-byte prologue to a cave.  The cave replays the
| prologue's `move.l d2,-(sp)`, then scans the 16 p-lock arrays (8 audio + 8 MIDI)
| for a longword != 0xFFFFFFFF.  Found -> return 1.  None -> `jmp 0x4009a46a` = the
| rest of the stock function (its trig scan + its own epilogue) runs unchanged, so
| every trig-bearing pattern still returns 1 exactly as before, and a genuinely
| empty pattern (all 0xFF, no trig) still returns 0.
|
| Detour (6 B @ 0x4009a464):  jmp <cave>   (replaces `move.l d2,-(sp) ; move.l 8(sp),d0`)
|
| Assemble like the other stubs:  m68k-elf-as -mcpu=5407 ; ld -Ttext=<cave> ; objcopy -O binary

    .equ  BLOB,         0x400e21e0        | pattern-blob base, bank 0 (hardcoded in the stock fn)
    .equ  PAT_STRIDE,   0x8ed8
    .equ  BANK_STRIDE,  0x9b340
    .equ  AUD_STRIDE,   0x91a
    .equ  MID_STRIDE,   0x8b0
    .equ  AUD_PLOCK,    0x59              | audio p-lock array, offset in the TRAC block
    .equ  MID_PLOCK,    0x4900            | MIDI  p-lock array, offset in the pattern block
    .equ  PLOCK_LEN,    0x800             | 64 steps * 32 bytes
    .equ  CONT,         0x4009a46a        | FUN_4009a464 + 6 : the instruction after the detour

    .text
    .global cave
cave:
    move.l  %d2,-(%sp)                    | replay the stock prologue's push (so CONT's stack is right)
    move.l  8(%sp),%d0                    | pattern
    move.l  #PAT_STRIDE,%d2
    muls.l  %d2,%d0
    move.l  12(%sp),%d1                   | bank
    move.l  #BANK_STRIDE,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d0
    move.l  %d0,%d1                       | d1 = this pattern's blob offset (kept across both scans)

    | ---- 8 audio p-lock arrays: base = BLOB + d1 + 0x59, stride 0x91a ----
    move.l  %d1,%d0
    add.l   #BLOB+AUD_PLOCK,%d0
    movea.l %d0,%a0
    moveq   #8,%d2                        | tracks left
.LaTrk:
    movea.l %a0,%a1                       | a1 = scan cursor for this track
.LaScan:
    move.l  (%a1)+,%d0
    addq.l  #1,%d0                        | 0xFFFFFFFF -> 0 (all unlocked); else nonzero
    bne     .Lhit
    move.l  %a1,%d0
    sub.l   %a0,%d0
    cmp.l   #PLOCK_LEN,%d0
    bcs     .LaScan
    lea     AUD_STRIDE(%a0),%a0
    subq.l  #1,%d2
    bne     .LaTrk

    | ---- 8 MIDI p-lock arrays: base = BLOB + d1 + 0x4900, stride 0x8b0 ----
    move.l  %d1,%d0
    add.l   #BLOB+MID_PLOCK,%d0
    movea.l %d0,%a0
    moveq   #8,%d2
.LmTrk:
    movea.l %a0,%a1
.LmScan:
    move.l  (%a1)+,%d0
    addq.l  #1,%d0
    bne     .Lhit
    move.l  %a1,%d0
    sub.l   %a0,%d0
    cmp.l   #PLOCK_LEN,%d0
    bcs     .LmScan
    lea     MID_STRIDE(%a0),%a0
    subq.l  #1,%d2
    bne     .LmTrk

    | ---- no p-lock anywhere: let the stock function body run (trig scan + epilogue) ----
    | CONT (0x4009a46a) expects d0 = arg0 (the detour swallowed both `move.l d2,-(sp)`
    | and `move.l 8(sp),d0`); we replayed the push, now replay the arg load.
    move.l  8(%sp),%d0
    jmp     CONT

.Lhit:
    move.l  (%sp)+,%d2                    | undo our prologue push
    moveq   #1,%d0
    rts
