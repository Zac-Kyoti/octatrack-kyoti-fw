| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
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
|
| ---- 2026-11-19: the [BANK] grid lights a bank whose patterns hold trigless locks ----
| The author's spec: under [BANK], a bank holding a pattern with trigless locks that
| carry a locked parameter lights (a trigless lock with nothing locked stays off, as
| under [PTN]); and no stall or slowdown while [BANK] is held.  So the [BANK] path
| (return address 0x4000fd8c) runs stock's test first, unchanged, and only when that
| says empty reads the trigless-LOCK masks stock skips -- TRAC+0x10 (audio, hardware
| trace in ../erase-empty-trigless-locks/patch_triglock.s) and MTRA+0x10 (MIDI: the
| same [FUNC]+trig cycle partner of +0x08 at 0x40040f90 as audio's at 0x40041336) --
| and for each set bit (step) checks only THAT step's 32-byte lock row (#1[step],
| TRAC+0x59+32*step / MTRA+0x30+32*step, one byte per parameter, 0xFF = not locked):
| any byte != 0xFF -> content.  An empty trigless lock (mask bit, row all 0xFF) and a
| stale MIDI +0x10 bit (stock's MIDI clear FUN_40038668 never clears +0x10, it does
| clear the row) stay off by construction; lock bytes WITHOUT a mask bit stay off
| under [BANK] (lit under [PTN], whose full-array scan is unchanged).
| Cost bound: at most PL_BUDGET rows are checked per call (22 instructions a row), so a
| pattern of nothing but empty trigless locks costs ~390 cave instructions instead of the
| 32 KB scan S119 removed; past the budget the pattern reads as stock reads it (empty).
| A pattern without trigless-lock bits costs one walk over the 16 masks: 104 instructions.
| Measured (tools/led_bank_stall.py, ot_emu, transport running, 0.6 s with [BANK] held):
| OT DEMO 41.16M -> 41.35M ColdFire instructions (idle 39.80M); all 256 patterns empty
| 39.57M -> 39.69M; every pattern 1,024 empty trigless locks 41.20M -> 42.13M (holding
| [PTN] on that project costs 42.42M with the FINAL already).  Session 119's stall: 116.8M.
| The [PTN] path is the Session 119 code (12,390 instructions per empty pattern).

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
    .equ  MID_BLK,      0x48d0            | MIDI MTRA block in the pattern (stock's a1 - 8)
    .equ  LMASK,        0x10              | trigless-lock step mask, audio and MIDI block alike
    .equ  AUD_ROW0,     AUD_PLOCK-LMASK   | lock row 0 relative to the mask: audio 0x49
    .equ  MID_ROW0,     MID_PLOCK-MID_BLK-LMASK | MIDI 0x20
    .equ  PL_BUDGET,    16                | lock rows checked per [BANK]-grid call, at most

| ff1 Dn (ISA_C encoding 0x04c0|n): Dn = leading-zero count.  Stock reaches it on every
| boot (0x4004098e, task creation; 0x40040ffa / 0x40041340 in the trig-type toggle); the
| assembler refuses it for -mcpu=5407, hence the .short.
    .macro ff1_d6
    .short 0x04c6
    .endm

    .text
    .global cave
cave:
    move.l  8(%sp),-(%sp)                 | bank
    move.l  8(%sp),-(%sp)                 | pattern
    bsr.w   .Lstock                       | stock's trig-mask test first -- cheap
    addq.l  #8,%sp
    tst.l   %d0
    beq.s   0f
    rts                                   | trigs -> content (d0 = 1)
0:  lea     -24(%sp),%sp
    movem.l %d2-%d4/%d6/%a2-%a3,(%sp)     | the caller's
    move.l  28(%sp),%d3                   | pattern (24(sp) = the return address)
    move.l  #PAT_STRIDE,%d2
    muls.l  %d2,%d3
    move.l  32(%sp),%d1                   | bank
    move.l  #BANK_STRIDE,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d3                       | d3 = this pattern's blob offset
    move.l  24(%sp),%d0
    cmpi.l  #BANKGRID_RET,%d0
    beq.s   .Lbank                        | the [BANK] grid: the trigless-lock rows only

| [PTN] grid / chain view: any lock byte anywhere (unchanged since Session 119)
    movea.l %d3,%a0                       | 8 audio arrays: BLOB + d3 + 0x59, stride 0x91a
    adda.l  #BLOB+AUD_PLOCK,%a0
    move.l  #AUD_STRIDE-PLOCK_LEN,%d1
    bsr.s   .Lscan8
    bne.s   .Ldone
    movea.l %d3,%a0                       | 8 MIDI arrays: BLOB + d3 + 0x4900, stride 0x8b0
    adda.l  #BLOB+MID_PLOCK,%a0
    move.l  #MID_STRIDE-PLOCK_LEN,%d1
    bsr.s   .Lscan8
    bra.s   .Ldone

| [BANK] grid (bank_has_content: all 256 patterns on every LED refresh while [BANK] is held)
| One walk over the 8 audio + 8 MIDI tracks in pairs: the four mask words ORed (8 instructions a
| pair, the usual answer being "no trigless lock"), and only a pair with a bit set has its rows read.
.Lbank:
    moveq   #PL_BUDGET,%d4
    movea.l %d3,%a0
    adda.l  #BLOB+LMASK,%a0               | a0 = audio track t's trigless-lock mask (TRAC+0x10)
    lea     MID_BLK(%a0),%a1              | a1 = MIDI track t's (MTRA+0x10)
    moveq   #8,%d2
1:  move.l  (%a0),%d0
    or.l    4(%a0),%d0
    or.l    (%a1),%d0
    or.l    4(%a1),%d0
    bne.s   3f
2:  lea     AUD_STRIDE(%a0),%a0
    lea     MID_STRIDE(%a1),%a1
    subq.l  #1,%d2
    bne.s   1b
    bra.s   .Ldone                        | Z set: no locked trigless lock
| the mask is 64-bit BE, bit n = step n: +0 holds steps 32..63, +4 steps 0..31
3:  lea     AUD_ROW0+32*32(%a0),%a2
    move.l  (%a0),%d0
    bsr.s   .Lrows
    bne.s   .Ldone
    lea     AUD_ROW0(%a0),%a2
    move.l  4(%a0),%d0
    bsr.s   .Lrows
    bne.s   .Ldone
    lea     MID_ROW0+32*32(%a1),%a2
    move.l  (%a1),%d0
    bsr.s   .Lrows
    bne.s   .Ldone
    lea     MID_ROW0(%a1),%a2
    move.l  4(%a1),%d0
    bsr.s   .Lrows
    beq.s   2b                            | nothing locked on this pair: the next one
.Ldone:                                   | Z clear: content; Z set: empty
    sne     %d0
    andi.l  #1,%d0                        | 1 / 0
    movem.l (%sp),%d2-%d4/%d6/%a2-%a3
    lea     24(%sp),%sp
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

| d0 = a mask word, a2 = the lock row of its bit 0.  Each set bit b: the 32 bytes at
| a2 + 32*b; their AND is 0xFFFFFFFF exactly when nothing is locked on that step.
| Z clear: locked; Z set: none.  Uses d0 d1 d6 a3 (d3 holds the pattern's offset), and d4 = the rows left in the budget:
| the row that spends it leaves through .Lspent, straight to the "empty" answer.
.Lrows:
    tst.l   %d0
    beq.s   9f
1:  move.l  %d0,%d6
    ff1_d6                                | d6 = 31 - b
    not.l   %d6                           | low 5 bits = b
    bclr    %d6,%d0                       | (bit number mod 32): this step is done
    moveq   #31,%d1
    and.l   %d1,%d6                       | b
    lsl.l   #5,%d6                        | 32*b
    lea     0(%a2,%d6.l),%a3
    move.l  (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    and.l   (%a3)+,%d1
    not.l   %d1
    bne.s   9f                            | a parameter is locked on this step: Z clear
    subq.l  #1,%d4
    beq.s   .Lspent                       | budget spent (Z set)
    tst.l   %d0
    bne.s   1b
9:  rts
.Lspent:                                  | called only from .Lbank: drop the return
    addq.l  #4,%sp                        | address (addq to sp keeps Z set)
    bra.s   .Ldone                        | -> 0, stock's answer

| The stock predicate, entered as the detour found it: replay the displaced prologue
| (`move.l d2,-(sp) ; move.l 8(sp),d0`) and continue at CONT; its own epilogue
| (0x4009a4f8: `move.l (sp)+,d2 ; rts`) returns to the bsr above.
.Lstock:
    move.l  %d2,-(%sp)
    move.l  8(%sp),%d0
    jmp     CONT
