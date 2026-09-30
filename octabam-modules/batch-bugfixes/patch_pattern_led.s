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
| Fix: detour FUN_4009a464's 6-byte prologue to a cave.  The cave runs the stock
| predicate first (its cheap trig-mask OR) and, only when that says empty, scans the
| 16 p-lock arrays (8 audio + 8 MIDI) for a longword != 0xFFFFFFFF.  Result = stock
| OR "some p-lock" -- the same answer the first version gave, found cheaper.
|
| Detour (6 B @ 0x4009a464):  jmp <cave>   (replaces `move.l d2,-(sp) ; move.l 8(sp),d0`)
|
| ---- Session 119: the [BANK] grid is left to stock (it starved the CPU) ----
| Hardware (KYOTI V1.0, RELOAD's [BANK]+[TRACK]): toast ~1 s late, trig grid dark,
| controls dead, the wait growing ~2x with how long the chord is held; key mashing
| glitched audio and timing.  Measured in ot_emu (the step list's new `key` verb):
| while [BANK] is held the bank grid calls bank_has_content 0x4000fd78 -> FUN_4009a464
| for all 16 patterns of all 16 banks every LED refresh (~130 bank checks/s).  An
| empty pattern cost the old cave the full 32 KB scan at 7 instructions per long
| (~57k), so in 0.6 s of [BANK] held the cave ran 71.4M instructions -- the whole
| idle workload is 44.5M.  [PTN] held (16 calls per refresh) cost 4.3M: noticeable,
| not fatal, which is why [PTN]+[TRACK] never showed it.  Three changes:
|   * a call from bank_has_content (return address 0x4000fd8c) gets stock's predicate
|     only -- a bank whose sole content is p-locks reads empty under [BANK], exactly
|     as stock does; the [PTN] grid and the chain view keep the fix;
|   * the stock trig-mask test runs FIRST, so a pattern with trigs never scans;
|   * the scan ANDs 8 longs per step (12 instructions per 32 B instead of 56).

    .equ  BLOB,         0x400e21e0        | pattern-blob base, bank 0 (hardcoded in the stock fn)
    .equ  PAT_STRIDE,   0x8ed8
    .equ  BANK_STRIDE,  0x9b340
    .equ  AUD_STRIDE,   0x91a
    .equ  MID_STRIDE,   0x8b0
    .equ  AUD_PLOCK,    0x59              | audio p-lock array, offset in the TRAC block
    .equ  MID_PLOCK,    0x4900            | MIDI  p-lock array, offset in the pattern block
    .equ  PLOCK_LEN,    0x800             | 64 steps * 32 bytes
    .equ  CONT,         0x4009a46a        | FUN_4009a464 + 6 : the instruction after the detour

    .equ  BANKGRID_RET, 0x4000fd8c        | bank_has_content 0x4000fd78's return site

    .text
    .global cave
cave:
    move.l  (%sp),%d0
    cmpi.l  #BANKGRID_RET,%d0
    beq.w   .Lstock                       | the [BANK] grid: stock's predicate, as-is
    move.l  8(%sp),-(%sp)                 | bank
    move.l  8(%sp),-(%sp)                 | pattern
    bsr.w   .Lstock                       | stock's trig-mask test first -- cheap
    addq.l  #8,%sp
    tst.l   %d0
    bne.s   .Lret                         | trigs -> content (d0 = 1)
    move.l  %d2,-(%sp)                    | d2/d3 are the caller's
    move.l  %d3,-(%sp)
    move.l  12(%sp),%d3                   | pattern
    move.l  #PAT_STRIDE,%d2
    muls.l  %d2,%d3
    move.l  16(%sp),%d1                   | bank
    move.l  #BANK_STRIDE,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d3                       | d3 = this pattern's blob offset
    movea.l %d3,%a0                       | 8 audio arrays: BLOB + d3 + 0x59, stride 0x91a
    adda.l  #BLOB+AUD_PLOCK,%a0
    move.l  #AUD_STRIDE-PLOCK_LEN,%d1
    bsr.s   .Lscan8
    bne.s   .Lfound
    movea.l %d3,%a0                       | 8 MIDI arrays: BLOB + d3 + 0x4900, stride 0x8b0
    adda.l  #BLOB+MID_PLOCK,%a0
    move.l  #MID_STRIDE-PLOCK_LEN,%d1
    bsr.s   .Lscan8
.Lfound:                                  | Z set: nothing, and d0 is then 0 (the
    beq.s   4f                            | last NOT of 0xFFFFFFFF); Z clear: a p-lock
    moveq   #1,%d0
4:
    move.l  (%sp)+,%d3
    move.l  (%sp)+,%d2
.Lret:
    rts

| a0 = the first of 8 p-lock arrays, d1 = the gap from one array's end to the next's
| start.  Returns Z clear on the first longword != 0xFFFFFFFF, Z set if none.  An AND
| of 8 longs is 0xFFFFFFFF exactly when all 8 are.  Uses d0, d2, a0, a1.
.Lscan8:
    moveq   #8,%d2
1:  lea     PLOCK_LEN(%a0),%a1            | this array's end
2:  move.l  (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    and.l   (%a0)+,%d0
    not.l   %d0
    bne.s   3f                            | found: Z clear
    cmpa.l  %a1,%a0
    bcs.s   2b
    adda.l  %d1,%a0
    subq.l  #1,%d2
    bne.s   1b                            | falls out with Z set: nothing
3:  rts

| The stock predicate, entered as the detour found it: replay the displaced prologue
| (`move.l d2,-(sp) ; move.l 8(sp),d0`) and continue at CONT; its own epilogue
| (0x4009a4f8: `move.l (sp)+,d2 ; rts`) returns to whoever called -- the original
| caller from the [BANK]-grid branch, or the bsr above.
.Lstock:
    move.l  %d2,-(%sp)
    move.l  8(%sp),%d0
    jmp     CONT
