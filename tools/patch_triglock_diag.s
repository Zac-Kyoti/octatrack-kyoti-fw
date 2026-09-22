| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_triglock_diag v2 -- find out what the LIVE [NO]+knob gesture ACTUALLY calls, by
| measuring it on the unit instead of inferring it offline.
|
| WHERE v1 GOT TO. v1 instrumented the cave on FUN_40042158's tail. ARTLTEST6 (gesture
| performed on that build, then saved) came back with the log area completely untouched --
| and the RAM<->disk mapping for the log was verified independently afterwards (RAM
| TRAC(pat,trk) == disk trac_off+9, whole 0x91a block identical for every pattern/track
| including the (15,7) the log lives in), so the readout is trustworthy. The cave never
| ran ONCE -- not even for the two p-lock WRITES that created the trigless lock. So
| FUN_40042158 is not on the LIVE-REC editing path at all; it is reached some other way
| (grid rec: hold a trig and turn a knob), which is exactly why calling it directly in the
| emulator behaved perfectly and meant nothing.
|
| v1's OTHER FLAW, fixed here: an all-0xFF log is indistinguishable from "the user flashed
| the wrong image". v2 writes a beacon from a site that runs constantly, so a blank log now
| means exactly one thing -- wrong firmware or a broken channel -- and never gets confused
| with "the instrumented code did not run".
|
| WHAT v2 MEASURES. One detour on the sys task's message dispatcher, at the three
| instructions that decode the opcode (0x40061ce2: `moveb %a2@,%d0 ; subql #1,%d0 ;
| mvzb %d0,%d0`, exactly 6 bytes). Every UI message in the system passes through it, so a
| per-opcode histogram says precisely which messages the gesture produces. Combined with
| the routing table already decoded from 0x40061cfa (78 entries, index = msg[0]-1):
|
|     opcode 64 -> 0x40062496 -> FUN_40054cd8 then FUN_40042158   (writes `#1`)
|     opcode 65 -> 0x400625b8 -> FUN_40042d1c
|     opcode 66 -> 0x40062640 -> FUN_40042d1c
|     opcode 70 -> 0x400629ee -> FUN_4004f124 (armed) / FUN_40041bc4 (LIVE)
|     opcode 74 -> 0x40062a56 -> FUN_4004ef54 (armed) / FUN_40041784 (LIVE)
|
| ...the histogram names the handler without guessing. That is the whole point: no
| hypothesis about the gesture is required to read the result.
|
| v3 ADDS THE DECISIVE PART. ARTLTEST7 proved none of opcodes 64/65/66/70/74 occur during
| the gesture -- the entire 0x40062xxx p-lock cluster this thread has chased since Session
| 26 is uninvolved. The opcodes that DO occur are 1, 5, 8, 9, 17, 18, 20, 21, 24, 43, 50,
| 51. Rather than decompile all twelve and guess again, v3 watches the bytes that must
| change -- `#1[step 6][param 0..3]` and TRAC+0x10's step-0..7 byte, for bank 1 / pattern 1
| / track 1 -- and when one changes it records WHICH OPCODE'S HANDLER changed it (the
| previous message dispatched). That names the handler by observation.
|
| The FUN_40042158 cave is kept as-is, so if it does fire we still learn why it rejected.
|
| THE CHANNEL. The firmware has no debug output, but a project save serialises the whole
| bank blob to the card, so RAM inside the blob is a tape the user can export back. This
| uses `#1` (stored p-lock values) of bank 1 / pattern 16 / track 8 -- RAM 0x4016c097,
| disk 0x8a042 in bank01.work/.strd. Those are p-lock VALUE bytes for steps with no trig
| of any kind, so nothing reads or plays them.
| Cosmetic, expected: pattern 16 may read as "not empty" on the pattern grid (the Session
| 48 emptiness test) until the log is cleared.
|
| LOG LAYOUT (bytes, from LOG)
|     +0x00..04  beacon "KYOTI" -- present iff this firmware is running at all
|     +0x05      build id (2)
|     +0x06..07  reserved
|     +0x08      FUN_40042158 cave entries   (0xFF = never; saturates at 0xFE)
|     +0x09      last reason code
|     +0x0a..11  snapshot: track, value, bank, pattern, step, a0 low, pre-bitmap, trackbit
|     +0x12..19  reason histogram, index = reason code
|     +0x20..24  shadow of the watched bytes
|     +0x25      previous message's opcode
|     +0x26      number of observed changes
|     +0x28..47  ring of the last 8 changes: {opcode that caused it, which, old, new}
|     +0x80..CD  OPCODE HISTOGRAM: count for msg[0] = 1..78 at +0x80 + (msg[0]-1)
|     +0x100..14D CULPRIT HISTOGRAM: which opcode's handler changed a watched byte
|
| REASON CODES (unchanged): 1 not audio bitmap / 2 no stored p-lock here / 3 value != 0xFF
| / 4 #1[step] not all-0xFF / 5 a real trig owns the step / 6 trigless bit not set /
| 7 DELETED.
|
| Counters use 0xFF = "never written" (a fresh project has 0xFF there), mapping 0xFF -> 1
| on first use and saturating at 0xFE, so "never" and "a lot" can never be confused.

    .equ  BLOB_ABS,      0x400e21e0
    .equ  PAT_STRIDE,    0x8ed8
    .equ  BANK_STRIDE,   0x9b340
    .equ  TRK_STRIDE,    0x91a
    .equ  PLOCK_OFF,     0x59
    .equ  TYPE_FLAG_OFF, 0x10
    .equ  STORED_BITMAP, 0x46c7d48c
    .equ  MIRROR_BASE,   0x1001615e
    .equ  CUR_BANK,      0x80000002
    .equ  CUR_PATTERN,   0x80000004
    .equ  LOG,           0x4016c097    | bank 1, pattern 16, track 8, #1 step 1
    .equ  OPHIST,        0x80          | offset of the opcode histogram within the log
    .equ  BUILD_ID,      3
    .equ  WATCH_PLOCK,   0x400e22f9    | #1[step 6][param 0], bank 1 / pattern 1 / track 1
    .equ  WATCH_FLAG,    0x400e21f7    | TRAC+0x10's byte covering steps 0-7, same track
    .equ  SHADOW,        0x20          | 5 watched bytes
    .equ  PREVOP,        0x25
    .equ  NCHG,          0x26
    .equ  CHGRING,       0x28          | 8 records x 4 bytes {prev_opcode, which, old, new}
    .equ  CULPRIT,       0x100         | histogram by the opcode that caused a change

    .text

| ============================================================================
| caveA -- on the sys message dispatcher (detour 0x40061ce2, 6 B)
| entry: a2 = message pointer, msg[0] = opcode 1..78
| exit : must leave d0 = (opcode - 1), zero-extended, exactly as the displaced code did
| ============================================================================
    .global caveA
caveA:
    lea     %sp@(-40),%sp
    moveml  %d0-%d7/%a0-%a1,%sp@      | a2 is the message pointer -- never touched

    movea.l #LOG,%a1
    | ---- beacon: proves this firmware is the one running ----
    moveq   #0x4b,%d0
    move.b  %d0,%a1@(0)               | 'K'
    moveq   #0x59,%d0
    move.b  %d0,%a1@(1)               | 'Y'
    moveq   #0x4f,%d0
    move.b  %d0,%a1@(2)               | 'O'
    moveq   #0x54,%d0
    move.b  %d0,%a1@(3)               | 'T'
    moveq   #0x49,%d0
    move.b  %d0,%a1@(4)               | 'I'
    moveq   #BUILD_ID,%d0
    move.b  %d0,%a1@(5)

    | ---- opcode histogram ----
    clr.l   %d0
    move.b  %a2@,%d0                  | msg[0]
    subq.l  #1,%d0
    bmi     .Awatch                   | opcode 0 -- not a table index
    move.l  %d0,%d1
    sub.l   #78,%d1
    bpl     .Awatch                   | out of table range
    lea     %a1@(OPHIST),%a0
    adda.l  %d0,%a0
    bsr     .Lbump

    | ---- change detection ----
    | Compare the watched bytes against a shadow kept in the log. A difference means the
    | PREVIOUS message's handler changed them -- that handler is the thing this whole
    | thread has been unable to name. Record it, both as an ordered ring and as a
    | histogram, so a noisy session still yields an unambiguous culprit.
.Awatch:
    movea.l #WATCH_PLOCK,%a0
    moveq   #0,%d1
    bsr     .Lchk
    movea.l #WATCH_PLOCK+1,%a0
    moveq   #1,%d1
    bsr     .Lchk
    movea.l #WATCH_PLOCK+2,%a0
    moveq   #2,%d1
    bsr     .Lchk
    movea.l #WATCH_PLOCK+3,%a0
    moveq   #3,%d1
    bsr     .Lchk
    movea.l #WATCH_FLAG,%a0
    moveq   #4,%d1
    bsr     .Lchk

    | remember this message's opcode as "previous" for the next pass
    clr.l   %d0
    move.b  %a2@,%d0
    move.b  %d0,%a1@(PREVOP)

.Aout:
    moveml  %sp@,%d0-%d7/%a0-%a1
    lea     %sp@(40),%sp
    .short  0x1012, 0x5380, 0x7180    | moveb %a2@,%d0 ; subql #1,%d0 ; mvzb %d0,%d0
    rts

| ----------------------------------------------------------------------------
| .Lchk -- a0 = watched address, d1 = shadow index 0..4, a1 = LOG.
| If the byte changed since last time: update the shadow, append a ring record
| {previous opcode, index, old, new}, and bump the culprit histogram.
| clobbers d0, d2..d7, a0
| ----------------------------------------------------------------------------
.Lchk:
    clr.l   %d2
    move.b  %a0@,%d2                  | current
    clr.l   %d3
    move.b  %a1@(SHADOW,%d1:l),%d3    | shadow
    cmp.l   %d2,%d3
    beq     .Lchkdone
    move.b  %d2,%a1@(SHADOW,%d1:l)    | shadow := current

    | ring slot = (count) & 7, then count++ with the 0xFF-is-fresh convention
    clr.l   %d4
    move.b  %a1@(NCHG),%d4
    addq.l  #1,%d4
    and.l   #0xff,%d4
    bne     .Lchk1
    moveq   #1,%d4
    bra     .Lchk2
.Lchk1:
    move.l  %d4,%d5
    addq.l  #1,%d5
    and.l   #0xff,%d5
    bne     .Lchk2
    moveq   #-2,%d4
    and.l   #0xff,%d4
.Lchk2:
    move.b  %d4,%a1@(NCHG)
    subq.l  #1,%d4
    and.l   #7,%d4
    lsl.l   #2,%d4
    lea     %a1@(CHGRING),%a0
    adda.l  %d4,%a0
    clr.l   %d5
    move.b  %a1@(PREVOP),%d5
    move.b  %d5,%a0@(0)               | the opcode whose handler did it
    move.b  %d1,%a0@(1)               | which watched byte
    move.b  %d3,%a0@(2)               | old
    move.b  %d2,%a0@(3)               | new

    | culprit histogram, indexed by that opcode
    tst.l   %d5
    beq     .Lchkdone
    move.l  %d5,%d6
    sub.l   #79,%d6
    bpl     .Lchkdone
    lea     %a1@(CULPRIT),%a0
    adda.l  %d5,%a0
    bsr     .Lbump
.Lchkdone:
    rts

| ============================================================================
| caveB -- on FUN_40042158's stored-p-lock bitmap update (detour 0x400426fc, 6 B)
| entry: a0 = bitmap base (0x46c7d48c audio / 0x46c7d2e4 MIDI), d0 = 1<<track, d3 = step
| exit : must leave d0 = the value stock's own store at 0x40042702 writes back
| ============================================================================
    .global caveB
caveB:
    lea     %sp@(-48),%sp
    moveml  %d0-%d7/%a0-%a3,%sp@
    movea.l #LOG,%a3

    | .Lbump takes its address in a0, which is ALSO the live bitmap base every guard
    | below reads -- stash it across the call. (Caught in the emulator: without this,
    | every call rejected at guard 1 because a0 no longer looked like 0x46c7d48c.)
    movea.l %a0,%a1
    lea     %a3@(8),%a0
    bsr     .Lbump                    | cave entry count
    movea.l %a1,%a0

    | ---- snapshot, only for a call that actually stored the 0xFF sentinel ----
    clr.l   %d4
    move.b  %fp@(19),%d4
    addq.l  #1,%d4
    and.l   #0xff,%d4
    bne     .Bnosnap
    clr.l   %d4
    move.b  %fp@(11),%d4
    move.b  %d4,%a3@(10)              | track
    clr.l   %d4
    move.b  %fp@(19),%d4
    move.b  %d4,%a3@(11)              | value
    clr.l   %d4
    move.b  %fp@(-4),%d4
    move.b  %d4,%a3@(12)              | bank
    clr.l   %d4
    move.b  %fp@(-3),%d4
    move.b  %d4,%a3@(13)              | pattern
    move.b  %d3,%a3@(14)              | step
    move.l  %a0,%d4
    move.b  %d4,%a3@(15)              | bitmap base low byte
    clr.l   %d4
    move.b  %a0@(0,%d3:l),%d4
    move.b  %d4,%a3@(16)              | PRE-update bitmap byte
    move.b  %d0,%a3@(17)              | 1 << track
.Bnosnap:

    | ================= the fix itself, unchanged =================
    move.l  %a0,%d4
    sub.l   #STORED_BITMAP,%d4
    beq     .Bg2
    moveq   #1,%d5
    bra     .Bfail
.Bg2:
    clr.l   %d5
    move.b  %a0@(0,%d3:l),%d5
    and.l   %d0,%d5
    bne     .Bg3
    moveq   #2,%d5
    bra     .Bfail
.Bg3:
    clr.l   %d4
    move.b  %fp@(19),%d4
    addq.l  #1,%d4
    and.l   #0xff,%d4
    beq     .Bg4
    moveq   #3,%d5
    bra     .Bfail
.Bg4:
    clr.l   %d0
    move.b  %fp@(11),%d0
    clr.l   %d1
    move.b  %fp@(-3),%d1
    clr.l   %d2
    move.b  %fp@(-4),%d2
    clr.l   %d3
    move.b  %fp@(-2),%d3

    move.l  %d2,%d4
    move.l  #BANK_STRIDE,%d5
    muls.l  %d5,%d4
    move.l  %d1,%d5
    move.l  #PAT_STRIDE,%d6
    muls.l  %d6,%d5
    add.l   %d5,%d4
    move.l  %d0,%d5
    move.l  #TRK_STRIDE,%d6
    muls.l  %d6,%d5
    add.l   %d5,%d4
    add.l   #BLOB_ABS,%d4
    movea.l %d4,%a1

    lea     %a1@(PLOCK_OFF),%a0
    move.l  %d3,%d4
    lsl.l   #5,%d4
    adda.l  %d4,%a0
    moveq   #8,%d4
.Brow:
    move.l  %a0@+,%d5
    addq.l  #1,%d5
    bne     .Browbad
    subq.l  #1,%d4
    bne     .Brow
    bra     .Bg5
.Browbad:
    moveq   #4,%d5
    bra     .Bfail
.Bg5:
    move.l  %d3,%d4
    lsr.l   #3,%d4
    moveq   #7,%d7
    sub.l   %d4,%d7
    move.l  %d3,%d4
    and.l   #7,%d4
    moveq   #1,%d6
    lsl.l   %d4,%d6
    movea.l %a1,%a2
    adda.l  %d7,%a2

    clr.l   %d4
    move.b  %a2@(0x00),%d4
    and.l   %d6,%d4
    bne     .Btrig
    clr.l   %d4
    move.b  %a2@(0x08),%d4
    and.l   %d6,%d4
    bne     .Btrig
    clr.l   %d4
    move.b  %a2@(0x18),%d4
    and.l   %d6,%d4
    bne     .Btrig
    clr.l   %d4
    move.b  %a2@(0x20),%d4
    and.l   %d6,%d4
    bne     .Btrig
    clr.l   %d4
    move.b  %a2@(0x28),%d4
    and.l   %d6,%d4
    bne     .Btrig
    clr.l   %d4
    move.b  %a2@(0x30),%d4
    and.l   %d6,%d4
    beq     .Bg6
.Btrig:
    moveq   #5,%d5
    bra     .Bfail
.Bg6:
    clr.l   %d4
    move.b  %a2@(TYPE_FLAG_OFF),%d4
    and.l   %d6,%d4
    bne     .Bdo
    moveq   #6,%d5
    bra     .Bfail

.Bdo:
    clr.l   %d4
    move.b  %a2@(TYPE_FLAG_OFF),%d4
    eor.l   %d6,%d4
    move.b  %d4,%a2@(TYPE_FLAG_OFF)

    clr.l   %d4
    move.b  CUR_BANK,%d4
    cmp.l   %d2,%d4
    bne     .Bok
    clr.l   %d4
    move.b  CUR_PATTERN,%d4
    cmp.l   %d1,%d4
    bne     .Bok
    move.l  %d1,%d4
    move.l  #PAT_STRIDE,%d5
    muls.l  %d5,%d4
    move.l  %d0,%d5
    move.l  #TRK_STRIDE,%d3
    muls.l  %d3,%d5
    add.l   %d5,%d4
    add.l   #MIRROR_BASE,%d4
    movea.l %d4,%a2
    adda.l  %d7,%a2
    clr.l   %d4
    move.b  %a2@,%d4
    and.l   %d6,%d4
    beq     .Bok
    clr.l   %d4
    move.b  %a2@,%d4
    eor.l   %d6,%d4
    move.b  %d4,%a2@

.Bok:
    moveq   #7,%d5
    bsr     .Brec
    moveml  %sp@,%d0-%d7/%a0-%a3
    lea     %sp@(48),%sp
    move.b  %a0@(0,%d3:l),%d1
    not.l   %d0
    and.l   %d1,%d0
    rts

.Bfail:
    bsr     .Brec
    moveml  %sp@,%d0-%d7/%a0-%a3
    lea     %sp@(48),%sp
    move.b  %a0@(0,%d3:l),%d1
    or.l    %d1,%d0
    rts

| record reason d5 (a3 = LOG); clobbers d4, d6, d7, a0
.Brec:
    move.b  %d5,%a3@(9)
    lea     %a3@(18),%a0
    adda.l  %d5,%a0
    bsr     .Lbump
    rts

| ============================================================================
| .Lbump -- saturating byte counter at (a0). 0xFF (fresh) -> 1, 0xFE stays 0xFE.
| clobbers d6, d7, and CONSUMES a0 -- callers that still need a0 must stash it.
| ============================================================================
.Lbump:
    clr.l   %d6
    move.b  %a0@,%d6
    addq.l  #1,%d6
    and.l   #0xff,%d6
    bne     .Lb1
    moveq   #1,%d6                    | was 0xFF -- first ever
    bra     .Lb2
.Lb1:
    move.l  %d6,%d7
    addq.l  #1,%d7
    and.l   #0xff,%d7
    bne     .Lb2
    moveq   #-2,%d6
    and.l   #0xff,%d6                 | was 0xFE -- pin
.Lb2:
    move.b  %d6,%a0@
    rts
